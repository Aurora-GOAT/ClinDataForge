"""HPO knowledge base loading, verification and rare-disease selection.

Pure-stdlib parsers for the official Human Phenotype Ontology release files.
The vocabulary content is used AS DOWNLOADED (HPO license condition: the
ontology content and its logical relationships must not be altered); this
module only reads it and builds a read-only snapshot.

License (https://hpo.jax.org/app/license, verified 2026-10-26):
  freely available; must acknowledge/cite the HPO Consortium; must include
  version numbers when files are displayed; must not alter content.
  This module satisfies all three: files are unmodified, versions and SHA256
  are recorded in the snapshot manifest and every generated artefact.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

HPO_VERSION_NOTE = {
    'ontology': 'Human Phenotype Ontology',
    'license': 'https://hpo.jax.org/app/license (free to use; citation + version display required; content unmodified)',
    'credit': 'This product uses the Human Phenotype Ontology (version recorded in manifest). '
              'Find out more at http://www.human-phenotype-ontology.org',
}

# Frequency subontology midpoints, per HPO definitions (used as inclusion
# probabilities when sampling phenotypes for a synthetic case).
FREQUENCY_TERMS = {
    'HP:0040280': 1.00,   # Obligate (100%)
    'HP:0040281': 0.895,  # Very frequent (99-80%)
    'HP:0040282': 0.545,  # Frequent (79-30%)
    'HP:0040283': 0.170,  # Occasional (29-5%)
    'HP:0040284': 0.025,  # Very rare (4-1%)
    'HP:0040285': 0.00,   # Excluded (0%)
}
DEFAULT_FREQUENCY = 0.20  # annotation present but no frequency data

# Approximate representative age windows (years) for onset terms, used ONLY to
# sample a plausible patient age for a synthetic case narrative.
ONSET_AGE_RANGE = {
    'HP:0003577': (0.0, 0.1),    # Congenital onset
    'HP:0003623': (0.0, 0.08),   # Neonatal onset
    'HP:0003593': (0.08, 1.0),   # Infantile onset
    'HP:0011463': (1.0, 5.0),    # Childhood onset
    'HP:0003621': (5.0, 15.0),   # Juvenile onset
    'HP:0011462': (16.0, 40.0),  # Young adult onset
    'HP:0003596': (40.0, 60.0),  # Middle age onset
    'HP:0003584': (60.0, 80.0),  # Late onset
    'HP:0003581': (16.0, 60.0),  # Adult onset
}
DEFAULT_AGE_RANGE = (0.0, 60.0)

# Curated lab-linked phenotype subset. Each entry maps an HPO phenotype whose
# abnormality is directly expressible as a numeric laboratory result to a
# demonstration analyte. Reference intervals are common adult demonstration
# values (actual intervals are laboratory-specific; documented in data card).
LAB_PHENOTYPES = {
    'HP:0002910': {'analyte': 'ALT',  'direction': 'high'},  # Elevated hepatic transaminase
    'HP:0003074': {'analyte': 'GLUCOSE', 'direction': 'high'},  # Hyperglycemia
    'HP:0001943': {'analyte': 'GLUCOSE', 'direction': 'low'},   # Hypoglycemia
    'HP:0001903': {'analyte': 'HGB', 'direction': 'low'},       # Anemia
}
# Demonstration reference intervals (adult, commonly used values; the exact
# interval is laboratory-specific and these are NOT presented as a standard).
REFERENCE_INTERVALS = {
    'ALT': {'unit': 'U/L', 'lo': 7.0, 'hi': 40.0},
    'AST': {'unit': 'U/L', 'lo': 8.0, 'hi': 40.0},
    'GLUCOSE': {'unit': 'mmol/L', 'lo': 3.9, 'hi': 6.1, 'alt_unit': 'mg/dL', 'factor_mgdl_to_mmoll': 18.016},
    'HGB': {'unit': 'g/L', 'lo': 115.0, 'hi': 175.0, 'alt_unit': 'g/dL', 'factor_gdl_to_gl': 10.0},
}

_SYNONYM_RE = re.compile(r'^synonym: "(.+)"\s+(\w+)')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_obo(path):
    """Parse hp.obo -> {hp_id: {name, synonyms, alt_ids, is_obsolete}}.

    Only HP: terms are kept. Obsolete terms are flagged and excluded from
    selection but retained in the snapshot for auditability.
    """
    version, terms, current = None, {}, None
    def flush():
        if current is not None and 'id' in current and current['id'].startswith('HP:'):
            terms[current['id']] = {
                'name': current.get('name'),
                'synonyms': sorted(set(current.get('synonyms', []))),
                'alt_ids': sorted(set(current.get('alt_ids', []))),
                'is_obsolete': current.get('is_obsolete', False),
            }
    with open(path, encoding='utf-8') as handle:
        for raw in handle:
            line = raw.rstrip('\n')
            if line.startswith('data-version:'):
                version = line.split(':', 1)[1].strip()
            elif line == '[Term]':
                flush()
                current = {'synonyms': [], 'alt_ids': [], 'is_obsolete': False}
            elif line.startswith('['):
                flush()
                current = None
            elif current is not None:
                if line.startswith('id: '):
                    current['id'] = line[4:].strip()
                elif line.startswith('name: '):
                    current['name'] = line[6:].strip()
                elif line.startswith('alt_id: '):
                    current['alt_ids'].append(line[8:].strip().split(' ')[0])
                elif line.startswith('is_obsolete: true'):
                    current['is_obsolete'] = True
                else:
                    match = _SYNONYM_RE.match(line)
                    if match and match.group(2) != 'OBSOLETE':
                        current['synonyms'].append(match.group(1))
    flush()
    return version, terms


def parse_frequency(raw):
    """HPOA frequency field -> inclusion probability in [0, 1] or None."""
    value = (raw or '').strip()
    if not value:
        return DEFAULT_FREQUENCY
    if value in FREQUENCY_TERMS:
        return FREQUENCY_TERMS[value]
    if '/' in value:
        num, _, den = value.partition('/')
        try:
            return min(1.0, max(0.0, float(num) / float(den)))
        except (ValueError, ZeroDivisionError):
            return DEFAULT_FREQUENCY
    if value.endswith('%'):
        try:
            return min(1.0, max(0.0, float(value[:-1]) / 100.0))
        except ValueError:
            return DEFAULT_FREQUENCY
    return DEFAULT_FREQUENCY


def parse_hpoa(path, terms):
    """Parse phenotype.hpoa -> {disease_id: record}.

    Aspect 'P' rows only (phenotype annotations; inheritance/frequency
    metadata rows are ignored). qualifier=='NOT' rows are kept separately as
    explicitly-absent annotations. Phenotypes that are obsolete or missing
    from the ontology snapshot are dropped and counted.
    """
    version, diseases, dropped = None, {}, 0
    with open(path, encoding='utf-8') as handle:
        for raw in handle:
            if raw.startswith('#'):
                if raw.startswith('#version:'):
                    version = raw.split(':', 1)[1].strip()
                continue
            fields = raw.rstrip('\n').split('\t')
            if len(fields) < 12:
                continue
            (db_id, name, qualifier, hp_id, reference, evidence,
             onset, frequency, _sex, _modifier, aspect, _bioc) = fields[:12]
            if aspect != 'P':
                continue
            term = terms.get(hp_id)
            if term is None or term['is_obsolete']:
                dropped += 1
                continue
            record = diseases.setdefault(db_id, {
                'disease_id': db_id, 'disease_name': name,
                'source': db_id.split(':', 1)[0],
                'phenotypes': {}, 'absent_phenotypes': {}, 'onsets': [],
            })
            entry = {
                'hp_id': hp_id, 'name': term['name'],
                'frequency_raw': frequency, 'frequency': parse_frequency(frequency),
                'evidence': evidence, 'reference': reference,
            }
            if qualifier == 'NOT':
                record['absent_phenotypes'][hp_id] = entry
            else:
                record['phenotypes'][hp_id] = entry
                if onset and onset in ONSET_AGE_RANGE and onset not in record['onsets']:
                    record['onsets'].append(onset)
    return version, diseases, dropped


def build_knowledge_base(obo_path, hpoa_path, out_path):
    obo_path, hpoa_path = Path(obo_path), Path(hpoa_path)
    obo_version, terms = parse_obo(obo_path)
    hpoa_version, diseases, dropped = parse_hpoa(hpoa_path, terms)
    snapshot = {
        'provenance': {
            'ontology_file': {'name': 'hp.obo', 'data_version': obo_version,
                              'sha256': sha256_file(obo_path),
                              'url': 'https://purl.obolibrary.org/obo/hp.obo'},
            'annotation_file': {'name': 'phenotype.hpoa', 'version': hpoa_version,
                                'sha256': sha256_file(hpoa_path),
                                'url': 'https://purl.obolibrary.org/obo/hp/hpoa/phenotype.hpoa'},
            **HPO_VERSION_NOTE,
        },
        'n_terms': len(terms),
        'n_diseases': len(diseases),
        'dropped_obsolete_or_unknown_annotations': dropped,
        'terms': terms,
        'diseases': diseases,
    }
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError(f'Refusing to overwrite knowledge snapshot: {out_path}')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
    return snapshot


def load_knowledge_base(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def select_rare_diseases(kb, n_diseases, seed, min_phenotypes=8):
    """Deterministic rare-disease selection for the synthesis demo.

    Ranking favours (a) diseases whose annotation includes at least one
    lab-linked phenotype (so the downstream lab-standardisation demo has
    material) and (b) richer annotation sets; ties broken by disease id.
    A seeded random tail adds diversity beyond the top of the ranking.
    """
    import random
    candidates = []
    for disease in kb['diseases'].values():
        phenotypes = list(disease['phenotypes'].values())
        if len(phenotypes) < min_phenotypes:
            continue
        n_lab = sum(1 for p in phenotypes if p['hp_id'] in LAB_PHENOTYPES)
        candidates.append((disease['disease_id'], n_lab, len(phenotypes)))
    candidates.sort(key=lambda row: (-row[1], -row[2], row[0]))
    head = [row[0] for row in candidates[:max(1, n_diseases - 4)]]
    tail_pool = [row[0] for row in candidates[max(1, n_diseases - 4):max(1, n_diseases - 4) + 400]]
    rng = random.Random(seed)
    tail = sorted(rng.sample(tail_pool, min(4, len(tail_pool)))) if tail_pool else []
    chosen = head + tail
    return sorted(chosen[:n_diseases])
