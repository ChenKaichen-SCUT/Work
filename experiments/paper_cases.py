"""Versioned, deterministic cases and shared query workloads for paper evaluation."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry, producers, pipeline, recognize
from wmcheck.ra_program import RAProgram, parse_c_litmus
from wmcheck.ra_schedule import certificate, OutsideCertificate


def instance(spec):
    family = spec['family']; n = spec.get('n', 1)
    if family == 'producers':
        p = spec.get('writers', 2); t = spec.get('readers', 1); k = spec.get('reads', 2)
        return producers((n,)*p, ((1,)*k,)*t)
    if family == 'pipeline':
        return pipeline(n)
    if family == 'handoff':
        # A one-writer repeated-value publication stream. Two reader threads
        # retain ambiguity over old source identities; no CO is manually fixed.
        return producers((n,), ((1,)*spec.get('reads', 2),)*spec.get('readers', 2))
    if family in ('iriw', 'sb', 'mp', 'lb'):
        pattern = {
            'iriw': [[('W','x',1)], [('W','y',1)], [('R','x',1),('R','y',0)], [('R','y',1),('R','x',0)]],
            'sb': [[('W','x',1),('R','y',0)], [('W','y',1),('R','x',0)]],
            'mp': [[('W','x',1),('W','y',1)], [('R','y',1),('R','x',0)]],
            'lb': [[('R','x',1),('W','y',1)], [('R','y',1),('W','x',1)]]}[family]
        events = [Event('ix','W','x',-1,0),Event('iy','W','y',-1,0)]; threads=[]
        for t, ops in enumerate(pattern):
            seq=[]
            for j,(kind,loc,val) in enumerate(ops):
                eid=f't{t}_{j}'; seq.append(eid); events.append(Event(eid,kind,loc,t,val))
            threads.append(tuple(seq))
        return RAInstance(tuple(events),tuple(threads),('ix','iy'))
    if family == 'non_sc_chain':
        # Concatenated independent IRIW gadgets, each with its own locations.
        # Thread order connects gadgets; within every gadget the selected
        # outcome is allowed by RA and forbidden by SC.
        es=[]; threads=[[] for _ in range(4)]; initial=[]
        for phase in range(n):
            g=instance({'family':'iriw'})
            rename=lambda v:f'g{phase}_{v}'
            for e in g.events:
                es.append(Event(rename(e.id),e.kind,f'g{phase}_{e.loc}',e.thread,e.value))
            initial.extend(map(rename,g.initial))
            for t, seq in enumerate(g.threads): threads[t].extend(map(rename,seq))
        return RAInstance(tuple(es),tuple(map(tuple,threads)),tuple(initial))
    if family == 'public':
        obj=json.loads(Path(spec['input']).read_text())
        i=obj['instance']; return RAInstance(tuple(Event(**e) for e in i['events']),
            tuple(map(tuple,i['threads'])),tuple(i['initial']))
    raise ValueError(family)


def layout(inst, spec):
    if spec['family']=='pipeline':
        return inst.initial+tuple(v for stage in range(1,spec['n']+1) for t in inst.threads
                                 for v in t if v.split('_')[1]==str(stage))
    if spec['family']=='non_sc_chain':
        return tuple(v for phase in range(spec['n']) for v in inst.event if v.startswith(f'g{phase}_'))
    # Round-robin event positions; this is an input layout, not execution order.
    return inst.initial+tuple(t[j] for j in range(max(map(len,inst.threads),default=0))
                             for t in inst.threads if j<len(t))


def workload(inst, count=512, seed=20261015):
    from experiments.construction_suite import queries
    try:
        certificate(inst)
        return queries(inst,RARegistry(inst),count)
    except OutsideCertificate:
        pass
    from wmcheck.ra_sat import encode_ra
    from wmcheck.complete_query import forced_by_search
    from pysat.solvers import Minisat22
    rng=random.Random(seed); e=encode_ra(inst); out=[[]]
    with Minisat22(bootstrap_with=e.clauses) as s:
        ok,root,_=forced_by_search(s,e.registry.by_id)
        if not ok:
            return [[] for _ in range(count)]
        free=[v for v in e.registry.by_id if v not in root and -v not in root]
        for j in range(count-1):
            s.set_phases([v*rng.choice((-1,1)) for v in free]); assert s.solve()
            model={abs(l):l for l in s.get_model() if abs(l) in e.registry.by_id}
            density=(.05,.2,.5,.8)[j%4]
            order=list(free);rng.shuffle(order)
            if j%5==0:
                # Fixed-size subsets of a freshly shuffled variable order.
                # Queries are independent; paper_stress.py supplies genuinely
                # nested push/pop episodes with a shared order and model.
                chosen=order[:int(len(order)*density)]
            else:
                chosen=[v for v in free if rng.random()<density]
            out.append([model[v] if j%4!=3 else v*rng.choice((-1,1)) for v in chosen])
    return out


def interface_profile(inst, spec, cert=None):
    cert=cert or recognize(inst)
    if cert['status']=='PROVED_UNSAT':return dict(width=0,groups=0)
    ends=list(inst.sb)+[(i,t[0]) for i in inst.initial for t in inst.threads if t]
    ends += [(w,r) for r,ws in cert['domains'].items() for w in ws]
    reg=RARegistry(inst);L=cert['L']
    ends += [(a,b) for kind,a,b in reg.by_id.values() if kind=='co' and (a,b) not in L and (b,a) not in L]
    ends += list(cert['successors'])+[(e.id,) for e in inst.events]
    rank={v:i for i,v in enumerate(layout(inst,spec))}
    ends.sort(key=lambda vs:(max(rank[v] for v in vs),min(rank[v] for v in vs)))
    last={v:i for i,vs in enumerate(ends) for v in vs};active=set();width=0
    for i,vs in enumerate(ends):
        active.update(vs);width=max(width,len(active));active={v for v in active if last[v]!=i}
    return dict(width=width,groups=len(ends))


def prepare(out, baseline_root):
    out=Path(out);out.mkdir(parents=True,exist_ok=True); records=[]; public=[]
    corpus=Path(baseline_root)/'Dat3M/litmus/C11'
    for path in sorted(corpus.rglob('*.litmus')):
        source=path.read_text(); row={'path':str(path.relative_to(corpus.parent.parent)),
            'sha256':hashlib.sha256(source.encode()).hexdigest()}
        try:
            program=parse_c_litmus(source); inst=program.conditioned()
            target=out/('public_'+hashlib.sha256(row['path'].encode()).hexdigest()[:12]+'.json')
            target.write_text(json.dumps({'instance':asdict(inst),'source':row,'name':program.name},indent=2))
            row.update(status='accepted',events=len(inst.events),input=target.name)
            public.append(dict(family='public',input=str(target.resolve()),name=program.name))
        except ValueError as exc:
            row.update(status='outside_scope',reason=str(exc))
        records.append(row)
    (out/'coverage.json').write_text(json.dumps(dict(corpus='Dat3M/litmus/C11',manifest=records,
        accepted=len(public),total=len(records),selection='All strictly parsed RA cases; no performance filter'),indent=2))
    specs=[dict(family='producers',n=n) for n in (2,4,8,16,32,64,128)]
    specs += [dict(family='producers',n=4,writers=p) for p in (3,4)]
    specs += [dict(family='producers',n=8,readers=2),dict(family='producers',n=8,reads=8)]
    specs += [dict(family='pipeline',n=n) for n in (1,2,3)]
    specs += [dict(family='non_sc_chain',n=n) for n in (1,2,4,8)]
    specs += [dict(family='handoff',n=n) for n in (4,16,64)]
    specs += [dict(family=f,n=1) for f in ('iriw','sb','mp','lb')]+public
    for i,spec in enumerate(specs):
        spec['id']=f'c{i:03d}'
        inst=instance(spec);reg=RARegistry(inst); cert=recognize(inst)
        spec['events']=len(inst.events);spec['variables']=reg.nvars
        qs=workload(inst); path=out/(spec['id']+'_queries.json');path.write_text(json.dumps(qs))
        spec['queries']=str(path.resolve());spec['query_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        try: certificate(inst);spec['dynamic_certificate']=True
        except OutsideCertificate:spec['dynamic_certificate']=False
        spec['recognition']=dict(status=cert['status'],initial_rf=sum(map(len,inst.candidates.values())),
            certified_rf=sum(map(len,cert['domains'].values())),steps=len(cert['trace']))
        spec['interface']=interface_profile(inst,spec,cert)
    (out/'cases.json').write_text(json.dumps(specs,indent=2))
    return specs
