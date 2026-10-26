"""Real local GLiNER PII ONNX inference, without torch or remote inference.

Word-mask/span preparation follows GLiNER 0.2.13. Han characters are separated
to allow within-sentence Chinese boundaries; English follows its original regex.
The quantized checkpoint is a public conversion of the pretrained PII model.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from .operators import find_phi
from .phi_rules import RULE_REVISION, find_context_phi, union_spans


MODEL_REPO = 'onnx-community/gliner_multi_pii-v1'
MODEL_REVISION = '2e0397a7e8a250d76c37122232b3cbde42c8d629'
UPSTREAM_REPO = 'urchade/gliner_multi_pii-v1'
UPSTREAM_REVISION = '1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d'
# The int8 dynamic conversion shipped as onnx/model_quantized.onnx was measured
# to produce collapsed, non-discriminative representations on this machine
# (max span probability 0.202 on an unambiguous probe; prompt/word
# representations mutually indistinguishable). The fp16 conversion is used
# instead and is verified by hash before every run.
#
# PERFORMANCE NOTE (phase 4): fp16 on this CPU has no fast GEMM kernel, so
# onnxruntime inserts Cast nodes around every fp16 operator; profiling showed
# Cast alone taking 24.5% of runtime and MatMul taking 49.4% at ~1.8 GFLOPS.
# The official fp32 conversion (`onnx/model.onnx` of the same repo revision) is
# therefore the default for the pipeline, and the fp16 weights stay available
# so the phase-2 experiment remains byte-reproducible.
WEIGHTS_RELPATH = 'onnx_fp16/model_fp16.onnx'
WEIGHT_SHA256 = 'e756837e13d16ef832f6cd9fca473c2c3dd1eb232cab13e6443d958d608e797b'
WEIGHTS_FP32_RELPATH = 'onnx_fp32/model.onnx'
# sha256 of the official ONNX conversion, cross-checked against the Hugging Face
# LFS oid for the same revision (onnx/model.onnx, size 1157129714).
WEIGHTS_FP32_SHA256 = '7704865e414f24591da6aee08716a25677855bc8a84af81396d90e40df1e68d2'
QUANTIZED_WEIGHT_SHA256 = '3efb3b91aef91ae11cd781126133063a33a2ffd7787ec73057bbd57a9781a7ab'
PROMPTS = (('person', 'NAME'), ('phone number', 'PHONE'),
           ('medical record number', 'PATIENT_ID'), ('date', 'DATE'), ('address', 'ADDRESS'),
           ('location', 'ADDRESS'), ('social security number', 'SSN'),
           ('email address', 'EMAIL'), ('insurance member number', 'INSURANCE_ID'))
FRONTEND_REVISION = 'numpy-gliner-0.2.13-han-char-fp16-v1'
SPLITTER = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]|[^\W\u3400-\u4dbf\u4e00-\u9fff]+(?:[-_][^\W\u3400-\u4dbf\u4e00-\u9fff]+)*|\S', re.UNICODE)


def split_words(text):
    return [(m.group(), m.start(), m.end()) for m in SPLITTER.finditer(text)]


def validate_config(config):
    threshold = config.get('threshold', .35)
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not 0 < threshold < 1:
        raise ValueError('Model threshold must be between zero and one')
    threads = config.get('threads', 2)
    if type(threads) is not int or threads < 1 or threads > 8:
        raise ValueError('CPU threads must be an integer in [1,8]')
    return float(threshold), threads


class GLiNEROnnxDetector:
    def __init__(self, model_path, config):
        self.threshold, threads = validate_config(config)
        # Defaults preserve the phase-2 frozen configuration exactly: fp16 and
        # one document at a time. The fast configuration opts in explicitly.
        self.dtype = config.get('dtype', 'fp16')
        if self.dtype not in ('fp16', 'fp32'):
            raise ValueError("dtype must be 'fp16' or 'fp32'")
        self.batch_size = int(config.get('batch_size', 1))
        if not 1 <= self.batch_size <= 32:
            raise ValueError('batch_size must be in [1,32]')
        # Sorting chunks by length before batching removes most padding waste;
        # without it, batching is measurably SLOWER than one document at a time
        # on this machine (see docs/CONTEXT_AND_PERF_CN.md).
        self.batch_sort = bool(config.get('batch_sort', True))
        path = Path(model_path)
        if self.dtype == 'fp32':
            weights = path / WEIGHTS_FP32_RELPATH
            expected = WEIGHTS_FP32_SHA256
        else:
            weights = path / WEIGHTS_RELPATH
            expected = WEIGHT_SHA256
        if not weights.exists():
            raise FileNotFoundError(f'{weights} missing; see docs/CONTEXT_AND_PERF_CN.md for the fetch step')
        digest = hashlib.sha256(weights.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError('Local pretrained model weight SHA256 mismatch')
        # Imports are intentionally lazy: the core project remains stdlib-only.
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(path / 'tokenizer.json'))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.max_width = 12
        self.chunk_words = int(config.get('chunk_words', 160))
        if not 24 <= self.chunk_words <= 256:
            raise ValueError('chunk_words must be in [24,256]')
        self.overlap_words = 16
        # Prompt tokens are constant; encode them once instead of per chunk.
        self.prompt_ids = []
        for label, _ in PROMPTS:
            self.prompt_ids.extend(('<<ENT>>', label))
        self.prompt_ids.append('<<SEP>>')
        self.prompt_length = len(self.prompt_ids)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(weights), sess_options=options, providers=['CPUExecutionProvider'])
        self.input_names = {item.name for item in self.session.get_inputs()}
        # instrumented for the performance report
        self.n_forward_calls = 0
        self.n_chunks = 0
        self.metadata = {'model_repo': MODEL_REPO, 'model_revision': MODEL_REVISION,
                         'upstream_repo': UPSTREAM_REPO, 'upstream_revision': UPSTREAM_REVISION,
                         'weights_sha256': digest, 'license': 'Apache-2.0 upstream; conversion card attributes upstream',
                         'runtime': 'onnxruntime', 'runtime_version': ort.__version__,
                         'provider': 'CPUExecutionProvider', 'threads': threads,
                         'threshold': self.threshold,
                         'precision': self.dtype,
                         'batch_size': self.batch_size,
                         'quantization': 'none for fp32; fp16 conversion available for the phase-2 '
                                         'reproduction; int8 dynamic conversion rejected after collapse probe',
                         'frontend_revision': FRONTEND_REVISION, 'prompts': list(PROMPTS),
                         'chunk_words': self.chunk_words, 'overlap_words': self.overlap_words,
                         'training_performed_here': False,
                         'limitations': 'Pretrained corpus contamination cannot be ruled out. Chinese character segmentation differs from upstream whitespace splitting; no real-patient acceptance.'}

    # ---- span grid -----------------------------------------------------
    def _span_arrays(self, lengths):
        np = self.np
        batch = len(lengths)
        words = int(max(lengths)) if lengths else 0
        a = np.repeat(np.arange(words), self.max_width)
        w = np.tile(np.arange(self.max_width), words)
        grid = np.stack([a, a + w], axis=-1).astype(np.int64)
        span_idx = np.broadcast_to(grid, (batch, words * self.max_width, 2)).copy()
        lengths_col = np.asarray(lengths, dtype=np.int64)[:, None]
        span_mask = (a[None, :] + w[None, :]) < lengths_col
        return span_idx, span_mask

    def prepare_batch(self, chunks):
        """Tokenise and pad a batch of word lists into one session feed."""
        np = self.np
        encodings = []
        for words in chunks:
            encoded = self.tokenizer.encode(self.prompt_ids + [w[0] for w in words],
                                           is_pretokenized=True)
            if len(encoded.ids) > 512:
                raise ValueError('Prepared chunk exceeds model positional capacity')
            encodings.append(encoded)
        n = len(encodings)
        max_len = max(len(e.ids) for e in encodings)
        input_ids = np.zeros((n, max_len), dtype=np.int64)
        attention = np.zeros((n, max_len), dtype=np.int64)
        words_mask = np.zeros((n, max_len), dtype=np.int64)
        for row, encoded in enumerate(encodings):
            length = len(encoded.ids)
            input_ids[row, :length] = encoded.ids
            attention[row, :length] = encoded.attention_mask
            previous = None
            for index, word_id in enumerate(encoded.word_ids):
                words_mask[row, index] = (
                    word_id - self.prompt_length + 1
                    if word_id is not None and word_id != previous and word_id >= self.prompt_length
                    else 0)
                previous = word_id
        lengths = [len(words) for words in chunks]
        span_idx, span_mask = self._span_arrays(lengths)
        arrays = {'input_ids': input_ids, 'attention_mask': attention,
                  'words_mask': words_mask,
                  'text_lengths': np.asarray([[value] for value in lengths], dtype=np.int64),
                  'span_idx': span_idx, 'span_mask': span_mask}
        return {name: array for name, array in arrays.items() if name in self.input_names}

    def prepare(self, words):
        """Single-chunk preparation (kept for the phase-2 reproduction path)."""
        return self.prepare_batch([words])

    def _chunk_scores_batch(self, chunks):
        inputs = self.prepare_batch(chunks)
        logits = self.session.run(None, inputs)[0]
        self.n_forward_calls += 1
        self.n_chunks += len(chunks)
        np = self.np
        probabilities = 1 / (1 + np.exp(-np.clip(logits, -80, 80)))
        if probabilities.ndim != 4 or probabilities.shape[-1] != len(PROMPTS):
            raise RuntimeError('Unexpected GLiNER ONNX output contract')
        return probabilities

    def _chunk_scores(self, words):
        return self._chunk_scores_batch([words])[0]

    def _plan_chunks(self, text):
        words = split_words(text)
        chunks, start = [], 0
        if not words:
            return chunks
        while start < len(words):
            chunk = words[start:start + self.chunk_words]
            chunks.append(chunk)
            if start + len(chunk) >= len(words):
                break
            start += max(1, len(chunk) - self.overlap_words)
        return chunks

    def _decode_chunk(self, chunk, probabilities, min_threshold):
        found = []
        for a, width, label_index in zip(*self.np.where(probabilities > min_threshold)):
            end = int(a + width)
            if end < len(chunk):
                found.append({'start': chunk[int(a)][1], 'end': chunk[end][2],
                              'label': PROMPTS[int(label_index)][1],
                              'score': float(probabilities[a, width, label_index]),
                              'source': 'gliner_onnx'})
        return found

    def candidates(self, text, min_threshold=.1):
        if not isinstance(text, str):
            raise TypeError('PHI input must be a string')
        words = split_words(text)
        if not words:
            return []
        found = []
        start = 0
        while start < len(words):
            chunk = words[start:start + self.chunk_words]
            # Long English words/URLs can create many subtokens; reduce safely,
            # never silently truncate the end of a note.
            while True:
                try:
                    probabilities = self._chunk_scores(chunk)
                    break
                except ValueError as exc:
                    if 'positional capacity' not in str(exc) or len(chunk) <= 1:
                        raise
                    chunk = chunk[:max(1, len(chunk) // 2)]
            found.extend(self._decode_chunk(chunk, probabilities, min_threshold))
            if start + len(chunk) >= len(words):
                break
            start += max(1, len(chunk) - self.overlap_words)
        return union_spans(found)

    def find_batch(self, texts):
        """Batched inference over several notes.

        Chunks from different notes share one forward pass. Padding is bounded by
        the longest chunk in the batch; span validity is carried by `span_mask`,
        so concatenating notes with different lengths cannot create spans that
        cross a note boundary.
        """
        for text in texts:
            if not isinstance(text, str):
                raise TypeError('PHI input must be a string')
        plans = [self._plan_chunks(text) for text in texts]
        flat = [(doc, chunk) for doc, chunks in enumerate(plans) for chunk in chunks]
        if self.batch_sort and self.batch_size > 1:
            # Group chunks of similar length so padding stays small; the result
            # is reassembled per document, so the order is irrelevant.
            flat.sort(key=lambda item: len(item[1]))
        collected = [[] for _ in texts]
        for begin in range(0, len(flat), self.batch_size):
            group = flat[begin:begin + self.batch_size]
            try:
                batch_scores = self._chunk_scores_batch([chunk for _, chunk in group])
            except ValueError as exc:
                if 'positional capacity' not in str(exc):
                    raise
                # Rare: an over-long tokenisation. Fall back to per-chunk halving.
                for doc, chunk in group:
                    collected[doc].extend(self._decode_chunk(
                        chunk, self._chunk_scores(chunk), self.threshold))
                continue
            for (doc, chunk), scores in zip(group, batch_scores):
                collected[doc].extend(self._decode_chunk(chunk, scores, self.threshold))
        return [self.decode(union_spans(found), self.threshold) for found in collected]

    @staticmethod
    def decode(candidates, threshold):
        # Original GLiNER flat-NER greedy decoding: highest-scoring span wins.
        kept = []
        for item in sorted((c for c in candidates if c['score'] > threshold),
                           key=lambda c: (-c['score'], c['start'], c['end'], c['label'])):
            if not any(item['start'] < prior['end'] and prior['start'] < item['end'] for prior in kept):
                kept.append(item)
        return sorted(kept, key=lambda c: (c['start'], c['end'], c['label']))

    def find(self, text):
        if self.batch_size == 1:
            return self.decode(self.candidates(text, self.threshold), self.threshold)
        return self.find_batch([text])[0]

    def find_many(self, texts):
        if self.batch_size == 1:
            return [self.find(text) for text in texts]
        return self.find_batch(list(texts))

    def close(self):
        self.session = None


class PresidioDetector:
    """Microsoft Presidio over an explicitly loaded local spaCy model."""

    def __init__(self, config):
        from .presidio_adapter import PresidioAdapter
        model_name = config.get('presidio_model', 'en_core_web_lg')
        threshold = config.get('presidio_threshold', .5)
        if not isinstance(model_name, str) or not model_name.isidentifier():
            raise ValueError('Invalid spaCy model package name')
        if isinstance(threshold, bool) or not 0 <= threshold <= 1:
            raise ValueError('Presidio score threshold must be within [0,1]')
        adapter = PresidioAdapter(model_name=model_name, score_threshold=float(threshold))
        self.adapter = adapter
        self.metadata = dict(adapter.metadata, method='presidio_spacy_local',
                             engine='Microsoft Presidio AnalyzerEngine',
                             custom_recognizers='none; predefined recognizers only, no project MRN patterns')

    def find(self, text):
        return [dict(span, source='presidio') for span in self.adapter.analyze(text)]

    def find_many(self, texts):
        return [self.find(text) for text in texts]

    def close(self):
        self.adapter = None


class HybridDetector:
    """Union of pretrained-model spans and the supplemental context rules."""

    def __init__(self, model, config):
        self.model = model
        self.batch_size = getattr(model, 'batch_size', 1)
        self.components = list(config.get('fusion_components', ['context_rules', 'gliner']))
        if any(component not in ('context_rules', 'gliner', 'presidio') for component in self.components):
            raise ValueError('Unknown fusion component')
        self.presidio = PresidioDetector(config) if 'presidio' in self.components else None
        extras = dict(model.metadata)
        if self.presidio is not None:
            extras['presidio_metadata'] = self.presidio.metadata
        self.metadata = dict(extras, method='hybrid_union', supplemental_rules=RULE_REVISION,
                             fusion_components=self.components,
                             fusion='exact span union; overlaps retained for coverage masking and honest FP accounting')

    def find(self, text):
        groups = []
        if 'gliner' in self.components:
            groups.append(self.model.find(text))
        if 'presidio' in self.components:
            groups.append(self.presidio.find(text))
        if 'context_rules' in self.components:
            groups.append(find_context_phi(text))
        return union_spans(*groups)

    def find_many(self, texts):
        """Batched union: the model runs as one batch, the rules stay per text."""
        texts = list(texts)
        model_groups = (self.model.find_many(texts)
                        if 'gliner' in self.components else [None] * len(texts))
        out = []
        for index, text in enumerate(texts):
            groups = []
            if model_groups[index] is not None:
                groups.append(model_groups[index])
            if 'presidio' in self.components:
                groups.append(self.presidio.find(text))
            if 'context_rules' in self.components:
                groups.append(find_context_phi(text))
            out.append(union_spans(*groups))
        return out

    def close(self):
        self.model.close()
        if self.presidio is not None:
            self.presidio.close()


class RuleDetector:
    """Method A: the unchanged v0.1 recognizer, wrapped for a uniform contract."""

    def __init__(self, config=None):
        self.metadata = {'method': 'original_v0_1_regex', 'engine': 'clinforge.operators.find_phi',
                         'note': 'MRN is mapped to PATIENT_ID by the evaluation layer; no other change',
                         'device': 'CPU'}

    def find(self, text):
        return [{'start': span.start, 'end': span.end, 'label': span.label,
                 'score': 1.0, 'source': 'original_regex'} for span in find_phi(text)]

    def find_many(self, texts):
        return [self.find(text) for text in texts]

    def close(self):
        return None


def create_detector(method, model_path, config):
    """A=original rules, B=Presidio, C=GLiNER, D=rules+model fusion."""
    if method == 'A':
        return RuleDetector(config)
    if method == 'B':
        return PresidioDetector(config)
    if method == 'C':
        return GLiNEROnnxDetector(model_path, config)
    if method == 'D':
        return HybridDetector(GLiNEROnnxDetector(model_path, config), config)
    raise ValueError('Method must be one of A, B, C, D')
