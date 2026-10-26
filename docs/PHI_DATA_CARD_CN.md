# PHI 评测数据集卡（phase2-phi-v1）

生成时间见 `data/phase2_phi_v1/manifest.json` 的 `built_at_utc`；构建脚本 `scripts/build_phi_benchmark.py`（seed=20261025）；独立审计 `scripts/audit_phi_dataset.py` → `reports/phase2_dataset_audit/audit.json`。

## 一句话性质

**全部为合成数据，不含任何真实患者信息。** 英文部分来自公开的第三方合成基准，中文部分由本仓库独立编写的模板生成。标签为机器标签（上游作者标注值或程序化占位偏移），**没有经过临床医生复核**。

## 来源

### 英文：ASQ-PHI v1

| 项 | 值 |
| --- | --- |
| 名称 | ASQ-PHI: Adversarial Synthetic Queries for PHI de-identification |
| 许可 | MIT |
| 仓库 | github.com/JamesWeatherhead/asq-phi |
| 固定 revision | `fdb371ce7e3908a945d82f20411546b9876f862e` |
| 引用 | Weatherhead, Golovko & McCaffrey (2026), *Data in Brief* 65:112586, doi:10.1016/j.dib.2026.112586 |
| 数据量 | 1,051 条临床检索式查询，2,973 个 PHI 元素 |
| 合成方式 | 上游作者使用 Azure OpenAI GPT-4o 生成；上游声明未使用真实患者数据 |
| 标签来源 | 上游随数据发布的 `PHI_TAGS`（`identifier_type` + `value`），本仓库仅把 `value` 解析回字符偏移 |
| 文件校验 | `data/external/asq_phi/source_manifest.json` 记录每个文件的 SHA256，构建与审计均重新校验 |

### 中文：ClinDataForge-independent-zh-v1

| 项 | 值 |
| --- | --- |
| 生成脚本 | `scripts/build_phi_benchmark.py`（`ZH_TEMPLATES` 40 族 × 8 条） |
| 许可 | 与本仓库一致（MIT） |
| 数据量 | 320 条（280 条含 PHI + 40 条无 PHI 硬负样本） |
| 合成方式 | 程序化模板 + 程序化姓名/电话/编号/日期/地址；临床段来自 20 条固定临床描述 |
| 标签来源 | 模板占位符的程序化字符偏移，**非人工标注** |
| 独立性 | 模板由数据集任务编写，不导入也不参考 `clinforge.phi_rules`、`clinforge.operators` 或旧 v0.1 生成器的任何模式 |

## 标签映射（ASQ-PHI → 评测标签）

| ASQ-PHI `identifier_type` | 评测标签 | 数量 |
| --- | --- | --- |
| NAME | NAME | 814 |
| GEOGRAPHIC_LOCATION | ADDRESS | 826 |
| DATE | DATE | 806 |
| MEDICAL_RECORD_NUMBER | PATIENT_ID | 305 |
| HEALTH_PLAN_BENEFICIARY_NUMBER | INSURANCE_ID | 91 |
| PHONE_NUMBER | PHONE | 45 |
| SOCIAL_SECURITY_NUMBER | SSN | 33 |
| EMAIL_ADDRESS | EMAIL | 31 |
| UNIQUE_IDENTIFIER | PATIENT_ID | 14 |
| ACCOUNT_NUMBER | PATIENT_ID | 4 |
| FAX_NUMBER | PHONE | 2 |
| CERTIFICATE_LICENSE_NUMBER | **范围外，不评分** | 1 |
| IP_ADDRESS | **范围外，不评分** | 1 |

未解析条目共 3 条：1 条 `GEOGRAPHIC_LOCATION`（`Children's Clinic` 在原文中逐字未命中）与上述 2 条范围外类型，均在 manifest 中逐条列出。`UNIQUE_IDENTIFIER`、`ACCOUNT_NUMBER` → `PATIENT_ID` 是本仓库的归并判断，可能低估"唯一标识符"这一独立类别的难度。

## 保护医学内容（CLINICAL）标注层

- 英文：程序匹配 54 个临床词表词条 + 90 岁以下年龄表达式（`N-year-old`）。
- 中文：模板中的 `{CLINICAL}` 整段。
- 性质：**不完整的程序化代理**，仅用于测量"误删有用医学信息"的方向性代价。"未被标记为 CLINICAL"不等于"不是医学信息"，因此误删率只能横向比较，不能当作绝对安全指标。
- 与 PHI 金标重叠的 CLINICAL 跨度会在构建期直接报错。

## 划分与泄漏控制

划分单位是**近重复连通分量**。两份文档满足以下任一条件即并入同一分量，分量不得跨划分：

1. PHI 与临床段遮蔽后的骨架完全相同；
2. 骨架 5-gram Jaccard ≥ 0.50；
3. 另一套掩码（保留数字，仅留字母数字与汉字）6-gram Jaccard ≥ 0.50；
4. 同一中文模板族（作者声明）。

相似对检索使用前缀过滤（prefix filtering）的精确 Jaccard 连接，不留假阴性。目标配额按记录数：train 25% / dev 20% / test 55%，按语言分别执行，随机种子 20261025。

独立审计用**另一套掩码与 shingle 定义**重新核验，结论：相同文本跨划分 0 对、独立掩码碰撞跨划分 0 对、模板族跨划分 0 个、跨划分 6-gram Jaccard ≥ 0.50 的文档对 0 对。

### 划分结果

| 划分 | 记录 | 含 PHI | 无 PHI | 实体 | en / zh | 分量 |
| --- | --- | --- | --- | --- | --- | --- |
| train | 343 | 258 | 85 | 1,017 | 263 / 80 | 251 |
| dev | 396 | 367 | 29 | 1,411 | 332 / 64 | 90 |
| test | 632 | 487 | 145 | 1,942 | 456 / 176 | 463 |

`demo_pipeline.jsonl`（40 条）取自 train，仅用于流水线冒烟演示，不参与评测。

## 已知局限

1. 英文是**短查询**而非完整病历，PHI 密度与真实住院记录不同；结论不能外推到长文本病历。
2. 两个来源都是机器标签，未做医生复核；因此"高召回"只能说明在该合成分布上覆盖了已标注 PHI。
3. 中文模板由本仓库编写，与规则/模型开发过程在同一仓库内，独立性弱于英文第三方来源；必须分层报告。
4. GLiNER 与 Presidio 的训练语料是否包含 ASQ-PHI 无法排除；ASQ-PHI 由 GPT-4o 生成，与公开语料存在风格重叠的可能。
5. 八类标签之外仍可能存在其它 HIPAA 标识符（如完整 URL、设备序列号、生物特征），本基准不覆盖。
