"""Strict straight-line C11 litmus adapter and observable-outcome encoding.

No instruction is deleted or weakened to make a benchmark fit. Unknown
statements, relaxed/SC accesses, RMWs, branches, and final-memory predicates
are rejected with a reason. None on a read means its result is unobserved;
constant store values and the fixed event set remain mandatory.
"""
from dataclasses import dataclass
import re
from .model import Event
from .ra import RAInstance


@dataclass
class RAProgram:
    instance: object
    observations: dict
    name: str

    def clauses(self, reg):
        return [[reg.literal(('rf', w, r)) for w in self.instance.candidates[r]
                 if self.instance.event[w].value == val] for r, val in self.observations.items()]

    def conditioned(self):
        """Conjunction of observed read equalities can be pushed into RF domains."""
        i = self.instance
        return RAInstance(tuple(Event(e.id, e.kind, e.loc, e.thread,
            self.observations.get(e.id, e.value)) for e in i.events), i.threads, i.initial)


def parse_c_litmus(source):
    s = re.sub(r'\(\*.*?\*\)', '', source, flags=re.S)
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    s = re.sub(r'//[^\n]*', '', s)
    header = re.match(r'\s*C\s+([^\s]+)\s*\{([^{}]*)\}', s, re.S)
    if not header:
        raise ValueError('not_simple_C_litmus')
    name, initial = header.groups(); init = {}
    for statement in initial.split(';'):
        if not statement.strip():
            continue
        m = re.fullmatch(r'\s*\[?(\w+)\]?\s*=\s*(-?\d+)\s*', statement)
        if not m:
            raise ValueError('unsupported_initializer')
        if m[1] in init:
            raise ValueError('duplicate_initializer')
        init[m[1]] = int(m[2])
    remaining = s[header.end():]; threads = []; events = []; registers = {}; tids = set()
    while True:
        m = re.match(r'\s*P(\d+)\s*\(([^()]*)\)\s*\{([^{}]*)\}', remaining, re.S)
        if not m:
            break
        tid = int(m[1]); tids.add(tid); seq = []
        for statement in m[3].split(';'):
            statement = statement.strip()
            if not statement:
                continue
            w = re.fullmatch(r'atomic_store_explicit\(\s*&?(\w+)\s*,\s*(-?\d+)\s*,\s*memory_order_release\s*\)', statement)
            r = re.fullmatch(r'(?:int\s+)?(\w+)\s*=\s*atomic_load_explicit\(\s*&?(\w+)\s*,\s*memory_order_acquire\s*\)', statement)
            if w:
                kind, loc, value = 'W', w[1], int(w[2])
            elif r:
                kind, loc, value = 'R', r[2], None
            else:
                raise ValueError('unsupported_thread_statement')
            eid = f't{tid}_e{len(seq)}'; seq.append(eid)
            if r:
                if (tid, r[1]) in registers:
                    raise ValueError('register_reassignment')
                registers[tid, r[1]] = eid
            init.setdefault(loc, 0)
            events.append(Event(eid, kind, loc, tid, value))
        threads.append(tuple(seq)); remaining = remaining[m.end():]
    if not threads or len(tids) != len(threads):
        raise ValueError('unsupported_thread_structure')
    m = re.fullmatch(r'\s*exists\s*\((.*)\)\s*', remaining, re.S)
    if not m:
        raise ValueError('unsupported_observation_syntax_or_control_flow')
    obs = {}
    for term in m[1].split('/\\'):
        q = re.fullmatch(r'\s*\(?\s*(\d+)\s*:\s*(\w+)\s*=\s*(-?\d+)\s*\)?\s*', term)
        if not q or (int(q[1]), q[2]) not in registers:
            raise ValueError('observation_not_read_equality_conjunction')
        eid = registers[int(q[1]), q[2]]
        if eid in obs and obs[eid] != int(q[3]):
            raise ValueError('contradictory_observation')
        obs[eid] = int(q[3])
    initials = tuple('init_'+loc for loc in sorted(init))
    ies = tuple(Event('init_'+loc, 'W', loc, -1, init[loc]) for loc in sorted(init))
    return RAProgram(RAInstance(ies+tuple(events), tuple(threads), initials), obs, name)


def export_c(inst, observations=None):
    """Portable pthread program: assertion failure iff the observed outcome exists.

    Result slots have one writer and are read only after all joins. The joins
    introduce no order between the memory events of different worker threads.
    A result store is an unobserved non-atomic leaf with no shared reader until
    join. Values are never used to alter memory operations or addresses.
    """
    observations = observations if observations is not None else {
        r: inst.event[r].value for r in inst.reads if inst.event[r].value is not None}
    locs = {loc: f'x{i}' for i, loc in enumerate(sorted({e.loc for e in inst.events}))}
    rid = {r: i for i, r in enumerate(inst.reads)}
    lines = ['#include <pthread.h>', '#include <stdatomic.h>', '#include <assert.h>',
             '#include <stddef.h>', f'int result[{max(1,len(rid))}];']
    lines += [f'atomic_int {v};' for v in locs.values()]
    for t, seq in enumerate(inst.threads):
        lines.append(f'void *worker{t}(void *unused) {{')
        for v in seq:
            e = inst.event[v]
            if e.kind == 'W':
                lines.append(f'atomic_store_explicit(&{locs[e.loc]}, {e.value}, memory_order_release);')
            else:
                lines.append(f'result[{rid[v]}] = atomic_load_explicit(&{locs[e.loc]}, memory_order_acquire);')
        lines += ['return NULL;', '}']
    lines.append('int main(void) {')
    lines += [f'atomic_init(&{locs[inst.event[i].loc]}, {inst.event[i].value});' for i in inst.initial]
    lines += [f'pthread_t t{t}; pthread_create(&t{t}, NULL, worker{t}, NULL);' for t in range(len(inst.threads))]
    lines += [f'pthread_join(t{t}, NULL);' for t in range(len(inst.threads))]
    predicate = ' && '.join(f'result[{rid[r]}] == {v}' for r, v in observations.items()) or '1'
    lines += [f'assert(!({predicate}));', 'return 0;', '}']
    return '\n'.join(lines)+'\n'


def export_litmus(inst, observations=None, name='generated'):
    observations = observations if observations is not None else {
        r: inst.event[r].value for r in inst.reads if inst.event[r].value is not None}
    locs = {loc: f'x{i}' for i, loc in enumerate(sorted({e.loc for e in inst.events}))}
    lines = [f'C {name}', '{']+[f'[{locs[inst.event[i].loc]}] = {inst.event[i].value};' for i in inst.initial]+['}']
    obs = []
    for t, seq in enumerate(inst.threads):
        lines.append(f'P{t} ('+', '.join('atomic_int* '+v for v in locs.values())+') {')
        for j, v in enumerate(seq):
            e = inst.event[v]
            if e.kind == 'W':
                lines.append(f'atomic_store_explicit({locs[e.loc]}, {e.value}, memory_order_release);')
            else:
                lines.append(f'int r{j} = atomic_load_explicit({locs[e.loc]}, memory_order_acquire);')
                if v in observations:
                    obs.append(f'{t}:r{j}={observations[v]}')
        lines.append('}')
    if not obs:
        raise ValueError('Litmus export requires at least one observed read')
    return '\n'.join(lines)+ '\nexists ('+' /\\ '.join(obs)+')\n'
