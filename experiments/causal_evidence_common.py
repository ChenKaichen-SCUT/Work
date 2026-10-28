"""Shared inputs and bounded process controller for the next evidence round."""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest
OUT=ROOT/'results/causal_evidence_20261028'
CASES=[dict(family='buffer',rounds=n,capacity=3) for n in (4,8,16,32)]+[
    dict(family='buffer',rounds=8,capacity=c) for c in (2,4,6)]


def label(case):
    value=f"{case['family']}_n{case['rounds']}"
    if case['family']=='buffer':value+=f"_c{case['capacity']}"
    if case.get('failures'):value+=f"_f{case['failures']}"
    if case.get('tail_failures'):value+=f"_t{case['tail_failures']}"
    if case.get('partial'):value+='_partial'
    return value


def instance(case):
    from wmcheck.ra_protocols import barrier_instance,buffer_instance,prefix_input
    if case['family']=='barrier':return barrier_instance(case['rounds'])
    inp=buffer_instance(case['rounds'],capacity=case['capacity'],mode='branch',
        failures=case.get('failures',0),tail_failures=case.get('tail_failures',0))
    if case.get('partial'):inp=prefix_input(inp,{1:len(inp.inst.threads[1])-2})
    return inp


def run(job,path,seconds=60,memory_mib=1024):
    import psutil
    path=Path(path)
    if path.exists():
        row=json.loads(path.read_text(encoding='utf8'))
        if row['status']=='RUNNING':raise RuntimeError('Preserve interrupted RUNNING result before retry: '+str(path))
        return row
    spec=path.with_suffix('.job.json');save(spec,job)
    command=[sys.executable,str(ROOT/'experiments/causal_evidence_runner.py'),'--job',str(spec),'--out',str(path)]
    child=subprocess.Popen(command,cwd=ROOT,env=dict(os.environ,PYTHONHASHSEED='0',WMCHECK_NATIVE_PORTS='0',OMP_NUM_THREADS='1'),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    start=time.perf_counter();peak=0;failure=None
    while child.poll() is None:
        try:peak=max(peak,psutil.Process(child.pid).memory_info().rss)
        except psutil.Error:pass
        if peak>memory_mib*1024**2:failure='MEMORY_LIMIT'
        elif time.perf_counter()-start>seconds:failure='TIMEOUT'
        if failure:child.kill();break
        time.sleep(.02)
    stdout,stderr=child.communicate()
    row=json.loads(path.read_text(encoding='utf8')) if path.exists() else dict(status='ERROR',job=job)
    if failure:row.update(status='UNKNOWN' if job['mode']=='negative' else failure,resource_failure=failure)
    elif child.returncode:row.update(status='ERROR')
    row.update(limit_seconds=seconds,memory_limit_mib=memory_mib,controller_seconds=time.perf_counter()-start,
        peak_rss_sampled_bytes=peak,exit_code=child.returncode)
    if stderr:row['stderr']=stderr.decode(errors='replace')
    if stdout:row['stdout']=stdout.decode(errors='replace')
    save(path,row);print(path.name,row['status'],row.get('total_seconds'),len(row.get('queries',[])),flush=True)
    return row
