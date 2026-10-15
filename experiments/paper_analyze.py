"""Audit comparable tasks before aggregating paper results; keep every failure."""
import argparse
from collections import defaultdict,Counter
import gzip
import json
from pathlib import Path
import statistics


def distribution(xs):
    xs=sorted(xs)
    if not xs:return None
    q=statistics.quantiles(xs,n=4,method='inclusive') if len(xs)>1 else [xs[0]]*3
    return dict(n=len(xs),median=statistics.median(xs),min=xs[0],max=xs[-1],q1=q[0],q3=q[2])


def analyze(root):
    root=Path(root);rows=[];external=[];environments={}
    for name in ('primary','ablation','bdd_relational','bdd_coherence','stress','pruning','sat_strong','external','external_repair','external_direct','poct'):
        directory=root/name
        if not directory.exists():continue
        if (directory/'environment.json').exists():environments[name]=json.loads((directory/'environment.json').read_text())
        for p in sorted(directory.glob('[0-9]*.json')):
            r=json.loads(p.read_text());r['campaign']=name;r['record_path']=p.relative_to(root).as_posix()
            (external if name in ('external','external_repair','external_direct','poct') else rows).append(r)
    grouped=defaultdict(list);answers={};mismatches=[];checked=defaultdict(set);profile_errors=[]
    for r in rows:
        s=r['spec'];grouped[r['campaign'],s['id'],s['method']].append(r)
        if s['method']=='sat-up':continue
        for j,h in enumerate(r.get('answer_hashes',[])):
            key=(s['id'],r['query_sha256'],j)
            if key in answers and answers[key]!=h:mismatches.append(dict(path=r['record_path'],query=j))
            answers[key]=h;checked[key].add(s['method'])
        if 'max_interface' in r and 'interface' in s and r['max_interface']!=s['interface']['width']:
            profile_errors.append(r['record_path'])
    aggregates=[]
    for (campaign,case,method),rs in sorted(grouped.items()):
        completed=[r for r in rs if r['status']=='ok'];s=rs[0]['spec']
        row=dict(campaign=campaign,id=case,case={k:v for k,v in s.items() if k not in ('queries','query_sha256','method','repeat','cpu')},
            method=method,statuses=dict(Counter(r['status'] for r in rs)),records=[r['record_path'] for r in rs],
            attempted=sum(r['status']!='SKIPPED_AFTER_RESOURCE_LIMIT' for r in rs),completed=len(completed))
        for metric in ('compile_seconds','setup_seconds','peak_rss_kib','states','transitions','max_interface','max_layer_states','bdd_nodes','original_satisfying_assignments','clauses','label_literals','unique_label_literals'):
            row[metric]=distribution([r[metric] for r in completed if metric in r])
        row['checkpoints']={}
        for count in (1,8,64,512):
            valid=[r for r in rs if r.get('completed_queries',0)>=count]
            if valid:
                row['checkpoints'][str(count)]=dict(
                    total=distribution([r['compile_seconds']+r.get('setup_seconds',0)+sum(r['query_times'][:count]) for r in valid]),
                    queries=distribution([sum(r['query_times'][:count]) for r in valid]),
                    satisfiable_queries=sum(valid[0]['verdicts'][:count]),
                    complete_sat_calls=distribution([sum(r.get('sat_calls',[])[:count]) for r in valid]))
        row['failures']=[dict(path=r['record_path'],status=r['status'],stage=r.get('stage'),reason=r.get('reason'),
                             completed_queries=r.get('completed_queries',0),
                             elapsed_seconds=r.get('elapsed_seconds'),peak_rss_kib=r.get('peak_rss_kib'),
                             construction_stats=r.get('failure_stats')) for r in rs if r['status']!='ok']
        aggregates.append(row)
    propagation=[]
    for key,rs in grouped.items():
        campaign,case,method=key
        if campaign!='primary' or method!='sat-up':continue
        ups=[r for r in rs if r['status']=='ok']
        refs=[r for r in grouped.get(('primary',case,'sat'),[])+grouped.get(('sat_strong',case,'sat-up-assisted'),[])+grouped.get(('sat_strong',case,'sat-phase-assisted'),[]) if r.get('completed_queries',0)]
        if not ups or not refs:continue
        u=ups[0];ref=max(refs,key=lambda r:r.get('completed_queries',0));n=min(u['completed_queries'],ref['completed_queries'])
        sat=[j for j in range(n) if ref['verdicts'][j]];unsat=[j for j in range(n) if not ref['verdicts'][j]]
        propagation.append(dict(id=case,queries=n,sat_queries=len(sat),unsat_queries=len(unsat),
            missed_conflicts=sum(u['verdicts'][j] for j in unsat),
            missed_forced_literals=sum(ref['forced_counts'][j]-u['forced_counts'][j] for j in sat),
            queries_with_missing_forced=sum(ref['forced_counts'][j]>u['forced_counts'][j] for j in sat),
            exact_queries=sum(ref['answer_hashes'][j]==u['answer_hashes'][j] for j in range(n))))
    egroups=defaultdict(list);everdicts=defaultdict(set);boolhashes=defaultdict(set)
    for r in external:
        s=r['spec'];campaign='external' if r['campaign']=='external_repair' else r['campaign']
        egroups[campaign,s['name'],s['method']].append(r)
        if r['status']=='ok':
            # Poct rows explicitly use only the proved SC-equivalent family.
            everdicts[s['name']].add(r['reachable'])
            if 'property_sha256' in r:boolhashes[s['name']].add((r['property_sha256'],r['original_registry_sha256']))
    eaggregates=[]
    for (campaign,name,method),rs in sorted(egroups.items()):
        ok=[r for r in rs if r['status']=='ok'];row=dict(campaign=campaign,name=name,method=method,
            statuses=dict(Counter(r['status'] for r in rs)),completed=len(ok),attempted=len(rs),
            reachable=ok[0]['reachable'] if ok else None,records=[r['record_path'] for r in rs])
        for metric in ('wall_seconds','process_tree_peak_rss_kib'):
            row[metric]=distribution([r['process'][metric] for r in ok if r.get('process',{}).get(metric) is not None])
        for metric in ('total_seconds','solve_seconds','parse_seconds'):
            row[metric]=distribution([r[metric] for r in ok if metric in r])
        row['solver_stats']={metric:distribution([r['solver_stats'][metric] for r in ok if metric in r.get('solver_stats',{})])
                             for metric in ('decisions','conflicts','propagations')}
        eaggregates.append(row)
    workloads={}
    for r in rows:
        s=r['spec'];key=s['id']
        if key in workloads or not s.get('queries'):continue
        path=Path(s['queries'])
        if not path.exists():
            candidates=list(root.rglob(path.name));path=candidates[0] if candidates else path
        if path.exists():
            qs=json.loads(path.read_text());unique={tuple(sorted(a)) for a in qs}
            workloads[key]=dict(queries=len(qs),unique_partial_assignments=len(unique),
                empty_queries=sum(not a for a in qs),variables=s.get('variables'),
                workload=s.get('workload','independent seeded partial assignments'))
    result=dict(run_counts=dict(backend=len(rows),external=len(external)),
        statuses=dict(Counter(r['status'] for r in rows+external)),
        exact_query_mismatches=mismatches,profile_mismatches=profile_errors,
        external_verdict_mismatches={k:list(v) for k,v in everdicts.items() if len(v)>1},
        boolean_interface_mismatches=[k for k,v in boolhashes.items() if len(v)>1],
        query_comparisons=sum(len(v)>1 for v in checked.values()),
        completed_backend_query_evaluations=sum(r.get('completed_queries',0) for r in rows if r['spec']['method']!='sat-up'),
        workloads=workloads,aggregates=aggregates,propagation=propagation,external=eaggregates,environments=environments)
    (root/'analysis.json').write_text(json.dumps(result,indent=2))
    lines=['campaign case method completed/attempted compile_seconds total_1 total_8 total_64 total_512 rss_MiB']
    fmt=lambda d:f"{d['median']:.6g}" if d else '-'
    for r in aggregates:
        times=[fmt(r['checkpoints'].get(str(k),{}).get('total')) for k in (1,8,64,512)]
        mem=r['peak_rss_kib'];lines.append(' '.join([r['campaign'],r['id'],r['method'],f"{r['completed']}/{r['attempted']}",fmt(r['compile_seconds']),*times,
            f"{mem['median']/1024:.3f}" if mem else '-']))
    lines+=['','Observable outcome comparisons: name method completed/attempted reachable process_wall_seconds']
    for r in eaggregates:lines.append(f"{r['name']} {r['method']} {r['completed']}/{r['attempted']} {r['reachable']} {fmt(r['wall_seconds'])}")
    (root/'tables.txt').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('aggregates','external','environments','propagation','workloads')},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='results/paper');a=p.parse_args();analyze(a.root)
