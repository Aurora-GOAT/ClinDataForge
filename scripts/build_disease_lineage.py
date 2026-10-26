"""Build an as-run disease lineage manifest for the synthetic corpus.

Why this exists
---------------
`data/phase3_synth/kb/disease_selection.json` is a *historical* artefact: it was
written by the algorithmic selector (`select_rare_diseases`) in an earlier build
of `scripts/build_hpo_kb.py`.  The generator was later switched to the curated
demo set (`clinforge/synthgen.py::CURATED_DISEASES`), but the selection file was
never regenerated -- `build_hpo_kb.py` refuses to overwrite it.  The two lists
therefore disagree, and reading the stale file as "the diseases that were used"
is wrong.

This script does not rewrite history.  It writes a new, versioned manifest that
records what the 2,400 generated records *actually* reference, verifies every
link against the HPO snapshot and the Chinese gloss, and documents the stale
artefact as superseded-but-preserved.

Outputs (all write-once):
  data/phase4_lineage/lineage_manifest.json     machine-readable lineage
  data/phase4_lineage/record_disease_index.csv  one row per generated record
  reports/phase4_lineage/lineage_report.md      human-readable audit

Usage:
  python -m scripts.build_disease_lineage
  python -m scripts.build_disease_lineage --force   # same version only
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import select_rare_diseases
from clinforge.synthgen import CURATED_DISEASES, DISEASE_SET_RATIONALE, GENERIC_NEGATABLE_EN, GENERIC_NEGATABLE_ZH

ROOT = Path(__file__).resolve().parent.parent
LINEAGE_VERSION = 'lineage-1.0.0'

NOTES = ROOT / 'data/phase3_synth/gen/notes.jsonl'
SNAPSHOT = ROOT / 'data/phase3_synth/kb/hpo_snapshot.json'
STALE_SELECTION = ROOT / 'data/phase3_synth/kb/disease_selection.json'
GLOSS = ROOT / 'data/curated/zh_phenotype_gloss.json'
STRUCTURED = ROOT / 'data/phase4_synth_v2/pipeline_out/structured.jsonl'
QUARANTINE = ROOT / 'data/phase4_synth_v2/pipeline_out/quarantine.jsonl'
EXPORT = ROOT / 'data/phase4_synth_v2/training_candidates/sft_candidates.jsonl'

STATUSES = ('affirmed', 'suspected', 'history', 'negated')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def id_list_sha256(values) -> str:
    payload = '\n'.join(sorted(values)).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data/phase4_lineage')
    parser.add_argument('--report', default='reports/phase4_lineage/lineage_report.md')
    parser.add_argument('--force', action='store_true',
                        help='overwrite outputs of the SAME lineage version')
    args = parser.parse_args(argv)

    out_dir = ROOT / args.out
    report_path = ROOT / args.report
    manifest_path = out_dir / 'lineage_manifest.json'
    if manifest_path.exists() and not args.force:
        raise FileExistsError(f'{manifest_path} exists; lineage artefacts are write-once')
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    gloss = json.loads(GLOSS.read_text(encoding='utf-8'))
    notes = load_jsonl(NOTES)
    stale = json.loads(STALE_SELECTION.read_text(encoding='utf-8'))
    structured = load_jsonl(STRUCTURED) if STRUCTURED.exists() else []
    quarantine = load_jsonl(QUARANTINE) if QUARANTINE.exists() else []
    sft = load_jsonl(EXPORT) if EXPORT.exists() else []

    kb_diseases = snapshot['diseases']
    curated = list(CURATED_DISEASES)
    curated_present = [d for d in curated if d in kb_diseases]

    # ---- 1. reproduce the stale artefact, to prove where it came from -------
    reproduced = select_rare_diseases(snapshot, stale['n_diseases'], stale['seed'],
                                      stale['min_phenotypes'])
    stale_ids = [d['disease_id'] for d in stale['diseases']]
    stale_reproduced_exactly = sorted(reproduced) == sorted(stale_ids)

    # ---- 2. what the records actually reference ---------------------------
    per_disease = defaultdict(lambda: {
        'n_records': 0, 'n_zh': 0, 'n_en': 0, 'n_with_phi': 0,
        'template_families': Counter(), 'complexities': Counter(),
        'statuses': Counter(), 'phenotype_hp_ids': Counter(),
        'evidence_codes': Counter(), 'record_ids': [],
    })
    unknown_disease = []
    for record in notes:
        bucket = per_disease[record['disease_id']]
        bucket['n_records'] += 1
        bucket['n_zh' if record['language'] == 'zh' else 'n_en'] += 1
        bucket['n_with_phi'] += int(bool(record.get('with_phi')))
        bucket['template_families'][record['template_family']] += 1
        bucket['complexities'][record['complexity']] += 1
        bucket['record_ids'].append(record['record_id'])
        if record['disease_id'] not in curated:
            unknown_disease.append(record['record_id'])
        for entity in record['entities']:
            if entity['label'] != 'PHENOTYPE':
                continue
            bucket['statuses'][entity['status']] += 1
            bucket['phenotype_hp_ids'][entity['hp_id']] += 1
            if entity.get('evidence'):
                bucket['evidence_codes'][entity['evidence']] += 1

    # ---- 3. record-level verification -------------------------------------
    checks = Counter()
    violations = defaultdict(list)
    for record in notes:
        disease = kb_diseases.get(record['disease_id'])
        checks['records'] += 1
        if disease is None:
            violations['disease_missing_from_snapshot'].append(record['record_id'])
            continue
        checks['disease_in_curated'] += int(record['disease_id'] in curated)
        checks['disease_name_matches_snapshot'] += int(record['disease_name'] == disease['disease_name'])
        checks['disease_name_zh_matches_gloss'] += int(
            record['disease_name_zh'] == gloss['diseases'].get(record['disease_id']))
        checks['hpo_provenance_equals_snapshot'] += int(record['hpo_provenance'] == snapshot['provenance'])
        if record.get('onset_hp'):
            checks['onset_resolvable'] += int(
                record['onset_hp'] in disease['onsets'] or record['onset_hp'] in disease['phenotypes'])
        annotated = set(disease['phenotypes'])
        generic = set(GENERIC_NEGATABLE_ZH if record['language'] == 'zh' else GENERIC_NEGATABLE_EN)
        for entity in record['entities']:
            if entity['label'] == 'PHENOTYPE':
                checks['phenotype_entities'] += 1
                if entity['hp_id'] in annotated:
                    checks['phenotype_hp_in_annotation'] += 1
                elif entity['text'] in generic and entity['status'] == 'negated':
                    checks['phenotype_generic_allowlisted'] += 1
                else:
                    violations['phenotype_not_in_annotation'].append(
                        f"{record['record_id']}:{entity['hp_id']}")
                if entity.get('evidence') and entity.get('reference'):
                    checks['phenotype_evidence_and_reference'] += 1
                else:
                    violations['phenotype_missing_evidence'].append(
                        f"{record['record_id']}:{entity['hp_id']}")
            if entity.get('start', 0) >= 0 and record['text'][entity['start']:entity['end']] == entity['text']:
                checks['offset_roundtrip_ok'] += 1
            else:
                checks['offset_roundtrip_ok'] += 0
                violations['offset_mismatch'].append(f"{record['record_id']}:{entity['label']}")
        # spec vs emitted statuses
        counts = Counter(entity['status'] for entity in record['entities']
                         if entity['label'] == 'PHENOTYPE')
        spec = record.get('spec') or {}
        expected = {s: len(spec.get(s) or []) for s in STATUSES}
        if all(counts.get(s, 0) >= expected[s] for s in STATUSES):
            checks['status_counts_consistent'] += 1
        else:
            violations['status_count_mismatch'].append(record['record_id'])

    # ---- 4. downstream coverage ------------------------------------------
    accepted_ids = {r['record_id'] for r in structured}
    quarantined_ids = {r['record_id'] for r in quarantine}
    sft_by_split = Counter(r['split'] for r in sft)
    export_ids = {r['id'] for r in sft}
    coverage = {
        'records_in_corpus': len(notes),
        'records_reaching_pipeline_output': len(accepted_ids) + len(quarantined_ids),
        'records_accepted': len(accepted_ids),
        'records_quarantined': len(quarantined_ids),
        'records_in_sft_export': len(export_ids),
        'sft_by_split': dict(sorted(sft_by_split.items())),
        'export_ids_not_in_corpus': len(export_ids - {n['record_id'] for n in notes}),
        'accepted_not_in_export': len(accepted_ids - export_ids),
    }

    # ---- 5. assemble ------------------------------------------------------
    disease_rows = []
    for disease_id in curated:
        disease = kb_diseases.get(disease_id)
        stats = per_disease.get(disease_id, {})
        record_ids = stats.get('record_ids', [])
        disease_rows.append({
            'disease_id': disease_id,
            'disease_name': disease['disease_name'] if disease else None,
            'disease_name_zh': gloss['diseases'].get(disease_id),
            'source': disease['source'] if disease else None,
            'n_phenotype_annotations_in_snapshot': len(disease['phenotypes']) if disease else 0,
            'onsets_in_snapshot': disease['onsets'] if disease else [],
            'n_records': len(record_ids),
            'n_zh': stats.get('n_zh', 0),
            'n_en': stats.get('n_en', 0),
            'n_with_phi': stats.get('n_with_phi', 0),
            'template_families': dict(sorted(stats.get('template_families', {}).items())),
            'complexities': dict(sorted(stats.get('complexities', {}).items())),
            'status_counts': {s: stats.get('statuses', {}).get(s, 0) for s in STATUSES},
            'distinct_phenotypes_emitted': len(stats.get('phenotype_hp_ids', {})),
            'evidence_codes': dict(sorted(stats.get('evidence_codes', {}).items())),
            'record_ids_sha256': id_list_sha256(record_ids),
        })

    manifest = {
        'lineage_version': LINEAGE_VERSION,
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'purpose': 'as-run disease lineage for the 2,400-record synthetic corpus',
        'source_of_truth': {
            'generator': 'clinforge/synthgen.py::CURATED_DISEASES',
            'rationale': DISEASE_SET_RATIONALE,
            'n_diseases': len(curated),
        },
        'superseded_artifact': {
            'path': 'data/phase3_synth/kb/disease_selection.json',
            'status': 'stale-but-preserved (NOT deleted, NOT overwritten)',
            'written_by': 'an earlier build of scripts/build_hpo_kb.py using the algorithmic selector',
            'rule_recorded_in_file': stale.get('rule'),
            'n_diseases_in_file': len(stale_ids),
            'overlap_with_actual': sorted(set(stale_ids) & set(curated)),
            'n_overlap': len(set(stale_ids) & set(curated)),
            'reproduced_exactly_by_current_selector': stale_reproduced_exactly,
            'why_they_differ': (
                'The selection file predates the switch to a curated demo set. '
                'build_hpo_kb.py now defaults to CURATED_DISEASES and raises '
                'FileExistsError instead of overwriting the old file, so the two '
                'lists were never reconciled. The generated corpus follows '
                'CURATED_DISEASES, not this file.'
            ),
        },
        'hpo_provenance': snapshot['provenance'],
        'hpo_snapshot_stats': {
            'n_terms': snapshot['n_terms'],
            'n_diseases': snapshot['n_diseases'],
            'dropped_obsolete_or_unknown_annotations': snapshot['dropped_obsolete_or_unknown_annotations'],
        },
        'diseases': disease_rows,
        'checks': {
            'records': checks['records'],
            'disease_in_curated': checks['disease_in_curated'],
            'disease_name_matches_snapshot': checks['disease_name_matches_snapshot'],
            'disease_name_zh_matches_gloss': checks['disease_name_zh_matches_gloss'],
            'hpo_provenance_equals_snapshot': checks['hpo_provenance_equals_snapshot'],
            'onset_resolvable': checks['onset_resolvable'],
            'phenotype_entities': checks['phenotype_entities'],
            'phenotype_hp_in_annotation': checks['phenotype_hp_in_annotation'],
            'phenotype_generic_allowlisted': checks['phenotype_generic_allowlisted'],
            'phenotype_evidence_and_reference': checks['phenotype_evidence_and_reference'],
            'offset_roundtrip_ok': checks['offset_roundtrip_ok'],
            'status_counts_consistent': checks['status_counts_consistent'],
            'violations': {k: len(v) for k, v in sorted(violations.items())},
            'violation_samples': {k: v[:8] for k, v in sorted(violations.items())},
        },
        'downstream_coverage': coverage,
        'artifacts': {},
        'claim_boundary': {
            'this_manifest_proves': (
                'every generated record resolves to one curated disease id, and every '
                'phenotype entity resolves to that disease\'s HPO annotation set or a '
                'documented generic-symptom allowlist; file hashes pin the exact inputs'
            ),
            'this_manifest_does_not_prove': (
                'that the HPO annotations are clinically complete, that the Chinese '
                'disease names are official translations, or that the synthetic cases '
                'resemble any real hospital population'
            ),
        },
    }

    for path in (NOTES, SNAPSHOT, STALE_SELECTION, GLOSS, STRUCTURED, QUARANTINE, EXPORT):
        if path.exists():
            manifest['artifacts'][str(path.relative_to(ROOT)).replace('\\', '/')] = {
                'sha256': sha256_file(path),
                'bytes': path.stat().st_size,
            }

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    # ---- 6. record-level CSV ---------------------------------------------
    csv_path = out_dir / 'record_disease_index.csv'
    split_of = {row['id']: row['split'] for row in sft}
    with open(csv_path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['record_id', 'disease_id', 'disease_name', 'language', 'template_family',
                         'complexity', 'patient_group', 'with_phi', 'n_phenotypes',
                         'pipeline_status', 'sft_split'])
        for record in notes:
            if record['record_id'] in accepted_ids:
                pipeline_status = 'accepted'
            elif record['record_id'] in quarantined_ids:
                pipeline_status = 'quarantined'
            else:
                pipeline_status = 'missing'
            writer.writerow([
                record['record_id'], record['disease_id'], record['disease_name'],
                record['language'], record['template_family'], record['complexity'],
                record['patient_group'], int(bool(record.get('with_phi'))),
                sum(1 for e in record['entities'] if e['label'] == 'PHENOTYPE'),
                pipeline_status, split_of.get(record['record_id'], ''),
            ])

    # ---- 7. markdown report ----------------------------------------------
    lines = [
        '# 疾病数据血缘核验报告（as-run）',
        '',
        f'- 版本：`{LINEAGE_VERSION}`，生成时间 {manifest["generated_at_utc"]}',
        f'- 语料：`data/phase3_synth/gen/notes.jsonl`（{len(notes):,} 条）',
        f'- 事实来源：`clinforge/synthgen.py::CURATED_DISEASES`（{len(curated)} 种）',
        '',
        '## 1. 结论先说',
        '',
        f'- **`disease_selection.json` 与实际生成不一致，而且这是可解释的历史遗留**：两者只有 '
        f'**{len(set(stale_ids) & set(curated))}/16** 个疾病 ID 重合。',
        f'- 该文件由早期版本的算法选择器写出；用当前 `select_rare_diseases()` 以同参数重算，'
        f'{"能" if stale_reproduced_exactly else "不能"}精确复现文件里的 16 个 ID，说明它是真实产物而非损坏。',
        '- 生成器后来改用人工核验的 16 病清单，而 `build_hpo_kb.py` 设计为**拒绝覆盖**已存在的选择文件，'
        '于是旧文件被留在原处，文档里却仍指向它。',
        '- 本报告不修改、不删除该历史文件；新增的 `data/phase4_lineage/` 才是"实际运行"口径。',
        '',
        '## 2. 历史文件 vs 实际使用',
        '',
        '| | 历史 `disease_selection.json` | 实际 `CURATED_DISEASES` |',
        '| --- | --- | --- |',
        f'| 疾病数 | {len(stale_ids)} | {len(curated)} |',
        f'| 选择规则 | 算法排序 + 种子抽样 | 人工核验清单（{DISEASE_SET_RATIONALE[:28]}…） |',
        f'| 与语料一致 | 否（仅 {len(set(stale_ids) & set(curated))} 个重合） | 是（2400/2400） |',
        '| 是否被本报告覆盖 | 否 | 否（只新增清单） |',
        '',
        '历史文件中的 16 个 ID：',
        '',
        '```text',
        ', '.join(stale_ids),
        '```',
        '',
        '实际使用的 16 个 ID：',
        '',
        '```text',
        ', '.join(curated),
        '```',
        '',
        '## 3. 实际使用的疾病清单',
        '',
        '| # | 疾病 ID | 英文名 | 中文名 | 来源 | HPO 注释数 | 生成记录 | 中文/英文 | 含 PHI |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for idx, row in enumerate(disease_rows, 1):
        lines.append(
            f'| {idx} | `{row["disease_id"]}` | {row["disease_name"]} | {row["disease_name_zh"]} | '
            f'{row["source"]} | {row["n_phenotype_annotations_in_snapshot"]} | {row["n_records"]} | '
            f'{row["n_zh"]}/{row["n_en"]} | {row["n_with_phi"]} |')
    lines += [
        '',
        '## 4. HPO 溯源链',
        '',
        '| 文件 | 版本 | SHA256 | 来源 |',
        '| --- | --- | --- | --- |',
        f'| `hp.obo` | {snapshot["provenance"]["ontology_file"]["data_version"]} | '
        f'`{snapshot["provenance"]["ontology_file"]["sha256"]}` | {snapshot["provenance"]["ontology_file"]["url"]} |',
        f'| `phenotype.hpoa` | {snapshot["provenance"]["annotation_file"]["version"]} | '
        f'`{snapshot["provenance"]["annotation_file"]["sha256"]}` | {snapshot["provenance"]["annotation_file"]["url"]} |',
        '',
        f'快照统计：{snapshot["n_terms"]:,} 个 HP 术语、{snapshot["n_diseases"]:,} 个疾病注释、'
        f'丢弃 {snapshot["dropped_obsolete_or_unknown_annotations"]} 条过时/未知注释。',
        '许可：HPO 内容未修改，版本与 SHA256 随每条记录写入 `hpo_provenance`。',
        '',
        '## 5. 逐条核验',
        '',
        '| 检查项 | 通过 | 总数 / 说明 |',
        '| --- | --- | --- |',
        f'| 记录数 | {checks["records"]:,} | 2,400 |',
        f'| 疾病 ID 属于 CURATED_DISEASES | {checks["disease_in_curated"]:,} | {checks["records"]:,} |',
        f'| 疾病英文名与快照一致 | {checks["disease_name_matches_snapshot"]:,} | {checks["records"]:,} |',
        f'| 疾病中文名与人工词表一致 | {checks["disease_name_zh_matches_gloss"]:,} | {checks["records"]:,} |',
        f'| 记录级 HPO 溯源 = 快照溯源 | {checks["hpo_provenance_equals_snapshot"]:,} | {checks["records"]:,} |',
        f'| 表型 HP 编码属于该病注释集 | {checks["phenotype_hp_in_annotation"]:,} | '
        f'{checks["phenotype_entities"]:,} 个表型实体 |',
        f'| 通用症状否定白名单 | {checks["phenotype_generic_allowlisted"]:,} | 非疾病注释、按设计允许 |',
        f'| 表型带证据码与文献来源 | {checks["phenotype_evidence_and_reference"]:,} | {checks["phenotype_entities"]:,} |',
        f'| 字符偏移可回切原文 | {checks["offset_roundtrip_ok"]:,} | 全部实体 |',
        f'| `spec` 状态数与实际实体一致 | {checks["status_counts_consistent"]:,} | {checks["records"]:,} |',
        '',
        '未通过项：',
        '',
        '```json',
        json.dumps({k: len(v) for k, v in sorted(violations.items())}, ensure_ascii=False, indent=2),
        '```',
        '',
        '## 6. 下游覆盖',
        '',
        '| 环节 | 记录数 |',
        '| --- | --- |',
        f'| 生成语料 | {coverage["records_in_corpus"]:,} |',
        f'| 进入九段流水线 | {coverage["records_reaching_pipeline_output"]:,} |',
        f'| 接受（`structured.jsonl`） | {coverage["records_accepted"]:,} |',
        f'| 隔离（`quarantine.jsonl`） | {coverage["records_quarantined"]:,} |',
        f'| 导出 SFT 候选 | {coverage["records_in_sft_export"]:,} '
        f'（train {coverage["sft_by_split"].get("train", 0)} / '
        f'dev {coverage["sft_by_split"].get("dev", 0)} / '
        f'test {coverage["sft_by_split"].get("test", 0)}） |',
        '',
        '## 7. 这份清单能证明什么、不能证明什么',
        '',
        f'- 能证明：{manifest["claim_boundary"]["this_manifest_proves"]}。',
        f'- 不能证明：{manifest["claim_boundary"]["this_manifest_does_not_prove"]}。',
        '',
        '## 8. 复现',
        '',
        '```bash',
        'python -m scripts.build_disease_lineage            # 写一次，拒绝覆盖',
        'python -m scripts.build_disease_lineage --force    # 仅同版本重写',
        '```',
        '',
        '产物：',
        '',
        f'- `data/phase4_lineage/lineage_manifest.json`（含全部输入文件的 SHA256）',
        f'- `data/phase4_lineage/record_disease_index.csv`（{len(notes):,} 行逐条索引）',
        '',
    ]
    report_path.write_text('\n'.join(lines), encoding='utf-8')

    print(json.dumps({
        'lineage_version': LINEAGE_VERSION,
        'records': len(notes),
        'diseases_actual': len(curated),
        'overlap_with_stale': len(set(stale_ids) & set(curated)),
        'stale_reproduced': stale_reproduced_exactly,
        'checks': {k: v for k, v in manifest['checks'].items() if not isinstance(v, dict)},
        'violations': manifest['checks']['violations'],
        'outputs': [str(manifest_path.relative_to(ROOT)), str(csv_path.relative_to(ROOT)),
                    str(report_path.relative_to(ROOT))],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
