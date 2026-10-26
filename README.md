# ClinDataForge｜医疗大模型数据质量处理平台

面向蚂蚁集团2027届「医疗大模型数据科学家—平台技术」岗位的个人求职项目，使用 AI 编程工具辅助开发。核心是可复现的数据算子、评测和错误分析。项目与蚂蚁集团无关联，没有训练或微调大模型。

**当前为最终验收版（`final-package-1.0.0`）。第二阶段独立 PHI 验收已通过（冻结测试集一次性评测）；第四阶段完成上下文判定重写、PHI 提速与数据质量审计；最终验收补齐疾病血缘、切分关系与检验常数独立核验。真实患者病历入口与正文出口继续关闭，`--synthetic` 只是调用方的来源声明。未执行任何模型训练。**

## 最终验收（2026-10-27）：可网申版本

- **疾病血缘**：新增 `lineage-1.0.0`，2,400/2,400 条记录、22,156/22,156 个表型实体可回溯到实际使用疾病的 HPO 注释集；历史 `disease_selection.json` 与实际只有 **3/16** 重合，已用同参数精确复现并解释，历史文件不覆盖。
- **切分关系**：共享患者/精确文本/近重复跨组均为 0；但 test 记录 **99.02%** 的三元组已在 train 出现、疾病名出现在 100% 的正文中；留出集 260 条实际只有 186 种文本、**64 个近重复簇**，已补 cluster bootstrap（v2 准确率 CI [0.9451, 1.0000]）。
- **检验常数**：新增 `clinforge/lab_standards.py` 独立换算路径（分子式 + CIAAW 原子量），1,277/1,277 个检验值复算一致；注入错误实验下共享表 0 检出、独立路径检出 **26 个换算错 + 10 个方向错**。
- **成果包**：`docs/FINAL_DELIVERY_CN.md`（索引）、`reports/final/experiment_table.md`（57 项指标）、`reports/final/metrics_registry.json`（指标→产物字段）、`demo/index.html`（可运行演示）、`docs/REPRODUCE_CN.md`；**170 项测试**通过。

## 第四阶段（2026-10-26）：上下文判定机制重写 + PHI 推理提速 + 数据质量审计

- **上下文判定（P0）**：诊断出 783 例 `history → affirmed` 的四个作用域根因（段头冒号被当句界、接续只回溯一层、实体名内含否定字、固定字符窗口），基于 NegEx/ConText 重写为 `clinforge/context_scope.py`（`ctxscope-1.1.0`：pseudo-negation 掩码、硬终止符、termination terms、nearest-trigger 优先、段头延续）。
  - 开发集 783 → 0（准确率 0.9617 → 1.0000）。
  - **同生成器留出集在评测前冻结**（260 条 / 1,618 实体，SHA256 `75a733fb…`）：`history→affirmed` **221 → 0**，准确率 0.7021 → **0.9778**，宏 F1 0.6840 → **0.9567**，四类 F1 全部上升。该留出集实际只有 186 种文本、64 个近重复簇，簇自助 95% CI 见 `reports/phase4_split_relations/holdout_bootstrap.json`；只能称"同生成器留出合成语料"，不是独立临床验证。
  - 词表消融拆开「机制」与「词表」：仅换作用域 0.8869，再加文献词表 0.9778。残留 36 例裸「疑」判错，**故意不在留出集上修补**。
  - 首次留出评测暴露了自己的一处缺陷（英文硬终止符漏了 ASCII 句号，导致 57 例 `affirmed→history`），旧结果另存 `holdout_eval_ctxscope100.json` 不覆盖。
- **PHI 推理提速（P1）**：ORT profiler 定位到 fp16 在无 AVX512-FP16 的 CPU 上靠 Cast 模拟（24.5% 算子时间）+ 慢 MatMul（49.4%）。换官方 fp32 权重 + 4 线程：**2,778 → 995 ms/条（2.79×）**，p95 4,787 → 1,748 ms，吞吐 0.36 → 1.00 条/秒；端到端九段流水线 **79.1 → 42.0 分钟（1.89×）**；代价峰值内存 1,349 → 2,129 MB。
  - 输出一致性分两层：60 条探针集上五配置跨度完全一致；**632 条冻结测试集上实测 3 个跨度变化**（C 一致率 0.9968、D 0.9984），全部是**新增、缺失为 0**——1 个正确找回的手机号 + 2 个新增误报，**D 的召回与漏检数未变**（0.9042 / 186），precision 0.7566 → 0.7562。看到差异后**未回改阈值**，差异与理由写入配置 `frozen_test_regression`。
  - 批处理是**负结果**：padding 到批内最长 chunk 后 8 批更慢（1,785 ms/条），按长度排序仍不如逐条（1,248 ms/条），最终 `batch_size=1`，负结论写进 `configs/phase4_phi_fast.json` 的 `why_not_batching`。
- **数据质量审计（P2）**：六块独立重算（溯源 / 循环验证 / 分割泄漏 / 翻译状态 / 偏好标签 / 上下文污染）。修复后导出候选的状态标签不一致 **823/21,353（3.85%）→ 0/21,640（0.00%）**，偏好对标签噪声 **22/2,332 → 0/2,355**（另修掉 113 例重复追加）。隔离数 68 → 45，其中 **23 条是上下文错判导致的假隔离**，修复后自动恢复。
  - 明确**不可**支撑的结论：泛化（test 记录 99.02% 的三元组已在 train 出现；换方向 train 侧为 64.39%；疾病 16/16 重叠）、中文鲁棒性（214 条术语表自证）、偏好质量（程序化腐化非人类标注）、医学正确性（存在常数级循环验证）、临床可用性。
  - 全文：[数据质量审计](docs/DATA_QUALITY_AUDIT_CN.md)；机器可读：`reports/phase4_data_quality/audit.json`。
- **交付物（P3）**：[上下文与性能技术报告](docs/CONTEXT_AND_PERF_CN.md)、[罕见病样本与溯源](docs/RARE_DISEASE_SAMPLES_CN.md)、[一页纸](docs/PROJECT_ONE_PAGER_CN.md)、[简历三条](docs/RESUME_BULLETS_CN.md)、[面试问答 34 题](docs/INTERVIEW_QA_CN.md)、[九段流水线架构图](assets/pipeline_architecture.svg)、[交互报告](reports/phase4_dashboard.html)、自动生成的[结果对照表](reports/phase4_context/report_tables.md)。
- **复现**：
  ```powershell
  .venv-phi/Scripts/python -m scripts.run_med_pipeline --out data/phase4_synth_v2/pipeline_out      # 约 42 分钟
  .venv-phi/Scripts/python -m scripts.evaluate_pipeline_synth --pipeline data/phase4_synth_v2/pipeline_out --out reports/phase4_pipeline_eval
  .venv-phi/Scripts/python -m scripts.export_training_candidates --pipeline data/phase4_synth_v2/pipeline_out --out data/phase4_synth_v2/training_candidates
  .venv-phi/Scripts/python -m scripts.audit_data_quality --export data/phase4_synth_v2/training_candidates --pipeline data/phase4_synth_v2/pipeline_out --out reports/phase4_data_quality/audit.json
  python -m scripts.render_phase4_report
  python -m scripts.showcase_samples
  ```

## 第三阶段（2026-10-26）：知识约束罕见病合成 + 医疗结构化流水线

- **知识资源**：HPO 本体（release 2026-09-01）与疾病-表型注释 `phenotype.hpoa`（2026-09-02），许可条款逐条核实（可用、须署名与版本、不得改动本体再分发），SHA256 与来源清单在 `data/external/hpo/`。快照 20,482 术语 / 12,867 疾病；人工核验 16 种罕见病演示集（ORPHA/OMIM 各半）。
- **合成生成器**（`clinforge/synthgen.py`，固定种子）：2,400 条中英双语病历（5 模板族 × 3 复杂度），表型按 HPOA 注释频率采样，状态含确认/疑似/既往/否认；检验值仅对 4 个有文献依据的检验关联表型生成，方向与参考区间一致；每个实体携带 HP 编码、证据代码、PMID/ORPHA 引用、规则版本与种子。
- **独立验证**（`scripts/validate_synth.py`，不读生成器内部状态）：知识约束违反 0/2,400、检验一致性错误 0、跨度完整性错误 0；同疾病内骨架近重复对（Jaccard≥0.7）占 0.18%；人工复核队列 199 条（PENDING_HUMAN）。完整指标：`reports/phase3_synth_validation/`。
- **结构化流水线**（`clinforge/pipeline_med.py`）：Schema 校验 → HPO 词典表型抽取（双语同义词、最长匹配、英文词边界）→ 上下文判定（分句窗口 + 接续分句回溯，中英文断句规则不同）→ 检验标准化 v2（ALT/AST/血糖/血红蛋白）→ PHI 安全门控（复用第二阶段 D 方法）→ 近重复检测（含"同患者不同就诊"难负例保护）→ 知识一致性检查 → 质量评分与隔离 → SQLite 血缘审计。实测 2,400 输入 → 2,332 接受 / 68 隔离。模板内自检指标（`reports/phase3_pipeline_eval/`，**与独立测试分开报告**）：表型抽取 F1 0.991、上下文状态判定 96.17%、检验标准化 1,277/1,277、去重评测对 P/R/F1 全 1.0、合成 PHI 掩码率 100%。
- **训练候选导出**：`scripts/export_training_candidates.py` 产出 SFT（第三阶段为 1,904/227/201；第四阶段重跑后为 1,921/230/204）与偏好对（4 类程序化腐化规则）；未执行任何训练，腐化样本非人类偏好标签。MedMCQA 离线评测接口就绪（`clinforge/benchmarks.py`），在线模型评测无授权保持 BLOCKED。
- **复现**：
  ```powershell
  python -m scripts.build_hpo_kb          # 需先按 data/external/hpo/SOURCE_MANIFEST.json 放置原始文件
  python -m scripts.generate_synth --out data/phase3_synth/gen
  python -m scripts.validate_synth --gen data/phase3_synth/gen --out reports/my_synth_validation
  .venv-phi/Scripts/python -m scripts.run_med_pipeline --phi-gate hybrid --out data/phase3_synth/pipeline_out
  .venv-phi/Scripts/python -m scripts.evaluate_pipeline_synth --out reports/my_pipeline_eval
  ```

## 第二阶段（2026-10-26）：独立 PHI 评测基准 + 四路方法对照

- 评测集：ASQ-PHI v1（MIT，1,051 条第三方合成英文）+ 自建中文 320 条；近重复连通分量划分，独立审计（`scripts/audit_phi_dataset.py`）确认跨划分零泄漏；train/dev/test = 343/396/632。
- 冻结测试集（632 条 / 1,942 实体）一次性评测：A 原规则 F1 0.1457｜B Presidio F1 0.3446｜C GLiNER fp16 F1 0.7920｜**D 规则∪GLiNER 召回 0.9042、F1 0.8238**；配对 cluster bootstrap（2000 次）区间均不跨 0。
- 已知代价：仍漏 186 个金标实体（字符残留 5.36%）；96.55% 无 PHI 硬负样本被改动。不构成生产级脱敏安全。
- 工程记录：GLiNER int8 量化权重表征坍缩（判别力探针发现，改用 fp16）；spaCy 3.8.x 需锁定 preshed==3.0.9 / cymem==2.0.8 / murmurhash==1.0.10。
- 文档：[对照报告](docs/PHI_METHOD_COMPARISON_CN.md)、[数据卡](docs/PHI_DATA_CARD_CN.md)、[协议 v2.1](docs/PHI_EVALUATION_PROTOCOL_CN.md)、[审计](docs/PHASE2_DATASET_AUDIT_CN.md)、[交互报告](reports/phase2_phi_v1/phi_comparison.html)。

## 第一阶段复核结论（2026-10-25）

- 初版 **28/28** 测试通过，历史730条模板基准的五组指标及60条压力集结果均能复现。测试全绿没有覆盖隐私泄漏、错误金标和患者划分绕过等问题。
- 旧检验 F1=0.9979 的6处不一致来自生成器缺陷：异常温度 `T=` 替换误改了 `ALT=`，正文与金标不一致。修复后另建数据集；分数变化属于输入/标签一致性修复，不能称为抽取算法增益。
- PHI 规则未调参。旧压力集仍为 **TP100 / FP0 / FN80，Recall 0.5556，F1 0.7143**；仅 **10/60** 条记录完整覆盖三个已标注实体。六种重复模板不能充当第三方独立测试集。
- 历史 MIMIC 汇总 **222次就诊 / 64个患者 / 545条诊断** 无法由现存源文件复现。六个现存副本哈希一致，独立计数为 **85 / 40 / 21**，其中13条记录有诊断。历史报告保留，旧数字不作为本阶段已核实成果。
- 默认持久化结果现在只含伪名键、状态、固定问题码和计数；**正文、主诉、个体检验值及 SFT 候选文本全部暂停导出**。`accepted` 仅表示算子路由通过，不表示隐私批准或医学有效。

完整发现、验收结果和后续门槛见 [第一阶段审计](docs/PHASE1_AUDIT_CN.md)、[开发日志](DEVELOPMENT_PROGRESS.md)。机器可读证据在 `reports/phase1_20261025/`。

## 已实现与限制

| 模块 | 可复现能力 | 当前限制 |
|---|---|---|
| 合成数据 | 五种文本格式、600条基础记录及130个副本、跨度/检验/聚簇标签 | 标签来自同一生成器，无临床审核；旧版错误数据保留 |
| PHI规则 | 姓名、电话、病历号的有限模式，精确跨度P/R/F1 | 未覆盖完整PHI类别；同规则二次扫描不能证明无残留 |
| 检验标准化 | 体温、血糖、血红蛋白、ALT，单位转换、宽泛范围和歧义标记 | 无术语编码、医学NER或临床有效性验证 |
| 就诊内去重 | 字符shingle相似度、临床字段冲突保护、重复链接评测 | 缺少独立难负例；未解析的临床差异仍可能误合并 |
| 批处理 | Schema/HMAC预检、精确输入指纹、临时目录写入后发布、SQLite审计 | 整批驻留内存，无分布式、资源上限或断点恢复 |
| 隐私输出边界 | 所有结果只导出允许列表中的元数据；SFT文件为空 | 元数据和HMAC仍可能关联，不等于匿名化或合规认证 |
| 公开衍生数据审计 | 固定类别汇总、缺失字段/单位/非有限值检查 | 不下载或再分发行级数据；不能凭函数确认许可与来源 |
| 演示 | 实测JSON生成HTML、元数据审核CSV | 审核队列没有正文、未填写人工标签；不是标注闭环 |

## 离线复现

Python 3.10+，核心仅用标准库。在本项目根目录运行；所有目标使用**新的路径**，已有产物会拒绝覆盖。

```powershell
python -m unittest discover -s tests -v
python -m scripts.audit_phase1 --out reports/my_phase1_audit
```

第二条命令自动运行全量测试，保留旧集复算、生成修正集、独立核算计数、输出压力集错误分布、运行5次本机计时，并核验原有报告和示例未改变。首次审计记录已在 `reports/phase1_20261025/baseline/`。完整再现初版缺陷：

```powershell
python -m scripts.probe_legacy --out reports/my_legacy_probes.json
```

它从本地 Git 标签 `delivery-v0.1` 临时还原初版，仅使用合成对抗样本；需要 Git 和该标签，不访问网络。

单独运行各模块：

```powershell
python -m scripts.generate_fixture --out examples/my_corrected_fixture --n 600 --seed 20261025
python -m scripts.run_benchmark --data examples/my_corrected_fixture --out reports/my_run
python -m scripts.run_stress --out reports/my_run/stress.json
python -m scripts.render_dashboard --benchmark reports/my_run/synthetic_benchmark.json --stress reports/my_run/stress.json --out reports/my_run/dashboard.html
python -m scripts.make_review_queue --source reports/my_run/quarantine.jsonl --out reports/my_run/review_queue.csv
```

仪表盘仅使用显式传入的实验文件，避免混入旧汇总。`reports/demo_run/` 是保留的初版历史演示，含合成文本和未审阅候选；应结合本次审计阅读。最新审计演示见 `reports/phase1_20261025/verification/demo/dashboard.html`。

## 输入、输出与数据许可

合成 JSONL 每行包含非空字符串 `record_id`、`patient_group`、`encounter_group` 和字符串 `text`。重复记录ID令整批失败；Schema无效行仅计数、不回显。非JSON行令整批失败。HMAC配置错误直接失败，不能被计为坏记录。演示默认固定密钥只用于合成数据。

`accepted.jsonl`、`quarantine.jsonl` 均为元数据投影；`audit.db` 仅存伪名索引与计数；`provenance.json` 保存精确输入哈希而不保存原始文件名；`sft_candidate_UNREVIEWED.jsonl` 为空，并在审计JSON记录暂停原因。内存接口 `process_record()`、`build_sft_candidates()` 仍是研究接口，不能把返回文本作为安全出口。

公开 MIMIC Demo 衍生输入只运行聚合审计，不走文本管线。先核实来源和许可，再使用已有衍生文件：

```powershell
python -m clinforge audit-public-demo --input <已有合法公开衍生JSONL路径> --output reports/my_public_aggregate.json
```

本仓库仅分发自主合成记录及聚合结果，不复制 MIMIC 行级数据。当前复核不等于重新核验 PhysioNet 原始数据、分发许可、医学标注或合规认证。

## 后续验收

优先建立来源独立、许可可查、无真实隐私风险的冻结PHI数据集及评测协议，比较规则、可本地运行的模型和混合方法。必须按患者与模板隔离，记录误杀/漏检、记录级残留、拒绝率、耗时和错误清单，再决定是否开放任何文本出口。模型评测、SFT训练与下游价值验证均未完成。

不得自动调用付费API、租GPU、上传隐私数据或公开发布代码。后续阶段见 [阶段计划](docs/CODEX_PHASES_CN.md)、[岗位映射](docs/ANT_JD_MAPPING_CN.md)、[面试边界](docs/INTERVIEW_CN.md)。
