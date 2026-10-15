"""Poct SC supplement; same source outcomes only on the proved common class."""
import argparse,hashlib,json,os,random,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_external import invoke
from experiments.paper_suite import save
from wmcheck.poct_adapter import export_poct
from wmcheck.ra import RARegistry,producers
from wmcheck.ra_program import parse_c_litmus


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='/root/wm-research')
    ap.add_argument('--out',default='results/paper/poct');ap.add_argument('--repeats',type=int,default=5)
    a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True);(out/'inputs').mkdir(exist_ok=True)
    base=Path(a.root)/'baselines/poct';binary=base/'zord_sc_solver'
    env=dict(os.environ,LD_LIBRARY_PATH=str(base/'lib'));cpu=min(os.sched_getaffinity(0))
    # Calibration validates the adapter on arbitrary partial original assignments.
    from pysat.solvers import Minisat22
    from wmcheck.ra_order_sat import encode_order
    inst=producers((2,2),((1,1),));enc=encode_order(inst);rng=random.Random(1487);cal=[]
    with Minisat22(bootstrap_with=enc.clauses) as s:
        for i in range(64):
            alpha=[v if rng.getrandbits(1) else -v for v in rng.sample(list(enc.registry.by_id),rng.randrange(enc.registry.nvars+1))]
            f=out/'inputs'/f'calibration_{i:02d}.smt';f.write_text(export_poct(inst,[[x] for x in alpha]))
            p=invoke([str(binary),'--show-statistics',str(f.resolve())],env,ROOT,cpu,out/f'calibration_{i:02d}',timeout=10)
            text=(out/p['stdout']).read_text();m=re.search(r'^\s*(sat|unsat)\s*$',text,re.M)
            expected=s.solve(assumptions=alpha);actual=m[1]=='sat' if m else None
            cal.append(dict(assumptions=alpha,expected=expected,actual=actual,process=p))
            if actual!=expected:save(out/'calibration.json',cal);raise RuntimeError(f'Poct adapter calibration {i} failed: {text}')
    save(out/'calibration.json',cal)
    save(out/'environment.json',dict(cpu=cpu,isolated=True,repeats=a.repeats,wall_limit_seconds=180,memory_limit_gib=4,
        artifact_doi='10.5281/zenodo.18616443',artifact_tar_sha256='e0984b7ccf8b1b570ba2ccb80b6340d43b4ede39e1f148462bcc5c7c1b675fe2',
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        adapter_sha256=hashlib.sha256((ROOT/'wmcheck/poct_adapter.py').read_bytes()).hexdigest(),
        scope='Poct SC only: pure single-address producer/reader inputs with proved RA=SC projection',
        source_frontend='Our fixed-event SMT adapter; this is not a full C frontend timing comparison'))
    cases=json.loads(Path('results/paper/external/inputs/manifest.json').read_text())
    pairs=[(c,m) for c in cases if c['dynamic_certificate'] and c['name'].startswith('producer_') for m in ('poct','poct-no-prop')]
    rng.shuffle(pairs);index=0
    for c,method in pairs:
        program=parse_c_litmus(Path(c['litmus']).read_text());reg=RARegistry(program.instance)
        f=out/'inputs'/(c['name']+'.smt');f.write_text(export_poct(program.instance,program.clauses(reg)))
        for repeat in range(a.repeats):
            spec=dict(c,method=method,repeat=repeat,smt_sha256=hashlib.sha256(f.read_bytes()).hexdigest())
            cmd=[str(binary),'--show-statistics']+(['--no-prop'] if method.endswith('no-prop') else [])+[str(f.resolve())]
            process=invoke(cmd,env,ROOT,cpu,out/f'{index:04d}')
            text=(out/process['stdout']).read_text();match=re.search(r'^\s*(sat|unsat)\s*$',text,re.M)
            r=dict(spec=spec,process=process,status='ok' if match and process['status']!='UNKNOWN' else 'UNKNOWN' if process['status']=='UNKNOWN' else 'ERROR')
            if match:r['reachable']=match[1]=='sat'
            else:r['reason']=process['reason'] or 'unrecognized_Poct_result'
            save(out/f'{index:04d}.json',r);print(index,c['name'],method,r['status'],r.get('reachable'),flush=True);index+=1
            if r['status']!='ok':break


if __name__=='__main__':main()
