"""Incremental exact RA baseline with model-batched complete support queries.

B0 encodes original semantics. B1 uses the same encoding with supplied permanent
certificate facts, constant simplification and smaller source domains. Neither
constructs a protocol certificate, uses a layout, or calls the graph compiler.
"""
from itertools import combinations, permutations
from time import perf_counter
from pysat.solvers import Solver
from .ra import RARegistry
from .ra_reference import input_parts


class SupportSAT:
    def __init__(self, value, certificate=None, solver='cadical195', solver_factory=None):
        started = perf_counter()
        self.input = value
        self.inst, guards, allowed = input_parts(value)
        inst = self.inst
        self.registry = reg = RARegistry(inst)
        self.solver = Solver(name=solver) if solver_factory is None else solver_factory()
        self.nv = reg.nvars
        self.clauses = 0
        self.solve_calls = 0
        self.last_query_stats = {}
        self._closed = False
        if certificate and certificate.get('status') == 'OUTSIDE':
            raise ValueError('OUTSIDE is not a semantic UNSAT certificate')
        if certificate and 'certificate' in certificate:
            certificate = certificate['certificate']
        cert = certificate or {}
        if cert.get('status') == 'OUTSIDE':
            raise ValueError('OUTSIDE is not a semantic UNSAT certificate')
        domains = {r: tuple(sorted(cert.get('domains', inst.candidates).get(r, inst.candidates[r])))
                   for r in inst.reads}
        if any(not set(domains[r]) <= set(inst.candidates[r]) for r in inst.reads):
            raise ValueError('Certificate domain contains an unregistered source')
        known = {}
        for r in inst.reads:
            for w in inst.candidates[r]:
                bit = reg.literal(('rf', w, r))
                if w not in domains[r]:
                    known[bit] = False
                elif (w, r) in cert.get('mandatory', ()):
                    known[bit] = True
        for a, b in cert.get('L', ()):
            bit = reg.literal(('co', a, b))
            if type(bit) is int:
                truth = bit > 0
                if abs(bit) in known and known[abs(bit)] != truth:
                    self._raw_clause([])
                known[abs(bit)] = truth
            elif bit is False:
                self._raw_clause([])
        for bit, truth in known.items():
            self._raw_clause([bit if truth else -bit])
        if reg.nvars:
            self._raw_clause([reg.nvars, -reg.nvars])  # declare even unused original IDs

        def literal(value):
            if type(value) is bool:
                return value
            if abs(value) in known:
                return known[abs(value)] == (value > 0)
            return value

        def neg(value):
            return not value if type(value) is bool else -value

        def clause(*values):
            values = [literal(v) for v in values]
            if any(v is True for v in values):
                return
            values = list(dict.fromkeys(v for v in values if v is not False))
            if any(-v in values for v in values):
                return
            self._raw_clause(values)

        nodes = tuple(inst.event)
        must_h = set(cert.get('H', ()))
        hb = {}
        for a in nodes:
            for b in nodes:
                if a == b:
                    continue
                if (a, b) in must_h:
                    hb[a, b] = True
                elif (b, a) in must_h:
                    hb[a, b] = False
                else:
                    self.nv += 1
                    hb[a, b] = self.nv

        def H(a, b):
            return hb.get((a, b), False)

        def C(a, b):
            return reg.literal(('co', a, b))

        base = [(a, b, True) for a, b in sorted(inst.sb)]
        base += [(i, e, True) for i in inst.initial for e in nodes if e not in inst.initial]
        if cert.get('status') == 'PROVED_UNSAT':
            self._raw_clause([])
        else:
            if any(a == b for a, b in must_h):
                self._raw_clause([])
            for r, sources in domains.items():
                ids = [reg.literal(('rf', w, r)) for w in sources]
                clause(*ids)
                for a, b in combinations(ids, 2):
                    clause(-a, -b)
                base.extend((w, r, v) for w, v in zip(sources, ids))
            for a, b in combinations(nodes, 2):
                clause(neg(H(a, b)), neg(H(b, a)))
            for b, c, enabled in base:
                clause(neg(enabled), H(b, c))
                for a in nodes:
                    if a != b:
                        clause(neg(H(a, b)), neg(enabled), H(a, c))
            for loc in sorted({e.loc for e in inst.events}):
                writes = [w for w in inst.writes if inst.event[w].loc == loc]
                reads = [r for r in inst.reads if inst.event[r].loc == loc]
                initial = next(i for i in inst.initial if inst.event[i].loc == loc)
                for w in writes:
                    if w != initial:
                        clause(C(initial, w))
                for a, b, c in permutations(writes, 3):
                    clause(neg(C(a, b)), neg(C(b, c)), C(a, c))
                for a, b in permutations(writes, 2):
                    clause(neg(H(a, b)), C(a, b))
                for r in reads:
                    for source in domains[r]:
                        rf = reg.literal(('rf', source, r))
                        for w in writes:
                            clause(neg(H(w, r)), -rf, True if w == source else C(w, source))
                            clause(neg(H(r, w)), -rf, C(source, w))
                for r, s in permutations(reads, 2):
                    for a in domains[r]:
                        for b in domains[s]:
                            if a != b:
                                clause(neg(H(r, s)), -reg.literal(('rf', a, r)),
                                       -reg.literal(('rf', b, s)), C(a, b))
            for r, values in allowed.items():
                if r not in inst.reads:
                    raise ValueError('Allowed value restriction is not on a read')
                if values is not None:
                    for w in inst.candidates[r]:
                        if inst.event[w].value not in values:
                            clause(-reg.literal(('rf', w, r)))
            # Encode the actual two-read guard truth table. B1 may simplify clauses
            # using certified constants, but no own-index inference occurs here.
            for guard in guards:
                op = guard.get('op')
                if op not in ('buffer_full', 'buffer_empty'):
                    raise ValueError('OUTSIDE: unsupported original guard')
                own, peer = guard['own'], guard['peer']
                if own not in inst.reads or peer not in inst.reads:
                    raise ValueError('Guard endpoints must be reads')
                if type(guard['outcome']) is not bool:
                    raise ValueError('Guard outcome must be Boolean')
                modulus = guard['modulus']
                if type(modulus) is not int or modulus < 2:
                    raise ValueError('Invalid buffer modulus')
                for a in inst.candidates[own]:
                    for b in inst.candidates[peer]:
                        va, vb = inst.event[a].value, inst.event[b].value
                        observed = ((va + 1) % modulus == vb) if op == 'buffer_full' else (va == vb)
                        if observed != guard['outcome']:
                            clause(-reg.literal(('rf', a, own)), -reg.literal(('rf', b, peer)))
        self.stats = dict(algorithm='certificate-incidence-sat' if certificate else 'raw-incidence-sat',
                          solver=solver, original_variables=reg.nvars, cnf_variables=self.nv,
                          clauses=self.clauses, base_edges=len(base), build_seconds=perf_counter()-started,
                          certificate_supplied=bool(certificate), certificate_constants=len(known),
                          source_candidates=sum(map(len, domains.values())), model_batching=True,
                          query_solver_reused=True, protocol_inference=False)

    def _raw_clause(self, values):
        self.solver.add_clause(list(values))
        self.clauses += 1

    def _alpha(self, assumptions):
        result = tuple(assumptions)
        if any(type(lit) is not int or abs(lit) not in self.registry.by_id for lit in result):
            raise ValueError('Queries contain only original nonzero RF/CO literals')
        return result

    def _solve(self, assumptions):
        self.solve_calls += 1
        return self.solver.solve(assumptions=list(assumptions))

    def solve(self, assumptions=()):
        start = perf_counter()
        answer = self._solve(self._alpha(assumptions))
        self.last_query_stats = dict(task='consistency', calls=1, seconds=perf_counter()-start)
        return answer

    def single_support(self, literal, assumptions=()):
        result = self.solve(tuple(assumptions) + (literal,))
        self.last_query_stats['task'] = 'single-support'
        return result

    def model(self):
        return self.solver.get_model()

    def model_original(self):
        model = self.model()
        if model is None:
            return None
        return frozenset(lit for lit in model if abs(lit) <= self.registry.nvars)

    def all_support(self, assumptions=()):
        """Batch discover supported signs with one incremental solver and temporary ORs."""
        alpha = self._alpha(assumptions)
        start, before_calls = perf_counter(), self.solve_calls
        if not self._solve(alpha):
            self.last_query_stats = dict(task='all-support', calls=1, models=0,
                                         seconds=perf_counter()-start, output_literals=0)
            return False, set()
        supported = set(self.model_original())
        unknown = {lit for v in self.registry.by_id for lit in (v, -v)} - supported
        models = 1
        while unknown:
            self.nv += 1
            activation = self.nv
            self._raw_clause([-activation, *sorted(unknown)])
            try:
                found = self._solve(alpha + (activation,))
                witness = self.model_original() if found else ()
            finally:
                self._raw_clause([-activation])
            if not found:
                break
            discovered = unknown.intersection(witness)
            if not discovered:
                raise AssertionError('Guarded unknown-support clause did not discover a literal')
            supported.update(witness)
            unknown.difference_update(witness)
            models += 1
        self.last_query_stats = dict(task='all-support', calls=self.solve_calls-before_calls,
                                     models=models, seconds=perf_counter()-start,
                                     output_literals=len(supported))
        return True, supported

    supports = all_support

    def target_support(self, variables, assumptions=()):
        """Exact support only for requested original coordinates, not all RF/CO."""
        variables = frozenset(variables)
        if any(type(v) is not int or v not in self.registry.by_id for v in variables):
            raise ValueError('Targets must be positive original variable IDs')
        alpha = self._alpha(assumptions)
        started, before = perf_counter(), self.solve_calls
        supported = set()
        sat = self._solve(alpha)
        if sat:
            supported = {l for l in self.model_original() if abs(l) in variables}
            unknown = {l for v in variables for l in (v, -v)} - supported
            while unknown:
                self.nv += 1
                selector = self.nv
                self._raw_clause([-selector, *sorted(unknown)])
                try:
                    found = self._solve(alpha + (selector,))
                    witness = {l for l in self.model_original() if abs(l) in variables} if found else set()
                finally:
                    self._raw_clause([-selector])
                if not found:
                    break
                assert witness & unknown
                supported.update(witness)
                unknown.difference_update(witness)
        self.last_query_stats = dict(task='target-support', calls=self.solve_calls-before,
            target_variables=len(variables), output_literals=len(supported), seconds=perf_counter()-started)
        return sat, supported

    def propagate(self, assumptions=()):
        sat, supported = self.all_support(assumptions)
        return sat, {lit for lit in supported if -lit not in supported} if sat else set()

    def close(self):
        if not self._closed:
            self.solver.delete()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


IncrementalSupportSAT = SupportSAT
