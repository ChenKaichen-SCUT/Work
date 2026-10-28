"""Tree-aware controller: Windows venv Python can be a small launcher process.

The measured algorithms stay byte-identical. Original results are preserved.
"""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_evidence_common import OUT,save


def run(job,path,seconds=60,memory_mib=1024):
    import psutil
    path=Path(path)
    if path.exists():
        row=json.loads(path.read_text(encoding='utf8'))
        if row['status']=='RUNNING':raise RuntimeError('Preserve interrupted record before retry: '+str(path))
        return row
    spec=path.with_suffix('.job.json');save(spec,job)
    child=subprocess.Popen([sys.executable,str(ROOT/'experiments/causal_evidence_runner.py'),'--job',str(spec),'--out',str(path)],
        cwd=ROOT,env=dict(os.environ,PYTHONHASHSEED='0',WMCHECK_NATIVE_PORTS='0',OMP_NUM_THREADS='1'),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    start=time.perf_counter();peak=0;failure=None;seen={}
    while child.poll() is None:
        current=[]
        try:
            parent=psutil.Process(child.pid);current=[parent]+parent.children(recursive=True)
        except psutil.Error:pass
        total=0
        for proc in current:
            try:total+=proc.memory_info().rss;seen[proc.pid]=proc
            except psutil.Error:pass
        peak=max(peak,total)
        if peak>memory_mib*1024**2:failure='MEMORY_LIMIT'
        elif time.perf_counter()-start>seconds:failure='TIMEOUT'
        if failure:
            for proc in reversed(list(seen.values())):
                try:proc.kill()
                except psutil.Error:pass
            child.kill();break
        time.sleep(.02)
    stdout,stderr=child.communicate()
    row=json.loads(path.read_text(encoding='utf8')) if path.exists() else dict(status='ERROR',job=job)
    if failure:row.update(status='UNKNOWN' if job['mode']=='negative' else failure,resource_failure=failure)
    elif child.returncode:row.update(status='ERROR')
    row.update(limit_seconds=seconds,memory_limit_mib=memory_mib,controller_seconds=time.perf_counter()-start,
        peak_tree_rss_sampled_bytes=peak,observed_processes=len(seen),exit_code=child.returncode,
        controller='Tree-aware: sum RSS of launcher and recursive children; kill all observed processes on limit')
    if stderr:row['stderr']=stderr.decode(errors='replace')
    if stdout:row['stdout']=stdout.decode(errors='replace')
    save(path,row);print(path.name,row['status'],row.get('total_seconds'),len(row.get('queries',[])),flush=True)
    return row


def main():
    from experiments import causal_evidence_suite as suite
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['audit','prepare','scan','tasks','robustness','negative'],default='audit');a=p.parse_args()
    suite.freeze()
    original_rows=suite.summarize()
    if a.phase=='audit':
        for row in original_rows:
            if row['file'].startswith('scan/') and row['status']=='TIMEOUT':
                result=run(row['job'],OUT/'resource_audit'/Path(row['file']).name)
                assert result['status']!='ERROR',result
    else:
        # Same suite and fixed workloads, with only the controller replaced.
        suite.run=run;sys.argv=[sys.argv[0],a.phase];suite.main()
    save(OUT/'resource_controller.json',dict(source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        measured_algorithm_sources_unchanged=bool(suite.freeze()),
        original_limitation='Original external sampled RSS covered only the Windows venv launcher. Successful workers separately recorded their own OS peak working set. Timeout rows had no worker peak.',
        reporting='Use worker OS peak for completed original runs; separately report tree-aware resource rechecks. Never substitute launcher RSS as solver memory.'))


if __name__=='__main__':main()
