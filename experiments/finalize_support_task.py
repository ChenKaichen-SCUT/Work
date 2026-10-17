"""Read-only evidence checks plus a reproducible manifest for the task campaign."""
import argparse,collections,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):return json.loads(path.read_text(encoding='utf8'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    out=Path(parser.parse_args().out).resolve();env=read(out/'environment.json')
    changed={}
    with zipfile.ZipFile(out/'measured_sources.zip') as archive:
        for name,h in env['source_sha256'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==h,name
            now=sha(ROOT/name)
            if now!=h:changed[name]=dict(measured=h,current=now)
        assert hashlib.sha256(archive.read('experiments/support_task_demand.py')).hexdigest()==read(out/'demand_environment.json')['source_sha256']
    assert set(changed)<= {'experiments/support_task_study.py','experiments/support_task_demand.py'},changed
    runs=[read(p) for p in sorted((out/'runs').glob('*.json'))]
    demand=[read(p) for p in sorted((out/'demand_runs').glob('*.json'))]
    comparisons=[]
    for payload,n in sorted({(r['payload'],r['n']) for r in runs}):
        ok=[r for r in runs if (r['payload'],r['n'],r['status'])==(payload,n,'ok')]
        assert ok
        ref=ok[0];refq=[{k:v for k,v in q.items() if k!='seconds'} for q in ref['queries']]
        for r in ok:
            assert r['reports']==ref['reports'] and r['log_sha256']==ref['log_sha256']
            assert [{k:v for k,v in q.items() if k!='seconds'} for q in r['queries']]==refq
        task_ok=[r for r in demand if (r['payload'],r['n'],r['status'])==(payload,n,'ok')]
        for r in task_ok:assert r['reports']==ref['reports'] and r['log_sha256']==ref['log_sha256']
        comparisons.append(dict(payload=payload,n=n,full_support_methods=sorted({r['method'] for r in ok}),
            full_support_records=len(ok),task_specific_sat_records=len(task_ok),reports=len(ref['reports']),
            query_calls=len(ref['queries']),distinct_queries=len({tuple(q['assumptions']) for q in ref['queries']}),
            all_completed_full_answers_and_reports_equal=True,
            independent_full_support_backend=any(r['method'] in ('sat-phase','bdd-coherence') for r in ok)))
    controls=[]
    for n in (4,8):
        native=next(r for r in runs if (r['payload'],r['n'],r['method'])==('epoch',n,'ports-atomic'))
        python=next(r for r in runs if (r['payload'],r['n'],r['method'])==('epoch',n,'ports-python'))
        fields=('raw_states','raw_transitions','states','transitions','attempted_transitions','max_layer_states')
        for field in fields:assert native['stats'][field]==python['stats'][field],field
        assert native['stats']['native_port_steps']>0 and python['stats']['native_port_steps']==0
        controls.append(dict(n=n,identical_native_python_structure={f:native['stats'][f] for f in fields}))
    native=read(out/'native_full_set_audit.json');assert len(native)==6
    for r in native:
        assert r['full_h_l_rf_sets_equal']
        p=out/'native_analysis'/f"n{r['n']}"/Path(r['file'].replace('\\','/')).name
        assert sha(p)==r['sha256']
    semantic=read(out/'semantic_audit.json')
    for name,h in semantic['source_sha256'].items():assert sha(ROOT/name.replace('\\','/'))==h
    validation=read(out/'post_campaign_driver_validation/receipt.json');assert len(validation)==4
    for r in validation:assert sha(ROOT/'experiments'/r['script'])==r['source_sha256']
    for r in read(out/'genmc_outcomes.json'):
        if r['status']=='ok':assert sha(out/'inputs'/f"epoch_{r['n']}.c")==r['sha256']
    manifests={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
        if p.is_file() and p.name!='artifact_manifest.json' and '__pycache__' not in p.parts}
    current={p.relative_to(ROOT).as_posix():sha(p) for folder in ('wmcheck','experiments','tests')
        for p in sorted((ROOT/folder).iterdir()) if p.suffix in ('.py','.cpp','.java','.cat')}
    manifest=dict(format=1,measured_source_count=len(env['source_sha256']),measured_zip_all_hashes_verified=True,
        current_measured_source_differences=changed,all_measured_runtime_sources_unchanged=True,
        main_status_counts=dict(collections.Counter(r['status'] for r in runs)),
        demand_status_counts=dict(collections.Counter(r['status'] for r in demand)),
        demand_error_note='epoch 32 retains original ERROR: encoding MemoryError followed by reporter MemoryError; no result inferred',
        driver_validation_excluded_from_timing=True,comparisons=comparisons,native_python_controls=controls,
        native_full_set_audit_cases=len(native),semantic_named_queries=len(semantic['named']),
        independent_repair_audit_cases=len(semantic['repairs']),independent_sc_checks=len(semantic['sc_outcomes']),
        current_source_sha256=current,data_sha256=manifests)
    (out/'artifact_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:manifest[k] for k in ('measured_source_count','main_status_counts','demand_status_counts','native_full_set_audit_cases','semantic_named_queries','independent_sc_checks')},indent=2))


if __name__=='__main__':main()
