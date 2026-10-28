"""Isolated structural mechanism checks; this script never compiles state DAGs.

The applicability sample is generated template prefixes plus explicit negative
contracts. It is not an industrial-program applicability survey.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,digest


def configurations(quick=False):
    rounds=(1,2,4) if quick else (1,2,4,8,16,32)
    fail=(0,4) if quick else (0,1,4,16)
    cases=[dict(family='barrier',rounds=n,failures=f,long_gap=gap)
           for n in rounds for gap in (False,True) for f in fail]
    cases += [dict(family='buffer',rounds=3,capacity=3,mode=mode,failures=f,tail_failures=f)
              for mode in ('value','branch') for f in fail]
    cases += [dict(family='no_feedback',n=n) for n in ((2,4) if quick else (2,4,8,16))]
    cases += [dict(family='applicability',case=name) for name in (
        'barrier_partial_reset','barrier_only_failures','barrier_missing_wake',
        'buffer_half_operation','buffer_failed_tail','buffer_false_full',
        'unknown_family','joint_guard','wrong_work_bound','protocol_address_in_work')]
    return cases


def _make(config):
    from dataclasses import replace
    from wmcheck.ra import RAInstance,producers
    from wmcheck.ra_protocols import barrier_instance,buffer_instance,prefix_input
    family=config['family']
    if family=='barrier':
        return barrier_instance(config['rounds'],failures=config['failures'],long_gap=config['long_gap'])
    if family=='buffer':
        return buffer_instance(config['rounds'],capacity=config['capacity'],mode=config['mode'],
                               failures=config['failures'],tail_failures=config['tail_failures'])
    if family=='no_feedback':
        n=config['n'];return producers(lengths=(n,),reader_values=((1,)*n,))
    name=config['case']
    if name=='barrier_partial_reset':return prefix_input(barrier_instance(1,failures=1),{0:5,1:5,2:5})
    if name=='barrier_only_failures':return prefix_input(barrier_instance(1,workers=1,failures=3,data=False),{0:3,1:0})
    if name=='barrier_missing_wake':return prefix_input(barrier_instance(1),{0:0})
    if name=='buffer_half_operation':return prefix_input(buffer_instance(1,mode='branch'),{0:2,1:1})
    if name=='buffer_failed_tail':return buffer_instance(0,mode='branch',tail_failures=4)
    if name=='buffer_false_full':return buffer_instance(0,mode='branch',producer_tail_failures=1)
    if name=='joint_guard':
        inp=buffer_instance(1,mode='branch');inp.guards+=({'op':'unsupported_joint_guard'},);return inp
    inp=barrier_instance(1)
    if name=='unknown_family':inp.contract['family']='unproved-template'
    elif name=='wrong_work_bound':inp.contract['B']=0
    elif name=='protocol_address_in_work':
        events=tuple(replace(e,loc='a1') if e.id=='w1_1_ax' else e for e in inp.inst.events)
        inp.inst=RAInstance(events,inp.inst.threads,inp.inst.initial)
    else:raise ValueError(name)
    return inp


def _compact_plan(plan):
    groups=plan.groups;rank=plan.rank
    spans=[abs(rank[a]-rank[b]) for vertices,_ in groups for a in vertices for b in vertices]
    kinds={}
    for _,alternatives in groups:
        for _,edges,_ in alternatives:
            for kind,_,_ in edges:kinds[kind]=kinds.get(kind,0)+1
    return dict(actual_K=plan.stats['actual_K'],declared_K=plan.stats['declared_K'],
        candidate_pairs=plan.stats['candidate_pairs'],groups=plan.stats['groups'],
        candidate_span=max(spans,default=0),prepare_seconds=plan.stats['prepare_seconds'],
        semantic_candidate_edge_occurrences=kinds,schedule_kind=plan.stats['schedule_kind'])


def measure(config):
    from wmcheck.ra import RARegistry,recognize
    from wmcheck.ra_protocols import build_protocol,buffer_chain_bags,replay_certificate
    from wmcheck.ra_frontier import prepare_frontier
    tick=time.perf_counter();inp=_make(config);protocol=hasattr(inp,'inst');inst=inp.inst if protocol else inp
    row=dict(config=config,input_sha256=digest(inp),events=len(inst.events),
             original_variables=RARegistry(inst).nvars,does_compile=False)
    ordinary=inst.initial+tuple(e for t in inst.threads for e in t)
    if protocol:
        pre=build_protocol(inp);row.update(status=pre['status'],pre_seconds=pre['pre_seconds'],
            source=inp.contract.get('source'),observation=config.get('mode','fixed-values'),
            contract_fields_generated=list(sorted(inp.contract)),manual_annotation='template selected; all fields generated')
        if pre['status']=='OUTSIDE':row['reason']=pre['reason'];return row
        cert=pre['certificate'];row['metrics']=pre['metrics']
        row['failed_event_ids']=sorted(pre['failed_reads'])
        row['all_failed_events_in_original_input']=pre['failed_reads']<=set(inst.event)
        # Replay on small applicability fixtures. The larger scan pays construction
        # once and independently validates its plan, rather than timing duplicate Build.
        if config['family']=='applicability':row['certificate_replay']=replay_certificate(inp,pre)
        if pre['status']=='PROVED_UNSAT':return row
        special=dict(order=pre['order'])
        if inp.contract['family']=='gps_buffer':
            bags=buffer_chain_bags(inp,pre);special['bags']=bags
            row['bag_bound_kind']='failure-chain bag expansion; not causal-frontier bound'
            row['all_failed_events_in_bags']=pre['failed_reads']<=set().union(*map(set,bags))
        else:row['bag_bound_kind']='causal-frontier layout'
        row['old_write_gap_G_lower_bound']=max(0,config.get('rounds',1)-1) if config.get('long_gap') else None
    else:
        cert=recognize(inst,source_covers=True);special=dict(order=ordinary)
        row.update(status='CERTIFIED',protocol_status='NOT_A_PROTOCOL_CERTIFICATE',
                   source='two-thread one-address no-feedback quantifier separation',
                   semantic_scope='structural negative control; no solver hardness claim')
    for name,options in [('special',special),('ordinary',dict(order=ordinary))]:
        plan=prepare_frontier(inst,certificate=cert,co_mode='direct',summary_mode='full',**options)
        row[name]=_compact_plan(plan)
        if protocol:
            row[name]['all_failed_events_scheduled']=pre['failed_reads']<=set(plan.stats['event_first'])
            row[name]['sb_inversions']=sum(plan.stats['event_first'][b]<plan.stats['event_first'][a]
                                             for a,b in inst.sb)
    row.update(total_seconds=time.perf_counter()-tick)
    return row


def isolated(config,out,seconds,memory_mib):
    import psutil
    path=out.with_suffix('.config.json');save(path,config)
    command=[sys.executable,str(Path(__file__).resolve()),'--worker','--config',str(path),'--out',str(out)]
    start=time.perf_counter();peak=0;status=None
    with out.with_suffix('.log').open('w',encoding='utf8') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        process=psutil.Process(child.pid)
        while child.poll() is None:
            try:peak=max(peak,process.memory_info().rss)
            except psutil.Error:pass
            if peak>memory_mib*1024**2:status='MEMORY_LIMIT'
            elif time.perf_counter()-start>seconds:status='TIME_LIMIT'
            if status:
                child.kill();child.wait();break
            time.sleep(.025)
    if status:
        result=dict(status=status,config=config,does_compile=False)
    elif out.exists():result=json.loads(out.read_text(encoding='utf8'))
    else:result=dict(status='ERROR',config=config,returncode=child.returncode)
    result.update(wall_seconds=time.perf_counter()-start,peak_process_rss_bytes=peak,
                  time_limit_seconds=seconds,memory_limit_mib=memory_mib)
    save(out,result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--config')
    parser.add_argument('--quick',action='store_true');parser.add_argument('--seconds',type=float,default=40)
    parser.add_argument('--memory-mib',type=int,default=1024)
    args=parser.parse_args();out=Path(args.out)
    if args.worker:
        config=json.loads(Path(args.config).read_text(encoding='utf8'))
        try:row=measure(config)
        except Exception:row=dict(status='ERROR',config=config,traceback=traceback.format_exc(),does_compile=False)
        save(out,row);return
    out.mkdir(parents=True,exist_ok=True);rows=[]
    for index,config in enumerate(configurations(args.quick)):
        row=isolated(config,out/f'{index:03d}.json',args.seconds,args.memory_mib);rows.append(row)
        save(out/'summary.json',dict(rows=rows,sample_scope='generated protocol prefixes, explicit malformed contracts, no-feedback control; not industrial applicability',
             stages='structure and plan only; no state compilation or query timing'))
        print(index,config,row['status'],row.get('special',{}).get('actual_K'),flush=True)


if __name__=='__main__':main()
