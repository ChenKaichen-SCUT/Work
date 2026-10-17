# Bounded-interface weak-memory solver

**2026-10-17 server backup:** [Chinese recovery guide](SERVER_RECOVERY.zh.txt)
provides fresh-machine setup, full experiment checks, pinned upstream tools,
and restoration of all 6,929 archived research files. The [Chinese manuscript](artifacts/FM_Chinese_Manuscript.pdf)
and [editable sources](fm_chinese_paper/) are included.

Research implementation of a compiler from a restricted relational memory
theory and a certified event decomposition to exact history summaries and a
propagation encoding. The first semantic recognizer covers the alternating-flag
x86-TSO execution subclass described in `docs/proof_audit.txt`.

**This is a scoped research prototype, not a general x86 verifier or CAT compiler.**
The complete-propagation contract applies to original relation assumptions on
the accepted fixed event instance. It does not cover arbitrary auxiliary
decisions, dynamic addresses, RMWs, or general control-flow activation.

The latest [FM preparation evidence](FM_READINESS_RESULTS.zh.txt) adds an
[adversarial proof audit](docs/FM_PROOF_AUDIT.zh.txt), three/four-worker directed
rings, and an independent incidence-based RA encoding with CaDiCaL. At 32 rounds,
53 scenarios and 826 selected literal supports agree with the graph; 81 complete
witnesses are independently checked. This is selected-query evidence, not a full
support audit at that size. A three-worker four-round construction failure is
retained. The [artifact guide](docs/FM_ARTIFACT.zh.txt) provides portable quick
checks and bounded Linux reproduction; the [manuscript plan](docs/FM_MANUSCRIPT_PLAN.zh.txt)
separates the central theorem from existing compilation machinery.

The preceding [support-task delivery](SUPPORT_TASK_RESULTS.zh.txt) connects the
publication theorem to incomplete provenance-log diagnosis and all single-field
repairs. It includes a [native Dat3M analysis audit](docs/CLOSEST_ANALYSIS_AUDIT.zh.txt),
[proof addendum](docs/SUPPORT_TASK_THEOREM_ADDENDUM.zh.txt), and
[frozen measurements](results/support_task_20261016/summary.json). Version-tagged
payloads complete 32 rounds with three repeats and a separate 64-round stress
point; constant payloads still fail at six rounds. These are controlled protocol
kernels, not industrial traces or a general performance claim.

Run a small diagnosis with `python -m wmcheck.trace_cli --publication 2 --payload epoch`.
For an independent fixed RA JSON, use `--input fixed_ra.json --log observations.json`,
where observations is a list of original RF/CO literal IDs. The optional Linux
accelerator builds with `python experiments/build_port_native.py`; enable it with
`WMCHECK_NATIVE_PORTS=1`. Without the extension the same semantics run in Python.
The measured source snapshot, full-support checks, task-specific SAT comparator,
resource failures, and reproduction commands are documented in the latest report.

The [novelty audit](docs/NOVELTY_AUDIT.zh.txt) compares the current claims with
primary literature through 2026-10-15. The [theory agenda](docs/THEORY_AGENDA.zh.txt)
separates established generic machinery from open targets and records subsequent
proof progress. The new [relational forgetting proof](docs/RELATIONAL_FORGETTING_THEOREMS.zh.txt)
constructs summaries for regular relation constraints and certified sparse final
CO successors. The [RC11 release/acquire instance and lower bound](docs/RA_PIPELINE_PROOF.zh.txt)
prove a finite-value pipeline instance with unresolved cross-phase CO and a
necessary boundary for deterministic history summaries. These are mathematical
proof drafts, not proof-assistant certifications. The subsequent RA implementation
is documented in [construction algorithms](docs/CONSTRUCTION_ALGORITHMS.zh.txt).

The subsequent [relational recognition theorem](docs/RELATIONAL_RECOGNITION.zh.txt)
replaces the fixed protocol template with a checkable relation kernel, causal
separation and write-coverage conditions, including arbitrary strongly connected
synchronization networks. The [bounded-history comparison](docs/BOUNDED_HISTORY_COMPARISON.zh.txt)
also proves that the same RA family has exponentially many states at a fixed
CO-first cut but a polynomial exact support graph under a different decision
schedule. [Theory delivery](docs/THEORY_DELIVERY.zh.txt) states the precise
algorithm contract and remaining scope limits. Earlier TSO experiments retain
their original scope; new RA experiments are recorded separately below.

## RA construction algorithms

The earlier [paper evaluation report](PAPER_RESULTS.zh.txt) and
[reproduction guide](docs/PAPER_REPRODUCE.zh.txt) retain their frozen comparison.
They add stronger complete SAT and symbolic BDD baselines, native GenMC/
Dartagnan/Poct checks, and the direct-CO construction improvement. Earlier
speed ratios against the original SAT baseline are historical measurements;
they must not be carried forward as claims against the strengthened baseline.

The subsequent [future-port algorithm and proof](docs/FUTURE_PORT_THEOREMS.zh.txt)
refine the general RA summary to future incoming/outgoing product ports, while
preserving exactly-one-mark conflict paths and original RF/CO support. Its
[development validation](results/ports_development/comparison.json) is separate
from the frozen paper campaign; single development timings are not final speed
estimates. [When compilation pays off](docs/COMPILATION_ECONOMICS.zh.txt) analyses
every measured query prefix in the existing data without assuming amortization.
The [certificate-to-port bridge](docs/FUTURE_PORT_CERTIFICATE_BRIDGE.zh.txt)
shows how the existing relation certificates also bound the direct-CO port
construction, while keeping this corollary separate from novelty claims.

The [publication core theorem](docs/PUBLICATION_CORE_THEOREM.zh.txt) derives
bounded candidate interfaces from synchronization with unresolved source
identities. Its executable publication family keeps competing payload writes
and source-sensitive CO queries. The [focused results](PUBLICATION_RESULTS.zh.txt)
include five-repeat SAT/BDD comparisons, independent witnesses, GenMC outcome
checks, and construction failures. The optional `--source-covers` recognizer
infers common HB predecessors without fixing an individual RF source; defaults
and the frozen earlier campaigns remain unchanged.

The expanded paper evaluation uses `experiments/paper_suite.py`,
`paper_external.py`, `paper_bdd_direct.py`, `paper_poct.py`, and `paper_stress.py`.
Its [protocol](docs/PAPER_EXPERIMENT_PROTOCOL.zh.txt) separates the general RA
frontier F, the certified single-address specialization D, and range labels G.
The [adapter proofs](docs/PAPER_EVALUATION_PROOFS.zh.txt) state exactly which
observable tasks are shared with native tools. Install `requirements-paper.txt`
for this Linux experiment harness. Downloaded external baselines are excluded
from the repository.

[Construction results](CONSTRUCTION_RESULTS.zh.txt) preserve the earlier server runs.
The separate RA entry point supports fixed atomic release/acquire events, with
no RMW, fences, SC operations, nonatomics or dynamic addresses:

```sh
python -m wmcheck.ra_cli --family producers --size 32
python -m wmcheck.ra_cli --family producers --size 32 --dimacs ra.cnf --registry variables.json
python -m wmcheck.ra_cli --family pipeline --size 1
python -m wmcheck.ra_cli --family pipeline --size 2 --algorithm frontier-direct
python -m wmcheck.ra_cli --family pipeline --size 3 --algorithm frontier-ports
python -m wmcheck.ra_cli --family publication --size 2 --algorithm frontier-ports --source-covers
python -m wmcheck.ra_cli --input ra-instance.json --algorithm frontier
```

- A checked pure producer/reader structure selects a dynamic ownership DAG,
  generated directly without enumerating complete histories. Two producers and
  one reader thread additionally use range labels; with a fixed number of reads,
  construction, storage, support CNF and complete queries are quadratic in the
  number of writes. Other pure configurations use explicit dynamic labels.
- The general fixed-event RA backend selects one final RF/CO-successor candidate
  at a time, maintains joint regular-relation product summaries, and forgets only
  after all candidate incident edges have been processed. The implementation
  includes the permanent relation recognizer and ordered-source-chain rule.
- Incremental transitive closure and paired rotation acceptance reduce product
  matrix costs. They preserve exact common-witness semantics; the backend still
  has potentially exponential state growth and explicit resource limits.
- `--algorithm frontier-direct` uses original CO directions as closure
  generators, avoiding separate final-successor guesses. Its equivalence proof
  and post-diagnosis comparisons are kept separate from the frozen main run.
- `--algorithm frontier-ports` projects the direct-CO summaries to future edge
  targets and sources. It merges histories during construction and retains
  joint ordinary/one-mark paths; it does not enumerate complete assignments.
- All original RF/CO bits remain queryable, including recognized constants.
  Unsupported specialization is `OUTSIDE_CERTIFICATE`; resource exhaustion is
  `UNKNOWN`. Completed graphs return all forced original literals without
  completion search. Neither branch is a general RC11/CAT implementation.

New tests use an independent dense RA oracle, exhaustive small partial
assignments, source/value variants and an RA-valid non-SC execution. The SAT
comparison exploits the same producer structure and answers complete queries
by incremental countermodel search, rather than comparing only raw SAT UP.

```sh
python experiments/construction_validate.py
python experiments/construction_suite.py --suite final --out results/construction/final
python experiments/construction_suite.py --suite cnf --out results/construction/cnf_final
python experiments/construction_suite.py --suite frontier-small --out results/construction/frontier_final
python experiments/construction_suite.py --suite frontier-scale --repeats 1 --jobs 2 --out results/construction/frontier_scale
python experiments/construction_analyze.py
```

Final timing campaigns use isolated processes, one pinned worker and three
repetitions; parallel frontier probes are reported separately. They follow a
cost audit removing linear membership lookups from shared variable access and
gate construction. Initial campaigns remain as exploratory raw records, not
final performance evidence. Initial CNF runs also used unnecessary root search;
the final CNF campaign uses exact support propagation, charged to setup, before
native unit-propagation queries. Original-variable UP completeness is separately
checked using the pure unit-propagation reference implementation.

## Run the legacy TSO entry point

Python 3.10 or later:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m wmcheck --rounds 4
python -m wmcheck --rounds 4 --backend cnf
python -m wmcheck --rounds 2 --export-instance instance.json --dimacs memory.cnf
python -m unittest discover -s tests -v
```

For an arbitrary `--input` JSON, the supplied block order is part of the input
semantics. Merely placing a certificate name in its metadata does not prove
equivalence to unrestricted TSO. `wmcheck.recognize.recognize` checks the actual
protocol trace structure before applying the semantic reduction.

## Legacy TSO implementation

- Typed `rf` filters (`all`, `ext`, `none`), per-address total `co`, and `fr`
  derived from the **full** `rf`, for multiple acyclicity graphs.
- Address output ports, live-source input ports, exact closure before projection,
  and merging of histories with identical interfaces.
- Reuse of transitions with identical bit-matrix templates, even after event
  renaming. This cache is exact and independent of SAT assumptions.
- Layered support CNF with complete original-variable propagation on the scoped
  input, plus a forward/backward reference propagator.
- Directional entry-to-exit history kernels, exact backward suffix-language
  minimization, and shared label tests in the support CNF. These preserve the
  original-variable completeness contract; see `docs/optimization_proofs.txt`.
- A direct graph backend (the CLI default) returns conflicts and all forced
  original literals without constructing SAT auxiliaries. It reuses its index
  but recomputes reachability per query; it is not a general Boolean solver.
- One sufficient explanation per derived literal or conflict. A reversible
  Python session recomputes propagation after `push`/`pop`; it is **not** an
  optimized incremental trail engine. MiniSat supplies actual incremental SAT
  queries, learning and backtracking for the CNF backend.
- An independent full-graph oracle, a conventional binary-rank SAT encoding,
  no-history-merging and weak-propagation ablations.

The legacy compiler enumerates choices **within each block**, then merges boundary
states. It does not enumerate complete histories for the bounded-block protocol
family. For single-block public litmus tests, the block is the entire small
test; those runs demonstrate semantics, not scalable history compression.

## Legacy TSO experiments

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

The follow-up implementation and controlled before/after experiments are in
`GAP_RESULTS.zh.txt` and `results/gap/`. They preserve the earlier results below.
The new experiment separately measures (a) SAT answers and (b) the same complete
forced-literal query for every backend. Ordinary/weak SAT encodings use incremental
search with countermodel reuse to obtain all forced literals; this avoids
comparing partial answers with complete ones. Baseline sources are still excluded.

To reproduce the follow-up, first extract the **project's own** original code at
commit `fc28999afa20d5ba8267c7e46f3cf9d221590b49` into a separate `../wm-v1`
directory. Run these sequentially on the Linux experiment server, with no other
experiment jobs during the single-worker measurements:

```sh
python experiments/validate.py --out results/gap/validation.json
python experiments/propagation_audit.py --out results/gap/propagation_audit.json
python experiments/gap_suite.py --reference-root ../wm-v1 --out results/gap/serial
python experiments/gap_forced.py
python experiments/gap_suite.py --mode ablation --out results/gap/ablation
python experiments/gap_suite.py --mode wide --out results/gap/wide --jobs 2 --repeats 1
python experiments/analyze_gap.py --plots
```

`wide` is a parallel sensitivity run, not an isolated timing confirmation.
Server environment metadata and per-run source hashes are retained. Historical raw data use the
implementation then present; rerunning an old command on the current code tests
the optimized implementation. Do not describe it as a rerun of the old version.

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
