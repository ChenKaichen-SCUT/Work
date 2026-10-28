"""32-round selected witnesses checked against raw RA, not protocol certificates.

Positive-witness checks do not prove absent supports. Complete support hashes for
the saved B1 prefix are reported separately, with the shared-preprocessing caveat.
"""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest,workload
from wmcheck.ra_protocols import barrier_instance,build_protocol
from wmcheck.ra_frontier import prepare_frontier,compile_frontier
from wmcheck.ra_reference import evaluate_assignment
from wmcheck.ra import RARegistry
from wmcheck.owned_dag import OwnedGraphSolver


def main():
    folder=ROOT/'results/causal_20261028'
    inp=barrier_instance(32);reg=RARegistry(inp.inst);pre=build_protocol(inp)
    plan=prepare_frontier(inp.inst,certificate=pre['certificate'],order=pre['order'],co_mode='direct',summary_mode='ports',early_degrees=True)
    graph=compile_frontier(inp.inst,prepared=plan,max_states=200000,max_edges=600000,max_seconds=30)
    engine=OwnedGraphSolver(graph)
    frozen=json.loads((folder/'runs/history_B2_n32_r0.json').read_text(encoding='utf8'))
    filtered=json.loads((folder/'runs/history_B1_n32_r0.json').read_text(encoding='utf8'))
    assert digest(inp)==frozen['input_sha256']==filtered['input_sha256']
    queries=workload(inp.inst,100)
    assert all(a['answer_sha256']==b['answer_sha256'] for a,b in zip(filtered['queries'],frozen['queries']))
    targets=[]
    for n in (1,16,32):
        targets += [reg.literal(('rf',f'w1_{n}_ax',f'w1_{n}_ar')),
                    reg.literal(('rf',f'w2_{n}_bx',f'w1_{n}_ar')),
                    reg.literal(('co',f'w1_{n}_ax',f'w2_{n}_bx'))]
    witnesses={};records=[]
    for j,q in enumerate(queries[:10]):
        ok,forced=engine.propagate(q['assumptions'])
        supports={lit for v in reg.by_id for lit in (v,-v) if -lit not in forced} if ok else set()
        assert digest([ok,sorted(supports)])==frozen['queries'][j]['answer_sha256']
        checked=[]
        for literal in [None]+[l for v in targets for l in (v,-v)]:
            alpha=q['assumptions']+([] if literal is None else [literal])
            witness=engine.witness(alpha)
            if witness is None:continue
            ident=digest(sorted(witness))
            if ident not in witnesses:
                assert evaluate_assignment(inp,witness) and set(alpha)<=witness
                witnesses[ident]=sorted(witness)
            checked.append(dict(literal=literal,witness_sha256=ident))
        records.append(dict(name=q['name'],sat=ok,positive_checks=checked))
    result=dict(status='OK',rounds=32,events=len(inp.inst.events),original_variables=reg.nvars,
        input_sha256=digest(inp),full_support_queries_matching_B1=len(filtered['queries']),
        B1_caveat='independent SAT encoding; same protocol preprocessing as B2',
        unique_raw_RA_checked_witnesses=len(witnesses),queries=records,
        witnesses=witnesses,negative_supports_not_independently_certified=True,
        raw_B0_32_status='30-second encoding timeout; no completed raw support query')
    save(folder/'large32_check.json',result)
    print('large32 OK',len(witnesses),'raw RA witness checks',flush=True)


if __name__=='__main__':main()
