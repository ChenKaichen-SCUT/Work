"""Finite relational input and original-variable identities.

The generic input denotes block-ordered co, not arbitrary TSO. A recognizer
must prove that restriction before interpreting it as an unrestricted trace.
"""
from dataclasses import dataclass, field, asdict
from itertools import combinations, permutations, product


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    loc: str | None
    thread: int
    value: int | None = None


@dataclass(frozen=True)
class Axiom:
    name: str
    fixed: tuple[tuple[str, str], ...] = ()
    rf_mode: str = 'all'
    co: bool = True
    fr: bool = True


@dataclass
class Instance:
    events: tuple[Event, ...]
    blocks: tuple[tuple[str, ...], ...]
    candidates: dict[str, tuple[str, ...]]
    axioms: tuple[Axiom, ...]
    forced_co: tuple[tuple[str, str], ...] = ()
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.event = {e.id: e for e in self.events}
        self.layer = {e: i for i, block in enumerate(self.blocks) for e in block}
        flat = [e for b in self.blocks for e in b]
        if len(self.event) != len(self.events) or len(flat) != len(set(flat)) or set(flat) != set(self.event):
            raise ValueError('Blocks must partition unique events')
        for e in self.events:
            if e.kind not in ('R', 'W', 'F') or (e.kind != 'F' and e.loc is None):
                raise ValueError('Only fixed R/W/F events are supported')
            if e.kind == 'R':
                if e.id not in self.candidates:
                    raise ValueError('Every read needs an explicit candidate list')
                if len(set(self.candidates[e.id])) != len(self.candidates[e.id]):
                    raise ValueError('Duplicate read candidate')
                for w in self.candidates[e.id]:
                    src = self.event[w]
                    if src.kind != 'W' or src.loc != e.loc or self.layer[w] > self.layer[e.id]:
                        raise ValueError('Candidate must be a same-address past/current write')
                    if e.value is not None and src.value != e.value:
                        raise ValueError('Candidate read value mismatch')
        if any(self.event[r].kind != 'R' for r in self.candidates):
            raise ValueError('Candidate keys must be reads')
        for ax in self.axioms:
            if ax.rf_mode not in ('all', 'ext', 'none'):
                raise ValueError('Unsupported rf mask')
            if any(a not in self.event or b not in self.event for a,b in ax.fixed):
                raise ValueError('Unknown fixed edge endpoint')
        for a,b in self.forced_co:
            if self.event[a].kind != 'W' or self.event[b].kind != 'W' or self.event[a].loc != self.event[b].loc:
                raise ValueError('Invalid forced co')
            if self.layer[a] > self.layer[b]:
                raise ValueError('Forced co contradicts certified block order')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(tuple(Event(**e) for e in data['events']),
                   tuple(tuple(b) for b in data['blocks']),
                   {r: tuple(ws) for r,ws in data['candidates'].items()},
                   tuple(Axiom(a['name'], tuple(map(tuple,a.get('fixed',()))), a.get('rf_mode','all'),
                               a.get('co',True), a.get('fr',True)) for a in data['axioms']),
                   tuple(map(tuple,data.get('forced_co',()))), data.get('metadata',{}))


class Registry:
    def __init__(self, inst):
        self.inst = inst
        self.by_key, self.by_id, self.by_layer = {}, {}, []
        for block in inst.blocks:
            keys = []
            for r in sorted(block):
                for w in inst.candidates.get(r, ()):
                    keys.append(('rf',w,r))
            locs = {}
            for e in block:
                if inst.event[e].kind == 'W':
                    locs.setdefault(inst.event[e].loc, []).append(e)
            for loc in sorted(locs):
                keys.extend(('co',a,b) for a,b in combinations(sorted(locs[loc]),2))
            ids = []
            for key in keys:
                v = len(self.by_key)+1
                self.by_key[key], self.by_id[v] = v,key
                ids.append(v)
            self.by_layer.append(tuple(ids))
        self.nvars = len(self.by_key)

    def literal(self, key):
        """Signed integer, or a Boolean for a structural relation constant."""
        kind,a,b = key
        if kind == 'rf':
            return self.by_key.get(key, False)
        if kind != 'co': raise ValueError('Expected rf or co')
        ev = self.inst.event
        if a == b or ev[a].kind != 'W' or ev[b].kind != 'W' or ev[a].loc != ev[b].loc:
            return False
        la,lb = self.inst.layer[a],self.inst.layer[b]
        if la != lb: return la < lb
        return self.by_key[key] if a < b else -self.by_key[('co',b,a)]


def local_choices(inst, registry, i):
    block = inst.blocks[i]
    reads = sorted(r for r in block if inst.event[r].kind == 'R')
    byloc = {}
    for e in block:
        if inst.event[e].kind == 'W': byloc.setdefault(inst.event[e].loc,[]).append(e)
    orders = [tuple(permutations(sorted(ws))) for _,ws in sorted(byloc.items())]
    for ordering in product(*orders):
        co = frozenset((a,b) for order in ordering for k,a in enumerate(order) for b in order[k+1:])
        if any(inst.layer[a] == i == inst.layer[b] and (a,b) not in co for a,b in inst.forced_co):
            continue
        for sources in product(*(inst.candidates[r] for r in reads)):
            rf = dict(zip(reads,sources))
            label=[]
            for v in registry.by_layer[i]:
                kind,a,b=registry.by_id[v]
                truth = rf.get(b)==a if kind=='rf' else (a,b) in co
                label.append(v if truth else -v)
            yield rf,co,tuple(label)
