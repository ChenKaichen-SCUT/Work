"""Strict importer for a documented subset of X86 litmus tests.

All program events occupy one block. This is exact for the imported subset,
but gives NO history-width certificate independent of program length.
Unsupported syntax is rejected, never ignored.
"""
import re
from .model import Event,Instance,Axiom
from .recognize import Unsupported


def parse_x86(text,name='litmus'):
    text=re.sub(r'\(\*.*?\*\)','',text,flags=re.S)
    if not re.match(r'\s*X86\s+',text): raise Unsupported('not X86')
    match=re.search(r'\{([^{}]*)\}',text,re.S)
    if not match: raise Unsupported('missing initialization')
    initial={}
    for item in match.group(1).split(';'):
        if not item.strip(): continue
        m=re.fullmatch(r'\s*([A-Za-z_]\w*)\s*=\s*(-?\d+)\s*',item)
        if not m: raise Unsupported('unsupported initialization')
        if m[1] in initial: raise Unsupported('duplicate initialization')
        initial[m[1]]=int(m[2])
    rest=text[match.end():]
    if len(re.findall(r'\bexists\b',rest))!=1 or '~exists' in rest: raise Unsupported('only positive exists conditions supported')
    body,condition=rest.split('exists',1)
    if re.search(r'\b(filter|locations|forall)\b',body): raise Unsupported('unsupported filter or declaration')
    rows=[r.strip() for r in body.split(';') if r.strip()]
    if not rows: raise Unsupported('missing threads')
    headers=[r.strip() for r in rows[0].split('|')]
    if any(not re.fullmatch(r'P\d+',h) for h in headers): raise Unsupported('unsupported table header')
    tids=[int(h[1:]) for h in headers]
    if len(set(tids))!=len(tids): raise Unsupported('duplicate thread')
    sequences={t:[] for t in tids};raw=[];lastread={};locations=set(initial)
    for line in rows[1:]:
        columns=line.split('|')
        if len(columns)!=len(tids): raise Unsupported('malformed instruction table')
        for t,ins in zip(tids,columns):
            ins=ins.strip()
            if not ins: continue
            eid=f'e{t}_{len(sequences[t])}'
            store=re.fullmatch(r'MOV\s+\[([A-Za-z_]\w*)\]\s*,\s*\$?(-?\d+)',ins,re.I)
            read=re.fullmatch(r'MOV\s+([A-Za-z][A-Za-z0-9]*)\s*,\s*\[([A-Za-z_]\w*)\]',ins,re.I)
            if store:
                e=Event(eid,'W',store[1],t,int(store[2]));locations.add(store[1])
            elif read:
                e=Event(eid,'R',read[2],t,None);lastread[(t,read[1].upper())]=eid;locations.add(read[2])
            elif ins.upper()=='MFENCE': e=Event(eid,'F',None,t)
            else: raise Unsupported('unsupported instruction: '+ins)
            raw.append(e);sequences[t].append(eid)
    condition=condition.strip()
    if condition.startswith('(') and condition.endswith(')'): condition=condition[1:-1]
    expected={}
    for term in condition.split('/\\'):
        m=re.fullmatch(r'\s*(\d+):([A-Za-z][A-Za-z0-9]*)\s*=\s*(-?\d+)\s*',term)
        if not m: raise Unsupported('only conjunctions of final register equalities supported')
        key=(int(m[1]),m[2].upper())
        if key not in lastread: raise Unsupported('condition is not a final read register')
        eid=lastread[key]
        if eid in expected and expected[eid]!=int(m[3]): raise Unsupported('contradictory repeated condition')
        expected[eid]=int(m[3])
    events=[Event(f'init:{loc}','W',loc,-1,initial.get(loc,0)) for loc in sorted(locations)]
    init=tuple(e.id for e in events)
    events += [Event(e.id,e.kind,e.loc,e.thread,expected.get(e.id,e.value)) for e in raw]
    ev={e.id:e for e in events};local=set();global_=set()
    for seq in sequences.values():
        for i,a in enumerate(seq):
            if ev[a].kind=='F': continue
            for j in range(i+1,len(seq)):
                b=seq[j]
                if ev[b].kind=='F': continue
                if ev[a].loc==ev[b].loc: local.add((a,b))
                if ev[a].kind=='R' or ev[b].kind=='W' or any(ev[x].kind=='F' for x in seq[i+1:j]): global_.add((a,b))
    candidates={e.id:tuple(w.id for w in events if w.kind=='W' and w.loc==e.loc and (e.value is None or e.value==w.value)) for e in events if e.kind=='R'}
    return Instance(tuple(events),(init,tuple(e.id for e in raw)),candidates,
        (Axiom('sc-per-location',tuple(sorted(local)),'all'),Axiom('tso-global',tuple(sorted(global_)),'ext')),
        metadata={'certificate':'single-block-finite-x86','name':name,
                  'thread_sequences':{str(t):s for t,s in sequences.items()},
                  'scope':'Exact supported X86 syntax; all noninitial events in one block; no scalable-history claim.'})


def export_trace(trace,name='generated'):
    """Emit our own protocol as X86 litmus, including every successful-read condition."""
    ev={e.id:e for e in trace['events']};tids=sorted(trace['sequences']);instructions={};conditions=[]
    registers=['EAX','EBX','ECX','EDX','ESI','EDI','EBP']
    # Each read needs a distinct observable register. Large traces use a custom
    # event input instead; silently overwriting read conditions would be unsound.
    for t in tids:
        ops=[];ri=0
        for eid in trace['sequences'][t]:
            e=ev[eid]
            if e.kind=='W': ops.append(f'MOV [{e.loc}],${e.value}')
            elif e.kind=='F': ops.append('MFENCE')
            else:
                if ri==len(registers): raise Unsupported('too many observable reads for X86 exporter')
                r=registers[ri];ri+=1;ops.append(f'MOV {r},[{e.loc}]');conditions.append(f'{t}:{r}={e.value}')
        instructions[t]=ops
    lines=[f'X86 {name}','{ '+'; '.join(f'{ev[e].loc}={ev[e].value}' for e in trace['blocks'][0])+'; }',
           ' | '.join('P'+str(t) for t in tids)+' ;']
    for i in range(max(map(len,instructions.values()))):
        lines.append(' | '.join(instructions[t][i] if i<len(instructions[t]) else '' for t in tids)+' ;')
    lines.append('exists ('+' /\\ '.join(conditions)+')')
    return '\n'.join(lines)+'\n'
