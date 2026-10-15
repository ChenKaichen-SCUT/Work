"""Construct a quotient directly, before generating producer interleavings.

    Recognized class: one address; each nonempty thread entirely writes or
    entirely reads; all writes release, all reads acquire; arbitrary fixed
    write/read values. No mixed thread is accepted by this specialization.
"""
from itertools import product
from time import perf_counter
from .ra import RARegistry
from .compiler import Compiled, Transition, ResourceLimit, support_cnf


class OutsideCertificate(ValueError):
    pass


def certificate(inst):
    if len(inst.initial) != 1:
        raise OutsideCertificate('Scheduling certificate requires one address')
    writers, readers = [], []
    for t in inst.threads:
        if not t:
            continue
        kinds = {inst.event[v].kind for v in t}
        if len(kinds) != 1:
            raise OutsideCertificate('Mixed read/write thread is outside scheduling certificate')
        (writers if kinds == {'W'} else readers).append(t)
    return tuple(writers), tuple(readers)


def compile_schedule(inst, *, cnf=False, max_states=500000, max_edges=1500000,
                     max_seconds=120, merge=True):
    """merge=False unfolds histories online: an explicitly resource-limited ablation."""
    begin = perf_counter()
    writers, readers = certificate(inst)
    registry = RARegistry(inst)
    initial = inst.initial[0]
    producer = {w: (j, i+1) for j, t in enumerate(writers) for i, w in enumerate(t)}
    reader = {r: (j, i+1) for j, t in enumerate(readers) for i, r in enumerate(t)}
    constants = []
    for v, (kind, a, b) in registry.by_id.items():
        if kind == 'co' and (a == initial or b == initial or producer[a][0] == producer[b][0]):
            before = a == initial or (b != initial and producer[a][1] < producer[b][1])
            constants.append(v if before else -v)
    constants = tuple(constants)
    const_ids = {abs(l) for l in constants}
    pool = {constants: constants}
    def intern(label):
        label = tuple(label)
        return pool.setdefault(label, label)
    rf_labels = {(r, w): intern(registry.by_key['rf', u, r] * (1 if w == u else -1)
                                for u in inst.candidates[r])
                 for r in inst.reads for w in inst.candidates[r]}
    root_state = ((0,)*len(writers), (0,)*len(readers), -1)
    states = {0: None, 1: root_state}
    layers, edges = [[0], [1]], [Transition(0, 0, 1, constants)]
    nextid, attempts = 2, 0
    depth = sum(map(len, writers))+sum(map(len, readers))
    for step in range(depth):
        layer, by_state = [], {}
        for q in layers[-1]:
            counts, read_counts, last = states[q]
            choices = []
            for j, t in enumerate(writers):
                if counts[j] == len(t):
                    continue
                new = t[counts[j]]
                label = []
                for h, other in enumerate(writers):
                    if h != j:
                        label.extend(registry.literal(('co', w, new)) for w in other[:counts[h]])
                updated = list(counts); updated[j] += 1
                choices.append(((tuple(updated), read_counts, j), intern(label)))
            source = initial if last == -1 else writers[last][counts[last]-1]
            for j, t in enumerate(readers):
                if read_counts[j] == len(t):
                    continue
                r = t[read_counts[j]]
                if source not in inst.candidates[r]:
                    continue
                updated = list(read_counts); updated[j] += 1
                choices.append(((counts, tuple(updated), last), rf_labels[r, source]))
            for state, label in choices:
                attempts += 1
                target = by_state.get(state) if merge else None
                if target is None:
                    target = nextid; nextid += 1
                    states[target] = state; layer.append(target)
                    if merge:
                        by_state[state] = target
                edges.append(Transition(step+1, q, target, label))
                if nextid > max_states or len(edges) > max_edges:
                    raise ResourceLimit('Scheduling graph state/edge limit')
            if q % 256 == 0 and perf_counter()-begin > max_seconds:
                raise ResourceLimit('Scheduling compile time limit')
        layers.append(layer)
    graph_seconds = perf_counter()-begin
    clauses, nvars = support_cnf(registry, layers, edges) if cnf else ([], registry.nvars)
    used_labels = {e.label for e in edges}
    stats = dict(algorithm='dynamic' if merge else 'unfold', compile_seconds=perf_counter()-begin,
                 graph_seconds=graph_seconds, cnf_seconds=perf_counter()-begin-graph_seconds,
                 states=nextid, transitions=len(edges), attempted_transitions=attempts,
                 max_layer_states=max(map(len, layers)), original_variables=registry.nvars,
                 label_literals=sum(len(e.label) for e in edges), unique_labels=len(used_labels),
                 unique_label_literals=sum(map(len, used_labels)), clauses=len(clauses), cnf_variables=nvars,
                 producer_lengths=list(map(len, writers)), reader_lengths=list(map(len, readers)))
    compiled = Compiled(registry, layers, edges, clauses, nvars, stats)
    # O(q) is represented symbolically by prefix counters, never materialized in
    # production. Consumers can invoke this independent local checker on demand.
    def owned(q):
        if q == 0:
            return 0
        counts, read_counts, _ = states[q]
        mask = 0
        for v, (kind, a, b) in registry.by_id.items():
            yes = v in const_ids
            if kind == 'rf':
                j, i = reader[b]; yes = i <= read_counts[j]
            elif not yes:
                j, i = producer[a]; h, k = producer[b]
                yes = i <= counts[j] and k <= counts[h]
            if yes:
                mask |= 1 << (v-1)
        return mask
    compiled.owned = owned
    compiled.configurations = states
    return compiled


def compile_co_first(inst, *, cnf=False, max_states=100000, max_edges=1000000, max_seconds=90):
    """Fixed-plan baseline: decide whole CO, then reader sources.

    Enumerates only chain shuffles (not all write permutations); merges RF
    histories by reader progress/source position for each distinct CO. This is
    stronger than a naive complete-execution list but retains the proven cut.
    """
    begin = perf_counter(); writers, readers = certificate(inst); registry = RARegistry(inst)
    if len(readers) != 1:
        raise OutsideCertificate('Fixed-plan comparison currently uses one reader chain')
    initial = inst.initial[0]; orders = []
    def enumerate_orders(counts, prefix):
        if perf_counter()-begin > max_seconds or len(orders) >= max_states:
            raise ResourceLimit('CO-first order limit')
        if all(n == len(t) for n, t in zip(counts, writers)):
            orders.append((initial,)+prefix); return
        for j, t in enumerate(writers):
            if counts[j] < len(t):
                nxt = list(counts); nxt[j] += 1
                enumerate_orders(tuple(nxt), prefix+(t[counts[j]],))
    enumerate_orders((0,)*len(writers), ())
    layers = [[0], []]; edges = []; nextid = 1; states = {}
    for order in orders:
        pos = {w: i for i, w in enumerate(order)}
        label = tuple(v if pos[a] < pos[b] else -v for v, (k, a, b) in registry.by_id.items() if k == 'co')
        q = nextid; nextid += 1; layers[1].append(q); states[q] = (order, 0)
        edges.append(Transition(0, 0, q, label))
    raw_cut = len(orders)
    for step, r in enumerate(readers[0]):
        layer, grouped, newstates = [], {}, {}
        for q in layers[-1]:
            order, lower = states[q]
            for j in range(lower, len(order)):
                if order[j] not in inst.candidates[r]:
                    continue
                state = (order, j)
                if state not in grouped:
                    grouped[state] = nextid; newstates[nextid] = state; layer.append(nextid); nextid += 1
                label = tuple(registry.by_key['rf', w, r]*(1 if w == order[j] else -1)
                              for w in inst.candidates[r])
                edges.append(Transition(step+1, q, grouped[state], label))
                if nextid > max_states or len(edges) > max_edges or perf_counter()-begin > max_seconds:
                    raise ResourceLimit('CO-first construction limit')
        layers.append(layer); states = newstates
    graph_seconds = perf_counter()-begin
    clauses, nvars = support_cnf(registry, layers, edges) if cnf else ([], registry.nvars)
    labels = {e.label for e in edges}
    return Compiled(registry, layers, edges, clauses, nvars,
                    dict(algorithm='co-first', compile_seconds=perf_counter()-begin, graph_seconds=graph_seconds,
                         cnf_seconds=perf_counter()-begin-graph_seconds, states=nextid, transitions=len(edges),
                         max_layer_states=max(map(len, layers)), co_cut_states=raw_cut,
                         label_literals=sum(len(e.label) for e in edges), unique_labels=len(labels),
                         unique_label_literals=sum(map(len, labels)), original_variables=registry.nvars,
                         clauses=len(clauses), cnf_variables=nvars))
