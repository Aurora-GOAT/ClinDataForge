"""Tests for the NegEx/ConText-style context scope resolver (v2).

Each test pins one failure mode that the phase-3 v1 window classifier got wrong,
plus the regression cases that must keep working.
"""
from __future__ import annotations
import unittest

from clinforge.context_scope import (ContextResolver, resolve_context, mask_mentions,
                                     MASK_CHAR, CUE_SETS, STATUS_PRIORITY)


def status_of(text, mention_text, occurrence=0, language='zh', cue_set='negex', mask_also=()):
    """Classify the n-th occurrence of `mention_text`.

    Like the pipeline, every extracted mention is masked before cue matching, so
    `mask_also` lists the other entity surfaces present in the sentence.
    """
    start, seen = -1, -1
    while True:
        start = text.find(mention_text, start + 1)
        if start < 0:
            raise AssertionError(f'{mention_text!r} not found')
        seen += 1
        if seen == occurrence:
            break
    spans = [(start, start + len(mention_text))]
    for surface in mask_also:
        probe = -1
        while True:
            probe = text.find(surface, probe + 1)
            if probe < 0:
                break
            spans.append((probe, probe + len(surface)))
    resolver = ContextResolver(text, language, spans, cue_set)
    return resolver.classify(start)


class SectionHeaderScopeTest(unittest.TestCase):
    """The 783-error root cause: the header sits before the colon."""

    def test_header_before_colon_governs_first_item(self):
        text = '因身材高大就诊。既往史：有肝大。'
        self.assertEqual(status_of(text, '肝大'), 'history')

    def test_header_governs_enumeration_items(self):
        text = '因身材高大就诊。既往史：有肝大，并有脾大。'
        self.assertEqual(status_of(text, '肝大'), 'history')
        self.assertEqual(status_of(text, '脾大'), 'history')

    def test_header_governs_long_list(self):
        text = '既往史：有甲、乙、丙、丁、戊、己。'
        for item in ('甲', '乙', '丙', '丁', '戊', '己'):
            self.assertEqual(status_of(text, item), 'history', item)

    def test_newline_after_header_keeps_scope(self):
        text = '既往史：\n视锥细胞营养不良、肥胖、慢性肾脏病。查体：肝大。'
        self.assertEqual(status_of(text, '肥胖'), 'history')
        self.assertEqual(status_of(text, '慢性肾脏病'), 'history')
        self.assertEqual(status_of(text, '肝大'), 'affirmed')

    def test_plain_newline_still_terminates(self):
        text = '否认肝大\n脾大明显。'
        self.assertEqual(status_of(text, '脾大'), 'affirmed')

    def test_outpatient_header_without_colon(self):
        text = '查体发现肝大。既往曾有脾大，并有水肿。'
        self.assertEqual(status_of(text, '脾大'), 'history')
        self.assertEqual(status_of(text, '水肿'), 'history')


class PseudoNegationTest(unittest.TestCase):
    """Chinese phenotype names may contain 无; masking must stop the cue firing."""

    def test_term_with_negation_character_is_not_negated(self):
        text = '主诉：因“前脑无裂畸形伴面部形态异常”就诊。'
        self.assertEqual(status_of(text, '前脑无裂畸形', mask_also=('面部形态异常',)), 'affirmed')
        self.assertEqual(status_of(text, '面部形态异常', mask_also=('前脑无裂畸形',)), 'affirmed')

    def test_absent_speech_term_does_not_negate_neighbour(self):
        text = '患儿因“无言语伴耳廓后旋”就诊。'
        self.assertEqual(status_of(text, '耳廓后旋', mask_also=('无言语',)), 'affirmed')

    def test_real_negation_still_fires(self):
        text = '否认肝大、脾大。'
        self.assertEqual(status_of(text, '肝大'), 'negated')
        self.assertEqual(status_of(text, '脾大'), 'negated')

    def test_masking_preserves_offsets(self):
        text = '前脑无裂畸形'
        masked = mask_mentions(text, [(0, 6)])
        self.assertEqual(len(masked), len(text))
        self.assertTrue(masked.startswith(MASK_CHAR * 6))


class TerminationTest(unittest.TestCase):
    def test_contrastive_conjunction_ends_scope(self):
        text = '否认肝大、脾大，但水肿明显。'
        self.assertEqual(status_of(text, '水肿'), 'affirmed')

    def test_english_however_ends_scope(self):
        text = 'The patient denies fever, however hepatomegaly is evident.'
        self.assertEqual(status_of(text, 'hepatomegaly', language='en'), 'affirmed')


class ScopeBoundaryTest(unittest.TestCase):
    def test_no_leak_across_sentences(self):
        text = '既往有肝大。本次因脾大就诊。'
        self.assertEqual(status_of(text, '肝大'), 'history')
        self.assertEqual(status_of(text, '脾大'), 'affirmed')

    def test_english_full_stop_terminates(self):
        # regression: ctxscope-1.0.0 omitted '.' from the English terminators
        text = 'Past medical history is notable for Hepatomegaly. Examination is notable for Splenomegaly.'
        self.assertEqual(status_of(text, 'Hepatomegaly', language='en'), 'history')
        self.assertEqual(status_of(text, 'Splenomegaly', language='en'), 'affirmed')

    def test_semicolon_terminates(self):
        text = '另疑有肝大；脾大明显。'
        self.assertEqual(status_of(text, '脾大'), 'affirmed')


class PrecedenceTest(unittest.TestCase):
    def test_nearest_trigger_wins(self):
        text = '既往有肝大，否认脾大。'
        self.assertEqual(status_of(text, '脾大'), 'negated')

    def test_suspicion_beats_negation_character_in_same_phrase(self):
        text = '尚需评估有无肝大。'
        self.assertEqual(status_of(text, '肝大'), 'suspected')

    def test_negation_beats_history_when_later(self):
        text = '既往有肝大，本次否认脾大。'
        self.assertEqual(status_of(text, '脾大'), 'negated')

    def test_priority_table_is_documented(self):
        self.assertLess(STATUS_PRIORITY['suspected'], STATUS_PRIORITY['negated'])
        self.assertLess(STATUS_PRIORITY['negated'], STATUS_PRIORITY['history'])


class CueSetAblationTest(unittest.TestCase):
    def test_scope_only_cue_set_keeps_v1_vocabulary(self):
        self.assertIn('既往', CUE_SETS['v1']['zh']['history'])
        self.assertNotIn('需警惕', CUE_SETS['v1']['zh']['suspected'])
        self.assertIn('需警惕', CUE_SETS['negex']['zh']['suspected'])

    def test_v1_cue_set_misses_unseen_phrase(self):
        text = '不除外肝大。'
        self.assertEqual(status_of(text, '肝大', cue_set='v1'), 'affirmed')
        self.assertEqual(status_of(text, '肝大', cue_set='negex'), 'suspected')

    def test_bare_yi_is_still_unhandled(self):
        # documented lexicon gap found by the held-out corpus
        text = '疑肝大。'
        self.assertEqual(status_of(text, '肝大'), 'affirmed')


class FunctionalWrapperTest(unittest.TestCase):
    def test_wrapper_matches_class(self):
        text = '既往史：有肝大。'
        mention = {'start': text.index('肝大'), 'lang': 'zh'}
        self.assertEqual(resolve_context(text, mention), 'history')

    def test_rejects_unknown_cue_set(self):
        with self.assertRaises(ValueError):
            ContextResolver('x', 'zh', [], 'nope')

    def test_debug_trace_exposes_evidence(self):
        text = '既往史：有肝大，并有脾大。'
        start = text.index('脾大')
        trace = ContextResolver(text, 'zh', [(text.index('肝大'), text.index('肝大') + 2),
                                            (start, start + 2)]).debug(start)
        self.assertEqual(trace['status'], 'history')
        self.assertEqual(trace['cue'], '既往史')
        self.assertTrue(trace['run'])


class EnglishListTest(unittest.TestCase):
    def test_long_denies_list_beyond_old_window(self):
        text = ('The patient denies Progressive sensorineural hearing impairment, '
                'Cerebral calcification, Failure to thrive, Postnatal growth retardation, '
                'Gonadal dysgenesis.')
        for term in ('Cerebral calcification', 'Failure to thrive',
                     'Postnatal growth retardation', 'Gonadal dysgenesis'):
            self.assertEqual(status_of(text, term, language='en'), 'negated', term)

    def test_history_list_beyond_old_window(self):
        text = ('There is a history of Strabismus, Upslanted palpebral fissure, '
                'Joint hypermobility, Long face.')
        self.assertEqual(status_of(text, 'Long face', language='en'), 'history')


if __name__ == '__main__':
    unittest.main()
