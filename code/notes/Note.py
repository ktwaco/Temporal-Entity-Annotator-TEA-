
import os
import nltk.data

from utilities.note_utils import valid_path

class Note(object):


    def __init__(self, n_path, annotated_n_path=None, debug=False):

        self.debug = debug

        if self.debug: print "Note class: calling __init__"

        # will terminate
        self._set_note_path(n_path, annotated_n_path)


    def __del__(self):

        if self.debug: print "Note class: calling destructor"


    def _set_note_path(self, n_path, annotated_n_path):

        if self.debug: print "Note class: setting note path"

        valid_path(n_path)
        if annotated_n_path is not None:
            valid_path(annotated_n_path)
        self.note_path = n_path
        self.annotated_note_path = annotated_n_path


    def _read(self):

        return open(self.note_path, "rb").read()

    def _process(self):

        """ setenenize and tokenize text """
        pass

if __name__ == "__main__":
    print "nothing to do"


