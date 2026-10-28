"""Render the Chinese evidence ledger directly from the saved measurements."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/causal_followup_20261028'


def table(headers,rows):
    return '\n'.join([' | '.join(headers),' | '.join('---' for _ in headers)]+[' | '.join(map(str,r)) for r in rows])


def main():
    data=json.loads((OUT/'tables.json').read_text());rows=data['rows']
    raw=json.loads((OUT/'summary.json').read_text())['rows']
    abl=json.loads((OUT/'ablation.json').read_text())
    def f(x):return f'{x:.4f}'
    def find(family,n,u,m):return next(r for r in rows if (r['family'],r['rounds'],r['U'],r['method'])==(family,n,u,m))
    configs=[('barrier',n,u) for n in (8,16) for u in (21,100,500,1000)]+[('buffer',8,u) for u in (100,1000)]
    pivot=[]
    for family,n,u in configs:
        vals=[]
        for m in ('B0','B1','BD','B2'):
            r=find(family,n,u,m)
            vals.append(f(r['total_seconds']) if 'total_seconds' in r else '/'.join(r['status_counts']))
        pivot.append([family,n,u]+vals)
    cost=[]
    for r in rows:
        if 'total_seconds' not in r:continue
        cost.append([r['family'],r['rounds'],r['U'],r['method']]+[f(r[k]) for k in
            ('cold_seconds','miss_compute_seconds','hit_seconds','output_seconds','query_seconds','total_seconds')])
    novelty=[]
    for family,n,u in configs:
        r=find(family,n,u,'B2')
        novelty.append([family,n,u,r['distinct_answers'],r['cache_hits'],r['cache_misses'],u-10,10])
    local=[]
    for r in rows:
        if r['method']=='BD' and 'local_misses' in r:
            local.append([r['family'],r['rounds'],r['U'],r['components'],r['local_hits'],r['local_misses'],r['component_sat_calls']])
    missing=[]
    for r in rows:
        if 'total_seconds' in r:
            missing.append([r['family'],r['rounds'],r['U'],r['method'],f(r['sat_miss_compute_seconds']),f(r['unsat_miss_compute_seconds'])])
    failures=[]
    for r in raw:
        if r['status']!='OK':
            failures.append([r['family'],r['rounds'],r['U'],r['method'],r['status'],r['phase'],len(r['queries']),f(r['controller_seconds'])])
    mechanisms=[]
    for r in abl:
        if 'K' in r:
            mechanisms.append([r['rounds'],r['version'],r['K'],r['groups'],r['Smax'],r['states'],r['transitions']]+[f(r[k]) for k in ('T_plan','T_compile','T_query100','T_cold100')])
        else:mechanisms.append([r['rounds'],r['version'],'/'.join(r['statuses'])]+['—']*8)
    thresholds=[]
    for r in data['crossovers']:
        if r['baseline']=='BD':thresholds.append([r['family'],r['rounds'],r['U'],r['first_sustained_faster_prefix'] if r['first_sustained_faster_prefix'] is not None else '无'])
    a=find('barrier',8,1000,'B2');b=find('barrier',8,1000,'BD')
    shapes=[]
    for family,n in (('barrier',8),('barrier',16),('buffer',8)):
        r=next(r for r in raw if r['family']==family and r['rounds']==n and r['method']=='B2' and r['U']==100 and r['repeat']==0)
        shapes.append([family,n,r['N'],r['X'],r['plan_stats']['actual_K'],r['plan_stats']['groups'],
            r['compile_stats']['max_layer_states'],r['compile_stats']['states'],r['compile_stats']['transitions']])
    text=f'''新假设、局部分解与性能机制：后续实验交付
2026-10-28；不扩展理论范围、内存模型或协议种类

一、可以据此作出的判断

主屏障族确实存在容易提取的按轮分解。1/2/3轮原始完整关系分别含9/81/729
个模型，并逐集合等于各CNF组件关系的笛卡尔积；独立RA检查覆盖每个正模型。
8/16轮的实际简化CNF分别形成8/16个含原始位的组件，每个6个自由位、9个
原始投影。跨轮原始变量固定。恒定层状态不能被解释为持续跨轮相关性的证据。
这没有推翻结构界或支持保真，但修正了屏障性能实验的归因。

新假设实验保留了编译相对全局SAT的收益，也测出了组件基线的竞争力。
8轮U=1000时，B2为{f(a['total_seconds'])}秒，组件SAT为{f(b['total_seconds'])}秒。
它们均返回1000个完整支持答案；组件基线只遇到{b['local_misses']}个不同局部
子问题。因此不能写成“面对全新假设，编译普遍胜过利用独立分解的SAT”。
收益应同时用全局假设新颖度、局部子问题新颖度和冷启动成本解释。
在两个屏障规模的实测中，U<=500的端到端中位数仍有利于B2，而U=1000时
均由BD胜出。8轮U=500仅有小幅中位数差距，不能写成稳定的大幅优势。

已有branch缓冲8轮/C=3保留跨轮来源关联，另测U=100和1000。这里CNF含一个
40自由原始位的组件；两个不同阶段的RF文字分别可满足、合取不可满足，
由无协议过滤的原始SAT核查，两个正见证再用独立RA定义检查。它检验同一
工具在已有范围内不同关联结构的表现；该变体CO多固定，不替代多写者屏障。

二、实验合同与公平性

B0：原始RA增量SAT；B1：同证书预处理后的全局增量SAT；BD：B1同一CNF经
普通单位传播和变量关联分量后建立局部SAT；B2：同证书/计划完整编译。
四方使用同一全局alpha→完整答案缓存。BD另外缓存组件alpha→局部完整支持。
分区包括所有辅助变量，不读取轮号、不预先枚举模型、不输入“9”。纯辅助
组件也检查SAT。CNF生成、单位传播、分区和局部求解器构造全部计冷启动。
完整支持保留所有原始RF/CO，包括识别后常量；没有只返回未定部分。
三个固定输入的构造规模如下，不随U变化：
{table(['族','轮','事件','全部原始位','K','groups','Smax','states','transitions'],shapes)}

每输入Q=1000；U为21/100/500/1000。每条SAT alpha长度4、每条UNSAT长度2，
所有序列严格990次SAT、10次UNSAT，平均长度3.98。每个文字两极性有根支持，
SAT条件逐文字检查不可冗余，UNSAT对是最小冲突；两来源RF只取一个坐标。
无排列/重复文字/常量填充。主屏障每条SAT条件约束4个不同阶段。
99%SAT是为了避免以无关文字制造大量“新”无解条件；这是任务分布边界。
缺失中的SAT比例随U变化，故另列SAT/UNSAT缺失成本。U=21重现复用率，
不是重放旧21个条件，旧时延不可与本批次拼接。嵌套池、种子和输入哈希已保存。

每成功点3次独立进程，单CPU亲和；60秒/1GiB。失败保留一次及已保存前缀。
算法计时包括生成输入、证书构造及同核重放、编码/计划/编译、查询和显式
完整支持列表构造排序；不含结果哈希、JSON审计落盘或外部传输。
硬上限包含进程启动和审计IO，不能把TIMEOUT直接当算法耗时大于60秒。
证书重放不是独立语义证明。计时源码前后哈希相同，原始失败完整保留。
成功/失败记录数：{data['status_counts']}；共同已保存答案前缀不一致数：{len(data['answer_discrepancies'])}。

三、新假设矩阵：冷启动加1000请求中位数，秒

{table(['族','轮','U','B0','B1','BD组件SAT','B2编译'],pivot)}

不同答案按“SAT标志+全部原始支持集合”计数，所有UNSAT共用一个答案：
{table(['族','轮','U','不同完整答案','全局命中','全局缺失','SAT缺失','UNSAT缺失'],novelty)}

所有成功点的分项中位数如下。命中成本已包含该次输出；“输出”列跨全部
请求，亦已包含在查询总计中，因此各列不能再次相加。冷+查询=端到端只对
单次成立，各列独立取中位数后可能有小差异。
{table(['族','轮','U','方法','冷','缺失计算','命中含输出','全部输出','全部查询','冷+查询'],cost)}

SAT与UNSAT缺失计算分开计时，秒：
{table(['族','轮','U','方法','SAT缺失','UNSAT缺失'],missing)}

BD的局部缓存实际使用量；纯辅助组件SAT检查计入SAT调用数：
{table(['族','轮','U','含原始位组件','局部命中','局部缺失','SAT调用'],local)}

四、累计成本与适用范围

每次请求的耗时和答案哈希保存于runs/*.json，cumulative.json给出包含冷启动
的0..1000前缀中位数轨迹。下表是B2开始并持续比BD便宜直到第1000请求的
最早前缀；0表示从冷启动就便宜，“无”表示测量终点未胜出。它是固定序列
的描述，不是任意查询的理论摊销阈值，也不适用于不同长度/分布的假设。
{table(['族','轮','U','B2相对BD持续更快的首前缀'],thresholds)}

主屏障中局部缺失很快饱和；全局U增长并不等于局部新问题增长。B2查询成本
随全局缺失增加，而BD可以组合已缓存局部支持。应同时呈现冷与温态成本，
不把冷启动的优势写成每次新条件求解都更快；不把一般SAT基线视为最强分解器。
本轮未接入真实搜索器，也未声称这组查询代表所有实际使用分布。

资源失败及已落盘请求前缀（可能少于最后实际执行数）：
{table(['族','轮','U','方法','状态','阶段','已保存请求','控制器秒'],failures)}

五、机制账本与长写间隔的廉价布局对照

sparse_special=稀疏CO/专门计划；sparse_input_order=稀疏CO/普通输入事件序；
dense_special=稠密CO/专门计划。前三种来自保留的上一批次；gap两种来自本轮
顺序运行的匹配新批次，Q=100，不能与主矩阵Q=1000混为同一任务。
下面的groups、states、transitions为实际构造数，Smax为最大可达层状态数。
T_plan/T_compile/T_query100/T_cold100均为秒；cold100含冷启动和100次查询。
{table(['轮','版本','K','groups','Smax','states','transitions','T_plan','T_compile','T_query100','T_cold100'],mechanisms)}

稀疏CO同时改变了活跃候选结构、组数和处理成本，因此整个加速不能单独归因
于K。K是结构上界而非精确运行时间预测器；实际可达状态、转移、组数和计划
成本必须一起解释。便宜的输入事件序与专门布局对照独立于此前线程串接差序。
即使普通序相近或更快，有证明且无需布局搜索的构造仍是一项理论贡献；
不能由该事实进一步推断专门布局在这些实测实例上总是最优。
长间隔三种规模中，普通输入序K恒为17、专门计划K恒为15；16轮普通序的
端到端中位数更低，32轮两者约2秒。这不是专门计划相对廉价布局的大幅优势。

六、验收与制品

82项单元测试，79通过、3项可选BDD依赖跳过；新增组件基线包含单轮所有
3^6个原始部分赋值的完整支持对照。分解审计比较完整原始集合而非仅计数。
本轮没有把1/2/3轮计数直接外推为任意n的定理；8/16轮各自有实际CNF分区和
局部关系认证。更大规模的完整支持一致仍是相关算法对照，不是机械化证明。
仍保留此前恒定载荷6轮失败、4轮SAT更快、版本值缩小来源域等历史边界；
本轮特定屏障/缓冲成功不覆盖掉那些不同族和任务的失败。旧论文PDF未更新。

规范：docs/CAUSAL_FOLLOWUP_SPEC.zh.txt。
分解证明与证据边界：docs/CAUSAL_DECOMPOSITION_DIAGNOSIS.zh.txt。
复现：docs/CAUSAL_FOLLOWUP_REPRODUCE.zh.txt。
新实现：wmcheck/ra_component_sat.py；原SAT增加可选clause sink，默认路径不变。
原始数据、完整参数和图：results/causal_followup_20261028/。
图1 figures/new_assumptions.png/pdf：端到端成本随U变化；阴影为3次范围。
图2 figures/component_reuse.png/pdf：缺失计算与局部新颖度饱和。
图3 figures/cumulative_new.png/pdf：全新假设序列下BD/B2累计端到端曲线。
归档：artifacts/causal_followup_20261028.zip，独立于旧pilot包；SHA256清单及
恢复回执在同目录。恢复验收复用已安装环境，不冒称全新操作系统安装测试。
当前结果仅本地，未提交/推送GitHub；没有改写或扩张原理论适用范围。
'''
    (ROOT/'CAUSAL_FOLLOWUP_RESULTS.zh.txt').write_text(text,encoding='utf8')
    print(ROOT/'CAUSAL_FOLLOWUP_RESULTS.zh.txt')


if __name__=='__main__':main()
