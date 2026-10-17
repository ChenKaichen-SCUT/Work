"""Independent premise, span and group-liveness checks for the theorem.

Reuses the recognizer under audit, but independently enumerates its obligations
and candidate incidences. This is finite falsification evidence, not a proof.
"""
import argparse,json,sys
from itertools import combinations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import RAInstance,recognize
from wmcheck.ra_ring import publication_ring,ring_layout
from wmcheck.ra_publication import publication_exchange,publication_layout
from wmcheck.model import Event
from wmcheck.ra_oracle import valid


def stage(v):return int(v.split('_')[1])


def inspect(inst,rounds,flags,links,gap=1):
    p=len(inst.threads);assert set(flags)==set(range(p));assert all(u!=v for u,v in links)
    distances={}
    for t in range(p):
        seen={t:0};todo=[t]
        for u in todo:
            for a,b in links:
                if a==u and b not in seen:seen[b]=seen[u]+1;todo.append(b)
        assert len(seen)==p;distances[t]=seen
    diameter=max(v for ds in distances.values() for v in ds.values());h=2*diameter+1;delta=2*h+gap
    initial=set(inst.initial);noninit=[v for v in inst.event if v not in initial]
    assert set(map(stage,noninit))==set(range(1,rounds+1))
    for seq in inst.threads:assert list(map(stage,seq))==sorted(map(stage,seq))
    b=max(sum(stage(v)==i for v in noninit) for i in range(1,rounds+1));blocks={};reads={}
    for t,flag in flags.items():
        assert inst.event[next(i for i in initial if inst.event[i].loc==flag)].value==0
        assert all(inst.event[v].thread==t for v in inst.writes if v not in initial and inst.event[v].loc==flag)
        for i in range(1,rounds+1):
            block=[v for v in inst.threads[t] if stage(v)==i and inst.event[v].kind=='W' and inst.event[v].loc==flag]
            assert len(block)>=2 and all(inst.event[v].value==i%2 for v in block);blocks[t,i]=block
    for t,seq in enumerate(inst.threads):
        incoming={u for u,v in links if v==t}
        for i in range(1,rounds+1):
            actual=[v for v in seq if stage(v)==i and inst.event[v].kind=='R' and inst.event[v].loc in flags.values()]
            assert len(actual)==len(incoming)
            for u in incoming:
                rs=[v for v in actual if inst.event[v].loc==flags[u]];assert len(rs)==1
                r=rs[0];reads[u,t,i]=r
                assert inst.event[r].value==(i-1)%2 and seq.index(blocks[t,i][-1])<seq.index(r)
    data_locs={inst.event[v].loc for v in noninit}-set(flags.values())
    for loc in data_locs:
        access=[stage(v) for v in noninit if inst.event[v].loc==loc]
        writes={stage(v) for v in noninit if inst.event[v].loc==loc and inst.event[v].kind=='W'}
        for start in range(min(access),max(access)-gap+2):
            assert any(j in writes for j in range(start,start+gap)),('coverage',loc,start,gap)
    cert=recognize(inst,source_covers=True);assert cert['status']=='RECOGNIZED'
    D,H,L=cert['domains'],cert['H'],cert['L']
    for (u,t,i),r in reads.items():
        allowed=set(blocks[u,i-1]) if i>1 else {v for v in initial if inst.event[v].loc==flags[u]}
        assert D[r] and D[r]<=allowed
        if i>1:assert (blocks[u,i-1][0],r) in H
    for u in noninit:
        for v in noninit:
            if stage(v)-stage(u)>=h:assert (u,v) in H,(u,v,'causal separator')
    pairs=[];binary=[];atomic=[]
    def add(kind,vertices):
        pairs.append((kind,vertices));binary.append(vertices);atomic.append(vertices)
    for u,v in inst.sb:add('sb',(u,v))
    for init in initial:
        for seq in inst.threads:add('init',(init,seq[0]))
    for r,ws in D.items():
        for w in ws:pairs.append(('rf',(w,r)));binary.append((w,r))
        atomic.append((r,*ws))
    unresolved=0
    for loc in {inst.event[v].loc for v in inst.writes}:
        ws=[v for v in inst.writes if inst.event[v].loc==loc]
        for u,v in combinations(ws,2):
            if (u,v) not in L and (v,u) not in L:add('undecided_co',(u,v));unresolved+=1
        for u in ws:
            for v in ws:
                if (u,v) in L and not any((u,z) in L and (z,v) in L for z in ws):add('cover_co',(u,v))
    maxspan={}
    for kind,vertices in pairs:
        if any(v in initial for v in vertices):continue
        distance=abs(stage(vertices[0])-stage(vertices[1]));maxspan[kind]=max(distance,maxspan.get(kind,0))
        assert distance<=delta,(kind,vertices,distance,delta)
    for vertices in atomic:
        stages=[stage(v) for v in vertices if v not in initial]
        assert not stages or max(stages)-min(stages)<=2*delta
    order=inst.initial+tuple(sorted(noninit,key=lambda v:(stage(v),inst.event[v].thread,inst.threads[inst.event[v].thread].index(v))))
    rank={v:j for j,v in enumerate(order)}
    def width(groups):
        groups=groups+[(v,) for v in inst.event]
        groups=sorted(groups,key=lambda vs:(max(rank[v] for v in vs),min(rank[v] for v in vs)))
        last={v:j for j,vs in enumerate(groups) for v in vs};active=set();maximum=0
        for j,vs in enumerate(groups):
            active.update(vs);maximum=max(maximum,len(active));active={v for v in active if last[v]>j}
        return maximum
    old=recognize(inst)
    old_unresolved=sum((u,v) not in old['L'] and (v,u) not in old['L']
        for u,v in combinations(inst.writes,2) if inst.event[u].loc==inst.event[v].loc)
    k=(delta+1)*b+len(initial);ka=(2*delta+1)*b+len(initial)
    bw,aw=width(binary),width(atomic);assert bw<=k and aw<=ka
    return dict(rounds=rounds,workers=p,diameter=diameter,b=b,a=len(initial),G=gap,h=h,delta=delta,
        binary_bound=k,atomic_bound=ka,binary_observed_width=bw,atomic_observed_width=aw,
        maximum_noninitial_candidate_spans=maxspan,unresolved_co=unresolved,k0_unresolved_co=old_unresolved,
        ambiguous_sync_reads=sum(len(D[r])>1 for r in reads.values()),all_obligations_pass=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for workers,n,irregular in ((3,2,False),(3,4,False),(3,8,False),(3,16,False),(3,4,True),(4,3,False),(5,3,False)):
        inst=publication_ring(n,workers,irregular=irregular)
        rows.append(dict(family='ring',irregular=irregular,**inspect(inst,n,{t:f'f{t}' for t in range(workers)},
            {(t,(t+1)%workers) for t in range(workers)})))
    for n in (2,4,8,16,32):
        rows.append(dict(family='exchange',**inspect(publication_exchange(n,payload='epoch'),n,{0:'fa',1:'fb'},{(0,1),(1,0)})))
    # Check the interval arithmetic independently of the graph/kernel routines.
    intervals=0
    for d in range(1,7):
        for g in range(1,8):
            h=2*d+1;delta=2*h+g
            for j in range(delta+2,delta+12):
                i=1
                for z in range(j-h-g+1,j-h+1):assert z-i>=h and j-z>=h;intervals+=1
                for z in range(i+h,i+h+g):assert z-i>=h and j-z>=h;intervals+=1
    # Without the complete read chain, a prefix may read a later 0/1 block.
    es=(Event('i','W','f',-1,0),Event('w1','W','f',0,1),Event('w2','W','f',0,0),
        Event('w3','W','f',0,1),Event('r1','R','f',1,0),Event('r2','R','f',1,1))
    prefix=RAInstance(es,(('w1','w2','w3'),('r1','r2')),('i',))
    assert valid(prefix,{'r1':'w2','r2':'w3'},{'f':('i','w1','w2','w3')})
    # Remove intermediate payload accesses: G=1 must be rejected by the premise checker.
    inst=publication_ring(16);keep={v for v,e in inst.event.items() if v in inst.initial or e.loc.startswith('f') or stage(v) in (1,16)}
    thin=RAInstance(tuple(e for e in inst.events if e.id in keep),tuple(tuple(v for v in seq if v in keep) for seq in inst.threads),inst.initial)
    rejected=False
    try:inspect(thin,16,{t:f'f{t}' for t in range(3)},{(0,1),(1,2),(2,0)},1)
    except AssertionError as e:
        assert e.args and e.args[0][0]=='coverage';rejected=True
    assert rejected
    corrected=inspect(thin,16,{t:f'f{t}' for t in range(3)},{(0,1),(1,2),(2,0)},15)
    assert corrected['maximum_noninitial_candidate_spans']['cover_co']>11
    result=dict(structural_cases=rows,integer_interval_checks=intervals,
        incomplete_prefix_counterexample=dict(rf={'r1':'w2','r2':'w3'},independent_ra_valid=True),
        sparse_write_counterexample=dict(G1_rejected=True,correct_G15=corrected),
        scope='Finite independent premise/span checks, not a formal proof or an external human review')
    (out/'structure_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('Structure cases',len(rows),'interval checks',intervals,flush=True)


if __name__=='__main__':main()
