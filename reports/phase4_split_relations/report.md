# 训练集 / 留出集关系审计

- 版本 `split-rel-1.0.0`，生成时间 2026-10-26T18:04:05Z
- 输入：2,355 条导出的 SFT 候选（train/dev/test）+ 260 条上下文留出语料
- 近重复口径：字符 4-gram Jaccard ≥ 0.80（倒排索引，忽略出现在 >40 篇文档中的高频 shingle）

## 1. 结论摘要

- 患者/就诊号：四组之间**没有任何共享**（患者重叠 0，就诊号重叠 0）。
- 精确重复文本：组内 74 条，跨组 0 对。
- 骨架（实体槽位归一化后）跨组碰撞：1 个；test 中有 **0.49%** 的记录骨架已在 train 出现。
- 单元复用：test 记录中 **99.02%** 与 train 落在同一个（模板族, 复杂度, 疾病）格子；全体只有 238 个不同格子，最大单格 36 条。留出集的疾病 **100.00%** 在 train 中出现过（模板名不同，格子不可比）。
- 近重复：跨 train/dev/test 且 Jaccard ≥ 0.80 的样本对 **0** 对；留出集**内部** **706** 对，留出集与其他三组之间 **0** 对。
- 疾病名直接出现在输入正文中的比例：train 100.00% / test 100.00%；而金标输出包含 `disease_suspected`，这是一条可被模型利用的捷径。

## 2. 组成

| 语料 | 记录 | 疾病 | 患者 | 中文/英文 | 模板族数 | 复杂度数 |
| --- | --- | --- | --- | --- | --- | --- |
| train | 1921 | 16 | 1921 | 1303/618 | 5 | 3 |
| dev | 230 | 16 | 230 | 158/72 | 5 | 3 |
| test | 204 | 16 | 204 | 133/71 | 5 | 3 |
| holdout | 260 | 16 | 260 | 150/110 | 14 | 1 |

## 3. 患者、文本与骨架

| 关系 | 患者重叠 | 就诊号重叠 | 精确重复文本 | 骨架碰撞 |
| --- | --- | --- | --- | --- |
| train vs dev | 0 | 0 | 0 | 0 |
| train vs test | 0 | 0 | 0 | 1 |
| train vs holdout | 0 | 0 | 0 | 0 |
| dev vs test | 0 | 0 | 0 | 0 |
| dev vs holdout | 0 | 0 | 0 | 0 |
| test vs holdout | 0 | 0 | 0 | 0 |

组内精确重复：train 0、dev 0、test 0、holdout 74。

## 4. 格子复用与捷径

| 语料 | 记录 | 格子已在 train 出现 | 比例 | 口径 |
| --- | --- | --- | --- | --- |
| dev | 230 | 228 | 99.13% | （模板族, 复杂度, 疾病） |
| test | 204 | 202 | 99.02% | （模板族, 复杂度, 疾病） |
| holdout | 260 | 260 | 100.00% | 疾病 |

疾病名出现在正文（脱敏前 / 脱敏后）：

| 语料 | 原始正文 | 脱敏后正文 |
| --- | --- | --- |
| train | 100.00% | 85.37% |
| dev | 100.00% | 89.57% |
| test | 100.00% | 80.39% |
| holdout | 45.77% | — |

> 这不是"数据泄漏 bug"，而是任务定义问题：知识约束合成把疾病名写进 Assessment，又把疾病 ID 放进金标。用它训练/评测时，`disease_suspected` 字段应被去掉或单独报告，否则测到的是字符串匹配而不是表型理解。

## 5. 近重复

| 语料对 | 对数（Jaccard ≥ 0.80） |
| --- | --- |
| holdout|holdout | 706 |

最高相似度样例（前 10 对）：

| 语料 | A | B | Jaccard | A 片段 |
| --- | --- | --- | --- | --- |
| holdout/holdout | `HCTX-00191` | `HCTX-00239` | 1.000 | The patient presents with Increased circulating … |
| holdout/holdout | `HCTX-00159` | `HCTX-00255` | 1.000 | The patient presents with Increased circulating … |
| holdout/holdout | `HCTX-00159` | `HCTX-00207` | 1.000 | The patient presents with Increased circulating … |
| holdout/holdout | `HCTX-00207` | `HCTX-00255` | 1.000 | The patient presents with Increased circulating … |
| holdout/holdout | `HCTX-00155` | `HCTX-00251` | 1.000 | The patient presents with Tall stature. Possible… |
| holdout/holdout | `HCTX-00155` | `HCTX-00203` | 1.000 | The patient presents with Tall stature. Possible… |
| holdout/holdout | `HCTX-00185` | `HCTX-00233` | 1.000 | The patient presents with Increased body weight.… |
| holdout/holdout | `HCTX-00203` | `HCTX-00251` | 1.000 | The patient presents with Tall stature. Possible… |
| holdout/holdout | `HCTX-00128` | `HCTX-00144` | 1.000 | 患者，23岁，因视网膜营养不良就诊。既往史：
视锥-视杆细胞营养不良、肥胖、儿童期向心性肥胖。查… |
| holdout/holdout | `HCTX-00164` | `HCTX-00212` | 1.000 | The patient presents with Dementia. The patient … |

### 5.1 留出集内部的重复结构（重要）

- 260 条留出语料只有 **186** 种不同的规范化文本（74 条是重复副本）。
- 按 Jaccard ≥ 0.80 连通分量合并后只剩 **64** 个簇，最大簇 10 条，单例簇 0 个。
- 簇大小分布：`{"2": 34, "3": 14, "9": 10, "10": 6}`。

这意味着：**1,618 个提及并不是 1,618 个独立观测**。按提及数计算的置信区间会偏窄，留出集上的准确率应理解为"若干句型的加权平均"，而不是 260 位独立患者的表现。项目在正文中只报告点估计与混淆矩阵，未声称临床置信区间；这一点现在显式写出。


## 6. 260 条留出语料到底有多独立

| 维度 | 结果 |
| --- | --- |
| 与 train/dev/test 共享患者 | 0 |
| 与 train/dev/test 精确重复文本 | 0 |
| 与 train/dev/test 骨架碰撞 | 0 |
| 共享疾病 | 16/16 |
| 与 train/dev/test 近重复对 | 0 |
| 留出集内部近重复对 | 706（64 个簇） |
| 中文表型表面形式 Jaccard | 0.417 （共享 91 个表面形式） |
| 英文表型表面形式 Jaccard | 0.457 （共享 100 个表面形式） |

**共享的生成机制**：同一个 `CaseBuilder`（跨度与标签由构造过程直接产生，不是人工标注）、同一组 16 种疾病（同一份 HPO 注释）、同一份中文表型词表、同一套线索词家族。
**真正的差异**：随机种子、模板族名称与句法布局、每例的表型抽样。

因此这 260 条只能称为"**同生成器的留出合成模板验证**"，不能称为"独立临床验证"或"跨医院泛化"。原评测结果继续保留，措辞必须按此口径。

外部独立评测状态：**BLOCKED**。本机没有具备合法授权、且带上下文状态标注的真实临床语料；`data/external/asq_phi` 是第三方独立数据，但只覆盖 PHI 跨度，不能用于上下文状态评测。若将来获得此类语料，应另建冻结实验，**不得**在现有 260 条上重新调参。

## 7. 结论

- 患者级与精确文本级切分是干净的；近重复在阈值 0.80 下的跨组对数为 0（不含留出集）。
- **但"患者 ID 不重叠"几乎是同义反复**：每条合成记录的 patient_group 都是新生成的，文本完全相同也会得到不同患者号。真正的独立性必须看文本与近重复，而留出集内部有 74 条重复副本、706 对近重复，合并后只有 64 个簇。
- 但模板族 × 复杂度 × 疾病只有 238 个格子，test 与 train 的格子复用率很高，**不能据此声称泛化**。
- 疾病名入正文、疾病 ID 入金标，是任务设计层面的捷径，应在下游训练/评测中显式处理。
- 留出集共享生成机制，只能支持"作用域机制在未见句式上有效"，不能支持任何临床结论。

## 8. 复现

```bash
python -m scripts.audit_split_relations
```
