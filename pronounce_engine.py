# -*- coding: utf-8 -*-
"""法语拼读规则引擎。

从 data/pronounce.db 一次性载入规则、词表与例外词，在内存中按「最左最长匹配 +
条件判定 + 优先级」把法语单词/短语推导为音标，并给出每一步应用的规则。
"""

import os
import re
import sqlite3
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'data', 'pronounce.db')

VOWELS = set('aàâäeéèêëiîïoôöuùûüyœæ')
APOSTROPHES = {"'", '’'}
HYPHENS = {'-'}
SEPARATORS = APOSTROPHES | HYPHENS


def norm_text(text):
    """NFC 规范化、小写、去首尾空白，并把 oeu 视作 œu。"""
    text = unicodedata.normalize('NFC', text).strip().lower()
    return re.sub(r'oeu', 'œu', text)


def norm_ipa(ipa):
    return unicodedata.normalize('NFC', ipa).replace('g', 'ɡ')


def clean_ipa(ipa):
    """用于比较：去掉方括号、句点与空格。"""
    return re.sub(r'[\[\]\.\s]', '', norm_ipa(ipa))


class Rule:
    __slots__ = ('id', 'grapheme', 'phoneme', 'condition', 'output',
                 'desc', 'priority', 'silent', 'source')

    def __init__(self, row, phoneme):
        (rule_id, grapheme, output, condition, desc, priority,
         silent, source) = row
        self.id = rule_id
        self.grapheme = grapheme
        self.phoneme = phoneme
        self.condition = condition
        self.output = output
        self.desc = desc
        self.priority = priority
        self.silent = bool(silent)
        self.source = source

    def sort_key(self):
        return (len(self.grapheme), self.priority, self.id)


class Pronouncer:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_FILE
        self.by_first = {}
        self.exceptions = {}
        self.word_lists = {}
        self.spellings = {}
        self.examples = []
        self.loaded = False

    # ---------------- 载入 ----------------
    def load(self, db_path=None):
        if db_path:
            self.db_path = db_path
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f'拼读数据库不存在：{self.db_path}，请先运行 python3 build_pronounce_db.py')
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            phonemes = {row['id']: row['ipa'] for row in conn.execute(
                'SELECT id, ipa FROM phonemes')}
            rules = []
            for row in conn.execute(
                    '''SELECT id, grapheme, output_ipa, condition, condition_desc,
                              priority, is_silent, source, phoneme_id
                       FROM rules'''):
                rules.append(Rule((row['id'], row['grapheme'], row['output_ipa'],
                                   row['condition'], row['condition_desc'],
                                   row['priority'], row['is_silent'], row['source']),
                                  phonemes.get(row['phoneme_id'])))
            rules.sort(key=Rule.sort_key, reverse=True)
            for rule in rules:
                self.by_first.setdefault(rule.grapheme[0], []).append(rule)

            self.exceptions = {
                row['word']: (row['ipa'], row['note'])
                for row in conn.execute('SELECT word, ipa, note FROM exceptions')}
            for row in conn.execute('SELECT list_name, word FROM word_lists'):
                self.word_lists.setdefault(row['list_name'], set()).add(row['word'])
            self.examples = [(row['word'], row['ipa']) for row in conn.execute(
                'SELECT word, ipa FROM examples ORDER BY id')]
        finally:
            conn.close()

        self._build_spellings(rules)
        self.loaded = True
        return self

    def _build_spellings(self, rules):
        # 按数据库插入顺序（即源文件 F2 顺序）保留拼法，输出稳定
        groups = {}
        for rule in sorted(rules, key=lambda r: r.id):
            if rule.silent or not rule.phoneme:
                continue
            spellings = groups.setdefault((rule.phoneme, rule.output), [])
            if rule.grapheme not in spellings:
                spellings.append(rule.grapheme)
        self.spellings = groups

    def iter_examples(self):
        return list(self.examples)

    # ---------------- 公共接口 ----------------
    def pronounce(self, text):
        words = [self._pronounce_word(token) for token in norm_text(text).split()]
        ipa = ' '.join(w['ipa_raw'] for w in words if w['ipa_raw'])
        stats = {'rules_applied': 0, 'silent': 0, 'unknown': 0}
        for word in words:
            for seg in word['segments']:
                if seg['status'] == 'matched':
                    stats['rules_applied'] += 1
                elif seg['status'] == 'silent':
                    stats['silent'] += 1
                elif seg['status'] == 'unknown':
                    stats['unknown'] += 1
        return {
            'text': norm_text(text),
            'ipa': ipa,
            'ipa_display': f'[{ipa}]' if ipa else '',
            'complete': all(w['complete'] for w in words),
            'words': words,
            'stats': stats,
        }

    def pronounce_word(self, word):
        return self._pronounce_word(norm_text(word))

    # ---------------- 单词分析 ----------------
    def _pronounce_word(self, token):
        if token in self.exceptions:
            ipa, note = self.exceptions[token]
            return self._exception_word(token, ipa, note)

        segments = []
        for chunk in self._chunk(token):
            if chunk in SEPARATORS:
                segments.append({
                    'grapheme': chunk, 'ipa': '', 'display': chunk,
                    'status': 'separator', 'silent': False, 'spellings': [],
                    'condition_desc': '', 'source': None, 'phoneme': None,
                    'rule_id': None,
                })
                continue
            if chunk in self.exceptions:
                ipa, note = self.exceptions[chunk]
                exp = self._exception_word(chunk, ipa, note)
                segments.extend(exp['segments'])
                continue
            silent, silent_desc = self._classify_silent(chunk)
            segments.extend(self._analyze_chunk(chunk, silent, silent_desc))

        ipa = ''.join(seg['ipa'] for seg in segments if seg['status'] == 'matched')
        return {
            'word': token,
            'display': token,
            'ipa': f'[{ipa}]' if ipa else '',
            'ipa_raw': ipa,
            'complete': all(seg['status'] != 'unknown' for seg in segments),
            'exception': None,
            'segments': segments,
        }

    @staticmethod
    def _exception_word(token, ipa, note):
        return {
            'word': token,
            'display': token,
            'ipa': f'[{ipa}]',
            'ipa_raw': ipa,
            'complete': True,
            'exception': note or '例外词',
            'segments': [{
                'grapheme': token, 'ipa': ipa, 'display': f'[{ipa}]',
                'status': 'exception', 'silent': False, 'spellings': [],
                'condition_desc': note or '例外词', 'source': 'exception',
                'phoneme': None, 'rule_id': None,
            }],
        }

    @staticmethod
    def _chunk(token):
        chunks, current = [], []
        for ch in token:
            if ch in SEPARATORS:
                if current:
                    chunks.append(''.join(current))
                    current = []
                chunks.append(ch)
            else:
                current.append(ch)
        if current:
            chunks.append(''.join(current))
        return chunks

    def _classify_silent(self, chunk):
        """推导片段中不会发音的字符位置，供条件判定使用。

        返回 (静音位置集合, {位置: 静音原因})。
        """
        out = set()
        descs = {}
        length = len(chunk)
        if length == 0:
            return out, descs

        # 动词变位词尾 -ent
        if (length > 3 and chunk.endswith('ent')
                and chunk[:-3][-1] not in VOWELS):
            out.update({length - 3, length - 2, length - 1})

        # 词尾 -eux/-aux 的 x，以及词尾的 x
        if length >= 2 and chunk[-1] == 'x' and chunk[-2] in 'eua':
            out.add(length - 1)

        # 除单音节虚词外的词尾 e
        if chunk[-1] == 'e' and chunk not in self.word_lists.get('e_final_words', set()):
            out.add(length - 1)

        # 词尾辅音 s/t/d/z/p
        if length >= 2 and chunk[-1] in 'stdzp':
            out.add(length - 1)

        # 词尾 c 静音词表
        if length >= 2 and chunk[-1] == 'c' and chunk in self.word_lists.get('final_c_words', set()):
            out.add(length - 1)

        # 词尾静音簇：若某辅音之后全部是静音辅音，它也随之静音（temps 的 p）
        for idx in range(length - 2, 0, -1):
            if (chunk[idx] in 'stdzp' and chunk[idx + 1] not in VOWELS
                    and all(pos in out for pos in range(idx + 1, length))):
                out.add(idx)
                descs[idx] = '词尾辅音簇不发音'

        # h 永远不发音
        for idx, ch in enumerate(chunk):
            if ch == 'h':
                out.add(idx)
                descs[idx] = 'h 不发音'
        return out, descs

    # ---------------- 逐片段匹配 ----------------
    def _analyze_chunk(self, chunk, silent, silent_desc=None):
        silent_desc = silent_desc or {}
        nasal_sites = self._nasal_sites(chunk, silent)
        segments = []
        i, n = 0, len(chunk)
        while i < n:
            matched = None
            for rule in self.by_first.get(chunk[i], ()):
                length = len(rule.grapheme)
                if i + length > n or chunk[i:i + length] != rule.grapheme:
                    continue
                if not self._condition_ok(rule.condition, chunk, i, length,
                                          silent, nasal_sites):
                    continue
                matched = rule
                break

            if matched is None or (i in silent and not matched.silent):
                if i in silent:
                    segments.append(self._silent_segment(
                        chunk[i], silent_desc.get(i, '静音字母')))
                else:
                    segments.append(self._unknown_segment(chunk[i]))
                i += 1
                continue

            grapheme = chunk[i:i + len(matched.grapheme)]
            if matched.silent:
                segments.append(self._silent_segment(grapheme, matched.desc, matched))
            else:
                segments.append(self._matched_segment(matched))
            i += len(matched.grapheme)
        return segments

    def _nasal_sites(self, chunk, silent):
        """找出片段中应鼻化的元音组合起始位置。"""
        n = len(chunk)
        sites = []
        for i in range(n):
            rule = None
            for candidate in self.by_first.get(chunk[i], ()):
                if candidate.condition != 'nasal_context':
                    continue
                if (i + len(candidate.grapheme) <= n
                        and chunk[i:i + len(candidate.grapheme)] == candidate.grapheme):
                    rule = candidate
                    break
            if rule is None:
                continue
            end = i + len(rule.grapheme)
            doubled = end < n and chunk[end] == chunk[end - 1]
            if not doubled:
                sites.append(i)
        return set(sites)

    # ---------------- 逐片段匹配 ----------------
    def _analyze_chunk(self, chunk, silent, silent_desc=None):
        silent_desc = silent_desc or {}
        nasal_sites = self._nasal_sites(chunk, silent)
        segments = []
        i, n = 0, len(chunk)
        while i < n:
            matched = None
            for rule in self.by_first.get(chunk[i], ()):
                length = len(rule.grapheme)
                if i + length > n or chunk[i:i + length] != rule.grapheme:
                    continue
                if not self._condition_ok(rule.condition, chunk, i, length,
                                          silent, nasal_sites):
                    continue
                matched = rule
                break

            if matched is None or (i in silent and not matched.silent):
                if i in silent:
                    segments.append(self._silent_segment(
                        chunk[i], silent_desc.get(i, '静音字母')))
                else:
                    segments.append(self._unknown_segment(chunk[i]))
                i += 1
                continue

            grapheme = chunk[i:i + len(matched.grapheme)]
            if matched.silent:
                segments.append(self._silent_segment(grapheme, matched.desc, matched))
            else:
                segments.append(self._matched_segment(matched))
            i += len(matched.grapheme)
        return segments

    def _nasal_sites(self, chunk, silent):
        """找出片段中应鼻化的元音组合起始位置。"""
        n = len(chunk)
        sites = []
        for i in range(n):
            rule = None
            for candidate in self.by_first.get(chunk[i], ()):
                if candidate.condition != 'nasal_context':
                    continue
                if (i + len(candidate.grapheme) <= n
                        and chunk[i:i + len(candidate.grapheme)] == candidate.grapheme):
                    rule = candidate
                    break
            if rule is None:
                continue
            end = i + len(rule.grapheme)
            doubled = end < n and chunk[end] == chunk[end - 1]
            if not doubled:
                sites.append(i)
        return set(sites)

    @staticmethod
    def _silent_segment(grapheme, desc, rule=None):
        return {
            'grapheme': grapheme, 'ipa': '', 'display': '静音',
            'status': 'silent', 'silent': True,
            'spellings': [], 'condition_desc': desc,
            'source': rule.source if rule else 'supplement',
            'phoneme': None, 'rule_id': rule.id if rule else None,
        }

    @staticmethod
    def _unknown_segment(grapheme):
        return {
            'grapheme': grapheme, 'ipa': '?', 'display': '未识别',
            'status': 'unknown', 'silent': False,
            'spellings': [], 'condition_desc': '规则库中未找到该字母的读音',
            'source': None, 'phoneme': None, 'rule_id': None,
        }

    def _matched_segment(self, rule):
        spellings = list(self.spellings.get((rule.phoneme, rule.output), []))
        if rule.grapheme not in spellings:
            spellings.insert(0, rule.grapheme)
        return {
            'grapheme': rule.grapheme, 'ipa': rule.output,
            'display': f'[{rule.output}]',
            'status': 'matched', 'silent': False,
            'spellings': spellings,
            'condition_desc': rule.desc,
            'source': rule.source,
            'phoneme': rule.phoneme,
            'rule_id': rule.id,
        }

    # ---------------- 条件判定 ----------------
    @staticmethod
    def _next_pronounced_consonant_index(word, start, silent, limit=None):
        limit = len(word) if limit is None else min(limit, len(word))
        for idx in range(start, limit):
            ch = word[idx]
            if ch in VOWELS:
                return None
            if ch in SEPARATORS:
                return None
            if idx not in silent:
                return idx
        return None

    @staticmethod
    def _next_vowel_index(word, start, silent, limit=None):
        limit = len(word) if limit is None else min(limit, len(word))
        for idx in range(start, limit):
            ch = word[idx]
            if ch in VOWELS and idx not in silent:
                return idx
            if ch in SEPARATORS:
                return None
        return None

    @staticmethod
    def _intervocalic(word, pos, silent):
        n = len(word)
        prev_ok = pos > 0 and word[pos - 1] in VOWELS
        next_ok = pos + 1 < n and word[pos + 1] in VOWELS
        return prev_ok and next_ok

    def _rest_all_silent(self, word, start, silent):
        return all(idx in silent for idx in range(start, len(word)))

    def _condition_ok(self, condition, word, i, length, silent, nasal_sites=None):
        n = len(word)
        end = i + length
        next_ch = word[end] if end < n else ''
        next2 = word[end:end + 2]
        nasal_sites = nasal_sites or set()

        def is_vowel(ch):
            return bool(ch) and ch in VOWELS

        def pronounced(pos):
            return pos < n and pos not in silent

        def next_site_after(pos):
            sites = [s for s in nasal_sites if s >= pos]
            return min(sites) if sites else n

        if condition == 'always':
            return True
        if condition == 'word_final':
            return end == n
        if condition == 'word_initial':
            # 词首，或位于辅音旁（词首/辅音后的 s 等）
            return i == 0 or word[i - 1] not in VOWELS
        if condition == 'before_vowel':
            return is_vowel(next_ch)
        if condition == 'before_pronounced_vowel':
            return is_vowel(next_ch) and pronounced(end)
        if condition == 'before_e_i_y':
            return next_ch in ('e', 'é', 'è', 'ê', 'ë', 'i', 'î', 'ï', 'y')
        if condition == 'before_a_o_u':
            return next_ch in ('a', 'à', 'â', 'o', 'ô', 'u', 'ù', 'û', 'œ')
        if condition == 'before_r':
            return next_ch == 'r'
        if condition == 'before_z':
            return next_ch == 'z' or (next_ch == 's' and self._intervocalic(word, end, silent))
        if condition == 'before_z_or_t':
            return next_ch in ('z', 't')
        if condition == 'before_pronounced_consonant':
            return bool(next_ch) and not is_vowel(next_ch) and pronounced(end)
        if condition == 'before_pronounced_consonant_except_z':
            return (bool(next_ch) and not is_vowel(next_ch)
                    and next_ch != 'z' and pronounced(end))
        if condition == 'open_final_or_before_z_t':
            return end == n or next_ch in ('z', 't')
        if condition == 'intervocalic':
            return self._intervocalic(word, i, silent)
        if condition in ('closed_syllable', 'open_syllable'):
            # 以词尾或下一个鼻化位置作为音节边界（鼻化组合自成音节）
            limit = min(n, next_site_after(end))
            consonant = self._next_pronounced_consonant_index(word, end, silent, limit)
            vowel = self._next_vowel_index(word, end, silent, limit)
            if condition == 'closed_syllable':
                return consonant is not None
            return vowel is not None and consonant is None
        if condition == 'o_final':
            return (self._rest_all_silent(word, end, silent)
                    or self._condition_ok('before_z', word, i, length, silent))
        if condition == 'nasal_context':
            if end == n:
                return not any(j in silent for j in range(i, end))
            if is_vowel(next_ch):
                return False
            # 双写辅音阻断鼻化（pomme、anneau）
            if next_ch == word[end - 1]:
                return False
            # n/m 后接元音时，n/m 归入下一音节（année、ennui 类例外交给词表）
            if next_ch in 'nm' and end + 1 < n and word[end + 1] in VOWELS:
                return False
            return True
        if condition == 'before_double_consonant':
            return len(next2) == 2 and next2[0] == next2[1] and next2[0] not in VOWELS
        if condition == 'after_vowel':
            return i > 0 and word[i - 1] in VOWELS
        if condition == 'word_final_et':
            return end == n and word != 'et'
        if condition == 'i_between_vowels':
            return (i > 0 and word[i - 1] in VOWELS
                    and end < n and word[end] in VOWELS)
        if condition == 'y_glide':
            follower = word[end + 1] if end + 1 < n else ''
            return (word[end] in VOWELS
                    or (word[end] == 'e' and follower in VOWELS))
        if condition == 'schwa_context':
            # 单词的第一个元音，且后面还有可发音的元音（开音节）
            if any(word[idx] in VOWELS and idx not in silent for idx in range(i)):
                return False
            return self._next_vowel_index(word, end, silent) is not None
        if condition == 'e_silent':
            return end == n and word not in self.word_lists.get('e_final_words', set())
        if condition == 'silent_final_x':
            return end == n and i > 0 and word[i - 1] in 'eua'
        if condition == 'ends_with_ent':
            return (end == n and len(word) > 3
                    and word[:-3][-1] not in VOWELS)
        if condition.startswith('word_in:'):
            list_name = condition.split(':', 1)[1]
            return word in self.word_lists.get(list_name, set())
        raise ValueError(f'未知规则条件：{condition}')


def analyze(db_path=None):
    return Pronouncer().load(db_path)
