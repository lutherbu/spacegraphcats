#! /usr/bin/env python
import numpy
import pickle
import itertools
import sourmash_lib
import time

import hdbscan
from sklearn.manifold import TSNE


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('vectors_file')
    parser.add_argument('-o', '--output', type=argparse.FileType('wb'))
    args = parser.parse_args()

    assert args.output

    data = numpy.load(args.vectors_file)

    # load the k=31 MinHashes for identification, and the mapping between node IDs and 
    # data index.
    node_id_to_group_idx = pickle.load(open(args.vectors_file + '.node_ids', 'rb'))
    group_ident = pickle.load(open(args.vectors_file + '.node_mh', 'rb'))

    print('loaded data of shape {}'.format(str(data.shape)))

    print('running tSNE...')
    start = time.time()
    t = TSNE(n_components=2, perplexity=50).fit_transform(data)
    end = time.time()
    print('done! ({:.1f}s total)'.format(end - start))

    print('running HDBSCAN on tSNE results...')
    params = dict(min_cluster_size=15)
    start = time.time()
    h = hdbscan.HDBSCAN(**params).fit_predict(t)
    end = time.time()
    print('done! ({:.1f}s total)'.format(end - start))
    print('got {} clusters'.format(max(h) + 1))

    print('saving tSNE and HDBSCAN results to \'{}\''.format(args.output.name))

    pickle.dump((t, h), args.output)


if __name__ == '__main__':
    main()
