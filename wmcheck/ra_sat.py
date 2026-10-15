"""Independent conventional SAT encoding of the fixed-event RA contract.

HB is represented by a transitive irreflexive superset of sb|rf. Four
coherence constraints connect it to per-address total CO. Such a superset
exists exactly when the least HB closure satisfies RA coherence. No history
summaries, frontier recognizer, or legal-execution enumeration are used.
"""
from itertools import combinations, permutations
from time import perf_counter
from .ra import RARegistry
from .eager import Encoding


def encode_ra(inst):
    start = perf_counter(); reg = RARegistry(inst); clauses = []; nv = reg.nvars
    def clause(*xs):
        if True in [x for x in xs if type(x) is bool]:
            return
        xs = list(dict.fromkeys(x for x in xs if x is not False))
        if any(-x in xs for x in xs):
            return
        clauses.append(xs)
    def neg(x):
        return not x if type(x) is bool else -x
    nodes = tuple(inst.event); hb = {}
    for a in nodes:
        for b in nodes:
            if a != b:
                nv += 1; hb[a, b] = nv
    def H(a, b):
        return hb.get((a, b), False)
    def C(a, b):
        return reg.literal(('co', a, b))
    for a, b in inst.sb:
        clause(H(a, b))
    for i in inst.initial:
        for e in nodes:
            if e not in inst.initial:
                clause(H(i, e))
    for a, b in combinations(nodes, 2):
        clause(neg(H(a, b)), neg(H(b, a)))
    for a, b, c in permutations(nodes, 3):
        clause(neg(H(a, b)), neg(H(b, c)), H(a, c))
    for r, ws in inst.candidates.items():
        xs = [reg.literal(('rf', w, r)) for w in ws]
        clause(*xs)
        for x, y in combinations(xs, 2):
            clause(-x, -y)
        for w, x in zip(ws, xs):
            clause(-x, H(w, r))
    for loc in sorted({e.loc for e in inst.events}):
        ws = [w for w in inst.writes if inst.event[w].loc == loc]
        rs = [r for r in inst.reads if inst.event[r].loc == loc]
        initial = next(i for i in inst.initial if inst.event[i].loc == loc)
        for w in ws:
            if w != initial:
                clause(C(initial, w))
        for a, b, c in permutations(ws, 3):
            clause(neg(C(a, b)), neg(C(b, c)), C(a, c))
        for a, b in permutations(ws, 2):
            clause(neg(H(a, b)), C(a, b))
        for r in rs:
            for source in inst.candidates[r]:
                rf = reg.literal(('rf', source, r))
                for w in ws:
                    clause(neg(H(w, r)), -rf, True if w == source else C(w, source))
                    clause(neg(H(r, w)), -rf, C(source, w))
        for r, s in permutations(rs, 2):
            for a in inst.candidates[r]:
                for b in inst.candidates[s]:
                    if a != b:
                        clause(neg(H(r, s)), -reg.literal(('rf', a, r)),
                               -reg.literal(('rf', b, s)), C(a, b))
    return Encoding(reg, clauses, nv, dict(algorithm='ra-sat', compile_seconds=perf_counter()-start,
        original_variables=reg.nvars, cnf_variables=nv, clauses=len(clauses)))
