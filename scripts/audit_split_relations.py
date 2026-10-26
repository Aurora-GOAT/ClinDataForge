"""Strict train/dev/test vs context-holdout relation audit.

What this answers
-----------------
1. Do the exported splits share patients, encounters, exact text, skeletons or
   near-duplicate notes?
2. How much of the (template, complexity, disease) space is reused across
   splits, and how often does the disease name appear verbatim in the input
   (a shortcut for the `disease_suspected` field of the gold answer)?
3. How independent is the 260-note context holdout really?  It was frozen
   before evaluation and it uses new seeds and new templates, but it is built
   by the same `CaseBuilder`, from the same 16 diseases and the same Chinese
   gloss.  This script quantifies that overlap instead of asserting it away.

Nothing is overwritten. Outputs:
  reports/phase4_split_relations/relations.json
  reports/phase4_split_relations/report.md

Usage:
  python -m scripts.audit_split_relations
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.context_scope import CUE_SETS
from clinforge.synthgen import CURATED_DISEASES

ROOT = Path(__file__).resolve().parent.parent
RELATION_VERSION = 'split-rel-1.0.0'
NEAR_DUP_THRESHOLD = 0.80
SHINGLE_K = 4
MAX_DF = 40


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def norm_text(text: str) -> str:
    return re.sub(r'\s+', '', text.lower())


def shingles(text: str, k: int = SHINGLE_K) -> set[str]:
    s = norm_text(text)
    if len(s) <= k:
        return {s}
    return {s[i:i + k] for i in range(len(s) - k + 1)}


def skeleton(record: dict) -> str:
    """Entity spans replaced by their label, digits collapsed.

    Two notes with the same skeleton share the sentence frame and the entity
    layout; only the surface terms differ.
    """
    parts, pos = [], 0
    for entity in sorted(record['entities'], key=lambda x: x['start']):
        parts.append(record['text'][pos:entity['start']])
        parts.append(f'|{entity["label"]}|')
        pos = entity['end']
    parts.append(record['text'][pos:])
    return re.sub(r'\d+', '#', re.sub(r'\s+', ' ', ''.join(parts)))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def pair_overlap(groups: dict[str, set], names: list[str]) -> dict:
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            out[f'{a}|{b}'] = len(groups[a] & groups[b])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='reports/phase4_split_relations')
    parser.add_argument('--near-dup-threshold', type=float, default=NEAR_DUP_THRESHOLD)
    args = parser.parse_args(argv)

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    notes = {r['record_id']: r for r in load_jsonl(ROOT / 'data/phase3_synth/gen/notes.jsonl')}
    sft = load_jsonl(ROOT / 'data/phase4_synth_v2/training_candidates/sft_candidates.jsonl')
    holdout = load_jsonl(ROOT / 'data/phase4_context/holdout_notes.jsonl')
    structured_path = ROOT / 'data/phase4_synth_v2/pipeline_out/structured.jsonl'
    structured = {r['record_id']: r for r in load_jsonl(structured_path)} if structured_path.exists() else {}

    split_of = {row['id']: row['split'] for row in sft}
    docs = []
    for record_id, split in split_of.items():
        record = notes[record_id]
        docs.append({
            'id': record_id, 'corpus': split, 'text': record['text'],
            'disease_id': record['disease_id'], 'disease_name': record['disease_name'],
            'disease_name_zh': record.get('disease_name_zh') or '',
            'language': record['language'], 'template_family': record['template_family'],
            'complexity': record['complexity'], 'patient_group': record['patient_group'],
            'encounter_group': record.get('encounter_group') or '',
            'n_entities': len(record['entities']),
            'entities': record['entities'],
            'masked_text': structured.get(record_id, {}).get('masked_text'),
        })
    for record in holdout:
        docs.append({
            'id': record['record_id'], 'corpus': 'holdout', 'text': record['text'],
            'disease_id': record['disease_id'], 'disease_name': record['disease_name'],
            'disease_name_zh': '',
            'language': record['language'], 'template_family': record['template_family'],
            'complexity': 'n/a', 'patient_group': record['patient_group'],
            'encounter_group': record.get('encounter_group') or '',
            'n_entities': len(record['entities']),
            'entities': record['entities'],
            'masked_text': None,
        })

    corpora = ['train', 'dev', 'test', 'holdout']
    by_corpus = {c: [d for d in docs if d['corpus'] == c] for c in corpora}

    # ---- 1. composition ---------------------------------------------------
    composition = {}
    for corpus in corpora:
        rows = by_corpus[corpus]
        composition[corpus] = {
            'n_records': len(rows),
            'n_diseases': len({r['disease_id'] for r in rows}),
            'n_patients': len({r['patient_group'] for r in rows}),
            'languages': dict(Counter(r['language'] for r in rows)),
            'template_families': dict(Counter(r['template_family'] for r in rows).most_common()),
            'complexities': dict(Counter(r['complexity'] for r in rows).most_common()),
            'disease_counts': dict(Counter(r['disease_id'] for r in rows).most_common()),
        }

    # ---- 2. patient / encounter overlap ----------------------------------
    patient_groups = {c: {r['patient_group'] for r in by_corpus[c]} for c in corpora}
    encounter_groups = {c: {r['encounter_group'] for r in by_corpus[c]} for c in corpora}
    patient_overlap = pair_overlap(patient_groups, corpora)
    encounter_overlap = pair_overlap(encounter_groups, corpora)
    duplicate_patients_within = {
        c: len(by_corpus[c]) - len(patient_groups[c]) for c in corpora
    }

    # ---- 3. exact text duplicates ----------------------------------------
    text_keys = {c: Counter(norm_text(r['text']) for r in by_corpus[c]) for c in corpora}
    exact_duplicates = {}
    for i, a in enumerate(corpora):
        for b in corpora[i + 1:]:
            exact_duplicates[f'{a}|{b}'] = len(set(text_keys[a]) & set(text_keys[b]))
    within_duplicates = {c: sum(v - 1 for v in text_keys[c].values() if v > 1) for c in corpora}

    # ---- 4. skeleton collisions ------------------------------------------
    skeletons = {c: Counter(skeleton(r) for r in by_corpus[c]) for c in corpora}
    skeleton_collisions = {}
    for i, a in enumerate(corpora):
        for b in corpora[i + 1:]:
            skeleton_collisions[f'{a}|{b}'] = len(set(skeletons[a]) & set(skeletons[b]))
    skeleton_within = {c: len(by_corpus[c]) - len(skeletons[c]) for c in corpora}
    # how many test notes have a skeleton that already exists in train
    test_skeletons_in_train = len({skeleton(r) for r in by_corpus['test']} & set(skeletons['train']))
    test_skeleton_share = test_skeletons_in_train / max(1, len(by_corpus['test']))

    # ---- 5. cell reuse ----------------------------------------------------
    def cell(record: dict) -> tuple:
        return (record['template_family'], record['complexity'], record['disease_id'])

    train_cells = {cell(r) for r in by_corpus['train']}
    train_diseases = {r['disease_id'] for r in by_corpus['train']}
    cell_stats = {}
    for corpus in ('dev', 'test', 'holdout'):
        rows = by_corpus[corpus]
        if corpus == 'holdout':
            # The holdout uses its own template names, so a (template, complexity,
            # disease) cell cannot match by construction.  The meaningful reuse
            # question there is whether the disease itself was seen in train.
            key_name = 'disease_seen_in_train'
            hits = sum(1 for r in rows if r['disease_id'] in train_diseases)
        else:
            key_name = 'triple_seen_in_train'
            hits = sum(1 for r in rows if cell(r) in train_cells)
        cell_stats[corpus] = {
            'n_records': len(rows),
            key_name: hits,
            'rate': round(hits / max(1, len(rows)), 4),
            'definition': key_name,
        }
    all_cells = Counter(cell(r) for r in docs if r['corpus'] != 'holdout')
    cell_stats['n_distinct_cells_train_dev_test'] = len(all_cells)
    cell_stats['max_records_in_one_cell'] = max(all_cells.values()) if all_cells else 0
    cell_stats['cells_with_at_least_5_records'] = sum(1 for v in all_cells.values() if v >= 5)

    # ---- 6. near duplicates (character shingles) --------------------------
    shingle_sets = {d['id']: shingles(d['text']) for d in docs}
    index = defaultdict(list)
    for doc in docs:
        for sh in shingle_sets[doc['id']]:
            index[sh].append(doc['id'])
    candidates = defaultdict(set)
    for sh, ids in index.items():
        if len(ids) < 2 or len(ids) > MAX_DF:
            continue
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                candidates[a].add(b)
                candidates[b].add(a)
    corpus_of = {d['id']: d['corpus'] for d in docs}
    pairs = []
    seen = set()
    for a, others in candidates.items():
        for b in others:
            key = tuple(sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            score = jaccard(shingle_sets[a], shingle_sets[b])
            if score >= args.near_dup_threshold:
                pairs.append({'a': a, 'b': b, 'jaccard': round(score, 4),
                              'corpus_a': corpus_of[a], 'corpus_b': corpus_of[b]})
    pair_counts = Counter()
    for row in pairs:
        key = '|'.join(sorted((row['corpus_a'], row['corpus_b'])))
        pair_counts[key] += 1
    cross_split_pairs = sum(v for k, v in pair_counts.items()
                            if '|' in k and len(set(k.split('|'))) > 1 and 'holdout' not in k)
    holdout_internal_pairs = pair_counts.get('holdout|holdout', 0)
    holdout_cross_pairs = sum(v for k, v in pair_counts.items()
                              if 'holdout' in k and k != 'holdout|holdout')
    top_pairs = sorted(pairs, key=lambda x: -x['jaccard'])[:10]
    for row in top_pairs:
        row['a_text'] = next(d['text'] for d in docs if d['id'] == row['a'])[:140]
        row['b_text'] = next(d['text'] for d in docs if d['id'] == row['b'])[:140]

    # Connected components of the holdout near-duplicate graph: the 260 notes are
    # not 260 independent draws if some of them are the same sentence with the
    # same phenotypes.
    holdout_ids = {r['id'] for r in by_corpus['holdout']}
    adjacency = defaultdict(set)
    for row in pairs:
        if row['corpus_a'] == 'holdout' and row['corpus_b'] == 'holdout':
            adjacency[row['a']].add(row['b'])
            adjacency[row['b']].add(row['a'])
    seen_nodes, clusters = set(), []
    for node in sorted(holdout_ids):
        if node in seen_nodes:
            continue
        stack, component = [node], []
        while stack:
            current = stack.pop()
            if current in seen_nodes:
                continue
            seen_nodes.add(current)
            component.append(current)
            stack.extend(adjacency[current] - seen_nodes)
        clusters.append(component)
    cluster_sizes = Counter(len(c) for c in clusters)
    holdout_structure = {
        'n_records': len(holdout_ids),
        'n_distinct_normalised_texts': len(set(text_keys['holdout'])),
        'n_exact_duplicate_copies': len(holdout_ids) - len(set(text_keys['holdout'])),
        'n_near_duplicate_pairs_internal': holdout_internal_pairs,
        'n_clusters_at_threshold': len(clusters),
        'largest_cluster': max((len(c) for c in clusters), default=0),
        'cluster_size_histogram': dict(sorted(cluster_sizes.items())),
        'n_singleton_clusters': cluster_sizes.get(1, 0),
        'cluster_members': [sorted(c) for c in sorted(clusters, key=lambda x: (-len(x), sorted(x)[0]))],
        'interpretation': 'the nominal 260 notes contain repeated texts; mention-level counts '
                          'overstate the number of independent examples',
    }

    # ---- 7. disease name leakage -----------------------------------------
    leakage = {}
    for corpus in corpora:
        rows = by_corpus[corpus]
        raw_hit = sum(1 for r in rows
                      if r['disease_name'].lower() in r['text'].lower()
                      or (r['disease_name_zh'] and r['disease_name_zh'] in r['text']))
        masked_rows = [r for r in rows if r['masked_text']]
        masked_hit = sum(1 for r in masked_rows
                         if r['disease_name'].lower() in r['masked_text'].lower()
                         or (r['disease_name_zh'] and r['disease_name_zh'] in r['masked_text']))
        leakage[corpus] = {
            'n_records': len(rows),
            'disease_name_verbatim_in_raw_text': raw_hit,
            'raw_rate': round(raw_hit / max(1, len(rows)), 4),
            'n_with_pipeline_masked_text': len(masked_rows),
            'disease_name_survives_in_masked_text': masked_hit,
            'masked_rate': round(masked_hit / max(1, len(masked_rows)), 4) if masked_rows else None,
        }

    # ---- 8. holdout vs dev: shared generation mechanism -------------------
    def surface_set(rows, language):
        return {e['text'] for r in rows if r['language'] == language
                for e in r['entities'] if e['label'] in ('PHENOTYPE', 'SYMPTOM_GENERIC')}

    phenotype_overlap = {}
    for language in ('zh', 'en'):
        dev_set = surface_set(by_corpus['train'] + by_corpus['dev'] + by_corpus['test'], language)
        hold_set = surface_set(by_corpus['holdout'], language)
        phenotype_overlap[language] = {
            'dev_surfaces': len(dev_set),
            'holdout_surfaces': len(hold_set),
            'shared': len(dev_set & hold_set),
            'jaccard': round(jaccard(dev_set, hold_set), 4),
        }

    cue_overlap = {}
    for language in ('zh', 'en'):
        dev_text = ' '.join(r['text'] for r in by_corpus['train'] + by_corpus['dev'] + by_corpus['test']
                            if r['language'] == language)
        hold_text = ' '.join(r['text'] for r in by_corpus['holdout'] if r['language'] == language)
        per_status = {}
        for status, cues in CUE_SETS['negex'][language].items():
            per_status[status] = {
                'n_cues': len(cues),
                'cues_in_dev': sum(1 for c in cues if c in dev_text),
                'cues_in_holdout': sum(1 for c in cues if c in hold_text),
            }
        cue_overlap[language] = per_status

    holdout_vs_dev = {
        'patient_overlap': patient_overlap.get('dev|holdout', 0) + patient_overlap.get('train|holdout', 0)
                           + patient_overlap.get('test|holdout', 0),
        'exact_text_duplicates': exact_duplicates.get('train|holdout', 0) + exact_duplicates.get('dev|holdout', 0)
                                 + exact_duplicates.get('test|holdout', 0),
        'skeleton_collisions': skeleton_collisions.get('train|holdout', 0) + skeleton_collisions.get('dev|holdout', 0)
                               + skeleton_collisions.get('test|holdout', 0),
        'shared_diseases': len({r['disease_id'] for r in by_corpus['holdout']}
                               & {r['disease_id'] for r in docs if r['corpus'] != 'holdout'}),
        'holdout_diseases': len({r['disease_id'] for r in by_corpus['holdout']}),
        'near_duplicate_pairs': holdout_cross_pairs,
        'phenotype_surface_overlap': phenotype_overlap,
        'cue_overlap': cue_overlap,
        'shared_code': ['clinforge.synthgen.CaseBuilder', 'clinforge.synthgen.CURATED_DISEASES',
                        'clinforge.synthgen._age_text', 'data/curated/zh_phenotype_gloss.json'],
        'different': ['seed (20261026 vs 20261027)', 'template family names and layouts',
                      'per-case phenotype sampling', 'record/patient/encounter id prefixes'],
    }

    # ---- 9. assemble ------------------------------------------------------
    manifest = {
        'relation_version': RELATION_VERSION,
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'inputs': {
            str((ROOT / p).relative_to(ROOT)).replace('\\', '/'): hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
            for p in ('data/phase3_synth/gen/notes.jsonl',
                      'data/phase4_synth_v2/training_candidates/sft_candidates.jsonl',
                      'data/phase4_context/holdout_notes.jsonl')
        },
        'composition': composition,
        'patient_links': {
            'within_corpus_duplicate_patients': duplicate_patients_within,
            'pairwise_patient_overlap': patient_overlap,
            'pairwise_encounter_overlap': encounter_overlap,
        },
        'text_relations': {
            'exact_duplicate_records_within': within_duplicates,
            'exact_duplicate_pairs_across': exact_duplicates,
            'skeleton_collisions_across': skeleton_collisions,
            'skeleton_duplicates_within': skeleton_within,
            'test_skeletons_also_in_train': test_skeletons_in_train,
            'test_skeleton_share': round(test_skeleton_share, 4),
        },
        'cell_reuse': cell_stats,
        'near_duplicates': {
            'method': f'character {SHINGLE_K}-gram Jaccard, threshold {args.near_dup_threshold}, '
                      f'inverted index with df<={MAX_DF}',
            'pairs_by_corpus_pair': dict(sorted(pair_counts.items())),
            'cross_split_pairs_excluding_holdout': cross_split_pairs,
            'holdout_internal_pairs': holdout_internal_pairs,
            'holdout_cross_pairs': holdout_cross_pairs,
            'holdout_structure': holdout_structure,
            'top_pairs': top_pairs,
        },
        'disease_name_leakage': leakage,
        'holdout_vs_dev': holdout_vs_dev,
        'claim_boundary': {
            'holdout_is': 'a synthetic held-out template validation set, frozen before evaluation, '
                          'with new seeds and new sentence layouts',
            'holdout_is_not': 'an independent clinical validation set; it shares the generator code, '
                              'the 16-disease set and the Chinese gloss with dev',
            'allowed_claims': [
                'the scope resolver generalises to unseen sentence layouts and seeds of the same generator',
                'history->affirmed errors drop from 221 to 0 on this frozen synthetic holdout',
            ],
            'forbidden_claims': [
                'independent cross-hospital or real-patient generalisation',
                'clinician-adjudicated accuracy',
                'clinical safety or deployment readiness',
            ],
            'external_eval_status': 'BLOCKED: no licensed, genuinely independent clinical corpus with '
                                    'context-status annotations is available in this environment; '
                                    'ASQ-PHI v1 is third-party but covers PHI spans only',
        },
    }
    (out_dir / 'relations.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                            encoding='utf-8')

    # ---- 10. markdown -----------------------------------------------------
    lines = [
        '# 训练集 / 留出集关系审计',
        '',
        f'- 版本 `{RELATION_VERSION}`，生成时间 {manifest["generated_at_utc"]}',
        '- 输入：2,355 条导出的 SFT 候选（train/dev/test）+ 260 条上下文留出语料',
        '- 近重复口径：字符 4-gram Jaccard ≥ 0.80（倒排索引，忽略出现在 >40 篇文档中的高频 shingle）',
        '',
        '## 1. 结论摘要',
        '',
        f'- 患者/就诊号：四组之间**没有任何共享**（患者重叠 {sum(patient_overlap.values())}，'
        f'就诊号重叠 {sum(encounter_overlap.values())}）。',
        f'- 精确重复文本：组内 {sum(within_duplicates.values())} 条，跨组 '
        f'{sum(exact_duplicates.values())} 对。',
        f'- 骨架（实体槽位归一化后）跨组碰撞：{sum(skeleton_collisions.values())} 个；'
        f'test 中有 **{test_skeleton_share:.2%}** 的记录骨架已在 train 出现。',
        f'- 单元复用：test 记录中 **{cell_stats["test"]["rate"]:.2%}** 与 train 落在同一个'
        '（模板族, 复杂度, 疾病）格子；全体只有 '
        f'{cell_stats["n_distinct_cells_train_dev_test"]} 个不同格子，最大单格 '
        f'{cell_stats["max_records_in_one_cell"]} 条。留出集的疾病 '
        f'**{cell_stats["holdout"]["rate"]:.2%}** 在 train 中出现过（模板名不同，格子不可比）。',
        f'- 近重复：跨 train/dev/test 且 Jaccard ≥ 0.80 的样本对 **{cross_split_pairs}** 对；'
        f'留出集**内部** **{holdout_internal_pairs}** 对，留出集与其他三组之间 '
        f'**{holdout_cross_pairs}** 对。',
        f'- 疾病名直接出现在输入正文中的比例：train '
        f'{leakage["train"]["raw_rate"]:.2%} / test {leakage["test"]["raw_rate"]:.2%}；'
        '而金标输出包含 `disease_suspected`，这是一条可被模型利用的捷径。',
        '',
        '## 2. 组成',
        '',
        '| 语料 | 记录 | 疾病 | 患者 | 中文/英文 | 模板族数 | 复杂度数 |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for corpus in corpora:
        row = composition[corpus]
        lines.append(f'| {corpus} | {row["n_records"]} | {row["n_diseases"]} | {row["n_patients"]} | '
                     f'{row["languages"].get("zh", 0)}/{row["languages"].get("en", 0)} | '
                     f'{len(row["template_families"])} | {len(row["complexities"])} |')
    lines += [
        '',
        '## 3. 患者、文本与骨架',
        '',
        '| 关系 | 患者重叠 | 就诊号重叠 | 精确重复文本 | 骨架碰撞 |',
        '| --- | --- | --- | --- | --- |',
    ]
    for i, a in enumerate(corpora):
        for b in corpora[i + 1:]:
            key = f'{a}|{b}'
            lines.append(f'| {a} vs {b} | {patient_overlap[key]} | {encounter_overlap[key]} | '
                         f'{exact_duplicates[key]} | {skeleton_collisions[key]} |')
    lines += [
        '',
        f'组内精确重复：train {within_duplicates["train"]}、dev {within_duplicates["dev"]}、'
        f'test {within_duplicates["test"]}、holdout {within_duplicates["holdout"]}。',
        '',
        '## 4. 格子复用与捷径',
        '',
        '| 语料 | 记录 | 格子已在 train 出现 | 比例 | 口径 |',
        '| --- | --- | --- | --- | --- |',
    ]
    for corpus in ('dev', 'test', 'holdout'):
        row = cell_stats[corpus]
        hits = row.get('triple_seen_in_train', row.get('disease_seen_in_train'))
        definition = '（模板族, 复杂度, 疾病）' if corpus != 'holdout' else '疾病'
        lines.append(f'| {corpus} | {row["n_records"]} | {hits} | '
                     f'{row["rate"]:.2%} | {definition} |')
    lines += [
        '',
        '疾病名出现在正文（脱敏前 / 脱敏后）：',
        '',
        '| 语料 | 原始正文 | 脱敏后正文 |',
        '| --- | --- | --- |',
    ]
    for corpus in corpora:
        row = leakage[corpus]
        masked = '—' if row['masked_rate'] is None else f'{row["masked_rate"]:.2%}'
        lines.append(f'| {corpus} | {row["raw_rate"]:.2%} | {masked} |')
    lines += [
        '',
        '> 这不是"数据泄漏 bug"，而是任务定义问题：知识约束合成把疾病名写进 Assessment，'
        '又把疾病 ID 放进金标。用它训练/评测时，`disease_suspected` 字段应被去掉或单独报告，'
        '否则测到的是字符串匹配而不是表型理解。',
        '',
        '## 5. 近重复',
        '',
        '| 语料对 | 对数（Jaccard ≥ 0.80） |',
        '| --- | --- |',
    ]
    for key, value in sorted(pair_counts.items()):
        lines.append(f'| {key} | {value} |')
    lines += [
        '',
        f'最高相似度样例（前 {len(top_pairs)} 对）：',
        '',
        '| 语料 | A | B | Jaccard | A 片段 |',
        '| --- | --- | --- | --- | --- |',
    ]
    for row in top_pairs:
        lines.append(f'| {row["corpus_a"]}/{row["corpus_b"]} | `{row["a"]}` | `{row["b"]}` | '
                     f'{row["jaccard"]:.3f} | {row["a_text"][:48]}… |')
    lines += [
        '',
        '### 5.1 留出集内部的重复结构（重要）',
        '',
        f'- 260 条留出语料只有 **{holdout_structure["n_distinct_normalised_texts"]}** 种'
        f'不同的规范化文本（{holdout_structure["n_exact_duplicate_copies"]} 条是重复副本）。',
        f'- 按 Jaccard ≥ 0.80 连通分量合并后只剩 **{holdout_structure["n_clusters_at_threshold"]}** 个簇，'
        f'最大簇 {holdout_structure["largest_cluster"]} 条，单例簇 '
        f'{holdout_structure["n_singleton_clusters"]} 个。',
        f'- 簇大小分布：`{json.dumps(holdout_structure["cluster_size_histogram"], ensure_ascii=False)}`。',
        '',
        '这意味着：**1,618 个提及并不是 1,618 个独立观测**。按提及数计算的置信区间会偏窄，'
        '留出集上的准确率应理解为"若干句型的加权平均"，而不是 260 位独立患者的表现。'
        '项目在正文中只报告点估计与混淆矩阵，未声称临床置信区间；这一点现在显式写出。'
        '按上述簇做 cluster bootstrap 的结果单独存放在 '
        '`reports/phase4_split_relations/holdout_bootstrap.json`（2,000 次重采样）。',
        '',
        '',
        '## 6. 260 条留出语料到底有多独立',
        '',
        '| 维度 | 结果 |',
        '| --- | --- |',
        f'| 与 train/dev/test 共享患者 | {holdout_vs_dev["patient_overlap"]} |',
        f'| 与 train/dev/test 精确重复文本 | {holdout_vs_dev["exact_text_duplicates"]} |',
        f'| 与 train/dev/test 骨架碰撞 | {holdout_vs_dev["skeleton_collisions"]} |',
        f'| 共享疾病 | {holdout_vs_dev["shared_diseases"]}/{holdout_vs_dev["holdout_diseases"]} |',
        f'| 与 train/dev/test 近重复对 | {holdout_vs_dev["near_duplicate_pairs"]} |',
        f'| 留出集内部近重复对 | {holdout_internal_pairs}（'
        f'{holdout_structure["n_clusters_at_threshold"]} 个簇） |',
        f'| 中文表型表面形式 Jaccard | {phenotype_overlap["zh"]["jaccard"]:.3f} '
        f'（共享 {phenotype_overlap["zh"]["shared"]} 个表面形式） |',
        f'| 英文表型表面形式 Jaccard | {phenotype_overlap["en"]["jaccard"]:.3f} '
        f'（共享 {phenotype_overlap["en"]["shared"]} 个表面形式） |',
        '',
        '**共享的生成机制**：同一个 `CaseBuilder`（跨度与标签由构造过程直接产生，不是人工标注）、'
        '同一组 16 种疾病（同一份 HPO 注释）、同一份中文表型词表、同一套线索词家族。',
        '**真正的差异**：随机种子、模板族名称与句法布局、每例的表型抽样。',
        '',
        '因此这 260 条只能称为"**同生成器的留出合成模板验证**"，'
        '不能称为"独立临床验证"或"跨医院泛化"。原评测结果继续保留，措辞必须按此口径。',
        '',
        '外部独立评测状态：**BLOCKED**。本机没有具备合法授权、且带上下文状态标注的'
        '真实临床语料；`data/external/asq_phi` 是第三方独立数据，但只覆盖 PHI 跨度，'
        '不能用于上下文状态评测。若将来获得此类语料，应另建冻结实验，'
        '**不得**在现有 260 条上重新调参。',
        '',
        '## 7. 结论',
        '',
        '- 患者级与精确文本级切分是干净的；近重复在阈值 0.80 下的跨组对数为 '
        f'{cross_split_pairs}（不含留出集）。',
        '- **但"患者 ID 不重叠"几乎是同义反复**：每条合成记录的 patient_group 都是新生成的，'
        '文本完全相同也会得到不同患者号。真正的独立性必须看文本与近重复，'
        f'而留出集内部有 {holdout_structure["n_exact_duplicate_copies"]} 条重复副本、'
        f'{holdout_internal_pairs} 对近重复，合并后只有 '
        f'{holdout_structure["n_clusters_at_threshold"]} 个簇。',
        '- 但模板族 × 复杂度 × 疾病只有 '
        f'{cell_stats["n_distinct_cells_train_dev_test"]} 个格子，'
        'test 与 train 的格子复用率很高，**不能据此声称泛化**。',
        '- 疾病名入正文、疾病 ID 入金标，是任务设计层面的捷径，'
        '应在下游训练/评测中显式处理。',
        '- 留出集共享生成机制，只能支持"作用域机制在未见句式上有效"，'
        '不能支持任何临床结论。',
        '',
        '## 8. 复现',
        '',
        '```bash',
        'python -m scripts.audit_split_relations',
        '```',
        '',
    ]
    (out_dir / 'report.md').write_text('\n'.join(lines), encoding='utf-8')

    print(json.dumps({
        'relation_version': RELATION_VERSION,
        'composition': {c: composition[c]['n_records'] for c in corpora},
        'patient_overlap': patient_overlap,
        'exact_duplicates': exact_duplicates,
        'skeleton_collisions': skeleton_collisions,
        'cell_reuse': {k: v for k, v in cell_stats.items() if isinstance(v, dict)},
        'near_duplicates': {'cross_split': cross_split_pairs,
                            'holdout_internal': holdout_internal_pairs,
                            'holdout_cross': holdout_cross_pairs,
                            'holdout_clusters': holdout_structure['n_clusters_at_threshold'],
                            'by_pair': dict(sorted(pair_counts.items()))},
        'disease_name_leakage': {c: leakage[c]['raw_rate'] for c in corpora},
        'holdout_vs_dev': {k: v for k, v in holdout_vs_dev.items()
                           if k in ('patient_overlap', 'exact_text_duplicates',
                                    'skeleton_collisions', 'shared_diseases', 'near_duplicate_pairs')},
        'outputs': [str((out_dir / 'relations.json').relative_to(ROOT)),
                    str((out_dir / 'report.md').relative_to(ROOT))],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
