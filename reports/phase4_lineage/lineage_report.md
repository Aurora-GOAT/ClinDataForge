# 疾病数据血缘核验报告（as-run）

- 版本：`lineage-1.0.0`，生成时间 2026-10-26T17:57:11Z
- 语料：`data/phase3_synth/gen/notes.jsonl`（2,400 条）
- 事实来源：`clinforge/synthgen.py::CURATED_DISEASES`（16 种）

## 1. 结论先说

- **`disease_selection.json` 与实际生成不一致，而且这是可解释的历史遗留**：两者只有 **3/16** 个疾病 ID 重合。
- 该文件由早期版本的算法选择器写出；用当前 `select_rare_diseases()` 以同参数重算，能精确复现文件里的 16 个 ID，说明它是真实产物而非损坏。
- 生成器后来改用人工核验的 16 病清单，而 `build_hpo_kb.py` 设计为**拒绝覆盖**已存在的选择文件，于是旧文件被留在原处，文档里却仍指向它。
- 本报告不修改、不删除该历史文件；新增的 `data/phase4_lineage/` 才是"实际运行"口径。

## 2. 历史文件 vs 实际使用

| | 历史 `disease_selection.json` | 实际 `CURATED_DISEASES` |
| --- | --- | --- |
| 疾病数 | 16 | 16 |
| 选择规则 | 算法排序 + 种子抽样 | 人工核验清单（Curated rare-disease demo se…） |
| 与语料一致 | 否（仅 3 个重合） | 是（2400/2400） |
| 是否被本报告覆盖 | 否 | 否（只新增清单） |

历史文件中的 16 个 ID：

```text
OMIM:117550, OMIM:124000, OMIM:276700, OMIM:609069, OMIM:613658, OMIM:615453, OMIM:615471, OMIM:616483, OMIM:619991, OMIM:620887, OMIM:621184, ORPHA:264580, ORPHA:348, ORPHA:39812, ORPHA:506, ORPHA:618891
```

实际使用的 16 个 ID：

```text
ORPHA:64, ORPHA:84, ORPHA:506, ORPHA:110, ORPHA:355, ORPHA:550, ORPHA:116, OMIM:276700, OMIM:117550, ORPHA:191, ORPHA:79318, ORPHA:881, ORPHA:2162, ORPHA:79474, ORPHA:534, ORPHA:33364
```

## 3. 实际使用的疾病清单

| # | 疾病 ID | 英文名 | 中文名 | 来源 | HPO 注释数 | 生成记录 | 中文/英文 | 含 PHI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ORPHA:64` | Alström syndrome | Alström综合征 | ORPHA | 117 | 149 | 107/42 | 83 |
| 2 | `ORPHA:84` | Fanconi anemia | Fanconi贫血 | ORPHA | 106 | 151 | 98/53 | 77 |
| 3 | `ORPHA:506` | Leigh syndrome | Leigh综合征 | ORPHA | 98 | 151 | 105/46 | 73 |
| 4 | `ORPHA:110` | Bardet-Biedl syndrome | Bardet-Biedl综合征 | ORPHA | 95 | 149 | 114/35 | 76 |
| 5 | `ORPHA:355` | Gaucher disease | 戈谢病 | ORPHA | 92 | 150 | 96/54 | 70 |
| 6 | `ORPHA:550` | MELAS | MELAS综合征 | ORPHA | 87 | 151 | 96/55 | 90 |
| 7 | `ORPHA:116` | Beckwith-Wiedemann syndrome | Beckwith-Wiedemann综合征 | ORPHA | 85 | 149 | 99/50 | 72 |
| 8 | `OMIM:276700` | Tyrosinemia, type I | Ⅰ型酪氨酸血症 | OMIM | 38 | 150 | 103/47 | 90 |
| 9 | `OMIM:117550` | Sotos syndrome | Sotos综合征 | OMIM | 122 | 147 | 99/48 | 74 |
| 10 | `ORPHA:191` | Cockayne syndrome | Cockayne综合征 | ORPHA | 118 | 151 | 102/49 | 87 |
| 11 | `ORPHA:79318` | PMM2-CDG | PMM2先天性糖基化障碍 | ORPHA | 86 | 150 | 105/45 | 84 |
| 12 | `ORPHA:881` | Turner syndrome | Turner综合征 | ORPHA | 115 | 150 | 107/43 | 92 |
| 13 | `ORPHA:2162` | Holoprosencephaly | 前脑无裂畸形 | ORPHA | 93 | 150 | 94/56 | 83 |
| 14 | `ORPHA:79474` | Atypical Werner syndrome | 非典型Werner综合征 | ORPHA | 90 | 151 | 107/44 | 79 |
| 15 | `ORPHA:534` | Oculocerebrorenal syndrome of Lowe | Lowe眼脑肾综合征 | ORPHA | 119 | 150 | 100/50 | 88 |
| 16 | `ORPHA:33364` | Trichothiodystrophy | 毛发硫营养不良 | ORPHA | 91 | 151 | 107/44 | 81 |

## 4. HPO 溯源链

| 文件 | 版本 | SHA256 | 来源 |
| --- | --- | --- | --- |
| `hp.obo` | hp/releases/2026-09-01 | `93dace952fcb3ec4728818857f6ba76bc2d5312f4d83266519b8694b8e798f22` | https://purl.obolibrary.org/obo/hp.obo |
| `phenotype.hpoa` | 2026-09-02 | `e89aa39c8f97bf5a52c5d160f9250a603681d630ade8ec2679d84ac5aece1f72` | https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa |

快照统计：20,482 个 HP 术语、12,867 个疾病注释、丢弃 0 条过时/未知注释。
许可：HPO 内容未修改，版本与 SHA256 随每条记录写入 `hpo_provenance`。

## 5. 逐条核验

| 检查项 | 通过 | 总数 / 说明 |
| --- | --- | --- |
| 记录数 | 2,400 | 2,400 |
| 疾病 ID 属于 CURATED_DISEASES | 2,400 | 2,400 |
| 疾病英文名与快照一致 | 2,400 | 2,400 |
| 疾病中文名与人工词表一致 | 2,400 | 2,400 |
| 记录级 HPO 溯源 = 快照溯源 | 2,400 | 2,400 |
| 表型 HP 编码属于该病注释集 | 22,156 | 22,156 个表型实体 |
| 通用症状否定白名单 | 0 | 非疾病注释、按设计允许 |
| 表型带证据码与文献来源 | 22,156 | 22,156 |
| 字符偏移可回切原文 | 36,713 | 全部实体 |
| `spec` 状态数与实际实体一致 | 2,400 | 2,400 |

未通过项：

```json
{}
```

## 6. 下游覆盖

| 环节 | 记录数 |
| --- | --- |
| 生成语料 | 2,400 |
| 进入九段流水线 | 2,400 |
| 接受（`structured.jsonl`） | 2,355 |
| 隔离（`quarantine.jsonl`） | 45 |
| 导出 SFT 候选 | 2,355 （train 1921 / dev 230 / test 204） |

## 7. 这份清单能证明什么、不能证明什么

- 能证明：every generated record resolves to one curated disease id, and every phenotype entity resolves to that disease's HPO annotation set or a documented generic-symptom allowlist; file hashes pin the exact inputs。
- 不能证明：that the HPO annotations are clinically complete, that the Chinese disease names are official translations, or that the synthetic cases resemble any real hospital population。

## 8. 复现

```bash
python -m scripts.build_disease_lineage            # 写一次，拒绝覆盖
python -m scripts.build_disease_lineage --force    # 仅同版本重写
```

产物：

- `data/phase4_lineage/lineage_manifest.json`（含全部输入文件的 SHA256）
- `data/phase4_lineage/record_disease_index.csv`（2,400 行逐条索引）
