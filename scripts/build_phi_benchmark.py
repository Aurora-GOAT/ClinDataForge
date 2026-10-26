"""Build a source-pinned, independently constructed synthetic PHI benchmark.

No recognizer, old ClinDataForge generator, model or external inference is used.
The test set is authored/frozen by the data task before method selection.

Sources
-------
English : ASQ-PHI (Adversarial Synthetic Queries for PHI), 100% synthetic,
          MIT licence, pinned revision. Ground-truth PHI tags shipped by the
          upstream authors; we only resolve them to character offsets.
Chinese : templates authored by this dataset task independently of
          clinforge.phi_rules / clinforge.operators and of the frozen test.

Both are machine-labelled. Neither is real patient data.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import math
import json
import random
import re
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261025
BENCHMARK_VERSION = 'phase2-phi-v1'
TARGET_LABELS = ('NAME', 'PHONE', 'PATIENT_ID', 'DATE', 'ADDRESS', 'SSN', 'EMAIL', 'INSURANCE_ID')

# ASQ-PHI identifier_type -> benchmark label. Every mapping is declared here so
# that the scored label inventory can be audited from one place.
SOURCE_LABELS = {
    'NAME': 'NAME',
    'PHONE_NUMBER': 'PHONE',
    'FAX_NUMBER': 'PHONE',
    'MEDICAL_RECORD_NUMBER': 'PATIENT_ID',
    'UNIQUE_IDENTIFIER': 'PATIENT_ID',
    'ACCOUNT_NUMBER': 'PATIENT_ID',
    'HEALTH_PLAN_BENEFICIARY_NUMBER': 'INSURANCE_ID',
    'DATE': 'DATE',
    'GEOGRAPHIC_LOCATION': 'ADDRESS',
    'SOCIAL_SECURITY_NUMBER': 'SSN',
    'EMAIL_ADDRESS': 'EMAIL',
}
# Deliberately out of scope: two elements in total, disclosed in the data card.
EXCLUDED_LABELS = ('CERTIFICATE_LICENSE_NUMBER', 'IP_ADDRESS')

ASQ_ROOT = ROOT / 'data/external/asq_phi'
ASQ_FILE = ASQ_ROOT / 'data/synthetic_clinical_queries.txt'
ASQ_MANIFEST = ASQ_ROOT / 'source_manifest.json'
ASQ_CITATION = ('Weatherhead, Golovko & McCaffrey (2026) Data in Brief 65:112586 '
                'doi:10.1016/j.dib.2026.112586')

# These structures were authored independently by the dataset task. No existing
# detector patterns or original ClinDataForge templates are imported or inspected.
ZH_TEMPLATES = [
    '护理交班记录\n{DATE}晚班接收{NAME}，档案索引{PATIENT_ID}。{CLINICAL}出院后的联系号码为{PHONE}，家中通信位置记在{ADDRESS}。',
    '门诊随访便笺：请在{DATE}回电{PHONE}与{NAME}确认复诊。检索患者登记码{PATIENT_ID}，寄送地址{ADDRESS}。医生记录：{CLINICAL}',
    '【急诊观察】{NAME}于{DATE}由家属陪同就诊。卡片编号{PATIENT_ID}；{CLINICAL}若离院后不适加重可联系{PHONE}，居所位于{ADDRESS}。',
    '转诊联络单\n接收日{DATE}，转诊对象{NAME}，资料序号{PATIENT_ID}。{CLINICAL}请接诊单位核对通信住址{ADDRESS}并拨打{PHONE}通知。',
    '出院计划讨论：{NAME}拟于{DATE}结束观察，院内登记{PATIENT_ID}。{CLINICAL}居家随访去{ADDRESS}，电话联络使用{PHONE}。',
    '会诊申请摘录｜日期{DATE}｜受评估人{NAME}｜就医卡索引{PATIENT_ID}。{CLINICAL}此人的回访号码{PHONE}与地址{ADDRESS}仅供院内联络。',
    '电话随访：我们在{DATE}拨通{PHONE}，接听者{NAME}确认登记编号{PATIENT_ID}及住所{ADDRESS}。关于病情，{CLINICAL}',
    '康复评估笔记中，{NAME}的档案代码写作{PATIENT_ID}。{CLINICAL}首次评估安排于{DATE}；需要上门时请先拨{PHONE}，再前往{ADDRESS}。',
    '值班医生备忘\n请查阅{PATIENT_ID}对应的{NAME}。{CLINICAL}其{DATE}留存的紧急联系方法是{PHONE}，邮寄材料至{ADDRESS}。',
    '检验咨询登记：{NAME}（就诊凭证{PATIENT_ID}）在{DATE}提出咨询。{CLINICAL}回执寄往{ADDRESS}，发送前通过{PHONE}确认。',
    '预约受理记录：{DATE}登记复查，申请人为{NAME}，资料号{PATIENT_ID}。{CLINICAL}联络请用{PHONE}，通信栏记为{ADDRESS}。',
    '家庭病床交接摘要：{NAME}的服务地址为{ADDRESS}，服务档案{PATIENT_ID}，可拨{PHONE}。{DATE}记录的情况为：{CLINICAL}',
    '病区沟通摘记：{DATE}与{NAME}交流后核对卡号{PATIENT_ID}。{CLINICAL}本人表示回家后可在{PHONE}找到，住在{ADDRESS}。',
    '复查提醒任务｜请于{DATE}给{NAME}拨号{PHONE}。对应患者索引{PATIENT_ID}；{CLINICAL}登记住址是{ADDRESS}。',
    '营养门诊记录：档案{PATIENT_ID}属于{NAME}，面谈时间{DATE}。{CLINICAL}建议复诊前保留联络电话{PHONE}，材料可寄到{ADDRESS}。',
    '麻醉评估预约：{NAME}，信息号{PATIENT_ID}，约定日{DATE}。{CLINICAL}术前通知走{PHONE}；评估单上的居住地为{ADDRESS}。',
    '专科门诊给全科的回信：{DATE}见过{NAME}，使用病人检索码{PATIENT_ID}。{CLINICAL}联系电话{PHONE}，回信收件地{ADDRESS}。',
    '院内质控抽查摘录\n对象{NAME}，就诊资料码{PATIENT_ID}，所查日期{DATE}。{CLINICAL}联络字段记有{PHONE}和{ADDRESS}。',
    '慢病随访日志：在{DATE}核对{PATIENT_ID}后，{NAME}报告{CLINICAL}下一次随访联系{PHONE}，必要时到{ADDRESS}。',
    '小组交接清单中的{NAME}：档案标签{PATIENT_ID}，上次接触{DATE}。{CLINICAL}回拨{PHONE}可核实情况；家庭访视地点{ADDRESS}。',
    '社区转介附言：请接收{NAME}，其登记序列是{PATIENT_ID}。{CLINICAL}转介日期{DATE}，社区护士可用{PHONE}联系，地址栏{ADDRESS}。',
    '术后回访手记：{DATE}询问{NAME}恢复情况，病历检索键{PATIENT_ID}。{CLINICAL}离院后登记到{ADDRESS}居住，随访号码{PHONE}。',
    '诊间记录补充：就医资料编号{PATIENT_ID}，患者称呼{NAME}，问诊发生于{DATE}。{CLINICAL}其电话为{PHONE}；本次登记的住址是{ADDRESS}。',
    '远程门诊工作单\n{NAME}使用索引{PATIENT_ID}申请{DATE}咨询。{CLINICAL}联系设备号码{PHONE}，纸质病情摘要寄给{ADDRESS}。',
    '药学咨询回执：{DATE}为{NAME}核对治疗记录（个人病历键{PATIENT_ID}）。{CLINICAL}回复可发至住址{ADDRESS}，也可致电{PHONE}。',
    '多学科讨论纪要：{NAME}的资料位于索引{PATIENT_ID}下。{CLINICAL}讨论日{DATE}。家中可联系{PHONE}，出院登记地为{ADDRESS}。',
    '病案借阅交接：借阅{PATIENT_ID}时核对对象{NAME}。{DATE}的诊疗摘要为{CLINICAL}需要补充信息时拨打{PHONE}，邮递住处{ADDRESS}。',
    '护理评估摘录：{DATE}录入，受访者{NAME}，档案流水{PATIENT_ID}。{CLINICAL}本人留下电话号码{PHONE}，通讯地址{ADDRESS}。',
    '健康管理服务函：致{NAME}，您的管理索引为{PATIENT_ID}。{CLINICAL}我们拟在{DATE}经{PHONE}安排复诊，函件寄至{ADDRESS}。',
    '日间病房离院沟通：{NAME}于{DATE}完成观察，资料登记为{PATIENT_ID}。{CLINICAL}接下来请用{PHONE}保持联络，居住记录为{ADDRESS}。',
    '检后随访记录｜索引{PATIENT_ID}，对象{NAME}，联系日{DATE}。{CLINICAL}回访号码写作{PHONE}，邮件收取地点{ADDRESS}。',
    '救护转运交接条：{DATE}转交{NAME}，院内人员可通过{PATIENT_ID}调取资料。{CLINICAL}家庭联系人号码{PHONE}，去向住址{ADDRESS}。',
    '影像咨询登记附注：{NAME}持患者代码{PATIENT_ID}于{DATE}咨询。{CLINICAL}报告邮寄地{ADDRESS}，通知领取请拨{PHONE}。',
    '术前讨论联系簿：对象为{NAME}，档案号写成{PATIENT_ID}，安排在{DATE}。{CLINICAL}电话号码{PHONE}，纸质表单送至{ADDRESS}。',
    '居家护理预约单\n访视对象{NAME}、服务序号{PATIENT_ID}、预约日{DATE}。{CLINICAL}请先致电{PHONE}，访视位置为{ADDRESS}。',
    '呼吸专科复诊沟通：{NAME}在{DATE}提供档案检索号{PATIENT_ID}。{CLINICAL}下一步通过{PHONE}告知安排，本人登记住在{ADDRESS}。',
    '临床研究排除记录：{NAME}（受诊资料号{PATIENT_ID}）于{DATE}来院。{CLINICAL}仅在临床联系需要时使用{PHONE}及{ADDRESS}。',
    '接诊护士的补录：资料条目{PATIENT_ID}对应{NAME}，原接诊日期{DATE}。{CLINICAL}登记电话{PHONE}，通信目的地{ADDRESS}。',
    '复诊改期联络稿：请在{DATE}向{NAME}确认资料代码{PATIENT_ID}。{CLINICAL}拨号目标{PHONE}，若改发信件则收件地址{ADDRESS}。',
    '临床路径交班附页：{DATE}核对过{NAME}的个人检索号{PATIENT_ID}。{CLINICAL}随访时可在{PHONE}联系到本人，登记居所{ADDRESS}。',
]

# Hard negatives: one distinct no-PHI administrative/clinical note per template
# family. An earlier version differed only by a family digit, which made all 40
# negatives mutually near-duplicate and collapsed the whole Chinese set into a
# single leakage unit. They are now authored to be individually distinct.
ZH_NEGATIVE_NOTES = [
    '内科晨会记录：本周讨论重点为老年患者血压管理的随访节奏安排。',
    '护理部质控简报：抽查发现交接班记录书写不完整，需要加强模板培训。',
    '药剂科通报：本月抗菌药物使用强度较上月下降，仍需关注联合用药指征。',
    '检验科说明：新建的标本拒收标准已在内网发布，请各病区遵照执行。',
    '门诊办公室通知：预约挂号系统升级后放号时间调整，导医台已张贴说明。',
    '急诊科复盘：本次演练暴露的瓶颈在于留观床位周转，拟增设定期评估环节。',
    '影像科提示：增强检查知情同意书版本更新，旧版即日起停止使用。',
    '院感科简报：手卫生依从性调查结果已反馈至各科室，下季度将复查。',
    '病案室通知：归档病历的完整性检查改为每周一次，缺项清单以邮件反馈。',
    '康复科计划：团体训练课程表已排定，重点为平衡能力与步态训练。',
    '营养科宣教材料：低盐饮食的实操示例已补充图片说明，可自行取阅。',
    '麻醉科提醒：术前评估表单新增过敏史条目，请术前访视时逐项确认。',
    '心内科纪要：本次讨论聚焦射血分数保留型心衰的随访指标选择。',
    '呼吸科纪要：吸入装置使用错误率偏高，拟在操作台旁增设示范视频。',
    '消化科纪要：内镜检查前肠道准备的宣教话术统一后患者投诉下降。',
    '内分泌科纪要：血糖记录表单字段调整，便于后续统计与脱敏导出。',
    '肾内科纪要：透析患者的干体重评估频次调整为每月一次并记录趋势。',
    '神经内科纪要：卒中绿色通道的时间节点记录方式将改为自动采集。',
    '肿瘤科纪要：化疗方案的剂量核对流程增加双人复核环节。',
    '儿科纪要：儿童发热就诊的分诊标准已根据最新指南修订。',
    '妇产科纪要：产后访视的内容清单重新梳理，重点为母乳喂养支持。',
    '骨科纪要：术后康复路径的阶段性目标已细化到每周。',
    '泌尿外科纪要：结石成分分析的送检流程说明已更新。',
    '眼科纪要：白内障术前测量的设备校准记录纳入月度质控。',
    '耳鼻喉科纪要：听力筛查的转诊标准已在科室内网公示。',
    '皮肤科纪要：慢性湿疹的随访间隔建议写入门诊模板。',
    '风湿免疫科纪要：免疫抑制剂治疗前的筛查项目清单已统一。',
    '血液科纪要：输血不良反应上报流程简化为线上提交。',
    '感染科纪要：发热待查的初步评估表单增加流行病学史条目。',
    '重症医学科纪要：镇静深度评估的记录频次与脱机评估保持同步。',
    '老年医学科纪要：多重用药核查表将纳入入院评估的必填项。',
    '疼痛科纪要：慢性疼痛评估量表的选择标准已形成书面说明。',
    '中医科纪要：针灸治疗前后的记录要求已在模板中明确。',
    '口腔科纪要：种植修复的术前影像资料归档目录已统一命名。',
    '精神科纪要：焦虑抑郁量表的结果仅记录分级，不记录原始条目内容。',
    '全科医学纪要：转诊单必填字段调整后退回率明显下降。',
    '健康管理中心纪要：体检报告解读门诊的排班规则已明确。',
    '日间病房纪要：出入院评估表单合并为一张，减少重复填写。',
    '临床研究协调纪要：受试者筛选记录的保存期限与伦理要求保持一致。',
    '医学装备科纪要：输注泵的预防性维护计划按季度排程执行。',
]

ZH_CLINICAL = [
    '主诉：活动后气短三天；体温：37.1℃；血糖：5.8mmol/L；否认胸痛。',
    '主诉：腹部隐痛两天；体温：36.8℃；血红蛋白：128g/L；建议复查血常规。',
    '主诉：咳嗽伴少量白痰五天；体温：37.4℃；ALT：32U/L；无咯血。',
    '主诉：头晕一周；体温：36.7℃；血糖：6.2mmol/L；血压为132/78mmHg。',
    '主诉：乏力伴食欲下降；体温：36.9℃；血红蛋白：115g/L；继续观察症状。',
    '主诉：膝关节活动痛；体温：36.6℃；ALT：25U/L；步行后症状加重。',
    '主诉：夜间口渴；体温：37.0℃；血糖：9.3mmol/L；拟评估糖代谢。',
    '主诉：皮疹伴瘙痒；体温：36.5℃；ALT：29U/L；无呼吸困难。',
    '主诉：反复反酸两周；体温：36.8℃；血红蛋白：137g/L；体重近期稳定。',
    '主诉：睡眠不佳；体温：36.7℃；血糖：5.4mmol/L；保持规律作息。',
    '主诉：腰背痛三天；体温：36.9℃；ALT：30U/L；未出现肢体无力。',
    '主诉：心悸两次；体温：37.0℃；血红蛋白：131g/L；拟行心电图检查。',
    '主诉：间断恶心；体温：36.6℃；血糖：5.9mmol/L；继续补液观察。',
    '主诉：声音嘶哑一周；体温：36.8℃；ALT：24U/L；避免过度用嗓。',
    '主诉：双踝轻度水肿；体温：36.9℃；血红蛋白：126g/L；监测体重变化。',
    '主诉：运动后喘息；体温：37.2℃；血糖：6.1mmol/L；吸入治疗后好转。',
    '主诉：便秘四天；体温：36.5℃；血红蛋白：139g/L；调整膳食纤维摄入。',
    '主诉：肩部酸痛；体温：36.7℃；ALT：27U/L；建议适度活动。',
    '主诉：手指麻木；体温：36.8℃；血糖：7.2mmol/L；暂未见肌力下降。',
    '主诉：晨起头痛；体温：36.9℃；血红蛋白：133g/L；无颈项强直。',
]

# Clinical vocabulary that must survive de-identification. It is a programmatic,
# necessarily incomplete proxy for "useful medical content", never a clinician
# judgement of what is safe to keep.
EN_CLINICAL_TERMS = (
    'chronic kidney disease', 'hypertension', 'iron deficiency anemia', 'abdominal pain',
    'heart failure', 'chest pain', 'type 2 diabetes', 'diabetes', 'asthma', 'COPD', 'MS',
    'ACE inhibitors', 'insulin', 'metformin', 'bypass surgery', 'atrial fibrillation',
    'rheumatoid arthritis', 'multiple sclerosis', 'pneumonia', 'migraine', 'seizures',
    'epilepsy', 'cancer', 'chemotherapy', 'statins', 'blood pressure', 'hemoglobin',
    'glucose', 'stroke', 'anemia', 'dialysis', 'ECG', 'MRI', 'CT', 'beta-blockers',
    'depression', 'anxiety', 'osteoarthritis', 'hyperlipidemia', 'kidney', 'cardiac',
    'treatment', 'diagnosis', 'symptoms', 'medication', 'management', 'recommendations',
    'guidelines', 'surgery', 'therapy', 'patient', 'patients', 'female', 'male',
)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def overlaps(a, b):
    return a['start'] < b['end'] and b['start'] < a['end']


def render(template, values):
    parts, entities, protected = [], [], []
    position = 0
    for literal, field, spec, conversion in string.Formatter().parse(template):
        parts.append(literal)
        position += len(literal)
        if field is not None:
            value = values[field]
            annotation = {'start': position, 'end': position + len(value),
                          'label': 'CLINICAL' if field == 'CLINICAL' else field}
            (protected if field == 'CLINICAL' else entities).append(annotation)
            parts.append(value)
            position += len(value)
    return ''.join(parts), entities, protected


def clinical_spans(text, entities):
    matches = []
    for term in sorted(EN_CLINICAL_TERMS, key=lambda value: (-len(value), value)):
        for match in re.finditer(r'(?<![A-Za-z])' + re.escape(term) + r'(?![A-Za-z])', text, re.I):
            span = {'start': match.start(), 'end': match.end(), 'label': 'CLINICAL'}
            if not any(overlaps(span, other) for other in entities + matches):
                matches.append(span)
    # Under-90 age expressions are explicitly hard-negative clinical context in
    # ASQ-PHI. This only protects the stated under-90 ages, not arbitrary dates.
    for match in re.finditer(r'\b(?:[1-8]?[0-9]|9[0-9])-year-old\b', text):
        span = {'start': match.start(), 'end': match.end(), 'label': 'CLINICAL'}
        if not any(overlaps(span, other) for other in entities + matches):
            matches.append(span)
    return sorted(matches, key=lambda span: (span['start'], span['end']))


# --------------------------------------------------------------------------
# English source: ASQ-PHI
# --------------------------------------------------------------------------
def verify_asq_sources():
    """Every pinned upstream file must match the hash recorded at download time."""
    manifest = json.loads(ASQ_MANIFEST.read_text(encoding='utf-8'))
    checks = {}
    for name, entry in manifest['files'].items():
        path = ASQ_ROOT / name
        if not path.is_file():
            raise FileNotFoundError('Pinned ASQ-PHI file missing: ' + name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry['sha256']:
            raise ValueError(f'ASQ-PHI source hash mismatch for {name}')
        checks[name] = {'sha256': actual, 'bytes': path.stat().st_size}
    return {'repository': manifest['repository'], 'revision': manifest['revision'],
            'license': manifest['license'], 'citation': ASQ_CITATION,
            'verified_files': checks}


def parse_asq_phi(path):
    """Parse the upstream delimiter format without altering any content."""
    raw = path.read_text(encoding='utf-8')
    records, unresolved = [], []
    blocks = re.split(r'^===QUERY===\s*$', raw, flags=re.MULTILINE)[1:]
    for index, block in enumerate(blocks):
        if '===PHI_TAGS===' not in block:
            raise ValueError('Malformed ASQ-PHI block at index %d' % index)
        query, tags = block.split('===PHI_TAGS===', 1)
        text = query.strip('\n')
        spans, used = [], []
        for line in tags.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            tag = json.loads(line)
            source_label = tag['identifier_type']
            value = tag['value']
            if source_label in EXCLUDED_LABELS:
                unresolved.append({'doc_index': index, 'identifier_type': source_label,
                                   'value': value, 'reason': 'declared out of scope'})
                continue
            label = SOURCE_LABELS.get(source_label)
            if label is None:
                raise ValueError('Undeclared ASQ-PHI identifier type: ' + source_label)
            position = -1
            while True:
                position = text.find(value, position + 1)
                if position < 0:
                    break
                end = position + len(value)
                if not any(overlaps({'start': position, 'end': end}, prior) for prior in used):
                    break
            if position < 0:
                unresolved.append({'doc_index': index, 'identifier_type': source_label,
                                   'value': value, 'reason': 'value not found verbatim in query'})
                continue
            span = {'start': position, 'end': end, 'label': label}
            spans.append(span)
            used.append(span)
        records.append({'index': index, 'text': text, 'tags': tags.strip(), 'entities': spans})
    return records, unresolved


def english_records():
    parsed, unresolved = parse_asq_phi(ASQ_FILE)
    rows = []
    for record in parsed:
        entities = sorted(record['entities'], key=lambda s: (s['start'], s['end']))
        protected = clinical_spans(record['text'], entities)
        rows.append({'doc_id': f'EN-{record["index"]:04d}', 'text': record['text'],
                     'entities': entities,
                     'protected_spans': protected, 'language': 'en',
                     'source': 'ASQ-PHI v1 (synthetic clinical queries; MIT)',
                     'source_ref': 'github.com/JamesWeatherhead/asq-phi',
                     'source_group': f'EN-source-{record["index"]:04d}',
                     'patient_group': f'EN-query-{record["index"]:04d}',
                     'annotation_origin': 'upstream author-provided PHI tag values resolved to offsets; no human re-adjudication here',
                     'protected_annotation_origin': 'programmatic clinical-vocabulary and under-90 age spans; incomplete proxy',
                     'synthetic': True})
    return rows, unresolved, len(parsed)


def chinese_records():
    surnames = '陈林周吴郑王李赵钱孙冯蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜谢苏'
    given_a, given_b = '明若嘉思宇清晨子安文', '宁远然涵辰桐岚泽悦霖'
    cities = ['杭州市', '成都市', '苏州市', '武汉市', '宁波市', '南京市', '合肥市', '厦门市']
    roads = ['清溪路', '云杉路', '柳堤路', '青榆路', '梧桐路', '锦云路', '和景路', '望川路']
    rows = []
    for family, template in enumerate(ZH_TEMPLATES):
        for instance in range(8):
            index = family * 8 + instance
            clinical = ZH_CLINICAL[(family * 3 + instance) % len(ZH_CLINICAL)]
            if instance == 7:
                text = ZH_NEGATIVE_NOTES[family] + clinical
                entities = []
                start = text.index(clinical)
                protected = [{'start': start, 'end': start + len(clinical), 'label': 'CLINICAL'}]
            else:
                name = surnames[index % len(surnames)] + given_a[(index // len(surnames)) % len(given_a)] + given_b[(index // (len(surnames) * len(given_a))) % len(given_b)]
                digits = str(13000000000 + index * 103 + 197)
                phone_styles = [digits, digits[:3] + '-' + digits[3:7] + '-' + digits[7:],
                                '+86 ' + digits, '(' + digits[:3] + ') ' + digits[3:7] + ' ' + digits[7:]]
                dates = [f'2025年{index % 12 + 1}月{index % 27 + 1}日',
                         f'2025-{index % 12 + 1:02d}-{index % 27 + 1:02d}',
                         f'{index % 12 + 1}/{index % 27 + 1}/2025',
                         f'2025.{index % 12 + 1:02d}.{index % 27 + 1:02d}']
                ids = [f'ZY{index + 700100}', f'CF-{index + 301000:07d}',
                       f'RX{index + 451000}A', f'2025/{index + 611000}']
                values = {'NAME': name, 'PHONE': phone_styles[index % 4],
                          'PATIENT_ID': ids[index % 4], 'DATE': dates[index % 4],
                          'ADDRESS': cities[index % len(cities)] + roads[(index // len(cities)) % len(roads)] + f'{index + 31}号{index % 6 + 1}单元',
                          'CLINICAL': clinical}
                text, entities, protected = render(template, values)
            rows.append({'doc_id': f'ZH-{index:04d}', 'text': text, 'entities': entities,
                         'protected_spans': protected, 'language': 'zh',
                         'source': 'ClinDataForge-independent-zh-v1',
                         'source_ref': 'scripts/build_phi_benchmark.py',
                         'source_group': f'ZH-source-{index:04d}',
                         'patient_group': f'ZH-patient-{index:04d}',
                         'template_group': f'ZH-family-{family:02d}',
                         'annotation_origin': 'programmatic-placeholder-spans; no human review',
                         'protected_annotation_origin': 'author-defined-clinical-segment-programmatic-offsets; no human review',
                         'synthetic': True})
    return rows


# --------------------------------------------------------------------------
# Leakage control: near-duplicate / same-template connected components
# --------------------------------------------------------------------------
class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, n):
        while self.parent[n] != n:
            self.parent[n] = self.parent[self.parent[n]]
            n = self.parent[n]
        return n

    def union(self, a, b):
        self.parent[self.find(b)] = self.find(a)


def skeleton(row):
    """Text with every gold PHI and clinical segment replaced by its label.

    Two documents that differ only in PHI values or in the wording of their
    authored clinical segment share a skeleton, so they are treated as one
    leakage unit and can never land in different splits.
    """
    text, position, parts = row['text'], 0, []
    for span in sorted(row['entities'] + row['protected_spans'], key=lambda s: s['start']):
        if span['start'] < position:
            continue
        parts.extend((text[position:span['start']], ' <' + span['label'] + '> '))
        position = span['end']
    parts.append(text[position:])
    normalized = re.sub(r'\d+', '#', ''.join(parts).casefold())
    return re.sub(r'\s+', ' ', normalized).strip()


def gram_set(text, n=5):
    compact = re.sub(r'\W+', '', text, flags=re.UNICODE)
    return {compact[i:i + n] for i in range(max(1, len(compact) - n + 1))}


def shingle_set(value, n=6):
    """Slice an already-normalised value. Used for the audit-identical mask."""
    return {value[i:i + n] for i in range(max(1, len(value) - n + 1))}


def compact_mask(row):
    """Second masking used by the independent audit: keep digits, drop every
    non-alphanumeric character, so two different masking rules must both agree
    before a pair is considered safe to separate."""
    text, position, parts = row['text'], 0, []
    for span in sorted(row['entities'] + row['protected_spans'], key=lambda s: s['start']):
        if span['start'] < position:
            continue
        parts.extend((text[position:span['start']], '|' + span['label'] + '|'))
        position = span['end']
    parts.append(text[position:])
    return re.sub(r'[^0-9a-z一-鿿|]+', '', ''.join(parts).lower())


def near_duplicate_components(rows, threshold=.5, compact_threshold=.5):
    """Union documents that are near-duplicates so no variant crosses a split.

    Three independent signals, any of which forces two documents into the same
    leakage unit: identical PHI/clinical-masked skeleton, 5-gram Jaccard on the
    skeleton, and 6-gram Jaccard on a differently masked copy. Authored
    template families are additionally unioned outright.
    """
    skeletons = [skeleton(row) for row in rows]
    compacts = [compact_mask(row) for row in rows]
    grams = [gram_set(value) for value in skeletons]
    compact_grams = [shingle_set(value, 6) for value in compacts]
    union = UnionFind(len(rows))
    for group in (skeletons, compacts):
        buckets = collections.defaultdict(list)
        for index, value in enumerate(group):
            buckets[value].append(index)
        for members in buckets.values():
            for other in members[1:]:
                union.union(members[0], other)
    families = collections.defaultdict(list)
    for index, row in enumerate(rows):
        families[row.get('template_group', 'singleton-%d' % index)].append(index)
    for members in families.values():
        for other in members[1:]:
            union.union(members[0], other)

    for left, right in jaccard_pairs(grams, threshold):
        union.union(left, right)
    for left, right in jaccard_pairs(compact_grams, compact_threshold):
        union.union(left, right)
    return [union.find(index) for index in range(len(rows))]


def jaccard_pairs(sets_list, threshold):
    """Exact Jaccard similarity join by prefix filtering (no false negatives).

    Prefix length is |S| - ceil(t*|S|) + 1 over a globally frequency-ordered
    shingle order, which is the standard completeness condition: any pair with
    Jaccard >= t must share at least one indexed shingle.
    """
    frequency = collections.Counter()
    for value in sets_list:
        frequency.update(value)
    order = {key: rank for rank, key in enumerate(sorted(frequency, key=lambda k: (frequency[k], k)))}
    inverted = collections.defaultdict(list)
    for index, value in enumerate(sets_list):
        if not value:
            continue
        ordered = sorted(value, key=lambda key: order[key])
        prefix = max(1, min(len(ordered), len(ordered) - math.ceil(threshold * len(ordered)) + 1))
        for key in ordered[:prefix]:
            inverted[key].append(index)
    candidates = set()
    for members in inverted.values():
        if len(members) < 2:
            continue
        ordered = sorted(members)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                candidates.add((ordered[i], ordered[j]))
    found = []
    for left, right in candidates:
        a, b = sets_list[left], sets_list[right]
        intersection = len(a & b)
        if intersection and intersection / (len(a) + len(b) - intersection) >= threshold:
            found.append((left, right))
    return found


def assign_splits(rows, components, seed=SEED):
    """Split by connected component, per language, with fixed quotas."""
    quotas = (('train', .25), ('dev', .20), ('test', .55))
    split_of = {}
    for language in sorted({row['language'] for row in rows}):
        members = [i for i, row in enumerate(rows) if row['language'] == language]
        total = len(members)
        groups = collections.defaultdict(list)
        for index in members:
            groups[components[index]].append(index)
        keys = sorted(groups)
        rng = random.Random(seed + sum(ord(character) for character in language))
        rng.shuffle(keys)
        assigned, cursor = {}, 0
        for name, share in quotas:
            target = total * share
            taken = 0
            while cursor < len(keys) and taken < target:
                key = keys[cursor]
                assigned[key] = name
                taken += len(groups[key])
                cursor += 1
        for key in keys[cursor:]:
            assigned[key] = 'test'
        for key, name in assigned.items():
            for index in groups[key]:
                split_of[index] = name
    missing = [rows[i]['doc_id'] for i in range(len(rows)) if i not in split_of]
    if missing:
        raise ValueError('Unassigned documents: ' + ', '.join(missing[:5]))
    return split_of


def assert_contract(rows):
    ids = set()
    for row in rows:
        if row['doc_id'] in ids:
            raise ValueError('Duplicate document ID')
        ids.add(row['doc_id'])
        for name in ('entities', 'protected_spans'):
            spans = sorted(row[name], key=lambda s: (s['start'], s['end']))
            for span in spans:
                if not 0 <= span['start'] < span['end'] <= len(row['text']):
                    raise ValueError('Bad span offset')
                if name == 'entities' and span['label'] not in TARGET_LABELS:
                    raise ValueError('Unsupported gold label: ' + span['label'])
            if any(overlaps(a, b) for a, b in zip(spans, spans[1:])):
                raise ValueError('Overlapping spans')
        if any(overlaps(a, b) for a in row['entities'] for b in row['protected_spans']):
            raise ValueError('PHI/protected annotation conflict')


def dump_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def dump_rows(path, rows):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(canonical(row) + '\n')


def label_histogram(rows):
    counter = collections.Counter()
    for row in rows:
        for span in row['entities']:
            counter[span['label']] += 1
    return {label: counter.get(label, 0) for label in TARGET_LABELS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data/phase2_phi_v1')
    args = parser.parse_args(argv)
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)

    source_verification = verify_asq_sources()
    english, unresolved, parsed_count = english_records()
    chinese = chinese_records()
    rows = english + chinese
    assert_contract(rows)

    components = near_duplicate_components(rows)
    roots = {}
    for index, component in enumerate(components):
        roots.setdefault(component, len(roots))
    for index, row in enumerate(rows):
        row['near_duplicate_group'] = f'ND-{roots[components[index]]:04d}'
        row['bootstrap_group'] = row['near_duplicate_group']
    split_of = assign_splits(rows, components)

    files = {}
    splits = {}
    for name in ('train', 'dev', 'test'):
        selected = [dict(rows[i], split=name) for i in sorted(split_of) if split_of[i] == name]
        splits[name] = selected
        path = out / (name + '.jsonl')
        dump_rows(path, selected)
        files[name + '.jsonl'] = hashlib.sha256(path.read_bytes()).hexdigest()
    demo = splits['train'][:40]
    dump_rows(out / 'demo_pipeline.jsonl', demo)
    files['demo_pipeline.jsonl'] = hashlib.sha256((out / 'demo_pipeline.jsonl').read_bytes()).hexdigest()

    # A component must never appear in two splits.
    by_component = collections.defaultdict(set)
    for index, name in split_of.items():
        by_component[components[index]].add(name)
    leaked = [key for key, value in by_component.items() if len(value) > 1]
    if leaked:
        raise ValueError('Near-duplicate component spans multiple splits')

    manifest = {
        'benchmark_version': BENCHMARK_VERSION,
        'built_at_utc': None,
        'seed': SEED,
        'labels': list(TARGET_LABELS),
        'label_mapping_from_asq_phi': SOURCE_LABELS,
        'excluded_asq_phi_types': list(EXCLUDED_LABELS),
        'sources': {
            'en': {'name': 'ASQ-PHI v1', 'license': source_verification['license'],
                   'repository': source_verification['repository'],
                   'revision': source_verification['revision'],
                   'citation': source_verification['citation'],
                   'nature': '100% synthetic clinical search queries generated upstream with GPT-4o; no real patient data',
                   'n_parsed': parsed_count, 'n_records': len(english),
                   'verified_files': source_verification['verified_files']},
            'zh': {'name': 'ClinDataForge-independent-zh-v1', 'license': 'same repository licence (MIT)',
                   'generator': 'scripts/build_phi_benchmark.py',
                   'nature': 'programmatic templates authored independently of the detectors; machine labels',
                   'n_records': len(chinese),
                   'n_template_families': len(ZH_TEMPLATES)},
        },
        'annotation': {
            'gold_origin': 'upstream author PHI tags (en) and programmatic placeholders (zh)',
            'human_adjudication': False,
            'protected_span_origin': 'programmatic clinical vocabulary / under-90 age / authored clinical segment',
            'protected_span_completeness': 'incomplete proxy; absence of a protected label is not evidence that text is non-clinical',
        },
        'unresolved_asq_phi_values': unresolved,
        'split': {
            'unit': 'near-duplicate connected component (5-gram Jaccard >= 0.70 on PHI-masked skeleton, identical skeleton always joined)',
            'quotas_by_record_share': {'train': .25, 'dev': .20, 'test': .55},
            'seed': SEED,
            'components_total': len(by_component),
            'components_crossing_splits': len(leaked),
        },
        'counts': {},
        'files': files,
    }
    for name, selected in splits.items():
        manifest['counts'][name] = {
            'n_records': len(selected),
            'n_with_phi': sum(1 for row in selected if row['entities']),
            'n_without_phi': sum(1 for row in selected if not row['entities']),
            'n_entities': sum(len(row['entities']) for row in selected),
            'by_language': dict(collections.Counter(row['language'] for row in selected)),
            'by_label': label_histogram(selected),
            'protected_characters': sum(sum(s['end'] - s['start'] for s in row['protected_spans'])
                                        for row in selected),
        }
    manifest['counts']['all'] = {
        'n_records': len(rows),
        'n_entities': sum(len(row['entities']) for row in rows),
        'by_label': label_histogram(rows),
    }
    import datetime
    manifest['built_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dump_json(out / 'manifest.json', manifest)
    print(json.dumps({'out': str(out), 'counts': manifest['counts'],
                      'unresolved': len(unresolved),
                      'components': len(by_component)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
