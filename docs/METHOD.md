# Implementation and measurement contract

## Semantics

An instance has fixed typed events, fixed addresses/values, a partition into
blocks, candidate sources for every read, and a list of graphs
`P | (rf intersect theta) | optional co | optional fr`. Each graph must be
acyclic. `theta` is all, external-thread, or empty; `fr = inverse(rf);co`
always uses the full source relation. Read sources are functional and total.
Coherence is a strict total order per address. Generic instances require all
cross-block writes to follow block order. Local write orders remain choices.

The protocol recognizer checks private one-bit flag ownership, alternating
successful peer reads, the final MFENCE of every thread/round, per-round data
refresh, and the exact partition of events into thread traces and rounds. The
proof draft justifies matching flag sources, cross-round write order, and a
current/previous-round data source window. These reductions do not depend on
reversible SAT decisions. No unsuccessful polling events are removed.

Original SAT variables comprise candidate RF choices and canonical within-block
CO pairs. Excluded RF and cross-block CO are structural constants exposed by
`Registry.literal`; a caller querying them must respect the Boolean result.
Fresh CNF auxiliaries are private. Completeness is with respect to partial
assignments of the original variables, not all auxiliary assignments or the
logical consequences of an arbitrary external formula.

## History summary

The retained interface is the union of fixed-edge boundary events, still-live
read sources, source entry ports, and address exit ports. Source entry ports
preserve the effect of reads creating FR edges into older writes. New and old
ports have distinct generations. A transition combines the old reachability
matrix with local choices, detects cycles, and only then projects to the new
interface. Full prefix graphs are absent from the production algorithm.

The follow-up implementation stores only static future-entry to future-exit
reachability inside this interface. Every vertex still participates in cycle
detection before projection. A backward labelled-language quotient then trims
dead suffixes and merges states with identical possible continuations. The CNF
shares incompatibility and support groups for identical labels. These exact
transformations and their preservation arguments are in `optimization_proofs.txt`.
`raw_states`/`raw_transitions` describe the graph before the backward quotient;
`states`/`transitions` describe the graph actually used for queries. The direct
graph backend returns the same complete relation information without SAT search.

A layer contains one node per reachable summary. Its edges carry complete local
variable labels. Forward and backward dead-path information produces a support
CNF. The strong version adds clauses excluding values with no surviving path.
The weak ablation omits only those support-to-original-value clauses: complete
assignments and satisfiability retain the same semantics. No-merge keeps each
history as a distinct node but retains the same validity checks and labels.

The compilation cache keys the complete local edge matrices, projection indices
and previous summary matrices. It never identifies states using approximate
signatures or the current SAT trail. Historical variable labels and explanation
data remain stored; bounded active interfaces do not mean constant total memory.

## Baselines and correctness

The binary-rank eager baseline shares the certified candidates and forced
cross-block order. It enforces functional RF, transitive total local CO, and a
strict binary topological rank along every enabled axiom edge. It is an internal
conventional encoding, not an implementation of all Dartagnan optimizations.

The independent oracle uses Kahn's algorithm on complete graphs. For protocol
tests it reconstructs dense program-order and fence relations from raw thread
sequences instead of trusting the compiler's sparse fixed graph. Full enumeration
appears only in this small-instance oracle and in the older proof-audit scripts.

Raw propagation measurements use a solver on which `solve()` has never been
called, so learned clauses cannot inflate propagation coverage. The forced-literal
audit counts literal occurrences per satisfiable partial assignment, excluding
assumptions and root-level logically forced literals. These are not counts of
distinct variables across the entire benchmark.

The public corpus importer reports syntax coverage separately from theorem
coverage. Accepted public tests use a single block. They provide no evidence that
arbitrary long public programs have bounded interfaces. Third-party agreement
also cannot replace the universal proof.

For positive existential litmus specifications, this Dartagnan version prints
`PASS` when the requested outcome exists and `FAIL` when it does not. This was
calibrated with SB and SB+mfences and then checked against herd7. It is the reverse
of interpreting FAIL as a C assertion counterexample. External results retain
their raw stdout/stderr for inspection.

## Measurement protocol

Main experiments use three independent workers pinned to different logical CPUs,
with a 6 GiB address-space cap per worker, a 150-second whole-worker timeout,
20,000 compiled nodes, 300,000 transitions, and a 75-second compile limit. Limits
can terminate otherwise solvable instances; their statuses are not logical
answers. The state count is total compiled nodes across all layers, not the
number at one interface. These are configurable practical safeguards.

Every variant uses the same MiniSat22 backend and deterministic query sequence.
The cold total includes trace construction/recognition, compilation, solver
construction and the first solve. Incremental query time and raw propagation time
are reported separately. The main worker also runs a query batch, so its timeout
alone does not identify whether the cold solve or the batch timed out. Additional
long-instance runs checkpoint the stage to disambiguate this. Serial repetitions
check the main timing trend without simultaneous experiment workers.

Parallel CPU affinity does not eliminate shared-memory or cloud-host interference.
Medians, raw repetitions, unsuccessful runs and the serial confirmation are all
retained. `serial_isolated` is the confirmation without other experiment workers;
the earlier `serial` run overlapped with an independent UNSAT batch and must not
be described as an otherwise idle server run. External-tool startup and front-end costs differ from our in-process
core, so the public suite is primarily semantic cross-validation. It is not used
to claim an orders-of-magnitude end-to-end advantage over Dartagnan.

The main family fixes four threads, two data addresses, one write per thread per
round and two data reads, then varies rounds. All write values are 1, first-round
data reads are 0, subsequent reads are 1, and flag senses alternate 1/0. The family
retains at least four independent coherence combinations per round. Width tests
vary thread/address/read counts; no-merge tests isolate history sharing. The
current workload does not establish performance on general concurrent C/C++.
