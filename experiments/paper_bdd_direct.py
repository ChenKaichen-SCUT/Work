"""Additional strong symbolic-relation baseline, isolated from native campaigns."""
import argparse,hashlib,json,os,subprocess,sys,time,signal,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_suite import save
from experiments.paper_cases import instance


def worker(spec,dest):
    import resource
    from wmcheck.ra_bdd_relational import RelationalBDD
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2);os.sched_setaffinity(0,{spec['cpu']})
    r=dict(spec=spec,status='running',stage='compile');save(dest,r);start=time.perf_counter()
    try:
        c=RelationalBDD(instance(spec));r.update(c.stats,setup_seconds=0,stage='queries');save(dest,r)
        qs=json.loads(Path(spec['queries']).read_text());times=[];hashes=[];counts=[];verdicts=[]
        r['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        for j,a in enumerate(qs):
            t=time.perf_counter();ok,f=c.propagate(a);times.append(time.perf_counter()-t)
            hashes.append(hashlib.sha256(json.dumps([ok,sorted(f) if ok else []]).encode()).hexdigest())
            counts.append(len(f));verdicts.append(ok)
            if j in (0,7,63,511):
                r.update(query_times=times,answer_hashes=hashes,forced_counts=counts,verdicts=verdicts,completed_queries=j+1);save(dest,r)
        r.update(status='ok')
    except Exception as exc:r.update(status='UNKNOWN' if isinstance(exc,MemoryError) else 'ERROR',reason=str(exc),traceback=traceback.format_exc())
    r.update(elapsed_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss);save(dest,r)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/paper/bdd_relational');p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--worker');p.add_argument('--record');a=p.parse_args()
    if a.worker:worker(json.loads(a.worker),a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);cpu=min(os.sched_getaffinity(0))
    cases=json.loads(Path('results/paper/inputs/cases.json').read_text());index=0
    save(out/'environment.json',dict(isolated=True,cpu=cpu,repeats=a.repeats,wall_limit_seconds=180,memory_limit_gib=4,
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
            for directory in ('wmcheck','experiments') for f in (ROOT/directory).glob('*.py')},
        method='BDD directly evaluates symbolic relations; no auxiliary HB encoding'))
    for c in cases:
        if c['dynamic_certificate']:continue
        for repeat in range(a.repeats):
            spec=dict(c,method='bdd-relational',repeat=repeat,cpu=cpu);dest=out/f'{index:04d}.json'
            p=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                o,e=p.communicate(timeout=180)
                if p.returncode:
                    r=json.loads(dest.read_text());r.update(status='ERROR',stderr=e,returncode=p.returncode);save(dest,r)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGKILL);p.communicate();r=json.loads(dest.read_text());r.update(status='UNKNOWN',reason='wall_timeout_180s');save(dest,r)
            r=json.loads(dest.read_text());print(index,c['id'],r['status'],flush=True);index+=1
            if r['status']!='ok':break


if __name__=='__main__':main()
