# 第一阶段：独立代码审计与复现验收

日期：2026-10-25。结论：**完成本阶段代码与历史实验审计；独立PHI安全验收未通过，也尚未实施模型对照。** 当前不能安全处理真实患者病历。

## 1. 审计范围与证据保全

已阅读项目约定、启动说明、README、岗位映射、阶段计划、全部Python源码、三个原测试文件、Windows启动器和全部历史实验JSON/日志。历史JSONL及SQLite通过行数、关联、指标、输出一致性检查核验；没有把旧报告的文字结论直接当作事实。

项目最初仅存在于用户提供的ZIP。解压前检查全部成员路径均在工作目录内；创建独立本地Git仓库，避免把父目录其他项目已暂存的工作混入提交。初版快照为 `af8a8f7`，标签 `delivery-v0.1`。没有远程发布。

- ZIP SHA256：`5d3ee179f53d410e81aed63d7f72478c55c9152f6986580817c9bbada53732b3`。
- 初版全部文件指纹：[original_file_sha256.json](../reports/phase1_20261025/baseline/original_file_sha256.json)。
- 首次重跑测试：[baseline/unittest.log](../reports/phase1_20261025/baseline/unittest.log)，28/28通过。
- 初版复现：[baseline/summary.json](../reports/phase1_20261025/baseline/summary.json)。Windows生成文件CRLF与交付LF不同，但所有JSON对象完全相同；见 [delivery_provenance.json](../reports/phase1_20261025/baseline/delivery_provenance.json)。
- 原始 `examples/generated_fixture/`、`reports/demo_run/` 和顶层历史报告的每个字节均保留：[历史产物指纹验收](../reports/phase1_20261025/verification/historical_artifact_integrity.json)。

## 2. 历史结果复算

| 任务 | 数据与分母 | 朴素基线 | 复核后的规则结果 |
|---|---|---|---|
| 旧模板PHI精确跨度 | 730记录、2190跨度 | TP438 / FP0 / FN1752，F1=0.3333 | TP2190 / FP0 / FN0，F1=1.0000 |
| 旧模板检验字段（容差0.02） | 2886个金标字段 | TP430 / FP0 / FN2456，F1=0.2593 | TP2880 / FP6 / FN6，F1=0.9979 |
| 模板重复记录识别 | 130个额外副本 | 无对应基线 | TP130 / FP0 / FN0，F1=1.0000 |
| 旧合成压力集PHI | 60记录、180跨度、仅6种模板 | TP50 / FP0 / FN130，F1=0.4348 | TP100 / FP0 / FN80，Recall=0.5556，F1=0.7143 |

五组历史指标、压力测试JSON均完整复现。流水线路由仍为573通过、157隔离，130条重复和34次温度异常标志可重叠。当前导出策略另有收紧，不能把新输出与旧文本导出视为同一实验条件。

对压力集按标签复算：NAME TP30/FN30、PHONE TP50/FN10、MRN TP20/FN40，均FP0。只有10/60条记录覆盖全部三个金标跨度（16.67%）；它是**已标注实体的覆盖率**，不能说明未标实体不存在，也不是实际患者“零残留”证明。旧集反复模板、与开发假设有关联，只能用于诊断，不能再称为真正独立测试集。见 [stress_diagnostics.json](../reports/phase1_20261025/verification/stress_diagnostics.json)。

## 3. 影响实验可信度的两项发现

### 3.1 六处检验“错误”来自合成数据生成器

异常温度注入使用 `(T=)\d+...` 全局替换，误匹配 `ALT=` 中的 `T=`。五条基础记录及一个变体的正文ALT被改为700，金标仍保留原ALT。旧指标的6个FP和6个FN因此来自正文与金标不一致，而非解析器犯错。

已加token边界及单次替换，新增与原始字段文本独立核验的测试。旧数据不修改，新集保存在 [corrected_fixture_v1](../reports/phase1_20261025/verification/corrected_fixture_v1/fixture_manifest.json)，仅六条正文改变，金标对象与原文件完全相同。修正后检验TP2886/FP0/FN0、F1=1.0000。**这是数据一致性修复，不是抽取算法带来的独立收益。** PHI与重复检测分数不变。

错误记录列表及原因：[generator_correction.json](../reports/phase1_20261025/verification/generator_correction.json)。完整新旧计数及单独实现的指标算术复核：[summary.json](../reports/phase1_20261025/verification/summary.json)。算术复核独立于原评测函数，数据/金标仍然不独立。

### 3.2 历史MIMIC汇总无法由现存源复现

六个现存 `MedDataLab*/reports/public_demo/public_clinical_structured.jsonl` 副本完全相同，均为59,923字节，SHA256为 `8b7e245ab1525c3fc1b15e2f2672b76c36caaf77e80ca04c1a7d0ff0df376d21`。

| 指标 | 历史报告 | 现存衍生文件独立计数 |
|---|---:|---:|
| 记录/不同就诊ID | 222 / 222 | 85 / 85 |
| 不同subject ID | 64 | 40 |
| 诊断关联 | 545 | 21 |
| 有诊断记录 | 221 | 13 |

用不调用原审计函数的直接集合/计数再次检查，与修复后的审计器一致。见 [来源与历史差异](../reports/phase1_20261025/public_audit_v2/source_verification.json)、[六个副本独立重查](../reports/phase1_20261025/public_audit_v2/independent_recheck.json)。没有复制、打印或导出患者级记录/ID。

历史报告缺少源文件指纹，不能确定它对应另一个源版本还是其他过程；不能据此断言历史数字被伪造，也不能当作当前已核实成果。未重新下载PhysioNet原始文件或审计上游变换。源文件中的异常flag和主诉tag只做汇总计数，没有重新计算医学异常。

## 4. 已复现并修复的问题

初版可重放的合成对抗诊断见 [adversarial_probes.json](../reports/phase1_20261025/baseline/adversarial_probes.json)，复现脚本为 `scripts/probe_legacy.py`。这些已看过的样本只作为回归测试，不冒充新泛化集。

| 问题 | 初版复现 | 本阶段处理 |
|---|---|---|
| 漏检PHI外泄 | 未知前缀姓名/点分电话/病历号可被accepted并写入SFT；隔离也保留正文 | 所有流水线记录导出只做允许列表元数据投影，正文/主诉/个体检验值不写出，SFT为空并记录暂停原因 |
| 任意元数据外泄 | source_type可携带任意对象，provenance原样保存文件名 | 不持久化自由来源字段与原文件名，保留输入哈希 |
| 配置被吞掉 | 短HMAC密钥被算作坏记录，返回“成功处理0条” | 运行前预检，配置错误明确失败 |
| 输入Schema与重复ID | 列表行崩溃，空ID通过；重复ID在SQLite失败前已经写出正文 | 对象与非空ID校验；重复ID整批拒绝；临时目录完成文件/SQLite后再发布 |
| 半套结果 | 写文件或SQL失败留下部分产物 | 同文件系统暂存、关闭数据库后目录重命名；注入文件/SQL故障验证无最终产物 |
| 检验别名子串 | SALT/nonGLU/notT/noHb被当作四个检验字段 | 别名边界保护及对抗回归 |
| 临床更新被误去重 | 血糖5→25，文本相似0.8913仍被判重复 | 已抽取检验值/主诉冲突时保留不同记录 |
| split校验绕过 | 实际患者跨split而cluster不同仍返回完整性通过 | 验证实际patient_group及cluster的患者/就诊/split范围、唯一ID、跨度/有限值契约 |
| 只看重复分类 | duplicate_of链接错误也可能获得分类满分 | 另加早先同金标cluster链接的P/R/F1 |
| “仅聚合”字段泄漏 | 任意诊断系统、flag、tag、measurement键进入汇总 | 固定类别允许列表；未知项计OTHER/计数，原始字符串不写出 |
| 聚合缺失/数值错误 | 缺失键漏计、空ID被当一个人、未知温度单位按摄氏、NaN生成非法JSON | 固定字段分母，缺失ID独立计数；无效数值/单位单独标记，拒绝数值溢出，严格JSON |
| 历史产物覆盖/混用 | 多个脚本默认覆写；新仪表盘暗读旧汇总 | 独占创建拒绝覆盖；显式指定stress/public报告、动态分母、元数据审核CSV |

`accepted`/`quarantine` 仍为**算子质量路由**；隐私出口对两者一律关闭。非合成输入继续被拒绝；调用方不得用 `--synthetic` 给真实记录改标签。元数据仍可能关联，HMAC不是匿名化认证，演示固定密钥不得用于生产。内存算子仍可能返回漏检文本，不能作为安全文本出口。

## 5. 本阶段真实验收

- **70/70** 全量测试通过，unittest记录用时 **2.386秒**：[完整日志](../reports/phase1_20261025/verification/unittest.log)。其中隐私canary覆盖所有流水线文件及SQLite二进制，不仅检查已知规则是否匹配。
- 旧模板/压力集真实计数与原报告相符；全部原始示例和实验文件指纹未变。
- 生成器修正后的模板检验F1=1.0；没有修改PHI识别规则或训练模型。
- 730条本机、单进程、元数据输出流水线5次计时为0.375678、0.376649、0.343671、0.372883、0.384331秒；中位 **0.375678秒，1,943.15条/秒**。[环境与原始计时](../reports/phase1_20261025/verification/local_speed.json)。Python3.10.7，Windows10.0.26200，SQLite3.37.2。与历史0.0632秒的环境及输出条件不同，不能宣称提速/退化因果，更不能外推TB级。
- benchmark、仪表盘、40条元数据审核CSV及CLI真实运行成功：[命令与退出码](../reports/phase1_20261025/verification/cli_smoke.json)、[演示](../reports/phase1_20261025/verification/demo/dashboard.html)。没有进行人工医学审核。
- 源码/测试/脚本的运行时SHA256见 [environment.json](../reports/phase1_20261025/verification/environment.json)。新增功能验收证据均来自实际执行，没有付费API、GPU租用、外部上传或公开发布。

复现命令（每次换新目标）：

```powershell
python -m scripts.audit_phase1 --out reports/my_phase1_replay
python -m scripts.probe_legacy --out reports/my_legacy_probes.json
```

本机已有合法公开衍生文件的汇总可另行复现；报告不会包含行级记录：

```powershell
Get-FileHash ../MedDataLab/reports/public_demo/public_clinical_structured.jsonl -Algorithm SHA256
python -m clinforge audit-public-demo --input ../MedDataLab/reports/public_demo/public_clinical_structured.jsonl --output reports/my_public_replay.json
```

## 6. 未解决问题与下一阶段建议

1. **P0独立PHI评测尚缺失。** 先选择来源独立、许可可验证、无真实隐私风险的合成/挑战数据，冻结原始文本、独立金标、患者/模板分组及哈希，再开始建模；旧压力集不得继续当测试集调参。
2. 比较当前规则、可在本机运行且许可合适的模型、规则+模型。报告按类精确跨度P/R/F1、金标残留率、误杀、拒绝率、耗时与完整错误清单。未经评测不要承诺模型优于规则。
3. 质量分数无独立医学gold、未校准；去重仍是局部字符法，只保护已抽取字段，无法保证未解析时序、否定、处方等语义差异。
4. 现有合成集由开发者程序生成，标签与方法假设相关；划分结构正确不能证明未见泛化。SFT历史分组策略与评测标签也不同，当前不导出候选，更没有训练收益。
5. 批处理整批驻留内存，未测资源上限、10万条输入、恢复机制或并发一致性；不扩张功能数量来替代核心效果验证。
6. MIMIC历史222/64/545的原始来源仍未找回。本阶段完成的是现存衍生文件聚合核验，没有补全真实文本隐私许可、医院生产接入或临床认证。

在完成独立验收前维持文本出口关闭；下一阶段优先推进PHI数据协议和规则/模型对照，之后再推进医学实体、标准化、近重复、质量gold及规模化。
