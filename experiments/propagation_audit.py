"""Measure forced-literal coverage against independently enumerated executions."""
import json
import argparse
from pathlib import Path
import random
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wmcheck.generators import make_instance
from wmcheck.compiler import compile_instance
from wmcheck.eager import encode
from wmcheck.oracle import enumerate_models,truth_under
from wmcheck.propagation import unit_propagate
from pysat.solvers import Minisat22
from wmcheck.graph_solver import GraphSolver

parser=argparse.ArgumentParser()
parser.add_argument('--out',default='results/propagation_audit.json')
args=parser.parse_args()

inst=make_instance(rounds=2);strong=compile_instance(inst);weak=compile_instance(inst,strong=False);eager=encode(inst)
models=list(enumerate_models(inst,strong.registry,dense_tso=True))
reg=strong.registry;free=[v for v,(k,a,b) in reg.by_id.items() if k=='co' or len(inst.candidates[b])>1]
rng=random.Random(20261015);alphas=[[]]
alphas += [[v*rng.choice((-1,1)) for v in free if rng.random()<.25] for _ in range(2000)]
truth=[truth_under(models,alpha) for alpha in alphas]
report={'seed':20261015,'events':len(inst.events),'oracle_legal_executions':len(models),
        'partial_assignments':len(alphas),'satisfiable_partials':sum(t[0] for t in truth),'methods':{}}
rootforced=truth_under(models,[])[1]
for name,enc in [('proposed',strong),('graph',strong),('weak',weak),('eager',eager)]:
    start=time.perf_counter();root=unit_propagate(enc.clauses)
    rootvalues={v if b else -v for v,b in root.values.items() if v in reg.by_id}
    counts={'conflicts_detected':0,'conflicts_missed':0,'wrong_conflicts':0,
            'required_nonroot_literal_occurrences':0,'derived_nonroot_literal_occurrences':0,'missed_literals':0,'wrong_literals':0}
    solver=GraphSolver(enc) if name=='graph' else Minisat22(bootstrap_with=enc.clauses)
    try:
        for alpha,(consistent,forced) in zip(alphas,truth):
            ok,prop=solver.propagate(assumptions=alpha)
            if not consistent:
                counts['conflicts_detected' if not ok else 'conflicts_missed']+=1;continue
            if not ok: counts['wrong_conflicts']+=1;continue
            got={l for l in prop if abs(l) in reg.by_id}|rootvalues
            relevant=forced-set(alpha)-rootforced
            counts['required_nonroot_literal_occurrences']+=len(relevant)
            counts['derived_nonroot_literal_occurrences']+=len(got&relevant)
            counts['missed_literals']+=len(relevant-got)
            counts['wrong_literals']+=len(got-forced)
    finally:
        if name!='graph': solver.delete()
    counts['seconds']=time.perf_counter()-start;report['methods'][name]=counts
assert report['methods']['proposed']['conflicts_missed']==report['methods']['proposed']['missed_literals']==0
assert report['methods']['graph']['conflicts_missed']==report['methods']['graph']['missed_literals']==0
assert all(r['wrong_conflicts']==r['wrong_literals']==0 for r in report['methods'].values())
Path(args.out).parent.mkdir(parents=True,exist_ok=True)
Path(args.out).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
