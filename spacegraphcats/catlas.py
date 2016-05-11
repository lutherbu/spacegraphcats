#!/usr/bin/python
import sys, os, argparse
from collections import deque, defaultdict
from graph import Graph
from rdomset import rdomset, calc_domination_graph, calc_dominators
from minhash import MinHash
from parser import parse_minhash

class CAtlasBuilder(object):
    def __init__(self, project):
        self.graph = project.graph
        self.domgraph = project.domgraph
        self.domset = project.domset
        self.minhashes = project.minhashes
        self.assignment = project.assignment
        self.sizes = {}
        for v in project.graph:
            self.sizes[v] = project.node_attr[v]['size']

        self.level_threshold = 10
        self.minhash_size = 1000

    def set_level_threshold(self, thres):
        self.level_threshold = thres
        return self

    def set_minhash_size(self, size):
        self.minhash_size = size
        return self        

    def _build_component_catlas(self, comp):
          # Build first level 
        curr_level = {}
        curr_domgraph = self.domgraph
        leaf_hashes = defaultdict(lambda: MinHash(self.minhash_size))
        for u in self.graph:
            # Add u's hashes to all its assigned dominators
            for v in self.assignment[u]:
                leaf_hashes[u] = leaf_hashes[u].merge(self.minhashes[v], self.minhash_size)

        for v in self.domgraph:
            curr_level[v] = CAtlas.create_leaf(v, self.sizes[v], leaf_hashes[v])

        # Build remaining levels
        level = 1 # Just for debugging
        while len(curr_level) > self.level_threshold:
            print("Computing level {}".format(level))
            domset, augg = rdomset(curr_domgraph,1)
            dominators = calc_dominators(augg, domset, 1)
            next_domgraph, domset, dominators, next_assignment = calc_domination_graph(curr_domgraph, augg, domset, dominators, 1)

            child_map = defaultdict(set)
            for u in curr_domgraph:
                for v in next_assignment[u]:
                    child_map[v].add(u)

            next_level = {}
            # Debugging stats
            maxdeg, degsum, mindeg = 0, 0, float('inf')
            for v in next_domgraph:
                children = [curr_level[u] for u in child_map[v]]
                deg = len(children)
                maxdeg, mindeg = max(maxdeg, deg), min(mindeg, deg)
                degsum += deg
                next_level[v] = CAtlas.create_node(v, children, self.minhash_size)

            curr_domgraph = next_domgraph
            curr_level = next_level
            level += 1

            print("Level {} has {} vertices".format(level-1, len(curr_level)))
            print("  min deg ist {}, max deg is {}, average is {:.2f}".format(mindeg, maxdeg, degsum/len(curr_level)))

        # Add root
        root = CAtlas.create_node('root', curr_level.values(), self.minhash_size)
        return root


    def build(self):
        comp_atlases = []
        for comp in self.domgraph.components():
            comp_atlases.append(self._build_component_catlas(comp))

        if len(comp_atlases) == 1:
            return comp_atlases[0]

        raise RuntimeError("Implement this")
      

class CAtlas(object):
    def __init__(self, id, level, size, children, minhash):
        self.id = id
        self.children = children
        self.size = size
        self.minhash = minhash
        self.level = level

    @staticmethod
    def create_leaf(id, size, minhash):
        return CAtlas(id, 0, size, [], minhash)

    @staticmethod
    def create_node(id, children, hash_size):
        assert len(children) > 0
        size = 0
        level = next(iter(children)).level
        minhash = MinHash(hash_size)
        for c in children:
            assert c.level == level
            size += c.size
            minhash = minhash.merge(c.minhash,hash_size)

        return CAtlas(id, level, size, children, minhash)

    def score(self, Q, querysize):
        minsize = 1.0*min(len(Q),len(self.minhash))
        querysize = 1.0*len(Q)
        score = len(self.minhash.intersect(Q)) / querysize
        return score

    def query(self, Q, querysize, threshold):
        res = set()
        score = self.score(Q,querysize)
        if score < threshold:
            print(score)
            return res

        if len(self.children) == 0:
            res.add(self.id)
            return res

        for c in self.children:
            res |= c.query(Q, querysize, threshold)

        return res

    def leaves(self):
        if len(self.children) == 0:
            return set([self.id])
        res = set()
        for c in self.children:
            res |= c.leaves()
        return res

    def leaves2(self):
        if len(self.children) == 0:
            return set([self])
        res = set()
        for c in self.children:
            res |= c.leaves2()
        return res


    def to_file(self, stream):
        """
            write properties to filestream stream
        """
        children_id_str = [str(c.id) for c in self.children]
        children_str = ','.join(children_id_str)
        stream.write("{};{};{};{};{}\n".format(self.id, self.level, self.size, children_str, self.minhash))
        for c in self.children:
            c.to_file(stream)

def read_minhashes(inputfile):
    res = {}

    def add_hash(v, hashes):
        res[int(v)] = MinHash.from_list(hashes)

    parse_minhash(inputfile, add_hash)
    return res

def main(inputgraph, inputhash, output, hash_size, d_bottom, d_upper, top_level_size, test):
    G,node_attrs,edge_attrs = Graph.from_gxt(inputgraph)
    hashes = read_minhashes(inputhash)

    for v in G:
        assert v in hashes, "{} has no minhash".format(v)

    G.remove_loops()
    AB = CAtlasBuilder(G, hashes, hash_size, d_bottom, d_upper, top_level_size)
    print("Input graph has size", len(G))
    catlas = AB.build_catlas()
    catlas.to_file(output)

    print("CAtlas has {} leaves".format(len(catlas.leaves())))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('inputgraph', help='gxt input file', nargs='?', type=argparse.FileType('r'),
                        default=sys.stdin)
    parser.add_argument('inputhash', help='mxt input file', nargs='?', type=argparse.FileType('r'),
                        default=sys.stdin)
    parser.add_argument('output', help='catlas output file', nargs='?', type=argparse.FileType('w'),
                        default=sys.stdout)
    parser.add_argument("hashsize", help="number of hashes to keep", type=int)
    parser.add_argument("--bottom", help="bottom level domset distance", type=int, default=10)
    parser.add_argument("--inner", help="upper levels domset distance", type=int, default=1)
    parser.add_argument("--t", help="top level size threshold", type=int, default=5)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()

    main(args.inputgraph, args.inputhash, args.output, args.hashsize, args.bottom, args.inner, args.t, args.test)

