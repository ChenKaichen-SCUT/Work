"""Paper evaluation: isolated compilation, complete support, UP and integration.

Run prepare once, then pilot/primary/ablation/boolean. Every case/method is a
separate process. Timeouts retain completed query prefixes; never fabricate a
final answer or replace a resource failure by UNSAT.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import signal
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_cases import instance, layout, prepare


def save(path, record):
    p=Path(path);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2));temp.replace(p)


def worker(spec, dest):
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    if 'cpu' in spec:os.sched_setaffinity(0,{spec['cpu']})
    from wmcheck.ra_order_sat import encode_order
    from wmcheck.ra_sat import encode_ra
    from wmcheck.ra_schedule import compile_schedule,compile_co_first
    from wmcheck.ra_frontier import compile_frontier
    from wmcheck.ra_grid import compile_grid,GridSolver,grid_cnf
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.ra_bdd import BDDCompiler
    from wmcheck.complete_query import forced_by_search
    from wmcheck.propagation import unit_propagate
    from wmcheck.compiler import ResourceLimit
    from pysat.solvers import Minisat22
    rec=dict(spec=spec,status='running',stage='input');save(dest,rec);start=time.perf_counter()
    try:
        inst=instance(spec);method=spec['method'];limit=spec.get('compile_seconds',120)
        rec['stage']='compile';save(dest,rec)
        options=dict(max_states=200000,max_edges=600000,max_seconds=limit)
        if method.startswith('frontier'):
            c=compile_frontier(inst,order=layout(inst,spec),cnf=method.endswith('-cnf'),
                incremental=method!='frontier-full',compact=method!='frontier-dfa',
                merge=method!='frontier-unfold',**options)
        elif method in ('dynamic','dynamic-cnf','unfold'):
            c=compile_schedule(inst,cnf=method.endswith('-cnf'),merge=method!='unfold',**options)
        elif method=='co-first': c=compile_co_first(inst,**options)
        elif method in ('grid','grid-cnf'):
            c=compile_grid(inst,**options)
            if method=='grid-cnf': raw=c;c=grid_cnf(c)
        else:
            e=encode_order(inst) if spec['dynamic_certificate'] else encode_ra(inst)
            c=BDDCompiler(e,reorder=method!='bdd-fixed') if method.startswith('bdd') else e
        rec.update(c.stats);rec['stage']='setup';save(dest,rec)
        setup=time.perf_counter();nvars=c.registry.nvars;known=set();rootok=True
        native=method in ('sat','dynamic-cnf','frontier-cnf','grid-cnf','sat-up')
        if native:
            solver=Minisat22(bootstrap_with=c.clauses)
            if method.endswith('-cnf'):
                engine=GridSolver(raw) if method=='grid-cnf' else OwnedGraphSolver(c)
                rootok,known=engine.propagate()
            elif method=='sat-up':
                p=unit_propagate(c.clauses);rootok=p.consistent
                known={v if val else -v for v,val in p.values.items() if v<=nvars}
            else:
                known={row[0] for row in c.clauses if len(row)==1 and abs(row[0])<=nvars}
        else:solver=c if method.startswith('bdd') else GridSolver(c) if method=='grid' else OwnedGraphSolver(c)
        rec['setup_seconds']=time.perf_counter()-setup;rec['stage']='queries';save(dest,rec)
        qs=json.loads(Path(spec['queries']).read_text())[:spec.get('query_count',512)]
        times=[];answers=[];counts=[];satcalls=[];verdicts=[];new_forced=[]
        rec['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        for j,alpha in enumerate(qs):
            qstart=time.perf_counter();calls=0
            if method=='sat':
                ok,forced,calls=forced_by_search(solver,c.registry.by_id,alpha,known=known)
            elif native:
                ok,trail=solver.propagate(assumptions=alpha)
                ok=ok and rootok;forced=known|{l for l in trail if abs(l)<=nvars} if ok else set()
            else:ok,forced=solver.propagate(alpha)
            times.append(time.perf_counter()-qstart);counts.append(len(forced));satcalls.append(calls);verdicts.append(ok)
            new_forced.append(len(forced-set(alpha)))
            answers.append(hashlib.sha256(json.dumps([ok,sorted(forced) if ok else []]).encode()).hexdigest())
            if j==0 and method=='sat' and ok:known=forced
            if j+1 in (1,8,64,512) or (j+1)%16==0:
                rec.update(query_times=times,answer_hashes=answers,forced_counts=counts,new_forced=new_forced,
                    sat_calls=satcalls,verdicts=verdicts,completed_queries=j+1,
                    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                save(dest,rec)
        rec.update(status='ok',query_times=times,answer_hashes=answers,forced_counts=counts,
            new_forced=new_forced,sat_calls=satcalls,verdicts=verdicts,completed_queries=len(qs))
        if native:
            rec['solver_stats']=solver.accum_stats();solver.delete()
    except (MemoryError,ResourceLimit) as exc:
        rec.update(status='UNKNOWN',reason=str(exc) or 'memory_limit')
    except Exception as exc:
        rec.update(status='ERROR',reason=str(exc),traceback=traceback.format_exc())
    rec.update(elapsed_seconds=time.perf_counter()-start,
               peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(dest,rec)


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true')
    p.add_argument('--root',default='/root/wm-research');p.add_argument('--inputs',default='results/paper/inputs')
    p.add_argument('--out',default='results/paper/primary');p.add_argument('--suite',default='primary',choices=('pilot','primary','ablation'))
    p.add_argument('--repeats',type=int,default=5);p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--select',nargs='*');p.add_argument('--methods',nargs='*')
    p.add_argument('--censored-once',action='store_true',help='One full-budget attempt for configurations censored in the pilot; report n=1 explicitly')
    p.add_argument('--worker');p.add_argument('--record');p.add_argument('--resume',action='store_true')
    a=p.parse_args()
    if a.worker:worker(json.loads(a.worker),a.record);return
    if a.prepare:
        print(json.dumps(prepare(a.inputs,Path(a.root)/'baselines'),indent=2));return
    cases=json.loads((Path(a.inputs)/'cases.json').read_text());specs=[];censored=set()
    if a.censored_once:
        for f in (Path(a.inputs).parent/'pilot').glob('[0-9]*.json'):
            r=json.loads(f.read_text())
            if r['status']=='UNKNOWN':censored.add((r['spec']['id'],r['spec']['method']))
    for c in cases:
        if a.select and c['id'] not in a.select:continue
        if a.suite=='ablation':
            if c['family']=='producers' and c['n'] in (2,4,8) and c.get('writers',2)==2 and c.get('readers',1)==1 and c.get('reads',2)==2:
                methods=['dynamic','unfold','co-first','grid','dynamic-cnf','grid-cnf','bdd-fixed']
            elif c['family']=='pipeline' and c['n'] in (1,2):
                methods=['frontier','frontier-full','frontier-dfa','frontier-unfold','frontier-cnf','sat-up']
            else:continue
        else:
            methods=['sat','sat-up','bdd-sift','dynamic' if c['dynamic_certificate'] else 'frontier']
            if c['family']=='producers' and c.get('writers',2)==2 and c.get('readers',1)==1:
                methods+=['grid']
            if c['family']=='producers' and c['n'] in (2,4) and c.get('writers',2)==2 and c.get('readers',1)==1:
                methods+=['frontier']
        for method in methods:
            if a.methods and method not in a.methods:continue
            repetitions=1 if (c['id'],method) in censored else a.repeats
            for repeat in range(repetitions):
                specs.append(dict(c,method=method,repeat=repeat,query_count=32 if a.suite=='pilot' else 512,
                                  repetitions_planned=repetitions,
                                  compile_seconds=20 if a.suite=='pilot' else 120))
    random.Random(20261015).shuffle(specs);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    cpus=sorted(os.sched_getaffinity(0));limit=35 if a.suite=='pilot' else 180
    environment=dict(platform=platform.platform(),python=sys.version,jobs=a.jobs,isolated=a.jobs==1,
        repeats=a.repeats,suite=a.suite,wall_limit_seconds=limit,memory_limit_gib=4,seed=20261015,
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
          for directory in ('wmcheck','experiments') for f in (ROOT/directory).glob('*.py')},
        dependencies=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True).splitlines())
    save(out/'environment.json',environment);save(out/'plan.json',specs)
    stopped=set()
    def run(j,spec):
        spec=dict(spec,cpu=cpus[j%a.jobs]);dest=out/f'{j:04d}.json'
        key=(spec['id'],spec['method'])
        if a.censored_once and key in stopped:
            save(dest,dict(spec=spec,status='SKIPPED_AFTER_RESOURCE_LIMIT',reason='Earlier full-budget attempt exceeded a resource limit'))
            return
        if a.resume and dest.exists() and json.loads(dest.read_text()).get('status') in ('ok','UNKNOWN'):
            return
        proc=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        try:
            stdout,stderr=proc.communicate(timeout=limit)
            if proc.returncode:
                r=json.loads(dest.read_text()) if dest.exists() else dict(spec=spec)
                r.update(status='ERROR',returncode=proc.returncode,stderr=stderr[-4000:]);save(dest,r)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate()
            r=json.loads(dest.read_text()) if dest.exists() else dict(spec=spec)
            r.update(status='UNKNOWN',reason=f'wall_timeout_{limit}s',stderr=stderr[-2000:]);save(dest,r)
        r=json.loads(dest.read_text())
        if a.censored_once and r['status']=='UNKNOWN':stopped.add(key)
        print(j,spec['id'],spec['method'],r['status'],r.get('completed_queries',0),flush=True)
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for f in as_completed([pool.submit(run,j,s) for j,s in enumerate(specs)]):f.result()


if __name__=='__main__':main()
