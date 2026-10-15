"""Compare the SAME operation: return every forced original literal, or conflict."""
import argparse,hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def worker(spec,path):
    import resource
    os.sched_setaffinity(0,{spec['cpu']})
    resource.setrlimit(resource.RLIMIT_AS,(6*1024**3,)*2)
    from wmcheck.generators import make_instance
    from wmcheck.compiler import compile_instance,ResourceLimit
    from wmcheck.eager import encode
    from wmcheck.graph_solver import GraphSolver
    from wmcheck.complete_query import forced_by_search
    from wmcheck.propagation import unit_propagate
    from experiments.run_suite import queries
    from pysat.solvers import Minisat22
    rec={'spec':spec,'status':'started','operation':'conflict or all forced original literals',
         'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'wmcheck').glob('*.py')}}
    begin=time.perf_counter()
    def save(stage):
        rec['stage']=stage;Path(path).write_text(json.dumps(rec,indent=2))
    try:
        inst=make_instance(rounds=spec['rounds']);save('compile');method=spec['method']
        enc=encode(inst) if method=='eager' else compile_instance(inst,cnf=method!='graph',strong=method!='weak',max_seconds=75)
        rec.update(enc.stats);save('setup')
        qs=queries(inst,enc.registry,32)
        rec['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        if method=='graph': solver=GraphSolver(enc);root=solver.propagate([])[1]
        elif method=='cnf':
            solver=Minisat22(bootstrap_with=enc.clauses)
            up=unit_propagate(enc.clauses)
            root={v if b else -v for v,b in up.values.items() if v in enc.registry.by_id}
        else:
            solver=Minisat22(bootstrap_with=enc.clauses)
            _,root,rec['root_sat_calls']=forced_by_search(solver,enc.registry.by_id)
        rec['ready_seconds']=time.perf_counter()-begin;save('complete_queries');rows=[]
        for alpha in qs:
            start=time.perf_counter();calls=0
            if method=='graph': ok,forced=solver.propagate(alpha)
            elif method=='cnf':
                ok,prop=solver.propagate(assumptions=alpha)
                forced={l for l in prop if abs(l) in enc.registry.by_id}|root if ok else set()
            else: ok,forced,calls=forced_by_search(solver,enc.registry.by_id,alpha,known=root)
            elapsed=time.perf_counter()-start
            rows.append({'assumptions':alpha,'consistent':ok,'forced':sorted(forced),'seconds':elapsed,'sat_calls':calls})
        rec['queries']=rows
        rec['query_seconds']=sum(r['seconds'] for r in rows)
        rec['total_seconds']=rec['ready_seconds']+rec['query_seconds']
        rec['prefix_totals']={str(n):rec['ready_seconds']+sum(r['seconds'] for r in rows[:n]) for n in (1,8,32)}
        rec['sat_calls']=sum(r['sat_calls'] for r in rows)+rec.get('root_sat_calls',0)
        if method!='graph': solver.delete()
        rec['status']='ok'
    except (ResourceLimit,MemoryError) as e:
        rec.update(status='memory_limit' if isinstance(e,MemoryError) else 'resource_limit',reason=str(e))
    except Exception as e: rec.update(status='error',reason=str(e),traceback=traceback.format_exc())
    rec['elapsed_seconds']=time.perf_counter()-begin
    rec['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    Path(path).write_text(json.dumps(rec,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/gap/forced')
    p.add_argument('--rounds',type=int,nargs='+',default=[2,8]);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--worker');p.add_argument('--record');a=p.parse_args()
    if a.worker: worker(json.loads(a.worker),a.record);return
    import random
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    specs=[{'rounds':n,'method':method,'repeat':rep,'cpu':min(os.sched_getaffinity(0))}
           for n in a.rounds for method in ('graph','cnf','weak','eager') for rep in range(a.repeats)]
    random.Random(20261017).shuffle(specs);records=[]
    for j,spec in enumerate(specs):
        dest=out/f'{j:04d}.json'
        try: subprocess.run([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],check=True,timeout=180)
        except subprocess.TimeoutExpired:
            rec=json.loads(dest.read_text()) if dest.exists() else {'spec':spec}
            rec.update(status='timeout',limit_seconds=180);dest.write_text(json.dumps(rec,indent=2))
        rec=json.loads(dest.read_text());records.append(rec)
        print(j,rec['status'],spec,flush=True)
    truth={}
    for r in records:
        if r['status']!='ok': continue
        key=(r['spec']['rounds'],r['query_sha256'])
        answers=[(q['consistent'],q['forced']) for q in r['queries']]
        if key in truth: assert answers==truth[key],'Forced-literal answer mismatch'
        truth[key]=answers
    (out/'summary.json').write_text(json.dumps({'records':len(records),'cross_method_answer_mismatches':0,
        'statuses':{s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})}},indent=2))


if __name__=='__main__': main()
