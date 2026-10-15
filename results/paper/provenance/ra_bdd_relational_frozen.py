"""Stronger CUDD baseline: derive HB symbolically over original bits only.

Avoids compiling and later eliminating a quadratic set of auxiliary HB bits.
All common witnesses remain Boolean correlations in the BDD. This is a generic
symbolic relation evaluation, not the proposed boundary-summary construction.
"""
from itertools import combinations,permutations
from time import perf_counter
from .ra import RARegistry
from .ra_bdd import BDDCompiler


class RelationalBDD(BDDCompiler):
    def __init__(self,inst):
        from dd.cudd import BDD
        start=perf_counter();self.registry=reg=RARegistry(inst);self.bdd=b=BDD()
        b.configure(reordering=True);b.declare(*(f'x{i}' for i in reg.by_id));root=b.true
        def literal(l):
            if type(l) is bool:return b.true if l else b.false
            v=b.var(f'x{abs(l)}');return v if l>0 else ~v
        def C(a,c):return literal(reg.literal(('co',a,c)))
        nodes=tuple(inst.event);ix={v:i for i,v in enumerate(nodes)};n=len(nodes)
        h=[[b.false for _ in nodes] for _ in nodes]
        for a,c in inst.sb:h[ix[a]][ix[c]]=b.true
        for i in inst.initial:
            for t in inst.threads:
                if t:h[ix[i]][ix[t[0]]]=b.true
        rf={}
        for r,ws in inst.candidates.items():
            zero,one=b.true,b.false
            for w in ws:
                x=literal(reg.literal(('rf',w,r)));rf[w,r]=x
                one=(one & ~x)|(zero & x);zero &= ~x
                # Exactly-one makes a singleton RF domain permanently true.
                # Keep its original bit in root, but constant-fold it inside
                # relation evaluation instead of constructing impossible cases.
                h[ix[w]][ix[r]] |= b.true if len(ws)==1 else x
            root &= one
        for k in range(n):
            for i in range(n):
                if h[i][k]==b.false:continue
                for j in range(n):
                    if h[k][j]!=b.false:h[i][j] |= h[i][k]&h[k][j]
        def H(a,c):return h[ix[a]][ix[c]]
        for i in range(n):root &= ~h[i][i]
        for loc in sorted({e.loc for e in inst.events}):
            ws=[w for w in inst.writes if inst.event[w].loc==loc]
            rs=[r for r in inst.reads if inst.event[r].loc==loc]
            initial=next(i for i in inst.initial if inst.event[i].loc==loc)
            for w in ws:
                if w!=initial:root &= C(initial,w)
            for a,c,d in permutations(ws,3):root &= ~C(a,c)|~C(c,d)|C(a,d)
            for a,c in permutations(ws,2):root &= ~H(a,c)|C(a,c)
            for r in rs:
                for source in inst.candidates[r]:
                    for w in ws:
                        if source!=w:root &= ~H(w,r)|~rf[source,r]|C(w,source)
                        root &= ~H(r,w)|~rf[source,r]|C(source,w)
            for r,s in permutations(rs,2):
                for a in inst.candidates[r]:
                    for c in inst.candidates[s]:
                        if a!=c:root &= ~H(r,s)|~rf[a,r]|~rf[c,s]|C(a,c)
        b.reorder();b.configure(reordering=False);self.root=root
        self.stats=dict(algorithm='bdd-relational',compile_seconds=perf_counter()-start,
            original_variables=reg.nvars,bdd_nodes=root.dag_size,bdd_manager_nodes=len(b),
            singleton_rf_constant_fold=True,
            original_satisfying_assignments=int(b.count(root,nvars=reg.nvars)),
            original_order=[b.var_at_level(i) for i in range(len(b.vars))])
