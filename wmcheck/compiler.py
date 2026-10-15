"""Compile bounded interfaces to a layered graph and support CNF."""
from dataclasses import dataclass
from time import perf_counter
from math import factorial,prod
from .model import Registry, local_choices
from .summary import SummaryMachine


class ResourceLimit(RuntimeError): pass


@dataclass(frozen=True)
class Transition:
    layer: int
    source: int
    target: int
    label: tuple[int,...]


@dataclass
class Compiled:
    registry: Registry
    layers: list
    edges: list
    clauses: list
    nvars: int
    stats: dict


def support_cnf(registry,layers,edges,strong=True):
    clauses=[]; ids={}; nv=registry.nvars
    def atom(key):
        nonlocal nv
        if key not in ids: nv+=1;ids[key]=nv
        return ids[key]
    def imply(a,b): clauses.append([-a,b])
    incoming={q:[] for layer in layers for q in layer}
    outgoing={q:[] for layer in layers for q in layer}
    supports={lit:[] for v in registry.by_id for lit in (v,-v)}
    groups={}
    for e in edges: groups.setdefault(e.label,[])
    for label in groups:
        d=atom(('D',label))
        for lit in label: clauses.append([lit,d])
    for j,e in enumerate(edges):
        d=atom(('D',e.label))
        a,b,z=[atom((kind,j)) for kind in ('A','B','Z')]
        imply(d,a);imply(atom(('U',e.source)),a)
        imply(d,b);imply(atom(('V',e.target)),b)
        imply(a,z);imply(atom(('V',e.target)),z)
        incoming[e.target].append(a);outgoing[e.source].append(b)
        groups[e.label].append(z)
    for i,layer in enumerate(layers):
        for q in layer:
            if i: clauses.append([-a for a in incoming[q]]+[atom(('U',q))])
            if i<len(layers)-1: clauses.append([-b for b in outgoing[q]]+[atom(('V',q))])
    start=layers[0][0]
    clauses += [[-atom(('U',start))],[-atom(('V',start))]]
    for q in layers[-1]: clauses.append([-atom(('V',q))])
    # For a complete original assignment, no accepting path is rejected even
    # without support-to-literal clauses. This is a sound weak-propagation ablation.
    if strong:
        for label,zs in groups.items():
            dead=atom(('L',label))
            clauses.append([-z for z in zs]+[dead])
            for lit in label: supports[lit].append(dead)
        for lit,zs in supports.items(): clauses.append([-z for z in zs]+[-lit])
    return clauses,nv


def minimize_suffixes(layers,edges):
    """Trim dead suffixes and merge states with identical labelled futures.

    This is a backwards quotient of a deterministic layered automaton, not
    identification by approximate reachability matrices or current assumptions.
    """
    outgoing={q:[] for layer in layers for q in layer}
    for e in edges: outgoing[e.source].append(e)
    mapping={q:min(layers[-1]) for q in layers[-1]}
    reduced=[[] for _ in layers];reduced[-1]=sorted(set(mapping.values()))
    by_layer=[[] for _ in layers[:-1]]
    for i in range(len(layers)-2,-1,-1):
        signatures={}
        for q in layers[i]:
            signature=tuple(sorted({(e.label,mapping[e.target])
                                    for e in outgoing[q] if e.target in mapping}))
            if not signature and i: continue
            target=signatures.get(signature)
            if target is None:
                target=q;signatures[signature]=q;reduced[i].append(q)
                by_layer[i].extend(Transition(i,q,t,label) for label,t in signature)
            mapping[q]=target
    return reduced,[e for group in by_layer for e in group]


def compile_instance(inst,*,merge=True,strong=True,max_states=100000,max_transitions=1000000,
                     max_local_choices=100000,max_seconds=120,minimize=True,cnf=True,directional=True):
    start=perf_counter();registry=Registry(inst);machine=SummaryMachine(inst,directional=directional)
    states={0:machine.empty};layers=[[0]];edges=[];nextid=1;attempts=0;local_counts=[]
    for i in range(len(inst.blocks)):
        counts={}
        for e in inst.blocks[i]:
            if inst.event[e].kind=='W':
                loc=inst.event[e].loc;counts[loc]=counts.get(loc,0)+1
        upper=prod(factorial(n) for n in counts.values())*prod(len(inst.candidates[e]) for e in inst.blocks[i] if e in inst.candidates)
        if upper>max_local_choices: raise ResourceLimit('local choice upper-bound limit')
        choices=[]
        for choice in local_choices(inst,registry,i):
            choices.append(choice)
            if len(choices)>max_local_choices: raise ResourceLimit('local choice limit')
            if perf_counter()-start>max_seconds: raise ResourceLimit('compile time limit')
        local_counts.append(len(choices));newstates={};by_summary={};layer=[]
        for q in layers[-1]:
            for rf,co,label in choices:
                attempts+=1
                if attempts%256==0 and perf_counter()-start>max_seconds: raise ResourceLimit('compile time limit')
                state=machine.step(i,states[q],rf,co)
                if state is None: continue
                target=by_summary.get(state) if merge else None
                if target is None:
                    target=nextid;nextid+=1;layer.append(target);newstates[target]=state
                    if merge: by_summary[state]=target
                    if nextid>max_states: raise ResourceLimit('state limit')
                edges.append(Transition(i,q,target,label))
                if len(edges)>max_transitions: raise ResourceLimit('transition limit')
        layers.append(layer);states=newstates
    graph_seconds=perf_counter()-start
    raw_states=nextid;raw_transitions=len(edges);raw_max_layer=max(map(len,layers))
    t=perf_counter()
    if minimize and merge: layers,edges=minimize_suffixes(layers,edges)
    minimize_seconds=perf_counter()-t
    t=perf_counter()
    clauses,nvars=support_cnf(registry,layers,edges,strong) if cnf else ([],registry.nvars)
    cnf_seconds=perf_counter()-t
    stats={'compile_seconds':perf_counter()-start,'states':sum(map(len,layers)),'transitions':len(edges),
           'raw_states':raw_states,'raw_transitions':raw_transitions,'raw_max_layer_states':raw_max_layer,
           'graph_seconds':graph_seconds,'minimize_seconds':minimize_seconds,'cnf_seconds':cnf_seconds,
           'attempted_transitions':attempts,'layer_states':[len(x) for x in layers],
           'max_layer_states':max(map(len,layers)),'max_interface':max(len(f.nodes) for f in machine.frames),
           'interface_sizes':[len(f.nodes) for f in machine.frames],
           'local_choices':local_counts,'original_variables':registry.nvars,'cnf_variables':nvars,
           'clauses':len(clauses),'merge':merge,'strong':strong,'cnf':cnf,'minimize':minimize and merge,
           'directional':directional,
           'transition_cache_hits':machine.cache_hits,'transition_cache_misses':machine.cache_misses}
    return Compiled(registry,layers,edges,clauses,nvars,stats)
