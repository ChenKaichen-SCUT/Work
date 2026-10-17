"""Fetch the measured upstream revisions into a fresh chosen baseline directory."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path)
    p.add_argument('--tool',choices=['Dat3M','genmc','herdtools7','all'],default='all');a=p.parse_args()
    pins=json.loads((ROOT/'archives/server-20261017/baselines.json').read_text())
    for name in ['Dat3M','genmc','herdtools7']:
        if a.tool not in ('all',name):continue
        entry=pins[name];target=a.out.resolve()/name
        if target.exists():raise FileExistsError('Choose a fresh destination: '+str(target))
        url=entry['origin']['output'].strip();commit=entry['head']['output'].strip()
        target.mkdir(parents=True)
        def git(*args):return subprocess.check_output(['git','-C',str(target),*args],text=True).strip()
        git('init');git('remote','add','origin',url);git('fetch','--depth','1','origin',commit)
        git('checkout','--detach','FETCH_HEAD')
        if git('rev-parse','HEAD')!=commit:raise RuntimeError('Revision mismatch')
        if entry['diff']['output'].strip():raise RuntimeError('Unexpected nonempty historical patch')
        print(name,commit,flush=True)

if __name__=='__main__':main()
