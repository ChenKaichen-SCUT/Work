"""Verify and restore the exact published result records into a fresh directory."""
import argparse,base64,gzip,hashlib,json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--package',default='results/paper');p.add_argument('--out',required=True);a=p.parse_args()
    src=Path(a.package).resolve();out=Path(a.out).resolve();manifest=json.loads((src/'MANIFEST.json').read_text())
    if out==src:raise ValueError('Unpack into a separate directory')
    entries={r['path']:r for r in manifest['files']};seen=set()
    if len(entries)!=len(manifest['files']):raise ValueError('Duplicate manifest member')
    def write(path,data):
        if path not in entries:raise ValueError('Unexpected archive member')
        if path in seen:raise ValueError('Duplicate archive member: '+path)
        target=(out/path).resolve()
        if out not in target.parents:raise ValueError('Archive path escapes output directory')
        r=entries[path]
        if len(data)!=r['bytes'] or hashlib.sha256(data).hexdigest()!=r['sha256']:raise ValueError('Content digest mismatch: '+path)
        if target.exists() and target.read_bytes()!=data:raise ValueError('Refusing to replace different local content: '+path)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);seen.add(path)
    for name,meta in manifest['archives'].items():
        data=b''.join((src/part).read_bytes() for part in meta.get('parts',[name]))
        if hashlib.sha256(data).hexdigest()!=meta['sha256']:raise ValueError('Archive digest mismatch: '+name)
        for line in gzip.decompress(data).splitlines():
            row=json.loads(line);write(row['path'],base64.b64decode(row['base64']))
    for row in manifest['files']:
        if not row['storage'].startswith('archives/'):write(row['path'],(src/row['storage']).read_bytes())
    if seen!=set(entries):raise ValueError('Missing result records')
    print('Verified and restored files:',len(seen))


if __name__=='__main__':main()
