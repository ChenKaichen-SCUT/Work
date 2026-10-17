"""End-to-end incomplete-provenance diagnosis, with matched full-support oracles."""
import argparse,hashlib,json,os,platform,resource,statistics,subprocess,sys,time,traceback
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import RARegistry
from wmcheck.ra_publication import publication_exchange,publication_layout
from wmcheck.trace_diagnosis import diagnose,publication_logs
from wmcheck.compiler import ResourceLimit


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def prepare(out):
    from wmcheck.ra_program import export_c,export_litmus
    for payload,ns in [('epoch',(2,4,8,16,32,64)),('constant',(2,3,4,6))]:
        for n in ns:
            inst=publication_exchange(n,payload=payload);base=out/'inputs'/f'{payload}_{n}'
            save(str(base)+'.json',asdict(inst));save(str(base)+'_logs.json',publication_logs(inst,n))
            save(str(base)+'_registry.json',RARegistry(inst).by_id)
            Path(str(base)+'.c').write_text(export_c(inst))
            Path(str(base)+'.litmus').write_text(export_litmus(inst,name=f'{payload}_{n}'))


def worker(args):
    out=Path(args.out);payload,n,method=args.worker;n=int(n)
    record=Path(args.record);os.sched_setaffinity(0,{args.cpu})
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    os.environ['WMCHECK_NATIVE_PORTS']='0' if method=='ports-python' else '1'
    inst=publication_exchange(n,payload=payload);reg=RARegistry(inst)
    logs=json.loads((out/'inputs'/f'{payload}_{n}_logs.json').read_text())
    result=dict(payload=payload,n=n,method=method,status='running',budget_states=args.states,
        events=len(inst.events),original_variables=reg.nvars,log_sha256=digest(logs),queries=[],reports=[],examples=[],diagnosis_seconds=0)
    save(record,result);begin=time.perf_counter()
    try:
        if method.startswith('ports'):
            from wmcheck.ra_frontier import compile_frontier
            from wmcheck.dag_reduce import reduce_dag
            from wmcheck.owned_dag import OwnedGraphSolver
            c=compile_frontier(inst,order=publication_layout(inst,n),co_mode='direct',summary_mode='ports',
                rf_mode='binary' if method=='ports-binary' else 'atomic',source_covers=method!='ports-no-cover',
                early_degrees=True,max_states=args.states,max_edges=3*args.states,max_seconds=90)
            c=reduce_dag(c);result['stats']=c.stats
            engine=OwnedGraphSolver(c);query=engine.propagate
        elif method=='sat-phase':
            from pysat.solvers import Minisat22
            from wmcheck.ra_sat import encode_ra
            from wmcheck.query_sat_up import forced_with_up
            enc=encode_ra(inst);result['stats']=enc.stats
            sat=Minisat22(bootstrap_with=enc.clauses)
            known={r[0] for r in enc.clauses if len(r)==1 and abs(r[0])<=reg.nvars}
            def query(alpha):
                nonlocal known
                ok,f,calls=forced_with_up(sat,reg.by_id,alpha,known,flip_phases=True)
                result['sat_calls']=result.get('sat_calls',0)+calls
                if not alpha and ok:known=f
                return ok,f
        elif method=='bdd-coherence':
            from wmcheck.ra_bdd_relational import RelationalBDD
            engine=RelationalBDD(inst,coherence_first=True,semantic_order=True)
            query=engine.propagate;result['stats']=engine.stats
        else:raise ValueError(method)
        result['build_setup_seconds']=time.perf_counter()-begin
        def measured(alpha):
            start=time.perf_counter();ok,f=query(alpha);elapsed=time.perf_counter()-start
            result['queries'].append(dict(assumptions=alpha,consistent=ok,forced_count=len(f),
                answer_sha256=digest([ok,sorted(f) if ok else []]),seconds=elapsed))
            return ok,f
        for j,log in enumerate(logs):
            start=time.perf_counter()
            answer=diagnose(reg,measured,log['observations'])
            result['diagnosis_seconds']+=time.perf_counter()-start
            result['reports'].append(dict(name=log['name'],answer_sha256=digest(answer),
                consistent=answer['snapshot']['consistent'],conflict_size=len(answer['conflict']),
                repair_fields=len(answer['repairs']),replacements=sum(len(r['replacements']) for r in answer['repairs'])))
            if j in (1,2,3,4):result['examples'].append(dict(log,answer=answer))
            if j%16==0:save(record,result)
        result['status']='ok'
    except MemoryError as exc:
        # Release the failed encoder's retained clauses before serializing a receipt.
        exc.__traceback__=None;exc.__context__=None
        result.update(status='UNKNOWN',reason='worker_memory_failure_4GiB')
    except Exception as exc:
        result.update(status='UNKNOWN' if isinstance(exc,ResourceLimit) else 'ERROR',
            reason=str(exc),failure_stats=getattr(exc,'stats',{}),traceback=traceback.format_exc())
    result.update(elapsed_seconds=time.perf_counter()-begin,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(record,result)


def run(args):
    out=Path(args.out);prepare(out)
    cpu=min(os.sched_getaffinity(0))
    save(out/'environment.json',dict(platform=platform.platform(),python=sys.version,cpu=cpu,serial=True,
        repeats=args.repeats,compile_limit=90,wall_limit=240,memory_gib=4,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('wmcheck','experiments','tests') for p in (ROOT/folder).iterdir()
            if p.suffix in ('.py','.cpp','.java','.cat')},
        native_binary_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'wmcheck').glob('_port_native*.so')}))
    configs=[]
    for n in (2,4,8,16,32):
        for method in ('ports-atomic','ports-binary','ports-no-cover','sat-phase','bdd-coherence'):
            if method=='ports-no-cover' and n>8:continue
            configs.append(('epoch',n,method,1000000,args.repeats))
    for n in (2,3,4,6):
        for method in ('ports-atomic','sat-phase','bdd-coherence'):
            configs.append(('constant',n,method,1000000,args.repeats))
    configs += [('epoch',4,'ports-python',1000000,args.repeats),
                ('epoch',8,'ports-python',1000000,args.repeats),
                ('constant',3,'ports-binary',200000,1),
                ('constant',3,'ports-atomic',200000,1),
                ('epoch',64,'ports-atomic',2000000,1)]
    for payload,n,method,states,repeats in configs:
        for rep in range(repeats):
            record=out/'runs'/f'{payload}_{n}_{method}_s{states}_{rep}.json'
            if record.exists():raise FileExistsError(record)
            cmd=[sys.executable,__file__,'--out',str(out),'--worker',payload,str(n),method,
                '--record',str(record),'--cpu',str(cpu),'--states',str(states)]
            proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                stdout,stderr=proc.communicate(timeout=240)
                if proc.returncode:
                    row=json.loads(record.read_text()) if record.exists() else dict(payload=payload,n=n,method=method,budget_states=states)
                    memory='MemoryError' in stderr
                    save(record,dict(row,status='UNKNOWN' if memory or proc.returncode<0 else 'ERROR',
                        reason='worker_memory_failure_4GiB' if memory else 'worker_exit',returncode=proc.returncode,stderr=stderr))
            except subprocess.TimeoutExpired:
                proc.kill();stdout,stderr=proc.communicate()
                row=json.loads(record.read_text()) if record.exists() else {}
                save(record,dict(row,status='UNKNOWN',reason='wall_timeout_240s',stderr=stderr))
            row=json.loads(record.read_text());print(payload,n,method,rep,row['status'],flush=True)
            if row['status']!='ok':break


def analyze(out):
    rows=[json.loads(p.read_text()) for p in sorted((out/'runs').glob('*.json'))];report=[]
    for payload,n in sorted({(r['payload'],r['n']) for r in rows}):
        group=[r for r in rows if (r['payload'],r['n'])==(payload,n)]
        successful=[r for r in group if r['status']=='ok']
        if successful:
            ref=successful[0]
            for r in successful:
                assert r['log_sha256']==ref['log_sha256'] and r['reports']==ref['reports']
                assert [{k:v for k,v in q.items() if k!='seconds'} for q in r['queries']]==[
                    {k:v for k,v in q.items() if k!='seconds'} for q in ref['queries']]
        for method,states in sorted({(r['method'],r['budget_states']) for r in group}):
            rs=[r for r in group if (r['method'],r['budget_states'])==(method,states)];ok=[r for r in rs if r['status']=='ok']
            row=dict(payload=payload,n=n,method=method,budget_states=states,statuses=[r['status'] for r in rs])
            if ok:
                row.update(events=ok[0]['events'],original_variables=ok[0]['original_variables'],
                    build_median=statistics.median(r['build_setup_seconds'] for r in ok),
                    query_median=statistics.median(sum(q['seconds'] for q in r['queries']) for r in ok),
                    task_median=statistics.median(r['build_setup_seconds']+r['diagnosis_seconds'] for r in ok),query_calls=len(ok[0]['queries']),
                    reports=len(ok[0]['reports']),peak_rss_kib=max(r['peak_rss_kib'] for r in ok),
                    stats={k:v for k,v in ok[0]['stats'].items() if k not in ('layer_states',)})
            else:row['failures']=[dict(reason=r.get('reason'),stats=r.get('failure_stats',{})) for r in rs]
            report.append(row)
    save(out/'summary.json',dict(answer_audit='all_completed_methods_and_repeats_equal',records=len(rows),rows=report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--run',action='store_true')
    p.add_argument('--analyze',action='store_true');p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--worker',nargs=3);p.add_argument('--record');p.add_argument('--cpu',type=int,default=0)
    p.add_argument('--states',type=int,default=1000000);a=p.parse_args()
    if a.worker:worker(a)
    elif a.run:run(a)
    elif a.analyze:analyze(Path(a.out))
