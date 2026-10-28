"""Generic UP + residual-CNF components, without protocol/round/model-count rules.

Captures the same B1 encoding through a clause sink and builds one solver per
syntactic component. All this cold cost is charged. Component queries cache
local original assumptions, and every global answer still outputs all originals.
"""
from collections import defaultdict, deque
from time import perf_counter
from pysat.solvers import Solver
from .ra_support_sat import SupportSAT


class CapturedSAT(SupportSAT):
    def __init__(self, *args, **kwargs):
        class Sink:
            def add_clause(self, values):pass
            def delete(self):pass
        super().__init__(*args, solver_factory=Sink, **kwargs)

    def _raw_clause(self, values):
        if not hasattr(self, 'captured_clauses'):
            self.captured_clauses = []
        values = tuple(values)
        self.captured_clauses.append(values)
        super()._raw_clause(values)


def residual_components(clauses, originals):
    """Pure syntactic unit propagation followed by clause-incidence components."""
    clauses = [set(c) for c in clauses if not any(-v in c for v in c)]
    occurrences = defaultdict(set)
    for i, clause in enumerate(clauses):
        for lit in clause:
            occurrences[lit].add(i)
    live = set(range(len(clauses)))
    todo = deque(next(iter(c)) for c in clauses if len(c) == 1)
    units = set()
    conflict = any(not c for c in clauses)
    while todo and not conflict:
        lit = todo.popleft()
        if -lit in units:
            conflict = True
            break
        if lit in units:
            continue
        units.add(lit)
        live.difference_update(occurrences[lit])
        for i in occurrences[-lit] & live:
            clauses[i].discard(-lit)
            if not clauses[i]:
                conflict = True
                break
            if len(clauses[i]) == 1:
                todo.append(next(iter(clauses[i])))
    remaining = [tuple(sorted(clauses[i])) for i in sorted(live)]
    parent = {}
    def find(v):
        parent.setdefault(v, v)
        while v != parent[v]:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v
    for clause in remaining:
        if not clause:
            continue
        for lit in clause[1:]:
            parent[find(abs(lit))] = find(abs(clause[0]))
    for v in originals:
        if v not in units and -v not in units:
            find(v)  # keep unconstrained original variables, too
    grouped = defaultdict(lambda: dict(clauses=[], variables=set(), originals=set()))
    for clause in remaining:
        if clause:
            grouped[find(abs(clause[0]))]['clauses'].append(clause)
    for v in parent:
        grouped[find(v)]['variables'].add(v)
        if v in originals:
            grouped[find(v)]['originals'].add(v)
    components = sorted(grouped.values(), key=lambda c: min(c['variables']))
    return dict(units=units, components=components, conflict=conflict,
                residual_clauses=len(remaining))


class ComponentSAT:
    def __init__(self, value, certificate=None, solver='cadical195'):
        start = perf_counter()
        encoded = CapturedSAT(value, certificate=certificate, solver=solver)
        self.registry = encoded.registry
        self.encoding_stats = encoded.stats
        clauses = encoded.captured_clauses
        encoded.close()
        encoded_at = perf_counter()
        self.partition = residual_components(clauses, set(self.registry.by_id))
        self.constants = {lit for lit in self.partition['units'] if abs(lit) in self.registry.by_id}
        self.base_unsat = self.partition['conflict']
        self.engines = []
        self.owner = {}
        self.total_local_hits = self.total_local_misses = self.total_sat_calls = 0
        for i, component in enumerate(self.partition['components']):
            variables = sorted(component['variables'])
            mapping = {v:j+1 for j,v in enumerate(variables)}
            inverse = {j:v for v,j in mapping.items()}
            def local(lit):
                return mapping[abs(lit)] * (1 if lit > 0 else -1)
            engine = Solver(name=solver)
            for clause in component['clauses']:
                engine.add_clause([local(lit) for lit in clause])
            if variables:
                engine.add_clause([len(variables),-len(variables)])
            if not component['originals']:
                # Auxiliary-only components cannot be dropped without a SAT check.
                if not engine.solve():
                    self.base_unsat = True
                self.total_sat_calls += 1
            self.engines.append(dict(solver=engine, mapping=mapping, inverse=inverse,
                                     originals=component['originals'], cache={}, nv=len(variables)))
            for v in component['originals']:
                self.owner[v] = i
        self.stats = dict(algorithm='UP-CNF-component-SAT', encoding_seconds=encoded_at-start,
            partition_and_local_build_seconds=perf_counter()-encoded_at,
            build_seconds=perf_counter()-start, components=len(self.engines),
            original_components=sum(bool(c['originals']) for c in self.partition['components']),
            original_component_sizes=[len(c['originals']) for c in self.partition['components'] if c['originals']],
            fixed_originals=len(self.constants), residual_clauses=self.partition['residual_clauses'],
            semantic_oracle_used_for_partition=False, round_identifiers_used=False,
            no_discarded_global_solver=True)
        self.last_query_stats = {}

    def _local_support(self, item, alpha):
        if alpha in item['cache']:
            self.total_local_hits += 1
            return item['cache'][alpha]
        self.total_local_misses += 1
        solver, mapping, inverse = item['solver'], item['mapping'], item['inverse']
        assumptions = [mapping[abs(v)] * (1 if v > 0 else -1) for v in alpha]
        self.total_sat_calls += 1
        if not solver.solve(assumptions=assumptions):
            answer = False, frozenset()
        else:
            def model():
                return {inverse[abs(v)] * (1 if v > 0 else -1) for v in solver.get_model()
                        if abs(v) in inverse and inverse[abs(v)] in item['originals']}
            supported = model()
            unknown = {v for x in item['originals'] for v in (x,-x)} - supported
            while unknown:
                item['nv'] += 1
                selector = item['nv']
                solver.add_clause([-selector] + [mapping[abs(v)] * (1 if v>0 else -1) for v in sorted(unknown)])
                self.total_sat_calls += 1
                found = solver.solve(assumptions=assumptions+[selector])
                witness = model() if found else set()
                solver.add_clause([-selector])
                if not found:
                    break
                assert witness & unknown
                supported |= witness
                unknown -= witness
            answer = True, frozenset(supported)
        item['cache'][alpha] = answer
        return answer

    def all_support(self, assumptions=()):
        before = (self.total_local_hits,self.total_local_misses,self.total_sat_calls)
        alpha = set(assumptions)
        if any(type(v) is not int or abs(v) not in self.registry.by_id for v in alpha):
            raise ValueError('Only original RF/CO literals')
        if self.base_unsat or any(-v in alpha or -v in self.constants for v in alpha):
            answer = False, set()
        else:
            by_component = defaultdict(list)
            for lit in sorted(alpha):
                if abs(lit) in self.owner:
                    by_component[self.owner[abs(lit)]].append(lit)
            supported = set(self.constants)
            answer = True, supported
            for i,item in enumerate(self.engines):
                if not item['originals']:
                    continue
                sat, local = self._local_support(item, tuple(by_component[i]))
                if not sat:
                    answer = False, set()
                    break
                supported.update(local)
        after = (self.total_local_hits,self.total_local_misses,self.total_sat_calls)
        self.last_query_stats = dict(zip(('local_hits','local_misses','sat_calls'),
                                        (a-b for a,b in zip(after,before))))
        return answer

    def close(self):
        for item in self.engines:
            item['solver'].delete()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
