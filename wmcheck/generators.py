"""Finite-valued protocol traces; semantic certification lives in recognize.py."""
from .model import Event


def make_trace(rounds=2,threads=4,addresses=2,readers=2,first_read_value=0,writes_per_thread=1):
    if rounds<1 or threads<2 or not 1<=addresses<=threads or not 0<=readers<=threads or writes_per_thread<1:
        raise ValueError('Invalid finite protocol parameters')
    events=[];sequences={t:[] for t in range(threads)};blocks=[]
    locations=[f'x{x}' for x in range(addresses)];flags=[f'flag{t}' for t in range(threads)]
    initial=[]
    for loc in locations+flags:
        e=Event(f'init:{loc}','W',loc,-1,0);events.append(e);initial.append(e.id)
    blocks.append(initial)
    def add(e,block): events.append(e);sequences[e.thread].append(e.id);block.append(e.id)
    for i in range(1,rounds+1):
        block=[]
        for t in range(threads):
            for j in range(writes_per_thread):
                add(Event(f'w:{i}:{t}:{j}','W',locations[t%addresses],t,1),block)
            if t<readers:
                add(Event(f'r:{i}:{t}','R',locations[(t+1)%addresses],t,first_read_value if i==1 else 1),block)
            add(Event(f'fw:{i}:{t}','W',flags[t],t,i%2),block)
            for u in range(threads):
                if u!=t: add(Event(f'fr:{i}:{t}:{u}','R',flags[u],t,i%2),block)
            add(Event(f'f:{i}:{t}','F',None,t),block)
        blocks.append(block)
    return {'events':events,'sequences':sequences,'blocks':blocks,'flags':{t:flags[t] for t in range(threads)},
            'data_locations':locations,'rounds':rounds,'parameters':{'rounds':rounds,'threads':threads,
            'addresses':addresses,'readers':readers,'first_read_value':first_read_value,
            'writes_per_thread':writes_per_thread}}


def make_instance(**kwargs):
    from .recognize import recognize
    return recognize(make_trace(**kwargs))
