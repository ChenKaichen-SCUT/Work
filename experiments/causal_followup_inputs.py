"""Fixed, irredundant original-literal workloads; generation is outside timing."""
import json
import random
import sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest
from wmcheck.ra_protocols import barrier_instance,buffer_instance,build_protocol
from wmcheck.ra import RARegistry
from wmcheck.ra_support_sat import SupportSAT

OUT=ROOT/'results/causal_followup_20261028'


def instance(family,n):
    if family=='barrier':return barrier_instance(n)
    if family=='buffer':return buffer_instance(n,capacity=3,mode='branch')
    raise ValueError(family)


def generate(family,n):
    inp=instance(family,n);pre=build_protocol(inp);reg=RARegistry(inp.inst)
    rng=random.Random(271828+n+(1000 if family=='buffer' else 0))
    with SupportSAT(inp,certificate=pre['certificate']) as oracle:
        sat,supported=oracle.all_support()
        assert sat
        free={v for v in reg.by_id if v in supported and -v in supported}
        stages=pre['stages'];by_stage={}
        representatives=set()
        for r,domain in pre['certificate']['domains'].items():
            if len(domain)>1:
                # For two-source reads, use one Boolean coordinate, not both aliases.
                ws=sorted(domain)
                selected=ws[:1] if len(ws)==2 else ws
                representatives.update(reg.literal(('rf',w,r)) for w in selected)
        representatives|={v for v,(kind,_,_) in reg.by_id.items() if kind=='co' and v in free}
        representatives &= free
        for v in sorted(representatives):
            _,a,b=reg.by_id[v]
            by_stage.setdefault(stages[b],[]).extend((v,-v))
        signs=sorted(v for x in representatives for v in (x,-x))
        pairs=[(a,b) for ix,a in enumerate(signs) for b in signs[ix+1:] if abs(a)!=abs(b)]
        rng.shuffle(pairs);unsat=[]
        for pair in pairs:
            # Buffer contradictions must link different reads, not two sources of one read.
            if family=='buffer' and reg.by_id[abs(pair[0])][2]==reg.by_id[abs(pair[1])][2]:continue
            if not oracle.solve(pair):
                assert all(oracle.solve((lit,)) for lit in pair)
                unsat.append(tuple(sorted(pair)))
                if len(unsat)==10:break
        assert len(unsat)==10
        yes=[];seen=set();attempts=0
        while len(yes)<990:
            attempts+=1
            if attempts>200000:raise RuntimeError('No sufficiently varied irredundant pool')
            if family=='barrier':
                chosen=rng.sample(sorted(by_stage),4)
                alpha=tuple(sorted(rng.choice(by_stage[s]) for s in chosen))
            else:alpha=tuple(sorted(rng.sample(signs,4)))
            if len(set(map(abs,alpha)))!=4 or alpha in seen:continue
            seen.add(alpha)
            if not oracle.solve(alpha):continue
            # Every literal must rule out a previously possible completion.
            if not all(oracle.solve(tuple(x for x in alpha if x!=lit)+(-lit,)) for lit in alpha):continue
            yes.append(alpha)
    manifest=dict(family=family,rounds=n,input_sha256=digest(inp),unfixed_originals=len(free),
        representative_variables=len(representatives),sat_pool_size=len(yes),unsat_minimal_pairs=len(unsat),
        generation_attempts=attempts,all_sat_assumptions_irredundant=True,
        all_literals_have_both_root_supports=True,seed=271828+n+(1000 if family=='buffer' else 0),
        rule='990 satisfiable requests of length 4; 10 distinct minimal contradictory pairs; exact 1% UNSAT in every workload',
        no_constant_padding=True,no_literal_permutation_padding=True)
    save(OUT/'workloads'/f'{family}_{n}_pool.json',dict(manifest=manifest,sat=yes,unsat=unsat,
         decoded_unsat=[[reg.by_id[abs(lit)]+(lit>0,) for lit in pair] for pair in unsat]))
    for u in (21,100,500,1000):
        pool=yes[:u-10];queries=[];si=ui=0
        for j in range(1000):
            fail=j%100==99
            alpha=unsat[ui] if fail else pool[si%len(pool)]
            if fail:ui+=1
            else:si+=1
            queries.append(dict(assumptions=alpha,expected_sat=not fail))
        assert len({tuple(q['assumptions']) for q in queries})==u
        save(OUT/'workloads'/f'{family}_{n}_U{u}.json',dict(**manifest,U=u,Q=1000,queries=queries,
             workload_sha256=digest(queries),request_length_counts=dict(Counter(len(q['assumptions']) for q in queries))))
    print('workloads',family,n,manifest,flush=True)


if __name__=='__main__':
    for family,n in (('barrier',8),('barrier',16),('buffer',8)):generate(family,n)
