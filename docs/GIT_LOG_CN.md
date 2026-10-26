# Git 提交记录（本地仓库，未推送）

> 本文件为**提交记录说明**，不是命令行输出的逐字拷贝。哈希、时间、行数来自 `git log` 与 `git show --stat`。
> 仓库无 remote，**从未推送**到任何公开平台。

## 0. 仓库基本信息

| 项 | 值 |
| --- | --- |
| 仓库路径 | `ClinDataForge_AntHealth_2027/`（独立仓库，不在父目录暂存区内） |
| 当前分支 | `codex/phase1-audit` |
| 远端 | 无（`git remote -v` 为空） |
| 已跟踪文件数 | 336（功能提交 `ee51a56` 时点；本文件加入后为 337） |
| 提交数 | 11 条功能提交（见 §1 表）＋本文件及其后续措辞修正等纯文档提交 |
| 起始快照 | `af8a8f7`（原始交付 v0.1，逐字节保留） |
| 本地提交身份 | `Codex <codex@local.invalid>` —— **占位身份**，推送前必须改成真实身份 |

**推送前必做**：把 `user.name` / `user.email` 改成真实身份（`git config user.name "…"`）。
若已用占位身份推送过，改身份会改写全部历史哈希——所以顺序必须是「先改身份，再推送」，不是反过来。

## 1. 提交时间线

| 哈希 | 时间 | 主题 |
| --- | --- | --- |
| `ee51a56` | 2026-10-27 02:32 | final acceptance: as-run disease lineage, split-relation audit, independent lab standards |
| `cd7b86b` | 2026-10-26 21:56 | phase 4: scope-based context resolver, fp32 PHI throughput, data-quality audit |
| `0f649d7` | 2026-10-26 05:13 | feat(P1/P2): medical structuring pipeline run + evaluation + training candidates |
| `b734058` | 2026-10-26 03:48 | docs(P2/P4): benchmark interface, pipeline fixes, interview and presentation materials |
| `2cbaed4` | 2026-10-26 02:04 | feat(P0): knowledge-constrained rare-disease synthesis with HPO grounding |
| `16f3b4e` | 2026-10-26 00:59 | fix: report D-B and D-C bootstrap comparisons actually produced by the runner |
| `3b2f9bb` | 2026-10-26 00:58 | fix: drop empty bootstrap table row from generated report |
| `4f0336f` | 2026-10-26 00:57 | feat: phase-2 independent PHI benchmark and four-method comparison |
| `dde7530` | 2026-10-25 23:27 | feat: add optional Presidio baseline probe with explicit dependency gaps |
| `98e794d` | 2026-10-25 22:56 | fix: complete phase-one audit and withhold unverified text exports |
| `af8a8f7` | 2026-10-25 22:40 | chore: preserve original ClinDataForge v0.1 delivery |

上表是全部**功能提交**。`ee51a56` 之后只有纯文档提交（新增本文件、修正演示页「留出集 → 同生成器留出集」措辞），不改变上表任何一项内容，也不再改任何数字。

## 2. 各提交做了什么（按阶段）

### 2.1 `af8a8f7` 起始快照
原始 v0.1 交付原样入库，作为后续所有修复的对照基准。**此后任何改动都不覆盖它的内容。**

### 2.2 `98e794d` 第一阶段审计（v0.1.1）
- 复现旧 730 条集五组指标与 60 条压力集计数，算术核算一致。
- 修掉「温度异常注入误改 ALT」的生成器缺陷（6 条正文与金标不一致）。
- 发现历史 MIMIC 222/64/545 无法由现存源复现 → 另存差异，不再把旧数字当成果。
- 默认只导出允许列表元数据，SFT 文本导出 0 条并记录扣留原因。
- 全套 70/70 通过。

### 2.3 `dde7530` Presidio 探针
只加可选本地适配器 + 60 条压力集复现脚本；Presidio 未安装则指标为 `null`，**不以测试替身冒充模型结果**。

### 2.4 `4f0336f` / `3b2f9bb` / `16f3b4e` 第二阶段 PHI 基准
- ASQ-PHI v1（MIT，第三方合成）+ 独立中文模板集，按近重复连通分量划分。
- 四路方法 A/B/C/D 全部本地 CPU 推理；**冻结测试集只跑一次**。
- 两个后续 fix 都关于「报告要如实反映 runner 真实产出的比较」，而不是补数字。

### 2.5 `2cbaed4` / `0f649d7` 第三阶段合成与流水线
- HPO 许可与 SHA256 核验，16 病人工核验集，2,400 条双语病例。
- 独立验证器（不读生成器内部状态）：知识违反 0、检验错误 0。
- 九段流水线跑通，模板内自检与「不等于独立测试」的口径同时写出。
- SFT/偏好候选导出，明确标注**未执行任何训练**。

### 2.6 `cd7b86b` 第四阶段
- `ctxscope-1.1.0`：NegEx/ConText 作用域判定，783 例 `history→affirmed` → 0。
- PHI 门控 fp32 + 4 线程：2,778 → 995 ms/条（2.79×），端到端 1.89×；**输出差异 3 处如实披露，未回改阈值**。
- 数据质量审计（`dq-audit-1.0.0`）：六块独立重算，含偏好标签修复与上下文污染 3.85% → 0.00%。
- 发现 `disease_selection.json` 指向错误，**只在文档标注，不改历史产物**。

### 2.7 `ee51a56` 最终验收（本文件所在提交）
39 个文件、+10,726 / −842 行。四个新增证据链，全部为**追加式**：

| 模块 | 新产物 | 关键结果 |
| --- | --- | --- |
| 疾病血缘 | `data/phase4_lineage/lineage_manifest.json` + `record_disease_index.csv`（2,400 行） | 与遗留清单重合仅 **3/16**，但可被原选择器**精确复现**；2,400/2,400 记录、22,156/22,156 表型、36,713 个偏移回切、六类违规全 0 |
| 切分关系 | `reports/phase4_split_relations/relations.json` | 跨组患者/文本/近重复全 0，骨架碰撞 1 对；但 test 三元组 **99.02%** 已在 train 出现；260 条留出语料只有 **186 种文本 / 64 簇** |
| 簇级 bootstrap | `holdout_bootstrap.json` | v1 acc 0.7021 [0.6337,0.7734] vs v2 0.9778 [0.9451,1.0000]，宏 F1 0.9567 [0.9232,1.0000] |
| 检验常数独立路径 | `clinforge/lab_standards.py` + `reports/phase4_lab_independence/` | 1,277/1,277 复算一致（最大偏差 0.01）；注入错误后共享表 0 检出、独立路径 **26 换算错 + 10 方向错**；金标零修改 |
| 成果包 | `reports/final/metrics_registry.json`（57 项 / 16 个 SHA256）、`experiment_table.md`、`demo/index.html`、5 份中文文档 | 每条指标带 source 指针 + 五级效力标签 |

同提交内修掉两个自己引入的问题：
1. 看板把 `64.39%` 标成「测试集中的比例」，实际分母是 train 侧（1,237/1,921）——标签已改，并在第 6 节显式说明 99.02% 与 64.39% 分母不同。
2. `metrics_registry.json` 里 `experiment_table.md` 的 SHA256 记录的是**上一版**文件（表在登记簿之后生成）——改为两遍写，16 个指纹现已自校验一致。

**测试**：170/170 通过（Python 3.13.12 管理版；`reports/final/test_summary.json`）。

## 3. 如何复核这份记录

```bash
git log --oneline                                   # 全部提交（11 条功能提交 + 纯文档提交）
git show --stat ee51a56                             # 最终验收改了什么
git diff --stat af8a8f7 ee51a56                      # 与原始交付的总体差异（不含后续文档）
git ls-files | wc -l                                # 已跟踪文件数
```

复核某个具体数字时，不要读本文档——读它指向的 JSON：

```bash
python - <<'PY'
import json
d = json.load(open('reports/final/metrics_registry.json', encoding='utf-8'))
for m in d['metrics']:
    if 'recall' in m['metric'].lower():
        print(m['value'], m['claim_level'], m['source'], m['pointer'])
PY
```

## 4. 提交纪律（本轮实际执行的规则）

1. **冻结产物只增不改**：`reports/step*`、`phase2_phi_v1/test_run/`、`holdout_eval.json` 等一律不覆盖；新增证据落新目录。
2. **write-once 不是免死金牌**：`disease_selection.json` 证明「文件没被覆盖」不等于「内容与实际运行一致」，所以血缘必须每轮从产物反查重建。
3. **失败与负结果同样入库**：int8 量化表征坍缩、批处理更慢、`test_bare_yi_is_still_unhandled`、3 处 PHI 输出差异——都写进代码注释、配置字段或测试用例，而不是只留在对话里。
4. **不在测试集上回头调参**：看到 3 处跨度差异后没有改阈值 0.2，决定写进 `configs/phase4_phi_fast.json`。
5. **不推送**：全部 11 条提交只在本地；推送前需人工过 `docs/GITHUB_PUBLISHING_CHECKLIST` 类检查（许可、PHI、绝对路径）并改提交身份。

## 5. 已知的历史瑕疵（不改写）

| 项 | 状态 |
| --- | --- |
| `af8a8f7` 之后有 3 条 `fix:` 提交修正报告渲染 | 保留，说明当时的报告确实错过；不 squash |
| 第二阶段协议从 v2 改到 v2.1 | 修订原因已写在协议文件里，不悄悄改 |
| `disease_selection.json` 与实际运行不一致 | 文件保留 + `superseded_artifact` 登记 + as-run 清单取代 |
| 提交身份为占位 `codex@local.invalid` | 推送前必须改；本文档已标注 |
| 当前分支名 `codex/phase1-audit` 已不反映内容（覆盖四个阶段） | 保留原名，避免为「好看」重写历史 |
