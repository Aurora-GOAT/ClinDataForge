# ClinDataForge 系统架构（截至 2026-10-26）

> 本图与代码结构一一对应。所有外部资源记录版本与 SHA256；真实患者文本入口与正文出口**保持关闭**。

## 总体数据流

```mermaid
flowchart TD
    subgraph EXT[外部权威资源 - 只读 原样使用]
        HPO[hp.obo<br/>data-version 2026-09-01<br/>SHA256 93dace...]
        HPOA[phenotype.hpoa<br/>version 2026-09-02<br/>SHA256 e89aa3...]
        ASQ[ASQ-PHI v1 MIT<br/>第三方合成 PHI 基准]
        GLI[GLiNER gliner_multi_pii-v1<br/>ONNX fp16 本地推理]
    end

    subgraph P0[P0 知识约束合成]
        KB[hpo_knowledge.py<br/>解析→快照→疾病选择<br/>16 种罕见病人工核验集]
        GEN[synthgen.py<br/>频率加权表型采样<br/>多模板/否定/疑似/时间<br/>跨度级金标]
        VAL[validate_synth.py<br/>独立验证: 约束违反/覆盖/<br/>近重复/复核队列]
        KB --> GEN --> VAL
    end

    subgraph P1[P1 结构化质量流水线 pipeline_med.py]
        SCH[Schema 校验]
        NER[med_extract.py<br/>HPO 词典最长匹配<br/>上下文: 否定/疑似/既往]
        LAB[检验标准化 v2<br/>ALT/AST/血糖/Hb<br/>mmol/L g/L 换算]
        GATE[PHI 安全门控<br/>冻结 D 方法: 规则∪GLiNER]
        DEDUP[近重复检测<br/>同患者同就诊+检验冲突保护]
        CONS[知识一致性检查<br/>抽取表型 ⊆ 疾病注释集]
        QS[质量评分 → 接受/隔离/人工复核队列]
        SCH --> NER --> LAB --> GATE --> DEDUP --> CONS --> QS
    end

    subgraph P2[P2 评测与数据产品]
        EVAL[evaluate_pipeline_synth.py<br/>模板内自检: 抽取P/R/F1<br/>标准化准确率 去重P/R/F1]
        SFT[export_training_candidates.py<br/>SFT JSONL + 偏好对<br/>规则扰动生成 非人工标注]
        BENCH[benchmarks.py<br/>MedMCQA 离线接口<br/>在线评测: BLOCKED 未授权]
    end

    HPO --> KB
    HPOA --> KB
    ASQ --> PH2[第二阶段 PHI 四路对照<br/>独立冻结测试集 632条]
    GLI --> GATE
    GLI --> PH2
    GEN -->|notes.jsonl 合成| SCH
    QS --> EVAL
    QS --> SFT
    VAL --> RPT[报告/HTML 仪表盘]
    EVAL --> RPT
    PH2 --> RPT
```

## 关键设计决策

| 决策 | 选择 | 理由（真实证据） |
|---|---|---|
| 知识来源 | HPO 本体 + phenotype.hpoa 注释 | 许可允许自由使用；含频率/证据/PMID 引用；版本与哈希可冻结 |
| 合成约束 | 表型 ⊆ 疾病注释集（硬约束） | 独立验证器复核：2,400 条 0 违反 |
| 表型抽取 | 词典最长匹配 + 分句级提示词窗口 | 术语与知识库同源、可审计；medSpaCy 评估后暂缓引入（依赖重、行为等价于透明实现） |
| PHI 门控 | 复用第二阶段冻结的 D 方法（规则∪GLiNER fp16） | 独立测试集召回 0.9042 [ bootstrap 区间不跨 0 ]；int8 量化权重已证明判别力坍缩，禁用 |
| 去重保护 | 同患者+同就诊内比对；检验值冲突即不合并 | 防止把同患者检验更新误判为重复（160 对标注评测） |
| 出口控制 | 真实患者入口/出口关闭；合成数据演示文本输出 | 第二阶段结论：96.55% 无 PHI 硬负样本仍被改动，不能宣称生产级安全 |

## 失败与限制（如实记录）

- GLiNER int8 量化权重表征坍缩（探针最大概率 0.202）→ 全项目改用 fp16；
- spaCy 3.8.x 需锁 preshed==3.0.9 / cymem==2.0.8 / murmurhash==1.0.10，否则 pipeline 加载抛 OverflowError；
- Presidio 不适配中文（zh 召回 0.057）与病历号/医保号；
- 抽取/上下文/标准化指标目前为**模板内自检**，真实临床文本上的独立验证是明确的后续工作；
- SFT/偏好数据仅为候选导出（规则扰动），未执行任何训练，也未获得在线模型评测授权。
