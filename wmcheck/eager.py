"""Conventional full-graph binary-topological-rank SAT baseline.

Uses the same certified candidates and cross-block co as the proposed compiler.
No boundary summaries or complete-history enumeration are used.
"""
from dataclasses import dataclass
from itertools import combinations,permutations
from math import ceil,log2
from time import perf_counter
from .model import Registry


@dataclass
class Encoding:
    registry: Registry
    clauses: list
    nvars: int
    stats: dict


def encode(inst,*,rank=True):
    start=perf_counter();reg=Registry(inst);clauses=[];nv=reg.nvars
    def fresh():
        nonlocal nv
        nv+=1;return nv
    def neg(a): return not a if type(a) is bool else -a
    def clause(*ls):
        if any(l is True for l in ls): return
        ls=list(dict.fromkeys(l for l in ls if l is not False))
        if any(-l in ls for l in ls): return
        clauses.append(ls)
    def conjunction(*ls):
        if any(l is False for l in ls): return False
        ls=list(dict.fromkeys(l for l in ls if l is not True))
        if any(-l in ls for l in ls): return False
        if not ls: return True
        if len(ls)==1: return ls[0]
        q=fresh()
        for l in ls: clause(-q,l)
        clause(q,*(neg(l) for l in ls));return q
    def disjunction(*ls): return neg(conjunction(*(neg(l) for l in ls)))
    for r,ws in inst.candidates.items():
        variables=[reg.literal(('rf',w,r)) for w in ws]
        clause(*variables)
        for a,b in combinations(variables,2): clause(-a,-b)
    for block in inst.blocks:
        locations={inst.event[w].loc for w in block if inst.event[w].kind=='W'}
        for loc in locations:
            ws=[w for w in block if inst.event[w].kind=='W' and inst.event[w].loc==loc]
            for a,b,c in permutations(ws,3):
                clause(neg(reg.literal(('co',a,b))),neg(reg.literal(('co',b,c))),reg.literal(('co',a,c)))
    for a,b in inst.forced_co: clause(reg.literal(('co',a,b)))
    write_by_loc={}
    for e in inst.events:
        if e.kind=='W': write_by_loc.setdefault(e.loc,[]).append(e.id)
    guarded=[]
    for ax in inst.axioms:
        edges={}
        def edge(a,b,guards=()):
            if any(g is False for g in guards): return
            condition=conjunction(*guards)
            edges.setdefault((a,b),[]).append(condition)
        for a,b in ax.fixed: edge(a,b)
        if ax.co:
            for ws in write_by_loc.values():
                for a,b in permutations(ws,2): edge(a,b,(reg.literal(('co',a,b)),))
        for r,ws in inst.candidates.items():
            for w in ws:
                rf=reg.literal(('rf',w,r))
                if ax.rf_mode=='all' or (ax.rf_mode=='ext' and inst.event[w].thread!=inst.event[r].thread): edge(w,r,(rf,))
                if ax.fr:
                    for v in write_by_loc[inst.event[w].loc]: edge(r,v,(rf,reg.literal(('co',w,v))))
        guarded.append(edges)
        bits=max(1,ceil(log2(max(2,len(inst.events)))))
        ranks={e.id:tuple(fresh() for _ in range(bits)) for e in inst.events}
        for (a,b),guards in edges.items():
            if a==b:
                for g in guards: clause(neg(g))
                continue
            eq=True;less=False
            for abit,bbit in zip(reversed(ranks[a]),reversed(ranks[b])):
                less=disjunction(less,conjunction(eq,-abit,bbit))
                same=fresh()
                clause(-same,-abit,bbit);clause(-same,abit,-bbit)
                clause(same,-abit,-bbit);clause(same,abit,bbit)
                eq=conjunction(eq,same)
            for guard in guards: clause(neg(guard),less)
    return Encoding(reg,clauses,nv,{'compile_seconds':perf_counter()-start,
        'original_variables':reg.nvars,'cnf_variables':nv,'clauses':len(clauses),
        'guarded_edge_pairs':sum(map(len,guarded)),'encoding':'binary topological ranks'})
