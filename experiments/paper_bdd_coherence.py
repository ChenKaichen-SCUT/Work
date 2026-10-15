"""Strong symbolic baseline: coherence restrictions before CO total-order CNF."""
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
        c=RelationalBDD(instance(spec),coherence_first=True,semantic_order=True);r.update(c.stats,setup_seconds=0,stage='queries');save(dest,r)
        qs=json.loads(Path(spec['queries']).read_text());times=[];hashes=[];counts=[];verdicts=[]
        r['query_sha256']=hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        for j,a in enumerate(qs):
            t=time.perf_counter();ok,f=c.propagate(a);times.append(time.perf_counter()-t)
            hashes.append(hashlib.sha256(json.dumps([ok,sorted(f) if ok else []]).encode()).hexdigest())
            counts.append(len(f));verdicts.append(ok)
            if j+1 in (1,8,64,512) or (j+1)%16==0:
                r.update(query_times=times,answer_hashes=hashes,forced_counts=counts,verdicts=verdicts,completed_queries=j+1);save(dest,r)
        r.update(status='ok')
    except Exception as exc:r.update(status='UNKNOWN' if isinstance(exc,MemoryError) else 'ERROR',reason=str(exc),traceback=traceback.format_exc())
    r.update(elapsed_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss);save(dest,r)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='results/paper/bdd_coherence');p.add_argument('--worker');p.add_argument('--record');a=p.parse_args()
    if a.worker:worker(json.loads(a.worker),a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);cpu=min(os.sched_getaffinity(0))
    cases=json.loads(Path('results/paper/inputs/cases.json').read_text())
    extra=Path('results/paper/stress/inputs/cases.json')
    if extra.exists():cases+=json.loads(extra.read_text())
    save(out/'environment.json',dict(isolated=True,cpu=cpu,repeats=5,wall_limit_seconds=180,memory_limit_gib=4,
        method='Direct symbolic relations; singleton RF folded; coherence before CO transitivity; semantic event order then dynamic sifting',
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ('wmcheck','experiments') for f in (ROOT/d).glob('*.py')}))
    index=0
    for c in cases:
        for repeat in range(5):
            spec=dict(c,method='bdd-coherence-first',repeat=repeat,cpu=cpu);dest=out/f'{index:04d}.json'
            proc=subprocess.Popen([sys.executable,__file__,'--worker',json.dumps(spec),'--record',str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                o,e=proc.communicate(timeout=180)
                if proc.returncode:
                    r=json.loads(dest.read_text());r.update(status='ERROR',stderr=e,returncode=proc.returncode);save(dest,r)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.communicate();r=json.loads(dest.read_text());r.update(status='UNKNOWN',reason='wall_timeout_180s');save(dest,r)
            r=json.loads(dest.read_text());print(index,c['id'],r['status'],flush=True);index+=1
            if r['status']!='ok':break


if __name__=='__main__':main()
