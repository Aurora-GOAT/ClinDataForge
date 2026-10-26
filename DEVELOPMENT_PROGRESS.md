# ClinDataForge真实开发日志

## 2026-10-27 最终验收：as-run 血缘 + 切分关系审计 + 独立检验常数路径 + 成果包

**背景**：四项要求全部针对「已发布数字是否站得住」，本轮不新增大模型训练、影像模块或其他大型功能。所有改动都是**追加式**的——历史冻结产物一个字节都没改，新增证据全部落到新目录。

**P0 疾病来源清单与实际数据不一致（已完成）**
- [x] 先查清再修：`data/phase3_synth/kb/disease_selection.json` 与 `clinforge/hpo_knowledge.py::CURATED_DISEASES` **只有 3/16 个 ID 重合**。不是文件损坏，是 `disease_selection.json` 为早期算法选择器（`select_rare_diseases(snapshot, 16, 20261026, 8)`）的 write-once 遗留产物，生成后 `CURATED_DISEASES` 被人工替换成更可讲故事的 16 病，旧文件因「禁止覆盖」纪律没有被同步。
- [x] 用原选择器函数 + 原参数**精确复现**旧文件 16 个 ID（`stale_reproduced=True`），证明它确实是真实运行产物而非手写，所以不改不删，登记为 `superseded_artifact`。
- [x] 新建 `scripts/build_disease_lineage.py`（`lineage-1.0.0`）以 `CURATED_DISEASES` 为唯一事实来源，从 2,400 条生成记录反查：`disease_in_curated 2400/2400`、`phenotype_hp_in_annotation 22156/22156`、`hpo_provenance_equals_snapshot 2400/2400`、实体偏移回切 `36713` 全部通过、`violations {}`（六类违规全零）。
- [x] 产出 `data/phase4_lineage/lineage_manifest.json`、`record_disease_index.csv`（2,400 行逐条指针）、`reports/phase4_lineage/lineage_report.md`；旧文件路径/状态/重合数/可复现性/差异原因全部写进 `superseded_artifact` 字段。
- [x] 教训写进文档：write-once 保护只保证「不被覆盖」，不保证「与实际运行一致」；血缘必须每轮从产物反查重建，不能靠文件名互相指认。

**P1 训练/留出集的模板、患者、疾病与近重复关系（已完成）**
- [x] 新建 `scripts/audit_split_relations.py`（`split-rel-1.0.0`），四语料（train/dev/test/holdout）六类关系全量比对：共享患者 0、共享就诊号 0、精确重复文本 0、跨组近重复 0；`cross_split` 骨架碰撞仅 `train|test` **1 对**（已定位）。
- [x] 发现两个**任务设计层面**的捷径，如实公开：① `(template_family, complexity, disease_id)` 三元组 **test 侧 99.02%（202/204）已在 train 出现**，train 侧同口径为 64.39%——两个分母不同，不能混引；② 疾病名出现在 **100%** 的 test 正文中（表型/检验脱敏后仍 85.37%），且金标含 `disease_suspected`。结论：test 集是「格式遵从/联调」基准，**不是泛化基准**。
- [x] 260 条上下文留出集也做同样的解剖：**1,618 个提及只对应 186 种归一化文本**、内部近重复 **706 对**、连通分量 **64 个**（最大 10、无单例）。它与其余三组的重叠指标全为 0，但**内部高度重复**。
- [x] 新建 `scripts/analyze_holdout_clusters.py` 做簇级 bootstrap（2,000 次，`seed=20261027`，重采样单位＝近重复连通分量而非提及）：v1 acc 0.7021 CI [0.6337, 0.7734] → v2_scope_ng 0.9778 CI [0.9451, 1.0000]，宏 F1 0.6840 → 0.9567 CI [0.9232, 1.0000]。**点估计方向不变，但「260 条独立样本」的说法被自己推翻**。
- [x] 全库改口径：`docs/CONTEXT_AND_PERF_CN.md` 1.3 节标题改为「另冻结**同生成器**留出集」并新增 1.4b 节；`docs/DATA_QUALITY_AUDIT_CN.md` 新增 3.3 节与 3.1 节三元组双分母说明；README 第四阶段条目同步。**不再出现「独立留出集」「跨真实医院泛化」表述。**
- [x] 外部独立评测：ASQ-PHI 只覆盖 PHI 跨度、不覆盖上下文状态，故「来源真正独立的上下文评测集」标 **BLOCKED**，不新建、不在旧测试集上重调参。

**P2 生成器与验证器共享医学检验常数（已完成）**
- [x] 承认问题真实存在：验证器 `scripts/validate_synth.py` 直接 import `REFERENCE_INTERVALS` / 换算因子，与生成器同源。历史上的 `g/dL→g/L` 方向错误正是被这种共享掩盖过。
- [x] 新建 `clinforge/lab_standards.py` 作为**第二条独立路径**（**不 import `hpo_knowledge`**，有单测强制）：因子从分子式 + CIAAW 标准原子量推导（葡萄糖 180.156 g/mol → 0.055507、肌酐 113.120 g/mol → 88.401697），SI 词头按 BIPM 定义（g/dL→g/L ×10），酶活性 U/L 不做质量换算。
- [x] `data/external/lab_standards_sources.json` 登记来源（CIAAW 原子量、BIPM SI 词头、IUPAC 酶单位）与三条 `not_claimed`；参考区间显式标注 `demo values for pipeline testing; not a clinical reference standard`。
- [x] `scripts/audit_lab_independence.py`（`lab-independence-1.0.0`）：两表相对差 / 1,277 个检验值独立复算 / **注入错误实验**。实测 `table_agrees=True`、`conversion_mismatch=0`、`direction_mismatch=0`、`max_absolute_delta=0.01`。
- [x] 注入实验（300 例，`seed=424242`，`try/finally` 恢复共享表）：把换算因子与区间**同时注错**后，共享表路径 159 值 / 0 换算错 / 0 方向错（按构造必然通过），独立路径 159 值 / **26 换算错 + 10 方向错**。循环验证被实测证实，第二路径被证实有效。
- [x] **金标零修改**：注入只改内存中的常数表，`finally` 恢复；重跑验证器用 `--lab-standards independent` 写到新目录 `reports/phase4_lab_independence/validation_independent`（`lab_errors=0`），历史结果不动。
- [x] `tests/test_lab_standards.py` 14 项：摩尔质量、换算、恒等单位、未知单位抛错、往返误差、方向校验、篡改检出、无共享表 import、注入后恢复。

**P3 正式成果包（已完成）**
- [x] `scripts/build_final_package.py`（`final-package-1.0.0`）从 13 个产物 JSON 生成 `reports/final/metrics_registry.json`（**57 项指标** + 16 个产物 SHA256）与 `reports/final/experiment_table.md`（9 组实验 + 五级效力分级 + 「不能写进简历的结论」）。
- [x] 五级效力分级落地为机器字段：`template_self_check` / `synthetic_holdout` / `third_party_frozen` / `engineering_measurement` / `audit_finding`。
- [x] `scripts/build_demo.py` 生成自包含 `demo/index.html`（60,704 字节，5 个样例 / 52 个提及，四个标签页；JS 经 Node 语法校验）。零依赖、离线可开。
- [x] `docs/FINAL_DELIVERY_CN.md`（网申索引 + JD 映射 + 15 项交付物 + 可写/不能写口径 + 8 项 BLOCKED）、`docs/PROJECT_ONE_PAGER_CN.md`（重写）、`docs/RESUME_BULLETS_CN.md`（三条重写）、`docs/REPRODUCE_CN.md`（环境 + 从零重建 + 6 条「不要做的事」）。
- [x] `docs/INTERVIEW_QA_CN.md` 扩到 **34 题**（新增 Q31 血缘不一致、Q32 64 簇是否推翻结论、Q33 如何证明循环验证真实存在、Q34 主动公开的六个不利发现）。
- [x] `docs/GIT_LOG_CN.md` 记录本地提交历史（未推送）。

**本轮未做**：模型训练；真实临床数据；外部独立上下文评测集（BLOCKED）；在留出集上修补裸「疑」（会污染留出集）。**项目到此停止扩张。**

**测试**：全套 **170 项通过**（Python 3.13.12 管理版；`reports/final/test_summary.json`）。

## 2026-10-26 第四阶段：上下文判定重写 + PHI 推理提速 + 数据质量审计

**P0 上下文判定（已完成）**
- [x] 先诊断后改码：`scripts/diagnose_context.py` 只读产物不改代码，把 783 例 `history→affirmed` 按语言/模板族/所在小节/窗口切片拆开——783 例**全部在中文**、754 例在「既往史」段、英文侧只有 19 例 `negated→affirmed`。五个假设逐个验证，定位出四个作用域根因：① 段头「既往史：」的冒号被当句界；② 接续分句只回溯一层；③ 中文实体名内含否定字（「前脑无裂畸形」的「无」）；④ 固定 24/48 字符窗口。
- [x] 复用 NegEx/ConText 而非再写启发式：`clinforge/context_scope.py`（`ctxscope-1.1.0`）实现 pseudo-negation 掩码、硬终止符（冒号后换行不算边界）、termination terms、nearest-trigger 优先、段头延续、`MASK_CHAR` 保长度掩码。
- [x] 词表消融把「机制」与「词表」拆开：`CUE_SETS['v1']` / `CUE_SETS['negex']` 两套线索词，同机制下只换词表。
- [x] 开发集（已污染）783 → 0，准确率 0.9617 → 1.0000。
- [x] **另冻结同生成器留出集**（`clinforge/holdout_context.py` + `scripts/build_context_holdout.py`，8 个中文模板 / 6 个英文模板，与开发语料不同模板但**同一生成器**）：260 条 / 1,618 实体，SHA256 `75a733fb…`，落盘于评测之前，span_errors 0。**2026-10-27 复核**：1,618 个提及只对应 186 种归一化文本、内部近重复 706 对、近重复连通分量 64 个 —— 不是 260 个独立样本。
- [x] 留出集结果：v1 `history→affirmed` **221 → 0**，准确率 0.7021 → **0.9778**，宏 F1 0.6840 → **0.9567**；四类 F1 全部上升（affirmed 0.6972→0.9697、suspected 0.6667→0.8571、history 0.5822→1.0000、negated 0.7898→1.0000），未牺牲任何类别。**簇级 bootstrap（2026-10-27 补算，2,000 次，重采样单位＝连通分量）**：v1 acc CI [0.6337, 0.7734]、v2 acc CI [0.9451, 1.0000]、v2 宏 F1 CI [0.9232, 1.0000]，区间不重叠，方向结论成立但区间比原按提及计算的更宽。
- [x] 评测纪律：首次留出评测暴露**自己的缺陷**——`ctxscope-1.0.0` 英文硬终止符漏了 ASCII 句号，history 触发词跨句泄漏导致 **57 例 `affirmed→history`**（注意方向：把现症误判成既往）。修复为 `ctxscope-1.1.0`，旧结果另存 `holdout_eval_ctxscope100.json` **不覆盖**。
  - 易混淆点先说明：`v2 作用域 + v1 线索词表` 那一行也恰好是 57 例，但方向相反（`history→affirmed`，原因是缺线索词而非跨句泄漏）。两个 57 是不同的错误，别合并。
- [x] 一处被回滚的改动：曾把「出生后」加作既往史线索，导致 170 例 `affirmed→history`（「出生后即起被发现存在 X」是现症起病描述，不是既往史），从词表移除并在注释与文档中记录「起病时间标记 ≠ 既往史」。
- [x] 残留 36 例裸「疑」判错（如「疑有 X」缺「另/尚」前缀），**故意不在留出集上修补**，写进 `test_bare_yi_is_still_unhandled` 把缺口固定成已知项。
- [x] 27 项新单测（`tests/test_context_scope.py`）覆盖段头冒号、长枚举、换行续行、裸换行仍终止、pseudo-negation、英文句号回归、优先级、词表消融。

**P1 PHI 推理提速（已完成）**
- [x] 五个假设逐一排查（重复加载 / tokenizer 批量化 / ORT 线程与 EP / 无必要重复计算 / 批处理）：只有线程配置有效，其余四条证伪，表格在 `docs/CONTEXT_AND_PERF_CN.md` 第 2.1 节。
- [x] ORT profiler 定位真因：fp16 权重在无 AVX512-FP16 的 CPU 上靠 **Cast 模拟**（24.5% 算子时间）+ 慢 MatMul（49.4%）。
- [x] 换官方 fp32 权重（`onnx_fp32/model.onnx`，SHA256 `7704865e…`，与 HF LFS oid 逐位核对）+ 4 线程：**2,778 → 995 ms/条（2.79×）**，p95 4,787 → 1,748 ms，吞吐 0.36 → 1.00 条/秒，峰值 RSS 1,349 → 2,129 MB。
- [x] 端到端九段流水线复跑 2,400 条：**79.1 → 42.0 分钟（1.89×）**；抽取+上下文 5.6 → 8.2 ms/条（作用域判定更贵，相对门控可忽略）。
- [x] 输出一致性分两层，且第二层**推翻了第一层的乐观结论**：60 条探针集上五配置跨度集合完全一致（1.0000、0 缺失 0 新增）；632 条冻结测试集（先校验数据 SHA256）上实测 C 一致率 0.9968（新增 2）、D 一致率 0.9984（新增 1），**缺失跨度均为 0**。逐条查证：ZH-0140 的手机号 `PHONE[88,99)` 是正确找回（C 的 TP +1、recall 0.8363→0.8368），EN-0554 的 `"50-year-old male"→NAME` 是新增误报；**D 的 recall / TP / FN 完全不变（0.9042 / 1756 / 186）**，precision 0.7566→0.7562。
- [x] 看到这 3 个差异后**没有回头调阈值 0.2**（在测试集上调参等于污染测试集），差异与"未调参"的决定写进 `configs/phase4_phi_fast.json` 的 `frozen_test_regression.reading`。
- [x] 回归脚本 `scripts/evaluate_phi_optimized.py` 自身也修了两个 bug：把 `{'doc_id','spans'}` 包装字典误传给 `record_counts`（迭代字典得到 key，报出误导性的 `AttributeError: str`）；以及对 `(label, start, end)` 做 `sorted()` 导致 int 与 str 比较报错。顺带给 `normalize_spans` 加了类型守卫并补 1 项单测，让这类误用在报错时就点明"payload 是 str"。
- [x] 批处理是**负结果**并已文档化：padding 到批内最长 chunk 后 b8 更慢（1,785 ms/条），按长度排序仍不如逐条（1,248 ms/条），最终 `batch_size=1`，`why_not_batching` 写进 `configs/phase4_phi_fast.json`。
- [x] 默认值踩过的坑：初版把 `dtype` 默认改 `fp32`、`batch_size` 默认 8，会让 `phi_worker` 复现试验时**悄然改变配置**；改回默认 `fp16` / `batch_size=1`，快速配置显式 opt-in。
- [x] 新增 `scripts/bench_phi.py`（线程扫描 + 批处理可行性探针）、`scripts/bench_phi_configs.py`（每配置独立进程测峰值 RSS）、`scripts/evaluate_phi_optimized.py`（冻结集回归），7 项批处理单测。

**P2 数据质量审计（已完成，见 `docs/DATA_QUALITY_AUDIT_CN.md`）**
- [x] 六块独立重算（`scripts/audit_data_quality.py`，`dq-audit-1.0.0`）：溯源 / 循环验证 / 分割泄漏 / 翻译状态 / 偏好标签 / 上下文污染。全部从磁盘产物重算，不读自检报告。
- [x] 溯源：2,400/2,400 携带完整溯源；本体与注释文件 SHA256 与磁盘一致；跨度错误 0；缺 HP 编码或证据码 0；证据码 TAS 19,351 / PCS 2,739 / IEA 66。
- [x] 循环验证：验证器 import 了 `REFERENCE_INTERVALS` 等三个项目常量 → 常数级共享**确实存在**，已写成机器可读字段公开；换算常数用独立字面量复算一致；历史上 `g/dL→g/L` 方向错误正是被这种共享掩盖过。
- [x] 分割：零重复文本、零共享患者、零近重复对；跨组骨架碰撞仅 **1 对**（`train`→`test`）；但 `(模板族, 复杂度, 疾病)` 三元组 **test 侧 99.02% 已在 train 出现**（train 侧同口径 64.39%，分母不同不可混引），疾病名出现在 **100%** 的 test 正文中（脱敏后 85.37%），16 种疾病三对划分全部重叠 → **不是泛化基准**，只能做联调/格式遵从集。（2026-10-27 用 `split-rel-1.0.0` 复核，结论不变，补上双分母与疾病名泄漏口径。）
- [x] 翻译：214 表型 + 16 疾病，无双表面冲突，10 对子串、0 条含未译拉丁字母；审核状态为**单人机助 + 抽查，无临床或职业译者审核**，允许/禁止表述写进 JSON。
- [x] 偏好标签：修掉 `hallucinate_phenotype` 硬编码 Fever（22/2,332 的「错答」其实正确、113 例重复追加），改为从「HPO 全术语 − 该病注释集 − 当前输出」采样；**审计检查本身也重写**（原来的常数检查在规则改动后报出 29 这种无意义数字），用修复前导出复算精确复现 22 例，证明检查不是变宽松而是变正确。修复后 0/2,355。
- [x] 上下文污染闸门：修复前 **823 / 21,353（3.85%）** → 修复后 **0 / 21,640（0.00%）**。
- [x] 流水线复跑连带效应：接受 2,332 → **2,355**，隔离 68 → **45**，其中 23 条原为 `KNOWLEDGE_INCONSISTENT_PHENOTYPE`（上下文错判导致的假不一致），剩余 45 条是生成器自身检验值冲突（血糖 29 + ALT 16），继续隔离。
- [x] 发现文档指向错误：`DEVELOPMENT_PROGRESS.md` 第三阶段条目让读者去看 `disease_selection.json`（自动排序的候选池，16 种里只有 3 种与 `CURATED_DISEASES` 重合），已在审计文档标注，历史产物不改写。**2026-10-27 已建 as-run 血缘清单**（`lineage-1.0.0`）替代该指向，旧文件登记为 `superseded_artifact`。

**P3 交付物（已完成）**
- [x] `docs/CONTEXT_AND_PERF_CN.md`（诊断五假设逐条验证、四根因、NegEx/ConText 方法、留出集独立性边界、端到端实测与三点说明、批处理负结论、复现步骤）。
- [x] `docs/DATA_QUALITY_AUDIT_CN.md`（审计方法、效力声明、六块结论、训练候选可用性裁定、未解决问题）。
- [x] `docs/RARE_DISEASE_SAMPLES_CN.md`（自动生成：16 病溯源表 + 中文四态案例 + 英文案例 + PHI 脱敏对照含 1 例误报标注 + 3 个修复前后个案 + 效力边界）。
- [x] `assets/pipeline_architecture.svg`（1,240×820 九段流水线架构图，标注本轮重写的 ③ 与提速的 ⑤，含安全约束、四层证据链、产物清单、免责声明）。
- [x] 重写 `docs/PROJECT_ONE_PAGER_CN.md`（四个核心成果 + 审计结论 + 边界）、`docs/RESUME_BULLETS_CN.md`（三条）、`docs/INTERVIEW_QA_CN.md`（扩到 **30 题**）。
- [x] `reports/phase4_dashboard.html` + `reports/phase4_context/report_tables.md`（从 JSON 直接渲染，不手填数字）。

**本阶段未做**：任何模型训练（SFT/LoRA/DPO 全部未跑）；真实临床数据验证（无授权）；门控批次压到 1 的复跑（收益约 4.6%，需再花 40 分钟）；裸「疑」的修补（会污染留出集，留作已知缺口）。

**测试**：全套 **156 项通过**（3.13.12 管理版 Python，「核心包纯标准库」路径）。

## 2026-10-26 第三阶段 P0/P1：知识约束罕见病合成 + 结构化质量流水线（进行中）

**P0 知识约束合成（已完成并提交）**
- [x] HPO 资源核验：`hp.obo`（release 2026-09-01）与 `phenotype.hpoa`（2026-09-02），许可条款逐条核实（可用、须署名、禁改动再分发），SHA256 记录于 `data/external/hpo/`；快照 20,482 术语 / 12,867 疾病。
- [x] 人工核验 16 种罕见病演示集（ORPHA/OMIM 各半，覆盖神经/代谢/血液/内分泌/肝肾/染色体），事实来源为 `clinforge/hpo_knowledge.py::CURATED_DISEASES`。~~见 `data/phase3_synth/kb/disease_selection.json`~~ ← 该指向有误（旧算法选择器遗留文件，16 种里只有 3 种与实际运行重合），已由 `lineage-1.0.0` 的 `data/phase4_lineage/lineage_manifest.json` 取代，见 `docs/DATA_QUALITY_AUDIT_CN.md`。
- [x] 中文术语表 `data/curated/zh_phenotype_gloss.json`：214 表型 + 16 疾病，人工翻译。
- [x] 生成器 `clinforge/synthgen.py`（synthgen-1.0.0，seed 20261026）：2,400 病例（zh 70% / en 30%，3 模板族 × 3 复杂度）；表型按 HPOA 频率采样；状态四类；检验值仅 4 个有文献依据的检验关联表型；Turner/Lowe 性别约束；无编造药物剂量/诊断标准。
- [x] 独立验证器 `scripts/validate_synth.py`（不读生成器内部状态）：知识约束违反 **0/2,400**、检验错误 0、跨度错误 0；214 个不同 HP 表型；同疾病近重复对 0.18%；复核队列 199 条。
- [x] 测试先行抓出两处真实缺陷并修复：g/dL→g/L 换算方向错误（生成器与验证器同错互掩，验证器改独立换算路径）；英文否定列举逗号断句错误（中英文断句规则分离 + 接续分句回溯）。
- [x] 单元测试 13 项（hpo/synth）+ 5 项（benchmarks），全套 121 通过。

**P1 结构化流水线（已完成）**
- [x] `clinforge/pipeline_med.py` 九段流水线 + `clinforge/med_extract.py`（HPO 词典抽取、上下文判定、检验标准化 v2）。
- [x] 完整运行（GLiNER 门控，82.6 分钟）：2,400 输入 → 2,332 接受 / 68 隔离；`data/phase3_synth/pipeline_out/`。
- [x] 模板内自检（`reports/phase3_pipeline_eval/`，口径已明确标注，不等于独立测试）：表型抽取 P 0.9822 / R 1.0 / F1 0.991（zh F1 0.993 / en F1 0.987）；上下文状态判定准确率 0.9617（主要残余混淆 history→affirmed 783 例）；疾病名提及 F1 1.0；检验标准化 1,277/1,277 全部正确；合成 PHI 掩码率 100%；去重评测对（160 对，含同患者不同就诊难负例）P/R/F1 全 1.0。
- [x] 阶段性能：抽取+上下文均值 5.6ms/条，检验 0.18ms/条，PHI 门控（GLiNER）均值 1.97s/条（瓶颈，占 99% 耗时）。
- [x] 两处由评测驱动的修复：疾病名提及单次命中 bug；表型提及与疾病名跨度重叠抑制。另发现评测忠实度问题并修复——去重评测最初用原始文本（FN=4），但生产流水线在脱敏文本上去重，改用统一规则掩码口径后 P/R/F1=1.0，协议写入评测 JSON。
- [x] SFT/偏好候选导出（`scripts/export_training_candidates.py`）：2,332 条接受样本 → SFT 1,904/227/201（train/dev/test），偏好对含 4 类程序化腐化规则（flip_status 591 / drop_phenotype 561 / wrong_lab 271 / hallucinate_phenotype 909）；明确标注未执行任何训练、腐化样本非人类偏好标签。
- [x] MedMCQA 离线接口（`clinforge/benchmarks.py`）：本地 JSONL 加载 + Wilson 区间打分 + 文件 SHA256 泄漏审计；在线模型评测硬阻断（无 API 授权，标 BLOCKED）。
- [x] HTML 演示 `reports/phase3_synth_dashboard.html`；测试全套 **121 通过**。

**本阶段未做**：SFT/DPO 实际训练（无授权、无 GPU）；MedMCQA 实跑（接口就绪，模型评测 BLOCKED）；P3 多模态（明确列为未来扩展）；真实患者入口继续关闭。

## 2026-10-25 第一/二阶段：独立评测集 + PHI 四路方法对照（v0.2.0）

**核心结论**：在来源独立、零泄漏的冻结测试集（632 条 / 1,942 个金标实体）上，
融合方法 D（规则∪GLiNER）相对原规则 A 的实体召回 **+0.8239（95% 区间 [+0.8058, +0.8422]）**，
F1 由 0.1457 提升到 **0.8238**；相对单模型 C 召回 +0.0680 [+0.0541, +0.0822]。
原规则在该独立数据上召回仅 **0.0803**，远低于旧 60 条压力集的 0.5556，说明旧指标既高估模板内表现、也低估泛化失败。

- [x] **数据集**：ASQ-PHI v1（MIT，1,051 条英文合成查询，第三方来源）+ 本仓库独立中文模板集（320 条）。构建 `scripts/build_phi_benchmark.py`（seed=20261025），划分 unit 为近重复连通分量（骨架相同 / 5-gram Jaccard≥0.50 / 另一掩码 6-gram Jaccard≥0.50 / 同中文模板族），前缀过滤精确 Jaccard 连接。
- [x] **独立审计** `scripts/audit_phi_dataset.py` 用另一套掩码复核，修正三处真实泄漏后 **PASS**（跨划分相同文本 0、掩码碰撞 0、模板族 0、Jaccard≥0.50 对 0）。划分：train 343 / dev 396 / test 632，中英文均覆盖三集合。详见 `docs/PHASE2_DATASET_AUDIT_CN.md`、`docs/PHI_DATA_CARD_CN.md`。
- [x] **四路方法**：A 原规则、B Presidio 2.2.364 + spaCy `en_core_web_lg` 3.8.0、C GLiNER `urchade/gliner_multi_pii-v1`（ONNX **fp16**）、D 规则∪GLiNER。全部本地 CPU 推理，无付费 API / GPU / 数据外发。
- [x] **重要负面结果**：int8 动态量化权重 `model_quantized.onnx` 表征坍缩（探针最大跨度概率 0.202，prompt 与词表征不可区分），改用 fp16（SHA256 校验）。spaCy 3.8.x 配 preshed≥3.0.10/cymem≥2.0.9 在本机加载任何 pipeline 均抛 OverflowError，已锁定 preshed 3.0.9 / cymem 2.0.8。
- [x] **dev 阈值选择**（未接触 test）：B s=0.10、C t=0.20、D t=0.20 且**否决并入 Presidio**（F1 0.841→0.688）。协议 v2 的"召回优先"规则在 dev 前沿上选中退化点，已在**读 test 之前**修订为 v2.1 的 F1 最大化，并在协议中记录修订原因。
- [x] **冻结测试集一次性评测**：`reports/phase2_phi_v1/test_run/`，含逐条充分统计、751 条错误案例、性能与配对 cluster bootstrap（2,000 次）。
- [x] 单元测试 **103/103 通过**；新增 `tests/test_phi_phase2.py`（含两处真实缺陷的回归测试）。
- [x] 报告：`docs/PHI_METHOD_COMPARISON_CN.md`、`reports/phase2_phi_v1/report_tables.md`、`phi_comparison.html`。

**未做/未通过**：无人工医学标注；96.55% 无 PHI 硬负样本仍被改动（可用性代价，与 ASQ-PHI 公布的 Comprehend Medical 基线 86.8–90.0% 同量级）；Presidio 不适配中文（zh 召回 0.057）与病历号/医保号；真实患者入口与正文出口**继续关闭**。

## 2026-10-25 用户收窄任务：Presidio最小基线验证

- 停止此前未完成的数据集/模型工作，仅提交本次Presidio相关文件；此前工作保留未提交，不视为已验收成果。
- 当前Python3.10及已有隔离环境均无Presidio、spaCy或英文小模型；本次未安装依赖或下载模型。
- 新增可选本地适配器、原60条压力集复现实验脚本、许可说明与相关单元测试；原始规则及历史结果未改。
- 原规则TP100/FP0/FN80，P=1.0000、R=0.5556、F1=0.7143；本次识别调用合计0.002666秒。Presidio未运行，指标为null，绝不以测试替身冒充模型结果。
- 仅运行9项相关测试，9/9通过（0.011秒）。原始证据 `reports/presidio_probe_20261025/`；结论详见 `docs/PRESIDIO_BASELINE_CN.md`。未接入正文出口，本轮到此停止。

## 2026-10-25 初版 v0.1

- [x] 与蚂蚁医疗大模型数据科学家JD对齐：医疗文本结构化、标准化、去重、隐私模式识别、质控和训练候选导出。
- [x] 从零建立独立Python标准库仓库，非MedDataLab代码更名。
- [x] 600条基础合成病历 + 130条重复/近重复，程序自动产生跨度/字段/聚簇标签；固定seed=20261025。
- [x] 已实现带单位换算的4类检测字段、三类PHI识别、就诊内重复隔离、HMAC伪名化、质量分数、SQLite审计。
- [x] 完成730条的模板基准：PHI跨度F1=1.0、化验字段F1=0.9979、去重F1=1.0。**均为程序模板内分数。**
- [x] 完成独立模板压力集60条：PHI召回率0.5556、F1=0.7143。**红队结果证明系统尚不能用于真实患者文本。**
- [x] 前轮公开MIMIC-IV-ED Demo衍生数据只做222条记录聚合质量审计，无患者级数据重新分发。
- [x] 自动生成HTML仪表盘、40条空白人工审核队列、未审阅SFT候选数据，以及Python自动化回归测试。
- [x] 安全默认：不允许非合成输入走原始文本管线；禁止覆盖已有输出。

## 尚未完成

- [ ] 医学NER/脱敏外部金标独立评测与高召回、fail-closed实现。
- [ ] 检验/药物编码知识库、处方/医疗影像/基因组数据处理。
- [ ] 真实人工审核、产出高质量SFT训练集、GPU微调及下游模型增益。
- [ ] 分布式/高吞吐架构生产化，以及合规认证。

## 2026-10-25 第一阶段：独立审计与修复（v0.1.1）

**完成本阶段；未通过P0独立PHI验收。** 初版条目为历史记录，不应覆盖或沿用为当前已核实事实。详见 `docs/PHASE1_AUDIT_CN.md`。

- [x] 解压ClinDataForge独立项目；建立独立本地Git仓库，原始交付快照 `af8a8f7` / 标签 `delivery-v0.1`，不混入父目录其他项目暂存更改。
- [x] 阅读全部约定/源码/历史实验；首次重跑28/28通过。保存原始文件、ZIP指纹和独立基线，历史报告、示例数据均逐字节保留。
- [x] 复现730条旧集的全部五组指标和60条压力集计数；独立算术核算一致。压力集完整覆盖已标注实体的记录仅10/60，不能当作安全或第三方验收。
- [x] 找到并修复温度异常注入误改ALT的生成器缺陷：六条正文与金标不一致。修正集另存，检验TP2886/FP0/FN0/F1=1.0；这是输入一致性修复，非抽取算法增益。
- [x] 历史MIMIC 222/64/545无法由现存源复现。六个相同副本独立重算为85条记录/40个subject/21条诊断，13条有诊断；保存来源哈希及差异，不再将旧数字当作当前成果。
- [x] 默认流水线只导出允许列表元数据：无正文、主诉、个体检验值、任意来源字段或源文件名；SFT文本导出0条并记录扣留原因。真实数据禁入门继续保留。
- [x] 修复短HMAC密钥吞错、非对象/空ID、重复ID和写出失败的半套结果；新增文件/SQL故障注入和全产物隐私canary验证。
- [x] 修复检验别名子串误匹配；去重增加已提取临床字段冲突保护。评测验证实际患者split、cluster范围及标注契约，增加重复链接指标。
- [x] 修复聚合类别字符串泄漏、缺失字段/ID分母、NaN/未知单位；脚本拒绝覆盖、仪表盘显式读入、审核CSV仅元数据。
- [x] 最终全量 **70/70** 通过（2.386秒）；730条×5次本机中位0.375678秒、约1943.15条/秒，环境及原始计时均已保存。新旧计时条件不同，不主张吞吐提升。
- [x] 完成CLI/benchmark/HTML/审核CSV实跑，更新README、岗位映射、阶段状态与面试边界。实验目录：`reports/phase1_20261025/`，最新聚合为 `public_audit_v2/`。

**下一步（未完成）：** 冻结独立来源PHI数据与标注/划分协议，比较规则、本地模型及混合方法，测量跨模板效果、误杀/漏检、残留与拒绝代价。未训练模型、调用付费API、租用GPU、上传隐私数据或公开发布；不得宣称能安全处理真实患者病历。
