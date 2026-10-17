"""Focused publication experiment: shared original-support queries, isolated runs."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wmcheck.ra import RARegistry, recognize
from wmcheck.ra_publication import publication_exchange, publication_layout, staged_witness


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf8')


def digest(value):
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def profile(inst, cert, order):
    """Independent candidate incidence diagnostic; no summary-state generation."""
    from wmcheck.port_monitor import plan_ports, ra_port_monitors
    domains, required, mandatory = (cert[k] for k in ('domains', 'L', 'mandatory'))
    groups = []
    def fixed(symbol, a, b):
        arcs=((symbol,a,b),)+((('R',b,a),) if symbol=='r' else ())
        groups.append(((a,b),[((),arcs,())]))
    for a,b in sorted(inst.sb): fixed('s',a,b)
    for i in inst.initial:
        for thread in inst.threads:
            if thread: fixed('s',i,thread[0])
    reg=RARegistry(inst); unresolved=0
    for _,(kind,a,b) in reg.by_id.items():
        if kind=='rf' and a in domains[b]:
            if (a,b) in mandatory: fixed('r',a,b)
            else: groups.append(((a,b),[((),(),()),((),(('r',a,b),('R',b,a)),())]))
        elif kind=='co' and (a,b) not in required and (b,a) not in required:
            unresolved+=1
            groups.append(((a,b),[((),(('c',a,b),),()),((),(('c',b,a),),())]))
    for a,b in sorted(required):
        if not any((a,z) in required and (z,b) in required for z in inst.writes): fixed('c',a,b)
    groups += [((e,),[((),(),())]) for e in inst.event]
    rank={v:j for j,v in enumerate(order)}
    groups.sort(key=lambda g:(max(rank[v] for v in g[0]),min(rank[v] for v in g[0])))
    last={v:j for j,(vs,_) in enumerate(groups) for v in vs}
    active=set();width=0
    for j,(vs,_) in enumerate(groups):
        active.update(vs);width=max(width,len(active));active={v for v in active if last[v]>j}
    plans=plan_ports(ra_port_monitors(),groups)
    rho=max(sum((1 if p[j].acyclic else 2)*len(p[j].after_inputs)*len(p[j].after_outputs)
                for p in plans) for j in range(len(groups)))
    return dict(width=width,rho=rho,groups=len(groups),rf_candidates=sum(map(len,domains.values())),
                unresolved_co=unresolved,source_cover_edges=len(cert.get('source_cover_edges',())))


def diagnostic_queries(reg, n):
    if n<2: return [dict(name='root', assumptions=[])]
    read=reg.literal(('rf','t1_2_y','t1_2_read'))
    first=reg.literal(('rf','t0_1_pub0','t1_2_wait'))
    last=reg.literal(('rf','t0_1_pub1','t1_2_wait'))
    co=reg.literal(('co','t0_1_y','t1_2_y'))
    return [dict(name=name,assumptions=alpha) for name,alpha in (
        ('root',[]),('first_publication',[read,first]),('second_publication',[read,last]),
        ('first_with_inverted_co',[read,first,-co]),('second_with_inverted_co',[read,last,-co]),
        ('withdraw_source',[read]),('withdraw_all',[]))]


def prepare(out):
    from pysat.solvers import Minisat22
    from wmcheck.ra_sat import encode_ra
    from wmcheck.complete_query import forced_by_search
    from wmcheck.ra_program import export_c, export_litmus
    from wmcheck.ra_oracle import valid
    rows=[]
    for n in (1,2,3,4,6,10,16,24):
        inst=publication_exchange(n);order=publication_layout(inst,n)
        for covers in (False,True):
            start=time.perf_counter();cert=recognize(inst,source_covers=covers)
            elapsed=time.perf_counter()-start
            row=dict(rounds=n,source_covers=covers,recognition_seconds=elapsed,**profile(inst,cert,order))
            rows.append(row)
        if n>3: continue
        reg=RARegistry(inst);enc=encode_ra(inst);rng=random.Random(160026+n)
        named=diagnostic_queries(reg,n);queries=[r['assumptions'] for r in named]
        with Minisat22(bootstrap_with=enc.clauses) as sat:
            ok,root,_=forced_by_search(sat,reg.by_id)
            assert ok
            free=[v for v in reg.by_id if v not in root and -v not in root]
            while len(queries)<512:
                sat.set_phases([v*rng.choice((-1,1)) for v in free]);assert sat.solve()
                model={abs(l):l for l in sat.get_model() if abs(l) in reg.by_id}
                selected=rng.sample(free,min(len(free),1+(len(queries)%max(1,len(free)))))
                # Analyst-like nested assumptions, withdrawal and alternative
                # branches; scripted workload, not an external solver trace.
                prefix=[]
                for v in selected[:8]:
                    prefix=prefix+[model[v]];queries.append(prefix)
                    if len(queries)==512:break
                if len(queries)<512 and prefix:queries.append(prefix[:-1]+[-prefix[-1]])
                if len(queries)<512:queries.append([])
            queries=queries[:512]
            answers=[]
            for r in named:
                ok,f,_=forced_by_search(sat,reg.by_id,r['assumptions'])
                answers.append(dict(r,consistent=ok,forced=sorted(f)))
        rf,orders=staged_witness(inst,n);assert valid(inst,rf,orders)
        save(out/'inputs'/f'n{n}.json',asdict(inst))
        save(out/'inputs'/f'n{n}_registry.json',reg.by_id)
        save(out/'inputs'/f'n{n}_queries.json',queries)
        save(out/'inputs'/f'n{n}_diagnostics.json',answers)
        save(out/'inputs'/f'n{n}_witness.json',dict(rf=rf,orders=orders,independent_ra_valid=True,
            non_sc_cycle=['t0_1_x','t0_1_y','t1_1_y','t1_1_x','t0_1_x']))
        (out/'inputs'/f'n{n}.c').write_text(export_c(inst),encoding='utf8')
        (out/'inputs'/f'n{n}.litmus').write_text(export_litmus(inst,name=f'publication_{n}'),encoding='utf8')
    save(out/'structure.json',rows)


def worker(out, n, method, record, cpu):
    import resource
    from wmcheck.compiler import ResourceLimit
    resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    os.sched_setaffinity(0,{cpu})
    inst=publication_exchange(n)
    queries=json.loads((out/'inputs'/f'n{n}_queries.json').read_text())
    result=dict(rounds=n,method=method,status='running',query_sha256=digest(queries),
                query_times=[],answer_hashes=[],forced_counts=[],verdicts=[])
    save(record,result);begin=time.perf_counter()
    try:
        if method in ('ports','ports-cover','full-cover'):
            from wmcheck.ra_frontier import compile_frontier
            from wmcheck.owned_dag import OwnedGraphSolver
            c=compile_frontier(inst,order=publication_layout(inst,n),co_mode='direct',
                summary_mode='full' if method=='full-cover' else 'ports',source_covers=method!='ports',
                early_degrees=True,max_states=200000,max_edges=600000,max_seconds=90)
            result['stats']=c.stats;t=time.perf_counter();engine=OwnedGraphSolver(c)
            result['setup_seconds']=time.perf_counter()-t;query=engine.propagate
        elif method.startswith('sat'):
            from pysat.solvers import Minisat22
            from wmcheck.ra_sat import encode_ra
            from wmcheck.query_sat_up import forced_with_up
            enc=encode_ra(inst);result['stats']=enc.stats;t=time.perf_counter()
            solver=Minisat22(bootstrap_with=enc.clauses);result['setup_seconds']=time.perf_counter()-t
            known={r[0] for r in enc.clauses if len(r)==1 and abs(r[0])<=enc.registry.nvars}
            def query(alpha):
                nonlocal known
                ok,f,_=forced_with_up(solver,enc.registry.by_id,alpha,known,flip_phases=method=='sat-phase')
                if not alpha and ok:known=f
                return ok,f
        else:
            from wmcheck.ra_bdd_relational import RelationalBDD
            engine=RelationalBDD(inst,coherence_first=method=='bdd-coherence',semantic_order=True)
            result['stats']=engine.stats;result['setup_seconds']=0;query=engine.propagate
        for j,alpha in enumerate(queries):
            t=time.perf_counter();ok,f=query(alpha)
            result['query_times'].append(time.perf_counter()-t)
            result['answer_hashes'].append(digest([ok,sorted(f) if ok else []]))
            result['forced_counts'].append(len(f));result['verdicts'].append(ok)
            if j%32==0:save(record,result)
        result['status']='ok'
    except (ResourceLimit,MemoryError) as exc:
        result.update(status='UNKNOWN',reason=str(exc) or 'memory_limit',failure_stats=getattr(exc,'stats',{}))
    except Exception as exc:
        result.update(status='ERROR',reason=str(exc),traceback=traceback.format_exc())
    result.update(elapsed_seconds=time.perf_counter()-begin,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(record,result)


def run(out, repeats):
    cpu=min(os.sched_getaffinity(0))
    save(out/'environment.json',dict(platform=platform.platform(),python=sys.version,cpu=cpu,
        repeats=repeats,serial=True,wall_seconds=120,compile_seconds=90,memory_gib=4,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('wmcheck','tests','experiments') for p in (ROOT/folder).glob('*.py')}))
    for n in (1,2,3):
        for method in ('ports','ports-cover','full-cover','sat-up','sat-phase','bdd','bdd-coherence'):
            for rep in range(repeats):
                record=out/'runs'/f'n{n}_{method}_{rep}.json'
                if record.exists():raise FileExistsError('Use a fresh output directory')
                command=[sys.executable,__file__,'--out',str(out),'--worker',str(n),method,
                         '--record',str(record),'--cpu',str(cpu)]
                proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    stdout,stderr=proc.communicate(timeout=120)
                    if proc.returncode:
                        row=json.loads(record.read_text()) if record.exists() else {}
                        save(record,dict(row,status='ERROR',returncode=proc.returncode,stdout=stdout,stderr=stderr))
                except subprocess.TimeoutExpired:
                    proc.kill();stdout,stderr=proc.communicate()
                    row=json.loads(record.read_text()) if record.exists() else {}
                    save(record,dict(row,status='UNKNOWN',reason='wall_timeout_120s',stdout=stdout,stderr=stderr))
                row=json.loads(record.read_text());print(n,method,rep,row['status'],flush=True)
                if row['status']!='ok':break


def analyze(out):
    allrows=[json.loads(p.read_text()) for p in sorted((out/'runs').glob('*.json'))]
    report=[]
    for n in (1,2,3):
        rows=[r for r in allrows if r.get('rounds')==n]
        completed=[r for r in rows if r['status']=='ok']
        reference=completed[0] if completed else None
        for r in completed:
            assert r['query_sha256']==reference['query_sha256'] and r['answer_hashes']==reference['answer_hashes']
        queries=json.loads((out/'inputs'/f'n{n}_queries.json').read_text())
        methods={}
        for method in sorted({r['method'] for r in rows}):
            records=[r for r in rows if r['method']==method]; good=[r for r in records if r['status']=='ok']
            m=dict(statuses=[r['status'] for r in records],successful_repeats=len(good))
            if good:
                m.update(compile_median=statistics.median(r['stats']['compile_seconds'] for r in good),
                    setup_median=statistics.median(r['setup_seconds'] for r in good),
                    total_median=statistics.median(r['stats']['compile_seconds']+r['setup_seconds']+sum(r['query_times']) for r in good),
                    query_median=statistics.median(sum(r['query_times']) for r in good),
                    peak_rss_kib_median=statistics.median(r['peak_rss_kib'] for r in good))
                for key in ('states','attempted_transitions','max_interface','max_port_coordinates','bdd_nodes'):
                    if key in good[0]['stats']:m[key]=good[0]['stats'][key]
                m['prefix_medians']=[statistics.median(r['stats']['compile_seconds']+r['setup_seconds']+sum(r['query_times'][:q]) for r in good) for q in range(1,len(queries)+1)]
            else:m['failures']=[dict(reason=r.get('reason'),stats=r.get('failure_stats')) for r in records]
            methods[method]=m
        comparisons={}
        target=methods.get('ports-cover',{})
        if target.get('successful_repeats')==5:
            for label,baselines in (('sat',('sat-up','sat-phase')),('bdd',('bdd','bdd-coherence'))):
                eligible=[methods[b]['prefix_medians'] for b in baselines if methods.get(b,{}).get('successful_repeats')==5]
                if eligible:
                    wins=[q+1 for q,x in enumerate(target['prefix_medians']) if x<min(b[q] for b in eligible)]
                    stable=next((q for q in wins if all(j in wins for j in range(q,513))),None)
                    comparisons[label]=dict(first_win=min(wins) if wins else None,stable_through_512=stable,winning_prefixes=len(wins),baseline='post-hoc best of completed strategies')
        report.append(dict(rounds=n,queries=len(queries),distinct_assumptions=len({tuple(sorted(set(q))) for q in queries}),
            exact_answer_agreement=True,compared_methods=len({r['method'] for r in completed}),
            sat_queries=sum(reference['verdicts']) if reference else None,methods=methods,amortization=comparisons))
    save(out/'analysis.json',report)
    print(json.dumps([dict(rounds=r['rounds'],distinct=r['distinct_assumptions'],methods={m:{k:v for k,v in x.items() if k!='prefix_medians'} for m,x in r['methods'].items()},amortization=r['amortization']) for r in report],indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--prepare',action='store_true')
    p.add_argument('--run',action='store_true');p.add_argument('--analyze',action='store_true');p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--worker',nargs=2);p.add_argument('--record');p.add_argument('--cpu',type=int,default=0);a=p.parse_args()
    out=Path(a.out).resolve()
    if a.worker:worker(out,int(a.worker[0]),a.worker[1],Path(a.record),a.cpu);return
    if a.prepare:prepare(out)
    if a.run:run(out,a.repeats)
    if a.analyze:analyze(out)


if __name__=='__main__':main()
