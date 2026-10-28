"""Equal complete-answer caching on both incremental SAT and compiled graphs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest,workload


def worker(method,out):
    import psutil
    from wmcheck.ra_protocols import barrier_instance,build_protocol,replay_certificate
    from wmcheck.ra_frontier import prepare_frontier,compile_frontier
    from wmcheck.ra import RARegistry
    from wmcheck.ra_support_sat import SupportSAT
    from wmcheck.owned_dag import OwnedGraphSolver
    proc=psutil.Process();proc.cpu_affinity([min(proc.cpu_affinity())])
    started=time.perf_counter();inp=barrier_instance(8);reg=RARegistry(inp.inst)
    queries=workload(inp.inst,1000)
    cert=None
    if method!='B0':
        pre=build_protocol(inp);assert replay_certificate(inp,pre);cert=pre['certificate']
    if method=='B2':
        plan=prepare_frontier(inp.inst,certificate=cert,order=pre['order'],co_mode='direct',summary_mode='ports',early_degrees=True)
        compiled=compile_frontier(inp.inst,prepared=plan,max_states=200000,max_edges=600000,max_seconds=30)
        engine=OwnedGraphSolver(compiled)
    else:engine=SupportSAT(inp,certificate=cert,solver='cadical195')
    cold=time.perf_counter()-started
    cache={};records=[];misses=0
    for q in queries:
        tick=time.perf_counter();key=tuple(sorted(set(q['assumptions'])))
        miss=key not in cache
        if miss:
            misses+=1
            if method=='B2':
                sat,forced=engine.propagate(key)
                supported={l for v in reg.by_id for l in (v,-v) if -l not in forced} if sat else set()
            else:sat,supported=engine.all_support(key)
            cache[key]=(sat,frozenset(supported))
        sat,supported=cache[key]
        # Materialize and sort the complete answer for every hit as well as miss.
        answer=[sat,sorted(supported)]
        elapsed=time.perf_counter()-tick
        records.append(dict(seconds=elapsed,answer_sha256=digest(answer),cache_miss=miss))
    if method!='B2':engine.close()
    memory=proc.memory_info()
    save(out,dict(status='OK',method=method,rounds=8,queries=records,cache_entries=len(cache),
        cache_misses=misses,cold_seconds=cold,query_seconds=sum(q['seconds'] for q in records),
        input_sha256=digest(inp),workload_sha256=digest(queries),
        peak_wset_bytes=getattr(memory,'peak_wset',memory.rss),
        contract='all methods memoize the entire original support answer; complete output charged on every hit'))


def main():
    import psutil
    p=argparse.ArgumentParser();p.add_argument('--worker',choices=['B0','B1','B2']);p.add_argument('--out')
    a=p.parse_args()
    if a.worker:return worker(a.worker,a.out)
    folder=ROOT/'results/causal_20261028/cache';folder.mkdir(exist_ok=True)
    rows=[];reference=None
    for method in ('B0','B1','B2'):
        for rep in range(3):
            path=folder/f'{method}_{rep}.json';began=time.perf_counter()
            command=[sys.executable,str(Path(__file__).resolve()),'--worker',method,'--out',str(path)]
            child=subprocess.Popen(command,cwd=ROOT,env=dict(os.environ,PYTHONHASHSEED='0',WMCHECK_NATIVE_PORTS='0'),
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            process=psutil.Process(child.pid);peak=0;failure=None
            while child.poll() is None:
                try:peak=max(peak,process.memory_info().rss)
                except psutil.Error:pass
                if peak>1024**3:failure='MEMORY_LIMIT'
                if time.perf_counter()-began>30:failure='TIMEOUT'
                if failure:child.kill();child.wait();break
                time.sleep(.01)
            row=json.loads(path.read_text(encoding='utf8')) if path.exists() else dict(method=method,status=failure or 'ERROR')
            if failure:row['status']=failure
            row.update(repeat=rep,peak_rss_sampled_bytes=peak,controller_seconds=time.perf_counter()-began)
            save(path,row);rows.append(row)
            assert row['status']=='OK',row
            answers=[q['answer_sha256'] for q in row['queries']]
            if reference is None:reference=answers
            else:assert reference==answers
            prior=json.loads((folder.parent/'runs'/f'reuse1000_{method}_n8_r0.json').read_text(encoding='utf8'))
            assert answers[:len(prior['queries'])]==[q['answer_sha256'] for q in prior['queries']]
            print(method,rep,row['cold_seconds'],row['query_seconds'],row['cache_misses'],flush=True)
    save(folder/'summary.json',dict(rows=rows,answer_discrepancies=[],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


if __name__=='__main__':main()
