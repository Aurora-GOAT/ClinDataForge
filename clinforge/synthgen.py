"""Knowledge-constrained synthetic clinical note generator (P0).

Every generated case is driven by REAL disease-phenotype annotations from the
verified HPO snapshot (clinforge.hpo_knowledge). Hard rules:

  * affirmed / suspected / history phenotype mentions must belong to the
    disease's annotation set (aspect P, non-NOT rows);
  * negated phenotype mentions must belong to the annotation set or to a
    small curated generic-symptom whitelist (labelled SYMPTOM_GENERIC);
  * numeric labs are generated only for curated lab-linked phenotypes, with
    values sampled OUTSIDE the curated demonstration reference interval in
    the direction implied by the phenotype; normal distractor labs carry no
    phenotype entity;
  * drug doses, diagnostic criteria and real-patient details are NEVER
    fabricated; unsupported fields are omitted;
  * all randomness flows from one seeded RNG; the seed, generator version,
    HPO versions and per-phenotype evidence codes are persisted per case.

The builder tracks exact character spans of every inserted entity, so the
generated notes carry gold annotations used for the template-internal
self-check of the extraction pipeline (kept strictly separate from the
independent PHI benchmark of phase 2).
"""
from __future__ import annotations
import json
import random
from pathlib import Path

from .hpo_knowledge import LAB_PHENOTYPES, REFERENCE_INTERVALS, ONSET_AGE_RANGE, DEFAULT_AGE_RANGE

GENERATOR_VERSION = 'synthgen-1.0.0'
MAX_CORE_PHENOTYPES = 16

CURATED_DISEASES = [
    'ORPHA:64', 'ORPHA:84', 'ORPHA:506', 'ORPHA:110', 'ORPHA:355', 'ORPHA:550',
    'ORPHA:116', 'OMIM:276700', 'OMIM:117550', 'ORPHA:191', 'ORPHA:79318',
    'ORPHA:881', 'ORPHA:2162', 'ORPHA:79474', 'ORPHA:534', 'ORPHA:33364',
]
DISEASE_SET_RATIONALE = (
    'Curated rare-disease demo set: all entries are Orphanet/OMIM registered rare diseases with '
    '>=8 HPO phenotype annotations in the verified snapshot; jointly covering neurologic, metabolic, '
    'hematologic, endocrine, hepatic, renal, ophthalmologic and chromosomal systems; every disease '
    'contributes at least one curated lab-linked phenotype (ALT/AST, glucose, hemoglobin) where '
    'available so the lab-standardisation stage has material. Sex-limited diseases (Turner syndrome: '
    'female; Lowe syndrome: X-linked male) use the documented sex constraint only.'
)
# Documented sex constraints for the two sex-limited diseases in the demo set.
SEX_CONSTRAINT = {'ORPHA:881': 'F', 'ORPHA:534': 'M'}

# Generic symptoms allowed in NEGATED form without a disease annotation
# (labelled SYMPTOM_GENERIC, excluded from knowledge-violation checks).
GENERIC_NEGATABLE_ZH = ['发热', '咳嗽', '腹泻', '皮疹', '盗汗']
GENERIC_NEGATABLE_EN = ['fever', 'cough', 'diarrhea', 'skin rash', 'night sweats']

ZH_SURNAMES = ['林', '沈', '顾', '陆', '韩', '穆', '欧阳', '诸葛', '上官', '司马',
               '湛', '郗', '闻', '祁', '靳', '池', '边', '尚', '晏', '寇']
ZH_GIVEN = ['一诺', '子墨', '书瑶', '沐宸', '若汐', '亦辰', '思远', '静姝',
            '雨桐', '浩然', '欣怡', '宇航', '梓萱', '铭泽', '语嫣', '天佑']
EN_NAMES = ['Elena Marsh', 'Tobias Reed', 'Priya Nair', 'Jonah Fields', 'Mira Solberg',
            'Declan Pierce', 'Anika Roth', 'Soren Blake', 'Leila Osman', 'Nolan Park']

DURATIONS_ZH = ['3天', '1周', '2周', '1个月', '3个月', '半年', '1年', '2年余']
DURATIONS_EN = ['3 days', '1 week', '2 weeks', '1 month', '3 months', 'half a year', '1 year', 'over 2 years']

ONSET_PHRASE_ZH = {
    'HP:0003577': '出生后即', 'HP:0003623': '新生儿期即', 'HP:0003593': '婴儿期起',
    'HP:0011463': '幼儿期起', 'HP:0003621': '学龄期起', 'HP:0011462': '青年期起',
    'HP:0003596': '中年后', 'HP:0003584': '老年期起', 'HP:0003581': '成年后',
}
ONSET_PHRASE_EN = {
    'HP:0003577': 'since birth', 'HP:0003623': 'since the neonatal period',
    'HP:0003593': 'since infancy', 'HP:0011463': 'since early childhood',
    'HP:0003621': 'since the school-age years', 'HP:0011462': 'since young adulthood',
    'HP:0003596': 'after middle age', 'HP:0003584': 'in late adulthood',
    'HP:0003581': 'in adulthood',
}


class CaseBuilder:
    """Accumulates text segments and exact entity spans."""

    def __init__(self):
        self.parts = []
        self.entities = []
        self.length = 0

    def text(self, chunk):
        self.parts.append(chunk)
        self.length += len(chunk)
        return self

    def entity(self, chunk, record):
        start = self.length
        self.parts.append(chunk)
        self.length += len(chunk)
        self.entities.append({'start': start, 'end': self.length, 'text': chunk, **record})
        return self

    def build(self):
        return ''.join(self.parts)


def _round_value(value, decimals):
    return round(value, decimals) if decimals else int(round(value))


def _to_std(value, unit, analyte):
    """Convert a displayed value back to the standard unit (exact inverse of
    the display conversion, so the recorded standard value always matches the
    text within rounding of the displayed precision)."""
    ref = REFERENCE_INTERVALS[analyte]
    if unit == 'mg/dL':      # mg/dL -> mmol/L: divide by molar-mass factor
        return round(value / ref['factor_mgdl_to_mmoll'], 2)
    if unit == 'g/dL':       # g/dL -> g/L: multiply by 10
        return round(value * ref['factor_gdl_to_gl'], 2)
    return round(value, 2)


def sample_lab_value(rng, analyte, direction, use_alt_unit):
    """Sample a value consistent with the phenotype direction, then convert
    to the displayed unit. Returns (display_value, display_unit, std_value, std_unit)."""
    ref = REFERENCE_INTERVALS[analyte]
    if direction == 'high':
        std_target = rng.uniform(ref['hi'] * 1.1, ref['hi'] * 2.5)
    else:
        std_target = rng.uniform(ref['lo'] * 0.4, ref['lo'] * 0.85)
    unit = ref['unit']
    value = std_target
    if use_alt_unit and analyte == 'GLUCOSE':
        value, unit = std_target * ref['factor_mgdl_to_mmoll'], 'mg/dL'
    elif use_alt_unit and analyte == 'HGB':
        value, unit = std_target / ref['factor_gdl_to_gl'], 'g/dL'
    decimals = 1 if (analyte == 'GLUCOSE' and unit == 'mmol/L') or (analyte == 'HGB' and unit == 'g/dL') else 0
    value = _round_value(value, decimals)
    return value, unit, _to_std(value, unit, analyte), ref['unit']


def sample_normal_lab(rng, analyte):
    ref = REFERENCE_INTERVALS[analyte]
    std_target = rng.uniform(ref['lo'] * 1.02, ref['hi'] * 0.98)
    decimals = 1 if analyte == 'GLUCOSE' else 0
    value = _round_value(std_target, decimals)
    return value, ref['unit'], _to_std(value, ref['unit'], analyte), ref['unit']


LAB_NAME = {
    'zh': {'ALT': 'ALT', 'AST': 'AST', 'GLUCOSE': '空腹血糖', 'HGB': '血红蛋白'},
    'en': {'ALT': 'ALT', 'AST': 'AST', 'GLUCOSE': 'fasting glucose', 'HGB': 'hemoglobin'},
}


def _age_text(age, lang, style='noun'):
    if lang == 'zh':
        if age < 1:
            return f'{max(1, int(age * 12))}个月'
        return f'{int(age)}岁'
    if style == 'noun':
        if age < 1:
            return f'{max(1, int(age * 12))} months'
        return f'{int(age)} years'
    if age < 1:
        return f'{max(1, int(age * 12))}-month-old'
    return f'{int(age)}-year-old'


def _pheno_text(phenotype, lang, gloss, rng, allow_synonym):
    if lang == 'zh':
        return gloss['phenotypes'][phenotype['hp_id']]
    if allow_synonym:
        return phenotype['name']
    return phenotype['name']


class SynthGenerator:
    def __init__(self, kb, gloss, seed=20261026, n_cases=2400, zh_ratio=0.7, phi_rate=0.55):
        self.kb = kb
        self.gloss = gloss
        self.rng = random.Random(seed)
        self.seed = seed
        self.n_cases = n_cases
        self.zh_ratio = zh_ratio
        self.phi_rate = phi_rate
        self.diseases = [kb['diseases'][d] for d in CURATED_DISEASES if d in kb['diseases']]
        if len(self.diseases) != len(CURATED_DISEASES):
            raise ValueError('Curated disease missing from knowledge snapshot')
        # Core expressible phenotype set per disease: top-N by frequency plus
        # every curated lab-linked phenotype, all requiring a gloss/english name.
        self.core = {}
        for disease in self.diseases:
            phenos = sorted(disease['phenotypes'].values(), key=lambda p: -(p['frequency'] or 0))
            core = phenos[:MAX_CORE_PHENOTYPES]
            core += [p for p in phenos if p['hp_id'] in LAB_PHENOTYPES and p not in core]
            for p in core:
                if p['hp_id'] not in gloss['phenotypes']:
                    raise ValueError(f"Missing curated zh gloss for {p['hp_id']} ({p['name']})")
            self.core[disease['disease_id']] = core

    # ---- sampling ------------------------------------------------------
    def sample_case_plan(self, disease, complexity):
        rng = self.rng
        core = self.core[disease['disease_id']]
        affirmed, suspected, history = [], [], []
        for p in core:
            f = min(0.95, p['frequency'] or 0.05)
            if rng.random() < f:
                roll = rng.random()
                if roll < 0.15:
                    suspected.append(p)
                elif roll < 0.27 and complexity != 'simple':
                    history.append(p)
                else:
                    affirmed.append(p)
        target = {'simple': (2, 3), 'standard': (4, 6), 'detailed': (6, 9)}[complexity]
        if len(affirmed) > target[1]:
            rng.shuffle(affirmed)
            affirmed = affirmed[:target[1]]
        while len(affirmed) < target[0]:
            pool = [p for p in core if p not in affirmed and p not in suspected and p not in history]
            if not pool:
                break
            pool.sort(key=lambda p: -(p['frequency'] or 0))
            affirmed.append(pool[0])
        # negated: frequent phenotypes not expressed + generic symptoms
        negatable = [p for p in core if (p['frequency'] or 0) >= 0.5
                     and p not in affirmed and p not in suspected and p not in history]
        rng.shuffle(negatable)
        negated = negatable[:rng.randint(0, 2 if complexity != 'simple' else 1)]
        n_generic = rng.randint(0, 2 if complexity == 'detailed' else 1)
        onsets = disease['onsets']
        age_range = ONSET_AGE_RANGE.get(onsets[0], DEFAULT_AGE_RANGE) if onsets else DEFAULT_AGE_RANGE
        age = rng.uniform(*age_range) if age_range[1] > age_range[0] else age_range[0]
        return {'affirmed': affirmed, 'suspected': suspected, 'history': history,
                'negated': negated, 'n_generic_negated': n_generic,
                'age': age, 'onset': onsets[0] if onsets else None}

    # ---- text composition ----------------------------------------------
    def compose(self, disease, plan, lang, family, complexity):
        rng, gloss = self.rng, self.gloss
        b = CaseBuilder()
        did = disease['disease_id']
        dz_name = gloss['diseases'][did] if lang == 'zh' else disease['disease_name']
        sex = SEX_CONSTRAINT.get(did) or rng.choice('MF')

        def ptext(p):
            return _pheno_text(p, lang, gloss, rng, rng.random() < 0.3)

        def emit_pheno(p, status, chunk=None):
            b.entity(chunk if chunk is not None else ptext(p),
                     {'label': 'PHENOTYPE', 'hp_id': p['hp_id'], 'name_en': p['name'],
                      'status': status, 'evidence': p['evidence'], 'reference': p['reference'],
                      'frequency_raw': p['frequency_raw']})

        with_phi = rng.random() < self.phi_rate
        if with_phi:
            if lang == 'zh':
                name = rng.choice(ZH_SURNAMES) + rng.choice(ZH_GIVEN)
                mrn = 'R%07d' % rng.randint(0, 9999999)
                phone = '1%d%04d%04d' % (rng.choice([3, 5, 7, 8, 9]), rng.randint(0, 9999), rng.randint(0, 9999))
                date = '2026-%02d-%02d' % (rng.randint(1, 12), rng.randint(1, 28))
                b.text('姓名：'); b.entity(name, {'label': 'NAME'})
                b.text('｜性别：' + ('男' if sex == 'M' else '女') + '｜年龄：')
                b.text(_age_text(plan['age'], lang))
                b.text('｜病历号：'); b.entity(mrn, {'label': 'PATIENT_ID'})
                b.text('｜联系电话：'); b.entity(phone, {'label': 'PHONE'})
                b.text('｜就诊日期：'); b.entity(date, {'label': 'DATE'})
                b.text('\n')
            else:
                name = rng.choice(EN_NAMES)
                mrn = 'MRN-%06d' % rng.randint(0, 999999)
                phone = '555-%03d-%04d' % (rng.randint(0, 999), rng.randint(0, 9999))
                date = '2026-%02d-%02d' % (rng.randint(1, 12), rng.randint(1, 28))
                b.text('Name: '); b.entity(name, {'label': 'NAME'})
                b.text(' | Sex: ' + ('Male' if sex == 'M' else 'Female') + ' | Age: ')
                b.text(_age_text(plan['age'], lang))
                b.text(' | MRN: '); b.entity(mrn, {'label': 'PATIENT_ID'})
                b.text(' | Phone: '); b.entity(phone, {'label': 'PHONE'})
                b.text(' | Visit date: '); b.entity(date, {'label': 'DATE'})
                b.text('\n')

        if lang == 'zh':
            self._compose_zh(b, disease, plan, family, complexity, dz_name, sex, emit_pheno, ptext)
        else:
            self._compose_en(b, disease, plan, family, complexity, dz_name, sex, emit_pheno, ptext)
        return b.build(), b.entities, with_phi

    def _compose_zh(self, b, disease, plan, family, complexity, dz_name, sex, emit_pheno, ptext):
        rng = self.rng
        affirmed, suspected, history = plan['affirmed'], plan['suspected'], plan['history']
        onset_phrase = ONSET_PHRASE_ZH.get(plan['onset'])
        subj = '患儿' if plan['age'] < 14 else '患者'

        def chief():
            b.text('因“')
            emit_pheno(affirmed[0], 'affirmed')
            if len(affirmed) > 1:
                b.text('伴'); emit_pheno(affirmed[1], 'affirmed')
            b.text('”')
            b.entity(rng.choice(DURATIONS_ZH), {'label': 'TEMPORAL', 'kind': 'duration'})
            b.text('就诊' if family != 'admission' else '入院')

        def course():
            rest = list(affirmed[2:])
            if onset_phrase:
                b.text(f'{subj}')
                b.entity(onset_phrase, {'label': 'TEMPORAL', 'kind': 'onset'})
                if rest:
                    b.text(rng.choice(['即出现', '起被发现存在']))
                    emit_pheno(rest.pop(0), 'affirmed')
                    b.text('，')
                else:
                    b.text('有相关表现，')
            for p in rest:
                b.text(rng.choice(['病程中可见', '查体发现', '此后逐渐出现', '目前仍有']))
                emit_pheno(p, 'affirmed')
                b.text(rng.choice(['。', '；']))
            for p in suspected:
                b.text(rng.choice(['另疑有', '查体疑似', '尚需评估有无']))
                emit_pheno(p, 'suspected')
                b.text(rng.choice(['。', '；']))
            if complexity == 'detailed' and affirmed:
                b.text('上述表现')
                b.entity(rng.choice(['逐渐进展', '迁延至今', '时轻时重']), {'label': 'TEMPORAL', 'kind': 'course'})
                b.text('，家属为进一步诊治来诊。')

        def history_sec():
            if not history:
                return
            b.text('既往史：' if family != 'outpatient' else '既往')
            for i, p in enumerate(history):
                b.text(rng.choice(['有', '曾有']) if i == 0 else '，并有')
                emit_pheno(p, 'history')
            b.text('史。' if rng.random() < 0.5 else '。')

        if family == 'outpatient':
            b.text(f'{subj}，' + ('男' if sex == 'M' else '女') + '，')
            b.text(_age_text(plan['age'], 'zh') + '，')
            chief()
            b.text('。')
            course()
            history_sec()
        elif family == 'admission':
            b.text('主诉：')
            chief()
            b.text('。\n现病史：')
            course()
            b.text('\n')
            history_sec()
            b.text('\n')
        else:  # referral 会诊/转诊介绍
            b.text('会诊记录：兹介绍' + ('男' if sex == 'M' else '女') + '性' + subj + '，')
            b.text(_age_text(plan['age'], 'zh') + '，')
            chief()
            b.text('。')
            course()
            history_sec()
        self._zh_tail(b, disease, plan, complexity, dz_name, subj, family)

    def _zh_tail(self, b, disease, plan, complexity, dz_name, subj, family):
        """Shared tail: negations, labs, family history, impression."""
        rng = self.rng
        negated, generics = plan['negated'], plan['n_generic_negated']
        items = [('pheno', p) for p in negated] + \
                [('generic', rng.choice(GENERIC_NEGATABLE_ZH)) for _ in range(generics)]
        if items:
            b.text('入院后系统回顾：否认' if family == 'admission' else rng.choice(['系统回顾：否认', '否认', '无']))
            for i, (kind, item) in enumerate(items):
                if i:
                    b.text('、')
                if kind == 'pheno':
                    chunk = self.gloss['phenotypes'][item['hp_id']]
                    start = b.length
                    b.parts.append(chunk); b.length += len(chunk)
                    b.entities.append({'start': start, 'end': b.length, 'text': chunk,
                                       'label': 'PHENOTYPE', 'hp_id': item['hp_id'], 'name_en': item['name'],
                                       'status': 'negated', 'evidence': item['evidence'],
                                       'reference': item['reference'], 'frequency_raw': item['frequency_raw']})
                else:
                    b.entity(item, {'label': 'SYMPTOM_GENERIC', 'status': 'negated'})
            b.text(rng.choice(['。', '病史。', '等表现。']))
        # labs for affirmed lab-linked phenotypes
        lab_lines = []
        for p in plan['affirmed'] + plan['suspected']:
            spec = LAB_PHENOTYPES.get(p['hp_id'])
            if not spec:
                continue
            analytes = ['ALT', 'AST'] if p['hp_id'] == 'HP:0002910' else [spec['analyte']]
            for analyte in analytes:
                if rng.random() < 0.5 and analyte == 'AST':
                    continue
                use_alt = rng.random() < 0.3
                value, unit, std, std_unit = sample_lab_value(rng, analyte, spec['direction'], use_alt)
                lab_lines.append((analyte, value, unit, std, std_unit, p, spec['direction']))
        if rng.random() < 0.25 and complexity != 'simple':
            analyte = rng.choice(['GLUCOSE', 'ALT'])
            value, unit, std, std_unit = sample_normal_lab(rng, analyte)
            lab_lines.append((analyte, value, unit, std, std_unit, None, 'normal'))
        if lab_lines:
            b.text('辅助检查：')
            for i, (analyte, value, unit, std, std_unit, p, direction) in enumerate(lab_lines):
                if i:
                    b.text('，')
                b.entity(LAB_NAME['zh'][analyte], {'label': 'LAB_TEST', 'analyte': analyte})
                b.text(' ')
                rec = {'label': 'LAB_VALUE', 'analyte': analyte, 'unit_raw': unit,
                       'value_std': std, 'unit_std': std_unit, 'direction': direction}
                if p is not None:
                    rec['hp_id'] = p['hp_id']
                b.entity(f'{value} {unit}', rec)
                if direction == 'high':
                    b.text(rng.choice(['，升高', '，高于参考区间', '，明显升高']))
                elif direction == 'low':
                    b.text(rng.choice(['，降低', '，低于参考区间']))
                else:
                    b.text(rng.choice(['，在正常范围', '，大致正常']))
            b.text('。')
        b.text(rng.choice(['家族史：否认家族成员类似疾病史。', '家族史：无特殊。', '家族史：家属叙述不详。']))
        b.text(rng.choice(['初步印象：结合上述表现，需警惕', '初步诊断：考虑', '诊断思路：']))
        b.entity(dz_name, {'label': 'DISEASE', 'disease_id': disease['disease_id']})
        b.text(rng.choice(['可能，建议完善相关检查。', '，待进一步确诊。', '待排。']))

    def _compose_en(self, b, disease, plan, family, complexity, dz_name, sex, emit_pheno, ptext):
        rng = self.rng
        affirmed, suspected, history = plan['affirmed'], plan['suspected'], plan['history']
        subj = 'The child' if plan['age'] < 14 else 'The patient'
        onset_phrase = ONSET_PHRASE_EN.get(plan['onset'])
        b.text(f'{subj} is a {_age_text(plan["age"], "en", style="adjective")} '
               + ('boy' if sex == 'M' and plan['age'] < 14 else 'girl' if plan['age'] < 14 else 'man' if sex == 'M' else 'woman')
               + ' presenting with ')
        emit_pheno(affirmed[0], 'affirmed')
        if len(affirmed) > 1:
            b.text(' and '); emit_pheno(affirmed[1], 'affirmed')
        b.text(' for '); b.entity(rng.choice(DURATIONS_EN), {'label': 'TEMPORAL', 'kind': 'duration'})
        b.text('. ')
        rest = affirmed[2:]
        if onset_phrase:
            b.text('Findings have been noted '); b.entity(onset_phrase, {'label': 'TEMPORAL', 'kind': 'onset'})
            if rest:
                b.text(', including '); emit_pheno(rest[0], 'affirmed'); rest = rest[1:]
            b.text('. ')
        for p in rest:
            b.text(rng.choice(['Examination shows ', 'The course has been complicated by ',
                               'Review of systems is notable for ']))
            emit_pheno(p, 'affirmed'); b.text('. ')
        for p in suspected:
            b.text(rng.choice(['There is suspicion of ', 'Possible ']))
            emit_pheno(p, 'suspected'); b.text(rng.choice(['. ', ', to be confirmed. ']))
        if history:
            b.text('Past history: ')
            for i, p in enumerate(history):
                if i:
                    b.text(', and ')
                b.text(rng.choice(['a history of ', 'previously noted ']))
                emit_pheno(p, 'history')
            b.text('. ')
        items = [('pheno', p) for p in plan['negated']] + \
                [('generic', rng.choice(GENERIC_NEGATABLE_EN)) for _ in range(plan['n_generic_negated'])]
        if items:
            b.text(rng.choice(['The patient denies ', 'No reported ']))
            for i, (kind, item) in enumerate(items):
                if i:
                    b.text(', ')
                if kind == 'pheno':
                    chunk = item['name']
                    start = b.length
                    b.parts.append(chunk); b.length += len(chunk)
                    b.entities.append({'start': start, 'end': b.length, 'text': chunk,
                                       'label': 'PHENOTYPE', 'hp_id': item['hp_id'], 'name_en': item['name'],
                                       'status': 'negated', 'evidence': item['evidence'],
                                       'reference': item['reference'], 'frequency_raw': item['frequency_raw']})
                else:
                    b.entity(item, {'label': 'SYMPTOM_GENERIC', 'status': 'negated'})
            b.text('. ')
        lab_lines = []
        for p in plan['affirmed'] + plan['suspected']:
            spec = LAB_PHENOTYPES.get(p['hp_id'])
            if not spec:
                continue
            analytes = ['ALT', 'AST'] if p['hp_id'] == 'HP:0002910' else [spec['analyte']]
            for analyte in analytes:
                if rng.random() < 0.5 and analyte == 'AST':
                    continue
                use_alt = rng.random() < 0.3
                value, unit, std, std_unit = sample_lab_value(rng, analyte, spec['direction'], use_alt)
                lab_lines.append((analyte, value, unit, std, std_unit, p, spec['direction']))
        if lab_lines:
            b.text('Labs: ')
            for i, (analyte, value, unit, std, std_unit, p, direction) in enumerate(lab_lines):
                if i:
                    b.text(', ')
                b.entity(LAB_NAME['en'][analyte], {'label': 'LAB_TEST', 'analyte': analyte})
                b.text(' ')
                rec = {'label': 'LAB_VALUE', 'analyte': analyte, 'unit_raw': unit,
                       'value_std': std, 'unit_std': std_unit, 'direction': direction}
                if p is not None:
                    rec['hp_id'] = p['hp_id']
                b.entity(f'{value} {unit}', rec)
                b.text({'high': ' (elevated)', 'low': ' (decreased)', 'normal': ' (within range)'}[direction])
            b.text('. ')
        b.text(rng.choice(['Family history is unremarkable. ',
                           'No family history of similar conditions. ',
                           'Family history not available. ']))
        b.text(rng.choice(['Impression: findings raise suspicion for ', 'Assessment: consider ']))
        b.entity(dz_name, {'label': 'DISEASE', 'disease_id': disease['disease_id']})
        b.text(rng.choice(['; further workup recommended.', ', to be confirmed.']))

    # ---- public API ------------------------------------------------------
    def generate(self):
        rng = self.rng
        plan_diseases = self.diseases * (self.n_cases // len(self.diseases) + 1)
        rng.shuffle(plan_diseases)
        plan_diseases = plan_diseases[:self.n_cases]
        records = []
        for index, disease in enumerate(plan_diseases):
            lang = 'zh' if rng.random() < self.zh_ratio else 'en'
            family = rng.choice(['outpatient', 'admission', 'referral'] if lang == 'zh'
                                else ['clinic', 'admission', 'consult'])
            roll = rng.random()
            complexity = 'simple' if roll < 0.25 else ('standard' if roll < 0.75 else 'detailed')
            plan = self.sample_case_plan(disease, complexity)
            text, entities, with_phi = self.compose(disease, plan, lang, family, complexity)
            spec = {
                'affirmed': [p['hp_id'] for p in plan['affirmed']],
                'suspected': [p['hp_id'] for p in plan['suspected']],
                'history': [p['hp_id'] for p in plan['history']],
                'negated': [p['hp_id'] for p in plan['negated']],
                'n_generic_negated': plan['n_generic_negated'],
            }
            records.append({
                'case_id': f'SYN-{index:05d}',
                'disease_id': disease['disease_id'],
                'disease_name': disease['disease_name'],
                'disease_name_zh': self.gloss['diseases'][disease['disease_id']],
                'language': lang, 'template_family': family, 'complexity': complexity,
                'with_phi': with_phi, 'age_years': round(plan['age'], 2),
                'onset_hp': plan['onset'], 'spec': spec, 'text': text, 'entities': entities,
                'generator_version': GENERATOR_VERSION, 'seed': self.seed,
                'hpo_provenance': self.kb['provenance'],
            })
        return records


def load_gloss(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
