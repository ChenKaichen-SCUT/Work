import argparse
import json
from pathlib import Path
from .generators import make_instance
from .model import Instance
from .compiler import compile_instance,ResourceLimit
from .propagation import unit_propagate

def main():
    p=argparse.ArgumentParser(description='Certified-block weak-memory research solver')
    p.add_argument('--rounds',type=int,default=2);p.add_argument('--threads',type=int,default=4)
    p.add_argument('--input',help='Generic block-model JSON; supplied block order is part of its semantics')
    p.add_argument('--export-instance');p.add_argument('--dimacs');p.add_argument('--assume',type=int,nargs='*',default=[])
    a=p.parse_args()
    inst=Instance.from_dict(json.loads(Path(a.input).read_text())) if a.input else make_instance(rounds=a.rounds,threads=a.threads)
    if a.export_instance: Path(a.export_instance).write_text(json.dumps(inst.to_dict(),indent=2))
    try: c=compile_instance(inst)
    except ResourceLimit as exc:
        print(json.dumps({'status':'UNKNOWN','reason':str(exc)}));return
    if any(abs(l) not in c.registry.by_id for l in a.assume): p.error('assumptions must refer to original variables')
    if a.dimacs:
        Path(a.dimacs).write_text(f'p cnf {c.nvars} {len(c.clauses)}\n'+''.join(' '.join(map(str,x))+' 0\n' for x in c.clauses))
    r=unit_propagate(c.clauses,a.assume)
    result={'status':'SAT' if r.consistent else 'UNSAT','scope':inst.metadata.get('scope','User-supplied block-order semantics'),
            'stats':c.stats,'forced_original_literals':[v if b else -v for v,b in r.values.items() if v in c.registry.by_id]}
    if not r.consistent: result['conflict_assumptions']=r.explanation()
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
