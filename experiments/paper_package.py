"""Package only our source inputs/results; never include downloaded baselines.

Original filenames are retained inside deterministic gzip JSONL bundles so the
analysis can be independently rerun after paper_unpack.py. No record is dropped.
"""
import argparse,base64,gzip,hashlib,json,shutil
from collections import defaultdict
from pathlib import Path


CAMPAIGNS=('pilot','primary_setup','primary','external','external_repair','external_direct','ablation','bdd_relational','bdd_coherence','poct','stress','pruning','sat_strong')


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='results/paper');p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.root).resolve();out=Path(a.out).resolve()
    if root==out or root in out.parents:raise ValueError('Use a separate delivery directory')
    out.mkdir(parents=True,exist_ok=True);(out/'archives').mkdir(exist_ok=True);groups=defaultdict(list)
    direct={'analysis.json','tables.txt'};manifest=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        rel=path.relative_to(root);parts=rel.parts
        if 'dat3m_output' in parts or path.suffix=='.tmp':continue
        data=path.read_bytes();entry=dict(path=rel.as_posix(),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        if rel.as_posix() in direct or parts[0] in ('figures','provenance') or path.name in ('coverage.json','cases.json','environment.json'):
            target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);entry['storage']=rel.as_posix()
        else:
            group=parts[0]
            if parts[0]=='inputs' and path.name.endswith('_queries.json'):group='queries-'+path.stem
            elif parts[0] in CAMPAIGNS:
                if path.suffix=='.json' and path.stem.isdigit():
                    r=json.loads(data);s=r.get('spec',{});group+='-'+s.get('id',s.get('name','records'))
                elif path.name.startswith('calibration_'):group+='-calibration'
                elif path.name.endswith(('.stdout.txt','.stderr.txt')):group+='-logs'
                elif len(parts)>1 and parts[1]=='inputs':group+='-inputs'
                else:group+='-metadata'
            # base64 is solely an archive transport encoding; source bytes and
            # hashes remain exact, including non-UTF8 tool output if present.
            groups[group].append(dict(path=rel.as_posix(),base64=base64.b64encode(data).decode()))
            entry['storage']='archives/'+group+'.jsonl.gz'
        manifest.append(entry)
    archives={}
    for group,entries in groups.items():
        data=''.join(json.dumps(row,separators=(',',':'))+'\n' for row in entries).encode()
        packed=gzip.compress(data,compresslevel=9,mtime=0);name='archives/'+group+'.jsonl.gz';parts=[]
        # Bounded binary objects keep authenticated API publication practical.
        # Concatenating the parts restores one ordinary gzip stream exactly.
        for j,offset in enumerate(range(0,len(packed),256*1024)):
            part=name if len(packed)<=256*1024 else name+f'.part{j:03d}'
            (out/part).write_bytes(packed[offset:offset+256*1024]);parts.append(part)
        archives[name]=dict(bytes=len(packed),sha256=hashlib.sha256(packed).hexdigest(),parts=parts)
    result=dict(format='gzip JSON lines: path + base64 exact source bytes',files=manifest,archives=archives,
        exclusions=['Dat3M generated intermediate compilation directory','in-progress atomic-write .tmp files'],
        campaigns_excluded_from_headline=['pilot','primary_setup'],
        note='Baseline source/binaries are outside the result root and are never packaged.')
    (out/'MANIFEST.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(files=len(manifest),archives=len(archives),bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file()))))


if __name__=='__main__':main()
