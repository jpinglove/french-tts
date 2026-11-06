# -*- coding: utf-8 -*-
"""french.txt 的 F4 例词自动回归。"""

import os
import subprocess
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from pronounce_engine import Pronouncer, clean_ipa  # noqa: E402

DB_FILE = os.path.join(BASE_DIR, 'data', 'pronounce.db')


def setUpModule():
    if not os.path.exists(DB_FILE):
        subprocess.run([sys.executable, 'build_pronounce_db.py', '--skip-regression'],
                       cwd=BASE_DIR, check=True)


class F4RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Pronouncer().load()

    def test_examples_count(self):
        self.assertEqual(len(self.p.iter_examples()), 119)

    def test_all_examples_match(self):
        wrong = []
        for word, expected in self.p.iter_examples():
            actual = clean_ipa(self.p.pronounce(word)['ipa'])
            if actual != clean_ipa(expected):
                wrong.append((word, expected, actual))
        self.assertEqual(wrong, [], f'未命中 {len(wrong)} 条：{wrong}')


if __name__ == '__main__':
    unittest.main()
