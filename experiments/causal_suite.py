"""Frozen sequential pilot; retain failure rows and never rank different tasks."""
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.causal_bench import run_one, save, summarize


def sources():
    files = sorted((ROOT/'wmcheck').glob('*.py')) + [ROOT/'experiments'/name for name in
        ('causal_bench.py','causal_suite.py','causal_semantic_audit.py')]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    folder = ROOT/'results/causal_20261028'
    frozen = sources()
    save(folder/'environment.json',dict(platform=platform.platform(),processor=platform.processor(),
        python=sys.version,executable=sys.executable,packages={p:importlib.metadata.version(p) for p in
        ('python-sat','psutil','matplotlib','numpy')},seconds=30,memory_mib=1024,
        states=200000,edges=600000,seed=0,repeats=3,hash_seed='0',native_ports=False,
        source_sha256=frozen,experiment_date='2026-10-28',
        boundary='local Windows pilot; explicit protocol templates; not industrial applicability'))
    jobs=[]
    for n in (2,4,8,16,32):
        for method in ('B0','B1','B2'):
            for rep in range(3):
                jobs.append((f'history_{method}_n{n}_r{rep}',dict(rounds=n,method=method,repeat=rep),100))
    for task in ('sat','single'):
        for method in ('B0','B1','B2'):
            for rep in range(3):
                jobs.append((f'{task}_{method}_n8_r{rep}',dict(rounds=8,method=method,task=task,repeat=rep),100))
    for method in ('B0','B1','B2'):
        for rep in range(3):
            jobs.append((f'reuse1000_{method}_n8_r{rep}',dict(rounds=8,method=method,repeat=rep),1000))
    for n in (2,8,32):
        for rep in range(3):
            jobs.append((f'gap_B2_n{n}_r{rep}',dict(rounds=n,method='B2',long_gap=True,repeat=rep),100))
    for failures in (1,4,16):
        for rep in range(3):
            jobs.append((f'poll_B2_f{failures}_r{rep}',dict(rounds=4,method='B2',failures=failures,repeat=rep),100))
    for n in (2,8,16):
        for rep in range(3):
            jobs.append((f'ordinary_B2_n{n}_r{rep}',dict(rounds=n,method='B2',layout='ordinary',repeat=rep),100))
            jobs.append((f'dense_B2_n{n}_r{rep}',dict(rounds=n,method='B2',dense_co=True,repeat=rep),100))
    stopped=set()
    skipped=[]
    for name, config, count in jobs:
        path=folder/'runs'/f'{name}.json'
        family=name.split('_')[0]
        key=(family,config['method'],config.get('rounds'),config.get('failures',0))
        if key in stopped:
            skipped.append(dict(name=name,reason='same configuration already hit hard resource limit'))
            continue
        if sources()!=frozen:
            raise RuntimeError('Measured source changed after freeze')
        if path.exists():
            row=json.loads(path.read_text(encoding='utf8'))
        else:
            row=run_one(config,path,seconds=30,memory_mib=1024,queries=count)
        if row['status']=='ERROR':
            raise RuntimeError(f'Implementation error, stop measurement: {path}')
        if row['status']!='OK':
            stopped.add(key)
        save(folder/'skipped.json',skipped)
        summary=summarize(folder)
        if summary['answer_discrepancies']:
            raise AssertionError(summary['answer_discrepancies'])
    save(folder/'source_verification.json',dict(unchanged=sources()==frozen,sha256=sources()))
    print('FINAL',summarize(folder)['counts'],flush=True)


if __name__=='__main__':main()
