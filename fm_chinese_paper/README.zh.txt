中文研究稿与图表重建
==================
主文件 main.tex；原始 llncs.cls 与 splncs04.bst 从用户指定 Template 目录复制，未修改。
采用 LNCS 单栏结构，额外使用 ctex/XeLaTeX 排版中文；本稿依用户要求不压页数。
作者匿名，未虚构作者、单位、致谢或资助。正式 FM 投稿需要另行转换为英文并核对届次格式。

编译（TeX Live + XeLaTeX）：
  xelatex -interaction=nonstopmode -halt-on-error main.tex
  bibtex main
  xelatex -interaction=nonstopmode -halt-on-error main.tex
  xelatex -interaction=nonstopmode -halt-on-error main.tex
需要 ctex、fontspec、amsmath、booktabs、tabularx、enumitem、placeins、tikz、hyperref。
字体：Noto Serif CJK SC、Noto Sans CJK SC、Noto Sans Mono CJK SC、TeX Gyre Termes/Heros、Latin Modern Mono。

图表重建：
  python -m pip install matplotlib
  python make_results.py
优先从相邻原仓库 results/ 读取冻结文件；独立分发时使用 data/ 内的冻结副本。
生成四幅矢量数据/实例图和五份数据表片段；证明链图为正文 TikZ。
data/provenance.json 给出输入来源与 SHA-256，measurements.csv 保留全部主批次行。
不会重跑基准或修改历史数据。误差线未绘制；图中点为三次中位数，64轮标为单次。

组织参考（已读取原文，表达与论证均重新撰写）：
FM 2024: Unifying Weak Memory Verification Using Potentials
https://doi.org/10.1007/978-3-031-71162-6_27
FM 2026: Complexity of Consistency Testing for the Release-Acquire Semantics
https://doi.org/10.1007/978-3-032-26220-2_12
FM 要求参考：理论工作说明实际问题意义，实验公开可复核，明确新颖性与正确性。
https://conf.researchr.org/track/fm-2026/fm-2026-research-paper

贡献定位：具体发布条件到全候选局部化的定理、身份敏感支持、完整日志诊断。
共同前序可接入已有分析框架；通用自动机、后缀商、one-hot分组、支持编码和C++执行不冒称首创。
保留：恒定载荷六轮失败、四轮SAT更快、版本值缩小来源域、环四轮失败、64轮单次、32轮只选定独立核对。
新CaDiCaL核对与旧稠密Minisat任务计时不计算速度比。

完整实验制品另见 solver/artifacts/fm_submission_20261016.zip；论文源包并不替代算法证据包。
