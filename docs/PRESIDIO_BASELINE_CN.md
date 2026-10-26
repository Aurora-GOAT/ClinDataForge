# Presidio最小基线可行性验证（2026-10-25）

范围仅限环境检查、可选适配接口、原60条合成压力诊断和相关单元测试。此前第二阶段的大规模工作已停止，不纳入本次交付；没有安装依赖、下载模型或改变真实患者文本出口。

## 环境和许可

已检查当前Python3.10.7及项目已有 `.venv-phi`；两者均缺少 `presidio-analyzer`、`presidio-anonymizer`、spaCy、`en_core_web_sm`。识别任务不要求anonymizer，但至少需要analyzer、可运行的NLP引擎和模型。未尝试安装或调试这些依赖。

Presidio正式仓库已从旧Microsoft地址迁移至 [data-privacy-stack/presidio](https://github.com/data-privacy-stack/presidio)，为 [MIT许可](https://github.com/data-privacy-stack/presidio/blob/main/LICENSE)。[官方安装说明](https://github.com/data-privacy-stack/presidio/blob/main/docs/installation.md)默认示例采用英文大模型；本适配器只接受**已经安装**的模型，明确加载英文小模型，缺失时抛出 `PresidioUnavailable`，不自动安装或下载。

当前官方 [analyzer配置](https://github.com/data-privacy-stack/presidio/blob/main/presidio-analyzer/pyproject.toml)要求Python>=3.10,<3.15；本机Python版本满足这一静态要求，但**原生依赖兼容性和真实推理尚未验证**。所选候选 `en_core_web_sm` 的 [3.8.0官方元数据](https://github.com/explosion/spacy-models/blob/master/meta/en_core_web_sm-3.8.0.json)标记MIT，要求spaCy>=3.8.0,<3.9.0；本机并未安装该模型。将来使用其他版本必须重新核对其元数据，不能将上游main版本当成本机已安装版本。

## 接口边界

`PresidioAdapter.find(text)`返回项目现有 `PHISpan`，映射PERSON→NAME、PHONE_NUMBER→PHONE、DATE_TIME→DATE、LOCATION→ADDRESS。未添加自定义MRN规则；病历号不受此最小配置保证。只有英文NLP配置，即使历史样本包含中文也不能宣称支持中文。

适配器没有接入现有生产/导出流水线。缺少依赖和初始化失败均明确报错；推理错误不会转换为空预测。单元测试替身仅验证标签/偏移接口，不作为真实Presidio推理或任何模型成绩。

## 实测结果

数据为原有60条、180个程序标注PHI跨度、六种重复模板，仅是历史诊断集。没有改规则或根据该集调参。

| 方法 | TP/FP/FN | Precision | Recall | F1 | 识别耗时 |
|---|---|---:|---:|---:|---|
| 原始项目规则 | 100/0/80 | 1.0000 | 0.5556 | 0.7143 | 60条合计0.002666秒 |
| Presidio | 未运行 | — | — | — | 无有效推理计时 |

Presidio缺少所需包和模型，**没有产生可比较的真实结果，也不能据此声称优于原规则**。原规则时间只计识别调用，不含初始化和评分，单次微基准容易受本机环境影响。

命令与证据：

```powershell
python -m scripts.benchmark_presidio --out reports/my_presidio_probe.json
python -m unittest tests.test_presidio_adapter tests.test_operators.OperatorsTest.test_phi_chinese tests.test_operators.OperatorsTest.test_phi_english tests.test_operators.OperatorsTest.test_phi_conservative_scope -v
```

本次 **9/9** 相关测试通过（0.011秒）。结果在 `reports/presidio_probe_20261025/result.json`，测试原始日志为同目录 `unittest.log`。已有结果文件会拒绝覆盖。

结论：值得保留为后续候选框架基线，优点是统一识别器和实体接口；当前环境尚未证明其可运行，更未证明对中文或医疗编号有效。本次不安装模型、不继续集成、不进行下一阶段。
