"""Recheck new encodings against archived third-party results, without rerunning tools."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.litmus import parse_x86
from wmcheck.compiler import compile_instance
from wmcheck.graph_solver import GraphSolver
from pysat.solvers import Minisat22
dat=Path(sys.argv[1]);records=[]
manifest=json.loads((ROOT/'results/public/coverage.json').read_text())['manifest']
hashes={m['path']:m['sha256'] for m in manifest}
for p in sorted((ROOT/'results/public').glob('[0-9][0-9][0-9].json')):
    old=json.loads(p.read_text());path=old['path'];source=(dat/path).read_text()
    assert hashlib.sha256(source.encode()).hexdigest()==hashes[path]
    inst=parse_x86(source,Path(path).stem);enc=compile_instance(inst,max_seconds=30)
    graph=GraphSolver(enc).propagate()[0]
    with Minisat22(bootstrap_with=enc.clauses) as solver: cnf=solver.solve()
    previous={m:old[m]['sat'] for m in ('herd7','dartagnan_lazy','dartagnan_eager')}
    assert all(s==graph==cnf for s in previous.values()),path
    records.append({'path':path,'source_sha256':hashes[path],'graph':graph,'cnf':cnf,'archived_external':previous})
out=ROOT/'results/gap/public_regression.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'tests':len(records),'mismatches':0,
    'reference':'Archived third-party runs in results/public; external tools were not rerun for this regression.',
    'records':records},indent=2))
