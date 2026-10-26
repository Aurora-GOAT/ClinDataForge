"""Held-out context corpus (author-written realisations, never used in dev).

The phase-3 development corpus (`synthgen-1.0.0`, seed 20261026) was used to
diagnose and fix the context classifier, so it can no longer serve as an
independent test set. This module builds a second corpus whose *realisations*
are disjoint from that corpus, and it is frozen (SHA256 recorded) before any
evaluation of the new classifier runs.

What is independent here
------------------------
* seed 20261027 (dev used 20261026);
* template family names, sentence structures and section layouts the dev corpus
  never emits: colon + newline section bodies, `、` enumerations of 3-5 items,
  verb-less history lists, repeated triggers, contrastive conjunctions,
  multi-clause English denies lists, comma/Oxford variants;
* phenotype sampling per case.

What is NOT independent (stated so the claim cannot be inflated)
---------------------------------------------------------------
* gold labels come from the same template-emitter mechanism, not a clinician;
* the disease set is the same curated 16, because the verified Chinese gloss
  only covers their phenotypes (disease-phenotype *pairings* differ);
* the cue vocabulary overlaps dev's, so the cue-extension ablation is reported
  separately instead of being folded into the headline number.

This corpus is therefore reported as **held-out synthetic template validation**.
It is not clinical validation and no clinical claim is made from it.

Usage: python -m scripts.build_context_holdout
"""
from __future__ import annotations

import json
import random

from .synthgen import CaseBuilder, CURATED_DISEASES, _age_text

HOLDOUT_VERSION = 'holdout-ctx-1.0.0'
HOLDOUT_SEED = 20261027
N_ZH, N_EN = 150, 110

ZH_CASES = ('zh_section_enum', 'zh_section_bare_list', 'zh_long_denies',
            'zh_repeated_triggers', 'zh_contrast', 'zh_cross_sentence',
            'zh_suspected_series', 'zh_exam_list')
EN_CASES = ('en_pmh_notable', 'en_history_lists', 'en_long_denies',
            'en_repeated_negation', 'en_contrast', 'en_suspected_series')


def _core(disease, gloss, limit=10):
    phenos = sorted(disease['phenotypes'].values(), key=lambda p: -(p['frequency'] or 0))
    core = [p for p in phenos if p['hp_id'] in gloss['phenotypes']][:limit]
    if len(core) < 7:
        raise ValueError(f'Not enough glossed phenotypes for {disease["disease_id"]}')
    return core


def _zh_record(builder, kind, rng, gloss, core, disease_zh):
    def at(index):
        return core[index % len(core)]

    def pheno(item, status):
        chunk = gloss['phenotypes'][item['hp_id']]
        start = builder.length
        builder.parts.append(chunk)
        builder.length += len(chunk)
        builder.entities.append({'start': start, 'end': builder.length, 'text': chunk,
                                 'label': 'PHENOTYPE', 'hp_id': item['hp_id'],
                                 'name_en': item['name'], 'status': status,
                                 'evidence': item['evidence'], 'reference': item['reference'],
                                 'frequency_raw': item['frequency_raw']})

    builder.text('患者，' + _age_text(rng.randint(1, 40), 'zh') + '，因')
    pheno(core[0], 'affirmed')
    builder.text('就诊。')

    if kind == 'zh_section_enum':
        builder.text('既往史：\n')
        for index in range(3):
            if index:
                builder.text('、')
            pheno(at(1 + index), 'history')
        builder.text('。查体：')
        for index in range(3):
            if index:
                builder.text('，')
            pheno(at(4 + index), 'affirmed')
        builder.text('。')
    elif kind == 'zh_section_bare_list':
        builder.text('既往史：')
        for index in range(3):
            if index:
                builder.text('、')
            pheno(at(1 + index), 'history')
        builder.text('。否认')
        for index in range(3):
            if index:
                builder.text('、')
            pheno(at(4 + index), 'negated')
        builder.text('等表现。')
    elif kind == 'zh_long_denies':
        builder.text('系统回顾：否认')
        for index in range(5):
            if index:
                builder.text('、')
            pheno(at(1 + index), 'negated')
        builder.text('。此次因')
        pheno(core[0], 'affirmed')
        builder.text('加重入院。')
    elif kind == 'zh_repeated_triggers':
        for index in range(3):
            builder.text('未见')
            pheno(at(1 + index), 'negated')
            builder.text('，')
        builder.text('血常规大致正常。目前仍有')
        pheno(at(4), 'affirmed')
        builder.text('。既往曾患')
        pheno(at(5), 'history')
        builder.text('。')
    elif kind == 'zh_contrast':
        builder.text('否认')
        for index in range(3):
            if index:
                builder.text('、')
            pheno(at(1 + index), 'negated')
        builder.text('，但')
        pheno(at(4), 'affirmed')
        builder.text('明显。既往有')
        pheno(at(5), 'history')
        builder.text('史。')
    elif kind == 'zh_cross_sentence':
        builder.text('既往有')
        pheno(at(1), 'history')
        builder.text('。本次因')
        pheno(at(2), 'affirmed')
        builder.text('就诊，查体发现')
        pheno(at(3), 'affirmed')
        builder.text('。否认')
        pheno(at(4), 'negated')
        builder.text('。')
    elif kind == 'zh_suspected_series':
        builder.text('疑')
        pheno(at(1), 'suspected')
        builder.text('，疑')
        pheno(at(2), 'suspected')
        builder.text('，需警惕')
        pheno(at(3), 'suspected')
        builder.text('。不除外')
        pheno(at(4), 'suspected')
        builder.text('，建议随访。')
    else:  # zh_exam_list
        builder.text('查体：')
        for index in range(4):
            if index:
                builder.text('、')
            pheno(at(1 + index), 'affirmed')
        builder.text('。\n既往史：有')
        pheno(at(5), 'history')
        builder.text('，另有')
        pheno(at(6), 'history')
        builder.text('。')
    builder.text('结合上述表现，考虑' + disease_zh + '，建议完善检查。')


def _en_record(builder, kind, rng, core, disease_en):
    def at(index):
        return core[index % len(core)]

    def pheno(item, status):
        builder.entity(item['name'], {'label': 'PHENOTYPE', 'hp_id': item['hp_id'],
                                      'name_en': item['name'], 'status': status,
                                      'evidence': item['evidence'],
                                      'reference': item['reference'],
                                      'frequency_raw': item['frequency_raw']})

    builder.text('The patient presents with ')
    pheno(core[0], 'affirmed')
    builder.text('. ')

    if kind == 'en_pmh_notable':
        builder.text('Past medical history is notable for ')
        for index in range(3):
            if index:
                builder.text(', ')
            pheno(at(1 + index), 'history')
        builder.text('. Examination is notable for ')
        for index in range(3):
            if index:
                builder.text(' and ')
            pheno(at(4 + index), 'affirmed')
        builder.text('. ')
    elif kind == 'en_history_lists':
        builder.text('She has a history of ')
        for index in range(3):
            if index:
                builder.text(', ')
            pheno(at(1 + index), 'history')
        builder.text('. There is no evidence of ')
        for index in range(3):
            if index:
                builder.text(' or ')
            pheno(at(4 + index), 'negated')
        builder.text('. ')
    elif kind == 'en_long_denies':
        builder.text('The patient denies ')
        for index in range(5):
            if index:
                builder.text(', ')
            pheno(at(1 + index), 'negated')
        builder.text('. Findings include ')
        pheno(core[0], 'affirmed')
        builder.text('. ')
    elif kind == 'en_repeated_negation':
        for index in range(3):
            builder.text('Negative for ')
            pheno(at(1 + index), 'negated')
            builder.text('. ')
        builder.text('There is suspicion of ')
        pheno(at(4), 'suspected')
        builder.text('. Previously documented ')
        pheno(at(5), 'history')
        builder.text('. ')
    elif kind == 'en_contrast':
        builder.text('The patient denies ')
        pheno(at(1), 'negated')
        builder.text(', ')
        pheno(at(2), 'negated')
        builder.text(', however ')
        pheno(at(3), 'affirmed')
        builder.text(' is evident. There is a history of ')
        pheno(at(4), 'history')
        builder.text('. ')
    else:  # en_suspected_series
        builder.text('Possible ')
        pheno(at(1), 'suspected')
        builder.text(', suspected ')
        pheno(at(2), 'suspected')
        builder.text('; cannot exclude ')
        pheno(at(3), 'suspected')
        builder.text('. Previously noted ')
        pheno(at(4), 'history')
        builder.text('. ')
    builder.text(f'Overall this is consistent with {disease_en}.')


def generate(kb, gloss, seed=HOLDOUT_SEED, n_zh=N_ZH, n_en=N_EN):
    rng = random.Random(seed)
    diseases = [kb['diseases'][d] for d in CURATED_DISEASES if d in kb['diseases']]
    if len(diseases) != len(CURATED_DISEASES):
        raise ValueError('Curated disease missing from knowledge snapshot')
    records, counter = [], 0
    for language, count, kinds in (('zh', n_zh, ZH_CASES), ('en', n_en, EN_CASES)):
        for index in range(count):
            disease = diseases[(index * 7 + 3) % len(diseases)]
            core = _core(disease, gloss)
            kind = kinds[index % len(kinds)]
            builder = CaseBuilder()
            if language == 'zh':
                _zh_record(builder, kind, rng, gloss, core,
                           gloss['diseases'][disease['disease_id']])
            else:
                _en_record(builder, kind, rng, core, disease['disease_name'])
            case_id = f'HCTX-{counter:05d}'
            counter += 1
            age = rng.randint(1, 40)
            records.append({
                'case_id': case_id, 'record_id': case_id,
                'patient_group': f'PAT-{case_id}', 'encounter_group': f'ENC-{case_id}',
                'language': language, 'template_family': kind, 'age_years': age,
                'disease_id': disease['disease_id'], 'disease_name': disease['disease_name'],
                'text': builder.build(), 'entities': builder.entities,
                'seed': seed, 'generator_version': HOLDOUT_VERSION,
                'n_entities': len(builder.entities),
            })
    return records


def write_corpus(records, out_path):
    with open(out_path, 'w', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
