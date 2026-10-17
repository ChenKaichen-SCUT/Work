"""Download a public GitHub commit; verify its complete Git tree; reproduce."""
import argparse,hashlib,json,os,stat,subprocess,sys,time,urllib.request,zipfile
from pathlib import Path,PurePosixPath

p=argparse.ArgumentParser();p.add_argument('commit');p.add_argument('tree');a=p.parse_args()
base=Path('/root/wm-github-recovery-20261017');base.mkdir(exist_ok=False)
project=base/'project';project.mkdir();started=time.time()
url=f'https://codeload.github.com/ChenKaichen-SCUT/Work/zip/{a.commit}'
archive=base/'github-source.zip'
with urllib.request.urlopen(url,timeout=180) as r,archive.open('wb') as f:
    while True:
        b=r.read(1024*1024)
        if not b:break
        f.write(b)
print('Downloaded GitHub commit',a.commit,archive.stat().st_size,flush=True)
def obj(kind,data):return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).digest()
root={};count=0;filebytes=0;source_sha256={}
with zipfile.ZipFile(archive) as z:
    prefix=z.namelist()[0].split('/')[0]+'/'
    for member in z.infolist():
        if member.is_dir():continue
        if not member.filename.startswith(prefix):raise RuntimeError('Bad ZIP prefix')
        name=member.filename[len(prefix):];path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:raise RuntimeError('Bad ZIP path')
        data=z.read(member);mode=(member.external_attr>>16)&0xffff
        if stat.S_ISLNK(mode):raise RuntimeError('Unexpected symlink')
        gitmode=b'100755' if mode&0o111 else b'100644'
        d=root
        for part in path.parts[:-1]:d=d.setdefault(part,{})
        d[path.name]=(gitmode,obj('blob',data))
        target=project/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data);os.chmod(target,0o755 if gitmode==b'100755' else 0o644)
        source_sha256[name]=hashlib.sha256(data).hexdigest();count+=1;filebytes+=len(data)
def tree(d):
    data=b''
    for name,item in sorted(d.items(),key=lambda x:(x[0]+('/' if isinstance(x[1],dict) else '')).encode()):
        mode,h=(b'40000',tree(item)) if isinstance(item,dict) else item
        data+=mode+b' '+name.encode()+b'\0'+h
    return obj('tree',data)
got=tree(root).hex()
if got!=a.tree:raise RuntimeError(f'Tree mismatch: {got} != {a.tree}')
print('Verified complete Git tree:',got,'files:',count,flush=True)
commands=[]
def run(cmd,timeout=1800):
    begin=time.time();proc=subprocess.run(cmd,cwd=project,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    name=f'verification-command-{len(commands):02d}.txt';(base/name).write_text(proc.stdout)
    commands.append(dict(argv=cmd,returncode=proc.returncode,seconds=time.time()-begin,log=name))
    print(name,proc.returncode,proc.stdout[-1200:],flush=True)
    if proc.returncode:raise RuntimeError('Failed: '+name)
run(['python3','scripts/restore_server_backup.py','--out',str(base/'archived-research')])
run(['bash','scripts/setup_reproduction.sh'])
run([str(project/'.venv/bin/python'),'experiments/fm_reproduce.py','--out',str(base/'replay-full'),'--full'])
receipt=json.loads((base/'replay-full/reproduction_receipt.json').read_text())
large=json.loads((base/'replay-full/large32.json').read_text())
rings=json.loads((base/'replay-full/ring_summary.json').read_text())
coverage=json.loads((project/'archives/server-20261017/manifest.json').read_text())
changed=[];missing=[]
for row in coverage['files']:
    current=Path('/root/wm-research')/row['path']
    if not current.is_file():missing.append(row['path'])
    elif hashlib.sha256(current.read_bytes()).hexdigest()!=row['sha256']:changed.append(row['path'])
if changed or missing:raise RuntimeError('Original server changed after snapshot')
result=dict(status='ok',commit=a.commit,git_tree=got,github_url=url,repository_files=count,
    repository_bytes=filebytes,github_zip_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    snapshot_files_verified=len(coverage['files']),server_changed_files=changed,server_missing_files=missing,
    source='GitHub codeload commit ZIP only; fresh directory and fresh venv; no old runtime or source paths used by reproduction',
    commands=commands,reproduction=receipt,large32=dict(status=large['status'],scenarios=len(large['queries']),
      literal_checks=sum(len(q['checks']) for q in large['queries']),matched_frozen_queries=large['matched_frozen_queries']),
    rings=[dict(workers=r['workers'],rounds=r['rounds'],irregular=r['irregular'],source_covers=r['source_covers'],status=r['status']) for r in rings],
    elapsed_seconds=time.time()-started)
(base/'github_recovery_verification.json').write_text(json.dumps(result,indent=2)+'\n')
print('VERIFIED',json.dumps({k:v for k,v in result.items() if k not in ('commands','reproduction','rings')}),flush=True)
