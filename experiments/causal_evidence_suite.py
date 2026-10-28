"""Bounded, sequential study; seed selection is recorded before robustness runs."""
import argparse,hashlib,importlib.metadata,json,platform,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_evidence_common import OUT,CASES,label,run,save
TASK_CASES=[dict(family='barrier',rounds=8),dict(family='buffer',rounds=8,capacity=3)]


def freeze():
    paths=sorted((ROOT/'wmcheck').glob('*.py'))+[ROOT/'experiments'/p for p in
        ('causal_bench.py','causal_evidence_common.py','causal_evidence_inputs.py','causal_evidence_runner.py','causal_evidence_suite.py','causal_evidence_negative.py')]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    path=OUT/'environment.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf8'))['source_sha256']==hashes,'Measured code changed'
    else:save(path,dict(platform=platform.platform(),python=sys.version,packages={p:importlib.metadata.version(p) for p in ('python-sat','psutil')},
        source_sha256=hashes,resource_seconds=60,memory_mib=1024,scan_repeats=3,robustness_repeats=2))
    return hashes


def summarize():
    rows=[];signatures={};disagreements=[]
    for folder in ('scan','robustness','tasks','negative'):
        for p in sorted((OUT/folder).glob('*.json')):
            if p.name.endswith('.job.json'):continue
            r=json.loads(p.read_text(encoding='utf8'));job=r['job']
            key=(job['mode'],label(job['case']),job.get('seed',0),job.get('order',0),job.get('profile'))
            if job['mode']=='bench':sigs=[q['answer_sha256'] for q in r.get('queries',[])]
            elif job['mode']=='task':sigs=[q['result_sha256'] for q in r.get('reports',[])]
            else:sigs=[]
            old=signatures.get(key,[]);size=min(len(old),len(sigs))
            if old[:size]!=sigs[:size]:disagreements.append(str(p.relative_to(OUT)))
            if len(sigs)>len(old):signatures[key]=sigs
            compact={k:v for k,v in r.items() if k not in ('queries','reports','witnesses','positive_controls')}
            compact.update(file=p.relative_to(OUT).as_posix(),completed_queries=len(r.get('queries',[])),completed_episodes=len(r.get('reports',[])))
            rows.append(compact)
    save(OUT/'summary.json',dict(rows=rows,answer_discrepancies=disagreements));assert not disagreements
    return rows


def checked(job,path,seconds=60):
    freeze();row=run(job,path,seconds=seconds);summarize()
    if row['status']=='ERROR':raise RuntimeError(row.get('traceback',row))
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','scan','tasks','robustness','negative','summarize']);a=p.parse_args()
    if a.phase=='prepare':
        for case in CASES:
            row=run(dict(mode='generate',case=case,seed=0),OUT/'preparation'/f'{label(case)}_s0.json',seconds=120)
            assert row['status']=='OK',row
        for case in TASK_CASES:
            row=run(dict(mode='logs',case=case),OUT/'preparation'/f'{label(case)}_logs.json',seconds=120);assert row['status']=='OK',row
        return
    if a.phase=='scan':
        for case in CASES:
            for method in ('B0','B1','BD','B2'):
                for rep in range(3):
                    job=dict(mode='bench',case=case,seed=0,order=0,method=method,repeat=rep)
                    r=checked(job,OUT/'scan'/f'{label(case)}_{method}_r{rep}.json')
                    if r['status']!='OK':break
    elif a.phase=='tasks':
        for case in TASK_CASES:
            for profile in ('sparse','dense'):
                for method in ('B0','B1','BD','B2'):
                    for rep in range(3):
                        job=dict(mode='task',case=case,profile=profile,method=method,repeat=rep)
                        r=checked(job,OUT/'tasks'/f'{label(case)}_{profile}_{method}_r{rep}.json')
                        if r['status']!='OK':break
    elif a.phase=='robustness':
        rows=summarize();ratios=[]
        for case in CASES:
            costs={m:[r['total_seconds'] for r in rows if r['job']['mode']=='bench' and r['job']['case']==case and r['job']['method']==m and r['status']=='OK' and r['file'].startswith('scan/')] for m in ('BD','B2')}
            if all(costs.values()):ratios.append(dict(case=case,ratio=statistics.median(costs['B2'])/statistics.median(costs['BD'])))
        selected=[dict(family='buffer',rounds=8,capacity=3)]
        others=[r for r in ratios if r['case'] not in selected]
        if others:selected.append(min(others,key=lambda r:abs(r['ratio']-1))['case'])
        for ix,case in enumerate(CASES):
            failed=any(r['job']['case']==case and r['job'].get('method')=='B2' and r['status']!='OK' for r in rows if r['file'].startswith('scan/'))
            if failed:
                neighbours=[c for c in reversed(CASES[:ix]) if any(r['case']==c for r in ratios)]
                if neighbours and neighbours[0] not in selected:selected.append(neighbours[0])
                break
        save(OUT/'robustness_selection.json',dict(selected=selected,ratios=ratios,rule='Existing n8/C3; nearest successful B2/BD ratio to one; previous successful scan configuration before first B2 failure if any'))
        for case in selected:
            for seed in (1,2):
                prepared=run(dict(mode='generate',case=case,seed=seed),OUT/'preparation'/f'{label(case)}_s{seed}.json',seconds=120)
                assert prepared['status']=='OK',prepared
                for order in (0,1):
                    for method in ('BD','B2'):
                        for rep in range(2):
                            job=dict(mode='bench',case=case,seed=seed,order=order,method=method,repeat=rep)
                            r=checked(job,OUT/'robustness'/f'{label(case)}_s{seed}_o{order}_{method}_r{rep}.json')
                            if r['status']!='OK':break
    elif a.phase=='negative':
        from experiments.causal_evidence_negative import CASES as NEGATIVE_CASES
        for case in NEGATIVE_CASES:
            checked(dict(mode='negative',case=case),OUT/'negative'/f'{label(case)}.json')
    summarize()
    if a.phase!='summarize':save(OUT/f'source_verification_{a.phase}.json',dict(unchanged=True,source_sha256=freeze()))


if __name__=='__main__':main()
