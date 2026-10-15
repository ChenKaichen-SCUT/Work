# Bounded-interface weak-memory solver

Research implementation of a compiler from a restricted relational memory
theory and a certified event decomposition to exact history summaries and a
propagation encoding. The first semantic recognizer covers the alternating-flag
x86-TSO execution subclass described in `docs/proof_audit.txt`.

**This is a scoped research prototype, not a general x86 verifier or CAT compiler.**
The complete-propagation contract applies to original relation assumptions on
the accepted fixed event instance. It does not cover arbitrary auxiliary
decisions, dynamic addresses, RMWs, or general control-flow activation.

## Run

Python 3.10 or later:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m wmcheck --rounds 4
python -m wmcheck --rounds 2 --export-instance instance.json --dimacs memory.cnf
python -m unittest discover -s tests -v
```

For an arbitrary `--input` JSON, the supplied block order is part of the input
semantics. Merely placing a certificate name in its metadata does not prove
equivalence to unrestricted TSO. `wmcheck.recognize.recognize` checks the actual
protocol trace structure before applying the semantic reduction.

## What is implemented

- Typed `rf` filters (`all`, `ext`, `none`), per-address total `co`, and `fr`
  derived from the **full** `rf`, for multiple acyclicity graphs.
- Address output ports, live-source input ports, exact closure before projection,
  and merging of histories with identical interfaces.
- Reuse of transitions with identical bit-matrix templates, even after event
  renaming. This cache is exact and independent of SAT assumptions.
- Layered support CNF with complete original-variable propagation on the scoped
  input, plus a forward/backward reference propagator.
- One sufficient explanation per derived literal or conflict. A reversible
  Python session recomputes propagation after `push`/`pop`; it is **not** an
  optimized incremental trail engine. MiniSat supplies actual incremental SAT
  queries, learning and backtracking for the CNF backend.
- An independent full-graph oracle, a conventional binary-rank SAT encoding,
  no-history-merging and weak-propagation ablations.

The compiler enumerates choices **within each block**, then merges boundary
states. It does not enumerate complete histories for the bounded-block protocol
family. For single-block public litmus tests, the block is the entire small
test; those runs demonstrate semantics, not scalable history compression.

## Experiments

```sh
python experiments/validate.py
python validation/audit.py
python validation/tso_instance.py
python experiments/propagation_audit.py
python experiments/run_suite.py --out results/main --jobs 3 --repeats 3
python experiments/run_suite.py --mode serial --out results/serial --jobs 1 --repeats 3
python experiments/run_suite.py --mode cold_long --out results/cold_long --jobs 2 --repeats 1
python experiments/run_suite.py --mode unsat --out results/unsat --jobs 2 --repeats 3
python experiments/analyze.py --results results/main --out results/analysis
```

Optional plots require `requirements-plots.txt`; add `--plots` to the analyzer.
Raw per-run records include time, memory, SAT answers, assumptions, limits and
backend versions. Timeouts and resource limits remain in the data and are never
reported as UNSAT. `results/local_smoke` is development-only and is excluded
from the reported server comparisons.

The server uses separate directories for this project and downloaded baselines:

```text
wm-research/project/       this repository
wm-research/baselines/     external sources, excluded from publication
wm-research/runtime/       Python environment
wm-research/opam/          OCaml dependencies
```

`scripts/bootstrap.sh` installs dependencies on a dedicated Ubuntu machine;
`scripts/build_baselines.sh` builds Dartagnan or herd7. Baseline source revisions
used in the results are recorded in `results/public/coverage.json`. To reproduce
the exact experiment, check out those revisions before building. A Maven mirror
is configured in `scripts/maven-settings.xml`; it can be changed without changing
the algorithms.

```sh
python experiments/public_suite.py --root "$HOME/wm-research" --jobs 2
WM_RESEARCH_ROOT="$HOME/wm-research" python experiments/protocol_external.py
```

The strict X86 importer currently accepts MOV memory/immediate writes, MOV
register/memory reads, MFENCE, and positive existential conjunctions of final
read-register equalities. It rejects other syntax explicitly. Public benchmark
sources are **not** included; records contain their paths and content hashes.

## Read the results

`CONCLUSIONS.zh.txt` gives the measured conclusions and limitations in Chinese.
`docs/METHOD.md` specifies the implementation and experimental contracts.
`docs/proof_audit.txt` preserves the preceding proof draft; its historical audit
counts are separate from the new implementation tests. Neither is a
proof-assistant certification.

The authoritative serial confirmation is `results/serial_isolated`; an earlier
single-worker run in `results/serial` overlapped with separate experiment workers
and is retained only as supplementary data. The initial herd7 protocol runs that
enumerated all outcomes are preserved in
`results/protocol_external/full_enumeration_attempt.json`; the final run uses
herd7's documented `-speedcheck true` existence-query mode.

## Related tools

- [CAAT: Consistency as a Theory](https://doi.org/10.1145/3563292)
- [Dartagnan](https://github.com/hernanponcedeleon/Dat3M)
- [herdtools7](https://github.com/herd/herdtools7)
- [PySAT](https://pysathq.github.io/)

Generic memory-model solving, automaton support filtering, and SAT propagation
encodings are established techniques. The research question here is the
constructive, semantics-preserving `rf/co/fr` history interface and its scoped
completeness guarantee; the experimental results do not establish novelty.
