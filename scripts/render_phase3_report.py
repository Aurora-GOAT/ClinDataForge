"""Render the phase-3 (synthesis + pipeline) HTML quality dashboard.

Inputs: reports/phase3_synth_validation/validation_report.json,
        reports/phase3_pipeline_eval/pipeline_eval.json,
        data/phase3_synth/pipeline_out/audit.json
Output: reports/phase3_synth_dashboard.html (self-contained, no network).
"""
from __future__ import annotations
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CSS = """
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f6f8fa;color:#1f2328;margin:0;padding:24px;line-height:1.55}
h1{font-size:22px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #d0d7de;padding-bottom:4px}
.card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:14px 18px;margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}
th,td{border:1px solid #d0d7de;padding:5px 9px;text-align:left}
th{background:#f0f3f6}
.ok{color:#1a7f37;font-weight:600} .warn{color:#9a6700;font-weight:600} .bad{color:#cf222e;font-weight:600}
.bar{background:#e7ebef;border-radius:4px;height:14px;position:relative;min-width:120px}
.bar>span{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:#4c9aff}
.small{font-size:12px;color:#57606a}
.tag{display:inline-block;background:#ddf4ff;border-radius:10px;padding:1px 8px;font-size:12px;margin:1px}
"""


def esc(x):
    return html.escape(str(x))


def pct(x):
    return '—' if x is None else f'{100*x:.2f}%'


def main():
    val = json.loads((ROOT/'reports/phase3_synth_validation/validation_report.json').read_text(encoding='utf-8'))
    ev = json.loads((ROOT/'reports/phase3_pipeline_eval/pipeline_eval.json').read_text(encoding='utf-8'))
    audit = json.loads((ROOT/'data/phase3_synth/pipeline_out/audit.json').read_text(encoding='utf-8'))
    h = ['<html><head><meta charset="utf-8"><title>ClinDataForge Phase-3 Dashboard</title>',
         f'<style>{CSS}</style></head><body>']
    h.append('<h1>ClinDataForge · 知识约束合成 + 结构化质量流水线（第三阶段）</h1>')
    h.append(f'<p class="small">{esc(val["provenance"]["credit"])} ｜ '
             f'本页所有数字来自本地实际运行产物；PHI 独立指标见第二阶段报告。</p>')

    h.append('<h2>1. 合成数据质量（独立验证器）</h2><div class="card"><table>')
    h.append('<tr><th>指标</th><th>值</th><th>判定</th></tr>')
    rows = [
        ('病例数', val['n_records'], ''),
        ('跨度完整性错误', val['span_integrity_errors'], 'ok' if val['span_integrity_errors'] == 0 else 'bad'),
        ('知识约束违反（ affirmed/suspected/history 表型不在疾病注释集 ）', val['knowledge_violations'],
         'ok' if val['knowledge_violations'] == 0 else 'bad'),
        ('检验方向/换算一致性错误', val['lab_errors'], 'ok' if val['lab_errors'] == 0 else 'bad'),
        ('被使用的不同 HP 表型数', val['phenotype_use']['distinct_hp_used'], ''),
        ('人工复核队列（分层抽样+异常，PENDING_HUMAN）', val['human_review_queue_size'], ''),
    ]
    for name, value, cls in rows:
        h.append(f'<tr><td>{esc(name)}</td><td>{esc(value)}</td>'
                 f'<td class="{cls}">{"通过" if cls=="ok" else ("需处理" if cls=="bad" else "—")}</td></tr>')
    nd = val['near_duplicate']
    h.append(f'<tr><td>同疾病骨架近重复（5-gram Jaccard 均值 / ≥0.7 占比）</td>'
             f'<td>{nd["overall_mean"]:.4f} / {pct(nd["overall_share_ge_0_7"])}</td><td class="ok">多样性达标</td></tr>')
    h.append('</table></div>')

    h.append('<h2>2. 疾病与表型覆盖</h2><div class="card"><table>')
    h.append('<tr><th>疾病</th><th>注释表型数</th><th>被使用</th><th>注释覆盖率</th></tr>')
    for did, c in val['coverage'].items():
        h.append(f'<tr><td>{esc(did)} · {esc(c["disease_name"][:48])}</td><td>{c["n_annotated"]}</td>'
                 f'<td>{c["n_used"]}</td><td><div class="bar"><span style="width:{100*c["coverage_of_annotation"]:.0f}%"></span></div>'
                 f' {pct(c["coverage_of_annotation"])}</td></tr>')
    h.append('</table></div>')

    h.append('<h2>3. 流水线算法指标（模板内自检，非独立临床准确率）</h2><div class="card"><table>')
    h.append('<tr><th>指标</th><th>Precision</th><th>Recall</th><th>F1</th><th>说明</th></tr>')
    ph, dz = ev['phenotype_extraction'], ev['disease_mention_extraction']
    dd = ev['dedup_pairs']
    h.append(f'<tr><td>表型实体抽取（精确跨度+HP编码）</td><td>{pct(ph["precision"])}</td><td>{pct(ph["recall"])}</td>'
             f'<td>{pct(ph["f1"])}</td><td>tp={ph["tp"]} fp={ph["fp"]} fn={ph["fn"]}</td></tr>')
    h.append(f'<tr><td>疾病名提及抽取</td><td>{pct(dz["precision"])}</td><td>{pct(dz["recall"])}</td>'
             f'<td>{pct(dz["f1"])}</td><td>—</td></tr>')
    h.append(f'<tr><td>近重复判定（160 标注对）</td><td>{pct(dd["precision"])}</td><td>{pct(dd["recall"])}</td>'
             f'<td>{pct(dd["f1"])}</td><td>{esc(ev["dedup_pairs"].get("per_kind_correct"))}</td></tr>')
    lab = ev['lab_standardisation']
    h.append(f'<tr><td>检验标准化准确率</td><td colspan="3">{pct(lab["std_accuracy"])}（n={lab["n_gold"]}）</td>'
             f'<td>按分析物：{esc(lab["by_analyte"])}</td></tr>')
    h.append(f'<tr><td>上下文状态判定准确率（在匹配到的提及上）</td><td colspan="3">{pct(ev["context_status_accuracy_on_matched"])}</td>'
             f'<td> affirmed/suspected/history/negated</td></tr>')
    pg = ev['phi_gate_synthetic']
    h.append(f'<tr><td>合成 PHI 掩码覆盖率</td><td colspan="3">{pct(pg["gold_phi_masking_rate"])}（n={pg["gold_phi_entities"]}）</td>'
             f'<td>独立测试集指标以第二阶段为准</td></tr>')
    h.append('</table></div>')

    h.append('<h2>4. 流水线运行审计</h2><div class="card">')
    h.append(f'<p>输入 {audit["input_rows"]} 条 → 接受 {audit["accepted_rows"]} / 隔离 {audit["quarantined_rows"]} '
             f'｜ 去重隔离 {audit["duplicate_rows_quarantined"]} ｜ 复核队列 {audit["review_queue_rows"]} ｜ '
             f'总耗时 {audit.get("wall_seconds")}s ｜ 峰值内存 {audit.get("peak_rss_mb")}MB</p>')
    h.append('<table><tr><th>阶段</th><th>均值(ms)</th><th>p95(ms)</th></tr>')
    for stage, p in ev['stage_performance'].items():
        h.append(f'<tr><td>{esc(stage)}</td><td>{p["mean_ms"]}</td><td>{p["p95_ms"]}</td></tr>')
    h.append('</table></div>')

    h.append('<h2>5. 局限（如实）</h2><div class="card"><ul>')
    for item in [
        '第 3 节为模板内自检：金标来自同一生成器，系统性高估真实临床文本上的抽取能力；独立证据见第二阶段 PHI 基准。',
        '合成文本来自模板组合，语言多样性有限；骨架近重复 p95 仍存在模板痕迹。',
        '检验参考区间为演示用通行值，非任一机构标准；未包含药物剂量与诊断标准（禁止编造）。',
        '人工复核队列尚未由人工完成审核（PENDING_HUMAN）。',
    ]:
        h.append(f'<li>{esc(item)}</li>')
    h.append('</ul></div></body></html>')
    (ROOT/'reports/phase3_synth_dashboard.html').write_text(''.join(h), encoding='utf-8')
    print('wrote reports/phase3_synth_dashboard.html')


if __name__ == '__main__':
    main()
