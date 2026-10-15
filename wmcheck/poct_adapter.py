"""Fixed-event adapter to the published Poct SC artifact, for SC-equivalent inputs.

Callers must check the pure single-address certificate before comparing to RA.
Poct owns Event/guard-of/addr-of/po/rf/ws declarations in its custom parser.
No baseline code is copied into this repository.
"""
from itertools import combinations
from .ra import RARegistry
from .ra_schedule import certificate


def export_poct(inst, clauses=()):
    certificate(inst)
    reg=RARegistry(inst);names={e.id:f'e{i}' for i,e in enumerate(inst.events)}
    lines=['; Generated fixed-event SC-equivalent instance.']
    def emit(s):lines.append(s)
    def lit(x):return f'x{x}' if x>0 else f'(not x{-x})'
    for x in reg.by_id:emit(f'(declare-fun x{x} () Bool)')
    for e in inst.events:
        name=names[e.id]
        emit(f'(declare-fun {name} () Event)')
        emit(f'(declare-fun g_{name} () Bool)')
        emit(f'(assert (guard-of {name} g_{name}))');emit(f'(assert g_{name})')
        emit(f'(assert (addr-of {name} 1))')
    for r,ws in inst.candidates.items():
        xs=[]
        for w in ws:
            x=reg.literal(('rf',w,r));xs.append(x)
            emit(f'(assert (rf {names[w]} {names[r]} x{x}))')
        emit('(assert (or '+ ' '.join(map(lit,xs))+'))' if xs else '(assert false)')
        for x,y in combinations(xs,2):emit(f'(assert (or (not x{x}) (not x{y})))')
    for x,(kind,a,b) in reg.by_id.items():
        if kind!='co':continue
        emit(f'(declare-fun rev{x} () Bool)');emit(f'(assert (= rev{x} (not x{x})))')
        emit(f'(assert (ws {names[a]} {names[b]} x{x}))')
        emit(f'(assert (ws {names[b]} {names[a]} rev{x}))')
    edges=set(inst.sb)|{(i,e.id) for i in inst.initial for e in inst.events if e.id not in inst.initial}
    for a,b in sorted(edges):emit(f'(assert (po {names[a]} {names[b]}))')
    for clause in clauses:
        emit('(assert (or '+ ' '.join(map(lit,clause))+'))' if clause else '(assert false)')
    return '\n'.join(lines)+'\n'
