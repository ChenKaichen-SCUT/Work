"""Post-diagnosis algorithm change; keep separate from frozen main timings."""
import argparse,hashlib,json,os,signal,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_cases import instance,layout
from experiments.paper_suite import save


def worker(spec,dest):
    import resource
    from wmcheck.ra_frontier import compile_frontier
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.compiler import ResourceLimit
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2);os.sched_setaffinity(0,{spec['cpu']})
    r=dict(spec=spec,status='running',stage='compile');save(dest,r);start=time.perf_counter()
    try:
        c=compile_frontier(instance(spec),order=layout(instance(spec),spec),early_degrees=spec['method']!='frontier-diagnostic',
            co_mode='direct' if spec['method']=='frontier-direct-co' else 'successor',
            max_states=200000,max_edges=600000,max_seconds=120)
        r.update(c.stats);t=time.perf_counter();s=OwnedGraphSolver(c);r.update(setup_seconds=time.perf_counter()-t,stage='queries')
        qs=json.loads(Path(spec['queries']).read_text());r['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        times=[];hashes=[];counts=[];verdicts=[]
        for j,a in enumerate(qs):
            t=time.perf_counter();ok,f=s.propagate(a);times.append(time.perf_counter()-t)
            hashes.append(hashlib.sha256(json.dumps([ok,sorted(f) if ok else []]).encode()).hexdigest());counts.append(len(f));verdicts.append(ok)
            if j+1 in (1,8,64,512) or (j+1)%16==0:
                r.update(query_times=times,answer_hashes=hashes,forced_counts=counts,verdicts=verdicts,completed_queries=j+1);save(dest,r)
        r.update(status='ok')
    except (MemoryError,ResourceLimit) as exc:r.update(status='UNKNOWN',reason=str(exc),failure_stats=getattr(exc,'stats',{}))
    except Exception as exc:r.update(status='ERROR',reason=str(exc),traceback=traceback.format_exc())
    r.update(elapsed_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss);save(dest,r)


def main():
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--record');p.add_argument('--out',default='results/paper/pruning');a=p.parse_args()
    if a.worker:worker(json.loads(a.worker),a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);cpu=min(os.sched_getaffinity(0))
    cases=json.loads(Path('results/paper/inputs/cases.json').read_text())
    cases=[c for c in cases if not c['dynamic_certificate'] or c['id']=='c001']
    if Path('results/paper/stress/inputs/cases.json').exists():
        cases += [c for c in json.loads(Path('results/paper/stress/inputs/cases.json').read_text()) if not c['dynamic_certificate']]
    save(out/'environment.json',dict(cpu=cpu,isolated=True,repeats=5,wall_limit_seconds=180,memory_limit_gib=4,
        change='Early degree pruning and direct CO generators; original RF/CO projection unchanged',
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ('wmcheck','experiments') for f in (ROOT/d).glob('*.py')}))
    index=0
    for c in cases:
        methods=['frontier-direct-co']
        if c['id'] in ('c001','c011','c012','c013') or c['id'].startswith('a'):methods.append('frontier-pruned')
        if c['id'] in ('c012','c013'):methods.append('frontier-diagnostic')
        for method in methods:
            for repeat in range(1 if method=='frontier-diagnostic' else 5):
                spec=dict(c,method=method,repeat=repeat,cpu=cpu);dest=out/f'{index:04d}.json'
                if method=='frontier-direct-co':spec['successor_interface']=spec.pop('interface',None)
                proc=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
                try:
                    o,e=proc.communicate(timeout=180)
                    if proc.returncode:
                        r=json.loads(dest.read_text());r.update(status='ERROR',stderr=e,returncode=proc.returncode);save(dest,r)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.communicate();r=json.loads(dest.read_text());r.update(status='UNKNOWN',reason='wall_timeout_180s');save(dest,r)
                r=json.loads(dest.read_text());print(index,c['id'],method,r['status'],r.get('failure_stats'),flush=True);index+=1
                if r['status']!='ok':break


if __name__=='__main__':main()
