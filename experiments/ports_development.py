"""Limited development validation on existing cases, not a new paper campaign."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2)+'\n', encoding='utf8')


def worker(n, mode, out):
    import resource
    from wmcheck.ra import pipeline
    from wmcheck.ra_frontier import compile_frontier
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.compiler import ResourceLimit
    from experiments.paper_cases import layout
    resource.setrlimit(resource.RLIMIT_AS, (4*1024**3,)*2)
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    r = dict(status='running', purpose='development validation; n=1, not final performance estimate',
             pipeline_stages=n, mode=mode)
    save(out, r)
    try:
        inst = pipeline(n)
        c = compile_frontier(inst, order=layout(inst, {'family': 'pipeline', 'n': n}),
            co_mode='direct', summary_mode=mode, early_degrees=True,
            max_states=200000, max_edges=600000, max_seconds=120)
        r['stats'] = c.stats
        qs = json.loads((ROOT/'results/paper/inputs'/f'c{10+n:03d}_queries.json').read_text())
        r['query_sha256'] = hashlib.sha256(json.dumps(qs).encode()).hexdigest()
        start = time.perf_counter(); engine = OwnedGraphSolver(c)
        r['setup_seconds'] = time.perf_counter()-start
        answers, timings = [], []
        for alpha in qs:
            start = time.perf_counter(); ok, forced = engine.propagate(alpha)
            timings.append(time.perf_counter()-start)
            answers.append(hashlib.sha256(json.dumps([ok, sorted(forced) if ok else []]).encode()).hexdigest())
        r.update(status='ok', answer_hashes=answers, query_times=timings)
    except (ResourceLimit, MemoryError) as exc:
        r.update(status='UNKNOWN', reason=str(exc), failure_stats=getattr(exc, 'stats', {}))
    r['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    save(out, r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default='results/ports_development')
    p.add_argument('--worker', nargs=2)
    p.add_argument('--record')
    a = p.parse_args()
    if a.worker:
        worker(int(a.worker[0]), a.worker[1], a.record); return
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    save(out/'environment.json', dict(platform=platform.platform(), python=sys.version,
        repeats=1, purpose='development correctness and construction-size validation only',
        serial=True, cpu=min(os.sched_getaffinity(0)), memory_gib=4, process_seconds=180,
        source_sha256={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
                       for d in ('wmcheck', 'tests') for f in (ROOT/d).glob('*.py')}))
    comparison = []
    for n in (1, 2, 3):
        pair = {}
        for mode in ('full', 'ports'):
            path = out/f'pipeline_{n}_{mode}.json'
            subprocess.run([sys.executable, __file__, '--worker', str(n), mode, '--record', str(path)],
                           check=True, timeout=180)
            pair[mode] = json.loads(path.read_text())
        x, y = pair['full'], pair['ports']
        if x['status'] != 'ok' or y['status'] != 'ok':
            comparison.append(dict(stages=n, status='incomplete', methods={k:v['status'] for k,v in pair.items()}))
            continue
        same = x['query_sha256'] == y['query_sha256'] and x['answer_hashes'] == y['answer_hashes']
        a_states, b_states = x['stats']['layer_states'], y['stats']['layer_states']
        coarser = len(a_states) == len(b_states) and all(a >= b for a, b in zip(a_states, b_states))
        if not same or not coarser:
            raise AssertionError('Projection or quotient regression')
        row = dict(stages=n, status='ok', exact_query_agreement=same, compared_queries=len(x['answer_hashes']),
                   layerwise_no_more_states=coarser,
                   old_states=x['stats']['states'], new_states=y['stats']['states'],
                   old_attempts=x['stats']['attempted_transitions'], new_attempts=y['stats']['attempted_transitions'],
                   old_compile_seconds=x['stats']['compile_seconds'], new_compile_seconds=y['stats']['compile_seconds'])
        comparison.append(row); print(json.dumps(row), flush=True)
    save(out/'comparison.json', comparison)


if __name__ == '__main__':
    main()
