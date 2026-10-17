"""Portable quick check and bounded Linux full reproduction for the FM evidence."""
import argparse,hashlib,json,os,platform,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--full',action='store_true')
    p.add_argument('--frozen');a=p.parse_args();out=Path(a.out).resolve()
    if out.exists():raise FileExistsError('Choose a fresh output directory: '+str(out))
    out.mkdir(parents=True);commands=[];start=time.perf_counter()
    def run(argv,limit=600):
        begin=time.perf_counter();proc=subprocess.run([sys.executable,*argv],cwd=ROOT,capture_output=True,text=True,timeout=limit)
        name=f'command_{len(commands):02d}.txt';(out/name).write_text(proc.stdout+proc.stderr,encoding='utf8')
        commands.append(dict(argv=argv,returncode=proc.returncode,seconds=time.perf_counter()-begin,log=name))
        print(name,proc.returncode,argv,flush=True)
        if proc.returncode:raise RuntimeError('Reproduction failed; inspect '+str(out/name))
    if a.full:
        if platform.system()!='Linux':raise RuntimeError('Full bounded workers use Linux resource/affinity APIs; quick mode is portable')
        run(['experiments/build_port_native.py']);os.environ['WMCHECK_NATIVE_PORTS']='1'
        run(['-m','unittest','discover','-s','tests','-v'])
    else:run(['-m','unittest','discover','-s','tests','-p','test_fm_evidence.py','-v'])
    run(['experiments/fm_structure_audit.py','--out',str(out)])
    if a.full:
        frozen=Path(a.frozen).resolve() if a.frozen else ROOT/'reference/support_task_20261016'
        if not frozen.exists():frozen=ROOT/'results/support_task_20261016'
        run(['experiments/fm_large_audit.py','--out',str(out),'--frozen',str(frozen)])
        run(['experiments/fm_ring_study.py','--out',str(out)],limit=1500)
        large=json.loads((out/'large32.json').read_text());assert large['status']=='ok'
        assert len(large['queries'])==53 and sum(len(q['checks']) for q in large['queries'])==826
        assert large['matched_frozen_queries']==41
        rings=json.loads((out/'ring_summary.json').read_text())
        expected={(3,2,False,True):5738,(3,3,False,True):313864,(3,3,False,False):313864,
                  (3,2,True,True):5900,(4,2,False,True):20253}
        for r in rings:
            key=(r['workers'],r['rounds'],r['irregular'],r['source_covers'])
            if key in expected:assert r['status']=='ok' and r['stats']['raw_states']==expected[key]
            else:assert key==(3,4,False,True) and r['status']=='UNKNOWN'
    receipt=dict(status='ok',mode='full' if a.full else 'quick',platform=platform.platform(),python=sys.version,
        elapsed_seconds=time.perf_counter()-start,commands=commands,
        source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('wmcheck','experiments','tests') for p in (ROOT/folder).iterdir() if p.suffix in ('.py','.cpp')})
    (out/'reproduction_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print('Reproduction complete:',out,flush=True)


if __name__=='__main__':main()
