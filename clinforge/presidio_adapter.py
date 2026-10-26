"""Optional, local English Presidio baseline. Never installs or downloads models.

This adapter is not used by the production/text-export pipeline. It deliberately
adds no project-specific MRN rules: unsupported MRNs remain benchmark misses.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util

from .operators import PHISpan

ENTITY_MAP = {'PERSON': 'NAME', 'PHONE_NUMBER': 'PHONE',
              'DATE_TIME': 'DATE', 'LOCATION': 'ADDRESS',
              'US_SSN': 'SSN', 'EMAIL_ADDRESS': 'EMAIL'}
DEFAULT_MODEL = 'en_core_web_lg'


class PresidioUnavailable(RuntimeError):
    """Missing or broken optional local dependencies; not an empty prediction."""


def environment_status(model_name=DEFAULT_MODEL):
    versions = {}
    for package in ('presidio-analyzer', 'presidio-anonymizer', 'spacy', model_name.replace('_', '-')):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    required = {'presidio_analyzer': 'presidio-analyzer', 'spacy': 'spacy',
                model_name: model_name.replace('_', '-')}
    missing = []
    for module, package in required.items():
        try:
            installed = versions[package] is not None and importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            installed = False
        if not installed:
            missing.append(package)
    return {'versions': versions, 'missing_required': missing,
            'ready_for_initialization': not missing,
            'model': model_name, 'language': 'en',
            'anonymizer_required_for_detection': False,
            'note': 'Package presence is not proof of successful native imports or inference.'}


class PresidioAdapter:
    def __init__(self, *, model_name=DEFAULT_MODEL, score_threshold=.5):
        if not isinstance(model_name, str) or not model_name.isidentifier():
            raise ValueError('Use an already installed spaCy model package name')
        if not 0 <= score_threshold <= 1:
            raise ValueError('score_threshold must be between zero and one')
        status = environment_status(model_name)
        if status['missing_required']:
            raise PresidioUnavailable('Missing local dependencies: ' + ', '.join(status['missing_required']))
        try:
            import spacy
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import SpacyNlpEngine
            # Load explicitly with spaCy, which raises for absent models rather
            # than using Presidio's default large-model download path.
            loaded = spacy.load(model_name)
            engine = SpacyNlpEngine(models=[{'lang_code': 'en', 'model_name': model_name}])
            engine.nlp = {'en': loaded}
            if not engine.is_loaded():
                raise PresidioUnavailable('Explicit local NLP engine was not loaded')
            self._analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=['en'])
        except Exception as error:
            raise PresidioUnavailable('Local Presidio initialization failed: ' + type(error).__name__) from error
        self.score_threshold = score_threshold
        self.metadata = {**status, 'profile': 'predefined recognizers; no custom MRN patterns',
                         'score_threshold': score_threshold,
                         'entity_mapping': dict(ENTITY_MAP),
                         'limitations': ['English NLP only, including when diagnostic text contains Chinese.',
                                         'No project-specific patient-ID recognizer.',
                                         'Not a validated medical de-identification system.']}

    def analyze(self, text, score_threshold=None):
        """Return every Presidio result with its own score, for threshold sweeps.

        No score is invented: results without a score attribute are rejected
        rather than defaulted, so a silent change of contract cannot pass.
        """
        if not isinstance(text, str):
            raise ValueError('Text must be a string')
        threshold = self.score_threshold if score_threshold is None else score_threshold
        if isinstance(threshold, bool) or not 0 <= threshold <= 1:
            raise ValueError('score_threshold must be within [0,1]')
        results = self._analyzer.analyze(text=text, language='en',
            entities=list(ENTITY_MAP), score_threshold=threshold)
        spans = {}
        for result in results:
            if result.entity_type not in ENTITY_MAP:
                raise ValueError('Unexpected Presidio entity type')
            if (type(result.start) is not int or type(result.end) is not int
                    or not 0 <= result.start < result.end <= len(text)):
                raise ValueError('Invalid Presidio offsets')
            score = getattr(result, 'score', None)
            if score is None:
                raise ValueError('Presidio result without a score')
            key = (result.start, result.end, ENTITY_MAP[result.entity_type])
            if key not in spans or float(score) > spans[key]:
                spans[key] = float(score)
        return [{'start': start, 'end': end, 'label': label, 'score': score}
                for (start, end, label), score in sorted(spans.items())]

    def find(self, text):
        return [PHISpan(span['start'], span['end'], span['label'])
                for span in self.analyze(text)]
