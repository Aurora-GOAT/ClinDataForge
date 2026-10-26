"""Reproduce delivery defects in a temporary Git snapshot, using synthetic canaries."""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROBES = r'''
import json, pathlib, tempfile
from clinforge.pipeline import run_pipeline
from clinforge.operators import process_record, parse_labs, deduplicate
from clinforge.evaluate import evaluate
from clinforge.synthetic import save_dataset
from clinforge.mimic_audit import audit_public_structured
key='synthetic-only-demo-key-2026'
base=pathlib.Path('probe_outputs');base.mkdir()
row={'record_id':'SYN-PROBE-1','patient_group':'SYN-P','encounter_group':'SYN-E',
     'text':'Name=Synth Alpha; Contact=138.0000.1234; ChartNo=SYNTEST-42; 主诉：头痛；体温：37℃',
     'source_type':{'untrusted':'synthetic-marker@example.invalid'}}
inp=base/'synthetic-marker-input.jsonl'
inp.write_text(json.dumps(row,ensure_ascii=False)+'\n',encoding='utf-8')
audit=run_pipeline(inp,base/'leak',key,synthetic=True)
export=' '.join(p.read_text(encoding='utf-8') for p in (base/'leak').glob('*.jsonl'))
out={'unknown_phi_accepted':audit['accepted_rows']==1,
     'unknown_phi_persisted':'Synth Alpha' in export,
     'untrusted_source_type_persisted':'synthetic-marker@example.invalid' in export,
     'raw_input_basename_persisted':inp.name in (base/'leak/provenance.json').read_text(encoding='utf-8')}
short=run_pipeline(inp,base/'short-key','short',synthetic=True)
out['bad_key_reported_successful_zero_processed']=short['processed_rows']==0
dup=base/'duplicate.jsonl';dup.write_text((json.dumps(row,ensure_ascii=False)+'\n')*2,encoding='utf-8')
try:run_pipeline(dup,base/'partial',key,synthetic=True)
except Exception as e:out['duplicate_id_failure_type']=type(e).__name__
out['duplicate_failure_left_text_artifacts']=(base/'partial/accepted.jsonl').exists()
out['false_lab_alias_count']=len(parse_labs('SALT=42U/L; nonGLU=5mmol/L; notT=37℃; noHb=120g/L')[0])
a=dict(row,text='姓名：张若安；电话：13800001111；主诉：头痛；体温：37℃；血糖：5.0mmol/L')
b=dict(a,record_id='SYN-PROBE-2',text=a['text'].replace('5.0','25.0'))
processed=deduplicate([process_record(r,key) for r in [a,b]])
out['changed_clinical_value_falsely_deduplicated']=bool(processed[1]['duplicate_of'])
fixture=base/'fixture';save_dataset(fixture,n=20)
rows=[json.loads(s) for s in (fixture/'synthetic_notes.jsonl').read_text(encoding='utf-8').splitlines()]
rows[3]['patient_group']=rows[0]['patient_group']
(fixture/'synthetic_notes.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
out['patient_split_leak_falsely_verified']=evaluate(fixture/'synthetic_notes.jsonl',fixture/'gold_annotations.jsonl')['split_group_integrity_verified']
rec={'subject_id':'SYN-P','stay_id':'SYN-E','measurements':{'synthetic-field@example.invalid':{'value':1}},
     'diagnoses':[{'system':'synthetic-system@example.invalid','seq_num':1}],
     'flags':[{'issue':'synthetic-flag@example.invalid'}],
     'chiefcomplaint_search_tags_not_diagnoses':['synthetic-tag@example.invalid']}
public=base/'aggregate-canary.jsonl';public.write_text(json.dumps(rec)+'\n',encoding='utf-8')
out['aggregate_dynamic_categories_persisted']='@example.invalid' in json.dumps(audit_public_structured(public))
print(json.dumps(out,indent=2))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='delivery-v0.1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError(out)
    root = Path(__file__).resolve().parents[1]
    archive = subprocess.run(['git', 'archive', '--format=zip', args.revision], cwd=root,
                             capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(prefix='clinforge-legacy-') as folder:
        temporary = Path(folder).resolve()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            for member in zipped.infolist():
                if not (temporary / member.filename).resolve().is_relative_to(temporary):
                    raise ValueError('Unsafe archive member')
            zipped.extractall(temporary)
        run = subprocess.run([sys.executable, '-c', PROBES], cwd=temporary,
                             capture_output=True, text=True, encoding='utf-8', check=True)
        result = json.loads(run.stdout)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump({'revision': args.revision, 'probe_scope': 'Local synthetic adversarial diagnostics, not an independent PHI benchmark.',
                   'observations': result}, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
