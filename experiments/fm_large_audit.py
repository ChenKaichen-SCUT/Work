"""Selected 32-round queries: graph vs independent incidence/CaDiCaL oracle.

This is correctness evidence, not a timing comparison with the frozen dense
Minisat benchmark. Every SAT result is decoded and checked by dense RA semantics.
"""
import argparse,hashlib,json,os,platform,resource,sys,time,traceback
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import RARegistry
from wmcheck.ra_publication import publication_exchange,publication_layout
from wmcheck.ra_incidence_sat import IncidenceSAT
from wmcheck.ra_frontier import compile_frontier
from wmcheck.dag_reduce import reduce_dag
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.trace_diagnosis import publication_logs
from experiments.publication_semantics import decode


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--frozen',required=True)
    a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True);frozen=Path(a.frozen)
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))});resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,)*2)
    os.environ['WMCHECK_NATIVE_PORTS']='1';n=32;inst=publication_exchange(n,payload='epoch');reg=RARegistry(inst)
    assert json.loads(json.dumps(asdict(inst)))==json.loads((frozen/'inputs/epoch_32.json').read_text())
    original=json.loads((frozen/'runs/epoch_32_ports-atomic_s1000000_0.json').read_text())
    old={tuple(q['assumptions']):q['answer_sha256'] for q in original['queries']}
    result=dict(status='running',n=n,events=len(inst.events),original_variables=reg.nvars,
        memory_gib=8,platform=platform.platform(),python=sys.version,queries=[],witnesses={},
        independent_contract='selected consistency and literal supports only; not all 32-round supports',
        frozen_input_sha256=hashlib.sha256((frozen/'inputs/epoch_32.json').read_bytes()).hexdigest(),
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'wmcheck/ra_incidence_sat.py',ROOT/'wmcheck/ra_oracle.py',ROOT/'wmcheck/ra_frontier.py')})
    save(out/'large32.json',result)
    try:
        c=compile_frontier(inst,order=publication_layout(inst,n),co_mode='direct',summary_mode='ports',
            rf_mode='atomic',source_covers=True,early_degrees=True,max_states=1000000,max_edges=3000000,max_seconds=120)
        c=reduce_dag(c);engine=OwnedGraphSolver(c);result['graph_stats']=c.stats
        print('32-round graph rebuilt',c.stats['raw_states'],flush=True)
        selected=[dict(name='root',observations=[],stage=2,thread=1)]
        for stage in (2,8,16,24,32):
            for log in publication_logs(inst,n):
                if not log['name'].startswith(f's{stage}_'):continue
                selected.append(dict(log,stage=stage,thread=int(log['name'].split('_')[1][1:])))
            for t in (0,1):
                loc='x' if t==0 else 'y';own=reg.literal(('rf',f't{t}_{stage}_{loc}',f't{t}_{stage}_read'))
                selected.append(dict(name=f's{stage}_t{t}_withdraw',observations=[own],stage=stage,thread=t))
        # Direct negative RF assumptions and a false original constant are also audited.
        init_rf=reg.literal(('rf','ifb','t0_1_wait'))
        last_early=reg.literal(('rf','t0_31_pub0','t1_32_wait'))
        selected += [dict(name='negative_source',observations=[-last_early],stage=32,thread=1),
                     dict(name='negated_initial_source',observations=[-init_rf],stage=32,thread=1)]
        with IncidenceSAT(inst) as sat:
            result['oracle_stats']=sat.stats;print('Independent oracle built',sat.stats,flush=True)
            calls=0;start=time.perf_counter()
            for entry in selected:
                alpha=entry['observations'];i=entry['stage'];t=entry['thread'];peer=1-t;loc='x' if t==0 else 'y'
                ok,forced=engine.propagate(alpha);answer_hash=digest([ok,sorted(forced) if ok else []])
                prior=old.get(tuple(alpha))
                if prior is not None:assert prior==answer_hash
                observed=sat.solve(alpha);calls+=1;assert observed==ok,(entry['name'],'consistency')
                row=dict(entry,consistent=ok,full_graph_answer_sha256=answer_hash,
                    matches_frozen_answer=prior is not None,checks=[])
                targets=[reg.literal(('co',f't{peer}_{i-1}_{loc}',f't{t}_{i}_{loc}')),
                    reg.literal(('rf',f't{t}_{i}_{loc}',f't{t}_{i}_read')),
                    reg.literal(('rf',f't{peer}_{i}_{loc}',f't{t}_{i}_read')),
                    reg.literal(('rf',f't{peer}_{i-1}_pub0',f't{t}_{i}_wait')),
                    reg.literal(('rf',f't{peer}_{i-1}_pub1',f't{t}_{i}_wait')),
                    reg.literal(('rf',f't{peer}_1_pub0',f't{t}_{i}_wait')),
                    init_rf,reg.literal(('co','i'+loc,f't{t}_{i}_{loc}'))]
                for value in sorted({abs(v) for v in targets if type(v) is int}):
                    for lit in (value,-value):
                        actual=sat.solve(alpha+[lit]);calls+=1;expected=ok and -lit not in forced
                        assert actual==expected,(entry['name'],lit,expected,actual)
                        check=dict(literal=lit,supported=actual)
                        if actual:
                            model=[v for v in sat.model() if abs(v)<=reg.nvars]
                            key=digest(sorted(model));check['witness']=key
                            if key not in result['witnesses']:
                                witness=decode(inst,reg,model)
                                assert set(alpha+[lit])<=set(model)
                                result['witnesses'][key]=witness
                        row['checks'].append(check)
                result['queries'].append(row);save(out/'large32.json',result)
                print(entry['name'],ok,len(row['checks']),flush=True)
            result.update(status='ok',sat_calls=calls,checking_seconds=time.perf_counter()-start,
                every_sat_support_has_independently_checked_complete_witness=True,
                matched_frozen_queries=sum(q['matches_frozen_answer'] for q in result['queries']))
    except Exception:
        result.update(status='ERROR',traceback=traceback.format_exc());raise
    finally:
        result['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;save(out/'large32.json',result)


if __name__=='__main__':main()
