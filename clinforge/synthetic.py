"""Deterministic labeled SYNTHETIC fixtures; label derivation disclosed, NOT an external benchmark."""
from __future__ import annotations
import json
import random
import re
from pathlib import Path

ZH = ['张若安','李雨桐','王嘉宁','赵泽宇','陈思涵','孙梓萌','刘皓轩','周静怡','吴瑞泽','郑晨曦']
EN = ['Alex Taylor','Morgan Chen','Jamie Reed','Robin Ellis','Casey Lin']
COMPLAINT_ZH = ['头晕两天','腹痛一天','乏力三周','咳嗽五天','夜间胸闷','近期口渴']
COMPLAINT_EN = ['fatigue for three days','abdominal pain since yesterday','dizziness and nausea','five days of cough']


def put_value(template: str, fill: dict) -> tuple[str, list[dict]]:
    """Create gold PHI spans by position of tagged placeholders, independent of the PHI recognizer."""
    out = []
    phi = []
    pos = 0
    for m in re.finditer(r'\{(NAME|PHONE|MRN)\}', template):
        out.append(template[pos:m.start()])
        prefixlen = sum(len(s) for s in out)
        val = fill[m.group(1)]
        phi.append({'start': prefixlen, 'end': prefixlen+len(val), 'label': m.group(1)})
        out.append(val)
        pos = m.end()
    out.append(template[pos:])
    return ''.join(out), phi


def make_dataset(n: int = 600, seed: int = 20261025) -> tuple[list[dict], list[dict]]:
    if n < 20:
        raise ValueError('n must be >=20')
    rng = random.Random(seed)
    rows, labels = [], []
    for i in range(n):
        style = i % 5
        name = EN[i % len(EN)] if style == 2 else ZH[i % len(ZH)]
        phone_digits = '138'+f'{(i*271+1978)%100000000:08d}'
        phone = phone_digits if style in (0,2,4) else phone_digits[:3]+'-'+phone_digits[3:7]+'-'+phone_digits[7:]
        mrn = f'SYNHOSP-{i:06d}'
        temp_c = round(36.2+rng.random()*3.6, 1)
        glucose = round(3.8+rng.random()*12.1, 2)
        hemoglobin = round(85+rng.random()*79, 1)
        alt = round(9+rng.random()*165, 1)
        complaint = rng.choice(COMPLAINT_EN if style==2 else COMPLAINT_ZH)
        if style==0:
            tmpl = ('姓名：{NAME}；电话：{PHONE}；病历号：{MRN}；主诉：'+complaint
                    +f'；体温：{temp_c}℃；血糖：{glucose}mmol/L；血红蛋白：{hemoglobin}g/L；ALT：{alt}U/L。')
        elif style==1:
            tf=round(temp_c*9/5+32, 2)
            gl=round(glucose*18.0182, 3)
            hb=round(hemoglobin/10, 3)
            tmpl=('患者姓名：{NAME} | 手机：{PHONE} | 病历号：{MRN} | 症状描述：'+complaint
                   +f' | T={tf} °F | GLU={gl} mg/dL | Hb={hb} g/dL | ALT={alt} U/L')
        elif style==2:
            gl=round(glucose*18.0182, 3)
            tmpl=('Patient: {NAME} | Tel: {PHONE} | MRN: {MRN} | Complaint: '+complaint
                  +f' | temperature: {temp_c} °C | blood glucose: {gl} mg/dL | '
                   f'hemoglobin: {hemoglobin} g/L | alanine aminotransferase: {alt} U/L')
        elif style==3:
            tf=round(temp_c*9/5+32, 2)
            hb=round(hemoglobin/10,3)
            gl=round(glucose*18.0182,3)
            tmpl=('姓名：{NAME}；联系电话：{PHONE}；病历号：{MRN}；主诉：'+complaint
                   +f'；体温：{tf}°F；血糖：{gl}mg/dL；HGB：{hb}g/dL；ALT：{alt} U/L。')
        else:
            tmpl=('姓名：{NAME}\n电话：{PHONE}\n病历号：{MRN}\n主诉：'+complaint
                  +f'\n体温：{temp_c}°C\n血糖：{glucose} mmol/L\nHb：{hemoglobin} g/L\nALT：{alt} U/L')
        # Make a small number of intentionally abnormal values for quality-gate testing.
        invalid = (i%23 == 0)
        if invalid:
            if style in (0,4):
                tmpl = re.sub(r'(体温：)\d+(?:\.\d+)?', r'\g<1>280', tmpl)
            elif style==1:
                # Match the temperature token, not the suffix of ALT=.
                tmpl=re.sub(r'(?<![A-Za-z0-9_])(T=)\d+(?:\.\d+)?', r'\g<1>700', tmpl, count=1)
            elif style==2:
                tmpl=re.sub(r'(temperature: )\d+(?:\.\d+)?', r'\g<1>280', tmpl)
            else:
                tmpl=re.sub(r'(体温：)\d+(?:\.\d+)?', r'\g<1>700', tmpl)
        text, gold_phi = put_value(tmpl, {'NAME': name, 'PHONE':phone, 'MRN':mrn})
        rid = f'SYN-R{i:05d}'
        grp=f'GROUP-{i:05d}'
        split = ['dev','test','test','test','train'][i%5]
        gold_labs={'glucose_mmol_l':glucose,'hemoglobin_g_l':hemoglobin,'alt_u_l':alt}
        if not invalid:
            gold_labs['temp_c']=temp_c
        row={'record_id':rid,'patient_group':grp,'encounter_group':f'EPISODE-{i:05d}','source_type':'emr_note','text':text}
        label={'record_id':rid,'phi_spans':gold_phi,'labs':gold_labs,
               'duplicate_cluster':grp,'split':split,'generated_from_template':style,'intentional_bad_temperature':invalid}
        rows.append(row); labels.append(label)
        # 1 exact and 1 punctuation/whitespace variant per selected group.
        if i%8==0:
            dup=dict(row,record_id=rid+'-EXACT')
            rows.append(dup)
            labels.append(dict(label, record_id=dup['record_id']))
        if i%11==0:
            # This change is semantically identical and should be detected by shingles.
            variant=text.replace('；',';').replace(' | ','|').replace('  ',' ').replace('。','')
            dup=dict(row,record_id=rid+'-NEAR',text=variant)
            rows.append(dup)
            # spans shift with punctuation replacements: locate PHI values anew.
            new_phi=[]
            for span in gold_phi:
                value=text[span['start']:span['end']]
                idx=variant.find(value)
                new_phi.append({'start':idx,'end':idx+len(value),'label':span['label']})
            labels.append(dict(label,record_id=dup['record_id'],phi_spans=new_phi))
    return rows,labels


def save_dataset(root: str, n: int=600, seed: int=20261025) -> dict:
    root=Path(root)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise FileExistsError(f'Refusing to overwrite existing fixture: {root}')
    rows, labels=make_dataset(n,seed)
    root.mkdir(parents=True,exist_ok=True)
    for name, dataset in [('synthetic_notes.jsonl',rows),('gold_annotations.jsonl',labels)]:
        with (root/name).open('x',encoding='utf-8',newline='\n') as f:
            for r in dataset:
                f.write(json.dumps(r,ensure_ascii=False)+'\n')
    stats={'original_base_records':n,'total_records_including_duplicates':len(rows),
           'gold_duplicate_extra_records':len(rows)-n,
           'synthetic':True,'seed':seed,
           'generator_revision':'phase1-temperature-token-fix',
           'annotation_origin':'programmatically derived from generator; NOT human/clinical gold',
           'template_families':5}
    with (root/'fixture_manifest.json').open('x',encoding='utf-8',newline='\n') as f:
        f.write(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
    return stats
