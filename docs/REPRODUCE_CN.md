# 复现指南

> 所有命令在仓库根目录执行。核心包只依赖 Python 标准库；涉及 ONNX / spaCy / Presidio 的步骤
> 必须使用隔离环境 `.venv-phi`（Python 3.10.7）。Windows 路径含中文，命令统一用相对路径。

## 1. 环境

| 用途 | 环境 | 关键依赖 |
| --- | --- | --- |
| 单元测试、合成、审计、报告渲染 | 系统或管理版 Python 3.10+ / 3.13 | 标准库 |
| PHI 门控、上下文留出评测中的模型路径 | `.venv-phi`（Python 3.10.7） | onnxruntime 1.20.1、tokenizers、numpy、spacy 3.8.x、presidio |
| 已冻结的 PHI 权重 | `models/phase2_gliner_pii/onnx_fp16/`、`onnx_fp32/` | 不随仓库分发，需按 `docs/PHI_DATA_CARD_CN.md` 获取并校验 SHA256 |

```bash
# 隔离环境（已存在则跳过）
python -m venv .venv-phi
.venv-phi/Scripts/pip install -r requirements-phi.txt
```

依赖坑（已踩过）：
- `spacy` 3.8.x 需锁 `preshed==3.0.9`、`cymem==2.0.8`、`murmurhash==1.0.10`，否则加载 pipeline 抛 `OverflowError`。
- GLiNER 的 `model_quantized.onnx`（int8）会表征坍缩，必须用 `onnx_fp16/model_fp16.onnx` 或 `onnx_fp32/model.onnx`。
- 不要安装 `onnx` Python 包做图改造：本机 protobuf 版本冲突会导致 DLL 初始化失败。

## 2. 一分钟验证

```bash
python -m unittest discover -s tests -q
# 预期：Ran 170 tests ... OK（约 10 秒）
```

## 3. 从零重建（按顺序）

```bash
# 3.1 HPO 知识快照（需要 data/external/hpo/hp.obo 与 phenotype.hpoa）
python -m scripts.build_hpo_kb --out data/phase3_synth
# 产物：data/phase3_synth/kb/hpo_snapshot.json、disease_selection.json（write-once）
# 注意：disease_selection.json 是历史算法选择结果，不是实际生成清单；见 docs/FINAL_DELIVERY_CN.md

# 3.2 生成 2,400 条合成病例（约 1–2 分钟）
python -m scripts.generate_synth --out data/phase3_synth/gen --n-cases 2400

# 3.3 验证（模板内自检；项目共享常数表）
python -m scripts.validate_synth --out reports/phase3_synth_validation
# 3.3b 验证（独立常数路径，输出到新目录，不覆盖历史）
python -m scripts.validate_synth \
    --out reports/phase4_lab_independence/validation_independent --lab-standards independent

# 3.4 九段流水线（约 42 分钟，PHI 门控占绝大部分）
python -m scripts.run_med_pipeline --out data/phase4_synth_v2/pipeline_out

# 3.5 流水线评测（模板内自检）
python -m scripts.evaluate_pipeline_synth \
    --pipeline data/phase4_synth_v2/pipeline_out --out reports/phase4_pipeline_eval

# 3.6 导出 SFT / 偏好候选（不训练）
python -m scripts.export_training_candidates \
    --pipeline data/phase4_synth_v2/pipeline_out --out data/phase4_synth_v2/training_candidates

# 3.7 六类数据质量审计
python -m scripts.audit_data_quality \
    --export data/phase4_synth_v2/training_candidates \
    --pipeline data/phase4_synth_v2/pipeline_out \
    --out reports/phase4_data_quality/audit.json
```

## 4. 上下文判定实验

```bash
# 4.1 诊断 783 例的来源（只分析，不改代码）
python -m scripts.diagnose_context

# 4.2 冻结留出语料（write-once；已存在时会拒绝）
python -m scripts.build_context_holdout

# 4.3 三系统同数据对比（write-once；开发集仅诊断）
python -m scripts.evaluate_context_scope --corpus dev
python -m scripts.evaluate_context_scope --corpus holdout

# 4.4 簇自助（近重复结构下的不确定性）
python -m scripts.audit_split_relations      # 先产出 cluster_members
python -m scripts.analyze_holdout_clusters --iterations 2000
```

预期关键数字：
- `dev_eval.json`：v1 准确率 0.9617、history→affirmed 783；v2 1.0000、0。
- `holdout_eval.json`：v1 0.7021 / 221；v2_scope_v1 0.8869 / 57；v2 0.9778 / 0。
- `holdout_bootstrap.json`：v2 准确率 CI [0.9451, 1.0000]；64 个簇。
- 历史结果 `holdout_eval_ctxscope100.json` 保留首次留出评测暴露的英文句号缺陷，不覆盖。

## 5. 血缘、切分与检验常数

```bash
python -m scripts.build_disease_lineage
# 产物：data/phase4_lineage/lineage_manifest.json + record_disease_index.csv
#       reports/phase4_lineage/lineage_report.md

python -m scripts.audit_split_relations
# 产物：reports/phase4_split_relations/relations.json + report.md（约 25 秒）

python -m scripts.audit_lab_independence
# 产物：reports/phase4_lab_independence/audit.json + report.md（约 6 秒）
```

## 6. PHI 性能与回归

```bash
# 6.1 线程扫描 + 批处理探针（约 10 分钟）
python -m scripts.bench_phi

# 6.2 五配置独立进程对比（每个配置重新加载权重，测峰值 RSS）
python -m scripts.bench_phi_configs --report

# 6.3 冻结测试集回归（632 条，约 12 分钟；write-once）
python -m scripts.evaluate_phi_optimized \
    --config configs/phase4_phi_fast.json --out reports/phase4_perf/test_run_fast
```

注意：`test.jsonl` 的 SHA256 必须与 `reports/phase2_phi_v1/test_run/results.json`
的 `dataset_sha256` 一致；脚本会先校验再评测。冻结结果仍是主报告数字，重算只用于回归。

## 7. 报告、演示与成果包

```bash
python -m scripts.render_phase4_report          # 第四阶段表格 + 看板
python -m scripts.showcase_samples              # 罕见病样本与修复个案
python -m scripts.build_demo                    # demo/index.html
python -m scripts.build_final_package            # 实验表 + 指标登记簿
```

## 8. 不要做的事

- 不要重跑 `reports/phase2_phi_v1/test_run/`（冻结测试集只评测一次，重跑会改变实验次数口径）。
- 不要在 `data/phase4_context/holdout_notes.jsonl` 上调参；裸「疑」的 36 例残留是故意保留的。
- 不要覆盖 `holdout_eval_ctxscope100.json`、`holdout_eval_ctxscope110.json`、`holdout_eval.json`。
- 不要把 `data/phase3_synth/kb/disease_selection.json` 当作实际疾病清单。
- 不要修改金标来让审计数字变好；发现差异应写进报告与配置的 `frozen_test_regression` 字段。
- 不要 push 到 GitHub；本地提交即可。
