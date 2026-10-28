"""An on-demand provenance client: consistency, field repair, requested snapshots."""
from time import perf_counter


class QueryService:
    def __init__(self, method, engine, registry):
        self.method,self.engine,self.registry=method,engine,registry
        self.sat_cache={};self.full_cache={};self.target_cache={};self.calls=[]

    def _key(self, assumptions):return tuple(sorted(set(assumptions)))

    def consistent(self, assumptions=()):
        tick=perf_counter();key=self._key(assumptions);hit=key in self.sat_cache;stats={}
        if not hit:
            if self.method=='B2':value=self.engine._paths(key) is not None
            else:
                value=self.engine.solve(key);stats=dict(self.engine.last_query_stats)
            self.sat_cache[key]=value
        answer=self.sat_cache[key]
        self.calls.append(dict(task='sat',alpha=key,cache_hit=hit,sat=answer,
            seconds=perf_counter()-tick,output_literals=0,solver=stats))
        return answer

    def support(self, assumptions=(), variables=None):
        tick=perf_counter();key=self._key(assumptions)
        full=variables is None
        variables=tuple(sorted(self.registry.by_id if full else set(variables)))
        target_key=key,variables;stats={}
        hit=(key in self.full_cache or (not full and target_key in self.target_cache)
             or (key in self.sat_cache and not self.sat_cache[key]))
        if key in self.full_cache:
            ok,values=self.full_cache[key]
            supported=values if full else frozenset(l for l in values if abs(l) in variables)
        elif not full and target_key in self.target_cache:ok,supported=self.target_cache[target_key]
        elif key in self.sat_cache and not self.sat_cache[key]:ok,supported=False,frozenset()
        else:
            if self.method=='B2':
                ok,forced=self.engine.propagate(key)
                values=frozenset(l for v in self.registry.by_id for l in (v,-v) if -l not in forced) if ok else frozenset()
                self.full_cache[key]=ok,values
                supported=values if full else frozenset(l for l in values if abs(l) in variables)
            else:
                ok,values=(self.engine.all_support(key) if full else self.engine.target_support(variables,key))
                supported=frozenset(values);stats=dict(self.engine.last_query_stats)
            self.sat_cache[key]=ok
            if full:self.full_cache[key]=ok,supported
            else:self.target_cache[target_key]=ok,supported
        self.calls.append(dict(task='all' if full else 'field',alpha=key,cache_hit=hit,sat=ok,
            target_variables=len(variables),seconds=perf_counter()-tick,output_literals=len(supported),solver=stats))
        return ok,supported


def field(registry, literal):
    kind,a,b=registry.by_id[abs(literal)]
    return ('rf',b) if kind=='rf' else ('co',a,b)


def validate_log(registry, observations):
    fields=[]
    for lit in observations:
        if type(lit) is not int or abs(lit) not in registry.by_id:raise ValueError('Original literals only')
        if lit<0 and registry.by_id[-lit][0]=='rf':raise ValueError('RF fields record positive source identities')
        fields.append(field(registry,lit))
    if len(set(fields))!=len(fields):raise ValueError('At most one observation per RF/CO field')


def diagnose(service, observations):
    """Deletion-minimal conflict and all one-field replacements, with targeted calls."""
    reg=service.registry;obs=tuple(observations);validate_log(reg,obs)
    if service.consistent(obs):return dict(consistent=True,conflict=[],repairs=[])
    core=list(obs)
    for lit in obs:
        candidate=tuple(x for x in core if x!=lit)
        if not service.consistent(candidate):core.remove(lit)
    repairs=[]
    for lit in obs:
        remaining=tuple(x for x in obs if x!=lit);kind,a,b=reg.by_id[abs(lit)]
        variables=[reg.literal(('rf',w,b)) for w in reg.inst.candidates[b]] if kind=='rf' else [abs(lit)]
        ok,supported=service.support(remaining,variables)
        if not ok:continue
        replacements=([v for v in variables if v!=lit and v in supported] if kind=='rf'
                      else ([-lit] if -lit in supported else []))
        repairs.append(dict(remove=lit,replacements=sorted(replacements)))
    return dict(consistent=False,conflict=core,repairs=repairs)


def session(service, episodes, profile='sparse'):
    """Apply actual additions, repair, withdrawal, and restoration in a fixed order."""
    if profile not in ('sparse','dense'):raise ValueError(profile)
    results=[]
    for episode in episodes:
        obs=list(episode['observations']);validate_log(service.registry,obs);snapshots=[];edits=[]
        def snapshot(label,alpha):
            ok,supports=service.support(alpha)
            snapshots.append(dict(label=label,alpha=list(alpha),sat=ok,supports=sorted(supports)))
        current=[]
        for lit in obs:
            current.append(lit);ok=service.consistent(current)
            edits.append(dict(action='add',literal=lit,consistent=ok))
            if profile=='dense' and ok:snapshot('add',current)
        diagnosis=diagnose(service,current)
        if not diagnosis['consistent']:
            choices=[(r['remove'],v) for r in diagnosis['repairs'] for v in r['replacements']]
            if choices:
                removed,replacement=min(choices)
                current=[replacement if x==removed else x for x in current]
                edits.append(dict(action='replace',remove=removed,replacement=replacement))
            else:
                # General fallback: withdraw the reported conflict one field at a time.
                for lit in diagnosis['conflict']:
                    current.remove(lit);edits.append(dict(action='withdraw_conflict',literal=lit))
                    if service.consistent(current):break
            assert service.consistent(current)
            if profile=='dense':snapshot('repair',current)
        if current:
            removed=current.pop(0);assert service.consistent(current)
            edits.append(dict(action='withdraw',literal=removed))
            if profile=='dense':snapshot('withdraw',current)
            current.insert(0,removed);assert service.consistent(current)
            edits.append(dict(action='restore',literal=removed))
        snapshot('final',current)
        results.append(dict(name=episode['name'],input=obs,diagnosis=diagnosis,edits=edits,snapshots=snapshots))
    return results
