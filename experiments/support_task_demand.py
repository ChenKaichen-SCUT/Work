"""Task-specific SAT comparator: ask only for information the client needs.

Full snapshots require all supports. Conflict minimization needs consistency
only, and a single-field repair needs supports only for that field. This avoids
making SAT compute unrelated backbones merely to match a full-oracle API.
"""
import argparse,hashlib,json,os,resource,statistics,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import RARegistry
from wmcheck.ra_publication import publication_exchange
from wmcheck.trace_diagnosis import support_snapshot
from experiments.support_task_study import save,digest


class DemandSAT:
    def __init__(self,inst):
        from wmcheck.ra_sat import encode_ra
        from pysat.solvers import Minisat22
        enc=encode_ra(inst);self.reg=enc.registry;self.stats=enc.stats
        self.sat=Minisat22(bootstrap_with=enc.clauses);self.calls=0;self.known=set()
        self.units={r[0] for r in enc.clauses if len(r)==1 and abs(r[0])<=self.reg.nvars}

    def full(self,alpha):
        from wmcheck.query_sat_up import forced_with_up
        ok,f,calls=forced_with_up(self.sat,self.reg.by_id,alpha,self.known|self.units,flip_phases=True)
        self.calls+=calls
        if ok and not alpha:self.known=f
        return ok,f

    def consistent(self,alpha):
        self.calls+=1;return self.sat.solve(assumptions=list(alpha))

    def diagnose(self,observations):
        observations=tuple(observations);snapshot=support_snapshot(self.reg,self.full,observations)
        if snapshot['consistent']:return dict(snapshot=snapshot,conflict=[],repairs=[])
        core=list(observations)
        for lit in observations:
            candidate=[x for x in core if x!=lit]
            if not self.consistent(candidate):core.remove(lit)
        repairs=[]
        for lit in observations:
            remaining=[x for x in observations if x!=lit]
            if not self.consistent(remaining):continue
            kind,a,b=self.reg.by_id[abs(lit)]
            candidates=([self.reg.literal(('rf',w,b)) for w in self.reg.inst.candidates[b] if w!=a]
                        if kind=='rf' else [-lit])
            replacements=[v for v in candidates if -v not in self.known and self.consistent(remaining+[v])]
            repairs.append(dict(remove=lit,replacements=replacements))
        return dict(snapshot=snapshot,conflict=core,repairs=repairs)


def worker(args):
    out=Path(args.out);payload,n=args.worker;n=int(n)
    os.sched_setaffinity(0,{args.cpu});resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    inst=publication_exchange(n,payload=payload)
    logs=json.loads((out/'inputs'/f'{payload}_{n}_logs.json').read_text())
    result=dict(payload=payload,n=n,method='sat-demand',status='running',log_sha256=digest(logs),reports=[])
    save(args.record,result);start=time.perf_counter()
    try:
        engine=DemandSAT(inst);result['build_setup_seconds']=time.perf_counter()-start
        result['stats']=engine.stats;result['diagnosis_seconds']=0
        for log in logs:
            t=time.perf_counter()
            answer=engine.diagnose(log['observations'])
            result['diagnosis_seconds']+=time.perf_counter()-t
            result['reports'].append(dict(name=log['name'],answer_sha256=digest(answer),
                consistent=answer['snapshot']['consistent'],conflict_size=len(answer['conflict']),
                repair_fields=len(answer['repairs']),replacements=sum(len(r['replacements']) for r in answer['repairs'])))
        result.update(status='ok',sat_calls=engine.calls)
    except MemoryError as exc:
        exc.__traceback__=None;exc.__context__=None
        result.update(status='UNKNOWN',reason='worker_memory_failure_4GiB')
    except Exception as exc:
        result.update(status='ERROR',reason=str(exc),traceback=traceback.format_exc())
    result.update(elapsed_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(args.record,result)


def run(args):
    out=Path(args.out);cpu=min(os.sched_getaffinity(0))
    save(out/'demand_environment.json',dict(cpu=cpu,repeats=3,wall_seconds=240,memory_gib=4,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),contract='identical diagnosis outputs; task-specific SAT queries'))
    configs=[('epoch',n) for n in (2,4,8,16,32)]+[('constant',n) for n in (2,3,4,6)]
    for payload,n in configs:
        for rep in range(3):
            record=out/'demand_runs'/f'{payload}_{n}_{rep}.json'
            if record.exists():raise FileExistsError(record)
            cmd=[sys.executable,__file__,'--out',str(out),'--worker',payload,str(n),'--record',str(record),'--cpu',str(cpu)]
            proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                stdout,stderr=proc.communicate(timeout=240)
                if proc.returncode:
                    row=json.loads(record.read_text()) if record.exists() else {}
                    memory='MemoryError' in stderr
                    save(record,dict(row,status='UNKNOWN' if memory or proc.returncode<0 else 'ERROR',
                        reason='worker_memory_failure_4GiB' if memory else 'worker_exit',returncode=proc.returncode,stderr=stderr))
            except subprocess.TimeoutExpired:
                proc.kill();stdout,stderr=proc.communicate();row=json.loads(record.read_text())
                save(record,dict(row,status='UNKNOWN',reason='wall_timeout_240s',stderr=stderr))
            row=json.loads(record.read_text());print(payload,n,'sat-demand',rep,row['status'],flush=True)
            if row['status']!='ok':break
    analyze(out)


def analyze(out):
    rows=[json.loads(p.read_text()) for p in sorted((out/'demand_runs').glob('*.json'))];summary=[]
    configs=sorted({(r['payload'],r['n']) for r in rows})
    for payload,n in configs:
        rs=[r for r in rows if (r['payload'],r['n'])==(payload,n)];ok=[r for r in rs if r['status']=='ok']
        ref=None
        for p in (out/'runs').glob(f'{payload}_{n}_*.json'):
            r=json.loads(p.read_text())
            if r['status']=='ok':ref=r;break
        for r in ok:
            assert ref is not None and r['log_sha256']==ref['log_sha256'] and r['reports']==ref['reports']
        row=dict(payload=payload,n=n,statuses=[r['status'] for r in rs])
        if ok:
            row.update(build_median=statistics.median(r['build_setup_seconds'] for r in ok),
                diagnosis_median=statistics.median(r['diagnosis_seconds'] for r in ok),
                total_median=statistics.median(r['build_setup_seconds']+r['diagnosis_seconds'] for r in ok),
                sat_calls=[r['sat_calls'] for r in ok],peak_rss_kib=max(r['peak_rss_kib'] for r in ok),
                complete_client_outputs_equal=True)
        summary.append(row)
    save(out/'demand_summary.json',summary)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--run',action='store_true')
    p.add_argument('--analyze',action='store_true')
    p.add_argument('--worker',nargs=2);p.add_argument('--record');p.add_argument('--cpu',type=int,default=0)
    args=p.parse_args()
    if args.worker:worker(args)
    elif args.analyze:analyze(Path(args.out))
    else:run(args)
