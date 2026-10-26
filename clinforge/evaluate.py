"""Synthetic oracle metrics: extract/PII/de-dup. Not independent expert annotation."""
from __future__ import annotations
import collections
import math
from .operators import find_phi, parse_labs, process_record, deduplicate
from .pipeline import load_jsonl


def prf(tp, fp, fn):
    p=tp/(tp+fp) if tp+fp else 0
    r=tp/(tp+fn) if tp+fn else 0
    f=2*p*r/(p+r) if p+r else 0
    return {'tp':tp,'fp':fp,'fn':fn,'precision':round(p,4),'recall':round(r,4),'f1':round(f,4)}


def baseline_phi(text):
    """Documented naive baseline: recognizes only contiguous mainland phone numbers."""
    import re
    return {('PHONE', *m.span()) for m in re.finditer(r'(?<!\d)1[3-9]\d{9}(?!\d)',text)}


def baseline_labs(text):
    """Documented naive baseline: supports only temperature with ℃ and glucose mmol/L."""
    import re
    res={}
    t=re.search(r'体温：([\d.]+)℃',text)
    g=re.search(r'血糖：([\d.]+)\s*mmol/L',text)
    if t:
        v=float(t.group(1))
        if 25<=v<=46: res['temp_c']=v
    if g:
        v=float(g.group(1))
        if .5<=v<=55: res['glucose_mmol_l']=v
    return res


def compare_labs(predict, gold):
    """Prediction and gold may be absent for unsupported or intentionally invalid values."""
    tp=fp=fn=0
    for f in sorted(set(predict)|set(gold)):
        if f in predict and f in gold and abs(predict[f]-gold[f]) <= .02:
            tp+=1
        else:
            fp += int(f in predict)
            fn += int(f in gold)
    return tp,fp,fn


def validate_fixture(records, labels):
    """Validate evaluation contracts before counting any metric.

    Validation checks structural consistency, not whether annotations are true.
    Patient splits come from actual input patient groups; duplicate clusters must
    remain within one patient, encounter and split. All supplied splits are scored.
    """
    if len(records)!=len(labels):
        raise ValueError('Fixture records / annotations length mismatch')
    if not records:
        raise ValueError('Cannot evaluate an empty fixture')
    record_ids = set()
    patient_splits = {}
    cluster_scopes = {}
    for row, gold in zip(records, labels):
        if not isinstance(row, dict) or not isinstance(gold, dict):
            raise ValueError('Fixture rows and annotations must be objects')
        for field in ('record_id', 'patient_group', 'encounter_group'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f'Fixture requires a nonempty string {field}')
        record_id = row['record_id']
        if record_id != gold.get('record_id'):
            raise ValueError('fixture and gold misaligned')
        if record_id in record_ids:
            raise ValueError('Duplicate record_id in evaluation fixture')
        record_ids.add(record_id)
        if not isinstance(row.get('text'), str):
            raise ValueError('Fixture requires string text')
        split = gold.get('split')
        if not isinstance(split, str) or split not in ('train', 'dev', 'test'):
            raise ValueError('Gold split must be train, dev or test')
        patient = row['patient_group']
        if patient in patient_splits and patient_splits[patient] != split:
            raise ValueError('Actual patient group crosses splits')
        patient_splits[patient] = split
        cluster = gold.get('duplicate_cluster')
        if not isinstance(cluster, str) or not cluster.strip():
            raise ValueError('Gold requires a nonempty duplicate_cluster')
        scope = (patient, row['encounter_group'], split)
        if cluster in cluster_scopes and cluster_scopes[cluster] != scope:
            raise ValueError('Duplicate cluster crosses patient, encounter or split')
        cluster_scopes[cluster] = scope
        spans = gold.get('phi_spans')
        if not isinstance(spans, list):
            raise ValueError('Gold phi_spans must be a list')
        positions = []
        for span in spans:
            if not isinstance(span, dict) or span.get('label') not in ('NAME', 'PHONE', 'MRN'):
                raise ValueError('Unsupported or malformed gold PHI label')
            start, end = span.get('start'), span.get('end')
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(row['text']):
                raise ValueError('Gold PHI span is outside text or has invalid offsets')
            positions.append((start, end))
        positions.sort()
        if any(left[1] > right[0] for left, right in zip(positions, positions[1:])):
            raise ValueError('Gold PHI spans overlap or are duplicated')
        labs = gold.get('labs')
        if not isinstance(labs, dict):
            raise ValueError('Gold labs must be an object')
        for field, value in labs.items():
            if field not in ('temp_c', 'glucose_mmol_l', 'hemoglobin_g_l', 'alt_u_l'):
                raise ValueError('Unsupported gold lab field')
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('Gold labs must contain finite numeric values')
    return patient_splits, cluster_scopes


def evaluate(dataset, annotation, *, key='synthetic-only-demo-key-2026'):
    records=list(load_jsonl(dataset))
    labels=list(load_jsonl(annotation))
    patient_splits, cluster_scopes = validate_fixture(records, labels)
    stats = collections.defaultdict(lambda:[0,0,0])
    processed=[]
    predicted_dupes=set()
    gold_dupes=set()
    seen_clusters=set()
    for row,gold in zip(records, labels):
        actual_spans={(s['label'],s['start'],s['end']) for s in gold['phi_spans']}
        inferred_spans={(s.label,s.start,s.end) for s in find_phi(row['text'])}
        for model,pred in [('baseline',baseline_phi(row['text'])),('pipeline',inferred_spans)]:
            s=stats[model+'_phi'];s[0]+=len(pred & actual_spans);s[1]+=len(pred-actual_spans);s[2]+=len(actual_spans-pred)
        for model,pred in [('baseline',baseline_labs(row['text'])),('pipeline',parse_labs(row['text'])[0])]:
            s=stats[model+'_labs']
            a,b,c=compare_labs(pred,gold['labs'])
            s[0]+=a;s[1]+=b;s[2]+=c
        # Only subsequent members of a gold cluster are duplicate records.
        cl=gold['duplicate_cluster']
        if cl in seen_clusters:
            gold_dupes.add(row['record_id'])
        seen_clusters.add(cl)
        processed.append(process_record(row,key))
    deduplicate(processed)
    key_to_cluster = {r['record_key']: gold['duplicate_cluster'] for r, gold in zip(processed, labels)}
    prior_keys = set()
    correct_links = 0
    for row, gold, r in zip(records, labels, processed):
        if r['duplicate_of']:
            predicted_dupes.add(row['record_id'])
            if (r['duplicate_of'] in prior_keys
                    and key_to_cluster.get(r['duplicate_of']) == gold['duplicate_cluster']):
                correct_links += 1
        prior_keys.add(r['record_key'])
    tp=len(predicted_dupes & gold_dupes)
    results={
        'disclaimer':'Metrics use a programmatically generated, templated synthetic fixture; NOT independent clinical data or expert ground truth.',
        'n_records':len(records),
        'n_patient_groups':len(patient_splits),
        'n_duplicate_clusters':len(cluster_scopes),
        'n_duplicates_gold':len(gold_dupes),
        'metrics':{
          'baseline_phi_span_exact':prf(*stats['baseline_phi']),
          'pipeline_phi_span_exact':prf(*stats['pipeline_phi']),
          'baseline_lab_field_exact_with_numeric_tolerance':prf(*stats['baseline_labs']),
          'pipeline_lab_field_exact_with_numeric_tolerance':prf(*stats['pipeline_labs']),
          'pipeline_duplicate_record_detection':prf(tp,len(predicted_dupes-gold_dupes),len(gold_dupes-predicted_dupes)),
        },
        'duplicate_link_evaluation': {
            **prf(correct_links, len(predicted_dupes)-correct_links, len(gold_dupes)-correct_links),
            'definition':'A correct link targets an earlier record in the same gold duplicate cluster; wrong links count as both FP and FN when the source is a gold duplicate.',
        },
        'gold_provenance':'Generator-produced spans/values/clusters; may share structure with operators.',
        'unsupported_scope':'Unseen hospital notes, handwriting/OCR, DICOM images, ICD/SNOMED/LOINC mapping, real PHI recall, clinical safety',
        'split_group_integrity_verified':True,
        'split_integrity_checks':['actual patient_group has one split', 'duplicate_cluster has one patient, encounter and split', 'unique aligned record IDs'],
        'evaluation_scope': {
            'scored_records':'All supplied train/dev/test records; no fitting or held-out model selection occurs here.',
            'records_by_split':dict(sorted(collections.Counter(gold['split'] for gold in labels).items())),
            'candidate_export_split_policy':'SFT candidates independently hash patient_group_key to train/dev/test; those candidate splits are not these fixture labels.',
            'limitation':'Structural split integrity does not establish source independence or prevent development-time test exposure.',
        },
    }
    return results
