"""Versioned, isolated before/after comparisons, including compilation cost."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import random
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]


def worker(spec,out,reference):
    if spec.get('cpu') is not None: os.sched_setaffinity(0,{spec['cpu']})
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(6*1024**3,)*2)
    source=Path(reference) if spec['method']=='v1' else ROOT
    sys.path.insert(0,str(source))
    from wmcheck.generators import make_instance
    from wmcheck.compiler import compile_instance,ResourceLimit
    from wmcheck.eager import encode
    from experiments.run_suite import queries
    from pysat.solvers import Minisat22
    import pysat
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((source/'wmcheck').glob('*.py'))}
    record={'spec':spec,'source_sha256':hashes,'python':sys.version.split()[0],
            'python_sat':pysat.__version__,'status':'started',
            'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    def checkpoint(stage):
        record['stage']=stage
        Path(out).write_text(json.dumps(record,indent=2))
    begin=time.perf_counter()
    try:
        inst=make_instance(**spec['parameters'])
        record['recognize_seconds']=time.perf_counter()-begin;record['events']=len(inst.events)
        method=spec['method'];checkpoint('compile')
        if method=='eager': enc=encode(inst)
        else:
            options={'max_seconds':75,'max_states':20000,'max_transitions':300000}
            if method!='v1': options.update(cnf=method!='graph',strong=method!='weak')
            if method=='full_interface': options['directional']=False
            enc=compile_instance(inst,**options)
        record.update(enc.stats)
        qs=queries(inst,enc.registry,spec.get('queries',128))
        record['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        cold=qs[1] if spec.get('scenario')=='unsat' else []
        checkpoint('setup');start=time.perf_counter()
        if method=='graph':
            from wmcheck.graph_solver import GraphSolver
            solver=GraphSolver(enc)
        else: solver=Minisat22(bootstrap_with=enc.clauses)
        record['setup_seconds']=time.perf_counter()-start
        checkpoint('cold');start=time.perf_counter()
        record['cold_sat']=solver.propagate(cold)[0] if method=='graph' else solver.solve(assumptions=cold)
        record['cold_solve_seconds']=time.perf_counter()-start
        record['cold_total_seconds']=time.perf_counter()-begin
        checkpoint('queries');rows=[]
        raw=Minisat22(bootstrap_with=enc.clauses) if method!='graph' else None
        for alpha in qs:
            start=time.perf_counter()
            if method=='graph': sat,forced=solver.propagate(alpha)
            else: sat=solver.solve(assumptions=alpha)
            answer=time.perf_counter()-start
            if raw:
                start=time.perf_counter();ok,forced=raw.propagate(assumptions=alpha)
                propagation=time.perf_counter()-start
            else: ok=sat;propagation=answer
            assert ok or not sat
            if method not in ('eager','weak'): assert ok==sat
            rows.append({'assumptions':alpha,'sat':sat,'up_conflict':not ok,
                         'answer_seconds':answer,'propagation_seconds':propagation})
        if raw: raw.delete();record['sat_stats']=solver.accum_stats();solver.delete()
        record['queries']=rows
        record['query_answer_seconds']=sum(q['answer_seconds'] for q in rows)
        record['query_propagation_seconds']=sum(q['propagation_seconds'] for q in rows)
        record['total_with_queries_seconds']=record['cold_total_seconds']+record['query_answer_seconds']
        record['unsat_queries']=sum(not q['sat'] for q in rows)
        record['up_conflicts']=sum(q['up_conflict'] for q in rows)
        record['status']='ok'
    except (ResourceLimit,MemoryError) as exc:
        record.update(status='memory_limit' if isinstance(exc,MemoryError) else 'resource_limit',reason=str(exc))
    except Exception as exc:
        record.update(status='error',reason=str(exc),traceback=traceback.format_exc())
    record['elapsed_seconds']=time.perf_counter()-begin
    record['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    Path(out).write_text(json.dumps(record,indent=2))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',default='results/gap/serial');p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--reference-root')
    p.add_argument('--mode',choices=('main','wide','ablation'),default='main')
    p.add_argument('--worker');p.add_argument('--record');a=p.parse_args()
    if a.worker: worker(json.loads(a.worker),a.record,a.reference_root);return
    if a.mode=='main' and not a.reference_root: p.error('main requires the archived v1 source root')
    if a.mode=='main':
        cases=[({'rounds':n},'sat') for n in (2,8,16)]
        cases += [({'rounds':3,'threads':5},'sat'),({'rounds':8},'unsat')]
        methods=('v1','cnf','graph','eager')
    elif a.mode=='wide':
        cases=[({'rounds':3,'threads':6},'sat'),({'rounds':3,'readers':4},'sat')]
        methods=('graph','eager')
    else:
        cases=[({'rounds':8},'sat'),({'rounds':3,'threads':5},'sat')]
        methods=('full_interface','weak','cnf')
    specs=[{'parameters':params,'scenario':scenario,'method':method,'repeat':rep,'queries':128}
           for params,scenario in cases for method in methods for rep in range(a.repeats)]
    random.Random(20261016).shuffle(specs)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    cpus=sorted(os.sched_getaffinity(0));available=queue.Queue()
    for cpu in cpus[:a.jobs]: available.put(cpu)
    env={'platform':platform.platform(),'python':sys.version,'jobs':a.jobs,
         'cpu_pool':cpus[:a.jobs],'timeout_seconds':180,'memory_gb_per_worker':6,
         'repeats':a.repeats,'mode':a.mode,'seed':20261016,
         'v1_published_commit':'fc28999afa20d5ba8267c7e46f3cf9d221590b49',
         'notes':('Single worker; the reported campaign runs this after other experiment jobs finish.' if a.jobs==1 else 'Parallel sensitivity run; not an isolated timing confirmation.')+' Timed cold totals include compilation; additional raw-UP audit time is excluded from total_with_queries_seconds.'}
    (out/'environment.json').write_text(json.dumps(env,indent=2))
    def run(j,spec):
        spec=dict(spec,cpu=available.get());dest=out/f'{j:04d}.json'
        args=[sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)]
        if a.reference_root: args += ['--reference-root',a.reference_root]
        try:
            subprocess.run(args,check=True,timeout=180,stdout=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            rec=json.loads(dest.read_text()) if dest.exists() else {'spec':spec}
            rec.update(status='timeout',limit_seconds=180);dest.write_text(json.dumps(rec,indent=2))
        finally: available.put(spec['cpu'])
        rec=json.loads(dest.read_text());print(j,rec['status'],spec,flush=True)
        return rec
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        records=[f.result() for f in as_completed([pool.submit(run,j,s) for j,s in enumerate(specs)])]
    reference_answers={}
    for r in records:
        if r['status']!='ok': continue
        key=(json.dumps(r['spec']['parameters'],sort_keys=True),r['spec']['scenario'],r['query_sha256'])
        answers=[r['cold_sat']]+[q['sat'] for q in r['queries']]
        if key in reference_answers: assert reference_answers[key]==answers,'Version/baseline answer mismatch'
        reference_answers[key]=answers
    summary={'records':len(records),'statuses':{s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})},
             'cross_method_answer_mismatches':0}
    (out/'summary.json').write_text(json.dumps(summary,indent=2))


if __name__=='__main__': main()
