"""Complete relation propagation on the compiled DAG without SAT auxiliaries.

Queries reuse the graph and literal index, but recompute forward/backward
reachability. No claim of an incremental trail or general Boolean solver.
"""
class GraphSolver:
    def __init__(self,compiled):
        self.compiled=compiled
        self.groups={};self.edges=[]
        self.literal_groups={l:0 for v in compiled.registry.by_id for l in (v,-v)}
        for e in compiled.edges:
            if e.label not in self.groups:
                g=len(self.groups);self.groups[e.label]=g
                for l in e.label: self.literal_groups[l] |= 1<<g
            self.edges.append((e.source,e.target,self.groups[e.label],e.label))
        self.start=compiled.layers[0][0]
        self.accepting=set(compiled.layers[-1])

    def _paths(self,assumptions):
        disabled=0;seen=set()
        for l in assumptions:
            if abs(l) not in self.compiled.registry.by_id:
                raise ValueError('Only original relation assumptions are public')
            if -l in seen: return None
            seen.add(l);disabled |= self.literal_groups[-l]
        enabled=[not (disabled>>g)&1 for _,_,g,_ in self.edges]
        forward={self.start}
        for yes,(source,target,_,_) in zip(enabled,self.edges):
            if yes and source in forward: forward.add(target)
        if not forward&self.accepting: return None
        backward=set(self.accepting)
        for j in range(len(self.edges)-1,-1,-1):
            source,target,_,_=self.edges[j]
            if enabled[j] and target in backward: backward.add(source)
        return enabled,forward,backward

    def propagate(self,assumptions=()):
        paths=self._paths(assumptions)
        if paths is None: return False,set()
        enabled,forward,backward=paths; supported=0
        for yes,(source,target,g,_) in zip(enabled,self.edges):
            if yes and source in forward and target in backward: supported |= 1<<g
        forced=set()
        for v in self.compiled.registry.by_id:
            if not self.literal_groups[v]&supported: forced.add(-v)
            if not self.literal_groups[-v]&supported: forced.add(v)
        return True,forced

    def witness(self,assumptions=()):
        paths=self._paths(assumptions)
        if paths is None: return None
        enabled,_,backward=paths;current=self.start;assignment=set()
        for yes,(source,target,_,label) in zip(enabled,self.edges):
            if yes and source==current and target in backward:
                assignment.update(label);current=target
        assert current in self.accepting
        return assignment
