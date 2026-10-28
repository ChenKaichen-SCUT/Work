"""Verify every archived byte, then run tests and raw negative checks in a fresh copy."""
import argparse,hashlib,json,os,re,subprocess,sys,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--archive',type=Path,default=ROOT/'artifacts/causal_evidence_20261028.zip')
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--receipt',type=Path,default=ROOT/'artifacts/causal_evidence_20261028.recovery.json')
    a=p.parse_args();dest=a.destination.resolve();dest.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(a.archive) as z:
        manifest=json.loads(z.read('MANIFEST.json'))
        assert set(z.namelist())==set(manifest)|{'MANIFEST.json'}
        for name,entry in manifest.items():
            part=PurePosixPath(name);assert not part.is_absolute() and '..' not in part.parts
            target=dest.joinpath(*part.parts);assert target.resolve().is_relative_to(dest)
            data=z.read(name)
            assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256'],name
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    restored=dest/'solver'
    env=dict(os.environ,PYTHONHASHSEED='0',WMCHECK_NATIVE_PORTS='0',OMP_NUM_THREADS='1')
    test=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=restored,env=env,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
    log=a.receipt.with_suffix('.tests.txt');log.write_bytes(test.stdout)
    assert test.returncode==0,test.stdout.decode(errors='replace')[-4000:]
    counts=re.search(rb'Ran (\d+) tests?',test.stdout);skips=re.search(rb'OK \(skipped=(\d+)\)',test.stdout)
    records=[];runs=restored/'recovery_runs';runs.mkdir()
    for spec in sorted((restored/'results/causal_evidence_20261028/negative').glob('*.job.json')):
        out=runs/spec.name.replace('.job.json','.json')
        try:
            r=subprocess.run([sys.executable,'experiments/causal_evidence_runner.py','--job',str(spec),'--out',str(out)],
                cwd=restored,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
            row=json.loads(out.read_text(encoding='utf8'))
            assert r.returncode==0 and row['status']=='OK' and not row.get('certificate_supplied',True),row
            assert not row['disagreements']
            records.append(dict(case=row['job']['case'],status='OK',negative_checks=row['independent_negative_checks'],
                positive_controls=len(row['positive_controls']),sha256=hashlib.sha256(out.read_bytes()).hexdigest()))
        except subprocess.TimeoutExpired:
            records.append(dict(job=spec.name,status='UNKNOWN',reason='60 second recovery timeout'))
    receipt=dict(archive_sha256=hashlib.sha256(a.archive.read_bytes()).hexdigest(),verified_members=len(manifest),
        destination=str(dest),python=sys.version,reused_installed_environment=True,
        tests=int(counts[1]) if counts else None,skipped=int(skips[1]) if skips else 0,
        test_log_sha256=hashlib.sha256(test.stdout).hexdigest(),raw_checks=records,
        all_raw_checks_ok=all(r['status']=='OK' for r in records),
        scope='Byte-verified fresh extraction, full unit tests and rerun original RA negative checks; not a fresh OS dependency installation or performance rerun.')
    a.receipt.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2));assert receipt['all_raw_checks_ok']


if __name__=='__main__':main()
