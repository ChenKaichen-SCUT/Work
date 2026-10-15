"""Raw unit propagation, explanations, and reversible assumption sessions."""
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class Propagation:
    consistent: bool
    values: dict
    reasons: dict
    conflict_clause: int | None
    clauses: list
    assumptions: tuple

    def explanation(self, literal=None):
        """One sufficient original assumption support, not all minimal supports."""
        todo=[]
        if literal is None:
            if self.consistent: raise ValueError('No conflict to explain')
            if self.conflict_clause is not None:
                todo.extend(-l for l in self.clauses[self.conflict_clause])
            else:
                return tuple(self.assumptions)  # contradictory input assumptions
        else:
            if self.values.get(abs(literal)) != (literal>0): raise ValueError('Literal not derived')
            todo.append(literal)
        visited=set();support=set()
        while todo:
            lit=todo.pop()
            if lit in visited: continue
            visited.add(lit);reason=self.reasons.get(abs(lit))
            if reason is None:
                if lit in self.assumptions: support.add(lit)
            else:
                todo.extend(-q for q in self.clauses[reason] if q!=lit)
        return tuple(sorted(support,key=lambda x:(abs(x),x)))


def unit_propagate(clauses,assumptions=()):
    clauses=[list(dict.fromkeys(c)) for c in clauses]
    occurrence=defaultdict(list);remaining=[];satisfied=[]
    queue=deque((int(l),None) for l in assumptions)
    for i,c in enumerate(clauses):
        remaining.append(len(c));satisfied.append(False)
        for l in c: occurrence[l].append(i)
        if not c: return Propagation(False,{}, {},i,clauses,tuple(assumptions))
        if len(c)==1: queue.append((c[0],i))
    values={};reasons={}
    while queue:
        lit,reason=queue.popleft();v=abs(lit)
        if not v: raise ValueError('Zero is not a literal')
        if v in values:
            if values[v] != (lit>0):
                return Propagation(False,values,reasons,reason,clauses,tuple(assumptions))
            continue
        values[v]=lit>0;reasons[v]=reason
        for i in occurrence[lit]: satisfied[i]=True
        for i in occurrence[-lit]:
            if satisfied[i]: continue
            remaining[i]-=1
            if remaining[i]==0:
                return Propagation(False,values,reasons,i,clauses,tuple(assumptions))
            if remaining[i]==1:
                for q in clauses[i]:
                    if abs(q) not in values:
                        queue.append((q,i));break
    return Propagation(True,values,reasons,None,clauses,tuple(assumptions))


def supports(compiled,assumptions=()):
    """Forward/backward filtering without searching for a full completion."""
    values={}
    for l in assumptions:
        if abs(l) in values and values[abs(l)] != (l>0): return False,set()
        values[abs(l)]=l>0
    enabled=[all(abs(l) not in values or values[abs(l)]==(l>0) for l in e.label) for e in compiled.edges]
    forward={compiled.layers[0][0]}
    for yes,e in zip(enabled,compiled.edges):
        if yes and e.source in forward: forward.add(e.target)
    backward=set(compiled.layers[-1])
    for yes,e in reversed(list(zip(enabled,compiled.edges))):
        if yes and e.target in backward: backward.add(e.source)
    if compiled.layers[0][0] not in backward: return False,set()
    supported=set()
    for yes,e in zip(enabled,compiled.edges):
        if yes and e.source in forward and e.target in backward: supported.update(e.label)
    forced={l for l in supported if -l not in supported}
    return True,forced


class Session:
    """Exact push/pop API; recomputes propagation, not a claimed incremental trail engine."""
    def __init__(self,compiled): self.compiled=compiled;self.trail=[];self.marks=[]
    def push(self,*literals):
        if any(abs(l) not in self.compiled.registry.by_id for l in literals):
            raise ValueError('Only original relation assumptions are public')
        self.marks.append(len(self.trail));self.trail.extend(literals)
        return self.propagate()
    def pop(self):
        if not self.marks: raise IndexError('No decision level')
        del self.trail[self.marks.pop():]
        return self.propagate()
    def propagate(self): return unit_propagate(self.compiled.clauses,self.trail)
