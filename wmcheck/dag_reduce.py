"""Standard bottom-up reduction of a layered, original-labelled support DAG."""
from time import perf_counter
from .compiler import Compiled,Transition,support_cnf


def reduce_dag(compiled, *, cnf=False):
    """Preserve the exact root-to-final label language, including all RF/CO bits.

    Delete states without an accepting continuation and merge states in the
    same layer with identical sets of (label, successor-class) transitions.
    This is suffix-language reduction, not a new weak-memory analysis.
    """
    begin=perf_counter();old=compiled
    mapping={q:0 for q in old.layers[-1]};next_id=1
    layers=[[] for _ in old.layers];layers[-1]=[0] if mapping else []
    edges=[];position=len(old.edges)-1
    for level in range(len(old.layers)-2,-1,-1):
        outgoing={}
        while position>=0 and old.edges[position].layer==level:
            edge=old.edges[position];position-=1
            target=mapping.get(edge.target)
            if target is not None:outgoing.setdefault(edge.source,set()).add((edge.label,target))
        by_signature={}
        for state in old.layers[level]:
            signature=tuple(sorted(outgoing.get(state,())))
            if not signature:continue
            target=by_signature.get(signature)
            if target is None:
                target=next_id;next_id+=1;by_signature[signature]=target;layers[level].append(target)
                edges.extend(Transition(level,target,dest,label) for label,dest in signature)
            mapping[state]=target
    if not layers[0]:
        layers[0]=[next_id];next_id+=1
    edges.sort(key=lambda e:e.layer)
    clauses,nvars=support_cnf(old.registry,layers,edges) if cnf else ([],old.registry.nvars)
    elapsed=perf_counter()-begin;stats=dict(old.stats)
    stats.update(raw_states=old.stats['states'],raw_transitions=len(old.edges),states=next_id,
        transitions=len(edges),layer_states=list(map(len,layers)),dag_reduction_seconds=elapsed,
        compile_seconds=old.stats['compile_seconds']+elapsed,clauses=len(clauses),cnf_variables=nvars)
    return Compiled(old.registry,layers,edges,clauses,nvars,stats)
