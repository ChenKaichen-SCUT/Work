"""Reproduce source-sensitive queries and independently validate full witnesses.

This audit is separate from publication_study.py's frozen timing campaign.
Optional GenMC runs check only the generated C observable outcome, not RF/CO
support equivalence or the particular non-SC witness.
"""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pysat.solvers import Minisat22
from experiments.publication_study import diagnostic_queries, save
from wmcheck.complete_query import forced_by_search
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.propagation import unit_propagate
from wmcheck.ra import RARegistry, recognize
from wmcheck.ra_frontier import compile_frontier
from wmcheck.ra_oracle import reach, valid
from wmcheck.ra_publication import publication_exchange, publication_layout, staged_witness
from wmcheck.ra_sat import encode_ra


def decode(inst, reg, model):
    positive = set(model)
    rf = {r: w for v, (kind, w, r) in reg.by_id.items() if kind == 'rf' and v in positive}
    orders = {}
    for loc in sorted({e.loc for e in inst.events}):
        ws = [w for w in inst.writes if inst.event[w].loc == loc]
        orders[loc] = sorted(ws, key=lambda w: sum(reg.literal(('co', v, w)) in positive for v in ws if v != w))
    assert valid(inst, rf, orders), 'SAT witness rejected by independent dense RA definition'
    return dict(rf=rf, orders=orders, independent_ra_valid=True)


def finite_family_checks():
    rows = []
    for n, copies in ((1, 2), (2, 2), (3, 2), (2, 3)):
        inst = publication_exchange(n, copies)
        cert = recognize(inst, source_covers=True)
        assert cert['status'] == 'RECOGNIZED'
        for t in range(2):
            for i in range(2, n+1):
                assert cert['domains'][f't{t}_{i}_wait'] == {f't{1-t}_{i-1}_pub{j}' for j in range(copies)}
        count = 0
        for directions in product((0, 1), repeat=2*n):
            for publications in product(range(copies), repeat=2*(n-1)):
                rf, orders = staged_witness(inst, n, copies)
                for k, loc in enumerate(('x', 'y')):
                    orders[loc] = ('i'+loc,) + tuple(f't{t}_{i}_{loc}' for i in range(1, n+1)
                        for t in ((0, 1) if directions[k*n+i-1] else (1, 0)))
                for t in range(2):
                    for i in range(2, n+1):
                        rf[f't{t}_{i}_wait'] = f't{1-t}_{i-1}_pub{publications[t*(n-1)+i-2]}'
                assert valid(inst, rf, orders)
                count += 1
        assert count == 4**n * copies**(2*(n-1))
        rf, orders = staged_witness(inst, n, copies)
        co = {(a, b) for ws in orders.values() for i, a in enumerate(ws) for b in ws[i+1:]}
        assert ('t0_1_x', 't0_1_x') in reach(inst.sb | co, inst.event)
        rows.append(dict(rounds=n, publications=copies, independently_checked_distinct_models=count,
                         staged_non_sc_witness=True, exact_flag_domains=True))
    return rows


def audit(out):
    inst = publication_exchange(2); reg = RARegistry(inst); enc = encode_ra(inst)
    c = compile_frontier(inst, order=publication_layout(inst, 2), co_mode='direct',
                         summary_mode='ports', source_covers=True, early_degrees=True, cnf=True)
    engine = OwnedGraphSolver(c)
    order = reg.literal(('co', 't0_1_y', 't1_2_y'))
    named = diagnostic_queries(reg, 2)
    named.append(dict(name='first_with_forward_co', assumptions=named[1]['assumptions']+[order]))
    records = []
    with Minisat22(bootstrap_with=enc.clauses) as sat:
        for row in named:
            alpha = row['assumptions']
            ok, forced, _ = forced_by_search(sat, reg.by_id, alpha)
            assert engine.propagate(alpha) == (ok, forced)
            up = unit_propagate(c.clauses, alpha)
            assert up.consistent == ok
            if ok:
                assert {v if b else -v for v, b in up.values.items() if v in reg.by_id} == forced
            record = dict(row, consistent=ok, co_forced=order in forced if ok else None,
                          forced_original_literals=sorted(forced) if ok else [],
                          graph_sat_pure_up_agree=True)
            if ok:
                assert sat.solve(assumptions=alpha)
                record['witness'] = decode(inst, reg, sat.get_model())
            records.append(record)
    report = dict(co_query=['co', 't0_1_y', 't1_2_y'], co_literal=order,
                  queries=records, finite_family=finite_family_checks(),
                  source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (Path(__file__), ROOT/'wmcheck/ra_publication.py', ROOT/'wmcheck/ra.py')})
    save(out/'semantic_audit.json', report)
    print(json.dumps([dict(name=r['name'], consistent=r['consistent'], co_forced=r['co_forced']) for r in records], indent=2))


def native(out, executable):
    from experiments.paper_external import genmc_reachable
    version = subprocess.run([executable, '--version'], capture_output=True, text=True, check=True).stdout
    records = []
    for n in (1, 2, 3):
        source = out/'inputs'/f'n{n}.c'
        command = [executable, '--rc11', '--disable-estimation', '--', str(source)]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
            log = proc.stdout + proc.stderr
            answer = genmc_reachable(log, source)
            record = dict(rounds=n, command=command, exit_code=proc.returncode, outcome_reachable=answer,
                          status='checked' if answer is not None else 'unclassified')
        except subprocess.TimeoutExpired as exc:
            log = str(exc)
            record = dict(rounds=n, command=command, status='UNKNOWN', reason='wall_timeout_60s')
        (out/f'genmc_n{n}.txt').write_text(log, encoding='utf8')
        record['c_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        records.append(record)
    save(out/'native_outcomes.json', dict(version=version, contract='observable read values only', runs=records))
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--genmc')
    args = parser.parse_args()
    dest = Path(args.out).resolve(); dest.mkdir(parents=True, exist_ok=True)
    audit(dest)
    if args.genmc:
        native(dest, args.genmc)
