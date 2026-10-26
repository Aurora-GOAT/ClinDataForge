"""Dashboard from explicit experiment inputs; no hidden historical reads."""
import argparse
import html
import json
from pathlib import Path


def _read_json(path):
    def reject_nonfinite(_):
        raise ValueError("Non-finite report value")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_nonfinite)


def _safe(value):
    return html.escape(str(value))


def render_dashboard(benchmark, *, stress=None, public_aggregate=None):
    metrics, audit = benchmark["metrics"], benchmark["pipeline_audit"]
    rows = "".join(
        f'<tr><td>{html.escape(label)}</td><td>{value["precision"]:.1%}</td>'
        f'<td>{value["recall"]:.1%}</td><td>{value["f1"]:.1%}</td>'
        f'<td>{_safe(value["tp"])}</td><td>{_safe(value["fp"])}</td><td>{_safe(value["fn"])}</td></tr>'
        for label, value in metrics.items())
    stress_section = ""
    if stress is not None:
        score = stress["pipeline_phi_span_exact"]
        stress_section = (f'<section><h2>指定的合成压力测试</h2><p>{_safe(stress["n_cases"])}条病例，'
            f'{_safe(stress["n_phi_gold"])}个PHI标注；Precision {score["precision"]:.1%}，'
            f'Recall {score["recall"]:.1%}，F1 {score["f1"]:.1%}，漏检 {_safe(score["fn"])} 个实体。'
            '这不是独立临床验证，不能用于真实患者脱敏。</p></section>')
    public_section = ""
    if public_aggregate is not None:
        public_section = (f'<section><h2>指定的公开演示衍生数据汇总</h2><p>'
            f'{_safe(public_aggregate["rows"])}条记录，{_safe(public_aggregate["unique_subject_ids"])}个不同subject ID，'
            f'{_safe(public_aggregate["diagnosis_links"])}条诊断关联。这里只复述指定报告；'
            '来源核验以对应的输入指纹和独立审计记录为准。</p></section>')
    cards = "".join(f'<article><small>{html.escape(label)}</small><strong>{_safe(audit[field])}</strong></article>'
        for label, field in (("输入记录", "input_rows"), ("处理成功", "processed_rows"),
            ("质控通过", "accepted_rows"), ("隔离", "quarantined_rows")))
    issue_summary = html.escape(json.dumps(audit["operator_issue_counts"], ensure_ascii=False))
    return f'''<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClinDataForge | 可复现审计报告</title><style>
body{{font:16px system-ui,"Microsoft YaHei",sans-serif;background:#f5f7fb;color:#162636;margin:0}}
header{{background:#112b3b;color:white;padding:28px}}main{{max-width:1100px;margin:24px auto;padding:0 18px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px}}
article,section{{background:white;padding:18px;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:18px;overflow:auto}}
small,strong{{display:block}}strong{{font-size:28px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:12px 8px;text-align:left;border-bottom:1px solid #e5e8ef}}.warning{{padding:15px;background:#fff4d6}}
</style><header><h1>ClinDataForge · 医疗数据质量审计</h1><p>个人工程研究项目 · 阶段一验收</p></header><main>
<p class="warning">模板合成基准及程序标签只支持受限算子回归。系统尚未通过独立PHI验收；当前正文与SFT出口关闭，隔离区仅输出元数据。不能安全处理真实患者病历。</p>
<div class="cards">{cards}</div><section><h2>合成基准算子指标</h2><table><thead><tr><th>方法</th><th>Precision</th><th>Recall</th><th>F1</th><th>TP</th><th>FP</th><th>FN</th></tr></thead><tbody>{rows}</tbody></table></section>
{stress_section}{public_section}<section><h2>自动质量标志（不等于人工医学真值）</h2><p>{issue_summary}</p></section>
<p>仅使用命令行显式提供的报告；无外部网络资源。项目与蚂蚁集团无关联，没有执行大模型训练。</p></main></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="reports/demo_run/synthetic_benchmark.json")
    parser.add_argument("--stress", help="Explicit stress report; omitted means no stress section")
    parser.add_argument("--public-aggregate", help="Explicit public aggregate; omitted means no public-data section")
    parser.add_argument("--out", default="reports/demo_run/dashboard.html")
    args = parser.parse_args(argv)
    document = render_dashboard(_read_json(args.benchmark),
        stress=_read_json(args.stress) if args.stress else None,
        public_aggregate=_read_json(args.public_aggregate) if args.public_aggregate else None)
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(document)
    print(args.out)


if __name__ == "__main__":
    main()