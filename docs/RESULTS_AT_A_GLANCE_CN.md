# 第一阶段结果与证据边界

| 项目 | 复核结论 | 证据 |
|---|---|---|
| 原始交付 | 本地Git标签 `delivery-v0.1`，ZIP指纹已保存 | `reports/phase1_20261025/baseline/delivery_provenance.json` |
| 初版测试 | 28/28通过；不足以覆盖本次发现的缺陷 | `baseline/unittest.log` |
| 旧模板指标 | 730条、2190个PHI跨度；全部五组历史计数复现 | `verification/legacy_fixture_benchmark.json` |
| 六处检验不一致 | 温度注入误改ALT；修正正文另存，金标对象不变 | `verification/generator_correction.json` |
| 修正模板指标 | PHI F1=1.0、检验F1=1.0、重复检测F1=1.0；均非独立数据 | `verification/corrected_fixture_benchmark.json` |
| 旧压力集 | PHI Recall0.5556、F1 0.7143，完整覆盖记录10/60；仅六种模板 | `verification/stress_diagnostics.json` |
| MIMIC历史差异 | 旧222/64/545无法复现；现存源85/40/21，13条有诊断 | `public_audit_v2/source_verification.json` |
| 当前文本出口 | 流水线仅元数据；SFT输出0条 | `verification/corrected_fixture_pipeline/audit.json` |
| 最新测试和计时 | 见原始日志及JSON，均为本机软件实验 | `verification/unittest.log`、`verification/local_speed.json` |

上述相对证据路径统一位于 `reports/phase1_20261025/`。完整报告见 `PHASE1_AUDIT_CN.md`。独立PHI数据/模型对照、临床审核、模型训练、真实患者处理和生产合规均未完成。
