"""Exact RA factorization under a checked acyclic object traversal.

Unlike an arbitrary split by address, every cross-object SB edge must follow
one checked DAG. HB cannot leave an object and return; ECO is address-local.
Consequently all RA consistency obstructions, and all original variables, are
object-local. See docs/OBJECT_LOCALIZATION_THEOREM.zh.txt for the proof and a
two-object cyclic counterexample. This API never assumes a chosen RF/CO model.
"""
from time import perf_counter
from .compiler import Compiled, ResourceLimit, Transition, support_cnf
from .ra import RAInstance, RARegistry
from .ra_frontier import compile_frontier
from .ra_object_layout import object_layout


def compile_objects(inst, location_owner, *, cnf=False, max_seconds=90,
                    max_states=300000, max_edges=1000000, **options):
    begin = perf_counter()
    certificate = object_layout(inst, location_owner)
    owner = certificate['event_owner']
    registry = RARegistry(inst)
    layers, edges, previous = [[0]], [], [0]
    next_id = 1
    local_stats = []
    peak = 0
    options = dict(options)
    if 'order' in options or 'elide_init_hb' in options:
        raise ValueError('Object compilation owns the layout and initial-HB policy')
    for obj in certificate['object_order']:
        events = tuple(e for e in inst.events if owner[e.id] == obj)
        threads = tuple(tuple(v for v in seq if owner[v] == obj) for seq in inst.threads)
        initial = tuple(i for i in inst.initial if owner[i] == obj)
        local = RAInstance(events, tuple(seq for seq in threads if seq), initial)
        remaining = max_seconds-(perf_counter()-begin)
        if remaining <= 0:
            raise ResourceLimit('Object compilation time limit')
        order = local.initial+tuple(v for seq in local.threads for v in seq)
        compiled = compile_frontier(local, order=order, cnf=False, elide_init_hb=True,
            max_seconds=remaining, max_states=max_states-next_id, max_edges=max_edges-len(edges), **options)
        peak = max(peak, compiled.stats.get('max_interface', 0))
        local_stats.append(dict(object=obj, **compiled.stats))
        mapping = {}
        for layer in compiled.layers:
            for state in layer:
                mapping[state] = next_id
                next_id += 1
        base_layer = len(layers)
        start = mapping[compiled.layers[0][0]]
        edges.extend(Transition(base_layer-1, state, start, ()) for state in previous)
        layers.extend([[mapping[state] for state in layer] for layer in compiled.layers])
        variables = {v: registry.by_key[key] for v, key in compiled.registry.by_id.items()}
        for edge in compiled.edges:
            label = tuple(variables[abs(lit)]*(1 if lit > 0 else -1) for lit in edge.label)
            edges.append(Transition(base_layer+edge.layer, mapping[edge.source], mapping[edge.target], label))
        previous = layers[-1]
        if next_id > max_states or len(edges) > max_edges:
            raise ResourceLimit('Object compilation state/edge limit')
    clauses, nvars = support_cnf(registry, layers, edges) if cnf else ([], registry.nvars)
    stats = dict(algorithm='acyclic-object-product', states=next_id, transitions=len(edges),
        original_variables=registry.nvars, clauses=len(clauses), cnf_variables=nvars,
        compile_seconds=perf_counter()-begin, max_interface=peak,
        theorem_interface_bound=certificate['max_events_per_object']+certificate['max_initials_per_object'],
        objects=certificate['objects'], elide_initial_hb=True, factorization=True,
        local_stats=local_stats, layer_states=list(map(len, layers)),
        label_literals=sum(len(edge.label) for edge in edges))
    return Compiled(registry, layers, edges, clauses, nvars, stats)
