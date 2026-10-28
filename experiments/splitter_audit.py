"""Portable, source-derived splitter evidence; no remote server is required.

python experiments/splitter_audit.py --out results/splitter_20261019
Resource failures are saved as UNKNOWN. No frozen publication data is edited.
"""
import argparse
from dataclasses import asdict
import hashlib
from itertools import combinations, product
import json
from pathlib import Path
import platform
import random
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wmcheck.compiler import ResourceLimit
from wmcheck.complete_query import forced_by_search
from wmcheck.dag_reduce import reduce_dag
from wmcheck.oracle import truth_under
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.propagation import unit_propagate
from wmcheck.ra import RARegistry, recognize
from wmcheck.ra_frontier import compile_frontier
from wmcheck.ra_incidence_sat import IncidenceSAT
from wmcheck.ra_objects import compile_objects
from wmcheck.ra_oracle import enumerate_assignments, valid
from wmcheck.ra_splitter import grid_family, root_probe
from wmcheck.trace_diagnosis import diagnose


def decode(inst, reg, assignment):
    rf = {r: next(w for w in inst.candidates[r] if assignment[reg.literal(('rf', w, r))])
          for r in inst.reads}
    orders = {}
    for loc in sorted({e.loc for e in inst.events}):
        ws = [w for w in inst.writes if inst.event[w].loc == loc]
        def before(a, b):
            lit = reg.literal(('co', a, b))
            return a != b and assignment[abs(lit)] == (lit > 0)
        orders[loc] = tuple(sorted(ws, key=lambda b: sum(before(a, b) for a in ws)))
    return rf, orders


def sc_schedule(inst, rf, orders):
    """Independent SC witness check: sb + rf + co + fr must be acyclic.

    This uses neither the RA recognizer nor any compiled monitor.
    """
    edges = set(inst.sb) | {(w, r) for r, w in rf.items()}
    co = {(a, b) for ws in orders.values() for i, a in enumerate(ws) for b in ws[i+1:]}
    edges |= co | {(r, v) for r, w in rf.items() for u, v in co if u == w}
    pending = set(inst.event)
    result = []
    while pending:
        available = sorted(v for v in pending if not any(b == v and a in pending for a, b in edges))
        if not available:
            return None
        v = available[0]
        pending.remove(v)
        result.append(v)
    return result


def grid_sc_witness(inst, layout):
    """Construct and replay an SC schedule for the ordinary peel-route family.

    At a node: write the right participant's X first; the stopping participant
    writes X last; all open-door checks precede door-closing writes. No solver
    certificate or inferred HB/CO relation is consulted.
    """
    schedule = list(inst.initial)
    for obj in layout['object_order']:
        members = [v for v in layout['order'] if layout['event_owner'][v] == obj and v not in inst.initial]
        xs = [v for v in members if v.endswith('_wx')]
        reads = [v for v in members if v.endswith('_rx')]
        wanted = {inst.event[v].value for v in reads}
        if len(wanted) != 1 or None in wanted:
            raise ValueError('Not a retained ordinary peel trace')
        value = next(iter(wanted))
        xs.sort(key=lambda v: inst.event[v].value == value)
        schedule += xs
        schedule += [v for v in members if v.endswith('_ry') and inst.event[v].value == 0]
        schedule += [v for v in members if v.endswith('_wy')]
        schedule += reads
        schedule += [v for v in members if v.endswith('_ry') and inst.event[v].value == 1]
    position = {v: j for j, v in enumerate(schedule)}
    assert set(position) == set(inst.event) and len(schedule) == len(inst.event)
    assert all(position[a] < position[b] for a, b in inst.sb)
    latest, rf, orders = {}, {}, {}
    for v in schedule:
        e = inst.event[v]
        if e.kind == 'W':
            latest[e.loc] = v
            orders.setdefault(e.loc, []).append(v)
        else:
            w = latest[e.loc]
            assert e.value is None or e.value == inst.event[w].value
            rf[v] = w
    assert valid(inst, rf, orders)
    return dict(schedule=schedule, rf=rf, co_orders=orders)


def compile_case(inst, layout, *, old_init=False, seconds=20, cnf=False):
    return compile_frontier(inst, order=layout['order'], co_mode='direct',
        summary_mode='ports', rf_mode='atomic', source_covers=True,
        early_degrees=True, elide_init_hb=not old_init, cnf=cnf,
        max_seconds=seconds, max_states=150000, max_edges=500000)


def candidate_width(inst, layout, old_init=False, atomic=True):
    """Audit ALL raw candidates, without relying on any recognition pruning."""
    groups = list(inst.sb)
    if old_init:
        groups += [(i, seq[0]) for i in inst.initial for seq in inst.threads if seq]
    for r, ws in inst.candidates.items():
        groups += [(r, *ws)] if atomic else [(w, r) for w in ws]
    for a, b in combinations(inst.writes, 2):
        if inst.event[a].loc == inst.event[b].loc:
            groups.append((a, b))
    groups += [(v,) for v in inst.event]
    rank = {v: i for i, v in enumerate(layout['order'])}
    groups.sort(key=lambda vs: (max(rank[v] for v in vs), min(rank[v] for v in vs)))
    last = {v: j for j, vs in enumerate(groups) for v in vs}
    active = set()
    peak = 0
    for j, vs in enumerate(groups):
        active.update(vs)
        peak = max(peak, len(active))
        active = {v for v in active if last[v] > j}
    return peak


def json_input(inst, layout, metadata):
    return dict(events=[asdict(e) for e in inst.events], threads=inst.threads,
                initial=inst.initial, layout=layout, extraction=metadata)


def literal_keys(reg, literals):
    return [dict(value=lit > 0, key=reg.by_id[abs(lit)]) for lit in sorted(literals, key=abs)]


def exact_audit(out):
    inst, layout, metadata = root_probe()
    (out/'root_probe.input.json').write_text(json.dumps(json_input(inst, layout, metadata), indent=2)+'\n')
    c = compile_case(inst, layout, cnf=True)
    engine = OwnedGraphSolver(c)
    models = list(enumerate_assignments(inst, c.registry))
    reg = c.registry
    prefix = 'b0000_r0000_c0000'
    event = lambda t, op: f't{t}_{prefix}_{op}'
    rf = lambda t, op, u, wop: reg.literal(('rf', event(u, wop), event(t, op)))
    cy = reg.literal(('co', event(0, 'wy'), event(1, 'wy')))
    cx = reg.literal(('co', event(0, 'wx'), event(1, 'wx')))
    a_other, b_other = rf(0, 'rx', 1, 'wx'), rf(1, 'rx', 0, 'wx')
    a_own, b_own = rf(0, 'rx', 0, 'wx'), rf(1, 'rx', 1, 'wx')
    right_a, right_b = rf(2, 'ry', 0, 'wy'), rf(2, 'ry', 1, 'wy')
    selected = [a_other, b_other, a_own, b_own, right_a, cy]
    checked = 0
    for values in product((-1, 0, 1), repeat=len(selected)):
        alpha = [v*s for v, s in zip(selected, values) if s]
        expected = truth_under(models, alpha)
        assert engine.propagate(alpha) == expected
        up = unit_propagate(c.clauses, alpha)
        assert up.consistent == expected[0]
        if up.consistent:
            actual = {v if b else -v for v, b in up.values.items() if v in reg.by_id}
            assert actual == expected[1]
        checked += 1
    scenarios = [('root', []), ('both_stop', [a_own, b_own]),
                 ('A_reads_B', [a_other]), ('B_reads_A', [b_other]),
                 ('both_read_other', [a_other, b_other]),
                 ('inverted_order', [a_other, -cx]),
                 ('right_from_A', [right_a]), ('right_from_B', [right_b]),
                 ('Y_A_before_B', [cy]), ('Y_B_before_A', [-cy])]
    scenarios += [(f'both_stop_source{source}_co{direction}', [a_own, b_own, source_lit, co_lit])
                  for source, source_lit in [('A', right_a), ('B', right_b)]
                  for direction, co_lit in [('AB', cy), ('BA', -cy)]]
    rows = []
    witnesses = []
    with IncidenceSAT(inst) as sat:
        for name, alpha in scenarios:
            expected = engine.propagate(alpha)
            answer = forced_by_search(sat.solver, reg.by_id, alpha)
            assert answer[:2] == expected
            rows.append(dict(name=name, assumptions=literal_keys(reg, alpha),
                             consistent=expected[0], forced=literal_keys(reg, expected[1]),
                             sat_calls=answer[2]))
            if answer[0]:
                # forced_by_search may leave the last SAT call UNSAT. Obtain
                # a fresh model for the original assumptions before decoding.
                assert sat.solve(alpha)
                assignment = {abs(v): v > 0 for v in sat.model() if abs(v) in reg.by_id}
                sources, orders = decode(inst, reg, assignment)
                assert valid(inst, sources, orders)
                witnesses.append(dict(name=name, rf=sources, co_orders=orders,
                                      sc_schedule=sc_schedule(inst, sources, orders)))
    both_stop = [m for m in models if m[a_own] and m[b_own]]
    sc_models = [m for m in models if sc_schedule(inst, *decode(inst, reg, m)) is not None]
    assert both_stop and not any(sc_schedule(inst, *decode(inst, reg, m)) for m in both_stop)
    for a, b in product((right_a, right_b), (cy, -cy)):
        assert engine.propagate([a_own, b_own, a, b])[0]
    diagnosis = diagnose(reg, engine.propagate, [a_other, b_other, right_a])
    (out/'root_probe.witnesses.json').write_text(json.dumps(witnesses, indent=2)+'\n')
    (out/'root_probe.models.json').write_text(json.dumps(dict(
        registry=reg.by_id, ra_models=[[v if m[v] else -v for v in reg.by_id] for m in models],
        sc_models=[[v if m[v] else -v for v in reg.by_id] for m in sc_models]), indent=2)+'\n')
    return dict(events=len(inst.events), original_variables=reg.nvars, ra_models=len(models),
                sc_models=len(sc_models), duplicate_stop_ra_models=len(both_stop),
                duplicate_stop_sc_models=0, exhaustive_selected_partial_assignments=checked,
                all_original_supports_compared_per_query=reg.nvars,
                scenarios=rows, diagnosis=diagnosis, stats=c.stats)


def run_case(out, workers, batches, *, duplicate=False, old_init=False, seconds=20):
    inst, layout, metadata = grid_family(workers, batches, duplicate_stop=duplicate)
    label = f'p{workers}_b{batches}'+('_duplicate' if duplicate else '')+('_globalinit' if old_init else '')
    row = dict(name=label, workers=workers, batches=batches, duplicate_stop=duplicate,
               global_init_hb=old_init, events=len(inst.events), initial_events=len(inst.initial),
               objects=layout['objects'], theorem_bound=layout['interface_bound'],
               raw_binary_width=candidate_width(inst, layout, atomic=False),
               raw_atomic_width=candidate_width(inst, layout),
               old_raw_atomic_width=candidate_width(inst, layout, old_init=True))
    assert row['raw_atomic_width'] <= row['theorem_bound']
    if not duplicate:
        witness = grid_sc_witness(inst, layout)
        (out/(label+'.sc_witness.json')).write_text(json.dumps(witness, indent=2)+'\n')
        row['independent_sc_schedule_replayed'] = True
    start = perf_counter()
    try:
        c = compile_case(inst, layout, old_init=old_init, seconds=seconds)
        reduced = reduce_dag(c)
        row.update(status='OK', stats=c.stats, reduced_states=sum(map(len, reduced.layers)))
        assert c.stats['max_interface'] <= layout['interface_bound'] or old_init
        engine = OwnedGraphSolver(reduced)
        consistent, forced = engine.propagate(())
        assert consistent
        reg = c.registry
        ambiguous = {r: [w for w in inst.candidates[r] if -reg.literal(('rf', w, r)) not in forced]
                     for r in inst.reads}
        row['multi_source_reads'] = sum(len(ws) > 1 for ws in ambiguous.values())
        row['unresolved_original_co'] = sum(k[0] == 'co' and v not in forced and -v not in forced
                                             for v, k in reg.by_id.items())
        row['root_forced_original_literals'] = len(forced)
        # A selected independent complete-support check, including every RF/CO
        # bit, for the moderate cases. Larger rows are structural/compile data.
        if len(inst.events) <= 120:
            with IncidenceSAT(inst) as sat:
                answer = forced_by_search(sat.solver, reg.by_id)
                assert answer[:2] == (consistent, forced)
                row['independent_all_root_supports_checked'] = True
                row['independent_sat_calls'] = answer[2]
                assert sat.solve(())
                model = {abs(v): v > 0 for v in sat.model() if abs(v) in reg.by_id}
                sources, orders = decode(inst, reg, model)
                assert valid(inst, sources, orders)
        (out/(label+'.input.json')).write_text(json.dumps(json_input(inst, layout, metadata), indent=2)+'\n')
    except ResourceLimit as err:
        row.update(status='UNKNOWN', reason=str(err), stats=getattr(err, 'stats', {}))
    row['audit_seconds'] = perf_counter()-start
    print(label, row['status'], row['events'], row.get('stats', {}).get('max_interface'),
          round(row['audit_seconds'], 3), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    result = dict(scope='Fixed traces of our release/acquire port; not industrial extraction or a verification of all dynamic branches',
                  python=sys.version, platform=platform.platform(), exact=exact_audit(out), runs=[])
    def save():
        (out/'audit.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    save()
    cases = [(3, 1, False, False), (3, 1, True, False), (5, 1, False, False)]
    if not args.quick:
        cases += [(p, 1, False, False) for p in (7, 9)]
        cases += [(3, n, True, False) for n in (2, 4, 8, 16, 32)]
        cases += [(3, n, True, True) for n in (2, 8)]
    for p, n, duplicate, old in cases:
        result['runs'].append(run_case(out, p, n, duplicate=duplicate, old_init=old, seconds=20))
        save()
    structure = []
    for p, n in ((3, 1), (5, 1), (9, 1), (17, 1), (33, 1), (3, 8), (3, 32), (3, 64)):
        inst, layout, _ = grid_family(p, n)
        binary = candidate_width(inst, layout, atomic=False)
        atomic = candidate_width(inst, layout)
        assert max(binary, atomic) <= layout['interface_bound'] <= 5*p+2
        structure.append(dict(workers=p, batches=n, objects=layout['objects'], events=len(inst.events),
                              binary_width=binary, atomic_width=atomic, bound=layout['interface_bound'],
                              global_init_atomic_width=candidate_width(inst, layout, old_init=True)))
    result['structure'] = structure
    # Exact semantic factorization, checked against the unsplit RA oracle.
    # This is a separate run, not a relabeling of the monolithic experiments.
    factor_rows = []
    for p, n in ((3, 1), (5, 1), (3, 8), (3, 32), (3, 128)):
        inst, layout, metadata = grid_family(p, n, duplicate_stop=(p == 3))
        owners = {e.loc: layout['event_owner'][e.id] for e in inst.events}
        start = perf_counter()
        row = dict(workers=p, batches=n, events=len(inst.events), objects=layout['objects'],
                   factor_interface_bound=layout['max_events_per_object']+layout['max_initials_per_object'])
        try:
            c = compile_objects(inst, owners, max_seconds=20, co_mode='direct', summary_mode='ports',
                                rf_mode='atomic', source_covers=True, early_degrees=True)
            answer = OwnedGraphSolver(c).propagate(())
            assert answer[0] and c.stats['max_interface'] <= row['factor_interface_bound'] <= 4*p+2
            row.update(status='OK', states=c.stats['states'], transitions=c.stats['transitions'],
                       original_variables=c.registry.nvars, max_interface=c.stats['max_interface'],
                       compile_seconds=c.stats['compile_seconds'])
            if len(inst.events) <= 150:
                with IncidenceSAT(inst) as sat:
                    expected = forced_by_search(sat.solver, c.registry.by_id)
                    assert answer == expected[:2]
                    row['independent_all_root_supports_checked'] = True
                    row['independent_sat_calls'] = expected[2]
        except ResourceLimit as err:
            row.update(status='UNKNOWN', reason=str(err))
        row['audit_seconds'] = perf_counter()-start
        factor_rows.append(row)
        result['factorization_runs'] = factor_rows
        save()
        print('factor', p, n, row['status'], round(row['audit_seconds'], 3), flush=True)
    sources = ['wmcheck/ra_frontier.py', 'wmcheck/ra_object_layout.py', 'wmcheck/ra_splitter.py',
               'wmcheck/ra_objects.py', 'experiments/splitter_audit.py', 'examples/splitter_grid.c',
               'tests/test_object_protocol.py']
    result['source_sha256'] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
    save()
    print('Exact RA models:', result['exact']['ra_models'], 'selected partial assignments:',
          result['exact']['exhaustive_selected_partial_assignments'], flush=True)


if __name__ == '__main__':
    main()
