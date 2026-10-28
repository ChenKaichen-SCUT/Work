"""New-assumption matrix with equal global caches and a CNF-component baseline."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest
from experiments.causal_followup_inputs import OUT,instance


def worker(a):
    import psutil
    from wmcheck.ra import RARegistry
    from wmcheck.ra_protocols import build_protocol,replay_certificate
    from wmcheck.ra_frontier import prepare_frontier,compile_frontier
    from wmcheck.ra_support_sat import SupportSAT
    from wmcheck.ra_component_sat import ComponentSAT
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.compiler import ResourceLimit
    proc=psutil.Process();proc.cpu_affinity([min(proc.cpu_affinity())])
    workload=json.loads((OUT/'workloads'/f'{a.family}_{a.rounds}_U{a.unique}.json').read_text())
    row=dict(status='RUNNING',family=a.family,rounds=a.rounds,U=a.unique,Q=1000,method=a.method,
             repeat=a.repeat,phase='input',queries=[],workload_sha256=workload['workload_sha256'])
    save(a.out,row);cold_start=time.perf_counter();solver=None
    try:
        tick=time.perf_counter();inp=instance(a.family,a.rounds);reg=RARegistry(inp.inst)
        row['input_seconds']=time.perf_counter()-tick
        row.update(input_sha256=digest(inp),N=len(inp.inst.events),X=reg.nvars)
        assert row['input_sha256']==workload['input_sha256']
        tick=time.perf_counter();pre=None
        if a.method!='B0':pre=build_protocol(inp)
        row['certificate_seconds']=time.perf_counter()-tick
        tick=time.perf_counter()
        if pre is not None:assert replay_certificate(inp,pre)
        row['certificate_check_seconds']=time.perf_counter()-tick
        row['phase']='build';save(a.out,row);tick=time.perf_counter()
        if a.method=='B2':
            plan=prepare_frontier(inp.inst,certificate=pre['certificate'],order=pre['order'],
                co_mode='direct',summary_mode='ports',early_degrees=True)
            row['plan_seconds']=time.perf_counter()-tick;row['plan_stats']=plan.stats
            tick=time.perf_counter()
            graph=compile_frontier(inp.inst,prepared=plan,max_states=200000,max_edges=600000,max_seconds=50)
            row['compile_seconds']=time.perf_counter()-tick;row['compile_stats']=graph.stats
            tick=time.perf_counter();engine=OwnedGraphSolver(graph);row['index_seconds']=time.perf_counter()-tick
        else:
            typ=ComponentSAT if a.method=='BD' else SupportSAT
            solver=typ(inp,certificate=None if pre is None else pre['certificate'],solver='cadical195')
            row['encoding_seconds']=time.perf_counter()-tick;row['solver_stats']=solver.stats
        row['cold_seconds']=sum(row.get(k,0) for k in ('input_seconds','certificate_seconds','certificate_check_seconds',
            'plan_seconds','compile_seconds','index_seconds','encoding_seconds'))
        cache={};answers=set();row['phase']='queries';save(a.out,row)
        for j,q in enumerate(workload['queries']):
            began=time.perf_counter();key=tuple(sorted(set(q['assumptions'])))
            hit=key in cache;lookup=time.perf_counter()-began;solve_time=0;local={}
            if not hit:
                tick=time.perf_counter()
                if a.method=='B2':
                    ok,forced=engine.propagate(key)
                    supports={l for v in reg.by_id for l in (v,-v) if -l not in forced} if ok else set()
                else:
                    ok,supports=solver.all_support(key);local=dict(solver.last_query_stats)
                cache[key]=(ok,frozenset(supports));solve_time=time.perf_counter()-tick
            ok,supports=cache[key]
            assert ok==q['expected_sat']
            tick=time.perf_counter();answer=[ok,sorted(supports)];output_time=time.perf_counter()-tick
            total=time.perf_counter()-began;answer_hash=digest(answer);answers.add(answer_hash)
            row['queries'].append(dict(index=j,cache_hit=hit,sat=ok,lookup_seconds=lookup,
                miss_compute_seconds=solve_time,output_seconds=output_time,seconds=total,
                answer_sha256=answer_hash,local=local))
            row.update(observed_unique_alpha=len(cache),observed_unique_answers=len(answers))
            if j%20==19 or j==0:save(a.out,row)
        row.update(status='OK',phase='done',cache_hits=sum(q['cache_hit'] for q in row['queries']),
            cache_misses=sum(not q['cache_hit'] for q in row['queries']),
            distinct_answers=len(answers),query_seconds=sum(q['seconds'] for q in row['queries']),
            miss_compute_seconds=sum(q['miss_compute_seconds'] for q in row['queries']),
            hit_seconds=sum(q['seconds'] for q in row['queries'] if q['cache_hit']),
            output_seconds=sum(q['output_seconds'] for q in row['queries']))
        row['total_seconds']=row['cold_seconds']+row['query_seconds']
        assert row['cache_misses']==a.unique and row['cache_hits']==1000-a.unique
        if a.method=='BD':row.update(local_hits=solver.total_local_hits,local_misses=solver.total_local_misses,
                                      component_sat_calls=solver.total_sat_calls)
    except ResourceLimit as exc:row.update(status='RESOURCE_LIMIT',reason=str(exc),partial_stats=getattr(exc,'stats',{}))
    except Exception:row.update(status='ERROR',traceback=traceback.format_exc())
    finally:
        if solver is not None:solver.close()
        memory=proc.memory_info();row.update(peak_wset_bytes=getattr(memory,'peak_wset',memory.rss),wall_seconds=time.perf_counter()-cold_start)
        save(a.out,row)


def run(config,path,limit=60):
    import psutil
    command=[sys.executable,str(Path(__file__).resolve()),'--worker','--out',str(path)]
    for k,v in config.items():command+=['--'+k,str(v)]
    child=subprocess.Popen(command,cwd=ROOT,env=dict(os.environ,PYTHONHASHSEED='0',WMCHECK_NATIVE_PORTS='0'),
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    began=time.perf_counter();peak=0;failure=None
    while child.poll() is None:
        try:peak=max(peak,psutil.Process(child.pid).memory_info().rss)
        except psutil.Error:pass
        if peak>1024**3:failure='MEMORY_LIMIT'
        elif time.perf_counter()-began>limit:failure='TIMEOUT'
        if failure:child.kill();break
        time.sleep(.01)
    stdout,stderr=child.communicate()
    row=json.loads(path.read_text()) if path.exists() else dict(config,status='ERROR')
    if failure:row.update(status=failure,reason='controller hard resource limit')
    elif child.returncode and row.get('status')!='ERROR':row.update(status='ERROR',reason='worker exit')
    row.update(controller_seconds=time.perf_counter()-began,peak_rss_sampled_bytes=peak,limit_seconds=limit,
               memory_limit_mib=1024,command=command)
    if stderr:row['stderr']=stderr.decode(errors='replace')
    save(path,row)
    print(path.name,row['status'],row.get('total_seconds'),len(row.get('queries',[])),flush=True)
    return row


def summarize():
    rows=[];checks={};mismatches=[]
    for path in sorted((OUT/'runs').glob('*.json')):
        row=json.loads(path.read_text());row['file']=path.name;rows.append(row)
        key=(row['family'],row['rounds'],row['U'])
        signatures=[q['answer_sha256'] for q in row.get('queries',[])]
        if key in checks:
            old=checks[key];size=min(len(old),len(signatures))
            if old[:size]!=signatures[:size]:mismatches.append(path.name)
            if len(signatures)>len(old):checks[key]=signatures
        else:checks[key]=signatures
    save(OUT/'summary.json',dict(rows=rows,answer_discrepancies=mismatches))
    assert not mismatches,mismatches


def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--out')
    p.add_argument('--family',default='barrier');p.add_argument('--rounds',type=int,default=8)
    p.add_argument('--unique',type=int,default=21);p.add_argument('--method',default='B2');p.add_argument('--repeat',type=int,default=0)
    a=p.parse_args()
    if a.worker:return worker(a)
    paths=sorted((ROOT/'wmcheck').glob('*.py'))+[Path(__file__),ROOT/'experiments/causal_followup_inputs.py']
    def hashes():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    frozen=hashes();save(OUT/'environment.json',dict(platform=platform.platform(),python=sys.version,executable=sys.executable,
        packages={p:importlib.metadata.version(p) for p in ('python-sat','psutil')},seconds=60,memory_mib=1024,
        repeats=3,seed_policy='fixed pool seeds in workload manifests',source_sha256=frozen))
    for family,n,us in [('barrier',8,(21,100,500,1000)),('barrier',16,(21,100,500,1000)),('buffer',8,(100,1000))]:
        for u in us:
            for method in ('B0','B1','BD','B2'):
                for rep in range(3):
                    assert hashes()==frozen
                    path=OUT/'runs'/f'{family}_n{n}_U{u}_{method}_r{rep}.json'
                    if path.exists():
                        row=json.loads(path.read_text())
                        if row['status']=='RUNNING':raise RuntimeError('Interrupted row must be preserved separately before retry')
                    else:row=run(dict(family=family,rounds=n,unique=u,method=method,repeat=rep),path)
                    summarize()
                    if row['status']=='ERROR':raise RuntimeError(row)
                    if row['status']!='OK':break
    save(OUT/'source_verification.json',dict(unchanged=hashes()==frozen,source_sha256=hashes()))


if __name__=='__main__':main()
