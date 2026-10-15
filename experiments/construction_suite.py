"""Reproducible isolated construction/support experiments; no external source."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def queries(inst, registry, number=64):
    """Reproducible identity-sensitive queries; half sampled from legal models.

    Does not enumerate models. Fixed seed shared by every compilation method.
    For generic RA fixtures use predetermined input distributions, independently
    compare those answers against the dense oracle in the validation campaign.
    """
    from wmcheck.ra_schedule import certificate, OutsideCertificate
    rng = random.Random(20261015)
    variables = list(registry.by_id)
    try:
        writers, readers = certificate(inst)
    except OutsideCertificate:
        return [[]]+[[v*rng.choice((-1, 1)) for v in variables if rng.random() < .15] for _ in range(number-1)]
    out = [[]]
    for j in range(number-1):
        counts = [0]*len(writers); order = [inst.initial[0]]
        while any(n < len(t) for n, t in zip(counts, writers)):
            p = rng.choice([p for p, t in enumerate(writers) if counts[p] < len(t)])
            order.append(writers[p][counts[p]]); counts[p] += 1
        positions = {w: i for i, w in enumerate(order)}; rf = {}
        for t in readers:
            lower = 0
            for r in t:
                choices = [w for w in inst.candidates[r] if positions[w] >= lower]
                if not choices:
                    break
                source = rng.choice(choices); rf[r] = source; lower = positions[source]
        if len(rf) != len(inst.reads):
            out.append([]); continue
        model = {v: (rf[b] == a if kind == 'rf' else positions[a] < positions[b])
                 for v, (kind, a, b) in registry.by_id.items()}
        # Include RF-only, CO-only, mixed satisfiable restrictions and arbitrary
        # mixed restrictions. Avoid assuming the many fixed chain CO constants.
        owner = {w: p for p, t in enumerate(writers) for w in t}
        free = [v for v, (kind, a, b) in registry.by_id.items()
                if kind == 'rf' or (a in owner and b in owner and owner[a] != owner[b])]
        mode = j % 4; fraction = (.05, .2, .5)[j % 3]
        alpha = []
        for v in free:
            if (mode == 0 and registry.by_id[v][0] != 'rf') or (mode == 1 and registry.by_id[v][0] != 'co'):
                continue
            if rng.random() < fraction:
                truth = rng.choice((False, True)) if mode == 3 else model[v]
                alpha.append(v if truth else -v)
        out.append(alpha)
    return out


def worker(spec, dest):
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (3*1024**3,)*2)
    if 'cpu' in spec:
        os.sched_setaffinity(0, {spec['cpu']})
    from wmcheck.ra import producers, pipeline
    from wmcheck.ra_schedule import compile_schedule, compile_co_first
    from wmcheck.ra_frontier import compile_frontier
    from wmcheck.ra_order_sat import encode_order
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.ra_grid import compile_grid, GridSolver, grid_cnf
    from wmcheck.compiler import ResourceLimit
    from wmcheck.complete_query import forced_by_search
    from pysat.solvers import Minisat22
    record = dict(spec=spec, status='started',
                  started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted((ROOT/'wmcheck').glob('*.py'))})
    begin = time.perf_counter()
    try:
        family = spec['family']; n = spec['n']
        inst = producers((n, n)) if family == 'producers' else pipeline(n)
        method = spec['method']; options = dict(max_seconds=60, max_states=100000)
        record.update(events=len(inst.events), stage='compile')
        Path(dest).write_text(json.dumps(record))
        if method in ('grid', 'grid-cnf'):
            compiled = compile_grid(inst, max_edges=300000, **options)
            raw_grid = compiled
            if method == 'grid-cnf':
                compiled = grid_cnf(compiled)
        elif method in ('dynamic', 'dynamic-cnf', 'unfold'):
            compiled = compile_schedule(inst, cnf=method == 'dynamic-cnf', merge=method != 'unfold',
                                        max_edges=300000, **options)
        elif method == 'co-first':
            compiled = compile_co_first(inst, max_edges=300000, **options)
        elif method == 'order-sat':
            compiled = encode_order(inst)
        else:
            # Phase-interleaved layout is fixed from input identities, not from
            # a selected execution or a current set of assumptions.
            order = None
            if family == 'pipeline':
                order = inst.initial+tuple(v for stage in range(1, n+1) for t in inst.threads
                                           for v in t if v.split('_')[1] == str(stage))
            compiled = compile_frontier(inst, order=order, incremental=method != 'frontier-full',
                                        compact=method != 'frontier-dfa',
                                        merge=method != 'frontier-unfold', max_edges=300000, **options)
        record.update(compiled.stats)
        qs = queries(inst, compiled.registry, spec.get('queries', 64))
        record['query_sha256'] = hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        record['stage'] = 'setup'; Path(dest).write_text(json.dumps(record))
        start = time.perf_counter()
        sat_backend = method in ('order-sat', 'dynamic-cnf', 'grid-cnf')
        solver = Minisat22(bootstrap_with=compiled.clauses) if sat_backend else GridSolver(compiled) if method == 'grid' else OwnedGraphSolver(compiled)
        # MiniSat's propagate result omits root units; recover them once. For
        # ordinary SAT this cost is exact support search and is charged to setup.
        root = set()
        if sat_backend:
            if method != 'order-sat' and spec.get('root_policy', 'propagation') == 'propagation':
                engine = GridSolver(raw_grid) if method == 'grid-cnf' else OwnedGraphSolver(compiled)
                _, root = engine.propagate()
                record.update(root_sat_calls=0, root_support_source='exact_support_graph')
            else:
                units = {c[0] for c in compiled.clauses if len(c) == 1 and abs(c[0]) in compiled.registry.by_id}
                _, root, root_calls = forced_by_search(solver, compiled.registry.by_id, known=units)
                record.update(root_sat_calls=root_calls, root_support_source='countermodel_search')
        record['setup_seconds'] = time.perf_counter()-start
        results, times, sat_calls = [], [], 0
        record['stage'] = 'queries'; Path(dest).write_text(json.dumps(record))
        for alpha in qs:
            start = time.perf_counter()
            if method == 'order-sat':
                ok, forced, calls = forced_by_search(solver, compiled.registry.by_id, alpha, known=root)
                sat_calls += calls
            elif method in ('dynamic-cnf', 'grid-cnf'):
                ok, trail = solver.propagate(assumptions=alpha)
                forced = root | {l for l in trail if abs(l) in compiled.registry.by_id} if ok else set()
            else:
                ok, forced = solver.propagate(alpha)
            times.append(time.perf_counter()-start)
            results.append([ok, sorted(forced) if ok else []])
        if sat_backend:
            solver.delete()
        record.update(status='ok', complete_query_seconds=sum(times), query_times_seconds=times,
                      sat_calls=sat_calls, query_count=len(qs), sat_queries=sum(r[0] for r in results),
                      forced_counts=[len(r[1]) for r in results],
                      answers_sha256=hashlib.sha256(json.dumps(results).encode()).hexdigest(),
                      first_complete_total_seconds=compiled.stats['compile_seconds']+record['setup_seconds']+times[0])
    except (ResourceLimit, MemoryError) as exc:
        record.update(status='UNKNOWN', reason='memory_limit' if isinstance(exc, MemoryError) else str(exc))
    except Exception as exc:
        record.update(status='ERROR', reason=str(exc), traceback=traceback.format_exc())
    record.update(elapsed_seconds=time.perf_counter()-begin,
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    Path(dest).write_text(json.dumps(record, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default='results/construction/serial')
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--jobs', type=int, default=1)
    p.add_argument('--suite', choices=('main', 'final', 'frontier', 'frontier-small', 'frontier-scale', 'large', 'range', 'cnf'), default='main')
    p.add_argument('--root-policy', choices=('propagation', 'search'), default='propagation')
    p.add_argument('--worker'); p.add_argument('--record')
    a = p.parse_args()
    if a.worker:
        worker(json.loads(a.worker), a.record); return
    if a.suite == 'final':
        cases = [('producers', n, m) for n in (2, 4, 6, 8, 16, 32, 64, 128)
                 for m in ('dynamic', 'grid', 'order-sat')]
        cases += [('producers', n, 'co-first') for n in (2, 4, 6, 8)]
        cases += [('producers', n, 'unfold') for n in (2, 4, 6)]
    elif a.suite == 'main':
        cases = [('producers', n, m) for n in (2, 4, 6, 8) for m in ('dynamic', 'co-first', 'unfold', 'order-sat')]
        cases += [('producers', n, 'dynamic-cnf') for n in (2, 8, 32)]
    elif a.suite == 'cnf':
        cases = [('producers', n, m) for n in (8, 32, 128) for m in ('grid-cnf', 'dynamic-cnf')]
    elif a.suite == 'range':
        cases = [('producers', n, 'grid') for n in (2, 4, 6, 8, 16, 32, 64, 128)]
        cases += [('producers', n, 'grid-cnf') for n in (8, 32, 128)]
    elif a.suite == 'large':
        cases = [('producers', n, m) for n in (16, 32, 64, 128) for m in ('dynamic', 'order-sat')]
    elif a.suite == 'frontier-small':
        cases = [('producers', n, m) for n in (1, 2) for m in ('frontier', 'frontier-full', 'frontier-dfa')]
        cases += [('pipeline', 1, m) for m in ('frontier', 'frontier-full', 'frontier-dfa')]
    elif a.suite == 'frontier-scale':
        cases = [('pipeline', n, m) for n in (2, 3) for m in ('frontier', 'frontier-full', 'frontier-dfa')]
    else:
        cases = [('producers', n, m) for n in (1, 2) for m in ('frontier', 'frontier-full', 'frontier-dfa', 'dynamic')]
        cases += [('pipeline', n, m) for n in (1, 2, 3) for m in ('frontier', 'frontier-full', 'frontier-dfa')]
    specs = [dict(family=f, n=n, method=m, repeat=r, queries=64)
             for f, n, m in cases for r in range(a.repeats)]
    for spec in specs:
        spec['root_policy'] = a.root_policy
    random.Random(20261015).shuffle(specs)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cpu = min(os.sched_getaffinity(0))
    (out/'environment.json').write_text(json.dumps(dict(platform=platform.platform(), python=sys.version,
        jobs=a.jobs, isolated_timing=a.jobs == 1, cpu=cpu, memory_limit_gib=3, timeout_seconds=100,
        compile_limits=dict(seconds=60, states=100000, edges=300000), seed=20261015, suite=a.suite), indent=2))
    def run(j, spec):
        if a.jobs == 1:
            spec['cpu'] = cpu
        dest = out/f'{j:04d}.json'
        try:
            result = subprocess.run([sys.executable, __file__, '--worker', json.dumps(spec), '--record', str(dest)],
                                    timeout=100, capture_output=True, text=True)
            if result.returncode:
                record = json.loads(dest.read_text()) if dest.exists() else {'spec': spec}
                record.update(status='ERROR', process_returncode=result.returncode, stderr=result.stderr[-2000:])
                dest.write_text(json.dumps(record, indent=2))
        except subprocess.TimeoutExpired:
            record = json.loads(dest.read_text()) if dest.exists() else {'spec': spec}
            record.update(status='UNKNOWN', reason='wall_timeout_100s')
            dest.write_text(json.dumps(record, indent=2))
        record = json.loads(dest.read_text())
        print(j, record['status'], spec, flush=True)
        return record
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        records = [f.result() for f in as_completed([pool.submit(run, j, s) for j, s in enumerate(specs)])]
    seen = {}; mismatches = []
    for record in records:
        if record['status'] != 'ok':
            continue
        spec = record['spec']; key = (spec['family'], spec['n'], record['query_sha256'])
        if key in seen and seen[key] != record['answers_sha256']:
            mismatches.append(spec)
        seen[key] = record['answers_sha256']
    summary = dict(records=len(records), statuses={s: sum(r['status'] == s for r in records)
                    for s in sorted({r['status'] for r in records})}, mismatches=mismatches)
    (out/'summary.json').write_text(json.dumps(summary, indent=2))
    if mismatches or any(r['status'] == 'ERROR' for r in records):
        raise SystemExit('Experiment correctness/error audit failed')


if __name__ == '__main__':
    main()
