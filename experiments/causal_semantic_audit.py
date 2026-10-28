"""Independent complete-projection and rollback acceptance for the causal pilot."""
import argparse
import itertools
import json
import sys
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.causal_bench import save, digest, workload
from wmcheck.ra import RARegistry, RAInstance
from wmcheck.ra_protocols import (barrier_instance, buffer_instance, prefix_input,
                                 build_protocol, replay_certificate, buffer_chain_bags)
from wmcheck.ra_frontier import prepare_frontier, compile_frontier
from wmcheck.ra_reference import (evaluate_assignment, enumerate_completions,
                                 all_boolean_assignments, supports_from_models, has_sc_linearization)
from wmcheck.ra_support_sat import SupportSAT
from wmcheck.owned_dag import OwnedGraphSolver


def projected_models(compiled, limit=200000):
    outgoing = {}
    for edge in compiled.edges:
        outgoing.setdefault(edge.source, []).append(edge)
    final = set(compiled.layers[-1])
    pending = [(compiled.layers[0][0], frozenset())]
    models = set()
    paths = 0
    while pending:
        node, labels = pending.pop()
        if node in final:
            assert len(labels) == compiled.registry.nvars
            assert not any(-v in labels for v in labels)
            models.add(labels)
            paths += 1
            if paths > limit:
                raise RuntimeError('Projection path audit budget')
        for edge in outgoing.get(node, ()):
            pending.append((edge.target, labels.union(edge.label)))
    return models


def audit_case(name, inp, *, complete=True, chain=False, boolean=False):
    tick = time.perf_counter()
    reg = RARegistry(inp.inst)
    pre = build_protocol(inp)
    row = dict(name=name, events=len(inp.inst.events), variables=reg.nvars,
               pre_status=pre['status'], input_sha256=digest(inp))
    if pre['status'] == 'OUTSIDE':
        row.update(status='OUTSIDE', reason=pre.get('reason'))
        return row
    assert replay_certificate(inp, pre)
    options = dict(certificate=pre['certificate'], order=pre['order'],
                   co_mode='direct', summary_mode='ports', early_degrees=True)
    if chain and pre['status'] == 'CERTIFIED':
        options['bags'] = buffer_chain_bags(inp, pre)
    plan = prepare_frontier(inp.inst, **options)
    compiled = compile_frontier(inp.inst, prepared=plan, max_states=200000,
                                max_edges=600000, max_seconds=30)
    engine = OwnedGraphSolver(compiled)
    row['backend_consistent'] = engine.witness() is not None
    if chain and pre['status'] == 'CERTIFIED':
        first = {}
        for step, (vertices, _) in enumerate(plan.groups):
            for event in vertices:
                first.setdefault(event, step)
        row['reverse_sb_introduction_edges'] = sorted([a,b] for a,b in inp.inst.sb if first[b] < first[a])
        if name == 'buffer_failed_chain':
            assert row['reverse_sb_introduction_edges'], 'chain risk was not exercised'
    row['plan_stats'] = plan.stats
    row['graph_stats'] = compiled.stats
    queries = workload(inp.inst, 20)
    models = None
    if complete:
        models = set(enumerate_completions(inp, limit=200000))
        actual = projected_models(compiled)
        assert models == actual, (name, 'projection', len(models), len(actual),
                                  list(models-actual)[:1], list(actual-models)[:1])
        row.update(complete_projection=True, legal_assignments=len(models),
                   assignment_set_sha256=digest(sorted([sorted(m) for m in models])))
        if models:
            row['non_sc_assignments'] = sum(not has_sc_linearization(inp, m) for m in models)
            first = sorted(next(iter(models)), key=abs)
            if first:
                queries += [dict(name='model_partial', assumptions=first[::2], target=first[0]),
                            dict(name='full_model', assumptions=first, target=first[0])]
    else:
        row['complete_projection'] = False
    calls = 0
    with SupportSAT(inp) as raw, SupportSAT(inp, certificate=pre['certificate']) as filtered:
        if boolean:
            row['boolean_assignments'] = 0
            for x in all_boolean_assignments(reg, max_variables=12):
                expected = evaluate_assignment(inp, x)
                assert raw.solve(x) == expected
                assert filtered.solve(x) == expected
                assert (engine.witness(x) is not None) == expected
                row['boolean_assignments'] += 1
        checks = []
        for q in queries:
            alpha = q['assumptions']
            ok, forced = engine.propagate(alpha)
            expected = (ok, {l for v in reg.by_id for l in (v,-v) if -l not in forced} if ok else set())
            a, b = raw.all_support(alpha), filtered.all_support(alpha)
            assert a == b == expected, (name, q['name'], 'supports', a, b, expected)
            if models is not None:
                assert supports_from_models(models, alpha) == expected
            if ok:
                witness = engine.witness(alpha)
                assert evaluate_assignment(inp, witness) and set(alpha) <= witness
                assert raw.solve(alpha)
                assert evaluate_assignment(inp, raw.model_original())
            checks.append(dict(name=q['name'], assumptions=alpha, sat=ok,
                               answer_sha256=digest([ok, sorted(expected[1])])) )
            calls += 1
        row['queries'] = checks
    row.update(status='OK', query_checks=calls, seconds=time.perf_counter()-tick,
               certificate_replayed=True, all_sat_witnesses_dense_checked=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out)
    result = dict(status='RUNNING', cases=[], failures=[], contract='full projection for enumerated cases; explicit selected queries otherwise')
    cases = [
        ('barrier_control_boolean', barrier_instance(1, workers=1, data=False), dict(boolean=True)),
        ('barrier_data_identity_nonSC', barrier_instance(1), {}),
        ('barrier_data_failure', barrier_instance(1, failures=1), {}),
        ('buffer_value_boolean', buffer_instance(1, capacity=1, data=False), dict(boolean=True)),
        ('buffer_branch_boolean', buffer_instance(1, capacity=1, mode='branch', data=False), dict(boolean=True)),
        ('buffer_branch_guard', buffer_instance(1, capacity=2, mode='branch', data=False), {}),
        ('buffer_failed_chain', buffer_instance(1, capacity=2, mode='branch', failures=1,
                                              tail_failures=1, data=False), dict(chain=True)),
        ('buffer_only_failed_tail', buffer_instance(0, capacity=2, mode='branch', tail_failures=2,
                                                  data=False), dict(chain=True)),
        ('buffer_false_full_t_lt_C', buffer_instance(0, capacity=2, mode='branch', producer_tail_failures=1,
                                                   data=False), {}),
        ('barrier_2_selected', barrier_instance(2), dict(complete=False)),
        ('buffer_3_branch_selected', buffer_instance(3, capacity=3, mode='branch'), dict(complete=False)),
    ]
    short = barrier_instance(1, workers=1, failures=1, data=False)
    for coordinator in range(len(short.inst.threads[0])+1):
        for worker in range(len(short.inst.threads[1])+1):
            cases.append((f'barrier_prefix_c{coordinator}_w{worker}',
                          prefix_input(short, {0:coordinator,1:worker}), {}))
    buffer = buffer_instance(1, capacity=2, mode='branch', data=False)
    for producer, consumer in ((0,0),(1,0),(2,1),(3,1),(3,2),(2,3)):
        cases.append((f'buffer_partial_p{producer}_q{consumer}',
                      prefix_input(buffer,{0:producer,1:consumer}), {}))
    backend_unsat = deepcopy(barrier_instance(1))
    changes = {'w1_1_ax':('W',1), 'w1_1_ay':('R',2), 'w1_1_ar':('R',2),
               'w2_1_by':('W',2), 'w2_1_bx':('R',1), 'w2_1_br':('R',1)}
    events = tuple(replace(e, kind=changes[e.id][0], loc='x', value=changes[e.id][1])
                   if e.id in changes else e for e in backend_unsat.inst.events)
    backend_unsat.inst = RAInstance(events, backend_unsat.inst.threads, backend_unsat.inst.initial)
    cases.append(('certified_but_backend_unsat', backend_unsat, {}))
    malformed = deepcopy(buffer)
    malformed.guards = malformed.guards + ({'op':'arbitrary_joint_guard'},)
    cases.append(('unsupported_joint_guard',malformed,{}))
    for name, inp, options in cases:
        row = audit_case(name, inp, **options)
        if name == 'certified_but_backend_unsat':
            assert row['pre_status'] == 'CERTIFIED' and not row['backend_consistent']
        if name == 'unsupported_joint_guard':
            assert row['status'] == 'OUTSIDE'
        elif row['status'] != 'OK':
            result['failures'].append([name,row])
        result['cases'].append(row)
        save(out, result)
        print(name,row['status'],row.get('legal_assignments'),flush=True)
    result.update(status='OK' if not result['failures'] else 'FAILED',
                  boolean_assignments=sum(r.get('boolean_assignments',0) for r in result['cases']),
                  complete_projection_cases=sum(r.get('complete_projection',False) for r in result['cases']),
                  query_checks=sum(r.get('query_checks',0) for r in result['cases']))
    save(out,result)
    if result['failures']:
        raise AssertionError(result['failures'])


if __name__ == '__main__':
    main()
