"""Public-corpus coverage and independently executed third-party checks.

Reads downloaded benchmarks in an external directory; never copies their source
into the publication tree. Stores paths, hashes, tool revisions and raw logs.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import queue
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wmcheck.litmus import parse_x86
from wmcheck.recognize import Unsupported


def invoke(cmd,env,timeout=30,cpu=None):
    if cpu is not None: cmd=['taskset','-c',str(cpu)]+cmd
    start=time.perf_counter()
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=timeout)
        return {'exit_code':p.returncode,'seconds':time.perf_counter()-start,'stdout':p.stdout,'stderr':p.stderr,'status':'finished'}
    except subprocess.TimeoutExpired as exc:
        return {'seconds':time.perf_counter()-start,'status':'timeout','stdout':str(exc.stdout or ''),'stderr':str(exc.stderr or '')}


def worker(args,out):
    if hasattr(os,'sched_setaffinity'): os.sched_setaffinity(0,{args['cpu']})
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    from wmcheck.compiler import compile_instance,ResourceLimit
    from wmcheck.eager import encode
    from pysat.solvers import Minisat22
    path=Path(args['path']);start=time.perf_counter();record={'path':args['relative'],'status':'ok'}
    try:
        inst=parse_x86(path.read_text(),name=path.stem)
        for method in ('proposed','eager'):
            t=time.perf_counter()
            try:
                enc=compile_instance(inst,max_seconds=20,max_transitions=100000) if method=='proposed' else encode(inst)
                with Minisat22(bootstrap_with=enc.clauses) as s: sat=s.solve()
                record[method]={'sat':sat,'seconds':time.perf_counter()-t,'stats':enc.stats}
            except ResourceLimit as exc: record[method]={'status':'resource_limit','reason':str(exc)}
    except Exception as exc: record['status']='error';record['reason']=repr(exc)
    record['seconds']=time.perf_counter()-start
    record['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    Path(out).write_text(json.dumps(record,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='/root/wm-research');p.add_argument('--out',default='results/public')
    p.add_argument('--sample',type=int,default=40);p.add_argument('--jobs',type=int,default=2);p.add_argument('--skip-dartagnan',action='store_true')
    p.add_argument('--worker');p.add_argument('--record');p.add_argument('--scan-only',action='store_true')
    a=p.parse_args()
    if a.worker: worker(json.loads(a.worker),a.record);return
    root=Path(a.root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    dat=root/'baselines'/'Dat3M';herd=root/'baselines'/'herdtools7';corpus=dat/'litmus'/'X86'
    manifest=[];accepted=[]
    for path in sorted(corpus.rglob('*.litmus')):
        text=path.read_text();record={'path':str(path.relative_to(dat)),'sha256':hashlib.sha256(text.encode()).hexdigest()}
        try:
            inst=parse_x86(text,path.stem);record['status']='parsed';record['events']=len(inst.events);accepted.append(path)
        except (Unsupported,ValueError) as exc: record['status']='unsupported';record['reason']=str(exc)
        manifest.append(record)
    versions={name:subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
              for name,repo in [('Dat3M',dat),('herdtools7',herd)]}
    meta={'revisions':versions,'total':len(manifest),'parsed':len(accepted),
          'unsupported_reasons':dict(Counter(r['reason'] for r in manifest if r['status']=='unsupported')),
          'recognition':'All parsed tests use a single event block. This is not evidence of a bounded-history certificate for long programs.',
          'selection':'Deterministic SHA256 filename ordering, first N parsed tests; no outcome/performance filtering.',
          'manifest':manifest}
    (out/'coverage.json').write_text(json.dumps(meta,indent=2))
    if a.scan_only: print(json.dumps({k:v for k,v in meta.items() if k!='manifest'},indent=2));return
    selected=sorted(accepted,key=lambda x:hashlib.sha256(str(x.relative_to(dat)).encode()).hexdigest())[:a.sample]
    env=dict(os.environ,DAT3M_HOME=str(dat));env['LD_LIBRARY_PATH']=str(dat/'dartagnan'/'target'/'libs')
    available_cpus=sorted(os.sched_getaffinity(0));cpus=available_cpus[-(a.jobs+2):-2] or available_cpus[:a.jobs]
    pool_cpus=queue.Queue()
    for cpu in cpus: pool_cpus.put(cpu)
    def run(index,path):
        cpu=pool_cpus.get();relative=str(path.relative_to(dat));record={'path':relative,'cpu':cpu}
        internal=out/f'{index:03d}-internal.json'
        args={'path':str(path),'relative':relative,'cpu':cpu}
        record['internal_process']=invoke([sys.executable,__file__,'--worker',json.dumps(args),'--record',str(internal)],env,45,cpu)
        if internal.exists(): record['internal']=json.loads(internal.read_text())
        h=invoke([str(herd/'_build'/'default'/'herd'/'herd.exe'),'-I',str(herd/'herd'/'libdir'),'-model','x86tso.cat',str(path)],env,30,cpu)
        match=re.search(r'^Observation .* (Never|Sometimes|Always)\s',h.get('stdout',''),re.M)
        if match and h.get('exit_code')==0: h['sat']=match[1]!='Never'
        record['herd7']=h
        if not a.skip_dartagnan:
            for method in ('lazy','eager'):
                command=['java','-Xmx2g','-Djava.library.path='+str(dat/'dartagnan'/'target'/'libs'),'-jar',
                         str(dat/'dartagnan'/'target'/'dartagnan.jar'),str(dat/'cat'/'tso.cat'),str(path),
                         '--method='+method,'--property=program_spec']
                d=invoke(command,env,30,cpu)
                match=re.search(r'^Result: (PASS|FAIL)\s*$',d.get('stdout',''),re.M)
                # Calibrated on SB (possible -> PASS) and SB+mfences
                # (impossible -> FAIL). Litmus existential specifications have
                # different result polarity from C assertion violations.
                if match and d.get('exit_code')==0: d['sat']=match[1]=='PASS'
                record['dartagnan_'+method]=d
        values=[]
        for method in ('proposed','eager'):
            r=record.get('internal',{}).get(method,{})
            if 'sat' in r: values.append(r['sat'])
        for method in ('herd7','dartagnan_lazy','dartagnan_eager'):
            if 'sat' in record.get(method,{}): values.append(record[method]['sat'])
        record['mismatch']=len(set(values))>1
        (out/f'{index:03d}.json').write_text(json.dumps(record,indent=2))
        print(index,relative,'mismatch',record['mismatch'],flush=True)
        pool_cpus.put(cpu)
        return record
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        records=[f.result() for f in as_completed([pool.submit(run,i,path) for i,path in enumerate(selected)])]
    summary={'selected':len(records),'mismatches':sum(r['mismatch'] for r in records),'revisions':versions,
             'successful_results':{method:sum('sat' in r.get(method,{}) for r in records) for method in ('herd7','dartagnan_lazy','dartagnan_eager')}}
    (out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))


if __name__=='__main__': main()
