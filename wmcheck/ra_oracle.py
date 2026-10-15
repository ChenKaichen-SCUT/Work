"""Independent dense RA definition for validation only, with no recognizer reuse."""
from itertools import permutations, product


def reach(edges, nodes):
    adjacency = {v: set() for v in nodes}
    for a, b in edges:
        adjacency[a].add(b)
    out = set()
    for source in nodes:
        seen, todo = set(), list(adjacency[source])
        while todo:
            v = todo.pop()
            if v in seen:
                continue
            seen.add(v); todo.extend(adjacency[v]-seen)
        out.update((source, v) for v in seen)
    return out


def valid(inst, rf, orders):
    nodes = tuple(inst.event)
    if set(rf) != set(inst.reads) or any(w not in inst.candidates[r] for r, w in rf.items()):
        return False
    expected = {loc: {w for w in inst.writes if inst.event[w].loc == loc}
                for loc in {inst.event[w].loc for w in inst.writes}}
    if set(orders) != set(expected):
        return False
    for loc, ws in orders.items():
        if len(ws) != len(set(ws)) or set(ws) != expected[loc] or ws[0] not in inst.initial:
            return False
    co = {(a, b) for ws in orders.values() for i, a in enumerate(ws) for b in ws[i+1:]}
    rf_edges = {(w, r) for r, w in rf.items()}
    sb = {(a, b) for t in inst.threads for i, a in enumerate(t) for b in t[i+1:]}
    init = {(i, e) for i in inst.initial for e in nodes if e not in inst.initial}
    hb = reach(sb | rf_edges | init, nodes)
    fr = {(r, v) for r, w in rf.items() for u, v in co if u == w}
    eco = reach(rf_edges | co | fr, nodes)
    return not any(a == b or (b, a) in eco for a, b in hb)


def enumerate_assignments(inst, registry, limit=1000000):
    locs = sorted({inst.event[w].loc for w in inst.writes})
    groups = []
    for loc in locs:
        i = next(i for i in inst.initial if inst.event[i].loc == loc)
        ws = [w for w in inst.writes if inst.event[w].loc == loc and w != i]
        groups.append([(i,)+order for order in permutations(ws)])
    examined = 0
    for orders in product(*groups):
        mapping = dict(zip(locs, orders))
        for sources in product(*(inst.candidates[r] for r in inst.reads)):
            examined += 1
            if examined > limit:
                raise RuntimeError('Independent oracle resource limit')
            rf = dict(zip(inst.reads, sources))
            if valid(inst, rf, mapping):
                positions = {w: i for ws in orders for i, w in enumerate(ws)}
                yield {v: rf[b] == a if kind == 'rf' else positions[a] < positions[b]
                       for v, (kind, a, b) in registry.by_id.items()}
