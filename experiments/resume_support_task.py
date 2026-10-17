"""Resume the frozen campaign after its worker's 4 GiB failure reporter failed.

Uses exactly the original worker/source and budget. The original successful
records are never replaced. Adds parent-side handling of failed workers.
"""
import argparse,json,os,subprocess,sys
from pathlib import Path
from support_task_study import save,analyze


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    out=Path(a.out);cpu=min(os.sched_getaffinity(0))
    configs=[('epoch',32,'bdd-coherence',1000000,3)]
    for n in (2,3,4,6):
        for method in ('ports-atomic','sat-phase','bdd-coherence'):
            configs.append(('constant',n,method,1000000,3))
    configs += [('epoch',4,'ports-python',1000000,3),('epoch',8,'ports-python',1000000,3),
                ('constant',3,'ports-binary',200000,1),('constant',3,'ports-atomic',200000,1),
                ('epoch',64,'ports-atomic',2000000,1)]
    for payload,n,method,states,repeats in configs:
        for rep in range(repeats):
            record=out/'runs'/f'{payload}_{n}_{method}_s{states}_{rep}.json'
            if record.exists():raise FileExistsError(record)
            cmd=[sys.executable,str(Path(__file__).with_name('support_task_study.py')),'--out',str(out),
                '--worker',payload,str(n),method,'--record',str(record),'--cpu',str(cpu),'--states',str(states)]
            proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                stdout,stderr=proc.communicate(timeout=240)
                if proc.returncode:
                    row=json.loads(record.read_text()) if record.exists() else {}
                    save(record,dict(row,status='UNKNOWN' if 'MemoryError' in stderr or proc.returncode<0 else 'ERROR',
                        reason='worker_memory_failure' if 'MemoryError' in stderr else 'worker_exit',
                        returncode=proc.returncode,stderr=stderr))
            except subprocess.TimeoutExpired:
                proc.kill();stdout,stderr=proc.communicate();row=json.loads(record.read_text())
                save(record,dict(row,status='UNKNOWN',reason='wall_timeout_240s',stderr=stderr))
            row=json.loads(record.read_text());print(payload,n,method,rep,row['status'],flush=True)
            if row['status']!='ok':break
    analyze(out)


if __name__=='__main__':main()
