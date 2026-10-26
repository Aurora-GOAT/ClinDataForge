# 罕见病知识约束合成数据：样本与溯源（中文）

> 本文件由 `python -m scripts.showcase_samples` 自动生成，请勿手工编辑。
> 所有病例均为**程序化生成的合成文本**，患者编号、姓名、日期、病历号均为虚构占位，
> 不对应任何真实个体。文本中的临床描述只用于检验数据流水线，**不构成医学建议**。

## 0. 语料概况

- 病例总数：**2400**
- 实体总数：**22156**
- 语言分布：中文 1639 / 英文 761
- 含虚构 PHI 的病例：**1299**（占比 54.1%）
- 覆盖罕见病：**16** 种（人工核验后进入知识库）

四类上下文状态的约定：

| 状态 | 含义 | 生成器表达方式（示例） |
| --- | --- | --- |
| `affirmed` | 现症，本次就诊确认存在 | 「查体发现低血糖」 |
| `suspected` | 疑似，尚未确诊 | 「另疑有耳廓后旋」「尚需评估有无…」 |
| `history` | 既往史，曾经发生但当前不确认 | 「既往曾有体重增加」 |
| `negated` | 明确否定 | 「无吸吮无力」「否认家族成员类似表现」 |

## 1. 罕见病知识库与 HPO 溯源

知识库由 HPO 官方发布文件离线构建，每个表型都保留 HPO ID、证据代码与文献来源。
生成器只能使用知识库中登记的表型，验证器在**不读取生成器内部状态**的前提下独立比对，
因此“表型是否属于该病”这一约束是可追溯、可反驳的。

- 注释文件：`phenotype.hpoa`（版本 2026-09-02）
- 下载地址：https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa
- 文件 SHA256：`e89aa39c8f97bf5a52c5d160f9250a603681d630ade8ec2679d84ac5aece1f72`
- 快照内疾病数：12867，表型词条数：20482

本项目只使用其中**人工核验过的 16 种罕见病**作为生成目标，每种疾病贡献约 150 条病例：

| # | 疾病（英文） | 中文名 | 编码 | KB 可用表型数 | 起病 HPO | 病例数 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Cockayne syndrome | Cockayne综合征 | `ORPHA:191` | 118 | — | 151 |
| 2 | Trichothiodystrophy | 毛发硫营养不良 | `ORPHA:33364` | 91 | — | 151 |
| 3 | Leigh syndrome | Leigh综合征 | `ORPHA:506` | 98 | — | 151 |
| 4 | MELAS | MELAS综合征 | `ORPHA:550` | 87 | — | 151 |
| 5 | Atypical Werner syndrome | 非典型Werner综合征 | `ORPHA:79474` | 90 | — | 151 |
| 6 | Fanconi anemia | Fanconi贫血 | `ORPHA:84` | 106 | — | 151 |
| 7 | Tyrosinemia, type I | Ⅰ型酪氨酸血症 | `OMIM:276700` | 38 | — | 150 |
| 8 | Holoprosencephaly | 前脑无裂畸形 | `ORPHA:2162` | 93 | — | 150 |
| 9 | Gaucher disease | 戈谢病 | `ORPHA:355` | 92 | — | 150 |
| 10 | Oculocerebrorenal syndrome of Lowe | Lowe眼脑肾综合征 | `ORPHA:534` | 119 | — | 150 |
| 11 | PMM2-CDG | PMM2先天性糖基化障碍 | `ORPHA:79318` | 86 | — | 150 |
| 12 | Turner syndrome | Turner综合征 | `ORPHA:881` | 115 | — | 150 |
| 13 | Bardet-Biedl syndrome | Bardet-Biedl综合征 | `ORPHA:110` | 95 | — | 149 |
| 14 | Beckwith-Wiedemann syndrome | Beckwith-Wiedemann综合征 | `ORPHA:116` | 85 | — | 149 |
| 15 | Alström syndrome | Alström综合征 | `ORPHA:64` | 117 | — | 149 |
| 16 | Sotos syndrome | Sotos综合征 | `OMIM:117550` | 122 | `HP:0003577` | 147 |

## 2. 中文门诊病例：四类状态齐全

这条样本同时含现症、疑似、既往、否定四类表达，是上下文判定最容易出错的形态：
同一段文字里“有”和“无”交替出现，且既往史线索词与表型之间隔着逗号与分号。

> 提醒：本章及后续案例都是**挑选**出来的展示样本，不是随机抽样，不能当作整体指标。

- 病例编号：`SYN-00014`（患者组 `PAT-SYN-00014`，就诊组 `ENC-SYN-00014`）
- 疾病：MELAS综合征（`ORPHA:550`），模板族 `outpatient`，复杂度 `standard`
- 起病 HPO：—（知识库未登记起病年龄）

### 原始病历文本

```text
患儿，男，4岁，因“失语伴脑电图异常”1个月就诊。病程中可见卒中样发作。此后逐渐出现血乳酸升高。目前仍有肌无力；查体发现蛛网膜下腔增宽；尚需评估有无癫痫发作；尚需评估有无偏头痛。查体疑似乳酸酸中毒；尚需评估有无肌肉破碎红纤维；既往有精神病性症状史。系统回顾：否认肌组织线粒体异常等表现。辅助检查：空腹血糖 5.7 mmol/L，大致正常。家族史：家属叙述不详。诊断思路：MELAS综合征待排。
```

### 带上下文标注的版本

标注记号：`[+]` 现症、`[?]` 疑似、`[~]` 既往、`[-]` 否定。

```text
患儿，男，4岁，因“失语[+]伴脑电图异常[+]”1个月就诊。病程中可见卒中样发作[+]。此后逐渐出现血乳酸升高[+]。目前仍有肌无力[+]；查体发现蛛网膜下腔增宽[+]；尚需评估有无癫痫发作[?]；尚需评估有无偏头痛[?]。查体疑似乳酸酸中毒[?]；尚需评估有无肌肉破碎红纤维[?]；既往有精神病性症状[~]史。系统回顾：否认肌组织线粒体异常[-]等表现。辅助检查：空腹血糖 5.7 mmol/L，大致正常。家族史：家属叙述不详。诊断思路：MELAS综合征待排。
```

### 金标表型与溯源

| 实体（原文） | 上下文状态 | HPO ID | 证据代码 | 文献 |
| --- | --- | --- | --- | --- |
| 失语 | 现症（affirmed） | `HP:0002381` | TAS | ORPHA:550 |
| 脑电图异常 | 现症（affirmed） | `HP:0002353` | TAS | ORPHA:550 |
| 卒中样发作 | 现症（affirmed） | `HP:0002401` | TAS | ORPHA:550 |
| 血乳酸升高 | 现症（affirmed） | `HP:0002151` | TAS | ORPHA:550 |
| 肌无力 | 现症（affirmed） | `HP:0001324` | TAS | ORPHA:550 |
| 蛛网膜下腔增宽 | 现症（affirmed） | `HP:0012766` | TAS | ORPHA:550 |
| 癫痫发作 | 疑似（suspected） | `HP:0001250` | TAS | ORPHA:550 |
| 偏头痛 | 疑似（suspected） | `HP:0002076` | TAS | ORPHA:550 |
| 乳酸酸中毒 | 疑似（suspected） | `HP:0003128` | TAS | ORPHA:550 |
| 肌肉破碎红纤维 | 疑似（suspected） | `HP:0003200` | TAS | ORPHA:550 |
| 精神病性症状 | 既往（history） | `HP:0000709` | TAS | ORPHA:550 |
| 肌组织线粒体异常 | 否定（negated） | `HP:0008316` | TAS | ORPHA:550 |

### 流水线抽取结果

| 实体（流水线抽取） | 状态 | HPO ID | 对齐金标 |
| --- | --- | --- | --- |
| 失语 | 现症（affirmed） | `HP:0002381` | 状态一致、HPO 一致 |
| 脑电图异常 | 现症（affirmed） | `HP:0002353` | 状态一致、HPO 一致 |
| 卒中样发作 | 现症（affirmed） | `HP:0002401` | 状态一致、HPO 一致 |
| 血乳酸升高 | 现症（affirmed） | `HP:0002151` | 状态一致、HPO 一致 |
| 肌无力 | 现症（affirmed） | `HP:0001324` | 状态一致、HPO 一致 |
| 蛛网膜下腔增宽 | 现症（affirmed） | `HP:0012766` | 状态一致、HPO 一致 |
| 癫痫发作 | 疑似（suspected） | `HP:0001250` | 状态一致、HPO 一致 |
| 偏头痛 | 疑似（suspected） | `HP:0002076` | 状态一致、HPO 一致 |
| 乳酸酸中毒 | 疑似（suspected） | `HP:0003128` | 状态一致、HPO 一致 |
| 肌肉破碎红纤维 | 疑似（suspected） | `HP:0003200` | 状态一致、HPO 一致 |
| 精神病性症状 | 既往（history） | `HP:0000709` | 状态一致、HPO 一致 |
| 肌组织线粒体异常 | 否定（negated） | `HP:0008316` | 状态一致、HPO 一致 |

## 3. 英文病例：跨语言一致性检查

英文模板的难点在缩写与逗号列表：`no fever, rash, or vomiting` 里的三个表型
共享同一个否定触发词，作用域必须延伸到列表末尾而不是第一个逗号。
这条样本同时覆盖现症、疑似与否定三类，可用来对照中英判定逻辑是否一致。

- 病例编号：`SYN-00005`（患者组 `PAT-SYN-00005`，就诊组 `ENC-SYN-00005`）
- 疾病：MELAS综合征（`ORPHA:550`），模板族 `consult`，复杂度 `standard`
- 起病 HPO：—（知识库未登记起病年龄）

### 原始病历文本

```text
The patient is a 33-year-old man presenting with Migraine and EEG abnormality for 3 months. Review of systems is notable for Aphasia. Examination shows Lactic acidosis. Review of systems is notable for Ragged-red muscle fibers. Review of systems is notable for Sensorineural hearing impairment. There is suspicion of Dementia. There is suspicion of Seizure, to be confirmed. Past history: previously noted Increased circulating lactate concentration, and previously noted Abnormal mitochondria in muscle tissue, and a history of Aplasia/Hypoplasia of the cerebral white matter, and a history of Widened cerebral subarachnoid space, and previously noted Visual loss. No reported Psychosis, Muscle weakness. Family history not available. Impression: findings raise suspicion for MELAS, to be confirmed.
```

### 带上下文标注的版本

标注记号：`[+]` 现症、`[?]` 疑似、`[~]` 既往、`[-]` 否定。

```text
The patient is a 33-year-old man presenting with Migraine[+] and EEG abnormality[+] for 3 months. Review of systems is notable for Aphasia[+]. Examination shows Lactic acidosis[+]. Review of systems is notable for Ragged-red muscle fibers[+]. Review of systems is notable for Sensorineural hearing impairment[+]. There is suspicion of Dementia[?]. There is suspicion of Seizure[?], to be confirmed. Past history: previously noted Increased circulating lactate concentration[~], and previously noted Abnormal mitochondria in muscle tissue[~], and a history of Aplasia/Hypoplasia of the cerebral white matter[~], and a history of Widened cerebral subarachnoid space[~], and previously noted Visual loss[~]. No reported Psychosis[-], Muscle weakness[-]. Family history not available. Impression: findings raise suspicion for MELAS, to be confirmed.
```

### 金标表型与溯源

| 实体（原文） | 上下文状态 | HPO ID | 证据代码 | 文献 |
| --- | --- | --- | --- | --- |
| Migraine | 现症（affirmed） | `HP:0002076` | TAS | ORPHA:550 |
| EEG abnormality | 现症（affirmed） | `HP:0002353` | TAS | ORPHA:550 |
| Aphasia | 现症（affirmed） | `HP:0002381` | TAS | ORPHA:550 |
| Lactic acidosis | 现症（affirmed） | `HP:0003128` | TAS | ORPHA:550 |
| Ragged-red muscle fibers | 现症（affirmed） | `HP:0003200` | TAS | ORPHA:550 |
| Sensorineural hearing impairment | 现症（affirmed） | `HP:0000407` | TAS | ORPHA:550 |
| Dementia | 疑似（suspected） | `HP:0000726` | TAS | ORPHA:550 |
| Seizure | 疑似（suspected） | `HP:0001250` | TAS | ORPHA:550 |
| Increased circulating lactate concentration | 既往（history） | `HP:0002151` | TAS | ORPHA:550 |
| Abnormal mitochondria in muscle tissue | 既往（history） | `HP:0008316` | TAS | ORPHA:550 |
| Aplasia/Hypoplasia of the cerebral white matter | 既往（history） | `HP:0012429` | TAS | ORPHA:550 |
| Widened cerebral subarachnoid space | 既往（history） | `HP:0012766` | TAS | ORPHA:550 |
| Visual loss | 既往（history） | `HP:0000572` | TAS | ORPHA:550 |
| Psychosis | 否定（negated） | `HP:0000709` | TAS | ORPHA:550 |
| Muscle weakness | 否定（negated） | `HP:0001324` | TAS | ORPHA:550 |

### 流水线抽取结果

| 实体（流水线抽取） | 状态 | HPO ID | 对齐金标 |
| --- | --- | --- | --- |
| Migraine | 现症（affirmed） | `HP:0002076` | 状态一致、HPO 一致 |
| EEG abnormality | 现症（affirmed） | `HP:0002353` | 状态一致、HPO 一致 |
| Aphasia | 现症（affirmed） | `HP:0002381` | 状态一致、HPO 一致 |
| Lactic acidosis | 现症（affirmed） | `HP:0003128` | 状态一致、HPO 一致 |
| Ragged-red muscle fibers | 现症（affirmed） | `HP:0003200` | 状态一致、HPO 一致 |
| Sensorineural hearing impairment | 现症（affirmed） | `HP:0000407` | 状态一致、HPO 一致 |
| Dementia | 疑似（suspected） | `HP:0000726` | 状态一致、HPO 一致 |
| Seizure | 疑似（suspected） | `HP:0001250` | 状态一致、HPO 一致 |
| Increased circulating lactate concentration | 既往（history） | `HP:0002151` | 状态一致、HPO 一致 |
| Abnormal mitochondria in muscle tissue | 既往（history） | `HP:0008316` | 状态一致、HPO 一致 |
| Aplasia/Hypoplasia of the cerebral white matter | 既往（history） | `HP:0012429` | 状态一致、HPO 一致 |
| Widened cerebral subarachnoid space | 既往（history） | `HP:0012766` | 状态一致、HPO 一致 |
| Visual loss | 既往（history） | `HP:0000572` | 状态一致、HPO 一致 |
| Psychosis | 否定（negated） | `HP:0000709` | 状态一致、HPO 一致 |
| Muscle weakness | 否定（negated） | `HP:0001324` | 状态一致、HPO 一致 |

## 4. PHI 脱敏示例（虚构占位值）

生成器会在部分病例中注入**虚构**的直接标识符，用来检验 PHI 检测与掩码链路。
下列值全部由模板生成（如 `SYN-xxxx`、虚构姓名与日期），不对应任何真实个体；
把它们写进文档不会泄露隐私，但也不构成任何隐私保护证明——真实患者数据从未进入本项目。

- 病例编号：`SYN-00002`

### 脱敏前

```text
姓名：沈铭泽｜性别：女｜年龄：52岁｜病历号：R4930263｜联系电话：1315739767｜就诊日期：2026-10-16
主诉：因“色素性视网膜病变伴进行性感音神经性听力受损”1个月入院。
现病史：查体发现脑钙化；目前仍有出生后生长迟缓；病程中可见皮质下白质斑片状脱髓鞘；目前仍有小脑萎缩；尚需评估有无行为异常。另疑有生长迟缓；查体疑似重度身材矮小。

入院后系统回顾：否认脑髓鞘形成障碍、腹泻病史。家族史：无特殊。诊断思路：Cockayne综合征可能，建议完善相关检查。
```

### 脱敏后（流水线输出）

```text
姓名：[NAME]｜性别：女｜年龄：52岁｜病历号：[PATIENT_ID]｜联系电话：[PHONE]｜就诊日期：[DATE]
主诉：因“色素性视网膜病变伴进行性感音神经性听力受损”1个月入院。
现病史：查体发现脑钙化；目前仍有出生后生长迟缓；病程中可见皮质下白质斑片状脱髓鞘；目前仍有小脑萎缩；尚需评估有无行为异常。另疑有生长迟缓；查体疑似重度身材矮小。

入院后系统回顾：否认脑髓鞘形成障碍、腹泻病史。家族史：无特殊。诊断思路：[NAME]综合征可能，建议完善相关检查。
```

流水线报告的 PHI 跨度数量：**5**

### 被替换的片段

| # | 类型 | 原文片段 | 字符区间 | 掩码占位符 | 复核意见 |
| --- | --- | --- | --- | --- | --- |
| 1 | NAME | `沈铭*` | [3, 6) | `[NAME]` |  |
| 2 | PATIENT_ID | `R4******` | [23, 31) | `[PATIENT_ID]` |  |
| 3 | PHONE | `13********` | [37, 47) | `[PHONE]` |  |
| 4 | DATE | `20********` | [53, 63) | `[DATE]` |  |
| 5 | NAME | `Co******` | [216, 224) | `[NAME]` | **误报**：这是疾病名而非人名 |

上面标了误报的那一条是真实的代价：PII 模型把首字母大写的英文疾病名判成人名。
掩码偏保守的方向对隐私是安全的，但会削弱脱敏文本的可用性；这类误报已经计入第二阶段 PHI 评测的 FP（D 方法 precision 0.7566）。

## 5. 上下文误判修复个案

以下个案均为金标 `history`：修复前被判成 `affirmed`（把既往史当成现症），
修复后恢复为 `history`。右侧展示触发词到实体的实际文本窗口，
可以直接看出旧版固定字符窗口截断在哪里。

### 个案 1：`SYN-00015` — 肌肉破碎红纤维（`HP:0003200`）

- 修复前：`affirmed` → 修复后：`history`（金标 `history`）

```text
…肌组织线粒体异常；上述表现时轻时重，家属为进一步诊治来诊。既往史：有肌肉破碎红纤维。系统回顾：否认精神病性症状、脑电图异常等表现。家族史：否认家族成员…
```

### 个案 2：`SYN-00018` — 失明（`HP:0000618`）

- 修复前：`affirmed` → 修复后：`history`（金标 `history`）

```text
…力丧失。既往史：曾有视锥-视杆细胞营养不良，并有视网膜营养不良，并有失明史。否认视盘苍白、皮疹病史。家族史：无特殊。初步诊断：考虑Alstr…
```

### 个案 3：`SYN-00034` — 吸吮无力（`HP:0002033`）

- 修复前：`affirmed` → 修复后：`history`（金标 `history`）

```text
…现听力受损；目前仍有体重增加。既往史：曾有口吃，并有胼胝体变薄，并有吸吮无力，并有哭声嘶哑。系统回顾：否认低位耳。辅助检查：ALT 28 U/L…
```

## 6. 效力边界（必读）

**关于上面这些案例**：它们是按“状态齐全 / 含 PHI / 中英对照”的目的**挑选**出来的，
用于让人肉眼检查数据形态与抽取链路，**不是随机抽样，也不能代表整体指标**。
整体指标请看 `reports/phase4_pipeline_eval/`（九段流水线在 2355 条接受样本上的统计）
与 `reports/phase4_context/report_tables.md`（四类上下文判定）。

| 层级 | 本项目做到什么 | 不能声称什么 |
| --- | --- | --- |
| 模板内自检 | 表型 F1、上下文准确率等在生成模板内部统计 | 不等于独立评测，模板与金标同源 |
| 第三方合成数据独立评测 | ASQ-PHI v1（MIT）1,051 条英文第三方合成数据上评测 PHI | 不代表真实病历分布 |
| 真实临床数据验证 | **未进行**，无授权数据 | 不能声称临床可用 |
| 模型训练 | **未进行**，仅导出候选数据 | 不能声称任何训练收益 |

复现命令见 `README.md` 与 `docs/CONTEXT_AND_PERF_CN.md`。
