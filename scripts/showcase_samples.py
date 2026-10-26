"""Generate the rare-disease sample showcase document.

Reads the frozen synthetic corpus (``data/phase3_synth/gen/notes.jsonl``) plus one or
more pipeline output directories, and renders ``docs/RARE_DISEASE_SAMPLES_CN.md``.

The document is meant to let a reader audit the corpus without running anything:
every case shows the raw note, the gold HPO annotations with provenance, and the
pipeline's own extraction so the two can be diffed by eye.

Usage
-----
    python -m scripts.showcase_samples \
        --gen data/phase3_synth/gen/notes.jsonl \
        --kb  data/phase3_synth/kb/hpo_snapshot.json \
        --pipeline-v1 data/phase3_synth/pipeline_out \
        --pipeline-v2 data/phase4_synth_v2/pipeline_out \
        --out docs/RARE_DISEASE_SAMPLES_CN.md

``--pipeline-v2`` is optional: when the directory is missing or empty the
before/after section is skipped instead of emitting placeholder numbers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STATUS_ZH = {
    'affirmed': '现症（affirmed）',
    'suspected': '疑似（suspected）',
    'history': '既往（history）',
    'negated': '否定（negated）',
}

STATUS_BADGE = {
    'affirmed': '+',
    'suspected': '?',
    'history': '~',
    'negated': '-',
}


# --------------------------------------------------------------------------- io


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_index(pipeline_dir: Path | None) -> dict[str, dict]:
    """Map record_id -> structured record for one pipeline run."""
    if pipeline_dir is None:
        return {}
    target = pipeline_dir / 'structured.jsonl'
    if not target.exists():
        return {}
    return {row['record_id']: row for row in load_jsonl(target)}


def load_kb_snapshot(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


# ------------------------------------------------------------------ selection


def status_mix(note: dict) -> set[str]:
    return {entity['status'] for entity in note['entities'] if entity.get('status')}


def pick_samples(notes: list[dict], available: set[str]) -> dict[str, dict]:
    """Deterministically choose the cases shown in the document.

    ``available`` is the set of record ids present in a pipeline output; cases are
    restricted to it so the document never prints "not found in pipeline output"
    for a hand-picked example.
    """

    def usable(note: dict) -> bool:
        return not available or note['record_id'] in available

    all_four = {'affirmed', 'suspected', 'history', 'negated'}
    chosen: dict[str, dict] = {}

    for note in notes:
        if not usable(note) or note['language'] != 'zh':
            continue
        if status_mix(note) == all_four and not note.get('with_phi'):
            chosen['zh_full'] = note
            break

    for note in notes:
        if not usable(note) or note['language'] != 'zh' or not note.get('with_phi'):
            continue
        chosen['zh_phi'] = note
        break

    for note in notes:
        if not usable(note) or note['language'] != 'en':
            continue
        if status_mix(note) >= {'affirmed', 'negated', 'suspected'}:
            chosen['en_mixed'] = note
            break

    return chosen


def find_context_regressions(
    notes: list[dict], v1: dict[str, dict], v2: dict[str, dict], limit: int = 3
) -> list[dict]:
    """Gold-history mentions that v1 called affirmed and v2 called history."""
    findings = []
    if not v1 or not v2:
        return findings

    for note in notes:
        record_id = note['record_id']
        left, right = v1.get(record_id), v2.get(record_id)
        if not left or not right:
            continue
        right_map = {(m['start'], m['end']): m for m in right.get('phenotypes', [])}
        for entity in note['entities']:
            if entity.get('label') != 'PHENOTYPE' or entity.get('status') != 'history':
                continue
            key = (entity['start'], entity['end'])
            after = right_map.get(key)
            if after is None or after.get('status') != 'history':
                continue
            before_status = _lookup_status(left, key)
            if before_status == 'affirmed':
                findings.append(
                    {
                        'record_id': record_id,
                        'text': note['text'],
                        'mention': entity['text'],
                        'start': entity['start'],
                        'end': entity['end'],
                        'hp_id': entity.get('hp_id'),
                        'before': before_status,
                        'after': after.get('status'),
                    }
                )
                break
        if len(findings) >= limit:
            break
    return findings


def _lookup_status(structured: dict, key: tuple[int, int]) -> str | None:
    for mention in structured.get('phenotypes', []):
        if (mention['start'], mention['end']) == key:
            return mention.get('status')
    return None


# ------------------------------------------------------------------ rendering


def context_window(text: str, start: int, end: int, width: int = 26) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    snippet = text[left:right]
    return ('…' if left else '') + snippet + ('…' if right < len(text) else '')


def render_header(counts: dict) -> list[str]:
    return [
        '# 罕见病知识约束合成数据：样本与溯源（中文）',
        '',
        '> 本文件由 `python -m scripts.showcase_samples` 自动生成，请勿手工编辑。',
        '> 所有病例均为**程序化生成的合成文本**，患者编号、姓名、日期、病历号均为虚构占位，',
        '> 不对应任何真实个体。文本中的临床描述只用于检验数据流水线，**不构成医学建议**。',
        '',
        '## 0. 语料概况',
        '',
        f'- 病例总数：**{counts["records"]}**',
        f'- 实体总数：**{counts["entities"]}**',
        f'- 语言分布：中文 {counts["zh"]} / 英文 {counts["en"]}',
        f'- 含虚构 PHI 的病例：**{counts["with_phi"]}**（占比 {counts["phi_rate"]:.1%}）',
        f'- 覆盖罕见病：**{counts["diseases"]}** 种（人工核验后进入知识库）',
        '',
        '四类上下文状态的约定：',
        '',
        '| 状态 | 含义 | 生成器表达方式（示例） |',
        '| --- | --- | --- |',
        '| `affirmed` | 现症，本次就诊确认存在 | 「查体发现低血糖」 |',
        '| `suspected` | 疑似，尚未确诊 | 「另疑有耳廓后旋」「尚需评估有无…」 |',
        '| `history` | 既往史，曾经发生但当前不确认 | 「既往曾有体重增加」 |',
        '| `negated` | 明确否定 | 「无吸吮无力」「否认家族成员类似表现」 |',
        '',
    ]


def render_disease_table(kb: dict, notes: list[dict]) -> list[str]:
    if not kb:
        return []

    per_disease: dict[str, dict] = {}
    for note in notes:
        bucket = per_disease.setdefault(
            note['disease_id'],
            {'zh': note.get('disease_name_zh') or '', 'en': note.get('disease_name', ''), 'n': 0},
        )
        bucket['n'] += 1

    provenance = kb.get('provenance') or {}
    annotation = provenance.get('annotation_file') or {}

    lines = [
        '## 1. 罕见病知识库与 HPO 溯源',
        '',
        '知识库由 HPO 官方发布文件离线构建，每个表型都保留 HPO ID、证据代码与文献来源。',
        '生成器只能使用知识库中登记的表型，验证器在**不读取生成器内部状态**的前提下独立比对，',
        '因此“表型是否属于该病”这一约束是可追溯、可反驳的。',
        '',
    ]
    if annotation:
        lines.extend(
            [
                f'- 注释文件：`{annotation.get("name", "")}`（版本 {annotation.get("version", "")}）',
                f'- 下载地址：{annotation.get("url", "")}',
                f'- 文件 SHA256：`{annotation.get("sha256", "")}`',
                f'- 快照内疾病数：{kb.get("n_diseases", "")}，表型词条数：{kb.get("n_terms", "")}',
                '',
            ]
        )
    lines.extend(
        [
            '本项目只使用其中**人工核验过的 16 种罕见病**作为生成目标，'
            '每种疾病贡献约 150 条病例：',
            '',
            '| # | 疾病（英文） | 中文名 | 编码 | KB 可用表型数 | 起病 HPO | 病例数 |',
            '| --- | --- | --- | --- | --- | --- | --- |',
        ]
    )
    kb_diseases = kb.get('diseases') or {}
    ordered = sorted(per_disease, key=lambda d: (-per_disease[d]['n'], d))
    for idx, disease_id in enumerate(ordered, 1):
        info = kb_diseases.get(disease_id) or {}
        name = info.get('disease_name') or per_disease[disease_id]['en']
        name_zh = per_disease[disease_id]['zh']
        n_pheno = len(info.get('phenotypes') or {})
        onsets = info.get('onsets') or []
        onset_text = '、'.join(f'`{o}`' for o in onsets) if onsets else '—'
        lines.append(
            f'| {idx} | {name} | {name_zh} | `{disease_id}` | {n_pheno} | {onset_text} | '
            f'{per_disease[disease_id]["n"]} |'
        )
    lines.append('')
    return lines


def render_gold_table(note: dict) -> list[str]:
    lines = [
        '| 实体（原文） | 上下文状态 | HPO ID | 证据代码 | 文献 |',
        '| --- | --- | --- | --- | --- |',
    ]
    for entity in note['entities']:
        if entity.get('label') != 'PHENOTYPE':
            continue
        lines.append(
            '| {text} | {status} | `{hp}` | {ev} | {ref} |'.format(
                text=entity['text'],
                status=STATUS_ZH.get(entity.get('status'), entity.get('status') or ''),
                hp=entity.get('hp_id') or '',
                ev=entity.get('evidence') or '',
                ref=entity.get('reference') or '',
            )
        )
    lines.append('')
    return lines


def render_pipeline_table(structured: dict | None, note: dict) -> list[str]:
    if not structured:
        return ['（该记录未出现在流水线输出中）', '']

    gold = {(e['start'], e['end']): e for e in note['entities'] if e.get('label') == 'PHENOTYPE'}
    lines = [
        '| 实体（流水线抽取） | 状态 | HPO ID | 对齐金标 |',
        '| --- | --- | --- | --- |',
    ]
    for mention in structured.get('phenotypes', []):
        key = (mention['start'], mention['end'])
        reference = gold.get(key)
        if reference is None:
            verdict = '未对齐（跨度过期或边界不同）'
        else:
            status_ok = reference.get('status') == mention.get('status')
            hp_ok = reference.get('hp_id') == mention.get('hp_id')
            if status_ok and hp_ok:
                verdict = '状态一致、HPO 一致'
            elif hp_ok:
                verdict = f'状态不一致（金标 `{reference.get("status")}`）'
            elif status_ok:
                verdict = f'HPO 不一致（金标 `{reference.get("hp_id")}`）'
            else:
                verdict = (
                    f'状态与 HPO 均不一致（金标 `{reference.get("status")}` / '
                    f'`{reference.get("hp_id")}`）'
                )
        lines.append(
            '| {text} | {status} | `{hp}` | {verdict} |'.format(
                text=mention['text'],
                status=STATUS_ZH.get(mention.get('status'), mention.get('status') or ''),
                hp=mention.get('hp_id') or '',
                verdict=verdict,
            )
        )
    lines.append('')

    missing = [e for key, e in gold.items() if key not in {(m['start'], m['end']) for m in structured.get('phenotypes', [])}]
    if missing:
        names = '、'.join(f'{e["text"]}（`{e.get("hp_id", "")}`）' for e in missing)
        lines.extend([f'金标中未被抽取到的表型：{names}', ''])
    return lines


def annotate(text: str, entities: list[dict]) -> str:
    """Render the note with status badges inserted after each gold mention."""
    parts = []
    cursor = 0
    for entity in sorted(entities, key=lambda e: e['start']):
        if entity.get('label') != 'PHENOTYPE':
            continue
        if entity['start'] < cursor:
            continue
        parts.append(text[cursor : entity['start']])
        badge = STATUS_BADGE.get(entity.get('status'), '')
        parts.append(f'{entity["text"]}[{badge}]')
        cursor = entity['end']
    parts.append(text[cursor:])
    return ''.join(parts)


def render_case(title: str, note: dict, structured: dict | None, intro: list[str]) -> list[str]:
    lines = [f'## {title}', '']
    lines.extend(intro)
    lines.extend(
        [
            '',
            f'- 病例编号：`{note["record_id"]}`（患者组 `{note["patient_group"]}`，'
            f'就诊组 `{note["encounter_group"]}`）',
            f'- 疾病：{note.get("disease_name_zh") or note.get("disease_name")}'
            f'（`{note["disease_id"]}`），模板族 `{note["template_family"]}`，'
            f'复杂度 `{note["complexity"]}`',
            f'- 起病 HPO：{("`" + note["onset_hp"] + "`") if note.get("onset_hp") else "—（知识库未登记起病年龄）"}',
            '',
            '### 原始病历文本',
            '',
            '```text',
            note['text'],
            '```',
            '',
            '### 带上下文标注的版本',
            '',
            '标注记号：`[+]` 现症、`[?]` 疑似、`[~]` 既往、`[-]` 否定。',
            '',
            '```text',
            annotate(note['text'], note['entities']),
            '```',
            '',
            '### 金标表型与溯源',
            '',
        ]
    )
    lines.extend(render_gold_table(note))
    lines.append('### 流水线抽取结果')
    lines.append('')
    lines.extend(render_pipeline_table(structured, note))
    return lines


def load_accepted_count(pipeline_dir: Path | None) -> int | None:
    """Read ``accepted_rows`` from a pipeline audit so no count is typed by hand."""
    if pipeline_dir is None:
        return None
    target = pipeline_dir / 'audit.json'
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding='utf-8')).get('accepted_rows')
    except (ValueError, OSError):
        return None


def phi_regions(text: str, masked: str) -> list[dict]:
    """Recover PHI spans by aligning the raw note against the masked note.

    The masker replaces a span with a fixed placeholder (``[NAME]`` and friends),
    so raw offsets do not survive. ``SequenceMatcher`` gives us the replaced
    source ranges back; the placeholder on the masked side names the label.
    """
    import difflib

    matcher = difflib.SequenceMatcher(None, text, masked, autojunk=False)
    regions = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'replace' or i2 <= i1:
            continue
        placeholder = masked[j1:j2].strip()
        label = placeholder.strip('[]') if placeholder.startswith('[') else 'MASKED'
        regions.append({'start': i1, 'end': i2, 'label': label, 'raw': text[i1:i2]})
    return regions


def render_phi_case(note: dict, structured: dict | None) -> list[str]:
    lines = [
        '## 4. PHI 脱敏示例（虚构占位值）',
        '',
        '生成器会在部分病例中注入**虚构**的直接标识符，用来检验 PHI 检测与掩码链路。',
        '下列值全部由模板生成（如 `SYN-xxxx`、虚构姓名与日期），不对应任何真实个体；',
        '把它们写进文档不会泄露隐私，但也不构成任何隐私保护证明——真实患者数据从未进入本项目。',
        '',
        f'- 病例编号：`{note["record_id"]}`',
        '',
        '### 脱敏前',
        '',
        '```text',
        note['text'],
        '```',
        '',
        '### 脱敏后（流水线输出）',
        '',
    ]
    if structured and structured.get('masked_text'):
        lines.extend(['```text', structured['masked_text'], '```', ''])
    else:
        lines.extend(['（未找到该记录的流水线输出）', ''])

    detected = (structured or {}).get('phi_spans_found') or 0
    detected_count = detected if isinstance(detected, int) else len(detected)
    lines.append(f'流水线报告的 PHI 跨度数量：**{detected_count}**')
    lines.append('')

    if structured and structured.get('masked_text'):
        regions = phi_regions(note['text'], structured['masked_text'])
        if regions:
            disease_en = (note.get('disease_name') or '').lower()
            lines.append('### 被替换的片段')
            lines.append('')
            lines.append('| # | 类型 | 原文片段 | 字符区间 | 掩码占位符 | 复核意见 |')
            lines.append('| --- | --- | --- | --- | --- | --- |')
            has_false_positive = False
            for idx, region in enumerate(regions, 1):
                raw = region['raw']
                shown = raw[:2] + '*' * max(0, len(raw) - 2) if len(raw) > 2 else raw
                opinion = ''
                if region['label'] == 'NAME' and disease_en and raw.lower() in disease_en:
                    opinion = '**误报**：这是疾病名而非人名'
                    has_false_positive = True
                lines.append(
                    f'| {idx} | {region["label"]} | `{shown}` | '
                    f'[{region["start"]}, {region["end"]}) | `[{region["label"]}]` | {opinion} |'
                )
            lines.append('')
            if has_false_positive:
                lines.extend(
                    [
                        '上面标了误报的那一条是真实的代价：PII 模型把首字母大写的英文疾病名判成人名。',
                        '掩码偏保守的方向对隐私是安全的，但会削弱脱敏文本的可用性；'
                        '这类误报已经计入第二阶段 PHI 评测的 FP（D 方法 precision 0.7566）。',
                        '',
                    ]
                )
        elif detected_count:
            lines.append(
                '（掩码文本与原文差异无法逐段对齐，本表跳过；报告数量仍以流水线为准。）'
            )
            lines.append('')
    return lines


def render_regressions(findings: list[dict]) -> list[str]:
    if not findings:
        return [
            '## 5. 上下文误判修复个案',
            '',
            '（未提供两版流水线输出，本节跳过。）',
            '',
        ]
    lines = [
        '## 5. 上下文误判修复个案',
        '',
        '以下个案均为金标 `history`：修复前被判成 `affirmed`（把既往史当成现症），',
        '修复后恢复为 `history`。右侧展示触发词到实体的实际文本窗口，',
        '可以直接看出旧版固定字符窗口截断在哪里。',
        '',
    ]
    for idx, item in enumerate(findings, 1):
        lines.extend(
            [
                f'### 个案 {idx}：`{item["record_id"]}` — {item["mention"]}（`{item["hp_id"]}`）',
                '',
                f'- 修复前：`{item["before"]}` → 修复后：`{item["after"]}`（金标 `history`）',
                '',
                '```text',
                context_window(item['text'], item['start'], item['end'], width=34),
                '```',
                '',
            ]
        )
    return lines


def render_footer(accepted: int | None) -> list[str]:
    accepted_text = f'{accepted} 条接受样本' if accepted else '接受样本'
    return [
        '## 6. 效力边界（必读）',
        '',
        '**关于上面这些案例**：它们是按“状态齐全 / 含 PHI / 中英对照”的目的**挑选**出来的，',
        '用于让人肉眼检查数据形态与抽取链路，**不是随机抽样，也不能代表整体指标**。',
        f'整体指标请看 `reports/phase4_pipeline_eval/`（九段流水线在 {accepted_text}上的统计）',
        '与 `reports/phase4_context/report_tables.md`（四类上下文判定）。',
        '',
        '| 层级 | 本项目做到什么 | 不能声称什么 |',
        '| --- | --- | --- |',
        '| 模板内自检 | 表型 F1、上下文准确率等在生成模板内部统计 | 不等于独立评测，模板与金标同源 |',
        '| 第三方合成数据独立评测 | ASQ-PHI v1（MIT）1,051 条英文第三方合成数据上评测 PHI | 不代表真实病历分布 |',
        '| 真实临床数据验证 | **未进行**，无授权数据 | 不能声称临床可用 |',
        '| 模型训练 | **未进行**，仅导出候选数据 | 不能声称任何训练收益 |',
        '',
        '复现命令见 `README.md` 与 `docs/CONTEXT_AND_PERF_CN.md`。',
        '',
    ]


# ----------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gen', default='data/phase3_synth/gen/notes.jsonl')
    parser.add_argument('--kb', default='data/phase3_synth/kb/hpo_snapshot.json')
    parser.add_argument('--pipeline-v1', default='data/phase3_synth/pipeline_out')
    parser.add_argument('--pipeline-v2', default='data/phase4_synth_v2/pipeline_out')
    parser.add_argument('--out', default='docs/RARE_DISEASE_SAMPLES_CN.md')
    args = parser.parse_args()

    notes = load_jsonl(ROOT / args.gen)
    kb = load_kb_snapshot(ROOT / args.kb)
    v1 = load_index(ROOT / args.pipeline_v1)
    v2 = load_index(ROOT / args.pipeline_v2)

    entities = sum(len([e for e in n['entities'] if e.get('label') == 'PHENOTYPE']) for n in notes)
    counts = {
        'records': len(notes),
        'entities': entities,
        'zh': sum(1 for n in notes if n['language'] == 'zh'),
        'en': sum(1 for n in notes if n['language'] == 'en'),
        'with_phi': sum(1 for n in notes if n.get('with_phi')),
        'phi_rate': (sum(1 for n in notes if n.get('with_phi')) / len(notes)) if notes else 0.0,
        'diseases': len({n['disease_id'] for n in notes}),
    }

    available = set(v2) or set(v1)
    chosen = pick_samples(notes, available)
    findings = find_context_regressions(notes, v1, v2)

    lines = render_header(counts)
    lines.extend(render_disease_table(kb, notes))

    if 'zh_full' in chosen:
        note = chosen['zh_full']
        lines.extend(
            render_case(
                '2. 中文门诊病例：四类状态齐全',
                note,
                v2.get(note['record_id']) or v1.get(note['record_id']),
                [
                    '这条样本同时含现症、疑似、既往、否定四类表达，是上下文判定最容易出错的形态：',
                    '同一段文字里“有”和“无”交替出现，且既往史线索词与表型之间隔着逗号与分号。',
                    '',
                    '> 提醒：本章及后续案例都是**挑选**出来的展示样本，不是随机抽样，不能当作整体指标。',
                ],
            )
        )

    if 'en_mixed' in chosen:
        note = chosen['en_mixed']
        lines.extend(
            render_case(
                '3. 英文病例：跨语言一致性检查',
                note,
                v2.get(note['record_id']) or v1.get(note['record_id']),
                [
                    '英文模板的难点在缩写与逗号列表：`no fever, rash, or vomiting` 里的三个表型',
                    '共享同一个否定触发词，作用域必须延伸到列表末尾而不是第一个逗号。',
                    '这条样本同时覆盖现症、疑似与否定三类，可用来对照中英判定逻辑是否一致。',
                ],
            )
        )

    if 'zh_phi' in chosen:
        note = chosen['zh_phi']
        lines.extend(render_phi_case(note, v2.get(note['record_id']) or v1.get(note['record_id'])))

    lines.extend(render_regressions(findings))
    lines.extend(render_footer(load_accepted_count(ROOT / args.pipeline_v2)))

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'wrote {out_path} ({len(lines)} lines, {len(findings)} regressions shown)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
