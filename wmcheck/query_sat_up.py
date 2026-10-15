"""Strong complete SAT comparator: seed countermodel search with native UP.

Native UP is sound but not complete. Search still checks consistency and every
remaining unsupported opposite value. Root consequences supplied by the caller
must be globally entailed; they cover root units omitted by PySAT's trail API.
"""
from .complete_query import forced_by_search


def forced_with_up(solver,variables,assumptions=(),known=(),flip_phases=False):
    variables=set(variables);largest=max(variables,default=0)
    if largest>solver.nof_vars():solver.add_clause([largest,-largest])
    consistent,trail=solver.propagate(assumptions=list(assumptions))
    if not consistent:return False,set(),0
    seeded=set(known)|{l for l in trail if abs(l) in variables}
    if not flip_phases:
        return forced_by_search(solver,variables,assumptions,known=seeded)
    calls=1
    if not solver.solve(assumptions=list(assumptions)):return False,set(),calls
    base={abs(l):l for l in solver.get_model() if abs(l) in variables}
    if set(base)!=variables:raise ValueError('SAT model omitted original variables')
    forced=seeded|set(assumptions);unresolved=variables-{abs(l) for l in forced}
    while unresolved:
        # Prefer disagreement on every still unresolved variable, to cover as
        # many supports as possible in one countermodel. These are preferences,
        # not constraints; completeness does not depend on their success.
        solver.set_phases([-base[v] if v in unresolved else base[v] for v in variables])
        v=min(unresolved);calls+=1
        if solver.solve(assumptions=[*assumptions,-base[v]]):
            differs={abs(l) for l in solver.get_model() if abs(l) in unresolved and l!=base[abs(l)]}
            assert v in differs;unresolved.difference_update(differs)
        else:forced.add(base[v]);unresolved.remove(v)
    return True,forced,calls
