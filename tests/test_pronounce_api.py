# -*- coding: utf-8 -*-
"""POST /pronounce 接口测试。

测试环境不安装 Azure Speech SDK，这里用桩模块顶替，避免引入大型依赖。
"""

import os
import sys
import types
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)


def _install_azure_stub():
    if 'azure.cognitiveservices.speech' in sys.modules:
        return
    azure = types.ModuleType('azure')
    cognitiveservices = types.ModuleType('azure.cognitiveservices')
    speech = types.ModuleType('azure.cognitiveservices.speech')
    speech.SpeechConfig = object
    speech.SpeechSynthesizer = object
    speech.audio = types.SimpleNamespace(AudioOutputConfig=object)
    speech.ResultReason = types.SimpleNamespace(SynthesizingAudioCompleted=1)
    sys.modules.setdefault('azure', azure)
    sys.modules.setdefault('azure.cognitiveservices', cognitiveservices)
    sys.modules.setdefault('azure.cognitiveservices.speech', speech)


_install_azure_stub()

import app as app_module  # noqa: E402


class PronounceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config['TESTING'] = True
        cls.client = app_module.app.test_client()

    def test_pronounce_success(self):
        res = self.client.post('/pronounce', json={'text': 'chat'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['ipa_display'], '[ʃa]')
        self.assertTrue(data['complete'])
        self.assertEqual(data['words'][0]['segments'][0]['grapheme'], 'ch')
        self.assertEqual(data['stats']['rules_applied'], 2)

    def test_phrase(self):
        res = self.client.post('/pronounce', json={'text': 'bonjour tout le monde'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.get_json()['words']), 4)

    def test_empty_input(self):
        res = self.client.post('/pronounce', json={'text': '   '})
        self.assertEqual(res.status_code, 400)

    def test_invalid_characters(self):
        for text in ['123', '<script>', 'chat;ls']:
            with self.subTest(text=text):
                res = self.client.post('/pronounce', json={'text': text})
                self.assertEqual(res.status_code, 400)

    def test_too_long(self):
        res = self.client.post('/pronounce', json={'text': 'a' * 201})
        self.assertEqual(res.status_code, 400)

    def test_database_missing(self):
        original = app_module.pronouncer.loaded
        app_module.pronouncer.loaded = False
        try:
            res = self.client.post('/pronounce', json={'text': 'chat'})
            self.assertEqual(res.status_code, 503)
        finally:
            app_module.pronouncer.loaded = original

    def test_get_not_allowed(self):
        res = self.client.get('/pronounce')
        self.assertEqual(res.status_code, 405)

    def test_index_still_works(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('拼读', html)
        self.assertIn('语音', html)


if __name__ == '__main__':
    unittest.main()
