"""Trace named public MIMIC demo artifacts; persist hashes and aggregates only.

By default this only reads existing local files/ZIP members. --verify-official
downloads fixed public PhysioNet demo CSVs into a temporary directory, verifies
official checksums, and replays the existing upstream conversion in memory.
No patient rows, identifiers, complaints or clinical examples are written out.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from clinforge.artifacts import write_json_no_overwrite
from clinforge.mimic_audit import audit_public_structured


OFFICIAL_BASE = 'https://physionet.org/files/mimic-iv-ed-demo/2.2/'
CODE_NAMES = ('run_full_public_data.py', 'run_public_demo.py',
              'src/meddatalab/realworld.py', 'scripts/fetch_public_datasets.py')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def aggregate_structured(content):
    rows = [json.loads(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
    return {'rows': len(rows),
            'unique_subject_ids': len({str(r['subject_id']) for r in rows}),
            'unique_stay_ids': len({str(r['stay_id']) for r in rows}),
            'diagnosis_links': sum(len(r.get('diagnoses', [])) for r in rows),
            'stays_with_diagnoses': sum(bool(r.get('diagnoses', [])) for r in rows)}


def compare_historical(historical, actual, prefix=''):
    """Compare historical numeric claims; never export arbitrary source values."""
    differences = []
    for key, expected in historical.items():
        name = prefix + key
        if isinstance(expected, dict):
            differences.extend(compare_historical(expected, actual.get(key, {}), name + '.'))
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            observed = actual.get(key)
            if expected != observed:
                differences.append({'metric': name, 'historical': expected, 'recomputed': observed})
    return differences


def load_upstream(path):
    spec = importlib.util.spec_from_file_location('clinforge_upstream_public_demo', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay_csv_pair(upstream, triage, diagnoses, expected_bytes):
    # analyze() returns individual records in memory; none are printed or saved.
    summary, rows = upstream.analyze(triage, diagnoses, origin='provenance_replay', max_examples=0)
    serialized = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
    result = {'upstream_counts': {key: summary[key] for key in (
        'n_triage_rows', 'n_unique_patients_in_triage', 'n_unique_stays_in_triage',
        'n_diagnosis_rows', 'n_stays_with_matched_diagnosis')},
        'replayed_derivative_sha256': digest(serialized),
        'exact_lf_serialized_bytes_match_existing_derivative': serialized == expected_bytes,
        'replayed_aggregate': aggregate_structured(serialized)}
    del rows, serialized, summary
    return result


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'ClinDataForge-Provenance-Audit/0.2'})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def verify_official(upstream, existing_bytes, out):
    manifest = fetch(OFFICIAL_BASE + 'SHA256SUMS.txt')
    checksums = {}
    for line in manifest.decode('utf-8').splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})\s+\*?(.+)', line.strip())
        if match:
            checksums[match[2]] = match[1]
    license_content = fetch(OFFICIAL_BASE + 'LICENSE.txt')
    if digest(license_content) != checksums.get('LICENSE.txt'):
        raise ValueError('Official license checksum mismatch')
    # License text and checksum manifest contain no patient records.
    (out / 'official_LICENSE.txt').write_bytes(license_content)
    (out / 'official_SHA256SUMS.txt').write_bytes(manifest)
    artifacts = []
    with tempfile.TemporaryDirectory(prefix='clinforge-public-demo-') as temporary:
        folder = pathlib.Path(temporary)
        for name in ('ed/triage.csv.gz', 'ed/diagnosis.csv.gz'):
            content = fetch(OFFICIAL_BASE + name)
            if digest(content) != checksums.get(name):
                raise ValueError('Official demo CSV checksum mismatch')
            path = folder / pathlib.Path(name).name
            path.write_bytes(content)
            artifacts.append({'url': OFFICIAL_BASE + name, 'sha256': digest(content),
                              'bytes': len(content), 'official_checksum_verified': True})
        replay = replay_csv_pair(upstream, folder / 'triage.csv.gz', folder / 'diagnosis.csv.gz', existing_bytes)
    return {'status': 'verified', 'source_page': 'https://physionet.org/content/mimic-iv-ed-demo/2.2/',
            'manifest_url': OFFICIAL_BASE + 'SHA256SUMS.txt', 'manifest_sha256': digest(manifest),
            'license_url': OFFICIAL_BASE + 'LICENSE.txt', 'license_sha256': digest(license_content),
            'downloaded_raw_files_persisted': False, 'artifacts': artifacts, 'transformation_replay': replay}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-parent', type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parents[2])
    parser.add_argument('--out', required=True, type=pathlib.Path)
    parser.add_argument('--verify-official', action='store_true')
    args = parser.parse_args(argv)
    root = pathlib.Path(__file__).resolve().parents[1]
    workspace = args.workspace_parent.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    local = []
    for path in sorted(workspace.glob('MedDataLab*/reports/*/public_clinical_structured.jsonl')):
        if path.parent.name not in ('full_public', 'public_demo'):
            continue
        content = path.read_bytes()
        local.append({'path_relative_to_workspace': path.relative_to(workspace).as_posix(),
                      'bytes': len(content), 'sha256': digest(content),
                      'aggregate': aggregate_structured(content)})
    archives = []
    for path in sorted(workspace.glob('MedDataLab*.zip')):
        archive_record = {'archive': path.name, 'bytes': path.stat().st_size, 'members': []}
        # Fingerprint the archive to identify the precise historical delivery.
        archive_record['sha256'] = digest(path.read_bytes())
        with zipfile.ZipFile(path) as zipped:
            for member in zipped.infolist():
                if not member.filename.endswith('public_clinical_structured.jsonl'):
                    continue
                if '/reports/full_public/' not in member.filename and '/reports/public_demo/' not in member.filename:
                    continue
                content = zipped.read(member)
                archive_record['members'].append({'path': member.filename,
                    'bytes': len(content), 'sha256': digest(content),
                    'aggregate': aggregate_structured(content)})
        archives.append(archive_record)
    project = workspace / 'MedDataLab'
    full = project / 'reports/full_public/public_clinical_structured.jsonl'
    preview = project / 'reports/public_demo/public_clinical_structured.jsonl'
    full_bytes, preview_bytes = full.read_bytes(), preview.read_bytes()
    full_audit, preview_audit = audit_public_structured(full), audit_public_structured(preview)
    historical = json.loads((root / 'reports/public_demo_aggregate.json').read_text(encoding='utf-8'))
    mismatches = compare_historical(historical, full_audit)
    ignore_lines = (project / '.gitignore').read_text(encoding='utf-8').splitlines()
    relevant_ignores = [line for line in ignore_lines if line.strip() in ('reports/full_public/', 'data/external/')]
    code = [{'path_relative_to_workspace': (project / name).relative_to(workspace).as_posix(),
             'sha256': digest((project / name).read_bytes())} for name in CODE_NAMES]
    upstream = load_upstream(project / 'src/meddatalab/realworld.py')
    preview_replay = replay_csv_pair(upstream,
        project / 'data/public_preview/mimic_iv_ed_v2.2_triage_verified_preview.csv',
        project / 'data/public_preview/mimic_iv_ed_v2.2_diagnosis_verified_preview.csv', preview_bytes)
    history = subprocess.run(['git', '-C', str(workspace), 'rev-list', '--count', 'HEAD'],
                             capture_output=True, text=True)
    report = {'scope': 'Existing public deidentified MIMIC-IV-ED Demo derivative provenance only; no PHI benchmark.',
        'source_paths_resolved': True, 'local_artifacts': local, 'archives': archives,
        'historical_report': {'path': 'reports/public_demo_aggregate.json',
            'sha256': digest((root / 'reports/public_demo_aggregate.json').read_bytes()),
            'numeric_metric_differences_from_recovered_full_public': mismatches,
            'all_historical_numeric_metrics_reproduced': not mismatches},
        'upstream_code_fingerprints': code,
        'preview_csv_replay': preview_replay,
        'discovery_gap': {'gitignore_rules': relevant_ignores,
            'cause': 'Phase-one default rg --files inventory honored upstream .gitignore and omitted reports/full_public; public_demo preview and full_public share a basename.'},
        'parent_git_history': {'available': history.returncode == 0,
            'commit_count': int(history.stdout.strip()) if history.returncode == 0 else 0,
            'limit': 'Parent workspace has no commits; ZIP bytes and code fingerprints identify delivery snapshots.'},
        'conclusion': '222/64/545 belongs to full_public and 85/40/21 belongs to the partial preview. Both named artifacts now located; old report can be cited only with recovered full_public fingerprint and scope.',
        'no_patient_level_data_exported': True,
        'limitations': ['Historical reports and original records were not overwritten.',
            'Source flags and clinical text are not PHI annotation or clinical quality gold.',
            'Without --verify-official, no claim is made that archived derivatives match newly downloaded official raw CSVs.']}
    if args.verify_official:
        try:
            report['official_source_verification'] = verify_official(upstream, full_bytes, out)
        except (OSError, urllib.error.URLError, ValueError) as error:
            report['official_source_verification'] = {'status': 'failed', 'error_type': type(error).__name__,
                'raw_records_exported': False}
    write_json_no_overwrite(out / 'recovered_full_public_aggregate.json', full_audit)
    write_json_no_overwrite(out / 'preview_aggregate.json', preview_audit)
    write_json_no_overwrite(out / 'provenance_trace.json', report)
    print(json.dumps({'local_artifact_count': len(local), 'archive_count': len(archives),
        'full_aggregate': aggregate_structured(full_bytes), 'preview_aggregate': aggregate_structured(preview_bytes),
        'historical_numeric_metrics_reproduced': not mismatches,
        'official_source_status': report.get('official_source_verification', {}).get('status', 'not_requested')}, indent=2))


if __name__ == '__main__':
    main()
