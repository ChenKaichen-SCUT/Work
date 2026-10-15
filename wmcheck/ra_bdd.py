"""CUDD comparison: generic CNF compilation and exact original support queries.

This is a baseline, not the proposed relational-history algorithm. Auxiliary
variables are existentially quantified only after the complete CNF is built.
Sifting is enabled during construction; variable order and costs are reported.
"""
from time import perf_counter


class BDDCompiler:
    def __init__(self, encoded, *, reorder=True):
        from dd.cudd import BDD
        start = perf_counter(); self.registry = encoded.registry
        self.bdd = b = BDD(); b.configure(reordering=reorder)
        b.declare(*(f'x{i}' for i in range(1, encoded.nvars+1)))
        root = b.true
        for row in encoded.clauses:
            item = b.false
            for l in row:
                v = b.var(f'x{abs(l)}'); item |= v if l > 0 else ~v
            root &= item
        if encoded.nvars > self.registry.nvars:
            root = b.exist([f'x{i}' for i in range(self.registry.nvars+1, encoded.nvars+1)], root)
        if reorder:
            b.reorder()
        b.configure(reordering=False)
        self.root = root
        self.stats = dict(encoded.stats, algorithm='bdd-sift' if reorder else 'bdd-fixed',
            compile_seconds=encoded.stats['compile_seconds']+perf_counter()-start,
            bdd_nodes=root.dag_size, bdd_manager_nodes=len(b),
            original_order=[b.var_at_level(i) for i in range(len(b.vars))])

    def propagate(self, alpha=()):
        values = {}
        for l in alpha:
            if abs(l) not in self.registry.by_id:
                raise ValueError('Original assumptions only')
            name = f'x{abs(l)}'
            if name in values and values[name] != (l > 0):
                return False, set()
            values[name] = l > 0
        b = self.bdd; root = b.let(values, self.root) if values else self.root
        if root == b.false:
            return False, set()
        # One DAG traversal, including complemented edges and skipped levels.
        # A non-false child has a suffix to true. A skipped variable admits both
        # values on that path. Difference arrays aggregate skipped intervals.
        n = len(b.vars); skipped = [0]*(n+1); signs = [0]*n
        def level(u):
            return n if u == b.true or u == b.false else u.level
        def gap(lo, hi):
            skipped[lo] += 1; skipped[hi] -= 1
        gap(0, level(root)); todo = [root]; seen = set()
        while todo:
            node = todo.pop()
            if node == b.true or node in seen:
                continue
            seen.add(node); k, low, high = b.succ(node)
            if node.negated:
                low, high = ~low, ~high
            for child, sign in ((low, 1), (high, 2)):
                if child != b.false:
                    signs[k] |= sign; gap(k+1, level(child)); todo.append(child)
        running = 0
        for k in range(n):
            running += skipped[k]
            if running:
                signs[k] = 3
        forced = set(alpha)
        for i in self.registry.by_id:
            name = f'x{i}'
            if name in values:
                continue
            bit = signs[b.level_of_var(name)]
            if bit == 2:
                forced.add(i)
            elif bit == 1:
                forced.add(-i)
            elif bit != 3:
                raise AssertionError('BDD support traversal missed an original variable')
        return True, forced
