"""Untimed independent checks of the new client, versioned family and adapter."""
import argparse,hashlib,json,subprocess,sys
from itertools import product,combinations,permutations
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import RARegistry,recognize
from wmcheck.ra_publication import publication_exchange,publication_layout,staged_witness
from wmcheck.ra_frontier import compile_frontier
from wmcheck.ra_oracle import valid,reach
from wmcheck.ra_sat import encode_ra
from wmcheck.complete_query import forced_by_search
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.dag_reduce import reduce_dag
from wmcheck.propagation import unit_propagate
from wmcheck.trace_diagnosis import diagnose,publication_logs
from experiments.publication_semantics import decode
from experiments.publication_study import diagnostic_queries,save
from pysat.solvers import Minisat22


def sc_reachable(inst):
    """Independent total-order encoding, with no RA recognizer or CO kernel."""
    nodes=tuple(inst.event);index={e:i for i,e in enumerate(nodes)}
    order={pair:j for j,pair in enumerate(combinations(nodes,2),1)};nv=len(order);clauses=[]
    def lt(a,b):return order[a,b] if index[a]<index[b] else -order[b,a]
    for a,b,c in permutations(nodes,3):clauses.append([-lt(a,b),-lt(b,c),lt(a,c)])
    for a,b in inst.sb:clauses.append([lt(a,b)])
    for a in inst.initial:
        for b in nodes:
            if b not in inst.initial:clauses.append([lt(a,b)])
    for r,ws in inst.candidates.items():
        sources=[]
        for w in ws:
            nv+=1;v=nv;sources.append(v);clauses.append([-v,lt(w,r)])
            for x in inst.writes:
                if x!=w and inst.event[x].loc==inst.event[r].loc:
                    clauses.append([-v,lt(x,w),lt(r,x)])
        clauses.append(sources)
        clauses.extend([-a,-b] for a,b in combinations(sources,2))
    with Minisat22(bootstrap_with=clauses) as sat:return sat.solve(),len(clauses)


def semantic(out):
    result=dict(named=[],repairs=[],family=[],sc_outcomes=[],source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),ROOT/'wmcheck/trace_diagnosis.py',ROOT/'wmcheck/dag_reduce.py',ROOT/'wmcheck/ra_publication.py')})
    for payload,n in product(('constant','epoch'),range(1,5)):
        reachable,clauses=sc_reachable(publication_exchange(n,payload=payload));assert not reachable
        result['sc_outcomes'].append(dict(payload=payload,n=n,reachable=False,clauses=clauses,
            contract='all SC total event orders, fixed observed values, no fixed RF/CO'))
    for payload in ('constant','epoch'):
        n=2;inst=publication_exchange(n,payload=payload);reg=RARegistry(inst);enc=encode_ra(inst)
        c=compile_frontier(inst,order=publication_layout(inst,n),co_mode='direct',summary_mode='ports',
            rf_mode='atomic',source_covers=True,early_degrees=True)
        reduced=reduce_dag(c,cnf=True);engine=OwnedGraphSolver(reduced)
        with Minisat22(bootstrap_with=enc.clauses) as sat:
            for entry in diagnostic_queries(reg,n):
                alpha=entry['assumptions'];expected=forced_by_search(sat,reg.by_id,alpha)[:2]
                assert engine.propagate(alpha)==OwnedGraphSolver(c).propagate(alpha)==expected
                up=unit_propagate(reduced.clauses,alpha);assert up.consistent==expected[0]
                if up.consistent:assert {v if b else -v for v,b in up.values.items() if v in reg.by_id}==expected[1]
                row=dict(payload=payload,**entry,consistent=expected[0],forced=sorted(expected[1]),graph_sat_reduced_up_agree=True)
                if expected[0]:
                    assert sat.solve(assumptions=alpha);row['witness']=decode(inst,reg,sat.get_model())
                result['named'].append(row)
            for log in publication_logs(inst,n):
                obs=log['observations'];answer=diagnose(reg,engine.propagate,obs)
                if answer['snapshot']['consistent']:continue
                actual={(r['remove'],v) for r in answer['repairs'] for v in r['replacements']};expected=set()
                for lit in obs:
                    kind,a,b=reg.by_id[abs(lit)]
                    candidates=[reg.literal(('rf',w,b)) for w in inst.candidates[b]] if kind=='rf' else [-lit]
                    for value in candidates:
                        if value==lit:continue
                        remaining=[v for v in obs if v!=lit]+[value]
                        if sat.solve(assumptions=remaining):
                            expected.add((lit,value));decode(inst,reg,sat.get_model())
                assert actual==expected
                core=answer['conflict'];assert not sat.solve(assumptions=core)
                assert all(sat.solve(assumptions=[x for x in core if x!=lit]) for lit in core)
                result['repairs'].append(dict(payload=payload,log=log,answer=answer,
                    independently_enumerated_single_field_repairs=sorted(expected),every_repair_dense_ra_valid=True))
    for n,m in ((1,2),(2,2),(3,2),(2,3)):
        inst=publication_exchange(n,m,payload='epoch');count=0
        for directions in product((0,1),repeat=2*n):
            for pubs in product(range(m),repeat=2*(n-1)):
                rf,orders=staged_witness(inst,n,m)
                for k,loc in enumerate(('x','y')):
                    orders[loc]=('i'+loc,)+tuple(f't{t}_{i}_{loc}' for i in range(1,n+1)
                        for t in ((0,1) if directions[k*n+i-1] else (1,0)))
                for t in range(2):
                    for i in range(2,n+1):rf[f't{t}_{i}_wait']=f't{1-t}_{i-1}_pub{pubs[t*(n-1)+i-2]}'
                assert valid(inst,rf,orders);count+=1
        assert count==4**n*m**(2*(n-1))
        result['family'].append(dict(n=n,copies=m,independent_distinct_witnesses=count))
    for n in (4,8,16,32,64):
        inst=publication_exchange(n,payload='epoch');cert=recognize(inst,source_covers=True)
        for last in (False,True):
            rf,orders=staged_witness(inst,n,last_publication=last);assert valid(inst,rf,orders)
            co={(a,b) for ws in orders.values() for j,a in enumerate(ws) for b in ws[j+1:]}
            assert ('t1_1_x','t0_1_x') in co and ('t0_1_y','t1_1_y') in co
        result['family'].append(dict(n=n,staged_early_late_dense_ra_valid=True,explicit_sb_co_cycle=True,
            unresolved_co=sum((a,b) not in cert['L'] and (b,a) not in cert['L'] for kind,a,b in RARegistry(inst).by_id.values() if kind=='co'),
            ambiguous_waits=sum(len(cert['domains'][r])>1 for r in inst.reads if r.endswith('wait'))))
    save(out/'semantic_audit.json',result)


def native_audit(out,folder):
    rows=[]
    for n in (1,2,3,4,8,16):
        inst=publication_exchange(n);cert=recognize(inst,source_covers=True)
        files=sorted((folder/f'n{n}').glob('k0-plus-cover-closure_*.output.tsv'))
        final=files[-1];facts={tuple(row.split('\t')) for row in final.read_text().splitlines()}
        h={(a,b) for rel,bound,a,b in facts if (rel,bound)==('hb','must')}
        l={(a,b) for rel,bound,a,b in facts if (rel,bound)==('co','must')}
        rf={(a,b) for rel,bound,a,b in facts if (rel,bound)==('rf','may')}
        assert h==cert['H'] and l==cert['L'] and rf=={(a,b) for b,ws in cert['domains'].items() for a in ws}
        rows.append(dict(n=n,full_h_l_rf_sets_equal=True,file=str(final),sha256=hashlib.sha256(final.read_bytes()).hexdigest()))
    save(out/'native_full_set_audit.json',rows)


def genmc(out,executable):
    from experiments.paper_external import genmc_reachable
    rows=[]
    for n,model in ((2,'rc11'),(4,'rc11'),(2,'sc')):
        source=out/'inputs'/f'epoch_{n}.c'
        command=[executable,'--'+model,'--disable-estimation','--',str(source)]
        try:proc=subprocess.run(command,capture_output=True,text=True,timeout=60)
        except subprocess.TimeoutExpired:
            rows.append(dict(n=n,model=model,status='UNKNOWN',reason='timeout_60s'));continue
        log=proc.stdout+proc.stderr;answer=genmc_reachable(log,source);assert answer is (model=='rc11')
        (out/f'genmc_{model}_epoch_{n}.txt').write_text(log)
        rows.append(dict(n=n,model=model,status='ok',command=command,returncode=proc.returncode,outcome_reachable=answer,
            contract='observable fixed values only; not a full-support comparison',sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    save(out/'genmc_outcomes.json',rows)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--native-audit')
    p.add_argument('--genmc');a=p.parse_args();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
    semantic(out)
    if a.native_audit:native_audit(out,Path(a.native_audit))
    if a.genmc:genmc(out,a.genmc)
