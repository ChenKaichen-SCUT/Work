"""Isolated workers for the bounded evidence study; controller lives in common."""
import argparse,json,random,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_evidence_common import OUT,label,instance,save,digest


def build(job,row,out):
    from wmcheck.ra import RARegistry
    from wmcheck.ra_protocols import build_protocol,replay_certificate
    from wmcheck.ra_frontier import prepare_frontier,compile_frontier
    from wmcheck.ra_support_sat import SupportSAT
    from wmcheck.ra_component_sat import ComponentSAT
    from wmcheck.owned_dag import OwnedGraphSolver
    method=job['method'];tick=time.perf_counter();inp=instance(job['case']);reg=RARegistry(inp.inst)
    row.update(input_seconds=time.perf_counter()-tick,input_sha256=digest(inp),N=len(inp.inst.events),X=reg.nvars)
    pre=None
    if method!='B0':
        row['phase']='certificate';save(out,row);tick=time.perf_counter();pre=build_protocol(inp)
        row['certificate_seconds']=time.perf_counter()-tick;assert pre['status']=='CERTIFIED'
        tick=time.perf_counter();assert replay_certificate(inp,pre)
        row['certificate_check_seconds']=time.perf_counter()-tick
    if method=='B2':
        row['phase']='plan';save(out,row);tick=time.perf_counter()
        plan=prepare_frontier(inp.inst,certificate=pre['certificate'],order=pre['order'],co_mode='direct',summary_mode='ports',early_degrees=True)
        row.update(plan_seconds=time.perf_counter()-tick,plan_stats=plan.stats)
        row['phase']='compile';save(out,row);tick=time.perf_counter()
        graph=compile_frontier(inp.inst,prepared=plan,max_states=200000,max_edges=600000,max_seconds=50)
        row.update(compile_seconds=time.perf_counter()-tick,compile_stats=graph.stats)
        row['phase']='index';save(out,row);tick=time.perf_counter();engine=OwnedGraphSolver(graph)
        row['index_seconds']=time.perf_counter()-tick
    else:
        row['phase']='encoding';save(out,row);tick=time.perf_counter()
        typ=ComponentSAT if method=='BD' else SupportSAT
        engine=typ(inp,certificate=None if pre is None else pre['certificate'],solver='cadical195')
        row.update(encoding_seconds=time.perf_counter()-tick,solver_stats=engine.stats)
    row['cold_seconds']=sum(row.get(k,0) for k in ('input_seconds','certificate_seconds','certificate_check_seconds','plan_seconds','compile_seconds','index_seconds','encoding_seconds'))
    return inp,reg,engine


def bench(job,row,out,reg,engine):
    w=json.loads((OUT/'workloads'/f"{label(job['case'])}_s{job.get('seed',0)}.json").read_text(encoding='utf8'))
    assert w['input_sha256']==row['input_sha256']
    queries=list(w['queries'])
    if job.get('order',0):random.Random(991731+job['order']).shuffle(queries)
    row.update(workload_sha256=digest(queries),pool_sha256=w['workload_sha256'],U=w['U'],Q=len(queries),structure=w['structure'],phase='queries')
    save(out,row);cache={};answers=set()
    for j,q in enumerate(queries):
        tick=time.perf_counter();key=tuple(sorted(q['assumptions']));hit=key in cache;solve_time=0;stats={}
        if not hit:
            began=time.perf_counter()
            if job['method']=='B2':
                ok,forced=engine.propagate(key)
                values=frozenset(l for v in reg.by_id for l in (v,-v) if -l not in forced) if ok else frozenset()
            else:
                ok,values=engine.all_support(key);stats=dict(engine.last_query_stats);values=frozenset(values)
            cache[key]=ok,values;solve_time=time.perf_counter()-began
        ok,values=cache[key];assert ok==q['expected_sat']
        began=time.perf_counter();answer=[ok,sorted(values)];output_time=time.perf_counter()-began
        seconds=time.perf_counter()-tick;answer_hash=digest(answer);answers.add(answer_hash)
        row['queries'].append(dict(index=j,alpha=key,sat=ok,cache_hit=hit,seconds=seconds,
            compute_seconds=solve_time,output_seconds=output_time,answer_sha256=answer_hash,solver=stats))
        if j%25==24:save(out,row)
    row.update(cache_hits=sum(q['cache_hit'] for q in row['queries']),cache_misses=len(cache),distinct_answers=len(answers),
        query_seconds=sum(q['seconds'] for q in row['queries']),miss_compute_seconds=sum(q['compute_seconds'] for q in row['queries']),
        output_seconds=sum(q['output_seconds'] for q in row['queries']))
    if job['method']=='BD':row.update(local_hits=engine.total_local_hits,local_misses=engine.total_local_misses,component_sat_calls=engine.total_sat_calls)
    row['total_seconds']=row['cold_seconds']+row['query_seconds']


def task(job,row,out,reg,engine):
    from wmcheck.ra_task_diagnosis import QueryService,session
    workload=json.loads((OUT/'diagnostic_inputs'/f"{label(job['case'])}.json").read_text(encoding='utf8'))
    assert workload['input_sha256']==row['input_sha256']
    service=QueryService(job['method'],engine,reg);reports=[];seconds=0;output_seconds=0;output_bytes=0
    row.update(phase='diagnosis',episodes_sha256=workload['episodes_sha256'],reports=[]);save(out,row)
    for episode in workload['episodes']:
        start=time.perf_counter();report=session(service,[episode],job['profile'])[0]
        compute=time.perf_counter()-start;start=time.perf_counter()
        rendered=json.dumps(report,sort_keys=True,separators=(',',':'))
        output=time.perf_counter()-start;output_seconds+=output;output_bytes+=len(rendered.encode());seconds+=compute+output
        reports.append(report);row['reports'].append(dict(name=episode['name'],result_sha256=digest(report),
            consistent=report['diagnosis']['consistent'],conflict_size=len(report['diagnosis']['conflict']),
            repairs=sum(len(r['replacements']) for r in report['diagnosis']['repairs']),
            snapshots=len(report['snapshots']),seconds=compute+output))
        row['queries']=service.calls;save(out,row)
    row.update(task_seconds=seconds,output_seconds=output_seconds,output_bytes=output_bytes,
        total_seconds=row['cold_seconds']+seconds,task_result_sha256=digest(reports),
        query_types={kind:sum(q['task']==kind for q in service.calls) for kind in ('sat','field','all')},
        global_cache_hits=sum(q['cache_hit'] for q in service.calls),global_cache_misses=sum(not q['cache_hit'] for q in service.calls),
        natural_sat_calls=sum(q['sat'] for q in service.calls),natural_unsat_calls=sum(not q['sat'] for q in service.calls),
        assumption_lengths=sorted({len(q['alpha']) for q in service.calls}))
    if job['method']=='BD':row.update(local_hits=engine.total_local_hits,local_misses=engine.total_local_misses,component_sat_calls=engine.total_sat_calls)
    if job.get('repeat',0)==0:
        save(OUT/'diagnostic_outputs'/f"{label(job['case'])}_{job['profile']}_{job['method']}.json",reports)


def main():
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    import psutil
    from wmcheck.compiler import ResourceLimit
    proc=psutil.Process();proc.cpu_affinity([min(proc.cpu_affinity())])
    job=json.loads(Path(a.job).read_text(encoding='utf8'));row=dict(status='RUNNING',job=job,phase='input',queries=[])
    save(a.out,row);engine=None;start=time.perf_counter()
    try:
        if job['mode']=='generate':
            from experiments.causal_evidence_inputs import generate
            result=generate(job['case'],job.get('seed',0))
            row.update(workload_sha256=result['workload_sha256'],U=result['U'],structure=result['structure'])
        elif job['mode']=='logs':
            from experiments.causal_evidence_inputs import diagnostic_logs
            result=diagnostic_logs(job['case']);row.update(episodes=len(result['episodes']),episodes_sha256=result['episodes_sha256'])
        elif job['mode']=='negative':
            from experiments.causal_evidence_negative import raw_worker
            raw_worker(job,row,a.out)
        else:
            inp,reg,engine=build(job,row,a.out)
            if job['mode']=='bench':bench(job,row,a.out,reg,engine)
            elif job['mode']=='task':task(job,row,a.out,reg,engine)
            elif job['mode']!='probe':raise ValueError(job['mode'])
        row.update(status='OK',phase='done')
    except ResourceLimit as exc:row.update(status='RESOURCE_LIMIT',reason=str(exc),partial_stats=getattr(exc,'stats',{}))
    except Exception:row.update(status='ERROR',traceback=traceback.format_exc())
    finally:
        if engine is not None and hasattr(engine,'close'):engine.close()
        memory=proc.memory_info();row.update(wall_seconds=time.perf_counter()-start,peak_wset_bytes=getattr(memory,'peak_wset',memory.rss))
        save(a.out,row)


if __name__=='__main__':main()
