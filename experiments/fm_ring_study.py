"""New topology evidence, explicitly separate from the frozen timing campaign."""
import argparse,hashlib,json,os,resource,subprocess,sys,time,traceback
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import RARegistry
from wmcheck.ra_ring import publication_ring,ring_layout,ring_witness,ring_queries
from wmcheck.ra_program import export_c,export_litmus
from wmcheck.ra_frontier import compile_frontier
from wmcheck.compiler import ResourceLimit
from wmcheck.dag_reduce import reduce_dag
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.ra_incidence_sat import IncidenceSAT
from wmcheck.complete_query import forced_by_search
from wmcheck.propagation import unit_propagate
from wmcheck.ra_oracle import valid
from experiments.publication_semantics import decode
from experiments.fm_structure_audit import inspect
from experiments.support_task_semantics import sc_reachable


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')


def worker(args):
    out=Path(args.out);p,n,irregular,covers=map(int,args.worker)
    name=f'ring_p{p}_n{n}_i{irregular}_cover{covers}';record=out/'ring'/f'{name}.json'
    if record.exists():raise FileExistsError(record)
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))});resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
    os.environ['WMCHECK_NATIVE_PORTS']='1';inst=publication_ring(n,p,irregular=bool(irregular));reg=RARegistry(inst)
    base=out/'ring_inputs'/name;save(str(base)+'.json',asdict(inst))
    Path(str(base)+'.c').write_text(export_c(inst));Path(str(base)+'.litmus').write_text(export_litmus(inst,name=name))
    result=dict(name=name,status='running',workers=p,rounds=n,irregular=bool(irregular),source_covers=bool(covers),
        events=len(inst.events),original_variables=reg.nvars,queries=[],budget_states=1000000,
        compile_seconds_limit=90,memory_gib=4,wall_seconds_limit=240,
        measurement_role='single-run topology correctness experiment; not a repeated performance comparison')
    save(record,result);start=time.perf_counter()
    try:
        result['structure']=inspect(inst,n,{t:f'f{t}' for t in range(p)},{(t,(t+1)%p) for t in range(p)})
        for late in (False,True):assert valid(inst,*ring_witness(inst,n,p,late))
        result['early_late_witnesses_dense_ra_valid']=True
        if p==3 and n==2 and not irregular:
            answer,clauses=sc_reachable(inst);assert not answer;result['sc_observation_unreachable']=True
        t=time.perf_counter()
        c=compile_frontier(inst,order=ring_layout(inst),co_mode='direct',summary_mode='ports',source_covers=bool(covers),
            rf_mode='atomic',early_degrees=True,max_states=1000000,max_edges=3000000,max_seconds=90)
        up=(p==3 and n==2 and not irregular and bool(covers));c=reduce_dag(c,cnf=up)
        result['graph_seconds']=time.perf_counter()-t;result['stats']=c.stats;engine=OwnedGraphSolver(c)
        with IncidenceSAT(inst) as sat:
            result['oracle_stats']=sat.stats;known=set();calls=0
            for query in ring_queries(reg,n,p):
                alpha=query['assumptions'];expected=engine.propagate(alpha)
                actual=forced_by_search(sat.solver,reg.by_id,alpha,known);calls+=actual[2]
                assert actual[:2]==expected,(name,query['name'])
                if not alpha and actual[0]:known=actual[1]
                row=dict(query,consistent=actual[0],forced=sorted(actual[1]),all_original_supports_equal=True)
                if up:
                    u=unit_propagate(c.clauses,alpha);assert u.consistent==actual[0]
                    if u.consistent:assert {v if b else -v for v,b in u.values.items() if v in reg.by_id}==actual[1]
                    row['pure_up_equal']=True
                if actual[0]:
                    assert sat.solve(alpha);row['witness']=decode(inst,reg,sat.model())
                result['queries'].append(row);save(record,result)
            result.update(status='ok',sat_calls=calls)
    except ResourceLimit as e:result.update(status='UNKNOWN',reason=str(e),failure_stats=getattr(e,'stats',{}))
    except MemoryError as e:
        e.__traceback__=None;e.__context__=None;result.update(status='UNKNOWN',reason='memory_4GiB')
    except Exception:result.update(status='ERROR',traceback=traceback.format_exc())
    result.update(elapsed_seconds=time.perf_counter()-start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(record,result);print(name,result['status'],result.get('stats',{}).get('raw_states'),len(result['queries']),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--worker',nargs=4)
    args=p.parse_args()
    if args.worker:return worker(args)
    out=Path(args.out);rows=[]
    for cfg in ((3,2,0,1),(3,3,0,1),(3,4,0,1),(3,3,0,0),(3,2,1,1),(4,2,0,1)):
        cmd=[sys.executable,__file__,'--out',str(out),'--worker',*map(str,cfg)]
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        path=out/'ring'/f'ring_p{cfg[0]}_n{cfg[1]}_i{cfg[2]}_cover{cfg[3]}.json'
        try:
            stdout,stderr=proc.communicate(timeout=240)
            if proc.returncode:
                row=json.loads(path.read_text()) if path.exists() else {}
                save(path,dict(row,status='ERROR',stderr=stderr,returncode=proc.returncode))
        except subprocess.TimeoutExpired:
            proc.kill();stdout,stderr=proc.communicate();row=json.loads(path.read_text())
            save(path,dict(row,status='UNKNOWN',reason='wall_timeout_240s',stderr=stderr))
        print(stdout,flush=True,end='');row=json.loads(path.read_text());rows.append(row)
    save(out/'ring_summary.json',[{k:v for k,v in r.items() if k!='queries'}|{'query_count':len(r.get('queries',[]))} for r in rows])


if __name__=='__main__':main()
