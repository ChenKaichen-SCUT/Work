"""Verify a fresh archive extraction, then run correctness checks in that copy."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save


def main():
    p=argparse.ArgumentParser();p.add_argument('--target',type=Path,
        default=ROOT.parent/'tmp/causal-followup-replay-20261028');a=p.parse_args()
    target=a.target.resolve()
    if target.exists():raise RuntimeError('Use a fresh extraction directory; existing work is never removed')
    archive=ROOT/'artifacts/causal_followup_20261028.zip'
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('MANIFEST.json'))
        for name in z.namelist():
            if not (target/name).resolve().is_relative_to(target):raise ValueError('Unsafe archive member')
        z.extractall(target)
    for name,entry in manifest.items():
        data=(target/name).read_bytes()
        assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
    checks=[]
    for label,args in [('unittest',['-m','unittest','discover','-s','tests','-v']),
                       ('decomposition',['experiments/causal_decomposition_audit.py'])]:
        started=time.perf_counter()
        proc=subprocess.run([sys.executable]+args,cwd=target/'solver',capture_output=True,timeout=180)
        logfile=target/(label+'.log');logfile.write_bytes(proc.stdout+proc.stderr)
        checks.append(dict(check=label,exit_code=proc.returncode,seconds=time.perf_counter()-started,
                           log=str(logfile),log_sha256=hashlib.sha256(logfile.read_bytes()).hexdigest()))
        assert proc.returncode==0,checks[-1]
    original=json.loads((ROOT/'results/causal_followup_20261028/decomposition.json').read_text())
    replay=json.loads((target/'solver/results/causal_followup_20261028/decomposition.json').read_text())
    for a,b in zip(original['barrier'],replay['barrier']):
        assert a['rounds']==b['rounds'] and a['factor_model_counts']==b['factor_model_counts']
        assert a.get('complete_model_set_sha256')==b.get('complete_model_set_sha256')
    assert replay['buffer']['each_literal_raw_sat'] and replay['buffer']['joint_raw_unsat']
    receipt=dict(status='OK',archive=str(archive),archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        target=str(target),members_verified_before_execution=len(manifest),checks=checks,
        decomposition_projection_hashes_reproduced=True,environment='existing installed Python reused; no fresh OS/dependency installation claim')
    save(archive.with_suffix('.recovery.json'),receipt);print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
