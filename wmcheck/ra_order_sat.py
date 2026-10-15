"""Structure-aware SAT comparator for the same pure producer/reader RA class.

For two producers, monotone grid constraints characterize all chain shuffles;
no cubic transitivity expansion. It is an exact competitor, not a deliberately
weak UP-only baseline. Complete queries use incremental countermodel search.
"""
from itertools import combinations, permutations
from time import perf_counter
from .ra import RARegistry
from .ra_schedule import certificate
from .eager import Encoding


def encode_order(inst):
    begin = perf_counter(); writers, readers = certificate(inst); reg = RARegistry(inst)
    clauses = []; initial = inst.initial[0]
    for w in inst.writes:
        if w != initial:
            clauses.append([reg.literal(('co', initial, w))])
    for t in writers:
        for a, b in combinations(t, 2):
            clauses.append([reg.literal(('co', a, b))])
    if len(writers) == 2:
        a, b = writers
        for i, u in enumerate(a):
            for j, v in enumerate(b):
                bit = reg.literal(('co', u, v))
                if i:
                    clauses.append([-bit, reg.literal(('co', a[i-1], v))])
                if j+1 < len(b):
                    clauses.append([-bit, reg.literal(('co', u, b[j+1]))])
    elif len(writers) > 2:
        for a, b, c in permutations(inst.writes, 3):
            clauses.append([-reg.literal(('co', a, b)), -reg.literal(('co', b, c)), reg.literal(('co', a, c))])
    for r, ws in inst.candidates.items():
        bits = [reg.literal(('rf', w, r)) for w in ws]
        clauses.append(bits)
        clauses.extend([-a, -b] for a, b in combinations(bits, 2))
    for t in readers:
        for r, s in zip(t, t[1:]):
            for a in inst.candidates[r]:
                for b in inst.candidates[s]:
                    if a != b:
                        clauses.append([-reg.literal(('rf', a, r)), -reg.literal(('rf', b, s)),
                                        reg.literal(('co', a, b))])
    return Encoding(reg, clauses, reg.nvars,
                    dict(algorithm='order-sat', compile_seconds=perf_counter()-begin,
                         original_variables=reg.nvars, clauses=len(clauses), cnf_variables=reg.nvars))
