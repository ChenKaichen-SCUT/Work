"""Stronger SAT complete-support control with propagation before countermodels.

This comparison supersedes speed claims against the earlier unseeded search.
Both answer exactly the same question; every old record is retained.
"""
import argparse,hashlib,json,os,signal,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_cases import instance
from experiments.paper_suite import save


def worker(spec,dest):
    import resource
    from pysat.solvers import Minisat22
    from wmcheck.ra_sat import encode_ra
    from wmcheck.ra_order_sat import encode_order
    from wmcheck.query_sat_up import forced_with_up
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2);os.sched_setaffinity(0,{spec['cpu']})
    r=dict(spec=spec,status='running',stage='compile');save(dest,r);start=time.perf_counter()
    try:
        inst=instance(spec);e=encode_order(inst) if spec['dynamic_certificate'] else encode_ra(inst)
        r.update(e.stats);t=time.perf_counter();solver=Minisat22(bootstrap_with=e.clauses)
        known={row[0] for row in e.clauses if len(row)==1 and abs(row[0])<=e.registry.nvars}
        r.update(setup_seconds=time.perf_counter()-t,stage='queries');save(dest,r)
        qs=json.loads(Path(spec['queries']).read_text());r['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        times=[];hashes=[];counts=[];verdicts=[];calls=[]
        for j,alpha in enumerate(qs):
            t=time.perf_counter();ok,f,n=forced_with_up(solver,e.registry.by_id,alpha,known,flip_phases=spec['method']=='sat-phase-assisted')
            times.append(time.perf_counter()-t);calls.append(n);counts.append(len(f));verdicts.append(ok)
            hashes.append(hashlib.sha256(json.dumps([ok,sorted(f) if ok else []]).encode()).hexdigest())
            if j==0 and ok:known=f
            if j+1 in (1,8,64,512) or (j+1)%16==0:
                r.update(query_times=times,answer_hashes=hashes,forced_counts=counts,verdicts=verdicts,sat_calls=calls,completed_queries=j+1);save(dest,r)
        r.update(status='ok',solver_stats=solver.accum_stats());solver.delete()
    except MemoryError:r.update(status='UNKNOWN',reason='memory_limit')
    except Exception as exc:r.update(status='ERROR',reason=str(exc),traceback=traceback.format_exc())
    r.update(elapsed_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss);save(dest,r)


def main():
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--record');p.add_argument('--out',default='results/paper/sat_strong');a=p.parse_args()
    if a.worker:worker(json.loads(a.worker),a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);cpu=min(os.sched_getaffinity(0))
    cases=json.loads(Path('results/paper/inputs/cases.json').read_text())
    extra=Path('results/paper/stress/inputs/cases.json')
    if extra.exists():cases+=json.loads(extra.read_text())
    save(out/'environment.json',dict(cpu=cpu,isolated=True,repeats=5,wall_limit_seconds=180,memory_limit_gib=4,
        method='Native UP followed by incremental countermodel support search; globally complete original support',
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ('wmcheck','experiments') for f in (ROOT/d).glob('*.py')}))
    index=0
    for case,method in [(c,m) for c in cases for m in ('sat-up-assisted','sat-phase-assisted')]:
        for repeat in range(5):
            spec=dict(case,method=method,repeat=repeat,cpu=cpu);dest=out/f'{index:04d}.json'
            proc=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                o,e=proc.communicate(timeout=180)
                if proc.returncode:
                    r=json.loads(dest.read_text());r.update(status='ERROR',stderr=e,returncode=proc.returncode);save(dest,r)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.communicate();r=json.loads(dest.read_text());r.update(status='UNKNOWN',reason='wall_timeout_180s');save(dest,r)
            r=json.loads(dest.read_text());print(index,case['id'],method,r['status'],flush=True);index+=1
            if r['status']!='ok':break


if __name__=='__main__':main()
