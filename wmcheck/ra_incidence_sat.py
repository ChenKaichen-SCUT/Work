"""Independent fixed-RA oracle using closure under actual generating edges.

No recognizer, frontier, source-cover facts, layouts or compiled graph are used.
H contains sb/RF/init and is closed under appending a selected base edge. This
forces the least HB relation into H; full H;H transitivity is unnecessary for
the existential overapproximation encoding. All coherence clauses are negative
in H, so replacing H by least HB preserves satisfaction. See the proof audit.
Clauses stream into the solver; this is a new oracle, not the frozen benchmark.
"""
from itertools import combinations,permutations
from time import perf_counter
from pysat.solvers import Solver
from .ra import RARegistry


class IncidenceSAT:
    def __init__(self,inst,solver='cadical195'):
        start=perf_counter();self.registry=reg=RARegistry(inst)
        self.solver=Solver(name=solver);self.clauses=0
        nodes=tuple(inst.event);nv=reg.nvars;hb={}
        for a in nodes:
            for b in nodes:
                if a!=b:nv+=1;hb[a,b]=nv
        def H(a,b):return hb.get((a,b),False)
        def C(a,b):return reg.literal(('co',a,b))
        def neg(x):return not x if type(x) is bool else -x
        def clause(*xs):
            if any(x is True for x in xs):return
            xs=list(dict.fromkeys(x for x in xs if x is not False))
            if any(-x in xs for x in xs):return
            self.solver.add_clause(xs);self.clauses+=1
        base=[(a,b,True) for a,b in sorted(inst.sb)]
        base += [(i,e,True) for i in inst.initial for e in nodes if e not in inst.initial]
        for r,ws in inst.candidates.items():
            ids=[reg.literal(('rf',w,r)) for w in ws]
            clause(*ids)
            for x,y in combinations(ids,2):clause(-x,-y)
            base.extend((w,r,v) for w,v in zip(ws,ids))
        for a,b in combinations(nodes,2):clause(-H(a,b),-H(b,a))
        for b,c,enabled in base:
            clause(neg(enabled),H(b,c))
            for a in nodes:
                if a!=b:clause(neg(H(a,b)),neg(enabled),H(a,c))
        for loc in sorted({e.loc for e in inst.events}):
            ws=[w for w in inst.writes if inst.event[w].loc==loc]
            rs=[r for r in inst.reads if inst.event[r].loc==loc]
            initial=next(i for i in inst.initial if inst.event[i].loc==loc)
            for w in ws:
                if w!=initial:clause(C(initial,w))
            for a,b,c in permutations(ws,3):clause(neg(C(a,b)),neg(C(b,c)),C(a,c))
            for a,b in permutations(ws,2):clause(-H(a,b),C(a,b))
            for r in rs:
                for source in inst.candidates[r]:
                    rf=reg.literal(('rf',source,r))
                    for w in ws:
                        clause(neg(H(w,r)),-rf,True if w==source else C(w,source))
                        clause(neg(H(r,w)),-rf,C(source,w))
            for r,s in permutations(rs,2):
                for a in inst.candidates[r]:
                    for b in inst.candidates[s]:
                        if a!=b:clause(-H(r,s),-reg.literal(('rf',a,r)),-reg.literal(('rf',b,s)),C(a,b))
        self.stats=dict(algorithm='independent-incidence-sat',solver=solver,original_variables=reg.nvars,
            cnf_variables=nv,clauses=self.clauses,base_edges=len(base),build_seconds=perf_counter()-start,
            recognizes=False,streams_clauses=True)

    def solve(self,assumptions=()):return self.solver.solve(assumptions=list(assumptions))
    def model(self):return self.solver.get_model()
    def close(self):self.solver.delete()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
