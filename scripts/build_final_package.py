"""Assemble the final metrics registry and experiment table from artefacts.

Every headline number in the delivery package must point to a file and a field.
This script reads the JSON artefacts, writes:

  reports/final/metrics_registry.json   machine-readable: metric -> value -> source
  reports/final/experiment_table.md     human-readable tables grouped by claim level

Nothing is recomputed and no experiment is re-run; this is a traceability layer.

Usage: python -m scripts.build_final_package
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_VERSION = 'final-package-1.0.0'

CLAIM_LEVELS = {
    'template_self_check': '模板内自检：金标由生成器构造，模板与金标同源，不能当独立评测',
    'synthetic_holdout': '同生成器的留出合成语料：评测前冻结，新种子/新句式，但共享代码与疾病集',
    'third_party_frozen': '第三方合成数据上的冻结评测：ASQ-PHI v1（MIT），一次性测试',
    'engineering_measurement': '同机同数据的工程测量：可以声称加速比，不能外推到其他硬件',
    'audit_finding': '审计结论：对产物做静态/重算检查，不是模型指标',
}


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def pct(value: float, digits: int = 2) -> str:
    return f'{value * 100:.{digits}f}%'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='reports/final')
    args = parser.parse_args(argv)
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    dev = load('reports/phase4_context/dev_eval.json')
    holdout = load('reports/phase4_context/holdout_eval.json')
    boot = load('reports/phase4_split_relations/holdout_bootstrap.json')
    relations = load('reports/phase4_split_relations/relations.json')
    lineage = load('data/phase4_lineage/lineage_manifest.json')
    quality = load('reports/phase4_data_quality/audit.json')
    lab = load('reports/phase4_lab_independence/audit.json')
    pipeline = load('reports/phase4_pipeline_eval/pipeline_eval.json')
    perf = load('reports/phase4_perf/comparison.json')
    regression = load('reports/phase4_perf/test_run_fast/comparison.json')
    phi = load('reports/phase2_phi_v1/test_run/results.json')
    audit_v1 = load('data/phase3_synth/pipeline_out/audit.json')
    audit_v2 = load('data/phase4_synth_v2/pipeline_out/audit.json')
    tests = load('reports/final/test_summary.json')

    rows = []

    def add(section, metric, value, unit, claim, source, pointer, note=''):
        rows.append({'section': section, 'metric': metric, 'value': value, 'unit': unit,
                     'claim_level': claim, 'source': source, 'pointer': pointer, 'note': note})

    # ---- context: dev -----------------------------------------------------
    d1 = dev['systems']['v1']
    d2 = dev['systems']['v2_scope_ng']
    add('context_dev', '开发集匹配提及数', d1['per_class']['_overall']['n'], 'mentions',
        'template_self_check', 'reports/phase4_context/dev_eval.json', 'systems.v1.per_class._overall.n')
    add('context_dev', 'v1 固定窗口准确率', pct(d1['per_class']['_overall']['accuracy']), '%',
        'template_self_check', 'reports/phase4_context/dev_eval.json', 'systems.v1.per_class._overall.accuracy')
    add('context_dev', 'v2 作用域准确率', pct(d2['per_class']['_overall']['accuracy']), '%',
        'template_self_check', 'reports/phase4_context/dev_eval.json', 'systems.v2_scope_ng.per_class._overall.accuracy')
    add('context_dev', 'history→affirmed（v1）', d1['confusion']['history']['affirmed'], 'mentions',
        'template_self_check', 'reports/phase4_context/dev_eval.json', 'systems.v1.confusion.history.affirmed')
    add('context_dev', 'history→affirmed（v2）', d2['confusion']['history']['affirmed'], 'mentions',
        'template_self_check', 'reports/phase4_context/dev_eval.json', 'systems.v2_scope_ng.confusion.history.affirmed')

    # ---- context: holdout -------------------------------------------------
    hs = relations['near_duplicates']['holdout_structure']
    add('context_holdout', '留出语料记录数', holdout['n_records'], 'notes',
        'synthetic_holdout', 'reports/phase4_context/holdout_eval.json', 'n_records')
    add('context_holdout', '留出语料匹配提及数', holdout['n_matched_mentions'], 'mentions',
        'synthetic_holdout', 'reports/phase4_context/holdout_eval.json', 'n_matched_mentions')
    add('context_holdout', '不同规范化文本数', hs['n_distinct_normalised_texts'], 'texts',
        'audit_finding', 'reports/phase4_split_relations/relations.json',
        'near_duplicates.holdout_structure.n_distinct_normalised_texts',
        '260 条中存在重复副本')
    add('context_holdout', '近重复簇数（Jaccard≥0.8）', hs['n_clusters_at_threshold'], 'clusters',
        'audit_finding', 'reports/phase4_split_relations/relations.json',
        'near_duplicates.holdout_structure.n_clusters_at_threshold', '有效独立单位远少于 260')
    for system, label in (('v1', 'v1 固定窗口'), ('v2_scope_v1', 'v2 作用域 + v1 词表'),
                          ('v2_scope_ng', 'v2 作用域 + NegEx 词表')):
        point = boot['systems'][system]['point']
        ci = boot['systems'][system]['accuracy_ci95']
        f1ci = boot['systems'][system]['macro_f1_ci95']
        add('context_holdout', f'{label}准确率', pct(point['accuracy']), '%',
            'synthetic_holdout', 'reports/phase4_split_relations/holdout_bootstrap.json',
            f'systems.{system}.point.accuracy', f'簇自助 95% CI [{ci[0]:.4f}, {ci[1]:.4f}]')
        add('context_holdout', f'{label}宏 F1', f"{point['macro_f1']:.4f}", 'F1',
            'synthetic_holdout', 'reports/phase4_split_relations/holdout_bootstrap.json',
            f'systems.{system}.point.macro_f1', f'簇自助 95% CI [{f1ci[0]:.4f}, {f1ci[1]:.4f}]')
        add('context_holdout', f'{label}history→affirmed', point['history_to_affirmed'], 'mentions',
            'synthetic_holdout', 'reports/phase4_split_relations/holdout_bootstrap.json',
            f'systems.{system}.history_to_affirmed_point')

    # ---- PHI detection ----------------------------------------------------
    for method in ('A', 'B', 'C', 'D'):
        overall = phi['methods'][method]['overall']['entity_exact']
        add('phi_detection', f'方法 {method} 实体级 P/R/F1',
            f"{overall['precision']:.4f} / {overall['recall']:.4f} / {overall['f1']:.4f}", 'ratio',
            'third_party_frozen', 'reports/phase2_phi_v1/test_run/results.json',
            f'methods.{method}.overall.entity_exact')
    add('phi_detection', '冻结测试集文档数', phi['methods']['D']['overall']['n_records'], 'docs',
        'third_party_frozen', 'reports/phase2_phi_v1/test_run/results.json', 'methods.D.overall.n_records')
    add('phi_detection', '数据 SHA256', phi['dataset_sha256'][:16] + '…', 'sha256',
        'third_party_frozen', 'reports/phase2_phi_v1/test_run/results.json', 'dataset_sha256')

    # ---- PHI throughput ---------------------------------------------------
    table = {row['config_name']: row for row in perf['table']}
    base, fast = table['baseline_fp16_t2_b1'], table['fp32_t4_b1']
    add('phi_throughput', '基线 ms/条', round(base['mean_ms_per_doc'], 1), 'ms/doc',
        'engineering_measurement', 'reports/phase4_perf/comparison.json', 'table[baseline_fp16_t2_b1].mean_ms_per_doc')
    add('phi_throughput', '优化后 ms/条', round(fast['mean_ms_per_doc'], 1), 'ms/doc',
        'engineering_measurement', 'reports/phase4_perf/comparison.json', 'table[fp32_t4_b1].mean_ms_per_doc')
    add('phi_throughput', '单条加速比', round(base['mean_ms_per_doc'] / fast['mean_ms_per_doc'], 2), '×',
        'engineering_measurement', 'reports/phase4_perf/comparison.json', 'derived from table[].mean_ms_per_doc')
    add('phi_throughput', 'p95 基线→优化',
        f"{base['p95_ms_per_doc']:.1f} → {fast['p95_ms_per_doc']:.1f}", 'ms',
        'engineering_measurement', 'reports/phase4_perf/comparison.json', 'table[].p95_ms_per_doc')
    add('phi_throughput', '吞吐 基线→优化',
        f"{base['docs_per_second']:.2f} → {fast['docs_per_second']:.2f}", 'docs/s',
        'engineering_measurement', 'reports/phase4_perf/comparison.json', 'table[].docs_per_second')
    add('phi_throughput', '峰值内存 基线→优化',
        f"{base['peak_rss_mb']:.1f} → {fast['peak_rss_mb']:.1f}", 'MB',
        'engineering_measurement', 'reports/phase4_perf/comparison.json', 'table[].peak_rss_mb')
    minutes_v1 = audit_v1['wall_seconds'] / 60
    minutes_v2 = audit_v2['wall_seconds'] / 60
    add('phi_throughput', '九段流水线端到端 2,400 条',
        f'{minutes_v1:.1f} → {minutes_v2:.1f} 分钟（{minutes_v1 / minutes_v2:.2f}×）', 'min',
        'engineering_measurement',
        'data/phase3_synth/pipeline_out/audit.json; data/phase4_synth_v2/pipeline_out/audit.json', 'wall_seconds')

    # ---- PHI regression ---------------------------------------------------
    add('phi_regression', '冻结集重算文档数',
        regression['methods']['D']['documents'], 'docs', 'third_party_frozen',
        'reports/phase4_perf/test_run_fast/comparison.json', 'methods.D.documents')
    add('phi_regression', '方法 D 跨度一致率', f"{regression['methods']['D']['doc_identity_rate']:.4f}", 'ratio',
        'third_party_frozen', 'reports/phase4_perf/test_run_fast/comparison.json', 'methods.D.doc_identity_rate')
    add('phi_regression', '新增 / 缺失跨度',
        f"{regression['methods']['D']['spans_added_vs_frozen']} / {regression['methods']['D']['spans_missing_vs_frozen']}",
        'spans', 'third_party_frozen', 'reports/phase4_perf/test_run_fast/comparison.json',
        'methods.D.spans_added_vs_frozen, spans_missing_vs_frozen')
    frozen_d = regression['methods']['D']['metrics_frozen']['entity_exact']
    optimized_d = regression['methods']['D']['metrics_optimized']['entity_exact']
    add('phi_regression', '方法 D 召回 冻结→重算',
        f"{frozen_d['recall']:.4f} → {optimized_d['recall']:.4f}", 'ratio',
        'third_party_frozen', 'reports/phase4_perf/test_run_fast/comparison.json',
        'methods.D.metrics_frozen/optimized.entity_exact.recall')
    add('phi_regression', '方法 D 精确率 冻结→重算',
        f"{frozen_d['precision']:.4f} → {optimized_d['precision']:.4f}", 'ratio',
        'third_party_frozen', 'reports/phase4_perf/test_run_fast/comparison.json',
        'methods.D.metrics_frozen/optimized.entity_exact.precision')

    # ---- pipeline ---------------------------------------------------------
    add('pipeline', '输入 / 接受 / 隔离',
        f"{audit_v2['input_rows']} / {audit_v2['accepted_rows']} / {audit_v2['quarantined_rows']}", 'records',
        'template_self_check', 'data/phase4_synth_v2/pipeline_out/audit.json',
        'input_rows, accepted_rows, quarantined_rows')
    add('pipeline', '表型抽取 F1', f"{pipeline['phenotype_extraction']['f1']:.4f}", 'F1',
        'template_self_check', 'reports/phase4_pipeline_eval/pipeline_eval.json', 'phenotype_extraction')
    add('pipeline', '上下文状态准确率', pct(pipeline['context_status_accuracy_on_matched']), '%',
        'template_self_check', 'reports/phase4_pipeline_eval/pipeline_eval.json', 'context_status_accuracy_on_matched')
    add('pipeline', '检验标准化',
        f"{pipeline['lab_standardisation']['n_correct_std']}/{pipeline['lab_standardisation']['n_gold']}", 'values',
        'template_self_check', 'reports/phase4_pipeline_eval/pipeline_eval.json', 'lab_standardisation')
    add('pipeline', 'PHI 掩码覆盖（合成）',
        f"{pipeline['phi_gate_synthetic']['gold_phi_masked_in_output']}/{pipeline['phi_gate_synthetic']['gold_phi_entities']}",
        'entities', 'template_self_check', 'reports/phase4_pipeline_eval/pipeline_eval.json', 'phi_gate_synthetic')
    add('pipeline', '近重复判定 F1', f"{pipeline['dedup_pairs']['f1']:.4f}", 'F1',
        'template_self_check', 'reports/phase4_pipeline_eval/pipeline_eval.json', 'dedup_pairs')

    # ---- data quality -----------------------------------------------------
    prov = quality['provenance']
    split = quality['split_leakage']
    add('data_quality', '疾病血缘记录数', f"{lineage['checks']['records']}/{lineage['checks']['records']}", 'records',
        'audit_finding', 'data/phase4_lineage/lineage_manifest.json', 'checks.records')
    add('data_quality', '表型 HP 编码属于疾病注释集',
        f"{lineage['checks']['phenotype_hp_in_annotation']:,}/{lineage['checks']['phenotype_entities']:,}", 'entities',
        'audit_finding', 'data/phase4_lineage/lineage_manifest.json', 'checks.phenotype_hp_in_annotation')
    add('data_quality', '记录级 HPO 溯源 = 快照',
        f"{lineage['checks']['hpo_provenance_equals_snapshot']}/{lineage['checks']['records']}", 'records',
        'audit_finding', 'data/phase4_lineage/lineage_manifest.json', 'checks.hpo_provenance_equals_snapshot')
    add('data_quality', '历史疾病清单与实际重合', f"{lineage['superseded_artifact']['n_overlap']}/16", 'diseases',
        'audit_finding', 'data/phase4_lineage/lineage_manifest.json', 'superseded_artifact.n_overlap')
    add('data_quality', 'SFT 划分 train/dev/test',
        f"{split['split_sizes']['train']}/{split['split_sizes']['dev']}/{split['split_sizes']['test']}", 'records',
        'audit_finding', 'reports/phase4_data_quality/audit.json', 'split_leakage.split_sizes')
    add('data_quality', '跨划分患者 / 精确重复 / 近重复',
        f"{split['patients_shared_across_splits']} / {split['exact_duplicate_inputs_across_splits']} / "
        f"{relations['near_duplicates']['cross_split_pairs_excluding_holdout']}", 'counts',
        'audit_finding', 'reports/phase4_data_quality/audit.json; reports/phase4_split_relations/relations.json',
        'split_leakage.patients_shared_across_splits / exact_duplicate_inputs_across_splits')
    add('data_quality', 'test 记录三元组已在 train 出现',
        pct(relations['cell_reuse']['test']['rate']), '%', 'audit_finding',
        'reports/phase4_split_relations/relations.json', 'cell_reuse.test.rate')
    add('data_quality', '疾病名出现在正文（train）',
        pct(relations['disease_name_leakage']['train']['raw_rate']) + ' / ' +
        pct(relations['disease_name_leakage']['train']['masked_rate']) + '（脱敏后）', '%',
        'audit_finding', 'reports/phase4_split_relations/relations.json',
        'disease_name_leakage.train.raw_rate / masked_rate')
    add('data_quality', '上下文标签污染',
        f"{quality['context_contamination']['exported_status_mismatches']}/"
        f"{quality['context_contamination']['matched_mentions']}", 'mentions',
        'audit_finding', 'reports/phase4_data_quality/audit.json',
        'context_contamination.exported_status_mismatches')
    add('data_quality', '偏好对标签噪声',
        f"{quality['preference_labels']['pairs_where_rejected_is_not_actually_wrong']}/"
        f"{quality['preference_labels']['n_pairs']}", 'pairs',
        'audit_finding', 'reports/phase4_data_quality/audit.json',
        'preference_labels.pairs_where_rejected_is_not_actually_wrong')
    add('data_quality', '中文术语与专家审核',
        f"{quality['translation']['n_phenotype_terms']} 表型 + {quality['translation']['n_disease_terms']} 疾病；无专家审核",
        'terms', 'audit_finding', 'reports/phase4_data_quality/audit.json', 'translation')

    # ---- lab independence -------------------------------------------------
    add('lab_independence', '语料检验值独立复算',
        f"{lab['corpus_recomputation']['n_checked']}", 'values', 'audit_finding',
        'reports/phase4_lab_independence/audit.json', 'corpus_recomputation.n_checked')
    add('lab_independence', '换算 / 方向不一致',
        f"{lab['corpus_recomputation']['conversion_mismatch']} / "
        f"{lab['corpus_recomputation']['direction_mismatch']}", 'values', 'audit_finding',
        'reports/phase4_lab_independence/audit.json', 'corpus_recomputation')
    add('lab_independence', '注入实验：共享表 / 独立路径 检出',
        f"{lab['perturbation_experiment']['arm_shared_table']['conversion_mismatch']} + "
        f"{lab['perturbation_experiment']['arm_shared_table']['direction_mismatch']} 错 / "
        f"{lab['perturbation_experiment']['arm_independent_table']['conversion_mismatch']} + "
        f"{lab['perturbation_experiment']['arm_independent_table']['direction_mismatch']} 错", 'errors',
        'audit_finding', 'reports/phase4_lab_independence/audit.json', 'perturbation_experiment')

    # ---- tests ------------------------------------------------------------
    add('engineering', '自动化测试', tests['n_tests'], 'tests', 'engineering_measurement',
        'reports/final/test_summary.json', 'n_tests', tests.get('result', ''))

    # ---- write registry ---------------------------------------------------
    sources = {}
    for row in rows:
        for path in row['source'].split('; '):
            path = path.strip()
            if path and (ROOT / path).exists():
                sources[path] = {'sha256': sha256(ROOT / path), 'bytes': (ROOT / path).stat().st_size}
    for extra in ('demo/index.html', 'reports/final/experiment_table.md'):
        if (ROOT / extra).exists():
            sources[extra] = {'sha256': sha256(ROOT / extra), 'bytes': (ROOT / extra).stat().st_size}

    registry = {
        'package_version': PACKAGE_VERSION,
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'claim_levels': CLAIM_LEVELS,
        'metrics': rows,
        'artefacts': sources,
        'note': 'every value is read from an existing artefact; no number here is recomputed or estimated',
    }
    (out / 'metrics_registry.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2),
                                               encoding='utf-8')

    # ---- experiment table -------------------------------------------------
    titles = {
        'context_dev': '1. 上下文状态 · 开发集（仅诊断，不是测试集）',
        'context_holdout': '2. 上下文状态 · 冻结留出合成语料（260 条 / 64 个近重复簇）',
        'phi_detection': '3. PHI 检测 · ASQ-PHI v1 冻结测试集（632 条，第三方合成数据）',
        'phi_throughput': '4. PHI 吞吐 · 本机同一数据（工程测量）',
        'phi_regression': '5. PHI 回归 · 冻结测试集重算（只披露差异，不回改阈值）',
        'pipeline': '6. 九段流水线 · 2,400 条合成病例（模板内自检）',
        'data_quality': '7. 数据质量、血缘与切分审计',
        'lab_independence': '8. 检验常数独立核验',
        'engineering': '9. 工程与测试',
    }
    levels = {
        'context_dev': '模板内自检 / 诊断',
        'context_holdout': '同生成器留出合成语料',
        'phi_detection': '第三方合成数据冻结评测',
        'phi_throughput': '同机工程测量',
        'phi_regression': '冻结集回归检查',
        'pipeline': '模板内自检',
        'data_quality': '静态与重算审计',
        'lab_independence': '独立路径审计',
        'engineering': '可复现工程',
    }
    lines = [
        '# ClinDataForge · 核心实验表',
        '',
        f'- 版本 `{PACKAGE_VERSION}`，生成时间 {registry["generated_at_utc"]}',
        '- 每一行的数值都来自 `reports/final/metrics_registry.json` 中登记的产物字段；'
        '本表由 `scripts/build_final_package.py` 自动生成。',
        '',
        '## 效力分级（先读这一节）',
        '',
        '| 级别 | 含义 |',
        '| --- | --- |',
    ]
    for key, value in CLAIM_LEVELS.items():
        lines.append(f'| `{key}` | {value} |')
    lines.append('')

    for section, title in titles.items():
        subset = [row for row in rows if row['section'] == section]
        if not subset:
            continue
        lines += [f'## {title}', '',
                  f'**效力**：{levels[section]}', '',
                  '| 指标 | 数值 | 单位 | 产物 | 备注 |',
                  '| --- | --- | --- | --- | --- |']
        for row in subset:
            pointer = f"`{row['pointer']}`" if row['pointer'] else ''
            source = f"`{row['source']}`<br>{pointer}"
            note = row['note'].replace('|', '/')
            lines.append(f"| {row['metric']} | {row['value']} | {row['unit']} | {source} | {note} |")
        lines.append('')

    lines += [
        '## 10. 不能写进简历的结论',
        '',
        '- 任何“RAG 提升/无效”的结论：本项目没有做生成式 RAG 训练实验。',
        '- 任何“临床准确率”“跨医院泛化”“隐私安全已证明”的表述：没有真实临床数据、没有合规认证。',
        '- 任何“训练收益”：SFT/LoRA/DPO 均未执行，只导出了候选数据。',
        '- 任何“留出集是独立临床验证”：留出集与开发集共享生成器、16 种疾病与中文词表；'
        '它只有 64 个近重复簇。',
        '',
        '## 11. 复现',
        '',
        '```bash',
        'python -m scripts.build_final_package     # 重新生成本表与指标登记簿',
        'python -m unittest discover -s tests -q    # 170 项测试',
        '```',
        '',
    ]
    (out / 'experiment_table.md').write_text('\n'.join(lines), encoding='utf-8')

    # The table is generated *after* the registry, so its fingerprint in the first
    # pass would describe the previous version of the file. Rewrite the registry's
    # fingerprint entry once the table exists (a file cannot contain its own hash,
    # but the registry can, and a stale hash here would silently break traceability).
    table_path = out / 'experiment_table.md'
    key = str(table_path.relative_to(ROOT)).replace('\\', '/')
    registry['artefacts'][key] = {'sha256': sha256(table_path),
                                  'bytes': table_path.stat().st_size}
    (out / 'metrics_registry.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2),
                                               encoding='utf-8')

    print(json.dumps({'package_version': PACKAGE_VERSION, 'metrics': len(rows),
                      'sources': len(sources),
                      'outputs': [str((out / 'metrics_registry.json').relative_to(ROOT)),
                                  str((out / 'experiment_table.md').relative_to(ROOT))]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
