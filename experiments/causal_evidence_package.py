"""Freeze this evidence round without replacing either earlier artifact."""
import hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_evidence_common import OUT,save
from experiments.causal_evidence_suite import freeze


def main():
    freeze()
    files=set()
    for folder in ('wmcheck','tests','experiments','validation','scripts'):
        files.update((ROOT/folder).rglob('*.py'))
    files.update((ROOT/'docs').glob('CAUSAL_*.txt'))
    for pattern in ('FUTURE_PORT*.txt','RELATIONAL_FORGETTING*.txt','PUBLICATION_CORE*.txt'):
        files.update((ROOT/'docs').glob(pattern))
    files.update(p for p in OUT.rglob('*') if p.is_file() and p.suffix not in ('.tmp','.log'))
    for name in ('README.md','AGENTS.md','MIGRATION_HANDOFF.zh.txt','.gitattributes',
        'CAUSAL_EVIDENCE_RESULTS.zh.txt','CAUSAL_FRONTIER_RESULTS.zh.txt',
        'CAUSAL_EXPERIMENT_RESULTS.zh.txt','CAUSAL_FOLLOWUP_RESULTS.zh.txt',
        'requirements.txt','requirements-causal.txt'):
        files.add(ROOT/name)
    members={'solver/'+p.relative_to(ROOT).as_posix():p for p in sorted(files)}
    manifest={name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for name,p in members.items()}
    archive=ROOT/'artifacts/causal_evidence_20261028.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for name,p in members.items():z.write(p,name)
        z.writestr('MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,entry in manifest.items():
            data=z.read(name)
            assert len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256']
    save(archive.with_suffix('.manifest.json'),dict(files=manifest,
        zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),zip_bytes=archive.stat().st_size,
        measured_sources_unchanged=True,
        earlier_snapshots='Earlier pilot/follow-up archives remain separate and unchanged; this archive measures the current source.'))
    print(archive,len(manifest),archive.stat().st_size,flush=True)


if __name__=='__main__':main()
