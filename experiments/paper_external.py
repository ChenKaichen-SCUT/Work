"""Observable outcome and identical-Boolean-backend comparisons.

All C programs are generated from the same finite event instance. FAIL for a
C assertion and SAT for a memory encoding both mean the specified outcome is
reachable. No SC-only tool is compared on a genuinely non-SC RA instance.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import sys
import time
import threading
import traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_cases import instance,layout
from experiments.paper_suite import save
from wmcheck.ra import RAInstance,RARegistry,producers
from wmcheck.model import Event
from wmcheck.ra_program import RAProgram,parse_c_litmus,export_c,export_litmus
from wmcheck.ra_schedule import certificate,OutsideCertificate


def genmc_reachable(text,source):
    if 'No errors were detected.' in text:return False
    if 'Verification unsuccesful' not in text:return None
    # GenMC 0.19 calls __VERIFIER_error / assertion failures Safety violations.
    # Confirm the reported ERROR event is our generated final assertion, rather
    # than treating another memory-safety diagnostic as the desired outcome.
    if 'Safety violation!' in text:
        path=Path(source)
        lines=[j for j,line in enumerate(path.read_text().splitlines(),1) if re.match(r'\s*assert\(',line)]
        if any(f'ERROR {path.name}:{j}' in text for j in lines):return True
    if 'Assertion violation' in text:return True
    return None


def prepare(out,inputs):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);cases=[]
    for n in (2,8,32,64):
        for values in ((1,1),(1,0)):
            i=producers((n,n),(values,));cases.append((f'producer_{n}_{values[0]}{values[1]}',i,dict(family='producers',n=n)))
    for family,n in [('pipeline',1),('pipeline',2),('non_sc_chain',1),('non_sc_chain',4),('sb',1),('mp',1),('lb',1)]:
        s=dict(family=family,n=n);cases.append((f'{family}_{n}',instance(s),s))
    for s in json.loads((Path(inputs)/'cases.json').read_text()):
        if s['family']=='public':cases.append((s['name'],instance(s),s))
    records=[]
    for name,inst,spec in cases:
        lit=out/(name+'.litmus');c=out/(name+'.c');lit.write_text(export_litmus(inst,name=name));c.write_text(export_c(inst))
        try:certificate(inst);pure=True
        except OutsideCertificate:pure=False
        records.append(dict(name=name,litmus=str(lit.resolve()),c=str(c.resolve()),case=spec,
            dynamic_certificate=pure,events=len(inst.events),
            litmus_sha256=hashlib.sha256(lit.read_bytes()).hexdigest(),c_sha256=hashlib.sha256(c.read_bytes()).hexdigest()))
    save(out/'manifest.json',records);return records


def internal(spec,dest):
    import resource
    from pysat.solvers import Minisat22
    from wmcheck.ra_schedule import compile_schedule
    from wmcheck.ra_frontier import compile_frontier
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.ra_order_sat import encode_order
    from wmcheck.ra_sat import encode_ra
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    start=time.perf_counter();r=dict(spec=spec,status='running',stage='parse');save(dest,r)
    try:
        p=parse_c_litmus(Path(spec['litmus']).read_text());parse_time=time.perf_counter()-start
        method=spec['method'];r['stage']='compile';save(dest,r)
        inst=p.conditioned() if method in ('proposed-direct','proposed-frontier-direct') else p.instance
        if method=='sat-cnf':c=encode_order(inst) if spec['dynamic_certificate'] else encode_ra(inst)
        elif spec['dynamic_certificate']:
            c=compile_schedule(inst,cnf=method.startswith('support-'),max_states=200000,max_edges=600000,max_seconds=120)
        else:
            # Parser renames events. A round-robin input layout is independent
            # of the observed outcome and can be reproduced from the source.
            order=inst.initial+tuple(t[j] for j in range(max(map(len,inst.threads),default=0)) for t in inst.threads if j<len(t))
            options=dict(co_mode='direct',early_degrees=True) if method.endswith('frontier-direct') else {}
            c=compile_frontier(inst,order=order,cnf=method.startswith('support-'),max_states=200000,max_edges=600000,max_seconds=120,**options)
        r.update(stats=c.stats,parse_seconds=parse_time);r['stage']='solve';save(dest,r)
        t=time.perf_counter()
        if method.startswith('proposed-'):sat=OwnedGraphSolver(c).propagate()[0]
        else:
            prop=p.clauses(c.registry)
            r['property_clauses']=len(prop);r['original_registry_sha256']=hashlib.sha256(json.dumps(c.registry.by_id,sort_keys=True).encode()).hexdigest()
            r['property_sha256']=hashlib.sha256(json.dumps(prop).encode()).hexdigest()
            with Minisat22(bootstrap_with=c.clauses+prop) as s:
                sat=s.solve();r['solver_stats']=s.accum_stats()
        r.update(status='ok',reachable=sat,solve_seconds=time.perf_counter()-t)
    except Exception as exc:
        from wmcheck.compiler import ResourceLimit
        r.update(status='UNKNOWN' if isinstance(exc,(ResourceLimit,MemoryError)) else 'ERROR',reason=str(exc),traceback=traceback.format_exc())
    r.update(total_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss);save(dest,r)


def invoke(command,env,cwd,cpu,logprefix,timeout=180):
    import psutil
    logprefix=Path(logprefix);stdout=logprefix.with_suffix('.stdout.txt');stderr=logprefix.with_suffix('.stderr.txt')
    start=time.perf_counter();peak=0;status='finished';reason=None;finished=threading.Event()
    with stdout.open('w') as o,stderr.open('w') as e:
        p=subprocess.Popen(['taskset','-c',str(cpu),*command],cwd=cwd,env=env,stdout=o,stderr=e,start_new_session=True)
        def monitor():
            nonlocal peak,status,reason
            while not finished.is_set():
                try:
                    parent=psutil.Process(p.pid);rss=sum(q.memory_info().rss for q in [parent,*parent.children(recursive=True)] if q.is_running())
                    peak=max(peak,rss)
                except psutil.Error:pass
                if time.perf_counter()-start>timeout or peak>4*1024**3:
                    status='UNKNOWN';reason='wall_timeout' if time.perf_counter()-start>timeout else 'process_tree_rss_limit'
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    break
                finished.wait(.02)
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        p.wait();wall=time.perf_counter()-start;finished.set();watcher.join()
    return dict(status=status,reason=reason,exit_code=p.returncode,wall_seconds=wall,
        process_tree_peak_rss_kib=peak/1024 if peak else None,rss_sample_interval_seconds=.02,
        command=command,stdout=stdout.name,stderr=stderr.name)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='/root/wm-research');ap.add_argument('--out',default='results/paper/external')
    ap.add_argument('--inputs',default='results/paper/inputs');ap.add_argument('--repeats',type=int,default=5)
    ap.add_argument('--internal');ap.add_argument('--record');ap.add_argument('--methods',nargs='*');ap.add_argument('--select',nargs='*')
    a=ap.parse_args()
    if a.internal:internal(json.loads(a.internal),a.record);return
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True);root=Path(a.root);dat=root/'baselines/Dat3M';gen=root/'baselines/genmc'
    cases=prepare(out/'inputs',a.inputs);cpu=min(os.sched_getaffinity(0));env=dict(os.environ,DAT3M_HOME=str(dat),
        DAT3M_OUTPUT=str((out/'dat3m_output').resolve()),PATH='/usr/lib/llvm-19/bin:'+os.environ['PATH'])
    (out/'dat3m_output').mkdir(exist_ok=True)
    methods=a.methods or ['proposed-direct','support-cnf','sat-cnf','genmc','dartagnan-lazy','dartagnan-eager']
    pairs=[(c,m) for c in cases if not a.select or c['name'] in a.select for m in methods]
    random.Random(20261015).shuffle(pairs)
    versions={name:subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip() for name,repo in [('Dat3M',dat),('GenMC',gen)]}
    save(out/'environment.json',dict(cpu=cpu,isolated=True,repeats=a.repeats,wall_limit_seconds=180,
        process_tree_rss_limit_gib=4,java_heap_gib=2,versions=versions,
        code_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
            for directory in ('wmcheck','experiments') for f in (ROOT/directory).glob('*.py')},
        task='Observed read-value outcome reachability in fixed straight-line RA programs',
        baseline_results='C assertion FAIL means reachable; no borrowed timing from litmus mode'))
    index=0
    for case,method in pairs:
        for repeat in range(a.repeats):
            spec=dict(case,method=method,repeat=repeat);dest=out/f'{index:04d}.json';rec=dict(spec=spec,status='running');save(dest,rec)
            if method in ('proposed-direct','support-cnf','sat-cnf','proposed-frontier-direct','support-frontier-direct'):
                command=[sys.executable,str(Path(__file__).resolve()),'--internal',json.dumps(spec),'--record',str(dest.resolve())];cwd=ROOT
            elif method=='genmc':
                command=[str(gen/'build/bin/genmc'),'--rc11','--disable-estimation',case['c']];cwd=ROOT
            else:
                command=['java','-Xmx2g','-XX:ActiveProcessorCount=1','-XX:+UseSerialGC','-Djava.library.path='+str(dat/'dartagnan/target/libs'),
                    '-jar',str(dat/'dartagnan/target/dartagnan.jar'),str(dat/'cat/rc11.cat'),case['c'],'--target=c11',
                    '--method='+method.split('-')[1],'--property=program_spec','--bound=4'];cwd=dat
            process=invoke(command,env,cwd,cpu,out/f'{index:04d}')
            rec=json.loads(dest.read_text());rec['process']=process
            if process['status']=='UNKNOWN':rec.update(status='UNKNOWN',reason=process['reason'])
            elif method=='genmc':
                text=(out/process['stdout']).read_text()
                result=genmc_reachable(text,case['c'])
                if result is not None:rec.update(status='ok',reachable=result)
                else:rec.update(status='ERROR',reason='unrecognized_GenMC_result')
                match=re.search(r'Number of complete executions explored:\s*(\d+)',text)
                if match:rec['executions']=int(match[1])
            elif method.startswith('dartagnan'):
                text=(out/process['stdout']).read_text();match=re.search(r'^Result: (PASS|FAIL|UNKNOWN)\s*$',text,re.M)
                if match and match[1]!='UNKNOWN':rec.update(status='ok',reachable=match[1]=='FAIL')
                else:rec.update(status='UNKNOWN' if match else 'ERROR',reason='Dartagnan_unknown' if match else 'unrecognized_Dartagnan_result')
            save(dest,rec);print(index,case['name'],method,rec['status'],rec.get('reachable'),flush=True);index+=1
            if rec['status']!='ok':break


if __name__=='__main__':main()
