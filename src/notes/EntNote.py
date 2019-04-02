import os
import itertools
import sys
import re
import copy
from multiprocessing.pool import ThreadPool

from string import whitespace
from Note import Note
from TimeNote import TimeNote

from utilities.timeml_utilities import annotate_root
from utilities.timeml_utilities import annotate_text_element
from utilities.timeml_utilities import get_doctime_timex
from utilities.timeml_utilities import get_make_instances
from utilities.timeml_utilities import get_stripped_root
from utilities.timeml_utilities import get_tagged_entities
from utilities.timeml_utilities import get_text
from utilities.timeml_utilities import get_text_element
from utilities.timeml_utilities import get_text_element_from_root
from utilities.timeml_utilities import get_text_with_taggings
from utilities.timeml_utilities import get_tlinks
from utilities.timeml_utilities import set_text_element

from utilities.xml_utilities import get_raw_text
from utilities.xml_utilities import get_root
from utilities.xml_utilities import write_root_to_file

# from utilities.time_norm import get_normalized_time_expressions
from utilities.pre_processing import pre_processing

verbose = False


class EntNote(Note):

    global verbose

    def __init__(self, note_path, overwrite=False):

        print "processing file...", note_path
        self.source_file = note_path
        self.overwrite = overwrite

        _Note = Note.__init__(self, note_path, note_path)

        self.raw_text = []
        self.text = []
        self.relations = []

        # read data, save text and relations
        self.load_data()
        print "data loaded"

        # send body of document to NewsReader pipeline.
        tokenized_text, token_to_offset, sentence_features, dependency_paths, id_to_tok = \
            pre_processing.pre_process('\n'.join(self.text), note_path, overwrite=self.overwrite)

        # chunks = self.split_text(200)
        # for i, chunk in enumerate(chunks):
        #     tokenized_text, token_to_offset, sentence_features, dependency_paths, id_to_tok = \
        #         pre_processing.pre_process('\n'.join(self.text), note_path+str(i), overwrite=self.overwrite)
        #
        #     self.pre_processed_text.update(tokenized_text)
        #     self.token_to_offset.update(token_to_offset)
        #     self.sentence_features.update(sentence_features)
        #     self.dependency_paths.update(dependency_paths)
        #     self.id_to_tok.update(id_to_tok)

        # {sentence_num: [{token},...], ...}
        self.pre_processed_text = tokenized_text

        # contains the char based offsets generated by tokenizer, used for asserting char offsets are correct
        # {'token':[(start, end),...],...}
        self.token_to_offset = token_to_offset

        # contains sentence level information extracted by newsreader
        self.sentence_features = sentence_features

        # dependency paths for sentences in the document
        self.dependency_paths = dependency_paths

        # map token ids to tokens within self.tokenized_text
        # {'wid':'token'}
        self.id_to_tok = id_to_tok

        self.discourse_connectives = {}

        self.iob_labels = []
        self.semLinks = []

        # get list of [{'entity_id': 10002, 'entity_label': 'Component-Whole(e2,e1)', 'entity_type': 'e2'}, ...]
        self.get_labels()

        """
        print "\n\nself.original_text:\n\n"
        print self.original_text
        print "\n\n"

        print "self.pre_processed_text:\n\n"
        print tokenized_text
        print "\n\n"

        print "self.token_to_offset:\n\n"
        print self.token_to_offset
        print "\n\n"

        print "self.sentence_features:\n\n"
        print self.sentence_features
        print "\n\n"
        """

    def load_data(self):
        with open(self.source_file) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                if '\t' in line:
                    num, sentence = line.split('\t')
                    sentence = sentence.strip().strip('"')
                    self.raw_text.append(sentence)
                    sentence = re.sub('</?e[12]>', '', sentence) # remove tags
                    if num.isdigit():
                        self.text.append(sentence)

                elif 'Comment' == line[0:7]: continue
                elif len(line) > 1:
                    self.relations.append(line.strip())

    def split_text(self, n):
        """Returns a list of chunks. Each chunk has n sentences"""
        if len(self.text) <= n:
            return ['\n'.join(self.text)]
        output = []
        for i in xrange(0, len(self.text)/n-1):
            chunk = self.text[i*n: (i+1)*n]
            output.append('\n'.join(chunk))
        output.append('\n'.join(self.text[(i+1)*n:]))
        return output

    def get_labels(self):
        #match_e1 = re.search('<e1>(.+)</e1>', s)
        #match_e2 = re.search('<e2>(.+)</e2>', s)

        tag_symbols = ('<', 'e1', 'e2', '/e1', '/e1', '>')

        # get tokens with tags. '<', '/e1', '>' are separate tokens this way
        tokenized_text, token_to_offset, sentence_features, dependency_paths, id_to_tok \
            = pre_processing.pre_process('\n'.join(self.raw_text), self.source_file+'.tagged', overwrite=self.overwrite)

        mismatch = 0
        for sent_num, tokens in tokenized_text.items(): #iterate over sentences
            if verbose:
                print sent_num, "last three tokens", ' '.join([x['token'] for x in tokens[-3:]])

            un_tagged_tokens = self.pre_processed_text[sent_num]
            raw_sentence = [x['token'] for x in tokenized_text[sent_num]]

            if 'e1' not in raw_sentence:
                print "Sentence without tags: ", ' '.join(raw_sentence)
                mismatch += 1
                continue

            labels_in_sent = []
            semLink = {}
            is_entity = None
            for i, token in enumerate(tokens): # iterate over tokens in a sentence
                entity = {}
                if not is_entity and token['token'] not in tag_symbols:
                    entity['entity_id'] = None
                    entity['entity_label'] = '0'
                    entity['entity_type'] = None
                    is_entity = None
                elif token['token'] in ('<', '>'):
                    continue
                elif token['token'] in ('e1', 'e2'):
                    is_entity = token['token']
                    continue
                elif token['token'] in ('/e1', '/e2'):
                    is_entity = None
                    continue
                elif is_entity:
                    entity['entity_id'] = str(sent_num) + '-' + is_entity # e.g. 10001
                    try:
                        entity['entity_label'] = self.relations[sent_num-1-mismatch]
                    except IndexError:
                        print sent_num, token
                        print ' '.join([x['token'] for x in tokens[0:i]])
                        sys.exit("list index out of range")
                    entity['entity_type'] = is_entity

                    if is_entity == 'e1':
                        try:
                            entity_e1 = un_tagged_tokens[i-3]
                        except IndexError:
                            print "Unexpected error:", sys.exc_info()[0]
                            print ' '.join([x['token'] for x in un_tagged_tokens])
                            sys.exit()
                        is_entity = None
                    if is_entity == 'e2':
                        try:
                            entity_e2 = un_tagged_tokens[i - 9]
                        except IndexError:
                            print "IndexError"
                            print sent_num, i, ' '.join([x['token'] for x in tokens])
                        semLink['src_entity'] = [entity_e1] # it must be a list for some reason
                        semLink['src_id'] = str(sent_num) + '-e1'
                        semLink['target_entity'] = [entity_e2]
                        semLink['target_id'] = str(sent_num) + '-e2'
                        semLink['rel_type'] = entity['entity_label']
                        semLink['semlink_id'] = 'l' + str(sent_num)
                        self.semLinks.append(semLink)
                        is_entity = None

                labels_in_sent.append(entity)
            self.iob_labels.append(labels_in_sent)

    def get_sentence_features(self):
        return self.sentence_features

    def get_tokenized_text(self):
        return self.pre_processed_text

    def get_discourse_connectives(self):
        return self.discourse_connectives

    def add_discourse_connectives(self, connectives):
        self.discourse_connectives.update(connectives)

    def get_timex_labels(self):
        return self.filter_label_by_type('TIMEX3')

    def get_event_labels(self):

        labels = self.filter_label_by_type("EVENT")

        for line in labels:
            for label in line:
                if label["entity_type"] != "EVENT":
                    label['entity_label'] = 'O'
                else:
                    label['entity_label'] = "EVENT"

        return labels

    def get_event_class_labels(self):
         return self.filter_label_by_type('EVENT')

    def get_rel_labels(self):
        return self.filter_label_by_type('rel')

    def filter_label_by_type(self, entity_type):
        assert entity_type in ['e1', 'e2', 'rel']

        labels = copy.deepcopy(self.get_labels())

        for line in labels:
            for label in line:

                if label["entity_type"] != entity_type:
                    label['entity_label'] = 'O' # set irrelevant entity labels to 0

        return labels

    def get_tokens(self):

        tokens = []

        for line in self.pre_processed_text:

            for token in self.pre_processed_text[line]:

                tokens.append(token)

        return tokens

    def set_iob_labels(self, iob_labels):

        # don't over write existing labels.
        assert len(self.iob_labels) == 0

        self.iob_labels = iob_labels

    def get_tlink_ids(self):

        tlink_ids = []

        for tlink in self.tlinks:

            tlink_ids.append(tlink["tlink_id"])

        return tlink_ids

    def get_semlink_labels(self):
        """ return the labels of each tlink from annotated doc """

        semlink_labels = []

        for semlink in self.semLinks:

            semlink_labels.append(semlink["rel_type"])

        return semlink_labels

    def get_tlink_id_pairs(self):

        """ returns the id pairs of two entities joined together """

        tlink_id_pairs = []

        for tlink in self.tlinks:

            tlink_id_pairs.append((tlink["src_id"], tlink["target_id"]))

        return tlink_id_pairs

    def get_token_char_offsets(self):

        """ returns the char based offsets of token.

        for each token within self.pre_processed_text iterate through list of dicts
        and for each value mapped to the key 'start_offset' and 'end_offset' create a
        list of 1-1 mappings

        Returns:
            A flat list of offsets of the token within self.pre_processed_text:

                [(0,43),...]
        """

        offsets = []

        for line_num in self.pre_processed_text:
            for token in self.pre_processed_text[line_num]:
                offsets.append((token["char_start_offset"], token["char_end_offset"]))

        return offsets

    def get_tokens_from_ids(self, ids):
        ''' returns the token associated with a specific id'''
        tokens = []
        for _id in ids:
            # ensuring id prefix value is correct.
            # TODO: adjust TimeNote to consistently use t# or w# format
            tokens.append(self.id_to_tok['w' + _id[1:]]["token"])
        return tokens

    def write(self, timexEventLabels, tlinkLabels, idPairs, offsets, tokens, output_path):
        '''
        Note::write()

        Purpose: add annotations this notes tml file and write new xml tree to a .tml file in the output folder.

        params:
            timexEventLabels: list of dictionaries of labels for timex and events.
            tlinkLabels: list labels for tlink relations
            idPairs: list of pairs of eid or tid that have a one to one correspondance with the tlinkLabels
            offsets: list of offsets tuples used to locate events and timexes specified by the label lists. Have one to one correspondance with both lists of labels.
            tokens: tokens in the note (used for tense)
            output_path: directory to write the file to
        '''
        # TODO: create output directory if it does not exist
        root = get_stripped_root(self.note_path)
        length = len(offsets)
        doc_time = get_doctime_timex(self.note_path).attrib["value"]

        # hack so events are detected in next for loop.
        for label in timexEventLabels:
            if label["entity_label"][0:2] not in ["B_","I_","O"] or label["entity_label"] in ["I_STATE", "I_ACTION"]:
                label["entity_label"] = "B_" + label["entity_label"]

        # start at back of document to preserve offsets until they are used
        for i in range(1, length+1):
            index = length - i

            if timexEventLabels[index]["entity_label"][0:2] == "B_":
                start = offsets[index][0]
                end = offsets[index][1]
                entity_tokens = tokens[index]["token"]

                #grab any IN tokens and add them to the tag text
                for j in range (1, i):

                    if(timexEventLabels[index + j]["entity_label"][0:2] == "I_"):
                        end = offsets[index + j][1]
                        entity_tokens += ' ' + tokens[index + j]["token"]
                    else:
                        break

                if timexEventLabels[index]["entity_type"] == "TIMEX3":
                    # get the time norm value of the time expression
                    # timex_value = get_normalized_time_expressions(doc_time, [entity_tokens])
                    timex_value = ''
                    # if no value was returned, set the expression to an empty string
                    # TODO: check if TimeML has a specific default value we should use here
                    if len(timex_value) != 0:
                        timex_value = timex_value[0]
                    else:
                        timex_value = ''

                   # if None in [start, end,  timexEventLabels[index]["entity_id"], timexEventLabels[index]["entity_label"][2:], timex_value]:
                   #     print "FOUND NoNE"
                   #     print [start, end,  timexEventLabels[index]["entity_id"], timexEventLabels[index]["entity_label"][2:], timex_value]
        #          #      exit()
                   # else:
                   #     print "NONE NONE"
                   #     print [start, end,  timexEventLabels[index]["entity_id"], timexEventLabels[index]["entity_label"][2:], timex_value]


                    annotated_text = annotate_text_element(root, "TIMEX3", start, end, {"tid": timexEventLabels[index]["entity_id"], "type":timexEventLabels[index]["entity_label"][2:], "value":timex_value})
                else:
                    annotated_text = annotate_text_element(root, "EVENT", start, end, {"eid": timexEventLabels[index]["entity_id"], "class":timexEventLabels[index]["entity_label"][2:]})
                    #if None in [start, end,  timexEventLabels[index]["entity_id"], timexEventLabels[index]["entity_label"][2:], timex_value]:
                    #    print "FOUND NoNE"
                    #    print [start, end,  timexEventLabels[index]["entity_id"], timexEventLabels[index]["entity_label"][2:], timex_value]
        #                exit()
                    #else:
                    #    print "NONE NONE"
                    #    print [start, end,  timexEventLabels[index]["entity_id"], timexEventLabels[index]["entity_label"][2:], timex_value]

                set_text_element(root, annotated_text)

        # make event instances
        eventDict = {}
        for i, timexEventLabel in enumerate(timexEventLabels):

            token = tokens[i]

            pos = None

            # pos
           # if token["pos_tag"] == "IN":
           #     pos = "PREPOSITION"
           # elif token["pos_tag"] in ["VB", "VBD","VBG", "VBN", "VBP", "VBZ", "RB", "RBR", "RBS"]:
           #     pos = "VERB"
           # elif token["pos_tag"] in ["NN", "NNS", "NNP", "NNPS", "PRP", "PRP$"]:
           #     pos = "NOUN"
           # elif token["pos_tag"] in ["JJ", "JJR", "JJS"]:
           #     pos = "ADJECTIVE"
           # else:
           #     pos = "OTHER"

            if timexEventLabel["entity_type"] == "EVENT":
                root = annotate_root(root, "MAKEINSTANCE", {"eventID": timexEventLabel["entity_id"], "eiid": "ei" + str(i), "tense":"NONE", "pos":"NONE"})
                eventDict[timexEventLabel["entity_id"]] = "ei" + str(i)

        # add tlinks
        for i, tlinkLabel in enumerate(tlinkLabels):

            if tlinkLabel == "None":
                continue

            annotations = {"lid": "l" + str(i), "relType": tlinkLabel}

            firstID = idPairs[i][0]
            secondID = idPairs[i][1]

            if firstID[0] == "e":
                annotations["eventInstanceID"] = eventDict[firstID]

            if firstID[0] == "t":
                annotations["timeID"] = firstID

            if secondID[0] == "e":
                annotations["relatedToEventInstance"] = eventDict[secondID]

            if secondID[0] == "t":
                annotations["relatedToTime"] = secondID

            root = annotate_root(root, "TLINK", annotations)

        note_path = os.path.join(output_path, self.note_path.split('/')[-1] + ".tml")

        print "root: ", root
        print "note_path: ", note_path

        write_root_to_file(root, note_path)

    @staticmethod
    def get_label(token, offsets):

        # NOTE: never call this directly. input is tested within _read
        tok_span = (token["char_start_offset"], token["char_end_offset"])

        label = 'O'
        entity_id = None
        entity_type = None

        for span in offsets:

            if offsets[span]["tagged_xml_element"].tag not in ["e1", "e2"]:
                print "unknown tag:", offsets[span]["tagged_xml_element"].tag
                continue

            if TimeNote.same_start_offset(span, tok_span):

                labeled_entity = offsets[span]["tagged_xml_element"]

                if 'class' in labeled_entity.attrib:
                    label = 'B_' + labeled_entity.attrib["class"]
                elif 'type' in labeled_entity.attrib:
                    label = 'B_' + labeled_entity.attrib["type"]

                if 'eid' in labeled_entity.attrib:
                    entity_id = labeled_entity.attrib["eid"]
                else:
                    entity_id = labeled_entity.attrib["tid"]

                entity_type = labeled_entity.tag

                break

            elif TimeNote.subsumes(span, tok_span):

                labeled_entity = offsets[span]["tagged_xml_element"]

                if 'class' in labeled_entity.attrib:
                    label = 'I_' + labeled_entity.attrib["class"]
                else:
                    label = 'I_' + labeled_entity.attrib["type"]

                if 'eid' in labeled_entity.attrib:
                    entity_id = labeled_entity.attrib["eid"]
                else:
                    entity_id = labeled_entity.attrib["tid"]

                entity_type = labeled_entity.tag

                break

       # if token["token"] == "expects":

       #     print
       #     print "Token span: ", tok_span
       #     print "Label found: ", label
       #     print

       #     sys.exit("found it")

        if entity_type == "EVENT":
            # don't need iob tagging just what the type is.
            # multi token events are very rare.
            label = label[2:]

        return label, entity_type, entity_id

    @staticmethod
    def same_start_offset(span1, span2):
        """
        doees span1 share the same start offset?
        """
        return span1[0] == span2[0]

    @staticmethod
    def subsumes(span1, span2):
        """
        does span1 subsume span2?
        """
        return span1[0] < span2[0] and span2[1] <= span1[1]


def __unit_tests():

    """ basic assertions to ensure output correctness """

    t =  TimeNote("APW19980219.0476.tml.TE3input", "APW19980219.0476.tml")

    for label in t.get_timex_iob_labels():
        for token in label:

            if token['entity_type'] == 'TIMEX3':
                assert token['entity_label'] != 'O'
            else:
                assert token['entity_label'] == 'O'

    for label in t.get_event_iob_labels():
        for token in label:

            if token['entity_type'] == 'EVENT':
                assert token['entity_label'] != 'O'
            else:
                assert token['entity_label'] == 'O'

    """
    number_of_tlinks = len(t.get_tlink_features())
    assert number_of_tlinks != 0
    assert len(t.get_tlink_id_pairs()) == number_of_tlinks, "{} != {}".format(len(t.get_tlink_id_pairs()), number_of_tlinks)
    assert len(t.get_tlink_labels()) == number_of_tlinks
    assert len(t.get_tlink_ids()) == number_of_tlinks
    #prin t.get_token_char_offsets()
    """

    t.get_tlink_features()

#    print t.get_iob_features()

#    print t.get_tlinked_entities()

#    print t.get_tlink_labels()

if __name__ == "__main__":

    __unit_tests()

    print "nothing to do"




