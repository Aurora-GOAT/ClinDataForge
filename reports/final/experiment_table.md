# ClinDataForge · 核心实验表

- 版本 `final-package-1.0.0`，生成时间 2026-10-26T18:34:49Z
- 每一行的数值都来自 `reports/final/metrics_registry.json` 中登记的产物字段；本表由 `scripts/build_final_package.py` 自动生成。

## 效力分级（先读这一节）

| 级别 | 含义 |
| --- | --- |
| `template_self_check` | 模板内自检：金标由生成器构造，模板与金标同源，不能当独立评测 |
| `synthetic_holdout` | 同生成器的留出合成语料：评测前冻结，新种子/新句式，但共享代码与疾病集 |
| `third_party_frozen` | 第三方合成数据上的冻结评测：ASQ-PHI v1（MIT），一次性测试 |
| `engineering_measurement` | 同机同数据的工程测量：可以声称加速比，不能外推到其他硬件 |
| `audit_finding` | 审计结论：对产物做静态/重算检查，不是模型指标 |

## 1. 上下文状态 · 开发集（仅诊断，不是测试集）

**效力**：模板内自检 / 诊断

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 开发集匹配提及数 | 22156 | mentions | `reports/phase4_context/dev_eval.json`<br>`systems.v1.per_class._overall.n` |  |
| v1 固定窗口准确率 | 96.17% | % | `reports/phase4_context/dev_eval.json`<br>`systems.v1.per_class._overall.accuracy` |  |
| v2 作用域准确率 | 100.00% | % | `reports/phase4_context/dev_eval.json`<br>`systems.v2_scope_ng.per_class._overall.accuracy` |  |
| history→affirmed（v1） | 783 | mentions | `reports/phase4_context/dev_eval.json`<br>`systems.v1.confusion.history.affirmed` |  |
| history→affirmed（v2） | 0 | mentions | `reports/phase4_context/dev_eval.json`<br>`systems.v2_scope_ng.confusion.history.affirmed` |  |

## 2. 上下文状态 · 冻结留出合成语料（260 条 / 64 个近重复簇）

**效力**：同生成器留出合成语料

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 留出语料记录数 | 260 | notes | `reports/phase4_context/holdout_eval.json`<br>`n_records` |  |
| 留出语料匹配提及数 | 1618 | mentions | `reports/phase4_context/holdout_eval.json`<br>`n_matched_mentions` |  |
| 不同规范化文本数 | 186 | texts | `reports/phase4_split_relations/relations.json`<br>`near_duplicates.holdout_structure.n_distinct_normalised_texts` | 260 条中存在重复副本 |
| 近重复簇数（Jaccard≥0.8） | 64 | clusters | `reports/phase4_split_relations/relations.json`<br>`near_duplicates.holdout_structure.n_clusters_at_threshold` | 有效独立单位远少于 260 |
| v1 固定窗口准确率 | 70.21% | % | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v1.point.accuracy` | 簇自助 95% CI [0.6337, 0.7734] |
| v1 固定窗口宏 F1 | 0.6840 | F1 | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v1.point.macro_f1` | 簇自助 95% CI [0.5872, 0.7980] |
| v1 固定窗口history→affirmed | 221 | mentions | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v1.history_to_affirmed_point` |  |
| v2 作用域 + v1 词表准确率 | 88.69% | % | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v2_scope_v1.point.accuracy` | 簇自助 95% CI [0.8129, 0.9460] |
| v2 作用域 + v1 词表宏 F1 | 0.8482 | F1 | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v2_scope_v1.point.macro_f1` | 簇自助 95% CI [0.7583, 0.9564] |
| v2 作用域 + v1 词表history→affirmed | 57 | mentions | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v2_scope_v1.history_to_affirmed_point` |  |
| v2 作用域 + NegEx 词表准确率 | 97.78% | % | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v2_scope_ng.point.accuracy` | 簇自助 95% CI [0.9451, 1.0000] |
| v2 作用域 + NegEx 词表宏 F1 | 0.9567 | F1 | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v2_scope_ng.point.macro_f1` | 簇自助 95% CI [0.9232, 1.0000] |
| v2 作用域 + NegEx 词表history→affirmed | 0 | mentions | `reports/phase4_split_relations/holdout_bootstrap.json`<br>`systems.v2_scope_ng.history_to_affirmed_point` |  |

## 3. PHI 检测 · ASQ-PHI v1 冻结测试集（632 条，第三方合成数据）

**效力**：第三方合成数据冻结评测

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 方法 A 实体级 P/R/F1 | 0.7800 / 0.0803 / 0.1457 | ratio | `reports/phase2_phi_v1/test_run/results.json`<br>`methods.A.overall.entity_exact` |  |
| 方法 B 实体级 P/R/F1 | 0.3905 / 0.3084 / 0.3446 | ratio | `reports/phase2_phi_v1/test_run/results.json`<br>`methods.B.overall.entity_exact` |  |
| 方法 C 实体级 P/R/F1 | 0.7522 / 0.8363 / 0.7920 | ratio | `reports/phase2_phi_v1/test_run/results.json`<br>`methods.C.overall.entity_exact` |  |
| 方法 D 实体级 P/R/F1 | 0.7566 / 0.9042 / 0.8238 | ratio | `reports/phase2_phi_v1/test_run/results.json`<br>`methods.D.overall.entity_exact` |  |
| 冻结测试集文档数 | 632 | docs | `reports/phase2_phi_v1/test_run/results.json`<br>`methods.D.overall.n_records` |  |
| 数据 SHA256 | 96d5b2c6aa3a52f8… | sha256 | `reports/phase2_phi_v1/test_run/results.json`<br>`dataset_sha256` |  |

## 4. PHI 吞吐 · 本机同一数据（工程测量）

**效力**：同机工程测量

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 基线 ms/条 | 2778.3 | ms/doc | `reports/phase4_perf/comparison.json`<br>`table[baseline_fp16_t2_b1].mean_ms_per_doc` |  |
| 优化后 ms/条 | 994.8 | ms/doc | `reports/phase4_perf/comparison.json`<br>`table[fp32_t4_b1].mean_ms_per_doc` |  |
| 单条加速比 | 2.79 | × | `reports/phase4_perf/comparison.json`<br>`derived from table[].mean_ms_per_doc` |  |
| p95 基线→优化 | 4787.4 → 1747.9 | ms | `reports/phase4_perf/comparison.json`<br>`table[].p95_ms_per_doc` |  |
| 吞吐 基线→优化 | 0.36 → 1.00 | docs/s | `reports/phase4_perf/comparison.json`<br>`table[].docs_per_second` |  |
| 峰值内存 基线→优化 | 1349.5 → 2128.6 | MB | `reports/phase4_perf/comparison.json`<br>`table[].peak_rss_mb` |  |
| 九段流水线端到端 2,400 条 | 79.1 → 42.0 分钟（1.89×） | min | `data/phase3_synth/pipeline_out/audit.json; data/phase4_synth_v2/pipeline_out/audit.json`<br>`wall_seconds` |  |

## 5. PHI 回归 · 冻结测试集重算（只披露差异，不回改阈值）

**效力**：冻结集回归检查

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 冻结集重算文档数 | 632 | docs | `reports/phase4_perf/test_run_fast/comparison.json`<br>`methods.D.documents` |  |
| 方法 D 跨度一致率 | 0.9984 | ratio | `reports/phase4_perf/test_run_fast/comparison.json`<br>`methods.D.doc_identity_rate` |  |
| 新增 / 缺失跨度 | 1 / 0 | spans | `reports/phase4_perf/test_run_fast/comparison.json`<br>`methods.D.spans_added_vs_frozen, spans_missing_vs_frozen` |  |
| 方法 D 召回 冻结→重算 | 0.9042 → 0.9042 | ratio | `reports/phase4_perf/test_run_fast/comparison.json`<br>`methods.D.metrics_frozen/optimized.entity_exact.recall` |  |
| 方法 D 精确率 冻结→重算 | 0.7566 → 0.7562 | ratio | `reports/phase4_perf/test_run_fast/comparison.json`<br>`methods.D.metrics_frozen/optimized.entity_exact.precision` |  |

## 6. 九段流水线 · 2,400 条合成病例（模板内自检）

**效力**：模板内自检

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 输入 / 接受 / 隔离 | 2400 / 2355 / 45 | records | `data/phase4_synth_v2/pipeline_out/audit.json`<br>`input_rows, accepted_rows, quarantined_rows` |  |
| 表型抽取 F1 | 0.9910 | F1 | `reports/phase4_pipeline_eval/pipeline_eval.json`<br>`phenotype_extraction` |  |
| 上下文状态准确率 | 100.00% | % | `reports/phase4_pipeline_eval/pipeline_eval.json`<br>`context_status_accuracy_on_matched` |  |
| 检验标准化 | 1277/1277 | values | `reports/phase4_pipeline_eval/pipeline_eval.json`<br>`lab_standardisation` |  |
| PHI 掩码覆盖（合成） | 5196/5196 | entities | `reports/phase4_pipeline_eval/pipeline_eval.json`<br>`phi_gate_synthetic` |  |
| 近重复判定 F1 | 1.0000 | F1 | `reports/phase4_pipeline_eval/pipeline_eval.json`<br>`dedup_pairs` |  |

## 7. 数据质量、血缘与切分审计

**效力**：静态与重算审计

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 疾病血缘记录数 | 2400/2400 | records | `data/phase4_lineage/lineage_manifest.json`<br>`checks.records` |  |
| 表型 HP 编码属于疾病注释集 | 22,156/22,156 | entities | `data/phase4_lineage/lineage_manifest.json`<br>`checks.phenotype_hp_in_annotation` |  |
| 记录级 HPO 溯源 = 快照 | 2400/2400 | records | `data/phase4_lineage/lineage_manifest.json`<br>`checks.hpo_provenance_equals_snapshot` |  |
| 历史疾病清单与实际重合 | 3/16 | diseases | `data/phase4_lineage/lineage_manifest.json`<br>`superseded_artifact.n_overlap` |  |
| SFT 划分 train/dev/test | 1921/230/204 | records | `reports/phase4_data_quality/audit.json`<br>`split_leakage.split_sizes` |  |
| 跨划分患者 / 精确重复 / 近重复 | 0 / 0 / 0 | counts | `reports/phase4_data_quality/audit.json; reports/phase4_split_relations/relations.json`<br>`split_leakage.patients_shared_across_splits / exact_duplicate_inputs_across_splits` |  |
| test 记录三元组已在 train 出现 | 99.02% | % | `reports/phase4_split_relations/relations.json`<br>`cell_reuse.test.rate` |  |
| 疾病名出现在正文（train） | 100.00% / 85.37%（脱敏后） | % | `reports/phase4_split_relations/relations.json`<br>`disease_name_leakage.train.raw_rate / masked_rate` |  |
| 上下文标签污染 | 0/21640 | mentions | `reports/phase4_data_quality/audit.json`<br>`context_contamination.exported_status_mismatches` |  |
| 偏好对标签噪声 | 0/2355 | pairs | `reports/phase4_data_quality/audit.json`<br>`preference_labels.pairs_where_rejected_is_not_actually_wrong` |  |
| 中文术语与专家审核 | 214 表型 + 16 疾病；无专家审核 | terms | `reports/phase4_data_quality/audit.json`<br>`translation` |  |

## 8. 检验常数独立核验

**效力**：独立路径审计

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 语料检验值独立复算 | 1277 | values | `reports/phase4_lab_independence/audit.json`<br>`corpus_recomputation.n_checked` |  |
| 换算 / 方向不一致 | 0 / 0 | values | `reports/phase4_lab_independence/audit.json`<br>`corpus_recomputation` |  |
| 注入实验：共享表 / 独立路径 检出 | 0 + 0 错 / 26 + 10 错 | errors | `reports/phase4_lab_independence/audit.json`<br>`perturbation_experiment` |  |

## 9. 工程与测试

**效力**：可复现工程

| 指标 | 数值 | 单位 | 产物 | 备注 |
| --- | --- | --- | --- | --- |
| 自动化测试 | 170 | tests | `reports/final/test_summary.json`<br>`n_tests` | OK |

## 10. 不能写进简历的结论

- 任何“RAG 提升/无效”的结论：本项目没有做生成式 RAG 训练实验。
- 任何“临床准确率”“跨医院泛化”“隐私安全已证明”的表述：没有真实临床数据、没有合规认证。
- 任何“训练收益”：SFT/LoRA/DPO 均未执行，只导出了候选数据。
- 任何“留出集是独立临床验证”：留出集与开发集共享生成器、16 种疾病与中文词表；它只有 64 个近重复簇。

## 11. 复现

```bash
python -m scripts.build_final_package     # 重新生成本表与指标登记簿
python -m unittest discover -s tests -q    # 170 项测试
```
