"""Binary candidate processing, joint regular summaries, final CO successors.

Never enumerates a block Cartesian product, complete CO orders or conflict
supports. Exponential summary growth is still possible; resource failures are
UNKNOWN (exceptions), never a consistency answer.
"""
from time import perf_counter
from dataclasses import dataclass
from .ra import RARegistry, recognize
from .compiler import Compiled, Transition, ResourceLimit, support_cnf
from .regular_monitor import ra_monitors, update
from .port_monitor import ra_port_monitors, plan_ports


@dataclass(frozen=True)
class FrontierPlan:
    """A completion/query-independent candidate plan. Treat contained maps as read-only.

    External certificates are a *given valid certificate* interface: structural
    checks here do not prove arbitrary submitted must facts semantically sound.
    Protocol callers must validate/replay their own proof rules before calling.
    """
    instance_signature: tuple
    registry: object
    certificate: dict
    constants: tuple
    groups: tuple
    order: tuple
    rank: dict
    last: dict
    due: dict
    monitors: tuple
    port_plans: object
    stats: dict
    options: dict


def _signature(inst):
    return (tuple(inst.events), tuple(map(tuple, inst.threads)), tuple(inst.initial))


def _checked_certificate(inst, certificate):
    """Check finite structural obligations, not semantic entailment of must facts."""
    if certificate.get('status') not in ('CERTIFIED', 'RECOGNIZED', 'PROVED_UNSAT'):
        raise ValueError('Certificate must be CERTIFIED, RECOGNIZED or PROVED_UNSAT')
    cert = dict(certificate)
    cert['trace'] = tuple(cert.get('trace', ()))
    if cert['status'] == 'PROVED_UNSAT':
        return cert
    D = {r: frozenset(ws) for r, ws in cert['domains'].items()}
    if set(D) != set(inst.reads) or any(not D[r] or not D[r] <= set(inst.candidates[r]) for r in D):
        raise ValueError('Certificate domains must be nonempty original-source subsets')
    H, L = frozenset(cert['H']), frozenset(cert['L'])
    nodes = set(inst.event)
    for name, relation in (('H', H), ('L', L)):
        if any(a not in nodes or b not in nodes or a == b for a, b in relation):
            raise ValueError(f'{name} must be an irreflexive event relation')
        # Integer bitsets verify transitivity without repeated set closures.
        positions = {v: i for i, v in enumerate(inst.event)}
        rows = {v: 0 for v in inst.event}
        for a, b in relation:
            rows[a] |= 1 << positions[b]
        if any(rows[b] & ~rows[a] for a, b in relation):
            raise ValueError(f'{name} must already be transitively closed')
    if not inst.sb <= H:
        raise ValueError('Certificate H omits program order')
    if any((i, e) not in H for i in inst.initial for e in nodes if e not in inst.initial):
        raise ValueError('Certificate H omits initialization precedence')
    if any(a not in inst.write_set or b not in inst.write_set or
           inst.event[a].loc != inst.event[b].loc for a, b in L):
        raise ValueError('L must contain only same-address write pairs')
    if any((a, b) not in L for a, b in H if a in inst.write_set and b in inst.write_set
           and inst.event[a].loc == inst.event[b].loc):
        raise ValueError('Certificate L omits same-address write H')
    singles = frozenset((next(iter(ws)), r) for r, ws in D.items() if len(ws) == 1)
    mandatory = frozenset(cert.get('mandatory', singles))
    if mandatory != singles or not mandatory <= H:
        raise ValueError('Mandatory RF must equal singleton domains and occur in H')
    cert.update(domains=D, H=H, L=L, mandatory=mandatory,
                successors=frozenset(cert.get('successors', ())))
    return cert


def _check_groups(registry, constants, groups):
    owners = {}
    for lit in constants:
        if abs(lit) in owners:
            raise ValueError('Original constant owned more than once')
        owners[abs(lit)] = -1
    for i, (vertices, alternatives) in enumerate(groups):
        if not alternatives:
            raise ValueError('Empty group')
        domain = set(vertices)
        expected = None
        for labels, additions, increments in alternatives:
            variables = {abs(lit) for lit in labels}
            if len(variables) != len(labels) or any(type(lit) is not int or not lit for lit in labels):
                raise ValueError('Malformed original labels')
            if expected is None:
                expected = variables
            if variables != expected:
                raise ValueError('All alternatives must assign the same original variables')
            if any(a not in domain or b not in domain for _, a, b in additions):
                raise ValueError('Group misses a relation endpoint')
            if any(v not in domain for v, _ in increments):
                raise ValueError('Group misses a counter endpoint')
        for v in expected:
            if v in owners:
                raise ValueError('Original variable owned by multiple groups')
            owners[v] = i
    if set(owners) != set(registry.by_id):
        raise ValueError('Plan must own every original RF/CO variable exactly once')


def prepare_frontier(inst, *, order=None, certificate=None, bags=None, group_order=None,
                     chain=True, incremental=True, compact=True,
                     sparse_init=True, early_degrees=False, co_mode='successor',
                     summary_mode='full', source_covers=False, rf_mode='binary',
                     elide_init_hb=False, dense_co_generators=False):
    if certificate is not None and co_mode != 'direct':
        raise ValueError('External certificates require direct CO; successor candidates need a separate proof')
    if dense_co_generators and co_mode != 'direct':
        raise ValueError('Dense CO generator ablation requires direct CO')
    if rf_mode not in ('binary', 'atomic'):
        raise ValueError('Expected binary or atomic RF groups')
    if co_mode not in ('successor','direct'):
        raise ValueError('Expected successor or direct CO generators')
    if summary_mode not in ('full', 'ports'):
        raise ValueError('Expected full or ports summary')
    if summary_mode == 'ports' and co_mode != 'direct':
        raise ValueError('Future-port summaries currently require direct CO generators')
    if summary_mode == 'ports' and (not incremental or not compact):
        raise ValueError('Future-port summaries use their own incremental one-mark monitor encoding')
    begin = perf_counter(); registry = RARegistry(inst)
    registry_seconds = perf_counter()-begin
    start = perf_counter()
    cert = recognize(inst, chain=chain, source_covers=source_covers) if certificate is None else certificate
    certificate_seconds = perf_counter()-start
    start = perf_counter(); cert = _checked_certificate(inst, cert)
    check_seconds = perf_counter()-start
    options = dict(incremental=incremental, compact=compact, sparse_init=sparse_init,
                   early_degrees=early_degrees, co_mode=co_mode, summary_mode=summary_mode,
                   source_covers=source_covers, rf_mode=rf_mode, elide_init_hb=elide_init_hb,
                   dense_co_generators=dense_co_generators)
    constants, groups = [], []
    if cert['status'] == 'PROVED_UNSAT':
        return FrontierPlan(_signature(inst), registry, cert, (), (), (), {}, {}, {}, (), None,
            dict(registry_seconds=registry_seconds, certificate_seconds=certificate_seconds,
                 check_seconds=check_seconds, group_seconds=0.0, plan_seconds=0.0,
                 prepare_seconds=perf_counter()-begin, actual_K=0, groups=0,
                 external_certificate=certificate is not None), options)
    group_start = perf_counter()
    D, H, L, mandatory = (cert[k] for k in ('domains', 'H', 'L', 'mandatory'))
    # A group is (endpoints, [(label, edge additions, degree increments)]).
    def fixed(symbol, a, b, counters=()):
        additions = ((symbol, a, b),) + ((('R', b, a),) if symbol == 'r' else ())
        groups.append(((a, b), [((), additions, counters)]))
    for a, b in sorted(inst.sb):
        fixed('s', a, b)
    # Initialization is HB-before every non-initial event. Do not install H/L
    # dense closures as graph edges: only sb adjacency, init and mandatory RF.
    # sb adjacency already reaches every later event of the same thread.
    # Initial-to-first edges therefore have exactly the same transitive HB
    # closure as initial-to-all edges, without artificially dense frontiers.
    init_targets = [t[0] for t in inst.threads if t] if sparse_init else [
        e.id for e in inst.events if e.id not in inst.initial]
    # An initialization write has no incoming HB edge and no incoming ECO
    # path when it is CO-minimal. Extra HB edges starting there therefore
    # cannot create an HB;ECO? cycle. Keep its RF/CO identities, but optionally
    # omit these redundant global HB edges so object-local initials can retire.
    # See docs/OBJECT_LOCALIZATION_THEOREM.zh.txt, Lemma 1.
    for i in (() if elide_init_hb else inst.initial):
        for target in init_targets:
            fixed('s', i, target)
    for v, (kind, a, b) in registry.by_id.items():
        if kind == 'rf':
            if a not in D[b]:
                constants.append(-v)
            elif (a, b) in mandatory:
                constants.append(v); fixed('r', a, b, ((b, 0),))
            elif rf_mode == 'binary':
                groups.append(((a, b), [((-v,), (), ()),
                                        ((v,), (('r', a, b), ('R', b, a)), ((b, 0),))]))
        elif (a, b) in L or (b, a) in L:
            constants.append(v if (a, b) in L else -v)
        else:
            symbol = 'c' if co_mode == 'direct' else 'q'
            groups.append(((a, b), [((v,), ((symbol, a, b),), ()), ((-v,), ((symbol, b, a),), ())]))
    if rf_mode == 'atomic':
        # One-hot source choice is a single transition. All original RF bits
        # remain owned and labelled; this eliminates incomplete choices only.
        for read, domain in D.items():
            if len(domain) <= 1:
                continue
            writers = sorted(domain, key=inst.writes.index)
            alternatives = []
            for selected in writers:
                label = tuple(registry.literal(('rf', w, read)) *
                              (1 if w == selected else -1) for w in writers)
                alternatives.append((label, (('r', selected, read), ('R', read, selected)),
                                     ((read, 0),)))
            groups.append(((read, *writers), alternatives))
    if co_mode == 'direct':
        # The chosen original CO directions and a cover of mandatory L generate
        # a total reachability relation. Acyclicity makes its closure a strict
        # total order; no separate final-successor witness needs to be guessed.
        for a, b in sorted(L):
            if dense_co_generators or not any((a,z) in L and (z,b) in L for z in inst.writes):
                fixed('c',a,b)
    else:
        for a, b in sorted(cert['successors']):
            groups.append(((a, b), [((), (), ()), ((), (('c', a, b),), ((a, 2), (b, 1)))]))
    # Isolated vertices also need their final degree checks.
    for e in inst.events:
        groups.append(((e.id,), [((), (), ())]))
    if order is None:
        order = tuple(e.id for e in inst.events)
    if len(order) != len(set(order)) or set(order) != set(inst.event):
        raise ValueError('Layout order must contain every event exactly once')
    rank = {v: i for i, v in enumerate(order)}
    # Freeze canonical groups before a query/completion-independent permutation.
    groups = tuple((tuple(vs), tuple((tuple(ls), tuple(es), tuple(cs)) for ls, es, cs in alts))
                   for vs, alts in groups)
    _check_groups(registry, constants, groups)
    group_seconds = perf_counter()-group_start
    plan_start = perf_counter()
    if bags is not None and group_order is not None:
        raise ValueError('Supply bags or group_order, not both')
    declared_K = None
    if bags is not None:
        bags = tuple(frozenset(bag) for bag in bags)
        occurrences = {v: set() for v in inst.event}
        for i, bag in enumerate(bags):
            if not bag <= set(inst.event):
                raise ValueError('Bag contains unknown events')
            for v in bag:
                occurrences[v].add(i)
        if any(not positions or max(positions)-min(positions)+1 != len(positions)
               for positions in occurrences.values()):
            raise ValueError('Every event needs a nonempty continuous bag lifetime')
        places = []
        for vertices, _ in groups:
            common = set.intersection(*(occurrences[v] for v in vertices))
            if not common:
                raise ValueError(f'No bag covers all alternatives of a group: {vertices!r}')
            places.append(min(common))
        permutation = sorted(range(len(groups)), key=lambda i: (places[i], i))
        declared_K = max(map(len, bags), default=0)
        schedule_kind = 'bags'
    elif group_order is not None:
        permutation = tuple(group_order)
        if any(type(i) is not int for i in permutation) or sorted(permutation) != list(range(len(groups))):
            raise ValueError('group_order must be a permutation of every canonical group index')
        schedule_kind = 'explicit-groups'
    else:
        permutation = sorted(range(len(groups)), key=lambda i: (
            max(rank[v] for v in groups[i][0]), min(rank[v] for v in groups[i][0])))
        schedule_kind = 'event-order'
    groups = tuple(groups[i] for i in permutation)
    last = {v: i for i, (vertices, _) in enumerate(groups) for v in vertices}
    first = {}
    for i, (vertices, _) in enumerate(groups):
        for v in vertices:
            first.setdefault(v, i)
    active = set(); widths = []
    for i, (vertices, _) in enumerate(groups):
        active.update(vertices); widths.append(len(active))
        active.difference_update(v for v in vertices if last[v] == i)
    actual_K = max(widths, default=0)
    if declared_K is not None and actual_K > declared_K:
        raise AssertionError('Constructed plan exceeds checked bag certificate')
    # A required degree can become impossible before its vertex is forgotten.
    # No suffix can repair degree zero after its last possible increment.
    degree_deadline = {}
    if early_degrees:
        for step, (_, alternatives) in enumerate(groups):
            for _, _, increments in alternatives:
                for v, field in increments:
                    if field == 0 or (field == 1 and v not in inst.initial):
                        degree_deadline[v, field] = step
    due = {}
    for key, step in degree_deadline.items():
        due.setdefault(step, []).append(key)
    monitors = ra_monitors(compact=compact)
    if co_mode == 'direct':
        monitors = monitors[:2]  # RA coherence and CO acyclicity; no Q/c binding.
    port_plans = None
    if summary_mode == 'ports':
        monitors = ra_port_monitors()
        port_plans = plan_ports(monitors, groups)
    stats = dict(registry_seconds=registry_seconds, certificate_seconds=certificate_seconds,
                 check_seconds=check_seconds, group_seconds=group_seconds,
                 plan_seconds=perf_counter()-plan_start, prepare_seconds=perf_counter()-begin,
                 actual_K=actual_K, declared_K=declared_K, groups=len(groups),
                 layer_interfaces=widths, group_permutation=list(permutation),
                 event_first=first, event_last=last, schedule_kind=schedule_kind,
                 external_certificate=certificate is not None,
                 candidate_pairs=len({frozenset(vs) for vs, _ in groups if len(vs) > 1}),
                 original_variables=registry.nvars)
    return FrontierPlan(_signature(inst), registry, cert, tuple(constants), groups, tuple(order),
                        rank, last, due, tuple(monitors), port_plans, stats, options)


def compile_frontier(inst, *, order=None, cnf=False, merge=True, max_states=30000,
                     max_edges=200000, max_seconds=90, chain=True, incremental=True, compact=True,
                     sparse_init=True, early_degrees=False, co_mode='successor',
                     summary_mode='full', source_covers=False, rf_mode='binary',
                     elide_init_hb=False, certificate=None, bags=None, group_order=None,
                     prepared=None, dense_co_generators=False):
    """Compile a fixed prepared plan, or prepare once using the historical API.

    With ``prepared`` the plan's options are authoritative; limits, merge and
    CNF construction remain per-call options. No query assumptions are accepted.
    """
    begin = perf_counter()
    reused = prepared is not None
    if prepared is None:
        prepared = prepare_frontier(inst, order=order, certificate=certificate, bags=bags,
            group_order=group_order, chain=chain, incremental=incremental, compact=compact,
            sparse_init=sparse_init, early_degrees=early_degrees, co_mode=co_mode,
            summary_mode=summary_mode, source_covers=source_covers, rf_mode=rf_mode,
            elide_init_hb=elide_init_hb, dense_co_generators=dense_co_generators)
    elif any(v is not None for v in (order, certificate, bags, group_order)):
        raise ValueError('A prepared plan cannot be combined with new plan inputs')
    if prepared.instance_signature != _signature(inst):
        raise ValueError('Prepared plan belongs to a different fixed input')
    registry, cert = prepared.registry, prepared.certificate
    constants, groups = prepared.constants, prepared.groups
    rank, last, due = prepared.rank, prepared.last, prepared.due
    monitors, port_plans = prepared.monitors, prepared.port_plans
    incremental, compact, sparse_init, early_degrees, co_mode, summary_mode, source_covers, rf_mode, elide_init_hb = (
        prepared.options[k] for k in ('incremental', 'compact', 'sparse_init', 'early_degrees',
            'co_mode', 'summary_mode', 'source_covers', 'rf_mode', 'elide_init_hb'))
    recognition_seconds = perf_counter()-begin
    if cert['status'] == 'PROVED_UNSAT':
        clauses = [[]] if cnf else []
        return Compiled(registry, [[0], []], [], clauses, registry.nvars,
            dict(prepared.stats, algorithm='frontier', states=1, transitions=0,
                 original_variables=registry.nvars, recognition='PROVED_UNSAT',
                 compile_seconds=perf_counter()-begin, state_build_seconds=0.0,
                 prepared_reused=reused, clauses=len(clauses)))
    D, H, L, mandatory = (cert[k] for k in ('domains', 'H', 'L', 'mandatory'))
    state_begin = perf_counter()
    layers, edges = [[0], [1]], [Transition(0, 0, 1, tuple(constants))]
    empty = tuple(((), ()) if port_plans is not None else () for _ in monitors)
    states, nextid = {1: (empty, ())}, 2
    before = (); attempts = 0; width = 0; layer_width = []; max_layer = 1
    monitor_updates = 0; monitor_cache_hits = 0
    for step, (vertices, alternatives) in enumerate(groups):
        active = tuple(sorted(set(before) | set(vertices), key=rank.get))
        after = tuple(v for v in active if last[v] != step)
        forgotten = set(active)-set(after)
        width = max(width, len(active)); layer_width.append(len(active))
        newstates, by_summary, layer = {}, {}, []
        monitor_caches = [{} for _ in monitors]
        for source in layers[-1]:
            matrices, degrees = states[source]
            counts = dict(zip(before, degrees))
            for v in active:
                counts.setdefault(v, (0, 0, 0))
            for alternative_index, (label, additions, increments) in enumerate(alternatives):
                attempts += 1
                local = dict(counts); reject = False
                for v, field in increments:
                    current = list(local[v]); current[field] += 1
                    if current[field] > 1:
                        reject = True; break
                    local[v] = tuple(current)
                if reject:
                    continue
                if early_degrees and any(local[v][field] != 1 for v, field in due.get(step, ())):
                    continue
                for v in forgotten:
                    if inst.event[v].kind == 'R' and local[v][0] != 1:
                        reject = True
                    if co_mode != 'direct' and inst.event[v].kind == 'W' and v not in inst.initial and local[v][1] != 1:
                        reject = True
                if reject:
                    continue
                newmat = []
                for monitor_index, (monitor, matrix) in enumerate(zip(monitors, matrices)):
                    if port_plans is None:
                        result = update(monitor, matrix, before, active, after, additions, incremental=incremental)
                        monitor_updates += 1
                    else:
                        cache = monitor_caches[monitor_index]
                        key = (matrix, alternative_index)
                        if key in cache:
                            result = cache[key]; monitor_cache_hits += 1
                        else:
                            result = port_plans[monitor_index][step].update(matrix, alternative_index)
                            cache[key] = result; monitor_updates += 1
                    if result is None:
                        reject = True; break
                    newmat.append(result)
                if reject:
                    continue
                state = (tuple(newmat), tuple(local[v] for v in after))
                target = by_summary.get(state) if merge else None
                if target is None:
                    target = nextid; nextid += 1; layer.append(target); newstates[target] = state
                    if merge:
                        by_summary[state] = target
                edges.append(Transition(step+1, source, target, label))
                if nextid > max_states or len(edges) > max_edges:
                    error = ResourceLimit('Frontier state/edge limit')
                    error.stats = dict(prepared.stats, states=nextid, transitions=len(edges), step=step,
                        groups=len(groups), max_interface=width, current_interface=len(active),
                        max_layer_states=max(max_layer,len(layer)), early_degrees=early_degrees,
                        co_mode=co_mode, summary_mode=summary_mode, status='UNKNOWN',
                        resource_reason='STATE_LIMIT' if nextid > max_states else 'EDGE_LIMIT',
                        state_build_seconds=perf_counter()-state_begin,
                        compile_seconds=perf_counter()-begin, layer_states=list(map(len, layers)))
                    raise error
            if perf_counter()-begin > max_seconds:
                error = ResourceLimit('Frontier compile time limit')
                error.stats = dict(prepared.stats, states=nextid, transitions=len(edges), step=step,
                    groups=len(groups), max_interface=width, current_interface=len(active),
                    max_layer_states=max(max_layer,len(layer)), early_degrees=early_degrees,
                    co_mode=co_mode, summary_mode=summary_mode, status='UNKNOWN',
                    resource_reason='TIME_LIMIT', state_build_seconds=perf_counter()-state_begin,
                    compile_seconds=perf_counter()-begin, layer_states=list(map(len, layers)))
                raise error
        layers.append(layer); states = newstates; before = after; max_layer = max(max_layer, len(layer))
    graph_seconds = perf_counter()-begin
    state_build_seconds = perf_counter()-state_begin
    clauses, nvars = support_cnf(registry, layers, edges) if cnf else ([], registry.nvars)
    labels = {e.label for e in edges}
    stats = dict(prepared.stats, algorithm='frontier' if merge else 'frontier-unfold', compile_seconds=perf_counter()-begin,
                 recognition_seconds=recognition_seconds, graph_seconds=graph_seconds,
                 state_build_seconds=state_build_seconds, prepared_reused=reused,
                 cnf_seconds=perf_counter()-begin-graph_seconds, states=nextid, transitions=len(edges),
                 attempted_transitions=attempts, max_interface=width, max_layer_states=max_layer,
                 layer_states=list(map(len, layers)), monitor_states=[m.size for m in monitors],
                 clauses=len(clauses), cnf_variables=nvars,
                 label_literals=sum(len(e.label) for e in edges), unique_labels=len(labels),
                 unique_label_literals=sum(map(len, labels)), certified_rf=sum(map(len, D.values())),
                 initial_rf=sum(map(len, inst.candidates.values())), mandatory_rf=len(mandatory),
                 successor_candidates=len(cert['successors']), recognition_steps=len(cert['trace']))
    stats['incremental_closure'] = incremental
    stats['compact_rotation'] = compact if port_plans is None else None
    stats['monitor_encoding'] = 'one-mark-ports' if port_plans is not None else 'rotation'
    stats['sparse_initialization'] = sparse_init
    stats['elide_initial_hb'] = elide_init_hb
    stats['dense_co_generators'] = prepared.options['dense_co_generators']
    stats['early_degrees'] = early_degrees
    stats['co_mode'] = co_mode
    stats['summary_mode'] = summary_mode
    stats['rf_mode'] = rf_mode
    stats['source_covers'] = source_covers
    stats['source_cover_edges'] = len(cert.get('source_cover_edges', ()))
    stats['monitor_updates'] = monitor_updates
    stats['monitor_cache_hits'] = monitor_cache_hits
    if co_mode == 'direct':
        stats['algorithm'] = 'frontier-direct-co'
    if port_plans is not None:
        stats['algorithm'] = 'frontier-ports'
        stats['native_port_steps'] = sum(p.native_plan is not None for plans in port_plans for p in plans)
        stats['total_port_steps'] = sum(map(len,port_plans))
        stats['max_port_coordinates'] = max((sum(
            (1 if plans[step].acyclic else 2) * len(plans[step].after_inputs) * len(plans[step].after_outputs)
            for plans in port_plans) for step in range(len(groups))), default=0)
        stats['max_product_vertices'] = [max((p.width for p in plans), default=0) for plans in port_plans]
    return Compiled(registry, layers, edges, clauses, nvars, stats)
