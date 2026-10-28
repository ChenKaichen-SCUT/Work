"""Predetermined exclusions tested against raw RA/guards, with no D/H/L input."""
import json,time
from experiments.causal_evidence_common import OUT,label,instance,save,digest

CASES=[dict(family='buffer',rounds=8,capacity=c) for c in (2,3,4)]+[
    dict(family='buffer',rounds=16,capacity=3),
    dict(family='buffer',rounds=8,capacity=3,failures=1,tail_failures=2),
    dict(family='buffer',rounds=8,capacity=3,partial=True),dict(family='barrier',rounds=8)]


def select(case):
    from wmcheck.ra import RARegistry
    from wmcheck.ra_protocols import build_protocol
    from wmcheck.ra_support_sat import SupportSAT
    from wmcheck.ra_task_diagnosis import field
    inp=instance(case);pre=build_protocol(inp);cert=pre['certificate'];reg=RARegistry(inp.inst)
    assert pre['status']=='CERTIFIED'
    stages=pre['stages'];failed=set();tail=set();partial=set()
    for attempts in inp.contract.get('attempts',[]):
        count=0
        for a in attempts:
            endpoints={e for e in (a['own'],a['peer']) if e is not None}
            if a['outcome']:
                failed.update(endpoints)
                if count==case['rounds']:tail.update(endpoints)
            elif a['update'] is None:partial.update(endpoints)
            if a['update'] is not None:count+=1
    guards={e for g in inp.guards for e in (g['own'],g['peer'])}
    def tags(lit):
        kind,a,b=reg.by_id[abs(lit)];s=stages.get(b,0);result=[]
        if 0<s<=case['rounds']//2:result.append('retired_early')
        if b in guards:result.append('branch_guard')
        if kind=='co' and inp.inst.event[a].thread!=inp.inst.event[b].thread:result.append('cross_thread_CO')
        if b in failed:result.append('failed_attempt')
        if b in tail:result.append('failed_tail')
        if b in partial:result.append('incomplete_call')
        if case['family']=='buffer' and s%(case['capacity']+1) in (0,1):result.append('modulus_wrap')
        if kind=='rf' and cert['domains'][b]:
            ss=[stages.get(w,0) for w in cert['domains'][b]]
            if stages.get(a,0) in (min(ss)-1,min(ss),max(ss),max(ss)+1):result.append('window_edge')
        return result or ['ordinary']
    def sample(values,limit=24):
        values=sorted(values,key=lambda q:digest([label(case),q['kind'],q['alpha'],q['literal']]))
        chosen=[]
        for tag in ('incomplete_call','failed_tail','failed_attempt','window_edge','modulus_wrap','branch_guard','cross_thread_CO','retired_early','ordinary'):
            subset=[q for q in values if tag in q['tags']]
            for q in subset[:3]:
                if q not in chosen:chosen.append(q)
        for q in values:
            if len(chosen)>=limit:break
            if q not in chosen:chosen.append(q)
        return chosen[:limit]
    pools={'deleted_RF':[],'fixed_CO_opposite':[],'conditional':[]}
    for v,(kind,a,b) in reg.by_id.items():
        if kind=='rf' and a not in cert['domains'][b]:
            pools['deleted_RF'].append(dict(kind='deleted_RF',alpha=[],literal=v,tags=tags(v)))
        elif kind=='co':
            direction=v if (a,b) in cert['L'] else -v if (b,a) in cert['L'] else None
            if direction is not None and a not in inp.inst.initial and b not in inp.inst.initial:
                pools['fixed_CO_opposite'].append(dict(kind='fixed_CO_opposite',alpha=[],literal=-direction,tags=tags(v)))
    with SupportSAT(inp,cert) as filtered:
        ok,root=filtered.all_support();assert ok
        candidates=sorted((l for v in reg.by_id if v in root and -v in root for l in (v,-v)),key=lambda l:digest([label(case),l]))
        for literal in candidates[:48]:
            ok,supported=filtered.all_support([literal]);assert ok
            for absent in sorted(root-supported):
                if field(reg,absent)==field(reg,literal):continue
                pools['conditional'].append(dict(kind='conditional',alpha=[literal],literal=absent,tags=tags(absent)))
            if len(pools['conditional'])>=160:break
    queries=[q for values in pools.values() for q in sample(values)]
    for q in queries:q['decoded']=[list(reg.by_id[abs(l)])+[l>0] for l in q['alpha']+[q['literal']]]
    result=dict(case=case,input_sha256=digest(inp),queries=queries,pool_sizes={k:len(v) for k,v in pools.items()},
        selection_rule='SHA256 order; up to 3 per named boundary tag, then fill to 24 per exclusion kind; no raw solver outcome used to select',
        contract='Raw worker receives only case/events/guards and queries, no certificate facts',
        selected_counts={k:sum(q['kind']==k for q in queries) for k in pools})
    save(OUT/'negative_inputs'/f'{label(case)}.json',result);return result


def raw_worker(job,row,out):
    # No call to build_protocol, no certificate/domain/CO/HB facts are supplied here.
    from wmcheck.ra_support_sat import SupportSAT
    from wmcheck.ra_reference import evaluate_assignment
    inp=instance(job['case'])
    spec=json.loads((OUT/'negative_inputs'/f"{label(job['case'])}.json").read_text(encoding='utf8'))
    assert digest(inp)==spec['input_sha256']
    row.update(input_sha256=digest(inp),phase='raw_encoding',certificate_supplied=False);save(out,row)
    start=time.perf_counter();raw=SupportSAT(inp,certificate=None)
    row.update(encoding_seconds=time.perf_counter()-start,solver_stats=raw.stats,phase='raw_queries');save(out,row)
    assert not raw.stats['certificate_supplied']
    witnesses={};controls=[];disagreements=[]
    def positive(alpha):
        ok=raw.solve(alpha)
        if not ok:raise AssertionError('Selected positive control is raw UNSAT: '+repr(alpha))
        witness=raw.model_original();assert set(alpha)<=witness and evaluate_assignment(inp,witness)
        ident=digest(sorted(witness));witnesses[ident]=sorted(witness)
        controls.append(dict(alpha=alpha,raw_sat=True,dense_RA_valid=True,witness_sha256=ident))
    try:
        positive([])
        for j,q in enumerate(spec['queries']):
            alpha=q['alpha']+[q['literal']];tick=time.perf_counter();sat=raw.solve(alpha)
            record=dict(q,raw_result='SAT' if sat else 'UNSAT',seconds=time.perf_counter()-tick)
            if sat:
                witness=raw.model_original();record.update(counterexample=sorted(witness),dense_RA_valid=evaluate_assignment(inp,witness));disagreements.append(j)
            row['queries'].append(record)
            if q['kind']=='conditional':
                positive(q['alpha']);positive([q['literal']])
                # The second positive query withdraws alpha: the target regains support.
            row.update(disagreements=disagreements,positive_controls=controls,witnesses=witnesses)
            save(out,row)
        row.update(independent_negative_checks=sum(q['raw_result']=='UNSAT' for q in row['queries']),
            checked_counts={kind:sum(q['kind']==kind for q in row['queries']) for kind in spec['selected_counts']},
            total_seconds=row['encoding_seconds']+sum(q['seconds'] for q in row['queries']))
        assert not disagreements,disagreements
    finally:raw.close()


if __name__=='__main__':
    for case in CASES:
        result=select(case);print(label(case),result['selected_counts'],flush=True)
