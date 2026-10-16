"""Binary candidate processing, joint regular summaries, final CO successors.

Never enumerates a block Cartesian product, complete CO orders or conflict
supports. Exponential summary growth is still possible; resource failures are
UNKNOWN (exceptions), never a consistency answer.
"""
from time import perf_counter
from .ra import RARegistry, recognize
from .compiler import Compiled, Transition, ResourceLimit, support_cnf
from .regular_monitor import ra_monitors, update
from .port_monitor import ra_port_monitors, plan_ports


def compile_frontier(inst, *, order=None, cnf=False, merge=True, max_states=30000,
                     max_edges=200000, max_seconds=90, chain=True, incremental=True, compact=True,
                     sparse_init=True, early_degrees=False, co_mode='successor',
                     summary_mode='full'):
    if co_mode not in ('successor','direct'):
        raise ValueError('Expected successor or direct CO generators')
    if summary_mode not in ('full', 'ports'):
        raise ValueError('Expected full or ports summary')
    if summary_mode == 'ports' and co_mode != 'direct':
        raise ValueError('Future-port summaries currently require direct CO generators')
    if summary_mode == 'ports' and (not incremental or not compact):
        raise ValueError('Future-port summaries use their own incremental one-mark monitor encoding')
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
            symbol = 'c' if co_mode == 'direct' else 'q'
            groups.append(((a, b), [((v,), ((symbol, a, b),), ()), ((-v,), ((symbol, b, a),), ())]))
    if co_mode == 'direct':
        # The chosen original CO directions and a cover of mandatory L generate
        # a total reachability relation. Acyclicity makes its closure a strict
        # total order; no separate final-successor witness needs to be guessed.
        for a, b in sorted(L):
            if not any((a,z) in L and (z,b) in L for z in inst.writes):
                fixed('c',a,b)
    else:
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
    # A required degree can become impossible before its vertex is forgotten.
    # No suffix can repair degree zero after its last possible increment.
    degree_deadline = {}
    if early_degrees:
        for step, (_, alternatives) in enumerate(groups):
            for _, _, increments in alternatives:
                for v, field in increments:
                    if field == 0 or (field == 1 and v not in inst.initial):
                        degree_deadline[v, field] = step
    due = {}
    for key, step in degree_deadline.items():
        due.setdefault(step, []).append(key)
    monitors = ra_monitors(compact=compact)
    if co_mode == 'direct':
        monitors = monitors[:2]  # RA coherence and CO acyclicity; no Q/c binding.
    port_plans = None
    if summary_mode == 'ports':
        monitors = ra_port_monitors()
        port_plans = plan_ports(monitors, groups)
    recognition_seconds = perf_counter()-begin
    layers, edges = [[0], [1]], [Transition(0, 0, 1, tuple(constants))]
    empty = tuple(((), ()) if port_plans is not None else () for _ in monitors)
    states, nextid = {1: (empty, ())}, 2
    before = (); attempts = 0; width = 0; layer_width = []; max_layer = 1
    monitor_updates = 0; monitor_cache_hits = 0
    for step, (vertices, alternatives) in enumerate(groups):
        active = tuple(sorted(set(before) | set(vertices), key=rank.get))
        after = tuple(v for v in active if last[v] != step)
        forgotten = set(active)-set(after)
        width = max(width, len(active)); layer_width.append(len(active))
        newstates, by_summary, layer = {}, {}, []
        monitor_caches = [{} for _ in monitors]
        for source in layers[-1]:
            matrices, degrees = states[source]
            counts = dict(zip(before, degrees))
            for v in active:
                counts.setdefault(v, (0, 0, 0))
            for alternative_index, (label, additions, increments) in enumerate(alternatives):
                attempts += 1
                local = dict(counts); reject = False
                for v, field in increments:
                    current = list(local[v]); current[field] += 1
                    if current[field] > 1:
                        reject = True; break
                    local[v] = tuple(current)
                if reject:
                    continue
                if early_degrees and any(local[v][field] != 1 for v, field in due.get(step, ())):
                    continue
                for v in forgotten:
                    if inst.event[v].kind == 'R' and local[v][0] != 1:
                        reject = True
                    if co_mode != 'direct' and inst.event[v].kind == 'W' and v not in inst.initial and local[v][1] != 1:
                        reject = True
                if reject:
                    continue
                newmat = []
                for monitor_index, (monitor, matrix) in enumerate(zip(monitors, matrices)):
                    if port_plans is None:
                        result = update(monitor, matrix, before, active, after, additions, incremental=incremental)
                        monitor_updates += 1
                    else:
                        cache = monitor_caches[monitor_index]
                        key = (matrix, alternative_index)
                        if key in cache:
                            result = cache[key]; monitor_cache_hits += 1
                        else:
                            result = port_plans[monitor_index][step].update(matrix, alternative_index)
                            cache[key] = result; monitor_updates += 1
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
                    error = ResourceLimit('Frontier state/edge limit')
                    error.stats = dict(states=nextid, transitions=len(edges), step=step,
                        groups=len(groups), max_interface=width, current_interface=len(active),
                        max_layer_states=max(max_layer,len(layer)), early_degrees=early_degrees,
                        co_mode=co_mode, summary_mode=summary_mode)
                    raise error
            if perf_counter()-begin > max_seconds:
                error = ResourceLimit('Frontier compile time limit')
                error.stats = dict(states=nextid, transitions=len(edges), step=step,
                    groups=len(groups), max_interface=width, current_interface=len(active),
                    max_layer_states=max(max_layer,len(layer)), early_degrees=early_degrees,
                    co_mode=co_mode, summary_mode=summary_mode)
                raise error
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
    stats['compact_rotation'] = compact if port_plans is None else None
    stats['monitor_encoding'] = 'one-mark-ports' if port_plans is not None else 'rotation'
    stats['sparse_initialization'] = sparse_init
    stats['early_degrees'] = early_degrees
    stats['co_mode'] = co_mode
    stats['summary_mode'] = summary_mode
    stats['monitor_updates'] = monitor_updates
    stats['monitor_cache_hits'] = monitor_cache_hits
    if co_mode == 'direct':
        stats['algorithm'] = 'frontier-direct-co'
    if port_plans is not None:
        stats['algorithm'] = 'frontier-ports'
        stats['max_port_coordinates'] = max((sum(
            (1 if plans[step].acyclic else 2) * len(plans[step].after_inputs) * len(plans[step].after_outputs)
            for plans in port_plans) for step in range(len(groups))), default=0)
        stats['max_product_vertices'] = [max((p.width for p in plans), default=0) for plans in port_plans]
    return Compiled(registry, layers, edges, clauses, nvars, stats)
