"""Direct finite RA semantics for experimental acceptance, independent of certificates.

Only the immutable event input, original registry and recorded guards are read.
No recognizer, protocol lemma, layout, monitor or compiled state is imported.
"""
from itertools import combinations, permutations, product
from .ra import RARegistry


class ReferenceLimit(RuntimeError):
    pass


def input_parts(value):
    inst = getattr(value, 'inst', value)
    guards = tuple(getattr(value, 'guards', ()))
    allowed = getattr(value, 'allowed_values', None) or {}
    return inst, guards, allowed


def guard_holds(guard, values):
    """Evaluate the original two-read control predicate, without own-index facts."""
    op = guard.get('op')
    if op not in ('buffer_full', 'buffer_empty'):
        raise ValueError('OUTSIDE: unsupported original guard: ' + str(op))
    own, peer = values[guard['own']], values[guard['peer']]
    if op == 'buffer_full':
        modulus = guard['modulus']
        if type(modulus) is not int or modulus < 2:
            raise ValueError('OUTSIDE: invalid buffer modulus')
        actual = (own + 1) % modulus == peer
    else:
        actual = own == peer
    if type(guard['outcome']) is not bool:
        raise ValueError('OUTSIDE: guard outcome must be Boolean')
    return actual == guard['outcome']


def _reach(nodes, edges):
    adjacency = {v: set() for v in nodes}
    for a, b in edges:
        adjacency[a].add(b)
    closure = set()
    for source in nodes:
        seen, todo = set(), list(adjacency[source])
        while todo:
            target = todo.pop()
            if target in seen:
                continue
            seen.add(target)
            todo.extend(adjacency[target] - seen)
        closure.update((source, target) for target in seen)
    return closure


def _assignment_map(registry, assignment):
    if isinstance(assignment, dict):
        if set(assignment) != set(registry.by_id):
            return None
        if any(type(v) is not bool for v in assignment.values()):
            return None
        return assignment
    literals = set(assignment)
    if any(type(lit) is not int or abs(lit) not in registry.by_id for lit in literals):
        return None
    if len(literals) != registry.nvars or any(-lit in literals for lit in literals):
        return None
    return {v: v in literals for v in registry.by_id}


def evaluate_assignment(value, assignment, registry=None):
    """Full Phi(x), including invalid one-hot/CO assignments (not just valid models)."""
    inst, guards, allowed = input_parts(value)
    registry = registry or RARegistry(inst)
    selected = _assignment_map(registry, assignment)
    if selected is None:
        return False
    rf = {}
    co = set()
    for variable, (kind, a, b) in registry.by_id.items():
        if kind == 'rf':
            if selected[variable]:
                if b in rf:
                    return False
                rf[b] = a
        elif selected[variable]:
            co.add((a, b))
        else:
            co.add((b, a))
    if set(rf) != set(inst.reads):
        return False
    values = {}
    for read, write in rf.items():
        if write not in inst.candidates[read]:
            return False
        actual = inst.event[write].value
        if allowed.get(read) is not None and actual not in allowed[read]:
            return False
        values[read] = actual
    if not all(guard_holds(g, values) for g in guards):
        return False
    for initial in inst.initial:
        if any((w, initial) in co for w in inst.writes):
            return False
    co_closure = _reach(inst.writes, co)
    if any(a == b for a, b in co_closure) or co_closure != co:
        return False
    nodes = tuple(inst.event)
    # Independently construct full SB rather than importing recognizer closure.
    sb = {(a, b) for thread in inst.threads for i, a in enumerate(thread)
          for b in thread[i + 1:]}
    initial_edges = {(i, v) for i in inst.initial for v in nodes if v not in inst.initial}
    rf_edges = {(w, r) for r, w in rf.items()}
    hb = _reach(nodes, sb | rf_edges | initial_edges)
    fr = {(r, after) for r, source in rf.items() for before, after in co if before == source}
    eco = _reach(nodes, rf_edges | co | fr)
    return not any(a == b or (b, a) in eco for a, b in hb)


def enumerate_completions(value, limit=1000000, registry=None):
    """Enumerate RF choices and full CO orders, then check original dense semantics.

    The limit counts attempted assignments, not accepted models. It is an UNKNOWN
    resource exception, never an UNSAT result. No protocol filtering is used.
    """
    inst, _, _ = input_parts(value)
    registry = registry or RARegistry(inst)
    locs = sorted({inst.event[w].loc for w in inst.writes})
    initial = {inst.event[w].loc: w for w in inst.initial}
    write_groups = [[w for w in inst.writes if inst.event[w].loc == loc and w != initial[loc]]
                    for loc in locs]
    # itertools.product caches iterables: use a recursive order traversal instead.
    def visit_orders(index, positions):
        if index == len(locs):
            yield positions
            return
        for tail in permutations(write_groups[index]):
            order = (initial[locs[index]],) + tail
            yield from visit_orders(index + 1, positions | {w: i for i, w in enumerate(order)})
    examined = 0
    for positions in visit_orders(0, {}):
        for sources in product(*(inst.candidates[r] for r in inst.reads)):
            examined += 1
            if examined > limit:
                raise ReferenceLimit('RF/CO enumeration attempt limit')
            rf = dict(zip(inst.reads, sources))
            x = frozenset(v if (rf[b] == a if kind == 'rf' else positions[a] < positions[b]) else -v
                          for v, (kind, a, b) in registry.by_id.items())
            if evaluate_assignment(value, x, registry):
                yield x


enumerate_models = enumerate_completions


def all_boolean_assignments(registry, max_variables=20):
    if registry.nvars > max_variables:
        raise ReferenceLimit('Full Boolean cube exceeds declared variable cap')
    for bits in product((False, True), repeat=registry.nvars):
        yield frozenset(v if bits[v - 1] else -v for v in registry.by_id)


def supports_from_models(models, assumptions=()):
    assumptions = set(assumptions)
    compatible = [model for model in models if assumptions <= model]
    return bool(compatible), set().union(*compatible) if compatible else set()


def has_sc_linearization(value, assignment, registry=None):
    """For a valid complete assignment, test SC constraints including read freshness."""
    inst, _, _ = input_parts(value)
    registry = registry or RARegistry(inst)
    if not evaluate_assignment(value, assignment, registry):
        return False
    x = _assignment_map(registry, assignment)
    rf, co = {}, set()
    for v, (kind, a, b) in registry.by_id.items():
        if kind == 'rf' and x[v]:
            rf[b] = a
        elif kind == 'co':
            co.add((a, b) if x[v] else (b, a))
    edges = set(inst.sb) | co | {(w, r) for r, w in rf.items()}
    edges |= {(r, b) for r, w in rf.items() for a, b in co if a == w}
    edges |= {(i, e) for i in inst.initial for e in inst.event if e not in inst.initial}
    return not any(a == b for a, b in _reach(inst.event, edges))
