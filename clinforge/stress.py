"""Out-of-template synthetic red-team examples. NOT hospital-derived, NOT independent medical annotations."""
from __future__ import annotations
from .synthetic import put_value
from .evaluate import prf, baseline_phi
from .operators import find_phi, parse_labs

STRESS_TEMPLATES = [
 'Name={NAME}; Contact={PHONE}; ChartNo={MRN}; fever 39°C',
 '患者姓名 {NAME}，联系方式 {PHONE}，住院号 {MRN}；T 39°C',
 '姓名：{NAME}; 电话：{PHONE}; 病历号：{MRN}; 主诉：胸闷；体温：37.2℃',
 'Patient: {NAME} | Tel: {PHONE} | MRN: {MRN} | Complaint: headache',
 '就诊者={NAME}; phone={PHONE}; ID={MRN}; 主诉：腹痛',
 '姓名：{NAME}。手机 {PHONE}。病例标识 {MRN}。主诉：乏力',
]


def stress_eval(n=60):
    if n<6:
        raise ValueError('n>=6')
    scores={name:[0,0,0] for name in ['baseline_phi','pipeline_phi']}
    flags={}
    for i in range(n):
        phone = '138'+f'{(371*i+1011)%100000000:08d}'
        if i%6==2:
            phone = phone[:3]+'.'+phone[3:7]+'.'+phone[7:]
        attrs={'NAME': ['Alex Taylor','李若青','陈佳宁'][i%3], 'PHONE':phone,'MRN':f'EDTEST-{i:06d}'}
        text,gold=put_value(STRESS_TEMPLATES[i%len(STRESS_TEMPLATES)],attrs)
        oracle={(s['label'],s['start'],s['end']) for s in gold}
        baseline=baseline_phi(text)
        enhanced={(s.label,s.start,s.end) for s in find_phi(text)}
        for name, pred in [('baseline_phi',baseline),('pipeline_phi',enhanced)]:
            stats=scores[name]
            stats[0]+=len(oracle&pred);stats[1]+=len(pred-oracle);stats[2]+=len(oracle-pred)
    return {'n_cases':n,'n_phi_gold':n*3,'baseline_phi_span_exact':prf(*scores['baseline_phi']),
            'pipeline_phi_span_exact':prf(*scores['pipeline_phi']),
            'known_weaknesses':['Prefixes other than 姓名：/Patient: are not covered',
                                'Phones with dots are not covered',
                                'MRN with other labels are not covered'],
            'scope':'Deliberately separate synthetic stress templates; no real patient data or clinical expert labels.',
            'warning':'Do not use this prototype for real PHI; incomplete recall can expose identifiers.'}
