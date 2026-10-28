"""Render publication figures/tables from frozen results. Never runs a solver.

Usage: python generate_results.py [--repo ROOT]
All reads are recorded with SHA-256 in generated/data_manifest.json.
"""
from pathlib import Path
import argparse, gzip, hashlib, json, statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, default=HERE.parent)
parser.add_argument('--snapshot', action='store_true', help='Read the bundled frozen inputs instead of the repository')
args = parser.parse_args()
ROOT = args.repo.resolve()
OUT = HERE / 'generated'
FIG = HERE / 'figures'
OUT.mkdir(exist_ok=True); FIG.mkdir(exist_ok=True)
manifest = {}
snapshot_path=HERE/'data'/'frozen_inputs.json.gz'
snapshot=json.loads(gzip.decompress(snapshot_path.read_bytes())) if args.snapshot else None
raw_inputs={}
def read(rel):
    p = ROOT / rel
    b = snapshot[rel].encode('utf-8') if snapshot is not None else p.read_bytes()
    raw_inputs[rel]=b.decode('utf-8')
    manifest[rel] = hashlib.sha256(b).hexdigest()
    return json.loads(b)

base = 'results/causal_evidence_20261028'
old = 'results/causal_followup_20261028'
d = read(f'{base}/tables.json')
f = read(f'{old}/tables.json')
ablation = read(f'{old}/ablation.json')
env = read(f'{base}/environment.json')
structures = {s['case']: s for s in d['structures']}
methods = ['B0', 'B1', 'BD', 'B2']
colors = {'B0':'#757575', 'B1':'#d18b24', 'BD':'#36799a', 'B2':'#a34250'}
markers = {'B0':'o', 'B1':'s', 'BD':'^', 'B2':'D'}
plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':9,
                     'axes.spines.top':False, 'axes.spines.right':False,
                     'axes.labelsize':9, 'legend.fontsize':8,
                     'pdf.fonttype':42, 'ps.fonttype':42,
                     'savefig.bbox':'tight', 'axes.titleweight':'medium'})
def row(case, method, mode='bench', profile=''):
    rows = [r for r in d['tables'] if r['case']==case and r['method']==method
            and r['mode']==mode and r['profile']==profile and r['seed']==0 and r['order']==0]
    assert len(rows)==1, (case,method,mode,profile)
    return rows[0]
def errline(ax, xs, rows, method):
    good=[(x,r) for x,r in zip(xs,rows) if r.get('successful_repeats',3)>0 and 'total_seconds' in r]
    # NaNs break a line at an unfinished observation; never interpolate failures.
    ys=[r.get('total_seconds',np.nan) for r in rows]
    ax.plot(xs,ys,marker=markers[method],color=colors[method],label=method,lw=1.5,ms=4)
    if good:
        gx=[x for x,r in good]; gy=[r['total_seconds'] for x,r in good]
        lo=[r['total_seconds']-r['total_min'] for x,r in good]
        hi=[r['total_max']-r['total_seconds'] for x,r in good]
        ax.errorbar(gx,gy,yerr=[lo,hi],fmt='none',ecolor=colors[method],capsize=2,lw=.8)
    ax.set_yscale('log'); ax.grid(axis='y',alpha=.22)
def save(fig,name):
    fig.savefig(FIG/f'{name}.pdf',metadata={'CreationDate':None,'ModDate':None})
    fig.savefig(FIG/f'{name}.png',dpi=180)
    plt.close(fig)
def tex(name,body):
    (OUT/f'{name}.tex').write_text('% Generated from frozen JSON; do not edit.\n'+body+'\n',encoding='utf-8')
def table(headers, rows, spec):
    return '\\begin{tabular}{'+spec+'}\n\\toprule\n'+' & '.join(headers)+' \\\\\n\\midrule\n'+'\n'.join(' & '.join(map(str,r))+' \\\\' for r in rows)+'\n\\bottomrule\n\\end{tabular}'
def num(x): return f'{x:.4f}'
def cost(r):
    if 'total_seconds' in r: return num(r['total_seconds'])
    status=next(iter(r.get('statuses',r.get('status_counts',{}))))
    return {'RESOURCE_LIMIT':'状态上限','TIMEOUT':'超时'}.get(status,status.replace('_',r'\_'))

# Fixed capacity / growing history.
rs=[4,8,16,32]
fig,ax=plt.subplots(figsize=(6.5,3.1),layout='constrained')
for method in methods: errline(ax,rs,[row(f'buffer_n{r}_c3',method) for r in rs],method)
ax.set_xticks(rs); ax.set_xlabel('History length (rounds r)'); ax.set_ylabel('Cold + 1,000 full-support requests (s)')
ax.text(.59,.97,'r = 16, 32: B0 / B1 / BD\nTIMEOUT (60 s process budget)',transform=ax.transAxes,va='top',ha='left',fontsize=8)
ax.legend(loc='upper left',ncol=4,frameon=False)
save(fig,'history_cost')
fig,axes=plt.subplots(1,2,figsize=(6.5,2.55),layout='constrained')
for key,label,marker in [('states','Total states','o'),('transitions','Transitions','s')]:
    axes[0].plot(rs,[structures[f'buffer_n{r}_c3']['graph'][key] for r in rs],marker=marker,label=label,lw=1.4)
axes[0].set_ylabel('Count'); axes[0].legend(frameon=False); axes[0].ticklabel_format(axis='y',style='plain')
axes[1].plot(rs,[structures[f'buffer_n{r}_c3']['graph']['max_layer_states'] for r in rs],marker='D',color=colors['B2'])
axes[1].set_ylabel('Maximum reachable layer states'); axes[1].set_ylim(0,40)
for ax in axes: ax.set_xticks(rs); ax.set_xlabel('History length (rounds r)'); ax.grid(alpha=.2,axis='y')
save(fig,'history_states')
tex('history_structure',table([r'$r$',r'$n$',r'$|X|$',r'$|D|$',r'歧义读',r'$K$',r'组数',r'$S_{\max}$',r'状态',r'转移'],
    [[r,s['events'],s['original_variables'],s['remaining_RF_candidates'],s['ambiguous_reads'],s['plan']['actual_K'],s['plan']['groups'],s['graph']['max_layer_states'],s['graph']['states'],s['graph']['transitions']]
     for r in rs for s in [structures[f'buffer_n{r}_c3']]],'rrrrrrrrrr'))

caps=[]
for C in [2,3,4,6]:
    case=f'buffer_n8_c{C}'; s=structures[case]; success=s['compile_status']=='OK'
    caps.append([C,s['max_RF_domain'],s['plan']['actual_K'],s['plan']['groups'],
                 s['graph']['max_layer_states'] if success else '$\\ge '+str(s['partial_graph']['max_layer_states'])+r'$\tnote{a}',
                 s['graph']['states'] if success else str(s['partial_graph']['states'])+r'\tnote{a}',
                 cost(row(case,'BD')),cost(row(case,'B2'))])
tex('capacity',table([r'$C$',r'$\max|D(r)|$',r'$K$',r'组数',r'$S_{\max}$',r'状态',r'BD (s)',r'B2 (s)'],caps,'rrrrrrrr'))

# Fresh-query matrix belongs to a separate, explicitly labelled batch.
Us=[21,100,500,1000]
fig,axes=plt.subplots(1,2,figsize=(6.5,3),layout='constrained')
for ax,r in zip(axes,[8,16]):
    for method in methods:
        rows=[next(z for z in f['rows'] if z['family']=='barrier' and z['rounds']==r and z['U']==u and z['method']==method) for u in Us]
        errline(ax,Us,rows,method)
    ax.set_title(f'Barrier, r = {r}'); ax.set_xlabel('Distinct assumptions U (Q = 1,000)')
    ax.set_xscale('log'); ax.set_xticks(Us,labels=['21','100','500','1000']); ax.minorticks_off()
    ax.text(.98,.97,'B0: timeout at '+('1,000' if r==8 else '500 / 1,000')+('\nB1: timeout at 1,000' if r==16 else ''),transform=ax.transAxes,ha='right',va='top',fontsize=7)
axes[0].set_ylabel('Cold + requests (s)'); axes[0].legend(ncol=2,frameon=False,loc='lower right')
save(fig,'query_reuse')
reuse=[]
for r in [8,16]:
    for u in Us:
        z={m:next(z for z in f['rows'] if z['family']=='barrier' and z['rounds']==r and z['U']==u and z['method']==m) for m in methods}
        reuse.append([r,u,1000-u,z['B2']['distinct_answers'],z['BD']['local_misses'],cost(z['B1']),cost(z['BD']),cost(z['B2'])])
tex('reuse',table([r'$r$',r'$U$',r'全局命中',r'不同答案',r'BD 局部缺失',r'B1 (s)',r'BD (s)',r'B2 (s)'],reuse,'rrrrrrrr'))

# Cold / warm / total are separate panels; each uses its own repeated samples.
fig,axes=plt.subplots(2,3,figsize=(6.65,4.8),layout='constrained')
for j,case in enumerate(['barrier_n8','buffer_n8_c3']):
    for k,metric in enumerate(['cold_seconds','task_seconds','total_seconds']):
        ax=axes[j,k]
        for mi,method in enumerate(methods):
            vals=[]; lows=[]; highs=[]
            for profile in ['sparse','dense']:
                raw=[read(f'{base}/tasks/{case}_{profile}_{method}_r{i}.json')[metric] for i in range(3)]
                med=statistics.median(raw); vals.append(med); lows.append(med-min(raw)); highs.append(max(raw)-med)
                assert abs(med-row(case,method,'task',profile)[metric])<1e-8
            xx=np.arange(2)+(mi-1.5)*.19
            ax.bar(xx,vals,.18,color=colors[method],label=method,yerr=[lows,highs],error_kw={'lw':.7,'capsize':1.5})
        ax.set_xticks([0,1],['Final','Frequent']); ax.set_ylabel('Seconds'); ax.set_yscale('log'); ax.grid(alpha=.2,axis='y')
        if j==0: ax.set_title(['Cold construction','Warm task','End to end'][k])
        if k==0: ax.text(.02,.98,'Barrier r=8' if j==0 else 'Buffer r=8, C=3',transform=ax.transAxes,va='top',fontsize=8)
handles,labels=axes[0,0].get_legend_handles_labels()
fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False)
save(fig,'diagnosis')

# Mechanism audit uses the recorded ablation provenance, no recomputed timings.
mechanisms=[]
for z in ablation:
    if z['rounds']==16:
        names={'sparse_special':'稀疏／专用','dense_special':'稠密／专用','sparse_input_order':'稀疏／普通','gap_special':'长间隔／专用','gap_ordinary':'长间隔／普通'}
        mechanisms.append([names.get(z['version'],z['version'].replace('_',r'\_')),z['K'],z['groups'],z['Smax'],z['states'],z['transitions'],num(z['T_plan']),num(z['T_compile']),num(z['T_query100']),num(z['T_cold100'])])
tex('mechanism',table(['表示／布局',r'$K$','组',r'$S_{\max}$','状态','转移',r'$T_{\rm plan}$',r'$T_{\rm compile}$',r'$T_{\rm query}$','总计'],mechanisms,'lrrrrrrrrr'))

# Detailed service costs: display separate medians, not their sum.
detail=[]
for case in [f'buffer_n{r}_c3' for r in rs]+['buffer_n8_c2','buffer_n8_c4','buffer_n8_c6']:
    s=structures[case]
    for method in methods:
        z=row(case,method)
        if 'total_seconds' in z:
            detail.append([f"{s['parameters']['rounds']}/{s['parameters']['capacity']}",method,z['U'],z['distinct_answers'],num(z['cold_seconds']),num(z.get('miss_compute_seconds',0)),num(z.get('output_seconds',0)),num(z['total_seconds'])])
        else:
            detail.append([f"{s['parameters']['rounds']}/{s['parameters']['capacity']}",method,'--','--','--','--','--',cost(z)])
tex('service_costs',table([r'$r/C$','方法',r'$U$','答案','冷启动','缺失计算','输出','总计'],detail,'llrrrrrr'))

# Macro values used in prose are read from the same rows as the plots.
macros={
 'HistoryFour':num(row('buffer_n4_c3','B2')['total_seconds']),
 'HistoryThirtyTwo':num(row('buffer_n32_c3','B2')['total_seconds']),
 'BufferEightBTwo':num(row('buffer_n8_c3','B2')['total_seconds']),
 'BufferEightBD':num(row('buffer_n8_c3','BD')['total_seconds']),
 'BufferRatio':f"{row('buffer_n8_c3','BD')['total_seconds']/row('buffer_n8_c3','B2')['total_seconds']:.1f}",
 'BufferSparseBD':num(row('buffer_n8_c3','BD','task','sparse')['total_seconds']),
 'BufferSparseBTwo':num(row('buffer_n8_c3','B2','task','sparse')['total_seconds']),
 'BufferDenseBD':num(row('buffer_n8_c3','BD','task','dense')['total_seconds']),
 'BufferDenseBTwo':num(row('buffer_n8_c3','B2','task','dense')['total_seconds']),
}
tex('numbers','\n'.join('\\newcommand{\\'+k+'}{'+v+'}' for k,v in macros.items()))
(OUT/'data_manifest.json').write_text(json.dumps({'baseline_commit':'2a70e4d46ef76e0cdd742d57017cb508cf7834f8','inputs_sha256':manifest,'outputs':sorted(p.name for p in FIG.iterdir())},indent=2)+'\n',encoding='utf-8')
(OUT/'plotted_data.json').write_text(json.dumps({'evidence_rows':d['tables'],'followup_rows':f['rows'],'macros':macros},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if snapshot is None:
    snapshot_path.parent.mkdir(exist_ok=True)
    snapshot_path.write_bytes(gzip.compress(json.dumps(raw_inputs,ensure_ascii=False,sort_keys=True).encode('utf-8'),mtime=0))
print(f'Rendered {len(list(FIG.glob("*.pdf")))} figures and {len(list(OUT.glob("*.tex")))} table/macro files from {len(manifest)} frozen JSON files; no experiments run.')
