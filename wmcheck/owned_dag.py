"""Support evaluation for acyclic graphs with path-dependent variable ownership."""


def check_ownership(compiled, owned):
    """Independent local certificate check, bitsets indexed by original ID-1.

    Runs without enumerating paths. Large callers may regenerate certificates
    lazily; the verification cost is explicitly separate from compilation.
    """
    all_bits = (1 << compiled.registry.nvars)-1
    start = compiled.layers[0][0]
    if owned(start) != 0 or any(owned(q) != all_bits for q in compiled.layers[-1]):
        raise ValueError('Ownership endpoints do not cover the original variables')
    levels = {q: i for i, layer in enumerate(compiled.layers) for q in layer}
    previous = -1
    for e in compiled.edges:
        if levels[e.source] >= levels[e.target] or levels[e.source] < previous:
            raise ValueError('Edges must be topologically ordered')
        previous = levels[e.source]
        a, b = owned(e.source), owned(e.target)
        if a & ~b:
            raise ValueError('A previously assigned variable was forgotten')
        ids = [abs(l) for l in e.label]
        if any(v < 1 or v > compiled.registry.nvars for v in ids) or len(ids) != len(set(ids)):
            raise ValueError('Invalid or repeated label variable')
        mask = sum(1 << (v-1) for v in ids)
        if mask != b & ~a:
            raise ValueError('Label does not exactly match newly owned variables')
    return True


class OwnedGraphSolver:
    """Sparse label index avoids quadratic dense group bitsets at large sizes.

    No SAT search, no enumeration of complete assignments, and no mutable
    query-dependent history summary. Every call computes all original support.
    """
    def __init__(self, compiled):
        self.compiled = compiled
        self.groups, self.labels, self.edges = {}, [], []
        self.occurs = {l: [] for v in compiled.registry.by_id for l in (v, -v)}
        for e in compiled.edges:
            g = self.groups.get(e.label)
            if g is None:
                g = len(self.labels); self.groups[e.label] = g; self.labels.append(e.label)
                for l in e.label:
                    self.occurs[l].append(g)
            self.edges.append((e.source, e.target, g))
        self.start = compiled.layers[0][0]
        self.finals = set(compiled.layers[-1])
        self.size = 1+max(q for layer in compiled.layers for q in layer)

    def _paths(self, assumptions):
        disabled = bytearray(len(self.labels)); seen = set()
        for l in assumptions:
            if abs(l) not in self.compiled.registry.by_id:
                raise ValueError('Only original RF/CO assumptions are supported')
            if -l in seen:
                return None
            seen.add(l)
            for g in self.occurs[-l]:
                disabled[g] = 1
        forward = bytearray(self.size); forward[self.start] = 1
        for a, b, g in self.edges:
            if forward[a] and not disabled[g]:
                forward[b] = 1
        if not any(forward[q] for q in self.finals):
            return None
        backward = bytearray(self.size)
        for q in self.finals:
            backward[q] = 1
        for a, b, g in reversed(self.edges):
            if backward[b] and not disabled[g]:
                backward[a] = 1
        return disabled, forward, backward

    def propagate(self, assumptions=()):
        paths = self._paths(assumptions)
        if paths is None:
            return False, set()
        disabled, forward, backward = paths
        supported = bytearray(len(self.labels))
        for a, b, g in self.edges:
            if forward[a] and backward[b] and not disabled[g]:
                supported[g] = 1
        literals = set()
        for g, yes in enumerate(supported):
            if yes:
                literals.update(self.labels[g])
        return True, {l for l in literals if -l not in literals}

    def witness(self, assumptions=()):
        paths = self._paths(assumptions)
        if paths is None:
            return None
        disabled, _, backward = paths
        current = self.start; assignment = set()
        for a, b, g in self.edges:
            if a == current and backward[b] and not disabled[g]:
                assignment.update(self.labels[g]); current = b
        assert current in self.finals and len(assignment) == self.compiled.registry.nvars
        return assignment
