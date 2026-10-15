"""Targeted evidence gaps: ambiguous non-SC RF and actual nested push/pop queries.

Added after inspecting the protocol, before inspecting their performance.
These are a separately named campaign, never folded into the original plan.
"""
import argparse,hashlib,json,os,random,signal,subprocess,sys
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_suite import save,worker
from experiments.paper_bdd_direct import worker as bdd_worker
from experiments.paper_cases import interface_profile
from wmcheck.ra import RAInstance,RARegistry,producers,recognize
from wmcheck.model import Event


def repeated_iriw(n):
    es=[Event('ix','W','x',-1,0),Event('iy','W','y',-1,0)];ts=[]
    for t,loc in enumerate(('x','y')):
        seq=[]
        for j in range(n):
            v=f'w{t}_{j}';seq.append(v);es.append(Event(v,'W',loc,t,1))
        ts.append(tuple(seq))
    for t,ops in ((2,(('x',1),('y',0))),(3,(('y',1),('x',0)))):
        seq=[]
        for j,(loc,val) in enumerate(ops):
            v=f'r{t}_{j}';seq.append(v);es.append(Event(v,'R',loc,t,val))
        ts.append(tuple(seq))
    return RAInstance(tuple(es),tuple(ts),('ix','iy'))


def nested_queries(inst,count=512):
    from pysat.solvers import Minisat22
    from wmcheck.ra_sat import encode_ra
    from wmcheck.ra_order_sat import encode_order
    from wmcheck.ra_schedule import certificate,OutsideCertificate
    from wmcheck.complete_query import forced_by_search
    try:certificate(inst);e=encode_order(inst)
    except OutsideCertificate:e=encode_ra(inst)
    rng=random.Random(20261017);out=[[]]
    with Minisat22(bootstrap_with=e.clauses) as s:
        ok,root,_=forced_by_search(s,e.registry.by_id)
        if not ok:raise ValueError('Stress inputs must have legal completions')
        free=[v for v in e.registry.by_id if v not in root and -v not in root]
        while len(out)<count:
            s.set_phases([v*rng.choice((-1,1)) for v in free]);assert s.solve()
            model={abs(l):l for l in s.get_model()};vs=free[:];rng.shuffle(vs);vs=vs[:32]
            # A fixed model and fixed order within each episode; every next
            # prefix is genuinely nested. Alternative branches are queried too.
            path=[];out.append([])
            for v in vs:
                out.append(path+[-model[v]]);path.append(model[v]);out.append(path[:])
            for j in range(len(path)-1,-1,-1):out.append(path[:j])
            if not vs:break
    return out[:count]


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/paper/stress');p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--worker');p.add_argument('--record');a=p.parse_args()
    if a.worker:
        s=json.loads(a.worker);(bdd_worker if s['method']=='bdd-relational' else worker)(s,a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);inp=out/'inputs';inp.mkdir(exist_ok=True);cpu=min(os.sched_getaffinity(0))
    cases=[]
    for n in (2,4,8,16):cases.append((f'a{n:03d}',repeated_iriw(n),False,'repeated_iriw',n))
    for n in (8,64):cases.append((f'r{n:03d}',producers((n,n)),True,'producer_replay',n))
    specs=[]
    for cid,inst,pure,label,n in cases:
        f=inp/(cid+'.json');f.write_text(json.dumps(dict(instance=asdict(inst))))
        qs=nested_queries(inst);q=inp/(cid+'_queries.json');q.write_text(json.dumps(qs))
        spec=dict(id=cid,family='public',input=str(f.resolve()),queries=str(q.resolve()),n=n,
            query_sha256=hashlib.sha256(q.read_bytes()).hexdigest(),query_count=len(qs),
            workload='nested push/pop with alternative branches; synthetic, not native solver traces',
            stress_family=label,dynamic_certificate=pure,events=len(inst.events),variables=RARegistry(inst).nvars)
        spec['interface']=interface_profile(inst,spec,recognize(inst));specs.append(spec)
    save(inp/'cases.json',specs)
    save(out/'environment.json',dict(cpu=cpu,isolated=True,repeats=a.repeats,wall_limit_seconds=180,memory_limit_gib=4,
        purpose='Non-SC family with unbounded writes per address and ambiguous RF; real nested synthetic queries',
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ('wmcheck','experiments') for f in (ROOT/d).glob('*.py')}))
    pairs=[(s,m) for s in specs for m in (('sat','dynamic','grid') if s['dynamic_certificate'] else ('sat','frontier','bdd-relational'))]
    random.Random(20261017).shuffle(pairs);index=0
    for case,method in pairs:
        for repeat in range(a.repeats):
            spec=dict(case,method=method,repeat=repeat,cpu=cpu,compile_seconds=120);dest=out/f'{index:04d}.json'
            proc=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                o,e=proc.communicate(timeout=180)
                if proc.returncode:
                    r=json.loads(dest.read_text());r.update(status='ERROR',returncode=proc.returncode,stderr=e);save(dest,r)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.communicate();r=json.loads(dest.read_text());r.update(status='UNKNOWN',reason='wall_timeout_180s');save(dest,r)
            r=json.loads(dest.read_text());print(index,case['id'],method,r['status'],flush=True);index+=1
            if r['status']!='ok':break


if __name__=='__main__':main()
