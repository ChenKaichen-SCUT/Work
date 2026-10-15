"""Generic exact forced-literal oracle using an ordinary incremental SAT solver.

Countermodels establish both values of many variables at once. This is used
as a stronger comparison than testing each value independently from scratch.
It is not the proposed propagation algorithm.
"""


def forced_by_search(solver,variables,assumptions=(),known=()):
    variables=set(variables)
    # An original variable may be unconstrained (e.g. the order of two writes
    # with one unobserved read). Reserve its ID without restricting either
    # value; SAT libraries otherwise omit never-mentioned trailing variables.
    largest=max(variables,default=0)
    if largest>solver.nof_vars(): solver.add_clause([largest,-largest])
    calls=1
    if not solver.solve(assumptions=list(assumptions)): return False,set(),calls
    base={abs(l):l for l in solver.get_model() if abs(l) in variables}
    if set(base)!=variables: raise ValueError('SAT model omitted original variables')
    forced=set(known)|set(assumptions)
    unresolved=variables-{abs(l) for l in forced}
    while unresolved:
        v=min(unresolved);calls+=1
        if solver.solve(assumptions=[*assumptions,-base[v]]):
            # Every differing value in this countermodel has support both ways.
            differs={abs(l) for l in solver.get_model() if abs(l) in unresolved and l!=base[abs(l)]}
            assert v in differs
            unresolved.difference_update(differs)
        else:
            forced.add(base[v]);unresolved.remove(v)
    return True,forced,calls
