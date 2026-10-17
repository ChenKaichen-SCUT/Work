"""Verify and optionally restore the research snapshot into a NEW directory."""
import argparse, hashlib, io, json, os, tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'archives/server-20261017'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--backup',type=Path,default=DEFAULT)
    ap.add_argument('--out',type=Path,help='Fresh directory; omit to verify only')
    args=ap.parse_args();src=args.backup.resolve()
    package=json.loads((src/'package.json').read_text(encoding='utf8'))
    for name,expected in package['metadata_sha256'].items():
        if sha((src/name).read_bytes())!=expected:raise ValueError('Metadata mismatch: '+name)
    manifest=json.loads((src/'manifest.json').read_text(encoding='utf8'))
    data=[]
    for row in package['parts']:
        b=(src/row['name']).read_bytes()
        if len(b)!=row['bytes'] or sha(b)!=row['sha256']:raise ValueError('Part mismatch: '+row['name'])
        data.append(b)
    compressed=b''.join(data)
    if sha(compressed)!=package['archive_sha256']:raise ValueError('Archive mismatch')
    objects={}
    with tarfile.open(fileobj=io.BytesIO(compressed),mode='r:gz') as t:
        for member in t:
            if not member.isfile() or not member.name.startswith('objects/'):raise ValueError('Invalid member')
            digest=member.name.removeprefix('objects/');b=t.extractfile(member).read()
            if sha(b)!=digest or digest in objects:raise ValueError('Invalid content object')
            objects[digest]=b
    if manifest['symlinks']:raise ValueError('This snapshot should not contain symlinks')
    paths=set()
    for row in manifest['files']:
        path=PurePosixPath(row['path'])
        if path.is_absolute() or '..' in path.parts or ':' in row['path'] or row['path'] in paths:
            raise ValueError('Invalid or duplicate path')
        paths.add(row['path'])
        if len(objects[row['sha256']])!=row['bytes']:raise ValueError('Size mismatch')
    if set(objects)!={r['sha256'] for r in manifest['files']}:raise ValueError('Object set mismatch')
    out=args.out.resolve() if args.out else None
    if out:
        if out.exists():raise FileExistsError('Choose a NEW output directory: '+str(out))
        out.mkdir(parents=True)
        for row in manifest['files']:
            dest=out/row['path'];dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(objects[row['sha256']])
            os.chmod(dest,row['mode']);os.utime(dest,ns=(row['mtime_ns'],row['mtime_ns']))
    print(json.dumps(dict(status='ok',files=len(paths),unique_objects=len(objects),
        original_bytes=sum(r['bytes'] for r in manifest['files']),archive_sha256=package['archive_sha256'],
        restored_to=str(out) if out else None),indent=2))

if __name__=='__main__':main()
