"""Separate RA entry point; preserves the legacy TSO command unchanged."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .model import Event
from .ra import RAInstance, producers, pipeline
from .ra_schedule import certificate, compile_schedule, OutsideCertificate
from .ra_frontier import compile_frontier
from .compiler import ResourceLimit
from .owned_dag import OwnedGraphSolver
from .ra_grid import compile_grid, GridSolver, grid_cnf
from .ra_publication import publication_exchange, publication_layout


def main():
    p = argparse.ArgumentParser(description='Fixed-event release/acquire support compiler')
    p.add_argument('--input', help='JSON with events, threads, initial fields')
    p.add_argument('--family', choices=('producers', 'pipeline', 'publication'), default='producers')
    p.add_argument('--size', type=int, default=4, help='Writes per producer or pipeline stages')
    p.add_argument('--algorithm', choices=('auto', 'grid', 'dynamic', 'frontier', 'frontier-direct', 'frontier-ports'), default='auto')
    p.add_argument('--seconds', type=float, default=60)
    p.add_argument('--source-covers', action='store_true', help='Infer common HB predecessors of ambiguous RF domains')
    p.add_argument('--rf-mode', choices=('binary', 'atomic'), default='binary', help='Process each RF bit or one complete source choice per read')
    p.add_argument('--states', type=int, default=100000)
    p.add_argument('--assume', type=int, nargs='*', default=[])
    p.add_argument('--dimacs'); p.add_argument('--export-instance'); p.add_argument('--registry')
    a = p.parse_args()
    if a.size < 1:
        p.error('size must be positive')
    if a.input:
        data = json.loads(Path(a.input).read_text())
        inst = RAInstance(tuple(Event(**e) for e in data['events']),
                          tuple(tuple(t) for t in data['threads']), tuple(data['initial']))
    else:
        inst = (producers((a.size, a.size)) if a.family == 'producers' else
                publication_exchange(a.size) if a.family == 'publication' else pipeline(a.size))
    if a.export_instance:
        Path(a.export_instance).write_text(json.dumps(asdict(inst), indent=2))
    method = a.algorithm
    if method == 'auto':
        try:
            writers, readers = certificate(inst)
            method = 'grid' if len(writers) == 2 and len(readers) == 1 else 'dynamic'
        except OutsideCertificate:
            method = 'frontier'
    try:
        if method == 'grid':
            c = compile_grid(inst, max_seconds=a.seconds, max_states=a.states)
        else:
            fn = compile_schedule if method == 'dynamic' else compile_frontier
            options = {}
            if method in ('frontier-direct', 'frontier-ports'):
                options.update(co_mode='direct',early_degrees=True)
            if method == 'frontier-ports':
                options['summary_mode'] = 'ports'
            if method.startswith('frontier'):
                options['source_covers'] = a.source_covers
                options['rf_mode'] = a.rf_mode
            if method.startswith('frontier') and not a.input and a.family == 'publication':
                options['order'] = publication_layout(inst, a.size)
            if method.startswith('frontier') and not a.input and a.family == 'pipeline':
                options['order'] = inst.initial+tuple(v for stage in range(1, a.size+1) for t in inst.threads
                                                      for v in t if v.split('_')[1] == str(stage))
            c = fn(inst, cnf=bool(a.dimacs), max_seconds=a.seconds, max_states=a.states, **options)
    except OutsideCertificate as exc:
        print(json.dumps(dict(status='OUTSIDE_CERTIFICATE', reason=str(exc)))); return
    except (ResourceLimit, MemoryError) as exc:
        result=dict(status='UNKNOWN',reason=str(exc) or 'memory_limit')
        if getattr(exc,'stats',None):result['construction_stats']=exc.stats
        print(json.dumps(result)); return
    if a.registry:
        Path(a.registry).write_text(json.dumps(c.registry.by_id, indent=2))
    if a.dimacs:
        encoded = grid_cnf(c) if method == 'grid' else c
        Path(a.dimacs).write_text(f'p cnf {encoded.nvars} {len(encoded.clauses)}\n'+
                                 ''.join(' '.join(map(str, row))+' 0\n' for row in encoded.clauses))
    if any(abs(l) not in c.registry.by_id for l in a.assume):
        p.error('Only original RF/CO literal IDs are accepted')
    solver = GridSolver(c) if method == 'grid' else OwnedGraphSolver(c)
    ok, forced = solver.propagate(a.assume)
    print(json.dumps(dict(status='SAT' if ok else 'UNSAT', algorithm=method,
        scope='Fixed atomic release/acquire events; no RMW, fences, SC, nonatomics or dynamic addresses',
        stats=c.stats, forced_original_literals=sorted(forced)), indent=2))


if __name__ == '__main__':
    main()
