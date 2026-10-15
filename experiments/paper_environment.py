"""Capture reproducibility metadata without network credentials or host addresses."""
import hashlib,json,os,platform,subprocess,sys
from pathlib import Path


def main():
    base=Path('/root/wm-research');out=Path('results/paper/provenance');out.mkdir(parents=True,exist_ok=True)
    commands={'cpu':['lscpu'],'os':['cat','/etc/os-release'],'kernel':['uname','-srmo'],
        'memory':['free','-b'],'python_packages':[sys.executable,'-m','pip','freeze'],
        'java':['java','-version'],'clang':['/usr/lib/llvm-19/bin/clang','--version'],
        'genmc_version':[str(base/'baselines/genmc/build/bin/genmc'),'--version']}
    result=dict(platform=platform.platform(),python=sys.version,cpu_affinity=sorted(os.sched_getaffinity(0)),commands={})
    for name,cmd in commands.items():
        p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20)
        result['commands'][name]=dict(command=cmd,returncode=p.returncode,output=p.stdout)
    result['baseline_revisions']={name:subprocess.check_output(['git','-C',str(base/'baselines'/name),'rev-parse','HEAD'],text=True).strip()
                                 for name in ('genmc','Dat3M')}
    result['baseline_binaries_sha256']={name:hashlib.sha256((base/path).read_bytes()).hexdigest() for name,path in (
        ('genmc','baselines/genmc/build/bin/genmc'),('dartagnan','baselines/Dat3M/dartagnan/target/dartagnan.jar'),('poct','baselines/poct/zord_sc_solver'))}
    (out/'environment.json').write_text(json.dumps(result,indent=2))


if __name__=='__main__':main()
