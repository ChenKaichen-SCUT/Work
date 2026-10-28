"""Archive the follow-up separately, preserving the earlier frozen pilot."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save


def main():
    measured=json.loads((ROOT/'results/causal_followup_20261028/environment.json').read_text())['source_sha256']
    assert all(hashlib.sha256((ROOT/p.replace('\\','/')).read_bytes()).hexdigest()==value for p,value in measured.items())
    files=set()
    for name in ('wmcheck','tests','experiments','validation'):
        files.update((ROOT/name).rglob('*.py'))
    files.update((ROOT/'docs').glob('CAUSAL_*.txt'))
    for pattern in ('FUTURE_PORT*.txt','RELATIONAL_FORGETTING*.txt','PUBLICATION_CORE*.txt'):
        files.update((ROOT/'docs').glob(pattern))
    for batch in ('causal_20261028','causal_followup_20261028'):
        files.update(p for p in (ROOT/'results'/batch).rglob('*') if p.is_file() and p.suffix!='.tmp')
    files.update(ROOT/name for name in ('README.md','CAUSAL_EXPERIMENT_RESULTS.zh.txt',
        'CAUSAL_FRONTIER_RESULTS.zh.txt','CAUSAL_FOLLOWUP_RESULTS.zh.txt','requirements.txt','requirements-causal.txt'))
    members={'solver/'+p.relative_to(ROOT).as_posix():p for p in sorted(files)}
    members['MIGRATION_HANDOFF.zh.txt']=ROOT.parent/'MIGRATION_HANDOFF.zh.txt'
    manifest={name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for name,p in members.items()}
    archive=ROOT/'artifacts/causal_followup_20261028.zip';archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for name,p in members.items():z.write(p,name)
        z.writestr('MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,entry in manifest.items():
            data=z.read(name)
            assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
    save(archive.with_suffix('.manifest.json'),dict(files=manifest,zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        zip_bytes=archive.stat().st_size,followup_measured_sources_unchanged=True,
        previous_batch_sources='Use the separately preserved causal_pilot_20261028.zip for the earlier exact source snapshot.'))
    print(archive,len(manifest),archive.stat().st_size,flush=True)


if __name__=='__main__':main()
