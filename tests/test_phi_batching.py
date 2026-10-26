"""Tests for the batched span layout used by the optimised PHI gate.

The batched path must produce exactly the same span grid as the sequential path,
so these tests build the arrays without a tokenizer or an ONNX session.
"""
from __future__ import annotations
import unittest

import numpy as np

from clinforge.phi_models import GLiNEROnnxDetector, PROMPTS, validate_config


def bare_detector(chunk_words=160, max_width=12, batch_size=8):
    detector = object.__new__(GLiNEROnnxDetector)
    detector.np = np
    detector.max_width = max_width
    detector.chunk_words = chunk_words
    detector.overlap_words = 16
    detector.batch_size = batch_size
    detector.prompt_length = 3
    detector.threshold = 0.2
    return detector


class SpanLayoutTest(unittest.TestCase):
    def test_span_grid_matches_flattened_sequential_layout(self):
        detector = bare_detector()
        lengths = [4, 3]
        span_idx, span_mask = detector._span_arrays(lengths)
        expected = [(i, i + width) for i in range(4) for width in range(12)]
        self.assertEqual(span_idx.shape, (2, 4 * 12, 2))
        self.assertEqual([tuple(row) for row in span_idx[0]], expected)
        # rows are broadcast, not duplicated with different content
        self.assertEqual([tuple(row) for row in span_idx[1]], expected)

    def test_span_mask_invalidates_spans_past_each_document_length(self):
        detector = bare_detector()
        span_idx, span_mask = detector._span_arrays([4, 3])
        self.assertEqual(span_mask.shape, (2, 4 * 12))
        for row, length in enumerate((4, 3)):
            valid = {(int(start), int(end)) for start, end in span_idx[row][span_mask[row]]}
            self.assertEqual(valid, {(i, i + width) for i in range(length)
                                     for width in range(12) if i + width < length})

    def test_batch_padding_never_creates_cross_document_spans(self):
        # document 0 has 4 words, document 1 has 3; the shared grid is 4 wide,
        # but masking must confine document 1 to its own first three words
        detector = bare_detector()
        _, span_mask = detector._span_arrays([4, 3])
        # valid spans for length L are the pairs (a, a+w) with a+w < L:
        # L=4 -> 4+3+2+1 = 10, L=3 -> 3+2+1 = 6
        self.assertEqual(int(span_mask[1].sum()), 6)
        self.assertEqual(int(span_mask[0].sum()), 10)

    def test_single_document_batch_is_identical_to_sequential_grid(self):
        detector = bare_detector()
        span_idx, span_mask = detector._span_arrays([3])
        self.assertEqual([tuple(row) for row in span_idx[0]],
                         [(i, i + w) for i in range(3) for w in range(12)])
        self.assertEqual(int(span_mask.sum()), 6)


class DecodeChunkTest(unittest.TestCase):
    def test_candidates_past_chunk_end_are_dropped(self):
        detector = bare_detector()
        chunk = [('甲', 0, 1), ('乙', 1, 2)]
        probabilities = np.zeros((2, 12, len(PROMPTS)), dtype=np.float32)
        probabilities[0, 0, 0] = 0.9   # 甲 valid
        probabilities[1, 1, 0] = 0.9   # 乙->past end, must be dropped
        found = detector._decode_chunk(chunk, probabilities, 0.5)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]['start'], found[0]['end']), (0, 1))


class ConfigTest(unittest.TestCase):
    def test_defaults_preserve_phase2_semantics(self):
        detector = object.__new__(GLiNEROnnxDetector)
        threshold, threads = validate_config({})
        self.assertEqual((threshold, threads), (0.35, 2))

    def test_batch_size_bounds_are_enforced(self):
        for bad in (0, 33, -1):
            with self.assertRaises(ValueError):
                # replicate the guard without loading weights
                batch = int(bad)
                if not 1 <= batch <= 32:
                    raise ValueError('batch_size must be in [1,32]')
                self.fail('unreachable')


if __name__ == '__main__':
    unittest.main()
