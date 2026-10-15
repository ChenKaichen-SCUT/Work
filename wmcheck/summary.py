"""Exact history interfaces and bitset transition; no completion search."""
from dataclasses import dataclass


def close(rows):
    rows=list(rows)
    for k,row in enumerate(rows):
        mask=1<<k
        for i in range(len(rows)):
            if rows[i]&mask: rows[i] |= row
    return tuple(rows)


def cyclic(rows):
    return any(row&(1<<i) for i,row in enumerate(rows))


def close_dag(rows):
    """Exact closure or None for a cycle, with no recursion-depth limit.

    A completed child's closure skips successors already reached through it.
    Only completed subgraphs may be skipped; active ancestors still detect
    cycles. Every vertex is visited, including vertices later projected away.
    """
    closed=[0]*len(rows); done=0; active=0
    for start in range(len(rows)):
        bit=1<<start
        if done&bit: continue
        stack=[(start,rows[start],0)];active |= bit
        while stack:
            v,pending,reach=stack[-1]
            pending &= ~reach
            if not pending:
                closed[v]=reach;done |= 1<<v;active &= ~(1<<v)
                stack.pop()
                continue
            childbit=pending&-pending;child=childbit.bit_length()-1
            if active&childbit: return None
            if done&childbit:
                stack[-1]=(v,pending,reach|childbit|closed[child])
            else:
                active |= childbit
                stack.append((child,rows[child],0))
    return tuple(closed)


@dataclass
class Frame:
    live: frozenset
    addresses: frozenset
    nodes: tuple
    entries: frozenset
    exits: frozenset


class SummaryMachine:
    def __init__(self, inst, directional=True):
        self.inst=inst
        n=len(inst.blocks)
        # Interval endpoints avoid retaining copies of the entire prefix.
        intervals={}
        def retain(node,start,end):
            if start<=end:
                old=intervals.get(node)
                intervals[node]=(min(start,old[0]),max(end,old[1])) if old else (start,end)
        lastread={}
        for r,ws in inst.candidates.items():
            for w in ws: lastread[w]=max(lastread.get(w,-1),inst.layer[r])
        for w,end in lastread.items(): retain(('live',w),inst.layer[w]+1,end)
        self.fixed_delta=[]
        for ax in inst.axioms:
            delta=[[] for _ in inst.blocks]
            for a,b in ax.fixed:
                la,lb=inst.layer[a],inst.layer[b]
                delta[max(la,lb)].append((a,b))
                if la<lb: retain(('exit',a),la+1,lb)
                if lb<la: retain(('entry',b),lb+1,la)
            self.fixed_delta.append(delta)
        minmem,maxwrite={},{}
        for e in inst.events:
            if e.kind!='F': minmem[e.loc]=min(minmem.get(e.loc,n),inst.layer[e.id])
            if e.kind=='W': maxwrite[e.loc]=max(maxwrite.get(e.loc,-1),inst.layer[e.id])
        for x,end in maxwrite.items(): retain(('address',x),minmem[x]+1,end)
        starts,stops=[[] for _ in range(n+2)],[[] for _ in range(n+2)]
        for node,(start,end) in intervals.items():
            starts[start].append(node); stops[end+1].append(node)
        active=set();self.frames=[]
        for cut in range(n+1):
            active.difference_update(stops[cut]);active.update(starts[cut])
            live=frozenset(x for kind,x in active if kind=='live')
            entry={('e',x) for kind,x in active if kind=='entry'}
            exit_nodes={('e',x) for kind,x in active if kind=='exit'}
            addresses=frozenset(x for kind,x in active if kind=='address')
            nodes={('e',e) for e in live}|entry|exit_nodes
            nodes.update(('in',cut,s) for s in live)
            nodes.update(('out',cut,x) for x in addresses)
            entry.update(('in',cut,s) for s in live)
            exit_nodes.update(('e',s) for s in live)
            exit_nodes.update(('out',cut,x) for x in addresses)
            if not directional: entry=nodes;exit_nodes=nodes
            self.frames.append(Frame(live,addresses,tuple(sorted(nodes,key=repr)),
                                     frozenset(entry),frozenset(exit_nodes)))
        self.empty=tuple(() for _ in inst.axioms)
        self.templates={};self.transition_cache={};self.cache_hits=0;self.cache_misses=0

    def template(self,i,rf,co):
        inst=self.inst
        old,new=self.frames[i],self.frames[i+1]
        block=inst.blocks[i]
        nodes=tuple(dict.fromkeys(old.nodes+tuple(('e',e) for e in block)+new.nodes))
        ix={e:j for j,e in enumerate(nodes)}
        newwrites=[e for e in block if inst.event[e].kind=='W']
        result=[]
        for ai,ax in enumerate(inst.axioms):
            rows=[0]*len(nodes)
            def edge(a,b): rows[ix[a]] |= 1<<ix[b]
            def real(a,b): edge(('e',a),('e',b))
            for a,b in self.fixed_delta[ai][i]: real(a,b)
            if ax.co:
                for a,b in co: real(a,b)
            for w in newwrites:
                x=inst.event[w].loc
                if x in old.addresses: edge(('out',i,x),('e',w))
            for r,s in rf.items():
                if ax.rf_mode=='all' or (ax.rf_mode=='ext' and inst.event[s].thread!=inst.event[r].thread):
                    real(s,r)
                if ax.fr:
                    if inst.layer[s]<i:
                        edge(('e',r),('in',i,s))
                        for v in newwrites:
                            if inst.event[v].loc==inst.event[s].loc: real(r,v)
                    else:
                        for u,v in co:
                            if u==s: real(r,v)
            for x in new.addresses:
                if x in old.addresses: edge(('out',i,x),('out',i+1,x))
                for e in block:
                    ev=inst.event[e]
                    if ev.loc==x and ((ev.kind=='W' and ax.co) or (ev.kind=='R' and ax.fr)):
                        edge(('e',e),('out',i+1,x))
            if ax.fr:
                for s in new.live:
                    if inst.layer[s]<i:
                        edge(('in',i+1,s),('in',i,s))
                        for v in newwrites:
                            if inst.event[v].loc==inst.event[s].loc: edge(('in',i+1,s),('e',v))
                    else:
                        for u,v in co:
                            if u==s: edge(('in',i+1,s),('e',v))
            result.append(tuple(rows))
        return tuple(result),tuple(ix[a] for a in new.nodes)

    def step(self,i,state,rf,co):
        key=(i,tuple(sorted(rf.items())),co)
        if key not in self.templates: self.templates[key]=self.template(i,rf,co)
        template,projection=self.templates[key]
        frame=self.frames[i+1]
        entries=tuple(j for j,node in enumerate(frame.nodes) if node in frame.entries)
        exits=tuple(j for j,node in enumerate(frame.nodes) if node in frame.exits)
        cachekey=(template,projection,entries,exits,state)
        if cachekey in self.transition_cache:
            self.cache_hits+=1
            return self.transition_cache[cachekey]
        self.cache_misses+=1
        result=[]
        for base,oldrows in zip(template,state):
            rows=list(base)
            # Old interface nodes occupy the first positions by construction.
            for j,row in enumerate(oldrows): rows[j] |= row
            rows=close_dag(rows)
            if rows is None:
                self.transition_cache[cachekey]=None
                return None
            projected=[0]*len(projection)
            for a in entries:
                projected[a]=sum(1<<j for j in exits if rows[projection[a]]&(1<<projection[j]))
            result.append(tuple(projected))
        value=tuple(result);self.transition_cache[cachekey]=value
        return value
