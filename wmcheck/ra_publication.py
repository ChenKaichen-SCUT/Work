"""Finite successful traces of a repeated-publication state exchange.

Two workers update shared atomic payloads in opposite orders and publish an
alternating epoch bit twice: before and after the second payload update. An
acquire of the peer's previous bit may synchronize with either publication.
The bounded trace fixes read values, not source identities or write order.
"""
from .model import Event
from .ra import RAInstance


def publication_exchange(rounds, copies=2, payload='constant'):
    if rounds < 1 or copies < 2:
        raise ValueError('Expected positive rounds and at least two publications')
    if payload not in ('constant','epoch'):
        raise ValueError('Expected constant or epoch-tagged payloads')
    initial = tuple('i' + loc for loc in ('x', 'y', 'fa', 'fb'))
    events = [Event(v, 'W', v[1:], -1, 0) for v in initial]
    threads = []
    for t in range(2):
        seq = []
        first, second = ('x', 'y') if t == 0 else ('y', 'x')
        own, peer = ('fa', 'fb') if t == 0 else ('fb', 'fa')
        for i in range(1, rounds + 1):
            value=1 if payload=='constant' else i
            ops = [('W', first, value, first), ('W', own, i % 2, 'pub0'),
                   ('W', second, value, second)]
            ops += [('W', own, i % 2, f'pub{j}') for j in range(1, copies)]
            ops += [('R', peer, (i-1) % 2, 'wait'), ('R', first, value, 'read')]
            for kind, loc, value, suffix in ops:
                eid = f't{t}_{i}_{suffix}'
                seq.append(eid)
                events.append(Event(eid, kind, loc, t, value))
        threads.append(tuple(seq))
    return RAInstance(tuple(events), tuple(threads), initial)


def publication_layout(inst, rounds):
    return inst.initial + tuple(v for i in range(1, rounds+1)
                                for thread in inst.threads for v in thread
                                if int(v.split('_')[1]) == i)


def staged_witness(inst, rounds, copies=2, last_publication=False):
    """RA-valid, non-SC complete RF/CO witness for every positive round count."""
    rf = {}
    for t in range(2):
        own_data = 'x' if t == 0 else 'y'
        peer_flag = 'fb' if t == 0 else 'fa'
        for i in range(1, rounds+1):
            rf[f't{t}_{i}_read'] = f't{t}_{i}_{own_data}'
            rf[f't{t}_{i}_wait'] = ('i'+peer_flag if i == 1 else
                f't{1-t}_{i-1}_pub{copies-1 if last_publication else 0}')
    orders = {
        'x': ('ix',) + tuple(f't{t}_{i}_x' for i in range(1, rounds+1) for t in (1, 0)),
        'y': ('iy',) + tuple(f't{t}_{i}_y' for i in range(1, rounds+1) for t in (0, 1)),
        'fa': ('ifa',) + tuple(f't0_{i}_pub{j}' for i in range(1, rounds+1) for j in range(copies)),
        'fb': ('ifb',) + tuple(f't1_{i}_pub{j}' for i in range(1, rounds+1) for j in range(copies)),
    }
    return rf, orders
