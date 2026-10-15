"""Sufficient structural recognizer for the proved alternating-flag TSO subclass.

This checks every trace condition; metadata alone never grants certification.
It is not an arbitrary-program decomposition finder or a general CAT parser.
"""
from .model import Instance,Axiom


class Unsupported(ValueError): pass


def recognize(trace):
    events=trace['events'];ev={e.id:e for e in events};blocks=trace['blocks']
    sequences=trace['sequences'];flags=trace['flags'];data=set(trace['data_locations'])
    if len(ev)!=len(events): raise Unsupported('duplicate events')
    if len(flags)<2 or set(sequences)!=set(flags) or len(set(flags.values()))!=len(flags):
        raise Unsupported('need fixed threads with private flag addresses')
    if data&set(flags.values()): raise Unsupported('payload accesses protocol flags')
    flat=[e for b in blocks for e in b]
    if len(flat)!=len(set(flat)) or set(flat)!=set(ev): raise Unsupported('invalid block partition')
    layer={e:i for i,b in enumerate(blocks) for e in b}
    if len(blocks)<2: raise Unsupported('no protocol round')
    initial=[ev[e] for e in blocks[0]]
    if any(e.kind!='W' or e.thread!=-1 or e.value!=0 for e in initial):
        raise Unsupported('initial writes must be zero')
    if len(initial)!=len(data)+len(flags) or {e.loc for e in initial}!=data|set(flags.values()):
        raise Unsupported('one initial write per address required')
    seen=[];fixed_rf={}
    for t,seq in sequences.items():
        if any(e not in ev or ev[e].thread!=t for e in seq): raise Unsupported('invalid thread sequence')
        if [layer[e] for e in seq]!=sorted(layer[e] for e in seq): raise Unsupported('non-prefix round blocks')
        seen.extend(seq)
        for i in range(1,len(blocks)):
            body=[ev[e] for e in seq if layer[e]==i]
            positions=[j for j,e in enumerate(body) if e.kind=='W' and e.loc==flags[t]]
            if len(positions)!=1: raise Unsupported('missing/duplicate own flag publication')
            j=positions[0];payload=body[:j];tail=body[j+1:]
            if any(e.kind not in ('R','W') or e.loc not in data for e in payload):
                raise Unsupported('payload contains unsupported operations')
            if body[j].value!=i%2: raise Unsupported('flags must alternate 1,0')
            if len(tail)!=len(flags) or tail[-1].kind!='F': raise Unsupported('successful peer reads followed by MFENCE required')
            reads=tail[:-1]
            if any(e.kind!='R' or e.value!=i%2 for e in reads) or {e.loc for e in reads}!={x for u,x in flags.items() if u!=t}:
                raise Unsupported('exactly one successful read of every peer flag required')
    expected=set(ev)-set(blocks[0])
    if len(seen)!=len(set(seen)) or set(seen)!=expected: raise Unsupported('thread sequences do not partition trace')
    for i in range(1,len(blocks)):
        ws={ev[e].loc for e in blocks[i] if ev[e].kind=='W' and ev[e].loc in data}
        if ws!=data: raise Unsupported('every data address must be refreshed each round')
        flagwrites={ev[e].loc:e for e in blocks[i] if ev[e].kind=='W' and ev[e].loc in flags.values()}
        for e in blocks[i]:
            if ev[e].kind=='R' and ev[e].loc in flags.values(): fixed_rf[e]=flagwrites[ev[e].loc]
    candidates={}
    writes=[e for e in events if e.kind=='W']
    for e in events:
        if e.kind=='R':
            candidates[e.id]=(fixed_rf[e.id],) if e.id in fixed_rf else tuple(w.id for w in writes
                if w.loc==e.loc and w.value==e.value and layer[w.id] in (layer[e.id]-1,layer[e.id]))
    local=set();global_=set()
    for seq in sequences.values():
        lastloc={};lr=lw=lf=None
        for eid in seq:
            e=ev[eid]
            if e.kind!='F':
                if e.loc in lastloc: local.add((lastloc[e.loc],eid))
                lastloc[e.loc]=eid
            prev=(lr,lf) if e.kind=='R' else ((lr,lw,lf) if e.kind=='F' else (lr,lw,lf))
            global_.update((p,eid) for p in prev if p is not None)
            if e.kind=='R': lr=eid
            elif e.kind=='W': lw=eid
            else: lf=eid
    fixed={(w,r) for r,w in fixed_rf.items()}
    metadata={'certificate':'alternating-flag-tso-v1','rounds':len(blocks)-1,
              'thread_sequences':{str(t):list(s) for t,s in sequences.items()},
              'flag_locations':list(flags.values()),'parameters':trace.get('parameters',{}),
              'scope':'Fixed successful-read branches; ordinary R/W/MFENCE; no arbitrary polling or dynamic events.'}
    return Instance(tuple(events),tuple(map(tuple,blocks)),candidates,
                    (Axiom('sc-per-location',tuple(sorted(local|fixed)),'all'),
                     Axiom('tso-global',tuple(sorted(global_|fixed)),'ext')),metadata=metadata)
