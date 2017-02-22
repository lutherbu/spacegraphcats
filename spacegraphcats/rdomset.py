from collections import defaultdict
import itertools
from spacegraphcats.graph import DictGraph

def low_degree_orientation(graph, comp=None):
    """ 
    Computes a low-in-degree orientation of a graph component in place
    by iteratively removing a vertex of mimimum degree and orienting
    the edges towards it. 
    Precondition:  every edge in the component has a corresponding arc in the
    anti-parallel direction (i.e. uv and vu are in the graph)
    """
    # number of vertices (needed for print statements)
    if comp is None:
        n = len(graph)
    else:
        n = len(comp)
    # most elegant way to handle possibly empty graph (from the frat graph in )
    if n == 0:
        return
    """
    compute necessary data structures for low degree orientation
    """
    # array binning the vertices by remaining degree
    (bins, 
    # pointers to the first vertex with a given degree
    bin_starts, 
    # remaining degree of the vertex
    degrees, 
    # pointer to the location of a vertex in bins
    location) = ldo_setup(graph,comp)

    checkpoint = 0
    max_d = 0
    # run the loop once per vertex
    for curr in range(n):
        # curr points the vertex of minimum degree
        v = bins[curr]
        d_v = degrees[v]
        # "move" v into bin 0 if it isn't there
        if d_v > 0:
            for i in range(d_v,0,-1):
                bin_starts[i] += 1
        degrees[v] = 0
        # decrement the degrees of the in neighbors not yet removed and orient
        # edges towards in neighbors already removed
        inbrs = list(graph.in_neighbors(v,1))
        for u in inbrs:
            d_u = degrees[u]
            loc_u = location[u]
            # if we've removed u, we orient the arc towards u by deleting uv
            if location[u] < location[v]:
                graph.remove_arc(u,v)
            # otherwise, the effective degree of u should drop by 1
            else:
                # swap u with w, the first vertex with the same degree
                # find where w is
                loc_w = bin_starts[d_u]
                w = bins[loc_w]
                # swap their positions
                if w != u:
                    bins[loc_u] = w
                    bins[loc_w] = u
                    location[w] = loc_u
                    location[u] = loc_w
                # move the bin start one place over
                bin_starts[d_u] += 1
                # decrement u's degree
                degrees[u] = d_u - 1         
        if curr == checkpoint:
            print("removed {} of {} nodes\r".format(curr+1, n),end="")
            checkpoint += n//100
    print("removed {} of {} nodes".format(curr+1, n))

def ldo_setup(graph, comp):
    # if a list of nodes in a component is supplied, we loop over that,
    # otherwise we loop over all nodes in the graph.

    # allows us to iterate over comp in all cases
    if comp is None:
        comp = graph
    n = len(comp)

    # hack-y way to know whether our location and degree lookups should be lists or 
    # dictionaries
    if len(comp) < len(graph) or isinstance(graph, DictGraph):
        # degree lookup
        degrees = {v:graph.in_degree(v) for v in comp}
        # pointer to place in vertex ordering
        location = {v:None for v in comp}
        max_deg = max(degrees.values())

    else:
        degrees = [graph.in_degree(v) for v in comp]
        location = [None for _ in comp]
        max_deg = max(degrees)

    # precompute the degrees of each vertex and make a bidirectional lookup
    degree_counts = [0 for i in range(max_deg+1)]
    for v in comp:
        d = degrees[v]
        degree_counts[d] += 1
    # assign the cutoffs of bins
    bin_starts = [sum(degree_counts[:i]) for i in range(max_deg+1)]
    del degree_counts
    bin_ptrs = list(bin_starts)
    bins = [None for _ in comp]

    # assign the vertices to bins
    checkpoint = 0
    for i,v in enumerate(comp):
        loc = bin_ptrs[degrees[v]]
        bins[loc] = v
        location[v] = loc
        bin_ptrs[degrees[v]] += 1
        if v == checkpoint:
            print("bucketed {} of {} nodes\r".format(i+1, n),end="")
            checkpoint += n//100
    del bin_ptrs
    print("bucketed {} of {} nodes".format(i+1, n))
    return bins, bin_starts, degrees, location

def dtf_step(graph, dist, comp=None):
    """ 
    Computes the d-th dtf-augmentation from a graph 
    (where d is provided by the argument dist). The input graph
    must be a (d-1)-th dtf-augmentation. See dtf() for usage. 
    This function adds arcs to graph.
    """

    fratGraph = DictGraph() # Records fraternal edges, must be oriented at the end

    # if a list of nodes in a component is supplied, we loop over that,
    # otherwise we loop over all nodes in the graph.
    if comp is None:
        nodes = range(len(graph))
    else:
        nodes = comp

    trans_pairs = 0
    # pick out the transitive pairs from v and add them as new edges
    for v in nodes:
        for x, y in graph.transitive_pairs(v, dist):
            graph.add_arc(x,y, dist)
            trans_pairs += 1
    print("added {} transitive edges".format(trans_pairs))
    # pick out the fraternal pairs from v and store them.  We do this after adding 
    # transitive edges to guarantee that no fraternal edge conflicts with a transitive 
    # edge
    for v in nodes:
        for x, y in graph.fraternal_pairs(v, dist):
            #assert x != y
            fratGraph.add_node(x)
            fratGraph.add_node(y)
            fratGraph.add_arc(x, y)
            fratGraph.add_arc(y, x)
    print("added {} fraternal edges".format(fratGraph.num_arcs()//2))

    # Orient fraternal edges and add them to the graph
    low_degree_orientation(fratGraph)

    for s, t in fratGraph.arcs(1):
        #assert s != t
        graph.add_arc(s,t,dist)

def dtf(graph, radius, comp=None):
    """
    Computes dft-augmentations of a graph.  The number of augmentations is
    given by the argument radius.
    Postcondition:
        If the distance between each pair of vertices u,v is at most radius in
        the original graph, uv or vu will be an arc with weight equal to that
        distance.
    """
    # the 1st "augmentation" is simply acyclically orienting the edges
    print("Computing low degree orientation (step 1)")
    low_degree_orientation(graph ,comp=comp)

    # keep track of whether we are adding edges so we can quit early
    #num_arcs = graph.num_arcs()
    changed = True
    d = 2
    while changed and d <= radius:
        print("Computing step {}".format(d))
        # shortcut paths of length d
        dtf_step(graph, d, comp)

        # Small optimization: if no new arcs have been added we can stop.
        #curr_arcs = graph.num_arcs() # This costs a bit so we store it
        #changed = num_arcs < curr_arcs
        #num_arcs = curr_arcs
        d += 1

def compute_domset(graph,radius,comp=None):
    """ Compute a d-dominating set using Dvorak's approximation algorithm 
        for dtf-graphs (see `Structural Sparseness and Complex Networks').
        graph needs a distance-d dtf augmentation (see rdomset() for usage). """    
    domset = set()
    infinity = float('inf')
    # minimum distance to a dominating vertex, obviously infinite at start
    domdistance = defaultdict(lambda: infinity)

    # if a list of nodes in a component is supplied, we loop over that,
    # otherwise we loop over all nodes in the graph.
    if comp is None:
        nodes = graph
    else:
        nodes = comp

    # Sort the vertices by indegree so we take fewer vertices
    order = sorted([v for v in nodes],key=lambda x:graph.in_degree(x))
    # vprops = [(v,graph.in_degree(v)) for v in nodes]
    # vprops.sort(key=itemgetter(1),reverse=False)
    # order = map(itemgetter(0),vprops)

    for v in order:
        # if v is already dominated at radius, no need to work
        if domdistance[v] <= radius:
            continue

        # look at the in neighbors to update the distance
        for u,r in graph.in_neighbors(v):
            domdistance[v] = min(domdistance[v],r+domdistance[u])

        # if v is dominated at radius now, keep going
        if domdistance[v] <= radius:
            continue
        # otherwise put v in the dominating set
        domset.add(v)
        domdistance[v] = 0

        # update distances of neighbors of v if v is closer
        for u,r in graph.in_neighbors(v):
            domdistance[u] = min(domdistance[u],r)

    return domset

def assign_to_dominators(graph, domset, radius,comp=None):
    """
    Computes for each vertex the subset of domset that dominates it at distance radius
    Returns a double level dictionary that maps vertices in the original graph to
    integers 0 to radius to sets of vertices that dominate at that distance
    """
    dominated_at_radius = defaultdict(lambda: defaultdict(set))

    if comp is None:
        nodes = graph
    else:
        nodes = comp

    # Every vertex in domset is a zero-dominator of itself
    for v in domset:
        dominated_at_radius[v][0].add(v)

    # We need two passes in order to only every access the
    # in-neighbourhoods (which are guaranteed to be small).
    for _ in range(2):
        for v in nodes:
            # Pull dominators from in-neighbourhood
            for u, r in graph.in_neighbors(v):
                for r2 in dominated_at_radius[u].keys():
                    domdist = r+r2
                    if domdist <= radius:
                        dominated_at_radius[v][domdist] |= dominated_at_radius[u][r2]
            # Push dominators to in-neighbourhood
            for u, r in graph.in_neighbors(v):
                for r2 in dominated_at_radius[v].keys():
                    domdist = r+r2
                    if domdist <= radius:
                        dominated_at_radius[u][domdist] |= dominated_at_radius[v][r2]

    # Clean up: vertices might appear at multiple distances as dominators,
    # we only want to store them for the _minimum_ distance at which they
    # act as a dominator.
    for v in dominated_at_radius:
        cumulated = set()
        for r in range(radius+1):
            dominated_at_radius[v][r] -= cumulated
            cumulated |= dominated_at_radius[v][r]

    return dominated_at_radius

def domination_graph(graph, domset, radius, comp=None):
    """ 
        Builds up a 'domination graph' by assigning each vertex to 
        its closest dominators. These dominators will be connected in the
        final graph.
        Precondition:
            The keys of dominated_at_radius are exactly one connected 
            component of graph
    """
    print("assigning to dominators")
    dominated_at_radius = assign_to_dominators(graph, domset, radius, comp)
    domgraph = DictGraph(nodes=domset)

    print("computing dominating edges")
    # dictionary mapping vertices from the graph to closest dominators to it
    closest_dominators = {v:list() for v in dominated_at_radius}
    # the keys of dominators should all belong to the same component, so this
    # should implicitly only operate on the vertices we care about
    for v in dominated_at_radius:
        # Find the domset vertices closest to v
        sorted_doms = [dominated_at_radius[v][r] for r in range(radius+1) if len(dominated_at_radius[v][r])>0]
        # sorted_doms[0] contains the closest dominators (we don't care about 
        # what radius it is at)
        closest = sorted_doms[0]
        # Assign each of those closest dominating nodes to v
        for x in closest:
            closest_dominators[v].append(x)
        # all closest dominating nodes should form a clique, since they 
        # optimally dominate a common vertex (namely, v)
        for x,y in itertools.combinations(closest,2):
            domgraph.add_arc(x,y)
            domgraph.add_arc(y,x)
    # all adjacent vertices in the dominating set should also be adjacent in 
    # the dominating graph.  If two dominators are adjacent, they probably 
    # optimally a common vertex and are already connected anyway, but we want 
    # to make sure we get all of them
    for v in domset:
        adj_doms = dominated_at_radius[v][1]
        for u in adj_doms:
            domgraph.add_arc(u,v)
            domgraph.add_arc(v,u)

    print("Make the domset connected")
    # ensure domgraph is connected
    make_connected(domgraph, domset, closest_dominators, graph)

    return domgraph, closest_dominators

def make_connected(domgraph, domset, closest_dominators, graph):
    """
    Makes a domination graph connected.  If it isn't already connected, we 
    need to start adding edges between components that have vertices u and v 
    respectively such that uv is an edge in graph.  Note that this will only 
    occur if u and v are optimally dominated by x and y respectively at the 
    same distance.
    """
    # map vertices to indices of components
    print("\tComputing components")
    dom_components = domgraph.component_index()
    num_comps = len(set([dom_components[v] for v in domset]))
    # don't do anything it it's already connected!
    if num_comps == 1:
        return
    # find the components the non-dominating vertices' dominators belong to
    print("\tComputing components for nondominators")
    nondom_components = {}
    for u in closest_dominators.keys():
        # since all of u's dominators are in the same component, we can pick 
        # an arbitrary one to look up
        nondom_components[u] = dom_components[closest_dominators[u][0]]

    print("\tfinding arcs that bridge components")
    # look at arcs in graph and determine whether they bridge components
    for u in closest_dominators.keys():
        # the domset vertices optimally dominate their neighbors, so they 
        # can't help us merge components
        if u in domset:
            continue
        for v in graph.in_neighbors(u,1):
            # if this edge bridges components, connect all the optimal 
            # dominators
            if nondom_components[u] != nondom_components[v]:
                for x in closest_dominators[u]:
                    for y in closest_dominators[v]:
                        domgraph.add_arc(x,y)
                        domgraph.add_arc(y,x)

def rdomset(graph, radius, comp=None):
    dtf(graph, radius, comp)
    domset = compute_domset(graph, radius, comp)
    return domset


