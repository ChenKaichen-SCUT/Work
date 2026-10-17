"""Collect research state, without credentials or disposable environments."""
import hashlib, io, json, os, re, shlex, subprocess, tarfile, time
from pathlib import Path

ROOT = Path('/root/wm-research')
OUT = Path('/root/wm-server-backup-20261017')
OUT.mkdir(exist_ok=True)
def run(argv, env=None, timeout=90):
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, env=env)
    return dict(argv=argv, returncode=p.returncode, output=p.stdout)
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def save(name, obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

environment = dict(captured_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
    os_release=Path('/etc/os-release').read_text(), uname=run(['uname','-a']),
    cpu=run(['lscpu']), memory=run(['free','-b']),
    apt_packages=run(['dpkg-query','-W','-f=${Package}\t${Version}\n']), commands={})
for name,cmd in {
    'runtime_python':[str(ROOT/'runtime/bin/python'),'--version'],
    'runtime_pip_freeze':[str(ROOT/'runtime/bin/python'),'-m','pip','freeze'],
    'old_venv_pip_freeze':[str(ROOT/'venv/bin/python'),'-m','pip','freeze'],
    'clean_pip_freeze':[str(ROOT/'fm-clean-reproduction-20261016/.venv/bin/python'),'-m','pip','freeze'],
    'g++':['g++','--version'], 'g++14':['g++-14','--version'],
    'clang19':['clang-19','--version'], 'java':['java','-version'],
    'maven':['mvn','-version'], 'xelatex':['xelatex','--version'],
    'cmake':['cmake','--version'], 'ninja':['ninja','--version']}.items():
    environment['commands'][name]=run(cmd)
opam_env=dict(os.environ,OPAMROOT=str(ROOT/'opam'))
environment['opam_export']=run(['opam','switch','export','--switch=wm-herd','-'],env=opam_env)
save('environment.json',environment)

baselines={}
extras=[]
for name in ['Dat3M','genmc','herdtools7']:
    p=ROOT/'baselines'/name
    meta={key:run(['git','-C',str(p),*args]) for key,args in {
        'origin':['remote','get-url','origin'], 'head':['rev-parse','HEAD'],
        'status':['status','--porcelain'], 'diff':['diff','HEAD','--binary'],
        'submodules':['submodule','status','--recursive']}.items()}
    untracked=run(['git','-C',str(p),'ls-files','--others','--exclude-standard'])['output'].splitlines()
    meta['untracked']=untracked
    for rel in untracked:
        if not rel.startswith(('build/','_build/','target/')):extras.append(p/rel)
    baselines[name]=meta
for rel in ['genmc/build/CMakeCache.txt','genmc/build/CMakeFiles/CMakeOutput.log',
            'genmc/build/build.ninja','herdtools7/Version.ml','herdtools7/_build/log']:
    if (ROOT/'baselines'/rel).is_file(): extras.append(ROOT/'baselines'/rel)
poct=ROOT/'baselines/poct'
baselines['poct']=dict(url='https://doi.org/10.5281/zenodo.18616443',
    artifact_url='https://zenodo.org/api/records/18616443/files/paper168-artifact.zip/content',
    tar_sha256='e0984b7ccf8b1b570ba2ccb80b6340d43b4ede39e1f148462bcc5c7c1b675fe2',files=[])
for p in sorted(poct.rglob('*')):
    if not p.is_file():continue
    s=p.stat()
    row=dict(path=p.relative_to(poct).as_posix(),bytes=s.st_size,allocated_bytes=s.st_blocks*512)
    if p.name=='artifact.zip':row['excluded_reason']='Incomplete sparse download; fetch the published DOI artifact instead.'
    else:row['sha256']=digest(p)
    baselines['poct']['files'].append(row)
    if p.name in ('archive_manifest.json','calibration.smt'):extras.append(p)
save('baselines.json',baselines)

skip={'runtime','venv','opam','baselines','.venv','__pycache__','.git','.pytest_cache'}
files=[];excluded=[]
for folder,dirs,names in os.walk(ROOT):
    for d in dirs:
        if d in skip:excluded.append(dict(path=(Path(folder)/d).relative_to(ROOT).as_posix(),
            reason='Reinstallable dependency/environment or cache; baseline pins and patches recorded separately.'))
    dirs[:]=[d for d in dirs if d not in skip]
    files.extend(Path(folder)/n for n in names)
files=sorted(set(files+extras))
rows=[];objects={};symlinks=[]
for p in files:
    rel=p.relative_to(ROOT).as_posix()
    if p.is_symlink():symlinks.append(dict(path=rel,target=os.readlink(p)));continue
    if not p.is_file():continue
    if p.suffix in ('.pyc','.pyo'):
        excluded.append(dict(path=rel,reason='Python bytecode cache'));continue
    if p.name=='.env' or p.suffix in ('.pem','.key') or p.name in ('id_rsa','id_ed25519'):
        raise RuntimeError('Unexpected credential-like file: '+rel)
    s=p.stat();sha=digest(p)
    rows.append(dict(path=rel,bytes=s.st_size,sha256=sha,mode=s.st_mode&0o777,mtime_ns=s.st_mtime_ns))
    objects.setdefault(sha,p)
manifest=dict(schema=1,root='/root/wm-research',captured_utc=environment['captured_utc'],
    files=rows,symlinks=symlinks,excluded=excluded,
    scope='All project research files, scripts, logs, results, inputs and historical source snapshots; excludes OS, credentials, caches, reinstallable environments and pristine upstream builds.',
    outside_root_audit=dict(root_other_entries='shell/user configuration and caches only; not copied',
        home_empty=True,opt_empty=True,mnt_empty=True,srv_empty=True,tmp='OS runtime files only'))
save('manifest.json',manifest)
with tarfile.open(OUT/'objects.tar.gz','w:gz',compresslevel=6) as t:
    for sha,p in sorted(objects.items()):
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=sha:raise RuntimeError('File changed during backup: '+str(p))
        info=tarfile.TarInfo('objects/'+sha);info.size=len(data);info.mode=0o644
        t.addfile(info,io.BytesIO(data))
summary=dict(files=len(rows),symlinks=len(symlinks),unique_objects=len(objects),
    original_bytes=sum(r['bytes'] for r in rows),unique_bytes=sum(p.stat().st_size for p in objects.values()),
    archive_bytes=(OUT/'objects.tar.gz').stat().st_size,archive_sha256=digest(OUT/'objects.tar.gz'),
    manifest_sha256=digest(OUT/'manifest.json'))
save('summary.json',summary)
print(json.dumps(summary),flush=True)
