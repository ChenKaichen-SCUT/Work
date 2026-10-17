"""Regenerate manuscript tables/figures from frozen JSON; never run benchmarks."""
from pathlib import Path
import csv, json, hashlib, shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / 'data'
DATA.mkdir(exist_ok=True)
SOURCES = {
    'task': 'results/support_task_20261016/summary.json',
    'demand': 'results/support_task_20261016/demand_summary.json',
    'native': 'results/support_task_20261016/native_analysis/summary.json',
    'native_sets': 'results/support_task_20261016/native_full_set_audit.json',
    'ring': 'results/fm_evidence_20261016/ring_summary.json',
    'structure': 'results/fm_evidence_20261016/structure_audit.json',
}
raw = {}
manifest = {}
for name, relative in SOURCES.items():
    src = ROOT / relative
    # The bundled copies make regeneration independent of the original checkout.
    if src.exists():
        shutil.copyfile(src, DATA / (name + '.json'))
    path = DATA / (name + '.json')
    raw[name] = json.loads(path.read_text(encoding='utf-8'))
    manifest[name] = {'source': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
(DATA/'provenance.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
for font in [Path('C:/Windows/Fonts/msyh.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]:
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=str(font)).get_name()
        break
plt.rcParams.update({'font.size': 9, 'axes.labelsize': 9, 'axes.titlesize': 10,
 'legend.fontsize': 8, 'axes.spines.top': False, 'axes.spines.right': False,
 'pdf.fonttype': 42, 'axes.unicode_minus': False, 'lines.linewidth': 1.6})
COLORS = ['#176B87','#B9513F','#6F699B','#5A8060']
rows = raw['task']['rows']
def row(payload,n,method):
    candidates = [r for r in rows if (r['payload'],r['n'],r['method']) == (payload,n,method)]
    return max(candidates, key=lambda r: r['budget_states']) if candidates else None
def demand(payload,n):
    return next((r for r in raw['demand'] if (r['payload'],r['n']) == (payload,n)),None)
def fmt(v): return f'{v:.3f}' if v is not None else '--'
def table(name, lines): (HERE/'tables'/name).write_text('\n'.join(line + chr(92) if line.endswith(chr(92)) and not line.endswith(chr(92)*2) else line for line in lines)+'\n', encoding='utf-8')
def save(name):
    plt.savefig(HERE/'figures'/f'{name}.pdf', bbox_inches='tight', pad_inches=.04)
    plt.savefig(HERE/'figures'/f'{name}.png', dpi=180, bbox_inches='tight', pad_inches=.04)
    plt.close()
flat = []
for r in rows:
    flat.append({k:r.get(k) for k in ['payload','n','method','budget_states','statuses','events','original_variables','build_median','query_median','task_median','query_calls','reports','peak_rss_kib']})
with (DATA/'measurements.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=flat[0].keys()); writer.writeheader(); writer.writerows(flat)

# Table 1: complete client times. UNKNOWN/error is never assigned a time.
lines=[]
for n in [2,4,8,16,32,64]:
    a=row('epoch',n,'ports-atomic'); b=row('epoch',n,'ports-binary')
    s=row('epoch',n,'sat-phase'); d=demand('epoch',n); z=row('epoch',n,'bdd-coherence')
    def val(r,key='task_median'):
        if r is None: return '--'
        if r.get(key) is not None: return fmt(r[key])
        return r['statuses'][0].replace('UNKNOWN',r'\textsc{unk}').replace('ERROR',r'\textsc{err}')
    lines.append(f"{n}{'$^*$' if n==64 else ''} & {a['events']} & {a['original_variables']} & {val(a)} & {val(b)} & {val(s)} & {val(d,'total_median')} & {val(z)} \\")
table('timing_rows.tex',lines)
lines=[]
for n in [2,4,8,16,32,64]:
    r=row('epoch',n,'ports-atomic'); s=r['stats']
    lines.append(f"{n}{'$^*$' if n==64 else ''} & {s['raw_states']:,} & {s['states']:,} & {s['max_layer_states']:,} & {fmt(r['build_median'])} & {r['reports']} & {r['query_calls']} \\")
table('size_rows.tex',lines)
lines=[]
for n in [2,3,4,6]:
    a=row('constant',n,'ports-atomic'); d=demand('constant',n); z=row('constant',n,'bdd-coherence')
    lines.append(f"{n} & {val(a)} & {val(d,'total_median')} & {val(z)} \\")
table('constant_rows.tex',lines)
lines=[]
for r in raw['ring']:
    desc=f"{r['workers']}线程/{r['rounds']}轮"
    if r['irregular']: desc+='，非均匀'
    if not r['source_covers']: desc+=r'，无$R_\forall$'
    s=r.get('stats',{})
    lines.append(f"{desc} & {r['events']} & {r['original_variables']} & {s.get('raw_states',r'$>10^6$')} & {s.get('states','--')} & {r['query_count']} & {'完成' if r['status']=='ok' else r'\textsc{unk}'} \\")
table('ring_rows.tex',lines)
lines=[]
for n in [2,3,4,8,16]:
    nr=[r for r in raw['native'] if r['n']==n]
    v=next(r for r in nr if r['mode']=='values'); k=next(r for r in nr if r['mode']=='k0')
    lines.append(f"{n} & {v['rf_may']} & {k['rf_may']} & {k['r5_rf']} & {k['required_common_hb']-k['found_common_hb']}/{k['required_common_hb']} & 是 \\")
table('native_rows.tex',lines)

fig, axes=plt.subplots(1,2,figsize=(6.1,2.8),layout='constrained')
for ax,payload,ns,title in [(axes[0],'epoch',[2,4,8,16,32],'(a) 版本载荷'),(axes[1],'constant',[2,3,4,6],'(b) 恒定载荷')]:
    for i,(method,label) in enumerate([('ports-atomic','端口／原子 RF'),('demand','稠密 SAT／按需'),('bdd-coherence','CUDD BDD')]):
        points=[]
        for n in ns:
            r=demand(payload,n) if method=='demand' else row(payload,n,method)
            y=r.get('total_median' if method=='demand' else 'task_median') if r else None
            if y is not None: points.append((n,y))
        ax.plot(*zip(*points),marker=['o','s','^'][i],color=COLORS[i],label=label,markersize=4)
    ax.set_yscale('log'); ax.set_xticks(ns); ax.set_xlabel('轮数 n'); ax.set_title(title); ax.grid(axis='y',alpha=.2)
axes[0].set_ylabel('完整诊断任务时间（秒，对数轴）')
axes[0].legend(loc='lower right',frameon=False)
axes[1].text(.97,.03,'端口：6 轮状态超限',ha='right',transform=axes[1].transAxes,fontsize=8,color=COLORS[0])
save('task_times')

fig,axes=plt.subplots(1,2,figsize=(6.1,2.75),layout='constrained')
ns=[2,4,8,16,32,64]
for key,label,c in [('raw_states','累计构造状态',COLORS[0]),('states','后缀商后状态',COLORS[1])]:
    ys=[row('epoch',n,'ports-atomic')['stats'][key] for n in ns]
    axes[0].plot(ns,ys,'o-',label=label,color=c,markersize=3)
    axes[0].plot([64],[ys[-1]],'D',mfc='white',mec=c,ms=6)
axes[0].axhline(1e6,color='.5',ls='--',lw=.8); axes[0].text(3,1.15e6,'正式状态上限',fontsize=7)
axes[0].set_xscale('log',base=2); axes[0].set_yscale('log'); axes[0].set_xticks(ns,ns); axes[0].set_xlabel('轮数 n（64 轮为单次压力点）'); axes[0].set_ylabel('状态数'); axes[0].legend(frameon=False,loc='lower right')
axes[1].plot(ns,[row('epoch',n,'ports-atomic')['stats']['max_layer_states'] for n in ns],'o-',color=COLORS[0],markersize=3)
axes[1].set_xscale('log',base=2); axes[1].set_xticks(ns,ns); axes[1].set_ylim(0,1450); axes[1].set_ylabel('最大单层状态数'); axes[1].set_xlabel('轮数 n'); axes[1].text(10,1280,'已测 n ≥ 8：1,230',fontsize=8)
for ax in axes: ax.grid(axis='y',alpha=.2)
save('graph_scaling')

fig,axes=plt.subplots(1,2,figsize=(6.1,2.7),layout='constrained')
ns=[2,4,8,16]
sr=[next(r for r in raw['structure']['structural_cases'] if r['family']=='ring' and r['workers']==3 and not r['irregular'] and r['rounds']==n) for n in ns]
axes[0].plot(ns,[r['k0_unresolved_co'] for r in sr],'s--',color=COLORS[1],label=r'$K_0$')
axes[0].plot(ns,[r['unresolved_co'] for r in sr],'o-',color=COLORS[0],label=r'$K_\forall$')
axes[0].set_ylabel('未决 CO 对数'); axes[0].legend(frameon=False)
axes[1].plot(ns,[r['atomic_observed_width'] for r in sr],'o-',color=COLORS[0]); axes[1].set_ylabel('实际事件袋大小'); axes[1].set_ylim(0,40)
for ax in axes: ax.set_xticks(ns); ax.set_xlabel('三线程环轮数 n'); ax.grid(axis='y',alpha=.2)
axes[1].text(4,6,'8／16 轮仅做结构核查',fontsize=8)
save('ring_structure')

# A schematic, not a timing or protocol execution trace.
fig,ax=plt.subplots(figsize=(6.1,2.75),layout='constrained'); ax.set_xlim(0,10); ax.set_ylim(-.3,4.8); ax.axis('off')
ax.text(.1,4.5,'线程 A：第 1 轮',fontsize=10,color=COLORS[0]); ax.text(5.9,4.5,'线程 B：第 2 轮',fontsize=10,color=COLORS[1])
left=[r'$W(x,1)$',r'$a_0: W(f_a,1)$',r'$u: W(y,1)$',r'$a_1: W(f_a,1)$']
right=[r'$v: W(y,2)$',r'$W(f_b,0)$',r'$r: R(f_a,1)$',r'$s: R(y,2)$']
for x,labels in [(1.6,left),(7.8,right)]:
    for i,label in enumerate(labels):
        y=3.8-i
        ax.text(x,y,label,ha='center',va='center',bbox=dict(boxstyle='round,pad=.25',fc='#F3F5F6',ec='#AEBAC1'),fontsize=9)
        if i<3: ax.annotate('',(x,y-.72),(x,y-.24),arrowprops=dict(arrowstyle='->',color='.45',lw=1))
ax.annotate('',(6.65,1.8),(2.9,2.8),arrowprops=dict(arrowstyle='->',color=COLORS[0],ls='--',lw=1.7)); ax.text(4,2.55,'早来源 e',color=COLORS[0],fontsize=8)
ax.annotate('',(6.65,1.65),(2.9,.8),arrowprops=dict(arrowstyle='->',color=COLORS[1],lw=1.7)); ax.text(4,.75,'晚来源 l',color=COLORS[1],fontsize=8)
ax.text(4.7,3.75,r'$q: u <_{co} v$',ha='center',fontsize=10)
ax.text(4.7,-.15,'仅画相关事件；d 固定 s 从 v 读取。两次发布的值相同，因果覆盖不同。',ha='center',fontsize=8)
save('identity_example')
print('Generated 4 figures, 5 table fragments, CSV and provenance from frozen sources.')
