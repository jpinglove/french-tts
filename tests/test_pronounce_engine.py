# -*- coding: utf-8 -*-
"""拼读引擎单元测试。运行前如无数据库会先调用构建脚本生成。"""

import os
import subprocess
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pronounce_engine import Pronouncer, norm_text, clean_ipa  # noqa: E402

DB_FILE = os.path.join(BASE_DIR, 'data', 'pronounce.db')


def setUpModule():
    if not os.path.exists(DB_FILE):
        subprocess.run([sys.executable, 'build_pronounce_db.py', '--skip-regression'],
                       cwd=BASE_DIR, check=True)


def ipa_of(pronouncer, word):
    return clean_ipa(pronouncer.pronounce(word)['ipa'])


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Pronouncer().load()

    def test_spec_examples(self):
        cases = {
            'chat': 'ʃa',
            'marché': 'maʁʃe',
            'maison': 'mɛzɔ̃',
            'porte': 'pɔʁt',
            'temps': 'tɑ̃',
            'fille': 'fij',
            'avec': 'avɛk',
            'bonjour': 'bɔ̃ʒuʁ',
            'les': 'le',
            'mer': 'mɛʁ',
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(ipa_of(self.p, word), expected)

    def test_context_rules(self):
        cases = {
            'café': 'kafe',
            'ce': 'sə',
            'garçon': 'ɡaʁsɔ̃',
            'guide': 'ɡid',
            'gare': 'ɡaʁ',
            'poisson': 'pwasɔ̃',
            'nation': 'nasjɔ̃',
            'rose': 'ʁoz',
            'yeux': 'jø',
            'oiseau': 'wazo',
            'château': 'ʃɑto',
            'sœur': 'sœʁ',
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(ipa_of(self.p, word), expected)

    def test_silent_boundaries(self):
        cases = {
            'vous': 'vu',
            'grand': 'ɡʁɑ̃',
            'grande': 'ɡʁɑ̃d',
            'parlent': 'paʁl',
            'deux': 'dø',
            'huit': 'ɥit',
            'pomme': 'pɔm',
            'anneau': 'ano',
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(ipa_of(self.p, word), expected)

    def test_exception_words(self):
        cases = {'femme': 'fam', 'monsieur': 'məsjø', 'fils': 'fis',
                 'ville': 'vil', 'pays': 'pei', 'œil': 'œj'}
        for word, expected in cases.items():
            with self.subTest(word=word):
                result = self.p.pronounce(word)
                self.assertEqual(clean_ipa(result['ipa']), expected)
                self.assertIsNotNone(result['words'][0]['exception'])

    def test_phrase_and_apostrophe(self):
        result = self.p.pronounce("l'école")
        self.assertEqual(clean_ipa(result['ipa']), 'lekɔl')
        result = self.p.pronounce('bonjour tout le monde')
        self.assertEqual(clean_ipa(result['ipa']), 'bɔ̃ʒuʁtuləmɔ̃d')
        self.assertEqual(len(result['words']), 4)

    def test_case_and_nfc(self):
        self.assertEqual(ipa_of(self.p, 'CHAT'), 'ʃa')
        self.assertEqual(norm_text('ÉCOLE'), 'école')

    def test_segments_have_rules(self):
        result = self.p.pronounce('chat')
        segments = result['words'][0]['segments']
        self.assertEqual([s['grapheme'] for s in segments], ['ch', 'a', 't'])
        self.assertEqual(segments[0]['display'], '[ʃ]')
        self.assertEqual(segments[0]['source'], 'french.txt')
        self.assertEqual(segments[2]['status'], 'silent')
        self.assertIn('sch', segments[0]['spellings'])

    def test_complete_and_stats(self):
        result = self.p.pronounce('bonjour')
        self.assertTrue(result['complete'])
        self.assertEqual(result['stats']['rules_applied'],
                         sum(1 for s in result['words'][0]['segments']
                             if s['status'] == 'matched'))
        self.assertEqual(result['ipa_display'], '[bɔ̃ʒuʁ]')

    def test_unknown_character(self):
        result = self.p.pronounce('chat5')
        # 数字不在字母表中，API 会拦截；引擎自身标记为未识别
        self.assertFalse(result['complete'])


if __name__ == '__main__':
    unittest.main()
