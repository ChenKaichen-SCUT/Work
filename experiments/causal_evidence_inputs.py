"""Finite, irredundant original assumptions and protocol-derived diagnostic logs."""
import itertools,math,random,time
from experiments.causal_evidence_common import OUT,label,instance,save,digest
from wmcheck.ra import RARegistry
from wmcheck.ra_protocols import build_protocol
from wmcheck.ra_support_sat import SupportSAT
from wmcheck.ra_task_diagnosis import field


def generate(case,seed=0):
    inp=instance(case);pre=build_protocol(inp);reg=RARegistry(inp.inst)
    assert pre['status']=='CERTIFIED'
    rng=random.Random(732041+seed*100003+case['rounds']*37+case.get('capacity',0))
    with SupportSAT(inp,pre['certificate']) as oracle:
        ok,support=oracle.all_support();assert ok
        free={v for v in reg.by_id if v in support and -v in support};representatives=set()
        for r,ws in pre['certificate']['domains'].items():
            ws=sorted(ws)
            if len(ws)>1:representatives.update(reg.literal(('rf',w,r)) for w in (ws[:1] if len(ws)==2 else ws))
        representatives|={v for v,(kind,a,b) in reg.by_id.items() if kind=='co' and v in free}
        representatives &= free
        signs=sorted(l for v in representatives for l in (v,-v))
        pairs=[p for p in itertools.combinations(signs,2) if abs(p[0])!=abs(p[1]) and field(reg,p[0])!=field(reg,p[1])]
        rng.shuffle(pairs);unsat=[]
        for pair in pairs[:10000]:
            if not oracle.solve(pair):
                unsat.append(pair)
                if len(unsat)==10:break
        yes=[];seen=set();attempts=0;exhausted=False;length=min(4,len(representatives))
        while length>0 and not yes:
            combinations=math.comb(len(signs),length)
            exhaustive=combinations<=25000
            if exhaustive:
                candidates=list(itertools.combinations(signs,length));rng.shuffle(candidates)
            else:candidates=(tuple(sorted(rng.sample(signs,length))) for _ in range(20000))
            for alpha in candidates:
                attempts+=1
                if len(set(map(abs,alpha)))!=length or alpha in seen:continue
                seen.add(alpha)
                if not oracle.solve(alpha):continue
                if not all(oracle.solve(tuple(x for x in alpha if x!=lit)+(-lit,)) for lit in alpha):continue
                yes.append(alpha)
                if len(yes)==990:break
            exhausted=exhaustive and len(yes)<990
            if not yes:length-=1;seen.clear()
        assert yes
        queries=[]
        for j in range(1000):
            bad=bool(unsat) and j%100==99
            alpha=unsat[(j//100)%len(unsat)] if bad else yes[(j-j//100)%len(yes)]
            queries.append(dict(assumptions=alpha,expected_sat=not bad))
        active={v for v,(kind,a,b) in reg.by_id.items() if kind=='rf' and v in support}
        structure=dict(events=len(inp.inst.events),original_variables=reg.nvars,
            raw_RF_candidates=sum(map(len,inp.inst.candidates.values())),remaining_RF_candidates=sum(map(len,pre['certificate']['domains'].values())),
            max_RF_domain=max(map(len,pre['certificate']['domains'].values()),default=0),supported_RF=len(active),
            ambiguous_reads=sum(sum(reg.literal(('rf',w,r)) in support for w in inp.inst.candidates[r])>1 for r in inp.inst.reads),
            undecided_CO=sum(kind=='co' and v in free for v,(kind,a,b) in reg.by_id.items()),
            permanent_H=len(pre['certificate']['H']),permanent_L=len(pre['certificate']['L']),protocol_metrics=pre['metrics'])
    result=dict(case=case,seed=seed,input_sha256=digest(inp),queries=queries,workload_sha256=digest(queries),
        Q=len(queries),U=len({tuple(q['assumptions']) for q in queries}),SAT_requests=sum(q['expected_sat'] for q in queries),
        sat_pool=yes,unsat_pool=unsat,assumption_length=length,generation_attempts=attempts,
        small_domain_exhausted=exhausted,all_sat_assumptions_irredundant=True,
        all_literals_have_both_root_supports=True,root_supported=sorted(support),structure=structure)
    save(OUT/'workloads'/f'{label(case)}_s{seed}.json',result)
    return result


def diagnostic_logs(case):
    inp=instance(case);pre=build_protocol(inp);reg=RARegistry(inp.inst);logs=[]
    with SupportSAT(inp,pre['certificate']) as oracle:
        ok,support=oracle.all_support();assert ok
        if case['family']=='barrier':
            for i in range(1,case['rounds']+1):
                for source,read,before,after in [(f'w2_{i}_bx',f'w1_{i}_ar',f'w1_{i}_ax',f'w2_{i}_bx'),
                    (f'w1_{i}_ay',f'w2_{i}_br',f'w2_{i}_by',f'w1_{i}_ay')]:
                    a=reg.literal(('rf',source,read));c=reg.literal(('co',before,after))
                    assert oracle.solve([a]) and oracle.solve([-c]) and not oracle.solve([a,-c])
                    logs.extend([dict(name=f'{read}_conflict',observations=[a,-c]),dict(name=f'{read}_consistent',observations=[a,c])])
        else:
            literals=[v for v,(kind,w,r) in reg.by_id.items() if kind=='rf' and v in support and -v in support]
            pairs=[(a,b) for a,b in itertools.combinations(literals,2) if field(reg,a)!=field(reg,b)
                and inp.inst.event[reg.by_id[a][2]].thread!=inp.inst.event[reg.by_id[b][2]].thread
                and pre['stages'][reg.by_id[a][2]]!=pre['stages'][reg.by_id[b][2]]]
            pairs.sort(key=lambda p:(min(pre['stages'][reg.by_id[v][2]] for v in p),p))
            for a,b in pairs:
                if oracle.solve([a,b]):continue
                read=reg.by_id[b][2];variables=[reg.literal(('rf',w,read)) for w in inp.inst.candidates[read]]
                ok,values=oracle.target_support(variables,[a]);assert ok
                replacement=min(v for v in variables if v in values)
                logs.extend([dict(name=f'pair{len(logs)//2}_conflict',observations=[a,b]),
                             dict(name=f'pair{len(logs)//2}_consistent',observations=[a,replacement])])
                if len(logs)>=32:break
            assert logs
    result=dict(case=case,input_sha256=digest(inp),episodes=logs,episodes_sha256=digest(logs),
        provenance='Executable protocol-derived provenance records, not industrial telemetry; SAT used only to construct the workload.')
    save(OUT/'diagnostic_inputs'/f'{label(case)}.json',result)
    return result
