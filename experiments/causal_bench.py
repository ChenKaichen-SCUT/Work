"""Isolated, resource-bounded comparisons for the frozen causal-frontier pilot.

No result from a killed process is interpreted as UNSAT. Raw rows and complete
query sequences are retained. Run --help for the controller and worker options.
"""
import argparse
import dataclasses
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serial(value):
    if dataclasses.is_dataclass(value):
        return serial(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(serial(v) for v in value)
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(serial(value), ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(serial(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def object_bytes(value, seen=None):
    """Python object estimate, not a replacement for full process RSS."""
    seen = set() if seen is None else seen
    key = id(value)
    if key in seen:
        return 0
    seen.add(key)
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        return total + sum(object_bytes(k, seen) + object_bytes(v, seen) for k, v in value.items())
    if isinstance(value, (tuple, list, set, frozenset)):
        return total + sum(object_bytes(v, seen) for v in value)
    if hasattr(value, '__dict__'):
        return total + object_bytes(vars(value), seen)
    return total


def workload(inst, count, seed=0):
    """Same explicit original assumptions for B0/B1/B2, no chosen model input."""
    from wmcheck.ra import RARegistry
    reg = RARegistry(inst)
    rounds = sorted(int(e.split('_')[1]) for e in inst.event if e.startswith('w1_') and e.endswith('_ar'))
    if not rounds or any(inst.event.get(f'w2_{i}_bx') is None or
                         inst.event[f'w2_{i}_bx'].kind != 'W' for i in rounds):
        values = list(reg.by_id)
        return [dict(name='root', assumptions=[], target=values[0] if values else None)] * count
    first, last = rounds[0], rounds[-1]
    def triple(i):
        remote = reg.literal(('rf', f'w2_{i}_bx', f'w1_{i}_ar'))
        local = reg.literal(('rf', f'w1_{i}_ax', f'w1_{i}_ar'))
        co = reg.literal(('co', f'w1_{i}_ax', f'w2_{i}_bx'))
        assert all(type(v) is int and v for v in (remote, local, co))
        return remote, local, co
    r, l, c = triple(first)
    rr, ll, cc = triple(last)
    blocks = [
        ('root', [], r), ('remote_source', [r], -c),
        ('correlated_conflict', [r, -c], l), ('rollback', [r], c),
        ('retired_co_query', [], -c), ('other_source', [l, -c], r),
        ('deep_branch', list(dict.fromkeys([l, rr])), c),
        ('deep_conflict', list(dict.fromkeys([l, rr, -cc])), -c),
        ('restore_root', [], rr), ('co_to_source', [-c], r),
    ]
    rng = random.Random(seed)
    result = []
    for j in range(count):
        name, alpha, target = blocks[j % len(blocks)]
        if j >= len(blocks) and j % len(blocks) in (1, 2, 3):
            i = rng.choice(rounds)
            ri, li, ci = triple(i)
            alpha = [ri, -ci] if j % len(blocks) == 2 else [ri]
            target = ci
        result.append(dict(name=name, assumptions=alpha, target=target))
    return result


def ambiguity(reg, supports):
    by_read = {}
    co = 0
    for v, (kind, a, b) in reg.by_id.items():
        if kind == 'rf' and v in supports:
            by_read.setdefault(b, []).append(a)
        if kind == 'co' and v in supports and -v in supports:
            co += 1
    return dict(u_RF=sum(len(ws) >= 2 for ws in by_read.values()), u_CO=co)


def worker(args):
    import psutil
    from wmcheck.ra import RARegistry
    from wmcheck.ra_protocols import barrier_instance, build_protocol, replay_certificate
    from wmcheck.ra_frontier import prepare_frontier, compile_frontier
    from wmcheck.ra_support_sat import SupportSAT
    from wmcheck.owned_dag import OwnedGraphSolver
    from wmcheck.compiler import ResourceLimit
    proc = psutil.Process()
    eligible = proc.cpu_affinity()
    if eligible:
        proc.cpu_affinity([min(eligible)])
    row = dict(status='RUNNING', method=args.method, rounds=args.rounds, failures=args.failures,
               long_gap=args.long_gap, layout=args.layout, task=args.task, repeat=args.repeat,
               dense_co=args.dense_co,
               limits=dict(seconds=args.seconds, memory_mib=args.memory_mib,
                           states=args.states, edges=args.edges), seed=0,
               affinity=proc.cpu_affinity(), phase='input', queries=[])
    save(args.out, row)
    start = time.perf_counter()
    solver = None
    try:
        tick = time.perf_counter()
        inp = barrier_instance(args.rounds, workers=2, failures=args.failures,
                               data=True, long_gap=args.long_gap)
        reg = RARegistry(inp.inst)
        queries = workload(inp.inst, args.queries)
        row.update(input_seconds=time.perf_counter()-tick, events=len(inp.inst.events),
                   original_variables=reg.nvars, input_sha256=digest(inp),
                   workload_sha256=digest(queries), phase='certificate')
        input_dir = Path(args.out).parent.parent / 'inputs'
        save(input_dir / f'barrier_n{args.rounds}_f{args.failures}_g{int(args.long_gap)}.json', inp)
        save(Path(args.out).with_suffix('.queries.json'), queries)
        save(args.out, row)
        pre = None
        tick = time.perf_counter()
        if args.method != 'B0':
            pre = build_protocol(inp)
            row['preprocessing'] = pre.get('metrics', {})
            row['pre_status'] = pre['status']
            if pre['status'] == 'OUTSIDE':
                row.update(status='OUTSIDE', reason=pre.get('reason'))
                return
        row['certificate_seconds'] = time.perf_counter()-tick
        tick = time.perf_counter()
        if pre is not None:
            assert replay_certificate(inp, pre)
        row['certificate_check_seconds'] = time.perf_counter()-tick
        row['phase'] = 'encoding' if args.method != 'B2' else 'plan'
        save(args.out, row)
        tick = time.perf_counter()
        plan = compiled = engine = None
        if args.method == 'B2':
            order = pre['order'] if args.layout == 'special' else tuple(e.id for e in inp.inst.events)
            plan = prepare_frontier(inp.inst, certificate=pre['certificate'], order=order,
                                    co_mode='direct', summary_mode='ports', early_degrees=True,
                                    dense_co_generators=args.dense_co)
            row['plan_seconds'] = time.perf_counter()-tick
            row['plan_stats'] = plan.stats
            row['phase'] = 'compile'
            save(args.out, row)
            tick = time.perf_counter()
            compiled = compile_frontier(inp.inst, prepared=plan, max_states=args.states,
                                        max_edges=args.edges, max_seconds=args.seconds)
            row['compile_seconds'] = time.perf_counter()-tick
            row['compile_stats'] = compiled.stats
            tick = time.perf_counter()
            engine = OwnedGraphSolver(compiled)
            row['query_index_seconds'] = time.perf_counter()-tick
        else:
            solver = SupportSAT(inp, certificate=None if pre is None else pre['certificate'], solver='cadical195')
            row['encoding_seconds'] = time.perf_counter()-tick
            row['sat_stats'] = solver.stats
        row['cold_seconds'] = sum(row.get(key, 0.0) for key in (
            'input_seconds', 'certificate_seconds', 'certificate_check_seconds',
            'plan_seconds', 'compile_seconds', 'query_index_seconds', 'encoding_seconds'))
        row['cold_wall_including_audit_io_seconds'] = time.perf_counter()-start
        row['phase'] = 'queries'
        save(args.out, row)
        for j, q in enumerate(queries):
            alpha, target = q['assumptions'], q['target']
            tick = time.perf_counter()
            if args.method == 'B2':
                if args.task == 'all':
                    ok, forced = engine.propagate(alpha)
                    supports = {l for v in reg.by_id for l in (v, -v) if -l not in forced} if ok else set()
                    answer = [ok, sorted(supports)]
                else:
                    use = alpha + ([target] if args.task == 'single' and target is not None else [])
                    ok = engine.witness(use) is not None
                    answer = [ok]
            else:
                if args.task == 'all':
                    ok, supports = solver.all_support(alpha)
                    answer = [ok, sorted(supports)]
                else:
                    ok = solver.solve(alpha + ([target] if args.task == 'single' and target is not None else []))
                    answer = [ok]
            elapsed = time.perf_counter()-tick
            item = dict(index=j, name=q['name'], seconds=elapsed, sat=ok, answer_sha256=digest(answer))
            if solver is not None:
                item['sat_calls'] = solver.last_query_stats.get('calls', solver.last_query_stats.get('sat_calls'))
            row['queries'].append(item)
            if args.task == 'all' and j == 0:
                row['ambiguity'] = ambiguity(reg, supports)
            if j in (0, 9, 99, 999):
                save(args.out, row)
        row['query_seconds'] = sum(q['seconds'] for q in row['queries'])
        row['cumulative_seconds'] = {str(q): row['cold_seconds'] + sum(v['seconds'] for v in row['queries'][:q])
                                     for q in (1, 10, 100, 1000) if q <= len(row['queries'])}
        row['algorithm_peak_wset_before_accounting_bytes'] = getattr(proc.memory_info(), 'peak_wset', proc.memory_info().rss)
        row['phase'] = 'memory-accounting'
        save(args.out, row)
        seen = set()
        row['python_object_bytes'] = {'input_and_registry': object_bytes((inp, reg), seen)}
        if pre is not None:
            row['python_object_bytes']['certificate'] = object_bytes(pre, seen)
        if plan is not None:
            row['python_object_bytes']['plan'] = object_bytes(plan, seen)
            row['python_object_bytes']['compiled_graph'] = object_bytes(compiled, seen)
            row['python_object_bytes']['query_index'] = object_bytes(engine, seen)
        row.update(status='OK', phase='done')
    except ResourceLimit as exc:
        partial = getattr(exc, 'stats', {})
        resource = partial.get('resource_reason', 'TIME_LIMIT' if 'time' in str(exc).lower() else 'STATE_LIMIT')
        row.update(status='TIMEOUT' if resource == 'TIME_LIMIT' else resource,
                   reason=str(exc), partial_stats=partial)
    except Exception:
        row.update(status='ERROR', traceback=traceback.format_exc())
    finally:
        if solver is not None:
            solver.close()
        row['worker_wall_seconds'] = time.perf_counter()-start
        mem = proc.memory_info()
        row['worker_peak_wset_bytes'] = getattr(mem, 'peak_wset', mem.rss)
        save(args.out, row)


def run_one(config, out, *, seconds=45, memory_mib=1024, queries=100, states=200000, edges=600000):
    import psutil
    cmd = [sys.executable, str(Path(__file__).resolve()), '--worker', '--out', str(out),
           '--seconds', str(seconds), '--memory-mib', str(memory_mib), '--queries', str(queries),
           '--states', str(states), '--edges', str(edges)]
    for k, v in config.items():
        if isinstance(v, bool):
            if v:
                cmd.append('--' + k.replace('_', '-'))
        else:
            cmd += ['--' + k.replace('_', '-'), str(v)]
    env = dict(os.environ, PYTHONHASHSEED='0', WMCHECK_NATIVE_PORTS='0', OMP_NUM_THREADS='1')
    began = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    peak = 0
    reason = None
    while p.poll() is None:
        try:
            rss = psutil.Process(p.pid).memory_info().rss
            peak = max(peak, rss)
            if rss > memory_mib * 1024**2:
                reason = 'MEMORY_LIMIT'
            elif time.perf_counter()-began > seconds:
                reason = 'TIMEOUT'
            if reason:
                p.kill()
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(.01)
    stdout, stderr = p.communicate()
    row = json.loads(Path(out).read_text(encoding='utf8')) if Path(out).exists() else dict(config)
    row.update(controller_seconds=time.perf_counter()-began, peak_rss_sampled_bytes=peak,
               exit_code=p.returncode, command=cmd)
    if reason:
        row.update(status=reason, reason='controller hard resource limit')
    elif p.returncode and row.get('status') != 'ERROR':
        row.update(status='ERROR', reason='worker exited unexpectedly')
    if stdout:
        row['stdout'] = stdout.decode('utf8', errors='replace')
    if stderr:
        row['stderr'] = stderr.decode('utf8', errors='replace')
    save(out, row)
    print(Path(out).name, row['status'], row.get('cold_seconds'), row.get('query_seconds'), flush=True)
    return row


def summarize(folder):
    rows = []
    for p in sorted((Path(folder) / 'runs').glob('*.json')):
        if p.name.endswith('.queries.json'):
            continue
        row = json.loads(p.read_text(encoding='utf8'))
        row['file'] = p.name
        rows.append(row)
    discrepancies = []
    by_input = {}
    for row in rows:
        if row['status'] != 'OK':
            continue
        key = (row['input_sha256'], row['workload_sha256'], row['task'])
        answers = [v['answer_sha256'] for v in row['queries']]
        if key in by_input and by_input[key][1] != answers:
            discrepancies.append([by_input[key][0], row['file']])
        else:
            by_input[key] = (row['file'], answers)
    result = dict(rows=rows, answer_discrepancies=discrepancies,
                  counts={s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})})
    save(Path(folder) / 'summary.json', result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--worker', action='store_true')
    p.add_argument('--out', required=True)
    p.add_argument('--method', choices=['B0', 'B1', 'B2'], default='B2')
    p.add_argument('--rounds', type=int, default=2)
    p.add_argument('--failures', type=int, default=0)
    p.add_argument('--long-gap', action='store_true')
    p.add_argument('--dense-co', action='store_true')
    p.add_argument('--layout', choices=['special', 'ordinary'], default='special')
    p.add_argument('--task', choices=['sat', 'single', 'all'], default='all')
    p.add_argument('--repeat', type=int, default=0)
    p.add_argument('--seconds', type=float, default=45)
    p.add_argument('--memory-mib', type=int, default=1024)
    p.add_argument('--queries', type=int, default=100)
    p.add_argument('--states', type=int, default=200000)
    p.add_argument('--edges', type=int, default=600000)
    a = p.parse_args()
    if a.worker:
        worker(a)
    else:
        config = {k: getattr(a, k) for k in ('method', 'rounds', 'failures', 'long_gap', 'dense_co', 'layout', 'task', 'repeat')}
        run_one(config, a.out, seconds=a.seconds, memory_mib=a.memory_mib,
                queries=a.queries, states=a.states, edges=a.edges)


if __name__ == '__main__':
    main()
