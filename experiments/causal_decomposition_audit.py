"""Exhaustive original projection and syntactic-factorization diagnosis."""
import itertools
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest
from experiments.causal_followup_inputs import OUT
from experiments.causal_semantic_audit import projected_models
from wmcheck.ra_protocols import barrier_instance,buffer_instance,build_protocol
from wmcheck.ra_component_sat import ComponentSAT
from wmcheck.ra_support_sat import SupportSAT
from wmcheck.ra_reference import evaluate_assignment
from wmcheck.ra_frontier import prepare_frontier,compile_frontier
from wmcheck.ra import RARegistry
from pysat.solvers import Solver


def raw_models(inp,limit=10000):
    models=set()
    with SupportSAT(inp) as solver:
        while solver.solve():
            model=solver.model_original()
            assert evaluate_assignment(inp,model)
            models.add(model)
            if len(models)>limit:raise RuntimeError('Audit model budget')
            solver.solver.add_clause([-lit for lit in model])
    return models


def factors(engine):
    answer=[]
    for part in engine.partition['components']:
        if not part['originals']:continue
        models=set()
        with Solver(name='cadical195',bootstrap_with=part['clauses']) as local:
            while local.solve():
                model=frozenset(l for l in local.get_model() if abs(l) in part['originals'])
                assert len(model)==len(part['originals'])
                models.add(model);local.add_clause([-l for l in model])
        answer.append(models)
    return answer


def main():
    results=[]
    for n in (1,2,3,8,16):
        inp=barrier_instance(n);pre=build_protocol(inp)
        with ComponentSAT(inp,pre['certificate']) as comp:
            local=factors(comp)
            stages=[sorted({pre['stages'][comp.registry.by_id[v][2]] for v in p['originals']})
                    for p in comp.partition['components'] if p['originals']]
            row=dict(rounds=n,component_stats=comp.stats,component_stages=stages,
                     factor_model_counts=[len(x) for x in local],fixed_originals=len(comp.constants),
                     factor_sizes=[len(p['originals']) for p in comp.partition['components'] if p['originals']])
            if n<=3:
                models=raw_models(inp)
                product={frozenset(comp.constants).union(*parts) for parts in itertools.product(*local)}
                assert product==models
                plan=prepare_frontier(inp.inst,certificate=pre['certificate'],order=pre['order'],co_mode='direct',summary_mode='ports')
                graph=compile_frontier(inp.inst,prepared=plan)
                assert projected_models(graph)==models
                row.update(exhaustive_raw_models=len(models),complete_product_equality=True,
                           graph_projection_equal=True,every_model_checked_by_dense_RA=True,
                           complete_model_set_sha256=digest(sorted(sorted(m) for m in models)))
            results.append(row);save(OUT/'decomposition.json',dict(status='RUNNING',barrier=results))
            print('decomposition',n,row.get('exhaustive_raw_models'),row['factor_model_counts'],flush=True)
    inp=buffer_instance(8,capacity=3,mode='branch');pre=build_protocol(inp);reg=RARegistry(inp.inst)
    pool=json.loads((OUT/'workloads/buffer_8_pool.json').read_text())
    chosen=None;witnesses=[]
    with SupportSAT(inp) as raw:
        for pair in pool['unsat']:
            reads=[reg.by_id[abs(lit)][2] for lit in pair]
            if len({pre['stages'][r] for r in reads})<2:continue
            assert not raw.solve(pair)
            for lit in pair:
                assert raw.solve([lit]);m=raw.model_original();assert evaluate_assignment(inp,m);witnesses.append(sorted(m))
            chosen=pair;break
    assert chosen is not None
    with ComponentSAT(inp,pre['certificate']) as comp:
        buffer=dict(component_stats=comp.stats,correlated_literals=chosen,
            decoded=[list(reg.by_id[abs(lit)])+[lit>0] for lit in chosen],
            stages=[pre['stages'][reg.by_id[abs(lit)][2]] for lit in chosen],
            each_literal_raw_sat=True,joint_raw_unsat=True,raw_checked_witnesses=witnesses,
            connected_CNF_alone_not_claimed_semantic_indecomposability=True)
    save(OUT/'decomposition.json',dict(status='OK',barrier=results,buffer=buffer,
        interpretation='CNF unit propagation and incidence components, no guessed round independence or model-count oracle; finite audited configurations'))


if __name__=='__main__':main()
