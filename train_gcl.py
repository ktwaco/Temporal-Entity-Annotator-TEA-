"""Training and evaluation on Timebank_Dense data"""

from __future__ import print_function
import sys
import os
import numpy
import argparse
import glob
import pickle
import json
import torch

# from src.learning.network_mem import NetworkMem, BATCH_SIZE
# from src.learning.ntm_models import MAX_LEN
from src.learning.network_pytorch import NetworkMemPT, BATCH_SIZE
from src.learning.models_pytorch import MAX_LEN
from src.learning.models_pytorch import GCLRelation

DENSE_LABELS = True
HAS_AUX = False


def main():
    '''
    Process command line arguments and then generate trained models (One for detection of links, one for classification)
    '''

    parser = argparse.ArgumentParser()

    parser.add_argument("train_dir",
                        help="Directory containing training annotations")

    parser.add_argument("model_destination",
                        help="Where to store the trained model")

    parser.add_argument("newsreader_annotations",
                        help="Where newsreader pipeline parsed file objects go")

    parser.add_argument("--val_dir",
                        default=None,
                        help="Directory containing validation annotations")

    parser.add_argument("--load_model",
                        default=None,
                        help="load trained model")

    parser.add_argument("--epochs",
                        type=int, default=40,
                        help="epochs for training")

    parser.add_argument("--gcl",
                        action='store_true', default=False,
                        help="use gcl model")

    args = parser.parse_args()

    device = torch.device('cuda')

    # validate file paths
    if os.path.isdir(args.newsreader_annotations) is False:
        sys.exit("invalid path for time note dir")
    if os.path.isdir(args.train_dir) is False:
        sys.exit("invalid path to directory containing training data")
    if os.path.isdir(os.path.dirname(args.model_destination)) is False:
        sys.exit("directory for model destination does not exist")

    print("arguments:\n", args)

    model_destination = args.model_destination
    if not os.path.exists(model_destination):
        os.makedirs(model_destination)

    # get files in directory
    files = glob.glob(os.path.join(args.train_dir, '*'))
    gold_files = []
    tml_files = []

    for f in files:
        if "E3input" in f:
            tml_files.append(f)
        elif f.endswith('.tml'):
            gold_files.append(f)

    gold_files.sort()
    tml_files.sort()

    if args.val_dir is None:
        val_files = None
    else:
        val_files = glob.glob(os.path.join(args.val_dir, '*'))
        val_files.sort()

    notes = get_notes(gold_files, args.newsreader_annotations)
    numpy.random.shuffle(notes)

    val_notes = get_notes(val_files, args.newsreader_annotations)

    # network = NetworkMem(nb_training_files=len(notes), model_path=model_destination)
    network = NetworkMemPT(nb_training_files=len(notes), model_path=model_destination, device=device)

    print("loading word vectors...")
    if os.path.exists(model_destination + 'vocab.pt'):
        network.word_vectors = torch.load(model_destination + 'vocab.pt')
    else:
        if val_notes:
            print("found notes for training and test...")
            network.build_wordvectors(notes + val_notes)
        else:
            network.build_wordvectors(notes)

        torch.save(network.word_vectors, model_destination + 'vocab.pt')

    training_data_gen = network.generate_training_input(notes, 'all', max_len=MAX_LEN, multiple=1)

    network.get_embedding_matrix()
    val_data_gen = network.generate_test_input(val_notes, 'all', max_len=MAX_LEN, multiple=1)
    callbacks = None

    if not args.gcl:
        print("Start training pairwise model...")
        # load pairwise model (without GCL)
        if args.load_model is not None:
            model = torch.load(args.load_model)
        else:
            model = None
        model, history = network.train_model(model=model, no_ntm=True, epochs=args.epochs,
                                             input_generator=training_data_gen, val_generator=val_data_gen,
                                             callbacks=callbacks,
                                             batch_size=40, has_auxiliary=HAS_AUX)

        torch.save(model, model_destination + 'pairwise_model.pt')

    else:
        pairwise_model = torch.load(model_destination + 'pairwise_model.pt')
        gcl_model = GCLRelation(pairwise_model, nb_classes=6, gcl_size=512, controller_size=512,
                 controller_layers=1, num_heads=1, num_slots=40, m_depth=512)

        model, history = network.train_model(model=gcl_model, no_ntm=False, epochs=args.epochs,
                                             input_generator=training_data_gen, val_generator=val_data_gen,
                                             callbacks=callbacks,
                                             batch_size=40, has_auxiliary=HAS_AUX)
        torch.save(model, model_destination + 'gcl_model.pt')
    # print("Start training GCL model...")
    # # load memory model (with GCL)
    # model, history = network.train_model(model=None, no_ntm=False, epochs=10,
    #                                      input_generator=training_data_gen, val_generator=val_data_gen,
    #                                      callbacks=callbacks,
    #                                      batch_size=50, has_auxiliary=HAS_AUX)
    # json.dump(history, open(model_destination + 'training_history_pairwise.json', 'w'))
    #
    # try:
    #     model.save(model_destination + 'final_model.h5')
    # except:
    #     model.save_weights(model_destination + 'final_weights.h5')
    # json.dump(history, open(model_destination + 'training_history_final.json', 'w'))


    test_data_gen = val_data_gen


    print("Prediction with double check in one batch.")
    results = network.predict(model, test_data_gen, batch_size=0, fit_batch_size=BATCH_SIZE,
                              evaluation=True, smart=True, has_auxiliary=HAS_AUX, pruning=False)


    with open(model_destination + 'results.pkl', 'wb') as f:
        pickle.dump(results, f)


def basename(name):
    name = os.path.basename(name)
    name = name.replace('.TE3input', '')
    name = name.replace('.tml', '')
    return name


def get_notes(files, newsreader_dir):

    if not files:
        return None

    notes = []

    for i, tml in enumerate(files):
        if i % 10 == 0:
            print('processing file {}/{} {}'.format(i + 1, len(files), tml))
        assert os.path.isfile(os.path.join(newsreader_dir, basename(tml) + ".parsed.pickle"))
        tmp_note = pickle.load(open(os.path.join(newsreader_dir, basename(tml) + ".parsed.pickle"), "rb"))
        notes.append(tmp_note)
    return notes

if __name__ == "__main__":
    main()
