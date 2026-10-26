# MIMIC历史数据来源修复：222/64/545与85/40/21

日期：2026-10-25。**第二阶段已定位两条来源，并由官方CSV重放确认历史222/64/545。第一阶段“现存源无法定位”的结论需要据此更正；第一阶段原报告保留不覆盖。**

## 结论与差异原因

两个目录都使用 `public_clinical_structured.jsonl` 这个文件名，但其来源和范围不同：

| 衍生路径 | 来源 | 记录/不同就诊ID | 不同subject ID | 诊断关联 | 有诊断记录 |
|---|---|---:|---:|---:|---:|
| `MedDataLab/reports/full_public/` | 完整公开MIMIC-IV-ED Demo v2.2的triage、diagnosis表 | 222 / 222 | 64 | 545 | 221 |
| `MedDataLab/reports/public_demo/` | 离线手工摘录的85条triage及28条diagnosis输入 | 85 / 85 | 40 | 21 | 13 |

预览的28条diagnosis输入只有21条能关联所选triage；其局部诊断覆盖率不能解释为医院编码缺失率。公开数据库的100名患者也不能直接当作ED triage中的患者数；此ED表实际关联64个subject。

第一阶段使用默认 `rg --files` 盘点时遵守了上游 `.gitignore`。其中 `reports/full_public/` 被忽略，导致只检查了85条预览路径。第二阶段对明确命名路径、忽略文件及ZIP成员重新核验，发现完整222条衍生文件不仅在历史ZIP中，当前磁盘上也存在。该审计方法缺口已记录，不能把第一阶段未找到来源误解为数据不存在或历史数字被造假。

## 指纹与历史版本证据

| 对象 | 字节数 | SHA256 |
|---|---:|---|
| full_public衍生JSONL | 203,719 | `9ae5aa3552bb9509707e30b9c62ea4a5abe44d930a4f18f6b8401a10985e3530` |
| public_demo预览JSONL | 59,923 | `8b7e245ab1525c3fc1b15e2f2672b76c36caaf77e80ca04c1a7d0ff0df376d21` |
| 历史ClinDataForge聚合报告 | 1,609 | `6dc18924e5ea1eebac14787b0ff7dfcf66d5e6a99bcb81a9360be1e0d2a9affb` |

六个现存MedDataLab目录均有这两份衍生文件，共12份；同类型文件指纹一致。七个顶层历史ZIP（V2.9、V2.11.1、V2.12、V2.15、V2.19、交付包及Codex交接包）均包含相同指纹的full_public和preview。每个ZIP的完整指纹、成员路径及聚合计数见 [provenance_trace.json](../reports/phase2_mimic_provenance/provenance_trace.json)。四个上游转换/下载脚本的各归档指纹另见 [archive_code_versions.json](../reports/phase2_mimic_provenance/archive_code_versions.json)。父工作目录Git没有提交历史，因此不声称恢复了某个未知历史commit。

## 上游转换链与官方重放

已阅读并指纹标识以下现存上游源码：

1. `scripts/fetch_public_datasets.py` 指向固定公开PhysioNet Demo目录，按 `SHA256SUMS.txt` 验证下载；未申请受限MIMIC全文。
2. `run_full_public_data.py` 读取 `data/external/mimic_iv_ed_demo_2_2/ed/{triage,diagnosis}.csv.gz`，调用 `src/meddatalab/realworld.py:analyze()`，输出到 `reports/full_public/`。
3. `run_public_demo.py` 读取 `data/public_preview/*verified_preview.csv`，调用同一转换器，输出到 `reports/public_demo/`。

本次从[PhysioNet公开文件目录](https://physionet.org/files/mimic-iv-ed-demo/2.2/)下载固定triage和diagnosis文件到临时目录，校验[官方SHA256SUMS](https://physionet.org/files/mimic-iv-ed-demo/2.2/SHA256SUMS.txt)后，仅在内存重放已审阅的上游转换逻辑。原始下载未留在项目、未上传给外部服务，也未打印或分发行级记录。

| 官方文件 | 下载字节数 | SHA256（与官方SUMS一致） |
|---|---:|---|
| ed/triage.csv.gz | 5,489 | `086dadcb49adc5f24bdda0e342ec9cf0fbcb2e9595516c5c101d408434e1e09b` |
| ed/diagnosis.csv.gz | 8,992 | `3a2d6bfb402d5783f1950f4729dd378e825475719f0535fb6b0209c2bc0744e9` |

重放结果为222条triage、64个subject、545条diagnosis、221条triage有诊断。以原转换器的JSON键顺序及LF序列化后，**字节级SHA256与历史full_public衍生文件完全相同**。已有preview两个CSV重放也与其历史衍生文件逐字节相同。

现有审计器对恢复full_public重算后，历史 `reports/public_demo_aggregate.json` 的全部数值字段都能复现（包括缺失统计、温度换算和标志计数）；差异列表为空。恢复聚合见 [recovered_full_public_aggregate.json](../reports/phase2_mimic_provenance/recovered_full_public_aggregate.json)。这支持引用222/64/545作为**公开Demo衍生表质量审计规模**，不支持声称222份真实自由文本病历脱敏、PHI模型验收或医院生产效果。

## 来源与许可

来源：Johnson等，MIMIC-IV-ED Demo v2.2，PhysioNet，DOI [10.13026/jzz5-vs76](https://doi.org/10.13026/jzz5-vs76)。[官方项目页](https://physionet.org/content/mimic-iv-ed-demo/2.2/)与[官方LICENSE](https://physionet.org/files/mimic-iv-ed-demo/2.2/LICENSE.txt)为来源引用。项目页本次浏览接口超时，但原始文件及许可经HTTPS成功获取，并与官方校验表匹配。

官方许可文本为ODC Open Database License（ODbL）。本次保留的[许可快照](../reports/phase2_mimic_provenance/official_LICENSE.txt)SHA256为 `bcdfcd4f31c790e30fb645dc36414907172405897adff329ad379eed85d12017`；许可不是本项目MIT代码许可证。数据库署名、衍生数据库及公开使用的义务应依原文执行；当前只保存聚合和来源证据，不重新分发行级数据。公开且已去标识化不代表能逆向识别患者，也不能用这些表验证自由文本PHI召回。

## 可复现命令与限制

从ClinDataForge根目录运行，目标目录必须是新路径：

```powershell
# 仅本机已有衍生文件、预览CSV和历史ZIP盘点/聚合
python -m scripts.trace_mimic_provenance --out reports/my_mimic_trace

# 额外执行官方公开小文件校验及临时内存重放
python -m scripts.trace_mimic_provenance --out reports/my_mimic_trace_official --verify-official
```

脚本只输出固定聚合字段、哈希与来源路径，不输出患者ID、主诉、诊断文本或病历行。网络不可用时会记录official状态失败，不把本地衍生核验冒充官方原始重放。现存上游路径和ZIP是本次复现的外部依赖，不能将ClinDataForge单独复制后仍声称这些源文件已经随项目提供。

原异常flag/主诉tag仍是程序筛查，不是临床专家金标。该来源修复与第二阶段冻结PHI算法对照是两个独立证据链；MIMIC Demo衍生表不能混入PHI合成测试集冒充真实患者泛化评测。
