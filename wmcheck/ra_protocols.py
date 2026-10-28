"""Checked finite protocol prefixes, with no RF/CO witness input.

The two templates are the explicitly documented RA adaptations, not arbitrary
program recognizers.  Protocol macros implement the proved prefix lemmas; the
generic kernel only adds reliable necessary facts. CERTIFIED does not mean SAT.
"""
from dataclasses import dataclass
from collections import defaultdict
from copy import deepcopy
from time import perf_counter
from .model import Event
from .ra import RAInstance, RARegistry


@dataclass
class ProtocolInput:
    inst: RAInstance
    contract: dict
    guards: tuple = ()
    allowed_values: dict | None = None


class Outside(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise Outside(reason)


def barrier_instance(rounds, workers=2, failures=0, data=True, long_gap=False,
                     prefixes=None):
    """MCS-architecture star RA adaptation, with genuine two-writer regions.

failures counts real failed reads in every wait. prefixes maps thread numbers
to retained event counts. No generating completion is stored in the input.
"""
    if rounds < 0 or workers < 1 or failures < 0:
        raise ValueError('Nonnegative rounds/failures and positive workers required')
    locs = {f'a{t}': 1 for t in range(1, workers+1)}
    locs.update({f'g{t}': 0 for t in range(1, workers+1)})
    if data:
        locs.update(x=0, y=0)
    if long_gap:
        locs['z'] = 0
    events = [Event('i_'+x, 'W', x, -1, value) for x, value in sorted(locs.items())]
    initial = tuple(e.id for e in events)
    threads = [[] for _ in range(workers+1)]
    positions = {}
    def add(t, i, role, ident, kind, loc, value, peer=None):
        events.append(Event(ident, kind, loc, t, value)); threads[t].append(ident)
        positions[ident] = dict(stage=i, role=role, peer=peer)
    for i in range(1, rounds+1):
        for t in range(1, workers+1):
            if data and t <= 2:
                region = [('ax','W','x'),('ay','W','y'),('ar','R','x')] if t == 1 else [
                    ('by','W','y'),('bx','W','x'),('br','R','y')]
                for name, kind, loc in region:
                    add(t,i,'work',f'w{t}_{i}_{name}',kind,loc,1)
            if long_gap and t == 1:
                kind = 'W' if i in (1, rounds) else 'R'
                add(t,i,'work',f'w{t}_{i}_z',kind,'z',1)
            add(t,i,'arrival',f'A{t}_{i}','W',f'a{t}',0,t)
            for k in range(failures):
                add(t,i,'go_fail',f'S{t}_{i}_f{k}','R',f'g{t}',1-i%2,t)
            add(t,i,'go_success',f'S{t}_{i}','R',f'g{t}',i%2,t)
        for t in range(1, workers+1):
            for k in range(failures):
                add(0,i,'arrival_fail',f'R{t}_{i}_f{k}','R',f'a{t}',1,t)
            add(0,i,'arrival_success',f'R{t}_{i}','R',f'a{t}',0,t)
        for t in range(1, workers+1):
            add(0,i,'reset',f'Z{t}_{i}','W',f'a{t}',1,t)
        for t in range(1, workers+1):
            add(0,i,'go',f'G{t}_{i}','W',f'g{t}',i%2,t)
    inp = ProtocolInput(RAInstance(tuple(events),tuple(map(tuple,threads)),initial),
        dict(family='star_barrier',workers=workers,B=(3 if data else 0)+int(long_gap),
             positions=positions,source='MCS1991 Fig12 architecture; star RA adaptation'))
    return prefix_input(inp,prefixes) if prefixes is not None else inp


def buffer_instance(rounds, capacity=2, mode='value', failures=0, prefixes=None,
                    tail_failures=0, producer_tail_failures=0, data=True):
    """GPS Fig6 RA buffer. Q failures precede each success; tails are retained.

Value mode records a sequential alternating witness's control values, without
passing its RF identities to Build. Branch mode records only the real guards.
"""
    if min(rounds,failures,tail_failures,producer_tail_failures) < 0 or capacity < 1:
        raise ValueError('Bad buffer size')
    if mode not in ('value','branch'):
        raise ValueError('mode must be value or branch')
    modulus=capacity+1
    locs=['wp','rp']+([f'slot{k}' for k in range(modulus)] if data else [])
    events=[Event('i_'+x,'W',x,-1,0) for x in locs]
    initial=tuple(e.id for e in events);threads=[[],[]];attempts=[[],[]];guards=[]
    def attempt(t,count,fail,serial):
        role='P' if t==0 else 'Q';base=f'{role}{serial}'
        own,peer=f'{base}_own',f'{base}_peer'
        ownloc,peerloc=('wp','rp') if t==0 else ('rp','wp')
        ownval=count%modulus
        peerval=((count-capacity)%modulus if fail else count%modulus) if t==0 else (
            count%modulus if fail else (count+1)%modulus)
        reads=[(own,ownloc,ownval),(peer,peerloc,peerval)] if t==0 else [
            (peer,peerloc,peerval),(own,ownloc,ownval)]
        for ident,loc,value in reads:
            events.append(Event(ident,'R',loc,t,value if mode=='value' else None));threads[t].append(ident)
        work=[];update=None
        if not fail:
            if data:
                ident=base+'_data';work.append(ident)
                events.append(Event(ident,'W' if t==0 else 'R',f'slot{count%modulus}',t,1))
                threads[t].append(ident)
            update=f'W{count+1}' if t==0 else f'A{count+1}'
            events.append(Event(update,'W',ownloc,t,(count+1)%modulus));threads[t].append(update)
        g=dict(op='buffer_full' if t==0 else 'buffer_empty',own=own,peer=peer,
               modulus=modulus,outcome=bool(fail))
        guards.append(g)
        attempts[t].append(dict(own=own,peer=peer,work=tuple(work),update=update,
                                outcome=bool(fail),events=tuple(x[0] for x in reads)+tuple(work)+((update,) if update else ())))
    for t in (0,1):
        serial=0
        for count in range(rounds):
            for _ in range(failures if t==1 else 0):
                attempt(t,count,True,serial);serial+=1
            attempt(t,count,False,serial);serial+=1
        for _ in range(producer_tail_failures if t==0 else tail_failures):
            attempt(t,rounds,True,serial);serial+=1
    inp=ProtocolInput(RAInstance(tuple(events),tuple(map(tuple,threads)),initial),
        dict(family='gps_buffer',capacity=capacity,B=int(data),attempts=attempts,
             source='GPS2014 Fig6; fixed RA payload adaptation'),tuple(guards))
    return prefix_input(inp,prefixes) if prefixes is not None else inp


def prefix_input(inp, lengths):
    """Retain actual per-thread prefixes, never remove an internal event."""
    inst=inp.inst; contract=deepcopy(inp.contract)
    threads=tuple(t[:lengths.get(inst.event[t[0]].thread,len(t))] if t else t for t in inst.threads)
    kept=set(inst.initial)|{v for t in threads for v in t}
    guards=tuple(g for g in inp.guards if g['own'] in kept and g['peer'] in kept)
    if contract['family']=='star_barrier':
        contract['positions']={e:p for e,p in contract['positions'].items() if e in kept}
    else:
        for t in range(2):
            remaining=[]
            for a in contract['attempts'][t]:
                actual=tuple(e for e in a['events'] if e in kept)
                if not actual: break
                a=dict(a,events=actual,own=a['own'] if a['own'] in kept else None,
                       peer=a['peer'] if a['peer'] in kept else None,
                       work=tuple(e for e in a['work'] if e in kept),
                       update=a['update'] if a['update'] in kept else None)
                if a['own'] is None or a['peer'] is None: a['outcome']=None
                remaining.append(a)
            contract['attempts'][t]=remaining
    allowed={r:vs for r,vs in (inp.allowed_values or {}).items() if r in kept}
    return ProtocolInput(RAInstance(tuple(e for e in inst.events if e.id in kept),threads,inst.initial),
                         contract,guards,allowed)


def _barrier_check(inp):
    inst,c=inp.inst,inp.contract; m=c['workers']; B=c['B'];positions=c['positions']
    _require(isinstance(m,int) and m>=1 and isinstance(B,int) and B>=0,'bad barrier parameters')
    _require(len(inst.threads)==m+1,'barrier participant count')
    _require(set(positions)==set(inst.event)-set(inst.initial),'program positions must cover actual prefix')
    _require(not inp.guards,'barrier arbitrary guard unsupported')
    protocols={f'a{t}' for t in range(1,m+1)}|{f'g{t}' for t in range(1,m+1)}
    initial={inst.event[x].loc:x for x in inst.initial}
    for loc in protocols:
        _require(loc in initial and inst.event[initial[loc]].value==int(loc[0]=='a'),'barrier initial value')
    mapping={};stages={};failure=set()
    for t,seq in enumerate(inst.threads):
        _require(all(inst.event[e].thread==t for e in seq),'barrier thread role mismatch')
        stage=1;phase='work';peer=1;work_count=0
        for e in seq:
            ev=inst.event[e];p=positions[e];role=p['role']
            _require(p['stage']==stage,'barrier skipped/reordered stage')
            stages[e]=stage
            if phase=='work' and role=='work':
                work_count+=1
                _require(work_count<=B and ev.loc not in protocols,'work bound/protocol address access')
                continue
            if phase=='work': phase='arrival' if t else 'wait'
            if t:
                expected='arrival' if phase=='arrival' else ('go_fail','go_success')
                _require(role==expected if isinstance(expected,str) else role in expected,'worker program prefix')
                _require(p.get('peer')==t,'worker target mismatch')
                if phase=='arrival':
                    _require((ev.kind,ev.loc,ev.value)==('W',f'a{t}',0),'arrival syntax')
                    mapping['A',t,stage]=e;phase='go'
                else:
                    value=1-stage%2 if role=='go_fail' else stage%2
                    _require((ev.kind,ev.loc,ev.value)==('R',f'g{t}',value),'worker polling observation')
                    if role=='go_fail':failure.add(e)
                    else: mapping['S',t,stage]=e;stage+=1;phase='work';work_count=0
            else:
                _require(p.get('peer')==peer,'coordinator target/order mismatch')
                if phase=='wait':
                    _require(role in ('arrival_fail','arrival_success'),'coordinator wait prefix')
                    _require((ev.kind,ev.loc,ev.value)==('R',f'a{peer}',int(role=='arrival_fail')),'arrival read syntax')
                    if role=='arrival_fail':failure.add(e)
                    else:
                        mapping['R',peer,stage]=e;peer+=1
                        if peer>m:phase='reset';peer=1
                elif phase=='reset':
                    _require(role=='reset' and (ev.kind,ev.loc,ev.value)==('W',f'a{peer}',1),'reset prefix')
                    mapping['Z',peer,stage]=e;peer+=1
                    if peer>m:phase='publish';peer=1
                else:
                    _require(role=='go' and (ev.kind,ev.loc,ev.value)==('W',f'g{peer}',stage%2),'wake prefix')
                    mapping['G',peer,stage]=e;peer+=1
                    if peer>m:phase='work';peer=1;stage+=1;work_count=0
    forced={}
    for e,p in positions.items():
        role,i,t=p['role'],p['stage'],p.get('peer')
        if role=='arrival_success':forced[e]=(mapping.get(('A',t,i)),'B3-arrival')
        elif role=='go_success':forced[e]=(mapping.get(('G',t,i)),'B3-go')
        elif role=='arrival_fail':forced[e]=(initial[f'a{t}'] if i==1 else mapping.get(('Z',t,i-1)),'B5-reset')
        elif role=='go_fail':forced[e]=(initial[f'g{t}'] if i==1 else mapping.get(('G',t,i-1)),'B5-go')
    rank={e:j for seq in inst.threads for j,e in enumerate(seq)}
    def key(e):
        p=positions[e];t=inst.event[e].thread
        block=1 if t==0 else (2 if p['role'].startswith('go_') else 0)
        return p['stage'],block,t,rank[e]
    order=inst.initial+tuple(sorted(positions,key=key))
    return forced,order,stages,failure,dict(B=B,p=m+1,a=len(initial),
        c_bound=2*((m+1)*B+5*m),K_bound=2*((m+1)*B+5*m)+len(initial)*(m+1)+(m+1)+len(initial)+1)


def _buffer_check(inp):
    inst,c=inp.inst,inp.contract;C=c['capacity'];M=C+1;B=c['B']
    _require(isinstance(C,int) and C>=1 and isinstance(B,int) and B>=0,'bad buffer parameters')
    _require(len(inst.threads)==2 and len(c['attempts'])==2,'buffer roles')
    initial={inst.event[e].loc:e for e in inst.initial}
    _require(all(x in initial and inst.event[initial[x]].value==0 for x in ('wp','rp')),'buffer initialization')
    writes=[{0:initial['wp']},{0:initial['rp']}];infos=[];stages={};failure=set();expected_guards=[]
    for t,seq in enumerate(inst.threads):
        _require(all(inst.event[e].thread==t for e in seq),'buffer thread role')
        count=0;flatten=[]
        for index,a in enumerate(c['attempts'][t]):
            own,peer=a.get('own'),a.get('peer');outcome=a.get('outcome');work=tuple(a.get('work',()));update=a.get('update')
            expected=((own,peer) if t==0 else (peer,own))
            existing=tuple(x for x in expected if x is not None)+work+((update,) if update else ())
            _require(tuple(a['events'])==existing and set(existing)<=set(seq),'buffer attempt event order')
            _require(bool(existing),'empty attempt')
            if own is None or peer is None:
                _require(index==len(c['attempts'][t])-1 and len(existing)==1 and outcome is None,'only last attempt may be partial')
                _require(existing[0]==(own if t==0 else peer),'missing first index read')
            else:
                _require(outcome in (True,False,None),'buffer branch observation')
            for ident,loc in ((own,'wp' if t==0 else 'rp'),(peer,'rp' if t==0 else 'wp')):
                if ident is not None:_require((inst.event[ident].kind,inst.event[ident].loc)==('R',loc),'index read syntax')
            _require(len(work)<=B and all(inst.event[e].loc not in ('wp','rp') for e in work),'buffer work bound/address')
            if outcome is None or outcome is True:
                _require(not work and not update,'failed/unobserved branch has work')
            if update:
                _require(outcome is False and (inst.event[update].kind,inst.event[update].loc,inst.event[update].value)==
                         ('W','wp' if t==0 else 'rp',(count+1)%M),'index update syntax')
                writes[t][count+1]=update
            elif outcome is not True:
                _require(index==len(c['attempts'][t])-1,'incomplete operation before later call')
            if outcome is not None:
                expected_guards.append(dict(op='buffer_full' if t==0 else 'buffer_empty',own=own,peer=peer,modulus=M,outcome=outcome))
            for e in existing:stages[e]=count+1
            if outcome is True:failure.update(existing)
            infos.append((t,count,a));flatten.extend(existing)
            if update:count+=1
        _require(tuple(flatten)==seq,'buffer attempts must cover actual prefix')
    _require(list(inp.guards)==expected_guards,'guard contract must exactly match observed branches')
    # No data event is permitted to impersonate an additional protocol writer.
    for e in inst.events:
        if e.loc in ('wp','rp') and e.kind=='W':
            _require(e.id in writes[0].values() or e.id in writes[1].values(),'hidden index writer')
    fixed={};windows={}
    for t,count,a in infos:
        own,peer=a.get('own'),a.get('peer');outcome=a.get('outcome')
        if own:fixed[own]=(writes[t].get(count),'F1-own')
        if peer:
            lo,hi=(max(0,count-C),count) if t==0 else (count,count+C)
            if outcome is False:lo=max(lo,count+1-C if t==0 else count+1)
            allowed={w for k,w in writes[1-t].items() if lo<=k<=hi}
            if outcome is not None:
                forbidden=(count+1)%M if t==0 else count%M
                allowed={w for w in allowed if (inst.event[w].value==forbidden)==outcome}
            windows[peer]=(allowed,'F2-F4-window-guard',lo,hi)
    rank={e:i for seq in inst.threads for i,e in enumerate(seq)}
    order=inst.initial+tuple(sorted(stages,key=lambda e:(stages[e],inst.event[e].thread,rank[e])))
    q=max((sum(1 for tt,cc,a in infos if tt==t and cc==stage-1 and a.get('outcome') is True)
           for t in (0,1) for stage in set(stages.values())),default=0)
    metrics=dict(p=2,a=len(initial),B=B,C=C,q=q,c_bound=(C+2)*2*(B+3+2*q),
                 K_bound=(C+2)*2*(B+3+2*q)+3*len(initial)+3,
                 K_chain_bound=2*(C+2)*(B+3)+3*len(initial)+4)
    return fixed,windows,order,stages,failure,metrics


def _closure_bits(nodes,edges):
    index={v:i for i,v in enumerate(nodes)};rows=[0]*len(nodes)
    for a,b in edges:rows[index[a]]|=1<<index[b]
    for k in range(len(nodes)):
        bit=1<<k;row=rows[k]
        for j in range(len(nodes)):
            if rows[j]&bit:rows[j]|=row
    return index,rows


def _saturate(inst,D,trace):
    nodes=tuple(inst.event);base=set(inst.sb)|{(i,t[0]) for i in inst.initial for t in inst.threads if t}
    mandatory=set();covered=set();iterations=0
    while True:
        iterations+=1
        for r in inst.reads:
            if len(D[r])==1:
                pair=(next(iter(D[r])),r)
                if pair not in mandatory:mandatory.add(pair);trace.append(('must-rf',*pair))
        ix,rows=_closure_bits(nodes,base|mandatory|covered)
        H={(a,b) for a in nodes for b in nodes if rows[ix[a]]>>ix[b]&1}
        L={(a,b) for a,b in H if a in inst.write_set and b in inst.write_set and inst.event[a].loc==inst.event[b].loc}
        if any(rows[j]>>j&1 for j in range(len(nodes))) or any(not ws for ws in D.values()):
            return dict(status='PROVED_UNSAT',domains=D,H=H,L=L,mandatory=mandatory,trace=trace,successors=set(),iterations=iterations)
        changed=False
        for r in inst.reads:
            preceding=[z for z in inst.writes if inst.event[z].loc==inst.event[r].loc and rows[ix[z]]>>ix[r]&1]
            for w in sorted(D[r]):
                witness=next((z for z in preceding if rows[ix[w]]>>ix[z]&1),None)
                if rows[ix[r]]>>ix[w]&1 or witness is not None:
                    D[r].remove(w);trace.append(('remove',w,r,'R1' if rows[ix[r]]>>ix[w]&1 else 'R2',witness));changed=True
        if any(not ws for ws in D.values()):continue
        predecessors={v:{v} for v in nodes}
        for a,b in H:predecessors[b].add(a)
        for r in inst.reads:
            ws=tuple(sorted(D[r]));common=set.intersection(*(predecessors[w] for w in ws))
            for a in sorted(common):
                if (a,r) not in H and (a,r) not in covered:
                    covered.add((a,r));trace.append(('Rforall',a,r,ws));changed=True
        if not changed:
            return dict(status='CERTIFIED',domains=D,H=H,L=L,mandatory=mandatory,trace=trace,
                        successors=set(),source_cover_edges=covered,iterations=iterations)


def build_protocol(inp):
    """Deterministic certificate construction; no query or completion parameter."""
    start=perf_counter();inst=inp.inst;trace=[]
    try:
        family=inp.contract.get('family')
        if family=='star_barrier':
            fixed,order,stages,failed,metrics=_barrier_check(inp);windows={}
        elif family=='gps_buffer':
            fixed,windows,order,stages,failed,metrics=_buffer_check(inp)
        else:raise Outside('unsupported protocol family')
        _require(set(inp.allowed_values or {})<=set(inst.reads),'unknown allowed-value read')
    except (Outside,KeyError,TypeError) as exc:
        return dict(status='OUTSIDE',reason=str(exc),pre_seconds=perf_counter()-start)
    D={r:set(ws) for r,ws in inst.candidates.items()}
    for r,values in (inp.allowed_values or {}).items():
        if values is not None:
            try:values=set(values)
            except TypeError:return dict(status='OUTSIDE',reason='allowed values must be explicit',pre_seconds=perf_counter()-start)
            removed=D[r]-{w for w in D[r] if inst.event[w].value in values}
            for w in sorted(removed):trace.append(('remove',w,r,'allowed-value'))
            D[r]-=removed
    for r,(source,rule) in fixed.items():
        for w in sorted(D[r]-{source}):trace.append(('remove',w,r,rule,source))
        D[r]&={source}
    for r,(allowed,rule,lo,hi) in windows.items():
        for w in sorted(D[r]-allowed):trace.append(('remove',w,r,rule,lo,hi))
        D[r]&=allowed
    cert=_saturate(inst,D,trace)
    rank={e:i for i,e in enumerate(order)}
    spans=[]
    for e in order:
        end=max((rank[f] for f in order if rank[f]>rank[e] and inst.event[e].loc==inst.event[f].loc and
                 (inst.event[e].kind=='W' or inst.event[f].kind=='W') and (e,f) not in cert['H']),default=rank[e])
        spans.append((rank[e],end))
    c_actual=max((sum(lo<=cut<hi for lo,hi in spans) for cut in range(len(order))),default=0)
    metrics.update(events=len(inst.events),original_variables=RARegistry(inst).nvars,c_actual=c_actual,
                   retained_rf=sum(map(len,D.values())),undecided_co=sum((a,b) not in cert['L'] and (b,a) not in cert['L']
                    for v,(kind,a,b) in RARegistry(inst).by_id.items() if kind=='co'),failed_reads=len(failed),
                   iterations=cert['iterations'],H_pairs=len(cert['H']),L_pairs=len(cert['L']))
    result=dict(status=cert['status'],certificate=cert,order=order,metrics=metrics,trace=trace,
                stages=stages,failed_reads=failed,pre_seconds=perf_counter()-start)
    return result


def replay_certificate(inp,result):
    """Reconstruct with the same deterministic kernel; not an independent proof checker."""
    fresh=build_protocol(inp)
    if fresh['status']!=result['status']:return False
    if fresh['status']=='OUTSIDE':return fresh['reason']==result.get('reason')
    return all(fresh['certificate'][key]==result['certificate'][key]
               for key in ('domains','H','L','mandatory','trace')) and fresh['order']==result['order']


def buffer_chain_bags(inp,result):
    """Fixed skeleton bags refined by every real failure read chain.

    Bags are planning objects only: no contracted SB edge reaches the semantic
    monitor. All original failures and labels remain present in the final plan.
    """
    _require(inp.contract.get('family')=='gps_buffer' and result['status']=='CERTIFIED','buffer chain requires certificate')
    inst=inp.inst;D=result['certificate']['domains'];L=result['certificate']['L']
    failed=result['failed_reads'];stages=result['stages'];C=inp.contract['capacity']
    skeleton=set(inst.event)-failed;packets=[]
    for seq in inst.threads:
        j=0
        while j<len(seq):
            if seq[j] not in failed:j+=1;continue
            start=j
            while j<len(seq) and seq[j] in failed:j+=1
            chain=seq[start:j];anchors={next(iter(D[r])) for r in chain}
            if start:anchors.add(seq[start-1])
            else:anchors.update(inst.initial)  # Real sparse init-to-thread-first edges.
            if j<len(seq):anchors.add(seq[j])
            _require(anchors<=skeleton,'failure source/SB anchor is not skeleton')
            packets.append((stages[chain[0]],chain,anchors))
    edges=set(inst.sb)
    edges|={(w,r) for r,ws in D.items() for w in ws}
    for a in inst.writes:
        for b in inst.writes:
            if a>=b or inst.event[a].loc!=inst.event[b].loc:continue
            if (a,b) not in L and (b,a) not in L:edges.add((a,b))
    for a,b in L:
        if not any((a,z) in L and (z,b) in L for z in inst.writes):edges.add((a,b))
    edges|={(i,t[0]) for i in inst.initial for t in inst.threads if t}
    order=[e for e in result['order'] if e in skeleton];rank={e:i for i,e in enumerate(order)}
    # Real non-failure edges and registered packet anchor hyperedges.
    obligations=[{a,b} for a,b in edges if a in skeleton and b in skeleton]
    obligations += [anchors for _,_,anchors in packets]
    end={e:rank[e] for e in order}
    packet_at={}
    for stage,chain,anchors in packets:
        eligible=[rank[e] for e in order if e not in inst.initial and stages[e]<=stage]
        at=max(eligible+list(map(rank.get,anchors)),default=len(order)-1)
        packet_at.setdefault(at,[]).append((stage,chain,anchors))
        for e in anchors:end[e]=max(end[e],at)
    for edge in obligations:
        if edge:
            stop=max(rank[e] for e in edge)
            for e in edge:end[e]=max(end[e],stop)
    bags=[];active=set()
    for index,e in enumerate(order):
        active.add(e);bags.append(tuple(sorted(active)))
        for stage,chain,anchors in packet_at.get(index,()):
            _require(anchors<=active,'packet anchor lifetime')
            previous=None
            for r in chain:
                bags.append(tuple(sorted(active|{r}|({previous} if previous else set()))));previous=r
            # The last node coexists with its actual right SB anchor.
        active={v for v in active if end[v]>index}
    return tuple(bags)
