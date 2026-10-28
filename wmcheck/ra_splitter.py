"""Fixed traces of the Moir--Anderson one-time splitter grid (Figure 2/4).

Source: Moir and Anderson, SCP 25(1), 1995, DOI 10.1016/0167-6423(95)00009-H.
This module models OUR all-release/acquire port, not the paper's atomic/SC
correctness claim. It adds no shared-memory operations to the protocol.
See docs/SPLITTER_PROVENANCE.zh.txt for extraction and mutation details.
"""
from dataclasses import dataclass
from .model import Event
from .ra import RAInstance
from .ra_object_layout import object_layout


@dataclass(frozen=True)
class Visit:
    batch: int
    row: int
    col: int
    outcome: str  # right, down, stop, or probe (last read result unlogged)
    observed_x: int | None = None

    @property
    def obj(self):
        return f'b{self.batch:04d}_r{self.row:04d}_c{self.col:04d}'


def extract_grid(paths):
    """Retain every shared access on each supplied branch, including prefixes.

    The raw X value on a down branch is required; probe is permitted only at
    the very end of a thread trace. Different batches use fresh addresses.
    No unobserved RF identity or CO direction is fixed by extraction.
    """
    paths = tuple(tuple(path) for path in paths)
    owners = {}
    for t, path in enumerate(paths):
        for j, visit in enumerate(path):
            if min(visit.batch, visit.row, visit.col) < 0:
                raise ValueError('Negative grid coordinate')
            if visit.row + visit.col >= len(paths)-1:
                raise ValueError('The original grid returns a name at this boundary, without another access')
            if visit.outcome not in ('right', 'down', 'stop', 'probe'):
                raise ValueError('Unknown outcome')
            if visit.outcome == 'down' and (visit.observed_x is None or visit.observed_x == t+1):
                raise ValueError('A down branch needs a logged other-process X value')
            if visit.outcome in ('right', 'probe') and visit.observed_x is not None:
                raise ValueError('No X result is retained for right/probe')
            if visit.outcome == 'stop' and visit.observed_x not in (None, t+1):
                raise ValueError('A stop branch must observe its own process identifier')
            if visit.outcome == 'probe' and j != len(path)-1:
                raise ValueError('An unlogged branch cannot determine subsequent events')
            if j == 0:
                if (visit.batch, visit.row, visit.col) != (0, 0, 0):
                    raise ValueError('Every thread enters the first grid at its root')
            else:
                prev = path[j-1]
                if visit.batch == prev.batch:
                    expected = ((prev.row, prev.col+1) if prev.outcome == 'right' else
                                (prev.row+1, prev.col) if prev.outcome == 'down' else None)
                    if expected != (visit.row, visit.col):
                        raise ValueError('Route does not follow the retained branch')
                elif not (visit.batch == prev.batch+1 and prev.outcome == 'stop'
                          and (visit.row, visit.col) == (0, 0)):
                    raise ValueError('Fresh batches require a completed previous call')
            for register in ('x', 'y'):
                owners[visit.obj+'_'+register] = visit.obj
    initial = tuple('i_'+loc for loc in sorted(owners))
    events = [Event('i_'+loc, 'W', loc, -1, 0) for loc in sorted(owners)]
    threads = []
    metadata = []
    for t, path in enumerate(paths):
        seq = []
        for visit in path:
            base = f't{t}_{visit.obj}'
            ops = [('wx', 'W', 'x', t+1),
                   ('ry', 'R', 'y', int(visit.outcome == 'right'))]
            if visit.outcome != 'right':
                value = None if visit.outcome == 'probe' else (t+1 if visit.outcome == 'stop' else visit.observed_x)
                ops += [('wy', 'W', 'y', 1), ('rx', 'R', 'x', value)]
            for suffix, kind, register, value in ops:
                eid = base+'_'+suffix
                events.append(Event(eid, kind, visit.obj+'_'+register, t, value))
                seq.append(eid)
                metadata.append(dict(event=eid, batch=visit.batch, row=visit.row, col=visit.col,
                                     source_operation=suffix, outcome=visit.outcome))
        threads.append(tuple(seq))
    inst = RAInstance(tuple(events), tuple(threads), initial)
    layout = object_layout(inst, owners)
    return inst, layout, metadata


def grid_family(workers=3, batches=1, *, duplicate_stop=False, open_terminal=False):
    """A routed grid trace; each level peels one stop and one right process.

    The right-going process reads a genuinely contested door, then stops at
    its next grid node. Others go down. The special three-process trace has
    two root stops: a fault of the release/acquire port, not of the SC source.
    Repeated batches are an explicitly separate fresh-object workload.
    """
    if workers < 3 or batches < 1 or (duplicate_stop and workers != 3):
        raise ValueError('Need workers>=3, batches>=1; duplicate-stop uses 3 workers')
    paths = [[] for _ in range(workers)]
    for batch in range(batches):
        active = list(range(workers))
        row = 0
        while active:
            if len(active) == 1:
                t = active[0]
                paths[t].append(Visit(batch, row, 0, 'stop'))
                break
            if duplicate_stop:
                for t in (0, 1):
                    paths[t].append(Visit(batch, 0, 0, 'stop'))
                paths[2] += [Visit(batch, 0, 0, 'right'), Visit(batch, 0, 1, 'stop')]
                break
            stopper = active[-2] if len(active) >= 3 else active[-1]
            right = active[-1] if len(active) >= 3 else None
            for t in active:
                if t == right:
                    paths[t] += [Visit(batch, row, 0, 'right'), Visit(batch, row, 1, 'stop')]
                elif t == stopper:
                    paths[t].append(Visit(batch, row, 0, 'stop'))
                else:
                    paths[t].append(Visit(batch, row, 0, 'down', stopper+1))
            active = [t for t in active if t not in (stopper, right)]
            row += 1
    if open_terminal:
        for t in range(workers):
            last = paths[t][-1]
            paths[t][-1] = Visit(last.batch, last.row, last.col, 'probe')
    return extract_grid(paths)


def root_probe():
    """A/B end after unlogged X checks; C sees a closed door and ends there."""
    return extract_grid(((Visit(0, 0, 0, 'probe'),),
                         (Visit(0, 0, 0, 'probe'),),
                         (Visit(0, 0, 0, 'right'),)))
