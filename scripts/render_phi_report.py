"""Render the phase-2 PHI comparison report from actual run artefacts.

Every number in the output is read from results.json / sweep.json. Nothing is
recomputed here and nothing is estimated; missing values render as "n/a".
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METHOD_NAMES = {'A': 'A 原规则', 'B': 'B Presidio', 'C': 'C GLiNER', 'D': 'D 融合（规则+GLiNER）'}
METRIC_ROWS = [
    ('精确跨度 Precision', lambda m: m['overall']['entity_exact']['precision']),
    ('精确跨度 Recall', lambda m: m['overall']['entity_exact']['recall']),
    ('精确跨度 F1', lambda m: m['overall']['entity_exact']['f1']),
    ('金标字符全部被掩码率（含PHI记录）', lambda m: m['overall']['all_gold_phi_masked_positive_rate']),
    ('全部实体精确识别率（含PHI记录）', lambda m: m['overall']['all_entities_exact_positive_rate']),
    ('金标字符残留率', lambda m: m['overall']['phi_character_residual_rate']),
    ('保护医学字符误删率', lambda m: m['overall']['protected_clinical_character_deletion_rate']),
    ('保护医学跨度受损率', lambda m: m['overall']['protected_clinical_span_damage_rate']),
    ('非PHI字符误删率', lambda m: m['overall']['non_phi_character_deletion_rate']),
    ('无PHI记录被任意掩码率', lambda m: m['overall']['negative_record_any_redaction_rate']),
]
PERF_ROWS = [
    ('初始化（秒）', lambda p: p['initialization_seconds'], '{:.2f}'),
    ('train 预热（秒）', lambda p: p['training_warmup_seconds'], '{:.3f}'),
    ('推理总时长（秒）', lambda p: p['inference_seconds'], '{:.2f}'),
    ('单文档时延中位数（毫秒）', lambda p: percentile(p['inference_seconds_each'], .5) * 1000, '{:.1f}'),
    ('吞吐（记录/秒）', lambda p: p['records_per_second'], '{:.2f}'),
    ('峰值进程 RSS（MB）', lambda p: p['peak_process_rss_bytes'] / 1048576, '{:.0f}'),
]


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def fmt(value, spec='{:.4f}'):
    return 'n/a' if value is None else spec.format(value)


def table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        out.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(out)


def bootstrap_row(name, comparison):
    metrics = comparison['metrics']
    cells = []
    for key, label in (('recall', '召回'), ('f1', 'F1'),
                       ('all_gold_phi_masked_positive_rate', '完整掩码率'),
                       ('protected_clinical_character_deletion_rate', '医学误删率')):
        value = metrics[key]
        interval = value['ci95_percentile']
        cells.append('%s Δ=%s [%s, %s]' % (label, fmt(value['delta_right_minus_left'], '{:+.4f}'),
                                           fmt(interval[0], '{:+.4f}'), fmt(interval[1], '{:+.4f}')))
    return [name] + cells


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', default='reports/phase2_phi_v1/test_run/results.json')
    parser.add_argument('--sweep', default='reports/phase2_dev_sweep/sweep.json')
    parser.add_argument('--selection', default='reports/phase2_dev_selection/selection.json')
    parser.add_argument('--audit', default='reports/phase2_dataset_audit/audit.json')
    parser.add_argument('--out', default='reports/phase2_phi_v1')
    args = parser.parse_args(argv)
    out = ROOT / args.out
    results = json.loads((ROOT / args.results).read_text(encoding='utf-8'))
    methods = results['methods']

    lines = ['# 第二阶段 PHI 对照结果（由实际运行产物生成）', '',
             '- 数据：`data/phase2_phi_v1/test.jsonl`（冻结测试集，%d 条记录）' % methods['A']['overall']['n_records'],
             '- 数据集 SHA256：%s' % results['dataset_sha256'][:16] + '…',
             '- 配置 SHA256：%s' % results['config_sha256'][:16] + '…',
             '- 协议与锁：docs/PHI_EVALUATION_PROTOCOL_CN.md（v2.1）、reports/phase2_phi_v1/frozen_experiment.json',
             '']
    lines.append('## 1. 主结果（冻结测试集，实体级精确跨度）')
    lines.append(table(['指标'] + [METHOD_NAMES[m] for m in ('A', 'B', 'C', 'D')],
                       [[label] + [fmt(fn(methods[m])) for m in ('A', 'B', 'C', 'D')]
                        for label, fn in METRIC_ROWS]))
    lines.append('')
    lines.append('计数：TP / FP / FN —— ' + '；'.join(
        '%s %d/%d/%d' % (METHOD_NAMES[m], methods[m]['overall']['entity_exact']['tp'],
                         methods[m]['overall']['entity_exact']['fp'],
                         methods[m]['overall']['entity_exact']['fn']) for m in ('A', 'B', 'C', 'D')))
    lines.append('')

    lines.append('## 2. 分类别结果（F1）')
    labels = sorted(methods['A']['overall']['per_label'])
    lines.append(table(['PHI 类别'] + [METHOD_NAMES[m] for m in ('A', 'B', 'C', 'D')] + ['测试集金标数'],
                       [[label] + [fmt(methods[m]['overall']['per_label'][label]['f1']) for m in ('A', 'B', 'C', 'D')]
                        + [str(methods['A']['overall']['per_label'][label]['tp'] + methods['A']['overall']['per_label'][label]['fn'])]
                        for label in labels]))
    lines.append('')

    lines.append('## 3. 分语言结果')
    for language, name in (('en', '英文 ASQ-PHI'), ('zh', '中文独立模板')):
        lines.append('### %s' % name)
        lines.append(table(['指标'] + [METHOD_NAMES[m] for m in ('A', 'B', 'C', 'D')],
                           [['记录数'] + [str(methods[m]['by_language'].get(language, {}).get('n_records', 0)) for m in ('A', 'B', 'C', 'D')],
                            ['Recall'] + [fmt(methods[m]['by_language'].get(language, {}).get('entity_exact', {}).get('recall')) for m in ('A', 'B', 'C', 'D')],
                            ['Precision'] + [fmt(methods[m]['by_language'].get(language, {}).get('entity_exact', {}).get('precision')) for m in ('A', 'B', 'C', 'D')],
                            ['F1'] + [fmt(methods[m]['by_language'].get(language, {}).get('entity_exact', {}).get('f1')) for m in ('A', 'B', 'C', 'D')]]))
        lines.append('')

    lines.append('## 4. 资源消耗（每方法独立进程，顺序单文档）')
    lines.append(table(['指标'] + [METHOD_NAMES[m] for m in ('A', 'B', 'C', 'D')],
                       [[label] + [fmt(fn(methods[m]['performance']), spec) for m in ('A', 'B', 'C', 'D')]
                        for label, fn, spec in PERF_ROWS]))
    lines.append('')

    if results.get('paired_cluster_bootstrap'):
        lines.append('## 5. 配对 cluster bootstrap（2000 次，按语言分层，差值 = 后者 − 前者）')
        rows = []
        for key in ('B_minus_A', 'C_minus_A', 'D_minus_A', 'D_minus_B', 'D_minus_C'):
            if key in results['paired_cluster_bootstrap']:
                rows.append(bootstrap_row(key.replace('_minus_', ' − '), results['paired_cluster_bootstrap'][key]))
        lines.append(table(['比较', '召回 Δ', 'F1 Δ', '完整掩码率 Δ', '医学误删率 Δ'], rows))
        lines.append('')

    (out / 'report_tables.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    html = render_html(results, ROOT / args.sweep, ROOT / args.selection, ROOT / args.audit)
    (out / 'phi_comparison.html').write_text(html, encoding='utf-8')
    print('wrote', out / 'report_tables.md', 'and', out / 'phi_comparison.html')


def render_html(results, sweep_path, selection_path, audit_path):
    methods = results['methods']
    sweep = json.loads(sweep_path.read_text(encoding='utf-8'))['rows'] if sweep_path.exists() else []
    selection = json.loads(selection_path.read_text(encoding='utf-8')) if selection_path.exists() else {}
    audit = json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}

    def cell(value):
        return 'n/a' if value is None else '{:.4f}'.format(value)

    rows = []
    for label, fn in METRIC_ROWS:
        rows.append('<tr><td>%s</td>%s</tr>' % (label, ''.join(
            '<td class="num">%s</td>' % cell(fn(methods[m])) for m in ('A', 'B', 'C', 'D'))))
    per_label = sorted(methods['A']['overall']['per_label'])
    label_rows = ''.join('<tr><td>%s</td>%s<td class="num">%d</td></tr>' % (
        label, ''.join('<td class="num">%s</td>' % cell(methods[m]['overall']['per_label'][label]['f1'])
                       for m in ('A', 'B', 'C', 'D')),
        methods['A']['overall']['per_label'][label]['tp'] + methods['A']['overall']['per_label'][label]['fn'])
        for label in per_label)
    frontier = ''.join('<tr><td>C</td><td>%.2f</td><td class="num">%s</td><td class="num">%s</td>'
                       '<td class="num">%s</td><td class="num">%s</td></tr>' % (
                           row['gliner_threshold'], cell(row['recall']), cell(row['precision']),
                           cell(row['f1']), cell(row['protected_deletion_rate']))
                       for row in sorted([r for r in sweep if r['method'] == 'C'], key=lambda r: r['gliner_threshold']))
    frontier_d = ''.join('<tr><td>D</td><td>%.2f</td><td class="num">%s</td><td class="num">%s</td>'
                         '<td class="num">%s</td><td class="num">%s</td></tr>' % (
                             row['gliner_threshold'], cell(row['recall']), cell(row['precision']),
                             cell(row['f1']), cell(row['protected_deletion_rate']))
                         for row in sorted([r for r in sweep if r['method'] == 'D' and r['presidio_threshold'] is None],
                                           key=lambda r: r['gliner_threshold']))
    perf = ''.join('<tr><td>%s</td>%s</tr>' % (label, ''.join(
        '<td class="num">%s</td>' % fmt(fn(methods[m]['performance']), spec) for m in ('A', 'B', 'C', 'D')))
        for label, fn, spec in PERF_ROWS)
    bootstrap = ''
    for key in ('B_minus_A', 'C_minus_A', 'D_minus_A', 'D_minus_C'):
        if key in results.get('paired_cluster_bootstrap', {}):
            metrics = results['paired_cluster_bootstrap'][key]['metrics']
            bootstrap += '<tr><td>%s</td>%s</tr>' % (key.replace('_minus_', ' − '), ''.join(
                '<td class="num">%s<br><span class="ci">[%s, %s]</span></td>' % (
                    fmt(metrics[k]['delta_right_minus_left'], '{:+.4f}'),
                    fmt(metrics[k]['ci95_percentile'][0], '{:+.4f}'),
                    fmt(metrics[k]['ci95_percentile'][1], '{:+.4f}'))
                for k in ('recall', 'f1', 'all_gold_phi_masked_positive_rate',
                          'protected_clinical_character_deletion_rate')))
    verdict = audit.get('verdict', 'n/a')
    return HTML_TEMPLATE.format(
        n_records=methods['A']['overall']['n_records'],
        n_entities=methods['A']['overall']['entity_exact']['tp'] + methods['A']['overall']['entity_exact']['fn'],
        verdict=verdict,
        main_rows=''.join(rows), label_rows=label_rows, frontier=frontier + frontier_d,
        perf_rows=perf, bootstrap=bootstrap,
        chosen=json.dumps(selection.get('per_method', {}), ensure_ascii=False, indent=1))


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>ClinDataForge PHI 方法对照（冻结测试集）</title>
<style>
:root {{ color-scheme: dark; }}
body {{ background:#12151c; color:#e6e9ef; font-family:"Segoe UI","Microsoft YaHei",sans-serif; margin:0; padding:28px; line-height:1.6; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:17px; margin:26px 0 8px; color:#9fd0ff; }}
.sub {{ color:#93a0b4; font-size:13px; margin-bottom:18px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; margin-bottom:8px; }}
th,td {{ border:1px solid #2c3341; padding:6px 9px; text-align:left; }}
th {{ background:#1b2130; color:#cfe0f5; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
tr:nth-child(even) td {{ background:#171c26; }}
.ci {{ color:#8b96a8; font-size:11px; }}
.warn {{ background:#3a2b16; border-left:3px solid #e0a33a; padding:10px 14px; margin:14px 0; font-size:13px; }}
pre {{ background:#0e1219; padding:10px; overflow:auto; font-size:12px; color:#b9c6d8; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:14px 0; }}
.card {{ background:#1b2130; border:1px solid #2c3341; border-radius:6px; padding:10px 12px; }}
.card b {{ display:block; font-size:12px; color:#93a0b4; font-weight:500; }}
.card span {{ font-size:20px; color:#7fd6a0; }}
</style></head><body>
<h1>ClinDataForge · PHI 识别四路方法对照</h1>
<div class="sub">冻结测试集 {n_records} 条记录 / {n_entities} 个金标 PHI 实体 · 全部数字来自一次实际运行 · 数据集独立审计结论：{verdict}</div>
<div class="warn"><b>阅读前提：</b>数据为 100% 合成（ASQ-PHI 第三方合成基准 + 本仓库独立中文模板），标签为机器标签、未经医生复核。
所有指标只描述该合成分布上的行为，<b>不等于真实患者病历的脱敏准确率</b>，也不能据此宣称满足 HIPAA Safe Harbor。</div>
<h2>1. 主结果（实体级精确跨度）</h2>
<table><tr><th>指标</th><th>A 原规则</th><th>B Presidio</th><th>C GLiNER</th><th>D 融合</th></tr>{main_rows}</table>
<h2>2. 分类别 F1</h2>
<table><tr><th>类别</th><th>A</th><th>B</th><th>C</th><th>D</th><th>金标数</th></tr>{label_rows}</table>
<h2>3. 资源消耗</h2>
<table><tr><th>指标</th><th>A</th><th>B</th><th>C</th><th>D</th></tr>{perf_rows}</table>
<h2>4. 配对 cluster bootstrap（2000 次）</h2>
<table><tr><th>比较</th><th>召回 Δ</th><th>F1 Δ</th><th>完整掩码率 Δ</th><th>医学误删率 Δ</th></tr>{bootstrap}</table>
<h2>5. 开发集阈值前沿（C 与 D）</h2>
<table><tr><th>方法</th><th>阈值</th><th>Recall</th><th>Precision</th><th>F1</th><th>医学误删率</th></tr>{frontier}</table>
<h2>6. 最终选定配置</h2>
<pre>{chosen}</pre>
</body></html>
"""


if __name__ == '__main__':
    main()
