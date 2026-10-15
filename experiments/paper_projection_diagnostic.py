"""Independent small-instance projection counts, used only to audit blow-up.

This enumerates SAT models for diagnostics. It is never called by a proposed
compiler, query engine, or headline performance benchmark.
"""
import json,time
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import pipeline
from wmcheck.ra_sat import encode_ra
from pysat.solvers import Minisat22


def main():
    rows=[]
    for n in (1,2,3):
        enc=encode_ra(pipeline(n));start=time.perf_counter();count=0;complete=False
        with Minisat22(bootstrap_with=enc.clauses) as s:
            while time.perf_counter()-start<30 and count<100000:
                if not s.solve():complete=True;break
                model={abs(l):l for l in s.get_model()}
                s.add_clause([-model[v] for v in enc.registry.by_id]);count+=1
        rows.append(dict(phases=n,original_variables=enc.registry.nvars,original_projections=count,complete=complete,
            diagnostic_seconds=time.perf_counter()-start,
            trie_upper_bound=1+enc.registry.nvars*count if complete else None))
    out=Path('results/paper/provenance');out.mkdir(parents=True,exist_ok=True)
    (out/'projection_diagnostic.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows))


if __name__=='__main__':main()
