"""Binary candidate processing, joint regular summaries, final CO successors.

Never enumerates a block Cartesian product, complete CO orders or conflict
supports. Exponential summary growth is still possible; resource failures are
UNKNOWN (exceptions), never a consistency answer.
"""
from time import perf_counter
from .ra import RARegistry, recognize
from .compiler import Compiled, Transition, ResourceLimit, support_cnf
from .regular_monitor import ra_monitors, update


def compile_frontier(inst, *, order=None, cnf=False, merge=True, max_states=30000,
                     max_edges=200000, max_seconds=90, chain=True, incremental=True, compact=True,
                     sparse_init=True):
    begin = perf_counter(); registry = RARegistry(inst); cert = recognize(inst, chain=chain)
    constants, groups = [], []
    if cert['status'] == 'PROVED_UNSAT':
        clauses = [[]] if cnf else []
        return Compiled(registry, [[0], []], [], clauses, registry.nvars,
                        dict(algorithm='frontier', states=1, transitions=0,
                             original_variables=registry.nvars, recognition='PROVED_UNSAT',
                             compile_seconds=perf_counter()-begin, clauses=len(clauses)))
    D, H, L, mandatory = (cert[k] for k in ('domains', 'H', 'L', 'mandatory'))
    # A group is (endpoints, [(label, edge additions, degree increments)]).
    def fixed(symbol, a, b, counters=()):
        additions = ((symbol, a, b),) + ((('R', b, a),) if symbol == 'r' else ())
        groups.append(((a, b), [((), additions, counters)]))
    for a, b in sorted(inst.sb):
        fixed('s', a, b)
    # Initialization is HB-before every non-initial event. Do not install H/L
    # dense closures as graph edges: only sb adjacency, init and mandatory RF.
    # sb adjacency already reaches every later event of the same thread.
    # Initial-to-first edges therefore have exactly the same transitive HB
    # closure as initial-to-all edges, without artificially dense frontiers.
    init_targets = [t[0] for t in inst.threads if t] if sparse_init else [
        e.id for e in inst.events if e.id not in inst.initial]
    for i in inst.initial:
        for target in init_targets:
            fixed('s', i, target)
    for v, (kind, a, b) in registry.by_id.items():
        if kind == 'rf':
            if a not in D[b]:
                constants.append(-v)
            elif (a, b) in mandatory:
                constants.append(v); fixed('r', a, b, ((b, 0),))
            else:
                groups.append(((a, b), [((-v,), (), ()),
                                        ((v,), (('r', a, b), ('R', b, a)), ((b, 0),))]))
        elif (a, b) in L or (b, a) in L:
            constants.append(v if (a, b) in L else -v)
        else:
            groups.append(((a, b), [((v,), (('q', a, b),), ()), ((-v,), (('q', b, a),), ())]))
    for a, b in sorted(cert['successors']):
        groups.append(((a, b), [((), (), ()), ((), (('c', a, b),), ((a, 2), (b, 1)))]))
    # Isolated vertices also need their final degree checks.
    for e in inst.events:
        groups.append(((e.id,), [((), (), ())]))
    if order is None:
        order = tuple(e.id for e in inst.events)
    if len(order) != len(set(order)) or set(order) != set(inst.event):
        raise ValueError('Layout order must contain every event exactly once')
    rank = {v: i for i, v in enumerate(order)}
    groups.sort(key=lambda g: (max(rank[v] for v in g[0]), min(rank[v] for v in g[0])))
    last = {v: i for i, (vertices, _) in enumerate(groups) for v in vertices}
    monitors = ra_monitors(compact=compact)
    recognition_seconds = perf_counter()-begin
    layers, edges = [[0], [1]], [Transition(0, 0, 1, tuple(constants))]
    empty = tuple(() for _ in monitors)
    states, nextid = {1: (empty, ())}, 2
    before = (); attempts = 0; width = 0; layer_width = []; max_layer = 1
    for step, (vertices, alternatives) in enumerate(groups):
        active = tuple(sorted(set(before) | set(vertices), key=rank.get))
        after = tuple(v for v in active if last[v] != step)
        forgotten = set(active)-set(after)
        width = max(width, len(active)); layer_width.append(len(active))
        newstates, by_summary, layer = {}, {}, []
        for source in layers[-1]:
            matrices, degrees = states[source]
            counts = dict(zip(before, degrees))
            for v in active:
                counts.setdefault(v, (0, 0, 0))
            for label, additions, increments in alternatives:
                attempts += 1
                local = dict(counts); reject = False
                for v, field in increments:
                    current = list(local[v]); current[field] += 1
                    if current[field] > 1:
                        reject = True; break
                    local[v] = tuple(current)
                if reject:
                    continue
                for v in forgotten:
                    if inst.event[v].kind == 'R' and local[v][0] != 1:
                        reject = True
                    if inst.event[v].kind == 'W' and v not in inst.initial and local[v][1] != 1:
                        reject = True
                if reject:
                    continue
                newmat = []
                for monitor, matrix in zip(monitors, matrices):
                    result = update(monitor, matrix, before, active, after, additions, incremental=incremental)
                    if result is None:
                        reject = True; break
                    newmat.append(result)
                if reject:
                    continue
                state = (tuple(newmat), tuple(local[v] for v in after))
                target = by_summary.get(state) if merge else None
                if target is None:
                    target = nextid; nextid += 1; layer.append(target); newstates[target] = state
                    if merge:
                        by_summary[state] = target
                edges.append(Transition(step+1, source, target, label))
                if nextid > max_states or len(edges) > max_edges:
                    raise ResourceLimit('Frontier state/edge limit')
            if perf_counter()-begin > max_seconds:
                raise ResourceLimit('Frontier compile time limit')
        layers.append(layer); states = newstates; before = after; max_layer = max(max_layer, len(layer))
    graph_seconds = perf_counter()-begin
    clauses, nvars = support_cnf(registry, layers, edges) if cnf else ([], registry.nvars)
    labels = {e.label for e in edges}
    stats = dict(algorithm='frontier' if merge else 'frontier-unfold', compile_seconds=perf_counter()-begin,
                 recognition_seconds=recognition_seconds, graph_seconds=graph_seconds,
                 cnf_seconds=perf_counter()-begin-graph_seconds, states=nextid, transitions=len(edges),
                 attempted_transitions=attempts, max_interface=width, max_layer_states=max_layer,
                 layer_states=list(map(len, layers)), monitor_states=[m.size for m in monitors],
                 original_variables=registry.nvars, clauses=len(clauses), cnf_variables=nvars,
                 label_literals=sum(len(e.label) for e in edges), unique_labels=len(labels),
                 unique_label_literals=sum(map(len, labels)), certified_rf=sum(map(len, D.values())),
                 initial_rf=sum(map(len, inst.candidates.values())), mandatory_rf=len(mandatory),
                 successor_candidates=len(cert['successors']), recognition_steps=len(cert['trace']))
    stats['incremental_closure'] = incremental
    stats['compact_rotation'] = compact
    stats['sparse_initialization'] = sparse_init
    return Compiled(registry, layers, edges, clauses, nvars, stats)
