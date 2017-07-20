"""Data structure for CAtlas."""

import argparse
import cProfile
import os
import sys
import tempfile
import gzip
from .rdomset import rdomset, domination_graph
from .graph_io import read_from_gxt, write_to_gxt
from .graph import Graph
from .logging import log
from io import TextIOWrapper
from collections import defaultdict
from typing import List, Dict, Set


class Project(object):
    """Methods for coordinating whole projects."""

    def __init__(self, directory, r, checkpoint=True):
        """
        Make a project in directory at raidus r.

        This object stores the intermediate variables for the CAtlas building
        so that they can be checkpointed as necessary.
        """
        self.dir = directory
        self.r = r
        self.checkpoint = checkpoint
        self.graph = None
        self.level_nodes = None
        self.idx = 0
        self.level = 0

        # project file names
        self.domfilename = os.path.join(self.dir, "first_doms.txt")
        self.graphfilename = os.path.join(self.dir, "cdbg.gxt")
        self.catlasfilename = os.path.join(self.dir, "catlas.csv")

    def existing_checkpoints(self):
        """Get the existing checkpoint files."""
        files = []
        for f in os.listdir(self.dir):
            name, ext = os.path.splitext(f)
            if ext == ".checkpoint":
                r, level = map(int, name.split("_"))
                if r == self.r:
                    files.append(level)

        return list(sorted(files))

    def cp_name(self, level):
        """Return the name of the checkpoint file after level level."""
        return os.path.join(self.dir,
                            "{}_{}.checkpoint".format(self.r, level))

    def load_furthest_checkpoint(self):
        """Load the checkpoint that is furthest along."""
        existing = self.existing_checkpoints()
        # if there are no checkpoints or we don't want to load from one,
        # just read G from the graph file
        if len(existing) == 0 or not self.checkpoint:
            print("Loading graph from {}".format(self.graphfilename))
            # we only need to set the graph variable since index, level, and
            # previous nodes have the proper values by default
            with open(self.graphfilename, 'r') as graph_file:
                self.graph = read_from_gxt(graph_file, self.r, False)
        else:
            self.load_checkpoint(existing[-1])

    def load_checkpoint(self, level):
        """Read cached information from a partial catlas computation."""
        if not self.checkpoint:
            raise IOError("I told you I didn't want to load from checkpoint!")
        print("Loading results of building level {}".format(level))
        # the temp file contains catlas and graph information.  To use the
        # readers for catlas and graph, we need to temporarily split them into
        # separate files
        tmpf = tempfile.TemporaryFile(mode='r+')

        infile = self.cp_name(level)
        with gzip.open(infile, 'rt') as f:
            # read until the end of the catlas
            for line in f:
                if line == "###\n":
                    break
                tmpf.write(line)
            # once we are at the graph section, start reading from there
            self.graph = read_from_gxt(f, radius=1, directed=False,
                                       sequential=False)
            # move back to the beginning of the temporary file and read the
            # catlas
            tmpf.seek(0)
            root = CAtlas.read(tmpf)
            tmpf.close()
            # print("Root has children {}".format(
            #         [i.vertex for i in root.children]))
            self.level_nodes = {node.vertex: node for node in root.children}
            self.idx = root.idx
            self.level = root.level
            # if the graph has isolated vertices, they don't appear in the
            # edge list, which means we need to infer them from the catlas
            # nodes
            self.__handle_missing_nodes()

    def __handle_missing_nodes(self):
        # sanity check that the catlas nodes and graph vertices correspond
        num_missing = len(self.level_nodes.keys()) - len(self.graph.nodes)
        if num_missing > 0:
            missing = set(self.level_nodes.keys()) - set(self.graph.nodes)
            # they are not equal when there are isolated vertices, which
            # cannot be represented in the edge list file format.  We need
            # to make sure that these vertices are indeed isolated by
            # checking that they are not dominated by multiple vertices.
            if self.level == 1:
                # at level 1, the domination relationship is not captured by
                # the children so we just assume the vertices are isolated.
                #  We could check first_doms.txt but this is probably too much
                # effort.
                for v in missing:
                    self.graph.add_node(v)
            else:
                parent_count = defaultdict(int)
                for _, node in self.level_nodes.items():
                    for u in node.children:
                        parent_count[u.vertex] += 1
                for v in missing:
                    if parent_count[v] != 1:
                        print("{} has {} parents".format(v, parent_count[v]))
                        raise ValueError("graph should have the same nodes as"
                                         " the previous level")
                    else:
                        self.graph.add_node(v)

    def _save(self):
        """Method used by the thread to write out."""
        outfile = self.cp_name(self.level)
        print("Writing to file {}".format(outfile))
        with gzip.open(outfile, 'wt') as f:
            # make a dummy root to write the catlas using catlas.write method
            root = CAtlas(self.idx, 0, self.level, self.level_nodes.values())
            root.write(f)
            f.write("###\n")
            write_to_gxt(f, self.graph)

    def save_checkpoint(self):
        """Write out a partial computation."""
        if not self.checkpoint:
            return
        else:
            self._save()


class CAtlas(object):
    """Hierarchical atlas for querying graphs."""

    LEVEL_THRESHOLD = 10

    def __init__(self, idx, vertex, level, children):
        """
        Construct a CAtlas node.

        Arguments:
            idx:  Integer identifier of the node.  A CAtlas with n nodes will
                  have ids 0,1,...,n-1
            vertex:  Name of vertex in the cDBG
            level:  The height of the node in the hierarchy.  The leaves are at
                    level 0, their parents at level 1, etc.
            children:  the CAtlas nodes for which this is a parent
        """
        self.idx = idx
        self.vertex = vertex
        self.children = children
        self.level = level

    @staticmethod
    def build(proj):
        """Build a CAtlas at a given radius."""
        # keep creating progressively smaller graphs until we hit the level
        # threshold or steady state
        while True:
            # the base level should have a large radius, others are just 1
            if proj.level == 0:
                r = proj.r
            else:
                r = 1
            # build the current level
            nodes, domgraph, dominated = CAtlas._build_level(proj.graph,
                                                             r,
                                                             proj.level,
                                                             proj.idx,
                                                             proj.level_nodes)

            print("Catlas level {} complete".format(proj.level))

            # at the bottom level we need to write out the domination
            # assignment
            if proj.level == 0:
                with open(proj.domfilename, 'w') as domfile:
                    for v, shadow in dominated.items():
                        domstr = str(v)
                        for u in shadow:
                            domstr += " {}".format(u)
                        domstr += "\n"
                        domfile.write(domstr)

            # increment the index and level now so they are correctly adjusted
            # if we happen to return
            proj.idx += len(nodes)
            proj.level += 1

            # quit if our level is sufficiently small
            if len(domgraph) <= CAtlas.LEVEL_THRESHOLD or \
                    len(domgraph) == len(proj.graph):
                break

            # prep for the next iteration
            proj.graph = domgraph
            proj.level_nodes = nodes

            # write level results to the checkpoint file if applicable
            proj.save_checkpoint()
            print(len(proj.graph))

        # create a single root over the top level
        root_children = list(nodes.values())
        root_vertex = root_children[0].vertex
        return CAtlas(proj.idx, root_vertex, proj.level, root_children)

    @staticmethod
    def _build_level(graph: Graph, radius: int, level: int, min_id: int=0,
                     prev_nodes: List[int]=None):
        # find the domgraph of the current domgraph
        domset = rdomset(graph, radius)
        domgraph, closest_dominators = domination_graph(graph, domset, radius)

        # closest_dominators indicates the domset vertices that dominate
        # each vertex.
        # v dominating u indicates that u will be a child of v
        # we have the assignment from vertices to dominators, make the
        # reverse
        dominated = {v: list() for v in domset}  # type: Dict[int, List[int]]
        for u, doms in closest_dominators.items():
            for v in doms:
                dominated[v].append(u)

        # create the CAtlas nodes
        nodes = {}
        for idx, v in enumerate(domset):
            # if no previous nodes were supplied, we assume we are on the
            # bottom level and thus the children field is empty
            if prev_nodes is None:
                children = []  # type: List[int]
            else:
                children = [prev_nodes[u] for u in dominated[v]]
            nodes[v] = CAtlas(min_id+idx, v, level, children)

        return nodes, domgraph, dominated

    def leaves(self, visited: Set[object]=None) -> Set[object]:
        """Find the descendants of this node with no children."""
        # this function is recursive so we need to keep track of nodes we
        # already visited
        if visited is None:
            visited = set([self])
        # base case is level 0
        if self.level == 0:
            return set([self])
        # otherwise gather the leaves of the children
        res = set()  # type: Set[object]
        for c in self.children:
            if c not in visited:
                visited.add(c)
                res |= c.leaves(visited)
        return res

    def write(self, outfile: TextIOWrapper):
        """Write the connectivity of the CAtlas to file."""
        # doesn't matter how we traverse the graph, so we use DFS for ease of
        # implementation
        stack = [self]
        seen = set()
        while len(stack) > 0:
            # remove from the stack
            curr = stack.pop()
            # write node information
            child_str = " ".join(str(child.idx) for child in curr.children)
            outfile.write("{},{},{},{}\n".format(curr.idx,
                                                 curr.vertex,
                                                 curr.level,
                                                 child_str))
            # all nodes already seen don't get re-added
            seen.add(curr)
            stack.extend(filter(lambda x: x not in seen, curr.children))

    @classmethod
    def read(cls, catlas_file):
        """Load the catlas Directed Acyclic Graph."""
        children = []
        nodes = []

        # load everything from the catlas file
        for line in catlas_file:
            catlas_node, cdbg_node, level, beneath = line.strip().split(',')

            level = int(level)
            catlas_node = int(catlas_node)
            cdbg_node = int(cdbg_node)

            # extend arrays as necessary
            if len(children) <= catlas_node:
                for i in range(catlas_node - len(children) + 1):
                    children.append([])
                    nodes.append(None)

            # parse out the children
            beneath = beneath.strip()
            if beneath:
                beneath = beneath.split(' ')
                children[catlas_node].extend(map(int, beneath))

            # make the new node with empty children
            node = cls(catlas_node, cdbg_node, level, [])
            nodes[catlas_node] = node

        # update the nodes with pointers to their children
        for i, n in enumerate(nodes):
            for child in children[n.idx]:
                n.children.append(nodes[child])

        return nodes[-1]


def main(args):
    """Build a CAtlas for the provided input graph."""
    # unpack command line arguments
    r = args.radius
    proj_dir = args.project
    checkpoint = not args.no_checkpoint
    level = args.level

    # make checkpoint
    proj = Project(proj_dir, r, checkpoint)

    print("reading graph")
    if level:
        proj.load(level)
    else:
        proj.load_furthest_checkpoint()

    print("reading complete")
    print("building catlas")
    cat = CAtlas.build(proj)
    print("catlas built")
    print("writing graph")
    with open(proj.catlasfilename, 'w') as cfile:
        cat.write(cfile)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", help="Project directory",
                        type=str)
    parser.add_argument("radius", help="Catlas radius", type=int)
    parser.add_argument("-n", "--no_checkpoint", action='store_true',
                        help="Do not read or write checkpoints")
    parser.add_argument("-l", "--level", type=int,
                        help="Level at which to load the checkpoint."
                        "Defaults to highest level saved when not invoked.")
    args = parser.parse_args()

    main(args)
    # prof = cProfile.Profile()
    # prof.run("main(args)")
    # prof.print_stats('tottime')
    log(args.project, sys.argv)
