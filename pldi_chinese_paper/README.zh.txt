《协议诱导的因果前沿：Release–Acquire 观测的精确支持编译》
中文完整论文与复现说明，2026-10-28

材料基准：ChenKaichen-SCUT/Work，提交
2a70e4d46ef76e0cdd742d57017cb508cf7834f8。
本交付仅重写论文、复核论证并从冻结结果绘图，没有增加实验、修改算法或扩大理论范围。
旧稿、冻结理论文档、实现和实验原始数据保留在仓库原位置。

一、文件
main.tex 及 01–09_*.tex：九节正文。
appendix_proofs.tex：原子组、失败链、屏障尾部、组合、无写覆盖推论、完整示例见证。
appendix_backend.tex：DFA、关系更新、支持 CNF、位复杂度、原始 SAT 投影。
appendix_results.tex：补充成本及布局表和简短复现说明。
references.bib：原始文献。
output/pdf/causal_frontier_pldi_zh.pdf：最终 PDF。
figures/：四张实验图，均提供矢量 PDF 和 PNG。
generated/：五张结果表、正文数值宏、绘图数据及输入 SHA-256 清单。
data/frozen_inputs.json.gz：绘图实际读取的 52 份冻结 JSON 的无损 UTF-8 快照。
internal/：写作前主张索引、符号表、技术复核、阅读复核和未决事项；不编入论文。

二、直接编译
安装 TeX Live（含 XeLaTeX、BibTeX、ctex、Fandol 字体和 main.tex 所列常规包）。
不需要实验求解器或服务器。已有的 generated/ 和 figures/ 足够编译：
  python build_paper.py
或：
  xelatex -interaction=nonstopmode -halt-on-error main.tex
  bibtex main
  xelatex -interaction=nonstopmode -halt-on-error main.tex
  xelatex -interaction=nonstopmode -halt-on-error main.tex
后一方式生成 main.pdf；build_paper.py 另导出至 output/pdf/。
本地验证使用 TeX Live 2024 的 XeLaTeX 与 BibTeX，不使用 pdfLaTeX。

三、离线重绘
在 Python 环境安装 requirements-paper.txt，然后运行：
  python generate_results.py --snapshot
  python build_paper.py
也可 python build_paper.py --redraw。仅重绘，不启动任何求解器。
在完整研究仓库中，省略 --snapshot 可直接读取原 results/。
generated/data_manifest.json 给出每份输入的原路径与原始字节 SHA-256；
快照保存这些原始字节的 UTF-8 内容，恢复后须逐一匹配。
generated/plotted_data.json 保存所用聚合行与正文宏。图表不混用各批次最优值。
图1/2：最新 branch 缓冲历史扫描；容量表：同批 C=2/3/4/6。
图3：查询新颖度独立批次；图4：最新按需诊断批次。
机制表保留原机制批次与长写间隔匹配对照的区别。
成功点中位数及最小/最大范围按原进程重复计算。失败点没有补造完成时间。
诊断冷、温与总计独立统计，不将各分项中位数相加。

四、历史测量边界
最新环境为 Windows 11、Python 3.12.14、python-sat 1.8.dev30/CaDiCaL195，
单性能进程使用一个 CPU，原生端口更新关闭。冻结主批次没有另记 CPU 商品型号；
同机早期环境记录为 Intel64 Family 6 Model 140 Stepping 1, GenuineIntel。
不以本次绘图环境或日期覆盖原实验环境及代码摘要。
旧外部控制器的 RSS 字段采样到 venv 启动器，不能作为求解器内存。
论文使用成功工作进程的操作系统峰值，并保留六个超时点的进程树重测结果。
原始失败数据、控制器修正及具体预算见原 CAUSAL_EVIDENCE_REPRODUCE.zh.txt。
不能声称原批次已经可靠实施了整棵进程树 1 GiB 限制。
本文不把 494 个选定排除核查解释为 32 轮全部支持穷尽核查，亦不声称证明助手认证。

五、打包和检查
  python package_paper.py
默认生成仓库 artifacts/pldi_chinese_paper_20261028.zip。
ZIP 附 PACKAGE_MANIFEST.json，列出所有文件 SHA-256；没有缓存、虚拟环境或凭据。
inspect_pdf.py 为可选排版检查脚本，另需 pypdf、Pillow 及 PATH 上的 pdftotext。
Fandol 使用标准预定义中文字符映射；Poppler 可以正确抽取中文。
部分 Python PDF 库无法解析该映射，其抽取乱码不代表视觉 PDF 缺字。
最终检查结合完整页面渲染、Poppler 抽取和 TeX 引用/字体/溢出诊断。
