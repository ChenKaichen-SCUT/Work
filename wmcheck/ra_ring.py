"""Directed-ring publication kernel, not an extracted industrial algorithm.

Worker t updates its own slot, publishes, updates its successor's slot, publishes
again, and observes its predecessor's previous phase. Each payload has two
writers; each flag has one writer. Three or more workers change both the
synchronization topology and the route needed to derive common causality.
"""
from .model import Event
from .ra import RAInstance


def publication_ring(rounds,workers=3,copies=2,payload='epoch',irregular=False):
    if rounds<1 or workers<3 or copies<2:raise ValueError('Expected rounds>=1, workers>=3, copies>=2')
    if payload not in ('constant','epoch'):raise ValueError('Unknown payload')
    locs=tuple(f'x{t}' for t in range(workers))+tuple(f'f{t}' for t in range(workers))
    initial=tuple('i'+loc for loc in locs)
    events=[Event('i'+loc,'W',loc,-1,0) for loc in locs];threads=[]
    for t in range(workers):
        seq=[]
        for i in range(1,rounds+1):
            value=i if payload=='epoch' else 1;m=copies+int(irregular and (i+t)%2==0)
            ops=[('W',f'x{t}',value,'own'),('W',f'f{t}',i%2,'pub0'),
                 ('W',f'x{(t+1)%workers}',value,'next')]
            ops += [('W',f'f{t}',i%2,f'pub{j}') for j in range(1,m)]
            ops += [('R',f'f{(t-1)%workers}',(i-1)%2,'wait'),('R',f'x{t}',value,'read')]
            for kind,loc,val,suffix in ops:
                eid=f't{t}_{i}_{suffix}';seq.append(eid);events.append(Event(eid,kind,loc,t,val))
        threads.append(tuple(seq))
    return RAInstance(tuple(events),tuple(threads),initial)


def ring_layout(inst):
    return inst.initial+tuple(sorted((e.id for e in inst.events if e.id not in inst.initial),
        key=lambda e:(int(e.split('_')[1]),inst.event[e].thread,inst.threads[inst.event[e].thread].index(e))))


def ring_witness(inst,rounds,workers=3,late=False):
    rf={};orders={}
    for t in range(workers):
        prev=(t-1)%workers
        for i in range(1,rounds+1):
            rf[f't{t}_{i}_read']=f't{t}_{i}_own'
            pubs=[e for e in inst.threads[prev] if e.startswith(f't{prev}_{i-1}_pub')]
            rf[f't{t}_{i}_wait']='i'+f'f{prev}' if i==1 else pubs[-1 if late else 0]
        orders[f'f{t}']=('i'+f'f{t}',)+tuple(e for e in inst.threads[t] if '_pub' in e)
        orders[f'x{t}']=('i'+f'x{t}',)+tuple(e for i in range(1,rounds+1)
            for e in (f't{prev}_{i}_next',f't{t}_{i}_own'))
    return rf,orders


def ring_queries(reg,rounds,workers=3):
    result=[dict(name='root',assumptions=[])]
    for i in range(2,rounds+1):
        for t in range(workers):
            prev=(t-1)%workers
            own=reg.literal(('rf',f't{t}_{i}_own',f't{t}_{i}_read'))
            early=reg.literal(('rf',f't{prev}_{i-1}_pub0',f't{t}_{i}_wait'))
            late=reg.literal(('rf',f't{prev}_{i-1}_pub1',f't{t}_{i}_wait'))
            co=reg.literal(('co',f't{prev}_{i-1}_next',f't{t}_{i}_own'))
            for name,alpha in [('early',[own,early]),('late',[own,late]),('early_inverted',[own,early,-co]),
                               ('late_inverted',[own,late,-co]),('withdraw',[own])]:
                result.append(dict(name=f's{i}_t{t}_{name}',assumptions=alpha,target=co))
    return result
