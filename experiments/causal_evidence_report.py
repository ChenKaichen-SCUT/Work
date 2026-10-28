"""Derived evidence tables/figures; resource failures are retained, never imputed."""
import json,statistics,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_evidence_common import OUT,CASES,label,save,instance
from experiments.causal_evidence_suite import summarize


def table(headers,rows):
    return '\n'.join([' | '.join(headers),' | '.join('---' for _ in headers)]+[' | '.join(map(str,row)) for row in rows])


def main():
    rows=summarize();groups=defaultdict(list)
    for r in rows:
        j=r['job']
        groups[j['mode'],label(j['case']),j.get('seed',0),j.get('order',0),j.get('profile',''),j.get('method','B0')].append(r)
    tables=[]
    for key,rs in sorted(groups.items()):
        mode,case,seed,order,profile,method=key;ok=[r for r in rs if r['status']=='OK']
        row=dict(mode=mode,case=case,seed=seed,order=order,profile=profile,method=method,
            statuses=dict(Counter(r['status'] for r in rs)),successful_repeats=len(ok),case_parameters=rs[0]['job']['case'])
        if ok:
            for name in ('total_seconds','cold_seconds','query_seconds','task_seconds','certificate_seconds','certificate_check_seconds',
                'encoding_seconds','plan_seconds','compile_seconds','index_seconds','output_seconds','miss_compute_seconds'):
                if name in ok[0]:row[name]=statistics.median(r[name] for r in ok)
            row.update(total_min=min(r.get('total_seconds',0) for r in ok),total_max=max(r.get('total_seconds',0) for r in ok),
                peak_mib=statistics.median(r['peak_wset_bytes']/1024**2 for r in ok))
            representative=sorted(ok,key=lambda r:r.get('total_seconds',0))[len(ok)//2]
            row.update(chart_cold_seconds=representative.get('cold_seconds',0),chart_task_seconds=representative.get('task_seconds',0))
            for name in ('U','Q','distinct_answers','cache_hits','cache_misses','global_cache_hits','global_cache_misses',
                'local_hits','local_misses','component_sat_calls','output_bytes','query_types','assumption_lengths'):
                if name in ok[0]:row[name]=ok[0][name]
            if mode=='task':
                raw=json.loads((OUT/ok[0]['file']).read_text(encoding='utf8'))
                row.update(unique_alpha=len({tuple(q['alpha']) for q in raw['queries']}),
                    output_snapshots=sum(r['snapshots'] for r in raw['reports']),
                    repair_alternatives=sum(r['repairs'] for r in raw['reports']),episodes=len(raw['reports']),
                    actual_sat_calls=sum(q.get('solver',{}).get('calls',q.get('solver',{}).get('sat_calls',0)) for q in raw['queries']),
                    natural_sat_calls=raw['natural_sat_calls'],natural_unsat_calls=raw['natural_unsat_calls'],
                    actual_uncached_query_types={k:sum(q['task']==k and not q['cache_hit'] for q in raw['queries']) for k in ('sat','field','all')})
        else:row.update(phases=sorted({r['phase'] for r in rs}),completed_queries=max(r['completed_queries'] for r in rs))
        tables.append(row)
    def get(mode,case,method,profile='',seed=0,order=0):
        return next((r for r in tables if (r['mode'],r['case'],r['method'],r['profile'],r['seed'],r['order'])==(mode,case,method,profile,seed,order)),None)
    structures=[]
    for case in CASES:
        w=json.loads((OUT/'workloads'/f'{label(case)}_s0.json').read_text(encoding='utf8'))
        struct=dict(case=label(case),parameters=case,U=w['U'],assumption_length=w['assumption_length'],**w['structure'])
        b2=next((r for r in rows if r['job']['mode']=='bench' and r['job']['case']==case and r['job']['method']=='B2' and r['file'].startswith('scan/')),None)
        bd=next((r for r in rows if r['job']['mode']=='bench' and r['job']['case']==case and r['job']['method']=='BD' and r['file'].startswith('scan/')),None)
        if b2:
            struct.update(compile_status=b2['status'],compile_phase=b2['phase'],plan=b2.get('plan_stats',{}),graph=b2.get('compile_stats',{}),partial_graph=b2.get('partial_stats',{}))
        if bd:struct['CNF']=bd.get('solver_stats',{})
        structures.append(struct)
    negative=[]
    from wmcheck.ra_protocols import build_protocol
    for r in rows:
        if r['job']['mode']!='negative':continue
        raw=json.loads((OUT/r['file']).read_text(encoding='utf8'));pre=build_protocol(instance(r['job']['case']));reg=__import__('wmcheck.ra',fromlist=['RARegistry']).RARegistry(instance(r['job']['case']).inst)
        counts=Counter(q['kind'] for q in raw['queries'] if q['raw_result']=='UNSAT');tags=Counter(t for q in raw['queries'] for t in q['tags'])
        crossing=[]
        for q in raw['queries']:
            if q['kind']!='conditional' or q['raw_result']!='UNSAT':continue
            literals=q['alpha']+[q['literal']];stages=[pre['stages'][reg.by_id[abs(l)][2]] for l in literals]
            if len(set(stages))>1:crossing.append(dict(alpha=q['alpha'],literal=q['literal'],stages=stages,decoded=q['decoded']))
        negative.append(dict(case=label(r['job']['case']),status=r['status'],counts=dict(counts),tags=dict(tags),
            raw_positive_controls=len(raw.get('positive_controls',[])),unique_dense_RA_witnesses=len(raw.get('witnesses',{})),
            cross_stage_conditionals=len(crossing),cross_stage_examples=crossing[:3],disagreements=raw.get('disagreements',[]),
            source='Unfiltered original RA SAT; positive witnesses also checked by dense HB/ECO'))
    amortization=[]
    for case in CASES:
        matched={m:[r for r in rows if r['job']['mode']=='bench' and r['job']['case']==case and r['job']['method']==m and r['status']=='OK' and r['file'].startswith('scan/')] for m in ('BD','B2')}
        if not all(matched.values()):continue
        curves={}
        for m,rs in matched.items():
            curves[m]=[]
            for r in rs:
                raw=json.loads((OUT/r['file']).read_text(encoding='utf8'));curve=[r['cold_seconds']]
                for q in raw['queries']:curve.append(curve[-1]+q['seconds'])
                curves[m].append(curve)
        med={m:[statistics.median(v) for v in zip(*cs)] for m,cs in curves.items()}
        bad=[i for i,(a,b) in enumerate(zip(med['B2'],med['BD'])) if a>b]
        threshold=max(bad)+1 if bad else 0
        amortization.append(dict(case=label(case),sustained_cheaper_after_requests=threshold if threshold<len(med['B2']) else None,
            scope='Median cumulative cost on the frozen seed-0 order, including cold construction; not a universal break-even bound'))
    resource=[]
    for p in sorted((OUT/'resource_audit').glob('*.json')):
        if p.name.endswith('.job.json'):continue
        r=json.loads(p.read_text(encoding='utf8'))
        resource.append(dict(file=p.relative_to(OUT).as_posix(),status=r['status'],case=label(r['job']['case']),method=r['job']['method'],
            peak_tree_mib=r['peak_tree_rss_sampled_bytes']/1024**2,controller_seconds=r['controller_seconds'],completed_queries=len(r.get('queries',[]))))
    data=dict(tables=tables,structures=structures,negative=negative,amortization=amortization,resource_audit=resource,statuses=dict(Counter(r['status'] for r in rows)),
        answer_discrepancies=json.loads((OUT/'summary.json').read_text(encoding='utf8'))['answer_discrepancies'])
    save(OUT/'tables.json',data)
    fmt=lambda value:'—' if value is None else f'{value:.4f}'
    cost=[]
    for case in CASES:
        items=[]
        for method in ('B0','B1','BD','B2'):
            r=get('bench',label(case),method);items.append(fmt(r.get('total_seconds')) if r and r['successful_repeats'] else '/'.join(r['statuses']) if r else '未运行')
        cost.append([label(case)]+items)
    details=[]
    for r in tables:
        if r['mode']!='bench' or not r['successful_repeats']:continue
        details.append([r['case'],r['seed'],r['order'],r['method'],r['U'],r['distinct_answers'],r['cache_hits'],r['cache_misses']]+[
            fmt(r.get(k)) for k in ('cold_seconds','query_seconds','output_seconds','total_seconds','peak_mib')])
    structure_rows=[];components=[]
    for r in structures:
        p,g,c=r.get('plan',{}),r.get('graph',{}),r.get('CNF',{})
        structure_rows.append([r['case'],r['events'],r['remaining_RF_candidates'],r['max_RF_domain'],r['ambiguous_reads'],r['undecided_CO'],p.get('actual_K','—'),p.get('groups','—'),g.get('max_layer_states','—'),g.get('states','—'),g.get('transitions','—'),r.get('compile_status','—')])
        components.append([r['case'],c.get('original_components','—'),c.get('original_component_sizes','—'),c.get('fixed_originals','—'),c.get('components','—')])
    phases=[]
    for r in tables:
        if r['mode']=='bench' and r['seed']==0 and r['order']==0 and r['successful_repeats']:
            phases.append([r['case'],r['method']]+[fmt(r.get(k)) for k in ('certificate_seconds','certificate_check_seconds','encoding_seconds','plan_seconds','compile_seconds','index_seconds','query_seconds','output_seconds','peak_mib')])
    taskrows=[]
    for r in tables:
        if r['mode']=='task' and r['successful_repeats']:
            taskrows.append([r['case'],r['profile'],r['method'],fmt(r.get('cold_seconds')),fmt(r.get('task_seconds')),fmt(r.get('output_seconds')),fmt(r.get('total_seconds')),
                r['query_types'],r['actual_uncached_query_types'],r['actual_sat_calls'],r['global_cache_hits'],r.get('local_hits','—'),r.get('local_misses','—'),r['output_snapshots'],r['output_bytes']])
    negrows=[[r['case'],r['status'],r['counts'].get('deleted_RF',0),r['counts'].get('fixed_CO_opposite',0),r['counts'].get('conditional',0),r['cross_stage_conditionals'],r['raw_positive_controls']] for r in negative]
    failures=[[r['file'],r['status'],r['phase'],r['completed_queries'],r.get('reason','')] for r in rows if r['status']!='OK']
    text='跨阶段范围与诊断：自动生成的完整结果表\n单位为秒；成功点中位数；超限不插补。各分项分别取中位数，其和未必等于总计中位数。\n峰值取完成worker自身OS peak working set；原控制器RSS仅测到Windows启动器，不用于内存结论。\n\n'
    text+='1. 主扫描冷启动+1000全支持请求\n'+table(['输入','B0','B1','BD','B2'],cost)
    text+='\n\n2. 候选与实际构造规模\n'+table(['输入','事件','RF候选','max域','歧义读','未决CO','K','组','Smax','总状态','转移','构造状态'],structure_rows)
    text+='\n\n3. 静态CNF组件\n'+table(['输入','含原始位组件','各组件原始自由位数','固定原始位','全部组件含纯辅助'],components)
    text+='\n\n4. 主扫描分项\n'+table(['输入','方法','证书','同核重放','SAT编码','计划','图构造','索引','查询','输出','峰值MiB'],phases)
    text+='\n\n5. 扫描及池/顺序稳健性完整成本\n'+table(['输入','seed','order','方法','U','不同答案','命中','缺失','冷','查询','输出','总计','峰值MiB'],details)
    text+='\n\n6. 按需诊断任务（输出成本已含在任务总计中；请求类型sat/field/all）\n'+table(['输入','模式','方法','冷','任务','输出','总计','请求类型','未缓存调用类型','实际SAT调用','全局命中','局部命中','局部缺失','快照数','输出字节'],taskrows)
    text+='\n\n7. 无证书原始语义负核查\n'+table(['输入','状态','删除RF','固定CO反向','条件无支持','跨阶段条件','原始SAT及dense正核查'],negrows)
    text+='\n\n8. 所有资源失败（请求数为最后保存前缀）\n'+table(['记录','状态','阶段','保存请求','原因'],failures)+'\n'
    text+='\n\n9. 固定序列的累计成本交点\n'+table(['输入','B2持续低于BD的起始请求数'],[[r['case'],r['sustained_cheaper_after_requests']] for r in amortization])
    text+='\n\n10. 进程树资源复核（单独重跑原超时点；原记录不覆盖）\n'+table(['输入','方法','状态','树峰值MiB','控制器秒','保存请求'],[[r['case'],r['method'],r['status'],fmt(r['peak_tree_mib']),fmt(r['controller_seconds']),r['completed_queries']] for r in resource])+'\n'
    (OUT/'tables.zh.txt').write_text(text,encoding='utf8')
    plots(data,get)
    print(json.dumps(dict(statuses=data['statuses'],negative_checks=sum(sum(r['counts'].values()) for r in negative),
        cross_stage_checks=sum(r['cross_stage_conditionals'] for r in negative),discrepancies=data['answer_discrepancies']),indent=2))


def plots(data,get):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150})
    colors={'B0':'#9a6223','B1':'#315ca8','BD':'#8b5194','B2':'#10816b'}
    names={'B0':'Raw SAT','B1':'Preprocessed SAT','BD':'Component SAT','B2':'Compiled'}
    folder=OUT/'figures';folder.mkdir(exist_ok=True)
    fig,axes=plt.subplots(2,2,figsize=(10,7))
    for col,(var,fixed) in enumerate((('rounds',dict(capacity=3)),('capacity',dict(rounds=8)))):
        cases=sorted((r for r in data['structures'] if all(r['parameters'][k]==v for k,v in fixed.items())),key=lambda r:r['parameters'][var])
        for m in colors:
            points=[(r['parameters'][var],get('bench',r['case'],m)) for r in cases]
            points=[(x,r) for x,r in points if r and 'total_seconds' in r]
            axes[0,col].plot([x for x,r in points],[r['total_seconds'] for x,r in points],'-o',color=colors[m],label=names[m])
            axes[0,col].fill_between([x for x,r in points],[r['total_min'] for x,r in points],[r['total_max'] for x,r in points],color=colors[m],alpha=.12)
        good=[r for r in cases if r.get('graph')]
        axes[1,col].plot([r['parameters'][var] for r in good],[r['graph']['max_layer_states'] for r in good],'-o',color='#10816b',label='Maximum layer states')
        axes[0,col].set(title='History scan, C=3' if col==0 else 'Capacity scan, n=8',ylabel='Cold + 1,000 full-support requests (s)',yscale='log')
        axes[1,col].set(xlabel='Rounds n' if col==0 else 'Capacity C',ylabel='Maximum reachable layer states',yscale='log')
        for ax in axes[:,col]:ax.grid(alpha=.2);ax.set_xticks([r['parameters'][var] for r in cases])
    axes[0,0].text(.98,.95,'n=16,32: SAT baselines did not finish',transform=axes[0,0].transAxes,ha='right',va='top',fontsize=8)
    axes[0,1].text(.98,.08,'C=6: compiled graph hit state limit',transform=axes[0,1].transAxes,ha='right',fontsize=8)
    axes[1,1].text(.98,.95,'C=6 partial: Smax >= 12,420',transform=axes[1,1].transAxes,ha='right',va='top',fontsize=8)
    axes[0,0].legend(fontsize=8);fig.text(.5,.01,'Shading: successful repeat range. Resource failures are reported separately, not assigned a time.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.035,1,1));fig.savefig(folder/'buffer_range.png');fig.savefig(folder/'buffer_range.pdf');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,case in zip(axes,('barrier_n8','buffer_n8_c3')):
        for i,m in enumerate(colors):
            for j,profile in enumerate(('sparse','dense')):
                r=get('task',case,m,profile)
                if not r or 'total_seconds' not in r:continue
                x=j+(i-1.5)*.18
                ax.bar(x,r['chart_cold_seconds'],width=.16,color=colors[m],alpha=.35,hatch='//')
                ax.bar(x,r['chart_task_seconds'],bottom=r['chart_cold_seconds'],width=.16,color=colors[m],label=names[m] if j==0 else None)
        ax.set(title=case,ylabel='End-to-end diagnosis (s)',xticks=[0,1],xticklabels=['Final snapshots','Frequent snapshots']);ax.grid(axis='y',alpha=.2)
    axes[0].legend(fontsize=8);fig.text(.5,.01,'Median-total run: hatched = cold construction; solid = on-demand diagnosis and explicit output.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.04,1,1));fig.savefig(folder/'diagnosis_task.png');fig.savefig(folder/'diagnosis_task.pdf');plt.close(fig)
    selected=json.loads((OUT/'robustness_selection.json').read_text())['selected'] if (OUT/'robustness_selection.json').exists() else []
    if selected:
        fig,ax=plt.subplots(figsize=(8,4))
        for ix,case in enumerate(selected):
            for j,(seed,order) in enumerate(((1,0),(1,1),(2,0),(2,1))):
                a,b=get('bench',label(case),'B2',seed=seed,order=order),get('bench',label(case),'BD',seed=seed,order=order)
                if a and b and 'total_seconds' in a and 'total_seconds' in b:
                    ax.scatter(ix+(j-1.5)*.09,a['total_seconds']/b['total_seconds'],s=50,color=['#315ca8','#c16b22','#10816b','#a34e94'][j],label=f'seed {seed}, order {order}' if ix==0 else None)
        ax.axhline(1,color='gray',ls='--');ax.set(xticks=range(len(selected)),xticklabels=[label(c) for c in selected],ylabel='Compiled / component SAT end-to-end cost',yscale='log')
        ax.grid(axis='y',alpha=.2);ax.legend(fontsize=8);fig.tight_layout();fig.savefig(folder/'query_robustness.png');fig.savefig(folder/'query_robustness.pdf');plt.close(fig)


if __name__=='__main__':main()
