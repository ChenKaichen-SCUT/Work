"""Independent full-graph oracle. Enumeration here is for tests only."""
from collections import defaultdict,deque
from itertools import permutations,product


def acyclic(nodes,edges):
    successors={v:set() for v in nodes};degree={v:0 for v in nodes}
    for a,b in edges:
        if b not in successors[a]: successors[a].add(b);degree[b]+=1
    todo=deque(v for v in nodes if degree[v]==0);count=0
    while todo:
        v=todo.popleft();count+=1
        for w in successors[v]:
            degree[w]-=1
            if not degree[w]: todo.append(w)
    return count==len(successors)


def dense_tso_fixed(inst):
    """Rebuild standard axioms from raw thread order, never generated sparse edges."""
    ev=inst.event;local=set();global_=set()
    for seq in inst.metadata['thread_sequences'].values():
        for i,a in enumerate(seq):
            if ev[a].kind=='F': continue
            for j in range(i+1,len(seq)):
                b=seq[j]
                if ev[b].kind=='F': continue
                if ev[a].loc==ev[b].loc: local.add((a,b))
                if ev[a].kind=='R' or ev[b].kind=='W' or any(ev[f].kind=='F' for f in seq[i+1:j]):
                    global_.add((a,b))
    return [('all',True,True,local),('ext',True,True,global_)]


def valid_execution(inst,rf,co,*,dense_tso=False):
    ev=inst.event;writes=[e.id for e in inst.events if e.kind=='W']
    reads=[e.id for e in inst.events if e.kind=='R']
    if set(rf)!=set(reads): return False
    for r,s in rf.items():
        if s not in ev or ev[s].kind!='W' or ev[s].loc!=ev[r].loc: return False
        if ev[r].value is not None and ev[r].value!=ev[s].value: return False
    for a in writes:
        if (a,a) in co: return False
        for b in writes:
            if a!=b and ev[a].loc==ev[b].loc and (((a,b) in co)==((b,a) in co)): return False
    if any(ev[a].kind!='W' or ev[b].kind!='W' or ev[a].loc!=ev[b].loc for a,b in co): return False
    succ=defaultdict(set)
    for a,b in co: succ[a].add(b)
    if any(not succ[b]<=succ[a] for a,b in co): return False
    if any((a,b) not in co for a,b in inst.forced_co): return False
    fr={(r,v) for r,s in rf.items() for v in succ[s]}
    axioms=dense_tso_fixed(inst) if dense_tso else [(a.rf_mode,a.co,a.fr,set(a.fixed)) for a in inst.axioms]
    for mask,hasco,hasfr,fixed in axioms:
        edges=set(fixed)
        if hasco: edges.update(co)
        if hasfr: edges.update(fr)
        edges.update((s,r) for r,s in rf.items() if mask=='all' or (mask=='ext' and ev[s].thread!=ev[r].thread))
        if not acyclic(ev,edges): return False
    return True


def enumerate_models(inst,registry,*,dense_tso=False,limit=1000000):
    reads=sorted(inst.candidates);groups=[]
    for block in inst.blocks:
        byloc=defaultdict(list)
        for e in block:
            if inst.event[e].kind=='W': byloc[inst.event[e].loc].append(e)
        groups.extend(tuple(permutations(sorted(ws))) for _,ws in sorted(byloc.items()))
    cross={(a.id,b.id) for a in inst.events for b in inst.events if a.kind==b.kind=='W'
           and a.loc==b.loc and inst.layer[a.id]<inst.layer[b.id]}
    examined=0
    for orders in product(*groups):
        co=set(cross)
        for order in orders:
            co.update((a,b) for i,a in enumerate(order) for b in order[i+1:])
        for choices in product(*(inst.candidates[r] for r in reads)):
            examined+=1
            if examined>limit: raise RuntimeError('oracle enumeration limit')
            rf=dict(zip(reads,choices))
            if valid_execution(inst,rf,co,dense_tso=dense_tso):
                assignment={}
                for v,(kind,a,b) in registry.by_id.items(): assignment[v]=(rf[b]==a if kind=='rf' else (a,b) in co)
                yield assignment


def truth_under(models,assumptions):
    possible=[m for m in models if all(m[abs(l)]==(l>0) for l in assumptions)]
    if not possible: return False,set()
    forced=set()
    for v,value in possible[0].items():
        if all(m[v]==value for m in possible): forced.add(v if value else -v)
    return True,forced
