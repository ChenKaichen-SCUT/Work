"""Isolated experiment workers with affinity, memory limits and raw records.

Run: python experiments/run_suite.py --out results/main --jobs 3 --repeats 3
Parallel jobs use distinct logical CPUs; final serial confirmation is separate.
"""
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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def queries(inst,registry,count=32):
    free=[v for v,(kind,a,b) in registry.by_id.items()
          if kind=='co' or len(inst.candidates[b])>1]
    rng=random.Random(20261015)
    out=[[]]
    rounds=inst.metadata['rounds']
    if rounds>=2:
        reads=[e for e in inst.events if e.kind=='R' and inst.layer[e.id]==rounds and e.loc not in inst.metadata['flag_locations']]
        for r in reads:
            ws=[w for w in inst.candidates[r.id] if inst.layer[w]==rounds-1]
            if len(ws)>=2:
                a,b=ws[:2];rf=registry.literal(('rf',a,r.id));co=registry.literal(('co',a,b))
                if type(rf) is int and type(co) is int: out.extend([[rf,co],[rf,-co]])
    for _ in range(count-len(out)):
        out.append([v*rng.choice((-1,1)) for v in free if rng.random()<min(.25,5/max(1,len(free)))])
    return out


def worker(spec,outpath):
    if spec.get('cpu') is not None and hasattr(os,'sched_setaffinity'): os.sched_setaffinity(0,{spec['cpu']})
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(spec.get('memory_gb',6)*1024**3,)*2)
    except ImportError: resource=None
    from wmcheck.generators import make_instance
    from wmcheck.compiler import compile_instance,ResourceLimit
    from wmcheck.eager import encode
    from pysat.solvers import Minisat22
    import pysat
    result={'spec':spec,'status':'started','python':sys.version.split()[0],
            'python_sat':pysat.__version__,'backend':'Minisat22','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    begin=time.perf_counter()
    def checkpoint(stage):
        result['stage']=stage
        Path(outpath).write_text(json.dumps(result,indent=2),encoding='utf-8')
    try:
        inst=make_instance(**spec['parameters']);result['recognize_seconds']=time.perf_counter()-begin
        result['events']=len(inst.events)
        checkpoint('compile')
        enc=encode(inst) if spec['method']=='eager' else compile_instance(inst,
            merge=spec['method']!='no_merge',strong=spec['method']!='weak',
            max_states=20000,max_transitions=300000,max_local_choices=100000,max_seconds=spec.get('compile_limit',75))
        result.update(enc.stats)
        qs=queries(inst,enc.registry,spec.get('queries',32))
        result['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        checkpoint('sat_setup')
        t=time.perf_counter();solver=Minisat22(bootstrap_with=enc.clauses)
        result['sat_setup_seconds']=time.perf_counter()-t
        cold=qs[1] if spec.get('scenario')=='unsat' and len(qs)>1 else []
        checkpoint('cold_solve')
        t=time.perf_counter();result['cold_sat']=solver.solve(assumptions=cold)
        result['cold_solve_seconds']=time.perf_counter()-t
        result['cold_total_seconds']=time.perf_counter()-begin
        result['cold_stats']=solver.accum_stats()
        checkpoint('incremental_queries')
        # Never perform solve() on this raw-UP solver: no learned-clause pollution.
        raw=Minisat22(bootstrap_with=enc.clauses)
        records=[]
        for alpha in qs:
            t=time.perf_counter();ok,implied=raw.propagate(assumptions=alpha);up_s=time.perf_counter()-t
            t=time.perf_counter();sat=solver.solve(assumptions=alpha);solve_s=time.perf_counter()-t
            if not ok and sat: raise AssertionError('UP incorrectly rejected a SAT query')
            if spec['method'] in ('proposed','no_merge') and ok!=sat:
                raise AssertionError('Complete propagation missed conflict')
            records.append({'assumptions':alpha,'sat':sat,'up_conflict':not ok,
                            'up_seconds':up_s,'solve_seconds':solve_s,
                            'additional_original_literals':len({l for l in implied if abs(l)<=enc.registry.nvars}-set(alpha))})
        result['queries']=records
        result['incremental_solve_seconds']=sum(x['solve_seconds'] for x in records)
        result['raw_up_seconds']=sum(x['up_seconds'] for x in records)
        result['unsat_queries']=sum(not x['sat'] for x in records)
        result['up_conflicts']=sum(x['up_conflict'] for x in records)
        result['final_stats']=solver.accum_stats();solver.delete();raw.delete()
        result['status']='ok'
    except (ResourceLimit,MemoryError) as exc:
        result['status']='memory_limit' if isinstance(exc,MemoryError) else 'resource_limit'
        result['reason']=str(exc)
    except Exception as exc:
        result['status']='error';result['reason']=str(exc);result['traceback']=traceback.format_exc()
    result['elapsed_seconds']=time.perf_counter()-begin
    if resource: result['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    Path(outpath).write_text(json.dumps(result,indent=2),encoding='utf-8')


def specifications(repeats,mode):
    specs=[]
    if mode=='unsat':
        for n in (2,8,16):
            for method in ('proposed','eager'):
                for rep in range(repeats):
                    specs.append({'family':'cold_unsat','parameters':{'rounds':n},'method':method,'repeat':rep,'scenario':'unsat'})
    if mode in ('main','smoke','serial','cold_long'):
        lengths=[1,2,4,8,16,32,64] if mode=='main' else ([1,2,4] if mode=='smoke' else ([8,16] if mode=='serial' else [32,64]))
        for n in lengths:
            for method in (('proposed','eager') if mode in ('serial','cold_long') else ('proposed','eager','weak')):
                for rep in range(repeats):
                    spec={'family':'length','parameters':{'rounds':n},'method':method,'repeat':rep}
                    if mode=='cold_long': spec['queries']=0
                    specs.append(spec)
        if mode=='main':
            for n in (1,2,3,4,5):
                for method in ('proposed','no_merge'):
                    for rep in range(repeats):
                        specs.append({'family':'merging','parameters':{'rounds':n},'method':method,'repeat':rep})
            for p,d,reads in ((2,2,2),(3,2,2),(4,2,2),(5,2,2),(6,2,2),(4,1,2),(4,4,2),(4,2,4)):
                for method in ('proposed','eager'):
                    for rep in range(repeats):
                        specs.append({'family':'width','parameters':{'rounds':3,'threads':p,'addresses':d,'readers':reads},'method':method,'repeat':rep})
    random.Random(20261015).shuffle(specs)
    return specs


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/main');p.add_argument('--jobs',type=int,default=3)
    p.add_argument('--repeats',type=int,default=3);p.add_argument('--mode',choices=['main','smoke','serial','cold_long','unsat'],default='main')
    p.add_argument('--timeout',type=int,default=150);p.add_argument('--worker');p.add_argument('--record')
    a=p.parse_args()
    if a.worker: worker(json.loads(a.worker),a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    cpus=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else [None]*a.jobs
    available=queue.Queue()
    for cpu in cpus[:a.jobs]: available.put(cpu)
    specs=specifications(a.repeats,a.mode)
    env={'platform':platform.platform(),'machine':platform.machine(),'python':sys.version,
         'jobs':a.jobs,'cpu_affinity_pool':cpus[:a.jobs],'timeout_seconds':a.timeout,'memory_gb_per_worker':6,
         'clock':'perf_counter wall clock','mode':a.mode,'repeats':a.repeats,'seed':20261015,
         'notes':'Parallel jobs are pinned to distinct logical CPUs; shared-memory/host interference remains possible.'}
    if Path('/proc/cpuinfo').exists():
        env['cpu_model']=next((x.split(':',1)[1].strip() for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')),None)
    (out/'environment.json').write_text(json.dumps(env,indent=2),encoding='utf-8')
    def run(index,spec):
        cpu=available.get();spec=dict(spec,cpu=cpu,memory_gb=6)
        dest=out/f'{index:04d}.json';log=out/f'{index:04d}.log'
        try:
            with log.open('w',encoding='utf-8') as f:
                proc=subprocess.run([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],
                    stdout=f,stderr=subprocess.STDOUT,timeout=a.timeout)
            if not dest.exists():
                dest.write_text(json.dumps({'spec':spec,'status':'process_failed','exit_code':proc.returncode}),encoding='utf-8')
        except subprocess.TimeoutExpired:
            partial=json.loads(dest.read_text()) if dest.exists() else {'spec':spec}
            partial.update(status='timeout',limit_seconds=a.timeout)
            dest.write_text(json.dumps(partial),encoding='utf-8')
        finally: available.put(cpu)
        record=json.loads(dest.read_text());print(index,record['status'],spec['family'],spec['method'],spec['parameters'],flush=True)
        return record
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results=[f.result() for f in as_completed([pool.submit(run,i,s) for i,s in enumerate(specs)])]
    (out/'summary.json').write_text(json.dumps({'records':len(results),'statuses':{s:sum(r['status']==s for r in results) for s in sorted({r['status'] for r in results})}},indent=2),encoding='utf-8')


if __name__=='__main__': main()
