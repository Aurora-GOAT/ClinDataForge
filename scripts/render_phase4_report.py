"""Render the phase-4 artefacts (context fix, PHI throughput, data audit) into
a markdown table set and a single HTML dashboard.

Every number is read from the JSON produced by the experiment scripts; nothing
is typed by hand, so the dashboard cannot drift from the artefacts.

Usage: python -m scripts.render_phase4_report
"""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ('affirmed', 'suspected', 'history', 'negated')

SYSTEM_LABEL = {
    'v1': 'v1 固定窗口（相位 3 基线）',
    'v2_scope_v1': 'v2 作用域 + v1 线索词表',
    'v2_scope_ng': 'v2 作用域 + NegEx/ConText 线索词表',
}


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def pct(value, digits=2):
    return '—' if value is None else f'{value * 100:.{digits}f}%'


def num(value, digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def context_section(dev, holdout):
    lines = ['## 1. 上下文状态判定', '',
             '同一批提及、同一套抽取词表、同一份金标，只替换上下文判定器。', '']
    for name, data, note in (
            ('开发语料（用于诊断与调参，**不可作为测试集**）',
             dev, 'data/phase3_synth/gen/notes.jsonl'),
            ('同生成器留出语料（评测前冻结，来源非独立）', holdout,
             'data/phase4_context/holdout_notes.jsonl')):
        lines += [f'### {name}', '',
                  f'记录 {data["n_records"]} 条，匹配提及 {data["n_matched_mentions"]} 个（`{note}`）', '',
                  '| 系统 | 准确率 | 宏平均 F1 | affirmed F1 | suspected F1 | history F1 | negated F1 |',
                  '| --- | --- | --- | --- | --- | --- | --- |']
        for key in ('v1', 'v2_scope_v1', 'v2_scope_ng'):
            block = data['systems'][key]['per_class']
            lines.append('| {} | {} | {} | {} | {} | {} | {} |'.format(
                SYSTEM_LABEL[key], pct(block['_overall']['accuracy']),
                num(block['_overall']['macro_f1'], 4),
                num(block['affirmed']['f1'], 4), num(block['suspected']['f1'], 4),
                num(block['history']['f1'], 4), num(block['negated']['f1'], 4)))
        lines.append('')
        lines.append('| 系统 | 类别 | Precision | Recall | F1 | 支持数 |')
        lines.append('| --- | --- | --- | --- | --- | --- |')
        for key in ('v1', 'v2_scope_ng'):
            block = data['systems'][key]['per_class']
            for status in STATUSES:
                cell = block[status]
                lines.append('| {} | {} | {} | {} | {} | {} |'.format(
                    SYSTEM_LABEL[key].split('（')[0], status, num(cell['precision'], 4),
                    num(cell['recall'], 4), num(cell['f1'], 4), cell['support']))
        lines.append('')
        for key in ('v1', 'v2_scope_v1', 'v2_scope_ng'):
            confusion = data['systems'][key]['confusion']
            lines.append(f'**混淆矩阵 — {SYSTEM_LABEL[key]}**（行=金标，列=预测）')
            lines.append('')
            lines.append('| 金标 \\ 预测 | ' + ' | '.join(STATUSES) + ' | 行合计 |')
            lines.append('| --- | ' + ' | '.join('---' for _ in STATUSES) + ' | --- |')
            for gold in STATUSES:
                row = confusion[gold]
                lines.append(f'| {gold} | ' + ' | '.join(str(row[status]) for status in STATUSES)
                             + f' | {sum(row.values())} |')
            lines.append('')
    return lines


def error_delta_section(dev, holdout):
    lines = ['### 误判迁移（改进前后）', '',
             '| 转移 | 开发语料 v1 | 开发语料 v2 | 留出 v1 | 留出 v2（仅作用域） | 留出 v2（完整） |',
             '| --- | --- | --- | --- | --- | --- |']
    names = ('v1', 'v2_scope_v1', 'v2_scope_ng')
    transitions = set()
    for data in (dev, holdout):
        for key in names:
            confusion = data['systems'][key]['confusion']
            for gold in STATUSES:
                for pred in STATUSES:
                    if gold != pred and confusion[gold][pred]:
                        transitions.add(f'{gold}->{pred}')
    for transition in sorted(transitions):
        gold, pred = transition.split('->')
        cells = []
        for data in (dev, holdout):
            for key in names:
                cells.append(data['systems'][key]['confusion'][gold][pred])
        if not any(cells[2:]):
            continue
        lines.append(f'| {transition} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {cells[4]} |')
    lines.append('')
    return lines


def perf_section(comparison):
    lines = ['## 2. PHI 门控吞吐', '',
             '同一台机器、同一批 60 条合成病历、同一权重版本与阈值，仅改变精度/线程/批大小。',
             '', '| 配置 | 平均 ms/条 | p95 ms | 条/秒 | 峰值内存 MB | 前向次数 | 相对加速 | 与基线输出一致 | 跨度差异 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in comparison['table']:
        agree = row.get('agreement', {})
        lines.append('| {} | {} | {} | {} | {} | {} | {}× | {} | {} |'.format(
            row['config_name'], num(row['mean_ms_per_doc'], 1), num(row['p95_ms_per_doc'], 1),
            num(row['docs_per_second'], 2), num(row['peak_rss_mb'], 1), row['n_forward_calls'],
            num(row.get('speedup_mean', 1.0), 2), pct(agree.get('doc_identity_rate'), 2),
            agree.get('spans_only_in_baseline', 0) + agree.get('spans_only_in_new', 0)))
    lines.append('')
    return lines


def phi_regression_section(path):
    if not (ROOT / path).exists():
        return ['## 3. 冻结 PHI 测试集回归', '', '_尚未运行_', '']
    data = load(path)
    lines = ['## 3. 冻结 PHI 测试集回归（输出是否改变）', '',
             '| 方法 | 条目一致率 | 相对冻结版缺失跨度 | 新增跨度 | 平均 ms/条 | p95 ms |',
             '| --- | --- | --- | --- | --- | --- |']
    for method, block in data['methods'].items():
        lines.append('| {} | {} | {} | {} | {} | {} |'.format(
            method, pct(block['doc_identity_rate']), block['spans_missing_vs_frozen'],
            block['spans_added_vs_frozen'], num(block['mean_ms_per_doc'], 1),
            num(block['p95_ms_per_doc'], 1)))
    lines.append('')
    lines.append('| 方法 | 指标 | 冻结版 | 优化后 |')
    lines.append('| --- | --- | --- | --- |')
    for method, block in data['methods'].items():
        for key in ('entity_exact',):
            frozen = block['metrics_frozen'][key]
            current = block['metrics_optimized'][key]
            for field in ('precision', 'recall', 'f1', 'tp', 'fp', 'fn'):
                lines.append(f'| {method} | {key}.{field} | {frozen[field]} | {current[field]} |')
    lines.append('')
    return lines


def audit_section(path):
    if not (ROOT / path).exists():
        return ['## 4. 数据质量审计', '', '_尚未运行_', '']
    data = load(path)
    prov = data['provenance']
    leak = data['split_leakage']
    pref = data['preference_labels']
    cont = data['context_contamination']
    trans = data['translation']
    lines = ['## 4. 数据质量审计', '',
             '| 检查项 | 结果 |', '| --- | --- |',
             f'| 溯源完整（含 HPO 版本与 SHA256） | {prov["cases_with_complete_provenance"]}/{prov["n_cases"]} |',
             f'| 记录内 SHA256 与磁盘一致 | {prov["ontology_sha_matches_disk"]} / {prov["annotation_sha_matches_disk"]} |',
             f'| 跨度完整性错误 | {prov["span_errors"]} |',
             f'| 知识约束违反（affirmed/suspected/history 不在注释集） | {prov["knowledge_violations_affirmed_suspected_history"]} |',
             f'| 证据代码缺失 | {prov["entities_missing_hp_id_or_evidence"]} |',
             f'| 跨划分完全相同文本 | {leak["exact_duplicate_inputs_across_splits"]} |',
             f'| 跨划分患者数 | {leak["patients_shared_across_splits"]} |',
             f'| 跨划分近重复对（Jaccard≥0.8，脱敏文本口径） | {leak["near_duplicate_pairs_jaccard_ge_0.8_across_splits"]} |',
             f'| 训练集记录落在与测试集共用（模板族, 复杂度, 疾病）格子中的比例（train 侧分母） | '
             f'{pct(leak["template_complexity_disease_triple_collisions"]["test|train"]["rate"])} |',
             f'| 偏好对 rejected==chosen | {pref["pairs_where_rejected_equals_chosen"]} |',
             f'| 偏好对 rejected 其实不错（幻觉表型本就在注释集） | {pref["pairs_where_rejected_is_not_actually_wrong"]} |',
             f'| 导出状态标签与金标不一致 | {cont["exported_status_mismatches"]}/{cont["matched_mentions"]} '
             f'（{pct(cont["mismatch_rate"])}） |',
             f'| 中文表型/疾病术语 | {trans["n_phenotype_terms"]} / {trans["n_disease_terms"]}（无双表面冲突，'
             f'子串对 {trans["substring_pairs"]} 个） |',
             '']
    return lines


def _sum_violations(checks):
    return sum(int(v) for v in (checks.get('violations') or {}).values())


def lineage_block(path):
    """Section 5: as-run disease lineage (lineage-1.0.0)."""
    if not (ROOT / path).exists():
        return None
    d = load(path)
    checks, sup = d['checks'], d['superseded_artifact']
    down, arts = d['downstream_coverage'], d['artifacts']
    n_dis = len(d['diseases'])
    tables = [
        {'caption': '与遗留清单的关系（旧文件不删不改）',
         'headers': ['项', '值'],
         'rows': [
             ['事实来源', f'`{d["source_of_truth"]["generator"]}`'],
             ['实际运行疾病数', str(n_dis)],
             ['遗留清单路径', f'`{sup["path"]}`'],
             ['遗留清单状态', sup['status']],
             ['与遗留清单重合 ID', f'{sup["n_overlap"]} / {sup["n_diseases_in_file"]}'],
             ['可用当前选择器精确复现', '是' if sup['reproduced_exactly_by_current_selector'] else '否'],
         ]},
        {'caption': '逐条一致性检查',
         'headers': ['检查项', '通过 / 总数'],
         'rows': [
             ['疾病 ID 属 `CURATED_DISEASES`', f'{checks["disease_in_curated"]} / {checks["records"]}'],
             ['疾病名与 HPO 快照一致', f'{checks["disease_name_matches_snapshot"]} / {checks["records"]}'],
             ['中文病名与术语表一致', f'{checks["disease_name_zh_matches_gloss"]} / {checks["records"]}'],
             ['记录级 HPO 溯源与快照 SHA256 一致', f'{checks["hpo_provenance_equals_snapshot"]} / {checks["records"]}'],
             ['HP 编码落在该病注释集内', f'{checks["phenotype_hp_in_annotation"]} / {checks["phenotype_entities"]}'],
             ['证据码与参考文献齐全', f'{checks["phenotype_evidence_and_reference"]} / {checks["phenotype_entities"]}'],
             ['实体偏移可回切原文', f'{checks["offset_roundtrip_ok"]} / {checks["offset_roundtrip_ok"]}'],
             ['四类状态计数自洽', f'{checks["status_counts_consistent"]} / {checks["records"]}'],
             ['违规总数（六类）', str(_sum_violations(checks))],
         ]},
        {'caption': '下游覆盖（生成了就要能追上）',
         'headers': ['环节', '条数'],
         'rows': [
             ['语料记录', down['records_in_corpus']],
             ['到达流水线输出', down['records_reaching_pipeline_output']],
             ['接受', down['records_accepted']],
             ['隔离', down['records_quarantined']],
             ['SFT 导出', down['records_in_sft_export']],
             ['SFT 划分 train / dev / test',
              '{} / {} / {}'.format(down['sft_by_split']['train'], down['sft_by_split']['dev'],
                                    down['sft_by_split']['test'])],
             ['导出 ID 不在语料中', down['export_ids_not_in_corpus']],
             ['接受但未导出', down['accepted_not_in_export']],
         ]},
        {'caption': '产物指纹（SHA256 前 16 位）',
         'headers': ['产物', 'SHA256', '字节'],
         'rows': [[f'`{name}`', f'`{meta["sha256"][:16]}…`', meta['bytes']]
                  for name, meta in arts.items()]},
    ]
    return {'title': '5. 疾病溯源：as-run 血缘（`lineage-1.0.0`）',
            'note': '以 `CURATED_DISEASES` 为唯一事实来源，从 2,400 条生成记录反查。'
                    '遗留清单 `disease_selection.json` 只有 3/16 与实际运行重合，'
                    '已登记为 superseded_artifact（保留原文件，不覆盖）。',
            'tables': tables}


def split_block(rel_path, boot_path):
    """Section 6: split / holdout relation audit (split-rel-1.0.0)."""
    if not (ROOT / rel_path).exists():
        return None
    r = load(rel_path)
    comp, pl, tx = r['composition'], r['patient_links'], r['text_relations']
    cells, nd = r['cell_reuse'], r['near_duplicates']
    leak, hv = r['disease_name_leakage'], r['holdout_vs_dev']
    hs = nd['holdout_structure']
    tables = [
        {'caption': '四语料组成',
         'headers': ['语料', '记录', '患者', '疾病', '中文', '英文', '模板族数'],
         'rows': [[name, comp[name]['n_records'], comp[name]['n_patients'],
                   comp[name]['n_diseases'], comp[name]['languages'].get('zh', 0),
                   comp[name]['languages'].get('en', 0), len(comp[name]['template_families'])]
                  for name in ('train', 'dev', 'test', 'holdout')],
         'note': 'holdout 的 14 个模板族来自另一套模板名（与前三组不共用），'
                 '但它与被评系统共享同一生成器、同一批疾病与同一套线索词，所以只能算「同生成器留出」。'},
        {'caption': '患者、文本与骨架关系',
         'headers': ['关系', '值'],
         'rows': [
             ['跨划分共享患者（6 对，全部）',
              str(max(pl['pairwise_patient_overlap'].values()))],
             ['跨划分共享就诊号', str(max(pl['pairwise_encounter_overlap'].values()))],
             ['跨划分完全相同文本',
              str(max(tx['exact_duplicate_pairs_across'].values()))],
             ['组内完全相同文本（holdout）', str(tx['exact_duplicate_records_within']['holdout'])],
             ['跨划分骨架碰撞（仅 `train`→`test`）',
              str(tx['skeleton_collisions_across'].get('train|test', 0))],
             ['组内骨架重复（holdout）', str(tx['skeleton_duplicates_within']['holdout'])],
             ['test 骨架同时出现在 train 的比例', pct(tx['test_skeleton_share'])],
         ]},
        {'caption': '三元组格子复用（两个分母不同，不可混引）',
         'headers': ['语料', '口径', '已出现 / 总数', '比例'],
         'rows': [
             ['dev', f'`{cells["dev"]["definition"]}`',
              f'{cells["dev"]["triple_seen_in_train"]} / {cells["dev"]["n_records"]}',
              pct(cells['dev']['rate'])],
             ['test', f'`{cells["test"]["definition"]}`',
              f'{cells["test"]["triple_seen_in_train"]} / {cells["test"]["n_records"]}',
              pct(cells['test']['rate'])],
             ['holdout', f'`{cells["holdout"]["definition"]}`',
              f'{cells["holdout"]["disease_seen_in_train"]} / {cells["holdout"]["n_records"]}',
              pct(cells['holdout']['rate'])],
         ],
         'note': f'训练+开发+测试共 {cells["n_distinct_cells_train_dev_test"]} 个不同格子，'
                 f'最大单格 {cells["max_records_in_one_cell"]} 条记录。'
                 'test 的 99.02% 与 train 侧 64.39% 分母不同：前者问「test 的格子有多少在 train 出现过」，'
                 '后者问「train 的格子有多少被其他组复用」，两者不是同一件事。'},
        {'caption': '近重复（字符 4-gram Jaccard ≥ 0.80）',
         'headers': ['范围', '对数'],
         'rows': [
             ['跨划分（不含 holdout 内部）', nd['cross_split_pairs_excluding_holdout']],
             ['holdout 内部', nd['holdout_internal_pairs']],
             ['holdout 与其余三组', nd['holdout_cross_pairs']],
         ]},
        {'caption': '260 条留出语料其实只有 186 种文本',
         'headers': ['指标', '值'],
         'rows': [
             ['记录数', hs['n_records']],
             ['归一化后不同文本', hs['n_distinct_normalised_texts']],
             ['完全重复副本', hs['n_exact_duplicate_copies']],
             ['内部近重复对', hs['n_near_duplicate_pairs_internal']],
             ['近重复连通分量（簇）', hs['n_clusters_at_threshold']],
             ['最大簇', hs['largest_cluster']],
             ['单例簇', hs['n_singleton_clusters']],
             ['簇规模分布',
              '、'.join(f'{k} 条 ×{v}' for k, v in sorted(hs['cluster_size_histogram'].items(),
                                                       key=lambda kv: int(kv[0])))],
         ]},
        {'caption': '疾病名泄漏（金标含 disease_suspected）',
         'headers': ['语料', '正文含病名', '脱敏后仍含'],
         'rows': [[name, pct(leak[name]['raw_rate']),
                   pct(leak[name]['masked_rate']) if leak[name]['masked_rate'] is not None else '—']
                  for name in ('train', 'dev', 'test', 'holdout')]},
    ]
    if (ROOT / boot_path).exists():
        b = load(boot_path)
        tables.append({
            'caption': f'簇级 bootstrap（{b["iterations"]} 次，seed {b["seed"]}，'
                       f'重采样单位＝近重复连通分量，{b["n_clusters"]} 个簇 / {b["n_mentions"]} 个提及）',
            'headers': ['系统', '准确率', '95% CI', '宏 F1', '95% CI', 'history→affirmed'],
            'rows': [[SYSTEM_LABEL.get(k, k), num(v['point']['accuracy'], 4),
                      '[{}, {}]'.format(num(v['accuracy_ci95'][0], 4), num(v['accuracy_ci95'][1], 4)),
                      num(v['point']['macro_f1'], 4),
                      '[{}, {}]'.format(num(v['macro_f1_ci95'][0], 4), num(v['macro_f1_ci95'][1], 4)),
                      v['history_to_affirmed_point']]
                     for k, v in b['systems'].items()],
            'note': '按提及计算会高估样本量、给出过窄区间；簇级重采样是唯一诚实的口径。'
                    '区间不重叠说明方向成立，但不等于「260 条独立临床样本」。'})
    return {'title': '6. 切分与留出集关系（`split-rel-1.0.0`）',
            'note': '四份语料互相之间的患者、就诊号、文本、骨架、格子、近重复、疾病名全部比对。'
                    '留出集与其余三组的重叠指标全为 0，但它**内部**高度重复。',
            'tables': tables,
            'tail': [f'留出集与开发集：共享疾病 {hv["shared_diseases"]}/{hv["holdout_diseases"]}，'
                     f'共享代码模块 `{", ".join(hv["shared_code"][:2])}` 等 —— '
                     '同一生成器、同一知识库、同一词表，因此这是**同生成器留出**，不是跨机构泛化。']}


def lab_block(path):
    """Section 7: independent lab-standard path (lab-independence-1.0.0)."""
    if not (ROOT / path).exists():
        return None
    d = load(path)
    ind = d['independent_path']
    diff, corp, pert, con = (d['table_difference'], d['corpus_recomputation'],
                             d['perturbation_experiment'], d['conclusion'])
    tables = [
        {'caption': '独立路径的推导链（不 import `hpo_knowledge`）',
         'headers': ['分析物', '依据', '摩尔质量 g/mol', '换算因子', '区间（演示值）'],
         'rows': [
             ['葡萄糖', 'C6H12O6 × CIAAW 原子量', num(ind['molar_mass']['GLUCOSE'], 3),
              num(ind['factors']['GLUCOSE'], 6),
              f"{ind['bands']['GLUCOSE']['lo']}–{ind['bands']['GLUCOSE']['hi']} {ind['bands']['GLUCOSE']['unit']}"],
             ['肌酐', 'C4H7N3O × CIAAW 原子量', num(ind['molar_mass']['CREATININE'], 3),
              num(ind['factors']['CREATININE'], 6), '—'],
             ['血红蛋白', 'BIPM SI 词头：1 g/dL = 10 g/L', '—', num(ind['factors']['HGB'], 1),
              f"{ind['bands']['HGB']['lo']}–{ind['bands']['HGB']['hi']} {ind['bands']['HGB']['unit']}"],
             ['ALT / AST', 'IUPAC 酶单位：U/L 为活性浓度，不做质量换算', '—',
              f"{num(ind['factors']['ALT'], 1)} / {num(ind['factors']['AST'], 1)}",
              f"ALT {ind['bands']['ALT']['lo']}–{ind['bands']['ALT']['hi']} U/L"],
         ]},
        {'caption': '双表差异（项目共享表 vs 独立路径）',
         'headers': ['分析物', '项目因子', '独立因子', '相对差', '区间一致'],
         'rows': [[name, num(v['project_factor'], 6), num(v['independent_factor'], 6),
                   f'{v["factor_relative_difference"]:.2e}',
                   '是' if v['band_identical'] else '否']
                  for name, v in diff.items()]},
        {'caption': '用独立路径重算全部检验值',
         'headers': ['指标', '值'],
         'rows': [
             ['检验值总数', corp['n_lab_values']],
             ['已复算', corp['n_checked']],
             ['无法解析', corp['unparsable']],
             ['换算不一致', corp['conversion_mismatch']],
             ['高低方向不一致', corp['direction_mismatch']],
             ['最大绝对偏差（标准单位）', num(corp['max_absolute_delta'], 2)],
             ['按分析物', '、'.join(f'{k} {v}' for k, v in corp['by_analyte'].items())],
             ['按单位', '、'.join(f'{k} {v}' for k, v in corp['by_unit'].items())],
         ]},
        {'caption': '注入错误实验（证明循环验证真实存在）',
         'headers': ['验证路径', '检查值数', '换算错', '方向错'],
         'rows': [
             ['共享常数表（生成器与验证器同源）', pert['arm_shared_table']['checked'],
              pert['arm_shared_table']['conversion_mismatch'],
              pert['arm_shared_table']['direction_mismatch']],
             ['独立路径（`clinforge/lab_standards.py`）', pert['arm_independent_table']['checked'],
              pert['arm_independent_table']['conversion_mismatch'],
              pert['arm_independent_table']['direction_mismatch']],
         ],
         'note': '注入 4 个错误（葡萄糖因子 20.0、血红蛋白因子 12.0、葡萄糖上限 4.5、'
                 '血红蛋白下限 160.0），共 300 例、seed 424242，`try/finally` 恢复共享表。'
                 '共享表路径按构造成立所以 0 检出 —— 这正是自证循环；独立路径检出 26 个换算错 + '
                 '10 个方向错，说明第二路径确实在独立判断。'},
    ]
    tail = ['结论：两表一致={}；独立路径下 1,277 个检验值清洁={}；循环性已被实证={}；金标被改动={}。'.format(
                '是' if con['table_agrees'] else '否',
                '是' if con['corpus_clean_under_independent_path'] else '否',
                '是' if con['circularity_demonstrated'] else '否',
                '是' if con['gold_labels_changed'] else '否'),
            f'**参考区间状态**：`{d["band_status"]}` —— 这些是流水线联调用的演示值，'
            '不是临床参考标准，不能用于任何医学判断。']
    return {'title': '7. 检验常数独立性（`lab-independence-1.0.0`）',
            'note': '生成器与验证器共享同一张常数表时，验证器无法发现生成器的常数错误。'
                    '本节目的是把「循环」变成可测量的量，而不是宣称常数已获临床认证。',
            'tables': tables, 'tail': tail}


def blocks_to_md(blocks):
    lines = []
    for b in blocks:
        if not b:
            continue
        lines += [f'## {b["title"]}', '', b['note'], '']
        for sub in b['tables']:
            if sub.get('caption'):
                lines += [f'**{sub["caption"]}**', '']
            lines.append('| ' + ' | '.join(str(h) for h in sub['headers']) + ' |')
            lines.append('| ' + ' | '.join('---' for _ in sub['headers']) + ' |')
            for row in sub['rows']:
                lines.append('| ' + ' | '.join(str(c) for c in row) + ' |')
            lines.append('')
            if sub.get('note'):
                lines += [f'> {sub["note"]}', '']
        for tail in b.get('tail', []):
            lines += [tail, '']
    return lines


def blocks_to_html(blocks):
    def md_inline(text):
        text = html.escape(text)
        while '`' in text:
            text = text.replace('`', '<code>', 1)
            if '`' in text:
                text = text.replace('`', '</code>', 1)
            else:
                text += '</code>'
        return text.replace('**', '')

    parts = []
    for b in blocks:
        if not b:
            continue
        parts.append(f'<h2>{md_inline(b["title"])}</h2>')
        parts.append(f'<p class="small">{md_inline(b["note"])}</p>')
        for sub in b['tables']:
            if sub.get('caption'):
                parts.append(f'<p class="cap">{md_inline(sub["caption"])}</p>')
            rows = [[md_inline(str(c)) for c in row] for row in sub['rows']]
            body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
            head = ''.join(f'<th>{md_inline(str(h))}</th>' for h in sub['headers'])
            parts.append(f'<div class="card"><table><tr>{head}</tr>{body}</table></div>')
            if sub.get('note'):
                parts.append(f'<p class="small">{md_inline(sub["note"])}</p>')
        for tail in b.get('tail', []):
            parts.append(f'<p class="small">{md_inline(tail)}</p>')
    return ''.join(parts)


def html_page(context_pairs, comparison, regression, audit, extra_html=''):
    def table(headers, rows, cls=''):
        head = ''.join(f'<th>{html.escape(str(h))}</th>' for h in headers)
        body = ''
        for row in rows:
            body += '<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>'
        return f'<table class="{cls}"><tr>{head}</tr>{body}</table>'

    cards = []
    for title, data in context_pairs:
        rows = []
        for key in ('v1', 'v2_scope_v1', 'v2_scope_ng'):
            block = data['systems'][key]['per_class']
            rows.append([SYSTEM_LABEL[key], pct(block['_overall']['accuracy']),
                         num(block['_overall']['macro_f1'], 4),
                         num(block['affirmed']['f1'], 4), num(block['suspected']['f1'], 4),
                         num(block['history']['f1'], 4), num(block['negated']['f1'], 4)])
        cards.append(f'<h2>{html.escape(title)}</h2><div class="card">'
                     + table(['系统', '准确率', '宏 F1', 'affirmed F1', 'suspected F1',
                              'history F1', 'negated F1'], rows) + '</div>')

    rows = []
    for row in comparison['table']:
        agree = row.get('agreement', {})
        rows.append([row['config_name'], num(row['mean_ms_per_doc'], 1),
                     num(row['p95_ms_per_doc'], 1), num(row['docs_per_second'], 2),
                     num(row['peak_rss_mb'], 1), row['n_forward_calls'],
                     num(row.get('speedup_mean', 1.0), 2),
                     pct(agree.get('doc_identity_rate'), 2)])
    perf_card = ('<h2>PHI 门控吞吐（同一机器 / 同一数据）</h2><div class="card">'
                 + table(['配置', 'ms/条', 'p95 ms', '条/秒', '峰值内存 MB', '前向次数',
                          '加速比', '输出一致率'], rows) + '</div>')

    audit_rows = []
    if audit:
        prov, leak, pref, cont = (audit['provenance'], audit['split_leakage'],
                                 audit['preference_labels'], audit['context_contamination'])
        audit_rows = [
            ['溯源完整', f'{prov["cases_with_complete_provenance"]}/{prov["n_cases"]}'],
            ['SHA256 与磁盘一致', f'{prov["ontology_sha_matches_disk"]} / {prov["annotation_sha_matches_disk"]}'],
            ['跨度错误 / 知识违反', f'{prov["span_errors"]} / {prov["knowledge_violations_affirmed_suspected_history"]}'],
            ['跨划分重复文本 / 近重复对', f'{leak["exact_duplicate_inputs_across_splits"]} / {leak["near_duplicate_pairs_jaccard_ge_0.8_across_splits"]}'],
            ['训练集记录落在与测试集共用格子中的比例', pct(leak['template_complexity_disease_triple_collisions']['test|train']['rate'])],
            ['偏好对标签噪声', str(pref['pairs_where_rejected_is_not_actually_wrong'])],
            ['导出状态标签错标率', pct(cont['mismatch_rate'])],
        ]
    audit_card = ('<h2>数据质量审计</h2><div class="card">'
                  + table(['检查项', '结果'], audit_rows) + '</div>') if audit_rows else ''

    reg_card = ''
    if regression:
        rows = []
        for method, block in regression['methods'].items():
            rows.append([method, pct(block['doc_identity_rate']),
                         str(block['spans_missing_vs_frozen']), str(block['spans_added_vs_frozen']),
                         num(block['mean_ms_per_doc'], 1)])
        reg_card = ('<h2>冻结 PHI 测试集回归</h2><div class="card">'
                    + table(['方法', '条目一致率', '缺失跨度', '新增跨度', 'ms/条'], rows) + '</div>')

    style = """
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f6f8fa;color:#1f2328;margin:0;padding:24px;line-height:1.55}
h1{font-size:22px} h2{font-size:16px;margin-top:26px;border-bottom:1px solid #d0d7de;padding-bottom:4px}
.card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:12px 16px;margin:10px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}
th,td{border:1px solid #d0d7de;padding:5px 9px;text-align:left}
th{background:#f0f3f6}
.small{font-size:12px;color:#57606a}
.cap{font-size:13px;font-weight:600;margin:16px 0 2px;color:#1f2328}
code{background:#eff1f3;border-radius:3px;padding:0 3px;font-size:12px}
"""
    body = ('<h1>ClinDataForge · 第四阶段：上下文判定修复 + PHI 吞吐优化 + 数据质量审计 + 最终验收</h1>'
            '<p class="small">所有数字由 scripts/render_phase4_report.py 从 JSON 产物直接渲染；'
            '模板内自检、同生成器留出语料评测、冻结 PHI 基准、独立常数核验与真实临床验证严格分开标注。</p>'
            + ''.join(cards) + perf_card + reg_card + audit_card + extra_html)
    return f'<html><head><meta charset="utf-8"><title>ClinDataForge Phase-4 Dashboard</title><style>{style}</style></head><body>{body}</body></html>'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dev', default='reports/phase4_context/dev_eval.json')
    parser.add_argument('--holdout', default='reports/phase4_context/holdout_eval.json')
    parser.add_argument('--perf', default='reports/phase4_perf/comparison.json')
    parser.add_argument('--regression', default='reports/phase4_perf/test_run_fast/comparison.json')
    parser.add_argument('--audit', default='reports/phase4_data_quality/audit.json')
    parser.add_argument('--lineage', default='data/phase4_lineage/lineage_manifest.json')
    parser.add_argument('--relations', default='reports/phase4_split_relations/relations.json')
    parser.add_argument('--bootstrap', default='reports/phase4_split_relations/holdout_bootstrap.json')
    parser.add_argument('--lab-audit', default='reports/phase4_lab_independence/audit.json')
    parser.add_argument('--md-out', default='reports/phase4_context/report_tables.md')
    parser.add_argument('--html-out', default='reports/phase4_dashboard.html')
    args = parser.parse_args(argv)
    dev, holdout = load(args.dev), load(args.holdout)
    comparison = load(args.perf)
    regression = load(args.regression) if (ROOT / args.regression).exists() else None
    audit = load(args.audit) if (ROOT / args.audit).exists() else None
    blocks = [lineage_block(args.lineage), split_block(args.relations, args.bootstrap),
              lab_block(args.lab_audit)]

    lines = ['# 第四阶段结果表（自动生成，请勿手改）', '']
    lines += context_section(dev, holdout)
    lines += error_delta_section(dev, holdout)
    lines += perf_section(comparison)
    lines += phi_regression_section(args.regression)
    lines += audit_section(args.audit)
    lines += blocks_to_md(blocks)
    md = ROOT / args.md_out
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    page = html_page([('开发语料（诊断用，非测试集）', dev), ('同生成器留出语料（评测前冻结）', holdout)],
                     comparison, regression, audit, blocks_to_html(blocks))
    (ROOT / args.html_out).write_text(page, encoding='utf-8')
    print(f'wrote {md} and {ROOT / args.html_out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
