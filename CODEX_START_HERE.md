# 给Codex的第一轮接手指令

> 2026-10-25第一阶段已完成：先读 `docs/PHASE1_AUDIT_CN.md` 和 `DEVELOPMENT_PROGRESS.md`。历史模板指标可复现但金标/正文有六处缺陷；历史MIMIC 222/64/545不可由现存源复现；现存源为85/40/21。当前所有流水线文本/SFT出口关闭，P0独立PHI/模型验收仍未完成。

请以当前目录为新的独立项目 ClinDataForge v0.1，不要继续 MedDataLab 的医学考试 RAG 分支。

请先完整阅读 `AGENTS.md`、`README.md`、`docs/ANT_JD_MAPPING_CN.md`、`docs/CODEX_PHASES_CN.md`，运行全量测试；核对 `reports/demo_run/synthetic_benchmark.json`、`reports/stress_eval.json`、`reports/public_demo_aggregate.json` 中所有实际数字。

本项目用于匹配2027蚂蚁星“医疗大模型数据科学家－平台技术”的医疗高质量数据处理与评估。请重点做P0：解决跨模板PHI识别不可靠的问题（独立来源测试集、模型/规则对照、可确认的隐私fail-closed安全边界），把真实错误模式和代价讲清楚。不要仅在我们已看过的60条压力样本上过拟合并称效果提高。

在未经本人批准的情况下：不得处理真实含隐私病历；不得运行有费用的外部API/GPU；不得发布任何用户文件到GitHub；不得删除现有benchmark、报告或历史记录。每次修改记录测试及真实结果，写入 `DEVELOPMENT_PROGRESS.md`，新建可复现实验目录。

到达P0独立验收后再进行P1。最终需要给出一份能进入技术面试的严谨结论，而不是继续增加无意义功能或版本号。
