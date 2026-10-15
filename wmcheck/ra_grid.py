"""Range-labelled two-producer support DAG: quadratic construction for fixed reads.

CO labels are prefix ranges, RF labels are one source with an implicit negative
complement. Neither vector is expanded during construction or graph queries.
The explicit original-variable output remains quadratic and is accounted for.
"""
from dataclasses import dataclass
from time import perf_counter
from .ra import RARegistry
from .ra_schedule import certificate, OutsideCertificate
from .compiler import Compiled, Transition, ResourceLimit


@dataclass(frozen=True)
class GridEdge:
    source: int
    target: int
    kind: str
    index: int
    prefix: int


@dataclass
class Grid:
    registry: object
    layers: list
    edges: list
    configurations: dict
    constants: tuple
    writers: tuple
    reads: tuple
    cross: tuple
    rf: tuple
    sources: tuple
    stats: dict

    def label(self, edge):
        """Reference/debug expansion only. Production never calls this method."""
        if edge.kind == 'a':
            return tuple(-self.cross[edge.index-1][j] for j in range(edge.prefix))
        if edge.kind == 'b':
            return tuple(self.cross[i][edge.index-1] for i in range(edge.prefix))
        if edge.kind == 'r':
            return tuple(v if s == edge.prefix else -v for s, v in self.rf[edge.index].items())
        return self.constants

    def expand(self):
        levels = {q: i for i, layer in enumerate(self.layers) for q in layer}
        return Compiled(self.registry, self.layers,
                        [Transition(levels[e.source], e.source, e.target, self.label(e)) for e in self.edges],
                        [], self.registry.nvars, dict(self.stats))


def compile_grid(inst, *, max_states=100000, max_edges=300000, max_seconds=60):
    begin = perf_counter(); writers, readers = certificate(inst)
    if len(writers) != 2 or len(readers) != 1:
        raise OutsideCertificate('Range grid requires exactly two producers and one reader thread')
    a, b = writers; reads = readers[0]; m, n = len(a), len(b)
    reg = RARegistry(inst); initial = inst.initial[0]
    sources = (initial,)+a+b; source_index = {w: i for i, w in enumerate(sources)}
    cross = tuple(tuple(reg.literal(('co', u, v)) for v in b) for u in a)
    variable = {abs(v) for row in cross for v in row}
    order = {w: i for i, w in enumerate(sources)}
    constants = tuple(v if order[u] < order[w] else -v for v, (kind, u, w) in reg.by_id.items()
                      if kind == 'co' and v not in variable)
    rf = tuple({source_index[w]: reg.literal(('rf', w, r)) for w in inst.candidates[r]} for r in reads)
    configurations = {0: None, 1: (0, 0, 0, -1)}
    layers, edges = [[0], [1]], [GridEdge(0, 1, 'const', 0, 0)]
    nextid = 2
    for depth in range(m+n+len(reads)):
        by_state, layer = {}, []
        for q in layers[-1]:
            i, j, l, last = configurations[q]
            choices = []
            if i < m:
                choices.append(((i+1, j, l, 0), 'a', i+1, j))
            if j < n:
                choices.append(((i, j+1, l, 1), 'b', j+1, i))
            source = 0 if last == -1 else (i if last == 0 else m+j)
            if l < len(reads) and source in rf[l]:
                choices.append(((i, j, l+1, last), 'r', l, source))
            for state, kind, index, prefix in choices:
                target = by_state.get(state)
                if target is None:
                    target = nextid; nextid += 1
                    by_state[state] = target; configurations[target] = state; layer.append(target)
                edges.append(GridEdge(q, target, kind, index, prefix))
                if nextid > max_states or len(edges) > max_edges:
                    raise ResourceLimit('Range grid state/edge limit')
            if q % 256 == 0 and perf_counter()-begin > max_seconds:
                raise ResourceLimit('Range grid compile time limit')
        layers.append(layer)
    stats = dict(algorithm='grid', compile_seconds=perf_counter()-begin, states=nextid,
                 transitions=len(edges), original_variables=reg.nvars,
                 label_descriptors=len(edges), explicit_constant_literals=len(constants),
                 cross_variable_cells=m*n, rf_variable_cells=sum(map(len, rf)),
                 max_layer_states=max(map(len, layers)))
    return Grid(reg, layers, edges, configurations, constants, writers, reads, cross, rf, sources, stats)


class GridSolver:
    def __init__(self, grid):
        self.grid = grid
        self.constant = {abs(v): v > 0 for v in grid.constants}
        self.co_index = {abs(v): (i, j, v > 0) for i, row in enumerate(grid.cross) for j, v in enumerate(row)}
        self.rf_index = {v: (r, source) for r, row in enumerate(grid.rf) for source, v in row.items()}

    def propagate(self, assumptions=()):
        c = self.grid; m, n = map(len, c.writers)
        a_limit, b_limit = [n+1]*m, [m+1]*n
        allowed = [set(row) for row in c.rf]; positive = [set() for _ in c.rf]
        seen = set()
        for lit in assumptions:
            v = abs(lit)
            if v not in c.registry.by_id:
                raise ValueError('Only original RF/CO assumptions are supported')
            if -lit in seen:
                return False, set()
            seen.add(lit)
            if v in self.constant:
                if self.constant[v] != (lit > 0):
                    return False, set()
            elif v in self.co_index:
                i, j, orientation = self.co_index[v]
                if (lit > 0) == orientation:  # a_i before b_j
                    a_limit[i] = min(a_limit[i], j+1)
                else:
                    b_limit[j] = min(b_limit[j], i+1)
            else:
                r, source = self.rf_index[v]
                if lit > 0:
                    positive[r].add(source)
                else:
                    allowed[r].discard(source)
        for r in range(len(allowed)):
            if len(positive[r]) > 1:
                return False, set()
            if positive[r]:
                allowed[r] &= positive[r]
            if not allowed[r]:
                return False, set()
        enabled = bytearray(len(c.edges))
        forward = bytearray(len(c.configurations)); forward[0] = 1
        for k, e in enumerate(c.edges):
            yes = ((e.prefix < a_limit[e.index-1]) if e.kind == 'a' else
                   (e.prefix < b_limit[e.index-1]) if e.kind == 'b' else
                   (e.prefix in allowed[e.index]) if e.kind == 'r' else True)
            enabled[k] = yes
            if yes and forward[e.source]:
                forward[e.target] = 1
        if not any(forward[q] for q in c.layers[-1]):
            return False, set()
        backward = bytearray(len(c.configurations))
        for q in c.layers[-1]:
            backward[q] = 1
        for k in range(len(c.edges)-1, -1, -1):
            e = c.edges[k]
            if enabled[k] and backward[e.target]:
                backward[e.source] = 1
        negative_prefix, positive_prefix = [0]*m, [0]*n
        rf_support = [set() for _ in c.rf]
        for k, e in enumerate(c.edges):
            if not (enabled[k] and forward[e.source] and backward[e.target]):
                continue
            if e.kind == 'a':
                negative_prefix[e.index-1] = max(negative_prefix[e.index-1], e.prefix)
            elif e.kind == 'b':
                positive_prefix[e.index-1] = max(positive_prefix[e.index-1], e.prefix)
            elif e.kind == 'r':
                rf_support[e.index].add(e.prefix)
        forced = set(c.constants)
        for i, row in enumerate(c.cross):
            for j, v in enumerate(row):
                if j+1 > negative_prefix[i]:
                    forced.add(v)
                if i+1 > positive_prefix[j]:
                    forced.add(-v)
        for r, row in enumerate(c.rf):
            for source, v in row.items():
                if source not in rf_support[r]:
                    forced.add(-v)
                elif len(rf_support[r]) == 1:
                    forced.add(v)
        return True, forced


def grid_cnf(c):
    """O(graph + original variables) support CNF, with shared prefix circuits.

    Full Tseitin gates are used here. They are monotone in dead-edge signals,
    so unit propagation discovers every dead support under original assumptions.
    """
    begin = perf_counter(); clauses = [[v] for v in c.constants]; nv = c.registry.nvars
    def fresh():
        nonlocal nv
        nv += 1; return nv
    true = fresh(); clauses.append([true]); false = -true
    def gate(kind, literals):
        xs = tuple(dict.fromkeys(literals))
        members = set(xs)
        neutral, absorbing = (true, false) if kind == 'and' else (false, true)
        if absorbing in members or any(-x in members for x in xs):
            return absorbing
        xs = tuple(x for x in xs if x != neutral)
        if not xs:
            return neutral
        if len(xs) == 1:
            return xs[0]
        v = fresh()
        if kind == 'and':
            clauses.extend([-v, x] for x in xs); clauses.append([v]+[-x for x in xs])
        else:
            clauses.extend([v, -x] for x in xs); clauses.append([-v]+list(xs))
        return v
    def prefixes(kind, xs):
        out = [true if kind == 'and' else false]
        for x in xs:
            out.append(gate(kind, (out[-1], x)))
        return out
    m, n = map(len, c.writers)
    da = [prefixes('or', row) for row in c.cross]
    db = [prefixes('or', [-c.cross[i][j] for i in range(m)]) for j in range(n)]
    dr = []
    for row in c.rf:
        items = list(row.items()); xs = [v for _, v in items]
        left, right = prefixes('or', xs), prefixes('or', xs[::-1])
        dr.append({source: gate('or', (-v, left[i], right[len(xs)-i-1]))
                   for i, (source, v) in enumerate(items)})
    incoming = {q: [] for q in c.configurations}; outgoing = {q: [] for q in c.configurations}
    ds = []
    for k, e in enumerate(c.edges):
        d = da[e.index-1][e.prefix] if e.kind == 'a' else db[e.index-1][e.prefix] if e.kind == 'b' else dr[e.index][e.prefix] if e.kind == 'r' else false
        ds.append(d); incoming[e.target].append(k); outgoing[e.source].append(k)
    prefix = {0: false}
    for layer in c.layers[1:]:
        for q in layer:
            prefix[q] = gate('and', [gate('or', (prefix[c.edges[k].source], ds[k])) for k in incoming[q]])
    suffix = {q: false for q in c.layers[-1]}
    for layer in reversed(c.layers[:-1]):
        for q in layer:
            suffix[q] = gate('and', [gate('or', (ds[k], suffix[c.edges[k].target])) for k in outgoing[q]])
    clauses.append([-suffix[0]])
    neg_groups = [[[] for _ in range(n+1)] for _ in range(m)]
    pos_groups = [[[] for _ in range(m+1)] for _ in range(n)]
    rf_groups = [{source: [] for source in row} for row in c.rf]
    for k, e in enumerate(c.edges):
        dead = gate('or', (prefix[e.source], ds[k], suffix[e.target]))
        if e.kind == 'a':
            neg_groups[e.index-1][e.prefix].append(dead)
        elif e.kind == 'b':
            pos_groups[e.index-1][e.prefix].append(dead)
        elif e.kind == 'r':
            rf_groups[e.index][e.prefix].append(dead)
    # W_(negative X_ij) = AND dead edges A_i with prefix >= j.
    for i in range(m):
        tail = true
        for j in range(n, 0, -1):
            tail = gate('and', [tail]+neg_groups[i][j])
            clauses.append([-tail, c.cross[i][j-1]])
    for j in range(n):
        tail = true
        for i in range(m, 0, -1):
            tail = gate('and', [tail]+pos_groups[j][i])
            clauses.append([-tail, -c.cross[i-1][j]])
    for r, groups in enumerate(rf_groups):
        items = list(groups); dead = [gate('and', groups[s]) for s in items]
        left, right = prefixes('and', dead), prefixes('and', dead[::-1])
        for i, s in enumerate(items):
            v = c.rf[r][s]
            clauses.append([-dead[i], -v])
            other_dead = gate('and', (left[i], right[len(items)-i-1]))
            clauses.append([-other_dead, v])
    result = Compiled(c.registry, c.layers, [], clauses, nv, dict(c.stats))
    result.stats.update(algorithm='grid-cnf', cnf_seconds=perf_counter()-begin,
                        compile_seconds=c.stats['compile_seconds']+perf_counter()-begin,
                        clauses=len(clauses), cnf_variables=nv)
    return result
