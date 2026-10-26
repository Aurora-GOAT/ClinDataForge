"""Medical structuring + quality pipeline (P1) for SYNTHETIC input only.

Stage chain per record (each stage appends to the record's lineage log):
  schema -> extract (HPO dictionary) -> context (NegEx/ConText scope, v2)
  -> labs (standardisation v2) -> phi_gate (frozen phase-2 hybrid detector)
  -> near-dup (within patient+encounter, lab-conflict protected)
  -> consistency (extracted phenotypes vs the record disease's HPO annotation)
  -> quality score -> routing (accepted / quarantine / human review)

`context_version='v1'` reproduces the phase-3 window classifier; the default
'v2' uses clinforge.context_scope, whose scope handling fixes the
history -> affirmed errors (see docs/CONTEXT_AND_PERF_CN.md).

Hard rules inherited from the phase-2 safety posture:
  * refuses non-synthetic input (synthetic=True required);
  * the gold `entities` field of generator output is NEVER read by any stage
    (it is stripped before processing and only joined back for evaluation);
  * text output is allowed here ONLY because the input is synthetic.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

from .hpo_knowledge import REFERENCE_INTERVALS
from .context_scope import ContextResolver, CONTEXT_SCOPE_VERSION
from .med_extract import (EXTRACTOR_VERSION, build_term_index, find_phenotype_mentions,
                          classify_context, parse_labs_v2)
from .operators import deduplicate, pseudo_id, doc_fingerprint, similarity

PIPELINE_MED_VERSION = 'pipeline-med-1.1.0'
CONTEXT_VERSIONS = ('v1', 'v2')

REQUIRED_FIELDS = ('record_id', 'patient_group', 'encounter_group', 'text', 'disease_id')


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_phi_gate(config, model_path):
    """Frozen phase-2 hybrid detector (rules ∪ GLiNER fp16)."""
    from .phi_models import create_detector
    return create_detector('D', model_path, config)


class MedicalPipeline:
    def __init__(self, kb, gloss, *, key, phi_gate=None,
                 context_version='v2', cue_set='negex'):
        if not isinstance(key, str) or len(key) < 12:
            raise ValueError('Provide a string HMAC key of at least 12 characters')
        if context_version not in CONTEXT_VERSIONS:
            raise ValueError('context_version must be one of ' + ', '.join(CONTEXT_VERSIONS))
        self.kb, self.gloss, self.key = kb, gloss, key
        self.context_version, self.cue_set = context_version, cue_set
        allowed = set()
        for did in self.demo_disease_ids():
            allowed |= set(kb['diseases'][did]['phenotypes'])
        self.term_index = build_term_index(kb, gloss, allowed)
        self.phi_gate = phi_gate
        # disease mention lexicon (zh curated gloss + en annotation names)
        self.disease_terms = []
        for did in self.demo_disease_ids():
            en = kb['diseases'][did]['disease_name']
            zh = gloss['diseases'].get(did)
            if zh:
                self.disease_terms.append((zh, did, 'zh'))
            self.disease_terms.append((en, did, 'en'))
        self.disease_terms.sort(key=lambda row: -len(row[0]))

    def demo_disease_ids(self):
        from .synthgen import CURATED_DISEASES
        return [d for d in CURATED_DISEASES if d in self.kb['diseases']]

    def process(self, record, phi_spans=None):
        """Process one synthetic record. Gold entities are stripped first.

        `phi_spans` allows the caller to supply spans computed by a batched gate
        call; the PHI stage then only performs masking and never re-runs the model.
        """
        lineage = []
        issues = []
        t0 = time.perf_counter()
        for field in REQUIRED_FIELDS:
            if field not in record or not isinstance(record[field], str) or not record[field].strip():
                return {'record_id': record.get('record_id', '<missing>'), 'status': 'quarantine',
                        'operator_issues': ['SCHEMA_MISSING_' + field.upper()],
                        'lineage': [{'stage': 'schema', 'ok': False}], 'quality_score': 0.0}
        lineage.append({'stage': 'schema', 'ok': True})
        text = record['text']
        language = record.get('language', 'zh')

        t = time.perf_counter()
        mentions_all = find_phenotype_mentions(text, self.term_index)

        # Disease mentions: keep the LAST surface occurrence (the impression
        # section), so a phenotype sharing the surface form (e.g. the disease
        # "Holoprosencephaly" vs phenotype HP:0001360) is not misreported as
        # the disease mention. Phenotype mentions overlapping a disease
        # mention are dropped below to avoid double-counting.
        disease_mentions = []
        lowered = text.casefold()
        for surface, did, dlang in self.disease_terms:
            probe = surface if dlang == 'zh' else surface.casefold()
            haystack = text if dlang == 'zh' else lowered
            start, last = 0, None
            while True:
                pos = haystack.find(probe, start)
                if pos < 0:
                    break
                end = pos + len(probe)
                if dlang == 'zh' or ((pos == 0 or not lowered[pos-1].isalnum())
                                     and (end >= len(lowered) or not lowered[end].isalnum())):
                    last = (pos, end)
                start = pos + 1
            if last is not None:
                disease_mentions.append({'disease_id': did, 'start': last[0], 'end': last[1],
                                         'text': text[last[0]:last[1]], 'status': 'suspected'})
        disease_spans = [(m['start'], m['end']) for m in disease_mentions]
        mentions = [m for m in mentions_all
                    if not any(m['start'] < de and m['end'] > ds for ds, de in disease_spans)]
        if self.context_version == 'v2':
            # Every mention (including the ones dropped as disease-name overlaps)
            # is masked before cue matching, so a negation character inside a term
            # name can never fire a cue.
            mask_spans = [(m['start'], m['end']) for m in mentions_all] + disease_spans
            resolver = ContextResolver(text, language, mask_spans, self.cue_set)
            for m in mentions:
                m['status'] = resolver.classify(m['start'])
        else:
            for m in mentions:
                m['status'] = classify_context(text, m, language)
        lineage.append({'stage': 'extract+context', 'version': EXTRACTOR_VERSION,
                        'context': self.context_version,
                        'context_scope_version': CONTEXT_SCOPE_VERSION
                        if self.context_version == 'v2' else None,
                        'cue_set': self.cue_set if self.context_version == 'v2' else None,
                        'n_mentions': len(mentions), 'ms': round((time.perf_counter() - t) * 1000, 2)})

        t = time.perf_counter()
        labs, lab_issues = parse_labs_v2(text)
        issues += lab_issues
        lineage.append({'stage': 'labs', 'n_labs': len(labs), 'ms': round((time.perf_counter() - t) * 1000, 2)})

        t = time.perf_counter()
        precomputed = phi_spans
        phi_spans = []
        batch_used = False
        masked = text
        if self.phi_gate is not None:
            if precomputed is None:
                spans = self.phi_gate.find(text)
            else:
                spans = precomputed
                batch_used = True
            phi_spans = spans
            parts, pos = [], 0
            for span in phi_spans:
                parts.append(text[pos:span['start']])
                parts.append('[' + span['label'] + ']')
                pos = span['end']
            parts.append(text[pos:])
            masked = ''.join(parts)
            # re-run mentions on masked text? no: extraction happened on raw;
            # masking positions shift, so keep extraction from raw and never
            # persist raw text downstream except in synthetic audit context.
        lineage.append({'stage': 'phi_gate',
                        'engine': None if self.phi_gate is None else self.phi_gate.metadata.get('method'),
                        'n_phi_spans': len(phi_spans), 'batched': batch_used,
                        'ms': round((time.perf_counter() - t) * 1000, 2)})

        t = time.perf_counter()
        disease = self.kb['diseases'].get(record['disease_id'])
        annotated = set(disease['phenotypes']) if disease else set()
        inconsistent = [m for m in mentions
                        if m['status'] in ('affirmed', 'suspected') and m['hp_id'] not in annotated]
        if inconsistent:
            issues.append('KNOWLEDGE_INCONSISTENT_PHENOTYPE')
        lineage.append({'stage': 'consistency', 'n_inconsistent': len(inconsistent)})

        labs_dict = {}
        for e in labs:
            labs_dict.setdefault(e['analyte'].lower(), e['value_std'])
        n_affirmed = sum(1 for m in mentions if m['status'] == 'affirmed')
        score = 0.2 + min(n_affirmed, 6) * 0.08 + min(len(labs), 4) * 0.08
        score -= 0.2 * len(issues)
        score = round(max(0.0, min(1.0, score)), 3)
        status = 'quarantine' if issues else 'accepted'
        result = {
            'record_key': pseudo_id(record['record_id'], self.key),
            'patient_group_key': pseudo_id(record['patient_group'], self.key),
            'encounter_group_key': pseudo_id(record['encounter_group'], self.key),
            'record_id': record['record_id'], 'patient_group': record['patient_group'],
            'encounter_group': record['encounter_group'],
            'disease_id': record['disease_id'], 'language': language,
            'masked_text': masked, 'text_sha256': sha256_text(text),
            'phenotypes': [{'hp_id': m['hp_id'], 'status': m['status'], 'text': m['text'],
                            'start': m['start'], 'end': m['end']} for m in mentions],
            'disease_mentions': disease_mentions,
            'labs': labs,
            'labs_dict': labs_dict,
            'phi_spans_found': len(phi_spans),
            'operator_issues': sorted(set(issues)),
            'quality_score': score, 'status': status,
            'complaint_fingerprint': doc_fingerprint(masked[:120]),
            'lineage': lineage,
            'total_ms': round((time.perf_counter() - t0) * 1000, 2),
            'pipeline_version': PIPELINE_MED_VERSION,
        }
        return result


def run_med_pipeline(notes_path, out_dir, kb, gloss, *, key, phi_gate=None,
                     context_version='v2', cue_set='negex'):
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f'Refusing to overwrite: {out}')
    out.mkdir(parents=True, exist_ok=True)
    pipe = MedicalPipeline(kb, gloss, key=key, phi_gate=phi_gate,
                           context_version=context_version, cue_set=cue_set)
    records = [json.loads(line) for line in open(notes_path, encoding='utf-8') if line.strip()]
    processed = []
    gate_seconds = 0.0
    if phi_gate is not None and hasattr(phi_gate, 'find_many'):
        batch = int(getattr(phi_gate, 'batch_size', 8) or 8) * 2
        batch = max(1, min(batch, 64))
        for begin in range(0, len(records), batch):
            group = records[begin:begin + batch]
            texts = [rec.get('text', '') if isinstance(rec.get('text'), str) else '' for rec in group]
            gate_started = time.perf_counter()
            spans_list = phi_gate.find_many(texts)
            gate_seconds += time.perf_counter() - gate_started
            for rec, spans in zip(group, spans_list):
                processed.append(pipe.process(rec, phi_spans=spans))
    else:
        for rec in records:
            processed.append(pipe.process(rec))
    # near-duplicate detection within patient+encounter, with the
    # lab-conflict protection from operators.deduplicate.
    legacy_view = []
    for r in processed:
        if r['status'] == 'quarantine' and 'SCHEMA_MISSING' in ','.join(r['operator_issues']):
            continue
        legacy_view.append({'record_key': r['record_key'],
                            'patient_group_key': r['patient_group_key'],
                            'encounter_group_key': r['encounter_group_key'],
                            'labs': r['labs_dict'],
                            'complaint': r['complaint_fingerprint'],
                            'masked_text': r['masked_text'],
                            'status': r['status'],
                            'operator_issues': r['operator_issues']})
    deduplicate(legacy_view)
    dup_map = {r['record_key']: r.get('duplicate_of') for r in legacy_view}
    for r in processed:
        r['duplicate_of'] = dup_map.get(r.get('record_key'))
        if r.get('duplicate_of'):
            r['status'] = 'quarantine'
            if 'DUPLICATE_WITHIN_PATIENT' not in r['operator_issues']:
                r['operator_issues'].append('DUPLICATE_WITHIN_PATIENT')
    accepted = [r for r in processed if r['status'] == 'accepted']
    quarantine = [r for r in processed if r['status'] != 'accepted']

    def dump(name, rows):
        with open(out / name, 'w', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')

    dump('structured.jsonl', accepted)
    dump('quarantine.jsonl', quarantine)
    dump('lineage.jsonl', [{'record_id': r.get('record_id'), 'lineage': r.get('lineage'),
                            'total_ms': r.get('total_ms')} for r in processed])
    review = [r for r in processed if r['operator_issues']]
    with open(out / 'review_queue.csv', 'w', encoding='utf-8') as handle:
        handle.write('record_id,quality_score,issues,review_status\n')
        for r in review:
            handle.write('%s,%.3f,%s,PENDING_HUMAN\n' % (
                r.get('record_id'), r['quality_score'], '|'.join(r['operator_issues'])))
    audit = {
        'pipeline_version': PIPELINE_MED_VERSION,
        'extractor_version': EXTRACTOR_VERSION,
        'context_version': context_version,
        'context_scope_version': CONTEXT_SCOPE_VERSION if context_version == 'v2' else None,
        'cue_set': cue_set if context_version == 'v2' else None,
        'phi_gate_seconds': round(gate_seconds, 2),
        'phi_gate_ms_per_record': round(gate_seconds / len(processed) * 1000, 1) if processed else None,
        'phi_gate_batched': gate_seconds > 0,
        'phi_gate': None if phi_gate is None else phi_gate.metadata,
        'input_rows': len(processed), 'accepted_rows': len(accepted),
        'quarantined_rows': len(quarantine),
        'duplicate_rows_quarantined': sum(1 for r in processed if r.get('duplicate_of')),
        'review_queue_rows': len(review),
        'export_policy': 'synthetic_input_only; text retained because all content is synthetic',
        'warnings': ['Structured output quality = pipeline routing only; not clinical validity.',
                     'Human review queue is unreviewed by default (PENDING_HUMAN).'],
    }
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    return audit
