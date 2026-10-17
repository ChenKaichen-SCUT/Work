"""Create a self-contained evidence archive; includes only allowlisted files."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();dest=Path(a.output)
    dest.parent.mkdir(parents=True,exist_ok=True);files={}
    for folder in ('wmcheck','experiments','tests'):
        for path in (ROOT/folder).iterdir():
            if path.suffix in ('.py','.cpp','.java','.cat'):files[path.relative_to(ROOT).as_posix()]=path
    for path in (ROOT/'docs').glob('*.txt'):files[path.relative_to(ROOT).as_posix()]=path
    for name in ('README.md','requirements.txt','requirements-paper.txt','requirements-fm.txt',
                 'PUBLICATION_RESULTS.zh.txt','SUPPORT_TASK_RESULTS.zh.txt','FM_READINESS_RESULTS.zh.txt'):
        files[name]=ROOT/name
    evidence=ROOT/'results/fm_evidence_20261016'
    for path in evidence.rglob('*'):
        if path.is_file() and path.suffix in ('.json','.txt','.c','.litmus','.zip'):
            files[path.relative_to(ROOT).as_posix()]=path
    reference=ROOT/'results/support_task_20261016'
    names=['inputs/epoch_32.json','runs/epoch_32_ports-atomic_s1000000_0.json','summary.json','demand_summary.json',
           'environment.json','runs/constant_6_ports-atomic_s1000000_0.json','demand_runs/epoch_32_0.json']
    for name in names:files['reference/support_task_20261016/'+name]=reference/name
    manifest={name:dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for name,path in sorted(files.items())}
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for name,path in sorted(files.items()):z.write(path,name)
        z.writestr('manifest.json',json.dumps(manifest,indent=2)+'\n')
    receipt=dict(path=str(dest),files=len(files),bytes=dest.stat().st_size,
        sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    dest.with_suffix('.sha256.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
