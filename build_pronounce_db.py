# -*- coding: utf-8 -*-
"""拼读规则数据库构建脚本。

解析 docs/french.txt（36 张音素卡、103 条拼写规则、119 条例词），合并补充规则与
例外词表，生成 data/pronounce.db。

用法：
    python3 build_pronounce_db.py             # 构建数据库并运行校验
    python3 build_pronounce_db.py --verify    # 仅校验现有数据库并回归
    python3 build_pronounce_db.py --stats     # 只打印源文件解析统计，不写库
"""

import argparse
import hashlib
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(BASE_DIR, 'docs', 'french.txt')
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_FILE = os.path.join(DATA_DIR, 'pronounce.db')
DB_TMP = DB_FILE + '.tmp'

BUILD_VERSION = '1.0'
BOLD_RE = re.compile(r'<b[^>]*>(.*?)</b>', re.S)
BR_RE = re.compile(r'<br\s*/?>', re.I)

# ==================== 条件键 ====================
# 运行期引擎（pronounce_engine.py）与构建期共享同一组条件键。
VALID_CONDITIONS = {
    'always', 'word_final', 'word_initial',
    'before_vowel', 'before_pronounced_vowel',
    'before_e_i_y', 'before_a_o_u',
    'before_r', 'before_z', 'before_z_or_t',
    'before_pronounced_consonant', 'before_pronounced_consonant_except_z',
    'open_final_or_before_z_t',
    'intervocalic', 'closed_syllable', 'open_syllable',
    'nasal_context', 'before_double_consonant', 'after_vowel',
    'word_final_et', 'schwa_context', 'e_silent', 'ends_with_ent',
    'silent_final_x', 'o_final', 'i_between_vowels', 'y_glide',
}
# 未单独覆盖优先级时，按条件给出默认优先级
CONDITION_PRIORITY = {
    'nasal_context': 20,
    'i_between_vowels': 30,
    'y_glide': 12,
}
WORD_LIST_CONDITIONS = {
    'e_final_words', 'final_es_words', 'greek_ch_words', 'final_c_words',
    'x_as_z_words', 'ex_gz_words',
}

# 词表：供 word_in:<名称> 条件使用
WORD_LISTS = {
    # 词尾 e 读 [ə] 的单音节虚词
    'e_final_words': {'le', 'ce', 'je', 'me', 'te', 'se', 'que', 'ne', 'de'},
    # 词尾 -es 读 [e] 的虚词
    'final_es_words': {'les', 'des', 'ses', 'ces', 'mes', 'tes'},
    # ch 读 [k] 的希腊词源词
    'greek_ch_words': {'chaos', 'orchestre', 'chœur', 'choeur', 'chrétien',
                       'chrome', 'technique', 'archéologie', 'psychologie',
                       'chirurgie', 'chiropraxie', 'choral', 'choléra'},
    # 词尾 c 不发音的词
    'final_c_words': {'blanc', 'banc', 'franc', 'tronc', 'suc', 'duc'},
    # x 读 [z] 的词（联诵不处理，仅保留独立使用时的发音）
    'x_as_z_words': {'dixième', 'sixième'},
    # x 读 [gz] 的词（ex- 后接元音）
    'ex_gz_words': {'examen', 'exemple', 'exercice', 'exiger', 'exister',
                    'exact', 'exécuter', 'exode', 'exil'},
}

# 源规则映射：音素 → 拼法 → 源括号原文或 None → (条件键, 说明)
# 映射不到的源规则会让构建失败，防止静默丢失。
SOURCE_CONDITION_MAP = {
    '[i]': {'i': {None: ('always', '')}, 'î': {None: ('always', '')},
            'ï': {None: ('always', '')}, 'y': {None: ('always', '')}},
    '[e]': {'é': {None: ('always', '')},
            'er': {'词尾': ('word_final', '词尾 -er')},
            'ez': {'词尾': ('word_final', '词尾 -ez')},
            'ed': {'词尾': ('word_final', '词尾 -ed')},
            'es': {'在单音节虚词中': ('word_in:final_es_words', '单音节虚词词尾 -es')}},
    '[ɛ]': {'è': {None: ('always', '')}, 'ê': {None: ('always', '')},
            'ë': {None: ('always', '')}, 'ei': {None: ('always', '')},
            'ai': {None: ('always', '')}, 'aî': {None: ('always', '')},
            'e': {'闭音节/双辅音前/-et词尾': ('closed_syllable', '闭音节 / 双辅音前 / 词尾 -et')}},
    '[a]': {'a': {None: ('always', '')}, 'à': {None: ('always', '')}},
    '[ɑ]': {'â': {None: ('always', '')},
            'as': {'词尾': ('word_final', '词尾 -as')},
            'az': {'词尾': ('word_final', '词尾 -az')}},
    '[ɔ]': {'o': {'在发音辅音前': ('closed_syllable', '在发音辅音前')},
            'au': {'仅在 r 前': ('before_r', '仅在 r 前')}},
    '[o]': {'ô': {None: ('always', '')}, 'au': {None: ('always', '')},
            'eau': {None: ('always', '')},
            'o': {'在词尾或 [z] 音前': ('o_final', '在词尾或 [z] 音前')}},
    '[u]': {'ou': {None: ('always', '')}, 'oû': {None: ('always', '')},
            'où': {None: ('always', '')}},
    '[y]': {'u': {None: ('always', '')}, 'û': {None: ('always', '')}},
    '[ø]': {'eu': {None: ('always', '')},
            'œu': {'词尾开音节或在 [z], [t] 等辅音前': ('open_final_or_before_z_t', '词尾开音节或在 [z]、[t] 前')}},
    '[œ]': {'eu': {None: ('before_pronounced_consonant_except_z', '在除 [z] 外的发音辅音前')},
            'œu': {'在除 [z] 外的发音辅音前，特别在 r 前': ('before_pronounced_consonant_except_z', '在除 [z] 外的发音辅音前（尤其 r 前）')}},
    '[ə]': {'e': {'单音节词中或词首开音节中': ('schwa_context', '单音节词 / 词首开音节')}},
    '[ɑ̃]': {'an': {None: ('nasal_context', '后无元音或双写辅音')},
            'am': {None: ('nasal_context', '后无元音或双写辅音')},
            'en': {None: ('nasal_context', '后无元音或双写辅音')},
            'em': {'后无元音或双写辅音': ('nasal_context', '后无元音或双写辅音')}},
    '[ɛ̃]': {'in': {None: ('nasal_context', '后无元音或双写辅音')},
            'im': {None: ('nasal_context', '后无元音或双写辅音')},
            'ain': {None: ('nasal_context', '后无元音或双写辅音')},
            'aim': {None: ('nasal_context', '后无元音或双写辅音')},
            'ein': {None: ('nasal_context', '后无元音或双写辅音')},
            'eim': {None: ('nasal_context', '后无元音或双写辅音')},
            'yn': {None: ('nasal_context', '后无元音或双写辅音')},
            'ym': {None: ('nasal_context', '后无元音或双写辅音')}},
    '[ɔ̃]': {'on': {None: ('nasal_context', '后无元音或双写辅音')},
            'om': {'后无元音或双写辅音': ('nasal_context', '后无元音或双写辅音')}},
    '[œ̃]': {'un': {None: ('nasal_context', '后无元音或双写辅音')},
            'um': {'后无元音或双写辅音': ('nasal_context', '后无元音或双写辅音')}},
    '[j]': {'y': {None: ('y_glide', '词首或两个元音之间')},
            'i': {'后接元音': ('i_between_vowels', '位于两个元音之间')},
            'ill': {'元音后': ('after_vowel', '元音后')},
            'il': {'词尾元音后': ('after_vowel', '词尾元音后（-il）')}},
    '[w]': {'ou': {'后接元音': ('before_pronounced_vowel', '后接元音')},
            'oi': {'固定组合，发 [wa]': ('always', '固定组合发 [wa]，输出 wa')}},
    '[ɥ]': {'u': {'后接发音元音': ('before_pronounced_vowel', '后接发音元音')}},
    '[p]': {'p': {None: ('always', '')}, 'pp': {None: ('always', '')}},
    '[b]': {'b': {None: ('always', '')}, 'bb': {None: ('always', '')}},
    '[t]': {'t': {None: ('always', '')}, 'tt': {None: ('always', '')},
            'th': {None: ('always', '')}},
    '[d]': {'d': {None: ('always', '')}, 'dd': {None: ('always', '')}},
    '[k]': {'k': {None: ('always', '')}, 'qu': {None: ('always', '')},
            'c': {'在 a, o, u 前': ('before_a_o_u', '在 a, o, u 前')},
            'cc': {None: ('always', '')},
            'ch': {'希腊语源词中': ('word_in:greek_ch_words', '希腊语源词中')}},
    '[ɡ]': {'g': {'在 a, o, u 前': ('before_a_o_u', '在 a, o, u 前')},
            'gu': {'在 e, i 前': ('before_e_i_y', '在 e, i 前')}},
    '[f]': {'f': {None: ('always', '')}, 'ff': {None: ('always', '')},
            'ph': {None: ('always', '')}},
    '[v]': {'v': {None: ('always', '')}, 'w': {'外来词中': ('always', '外来词中')}},
    '[s]': {'s': {'词首或辅音旁': ('word_initial', '词首或辅音旁')},
            'ss': {None: ('always', '')},
            'c': {'在 e, i, y 前': ('before_e_i_y', '在 e, i, y 前')},
            'ç': {'在 a, o, u 前': ('always', '在 a, o, u 前')},
            'tion': {'中的 t': ('always', '词尾 -tion 中的 t')}},
    '[z]': {'z': {None: ('always', '')},
            's': {'两个元音字母之间！核心法则': ('intervocalic', '两个元音字母之间')},
            'x': {'某些词或联诵时': ('word_in:x_as_z_words', '某些词中（词表）')}},
    '[ʃ]': {'ch': {None: ('always', '')}, 'sch': {None: ('always', '')}},
    '[ʒ]': {'j': {None: ('always', '')},
            'g': {'在 e, i, y 前': ('before_e_i_y', '在 e, i, y 前')},
            'ge': {'在 a, o 前为了保音': ('before_a_o_u', '在 a, o 前为保持音色')}},
    '[l]': {'l': {None: ('always', '')}, 'll': {None: ('always', '')}},
    '[ʁ]': {'r': {None: ('always', '')}, 'rr': {None: ('always', '')}},
    '[m]': {'m': {None: ('always', '')}, 'mm': {None: ('always', '')}},
    '[n]': {'n': {None: ('always', '')}, 'nn': {None: ('always', '')}},
    '[ɲ]': {'gn': {None: ('always', '')}},
}

# 优先级覆盖：未列出的默认 10。规则选择顺序为「长度降序 → 优先级降序」。
PRIORITY_OVERRIDES = {
    ('[o]', 'o', 'o_final'): 20,
    ('[ɔ]', 'o', 'closed_syllable'): 20,
    ('[ɔ]', 'au', 'before_r'): 12,
    ('[ɛ]', 'e', 'closed_syllable'): 20,
    ('[ə]', 'e', 'schwa_context'): 25,
    ('[y]', 'u', 'always'): 20,
    ('[ɥ]', 'u', 'before_pronounced_vowel'): 30,
    ('[j]', 'y', 'before_pronounced_vowel'): 30,
    ('[j]', 'i', 'before_pronounced_vowel'): 30,
    ('[j]', 'ill', 'after_vowel'): 20,
    ('[w]', 'ou', 'before_pronounced_vowel'): 30,
    ('[ø]', 'eu', 'always'): 12,
    ('[ɡ]', 'g', 'before_a_o_u'): 20,
    ('[ʒ]', 'g', 'before_e_i_y'): 20,
    ('[s]', 's', 'word_initial'): 5,
    ('[z]', 's', 'intervocalic'): 25,
    ('[k]', 'qu', 'always'): 30,
    ('[ɡ]', 'gu', 'before_e_i_y'): 30,
    ('[k]', 'ch', 'word_in:greek_ch_words'): 50,
    ('[t]', 't', 'always'): 5,
    ('[d]', 'd', 'always'): 5,
    ('[p]', 'p', 'always'): 5,
    ('[b]', 'b', 'always'): 5,
    ('[l]', 'l', 'always'): 5,
    ('[ʁ]', 'r', 'always'): 5,
    ('[m]', 'm', 'always'): 5,
    ('[n]', 'n', 'always'): 5,
    ('[f]', 'f', 'always'): 5,
    ('[v]', 'v', 'always'): 5,
    ('[s]', 'c', 'before_e_i_y'): 30,
    ('[e]', 'es', 'word_in:final_es_words'): 25,
    ('[ʃ]', 'ch', 'always'): 40,
    ('[j]', 'il', 'after_vowel'): 15,
}

# 补充规则：(grapheme, 音素, 输出, 条件, 说明, 优先级, 是否静音)
SUPPLEMENT_RULES = [
    # --- 默认读音 ---
    ('g', '[ɡ]', 'ɡ', 'always', '默认读音（g 在 a, o, u 前）', 6, 0),
    ('c', '[k]', 'k', 'always', '默认读音（c 在 a, o, u 前）', 8, 0),
    ('w', '[v]', 'v', 'always', '外来词中', 10, 0),
    ('x', '[ks]', 'ks', 'always', 'x 发音', 20, 0),
    ('x', '[gz]', 'gz', 'word_in:ex_gz_words', 'ex- 后接元音', 30, 0),
    ('œ', '[œ]', 'œ', 'always', 'œ 的读音', 20, 0),
    # --- 元音与辅音组合 ---
    ('ill', '[ij]', 'ij', 'always', 'ill 发 [ij]', 41, 0),
    ('ill', '[j]', 'j', 'after_vowel', 'ill 在元音后发 [j]', 42, 0),
    ('ail', '[aj]', 'aj', 'word_final', '词尾 -ail', 30, 0),
    ('eil', '[ɛj]', 'ɛj', 'word_final', '词尾 -eil', 30, 0),
    ('euil', '[œj]', 'œj', 'word_final', '词尾 -euil', 30, 0),
    ('aill', '[aj]', 'aj', 'always', 'aill → [aj]', 35, 0),
    ('eill', '[ɛj]', 'ɛj', 'always', 'eill → [ɛj]', 35, 0),
    ('ouill', '[uj]', 'uj', 'always', 'ouill → [uj]', 35, 0),
    ('euill', '[œj]', 'œj', 'always', 'euill → [œj]', 35, 0),
    ('ien', '[jɛ̃]', 'jɛ̃', 'always', 'ien → [jɛ̃]', 30, 0),
    ('oin', '[wɛ̃]', 'wɛ̃', 'always', 'oin → [wɛ̃]', 30, 0),
    ('ay', '[ɛj]', 'ɛj', 'always', 'ay → [ɛj]', 20, 0),
    ('ey', '[ɛj]', 'ɛj', 'always', 'ey → [ɛj]', 20, 0),
    ('oy', '[waj]', 'waj', 'always', 'oy → [waj]', 20, 0),
    ('cc', '[ks]', 'ks', 'before_e_i_y', 'cc 在 e, i, y 前', 35, 0),
    ('geons', '[ʒɔ̃]', 'ʒɔ̃', 'always', 'nous mangeons 等词尾', 40, 0),
    ('et', '[ɛ]', 'ɛ', 'always', '-et 词尾读 [ɛ]', 15, 0),
    ('ph', '[f]', 'f', 'always', 'ph 发 [f]', 30, 0),
    ('eur', '[œ]', 'œʁ', 'word_final', 'eu + 词尾 r 读 [œʁ]', 30, 0),
    ('eur', '[œ]', 'œʁ', 'before_pronounced_consonant', 'eu 在 r 前读 [œ]', 30, 0),
    ('o', '[o]', 'o', 'open_syllable', '开音节中的 o', 12, 0),
    # --- 静音规则（优先级低于语境规则、高于默认读音） ---
    ('e', None, '', 'e_silent', '词尾哑音 e', 5, 1),
    ('es', None, '', 'word_final', '词尾 -es 不发音', 15, 1),
    ('s', None, '', 'word_final', '词尾 s 不发音', 15, 1),
    ('t', None, '', 'word_final', '词尾 t 不发音', 15, 1),
    ('d', None, '', 'word_final', '词尾 d 不发音', 15, 1),
    ('x', None, '', 'silent_final_x', '词尾 -eux/-aux 的 x 不发音', 30, 1),
    ('z', None, '', 'word_final', '词尾 z 不发音', 15, 1),
    ('p', None, '', 'word_final', '词尾 p 不发音', 15, 1),
    ('c', None, '', 'word_in:final_c_words', '部分词尾 c 不发音', 15, 1),
    ('h', None, '', 'always', 'h 不发音', 5, 1),
    ('mn', None, '', 'always', 'mn 中 m 不发音', 15, 1),
    ('ent', None, '', 'ends_with_ent', '动词变位词尾 -ent', 15, 1),
]

# 例外词表：word -> (ipa, note)
EXCEPTIONS = {
    'hier': ('jɛʁ', 'h 不发音、ie 读 [jɛ]；例外'),
    'merci': ('mɛʁsi', 'e 在 r 前读 [ɛ]；例外'),
    'et': ('e', '连词 et 读 [e]；例外'),
    'mer': ('mɛʁ', '-er 词尾读 [ɛ]；例外'),
    'fer': ('fɛʁ', '-er 词尾读 [ɛ]；例外'),
    'cher': ('ʃɛʁ', '-er 词尾读 [ɛ]；例外'),
    'hiver': ('ivɛʁ', 'r 词尾发音；例外'),
    'femme': ('fam', 'e 读 [a]，mm 整段发音；例外'),
    'monsieur': ('məsjø', '整体读音特殊；例外'),
    'mademoiselle': ('madmwazɛl', '整体读音特殊；例外'),
    'fils': ('fis', '词尾 fils 读 [fis]；例外'),
    'pays': ('pei', '整体读音特殊；例外'),
    'pied': ('pje', 'ie 组合读音；例外'),
    'maïs': ('mais', '词尾 s 发音；例外'),
    'projet': ('pʁɔʒɛ', 'o 读 [ɔ]；例外'),
    'ville': ('vil', 'ill 读 [il]；例外'),
    'mille': ('mil', 'ill 读 [il]；例外'),
    'tranquille': ('tʁɑ̃kil', 'ill 读 [il]；例外'),
    'ouest': ('wɛst', 'ou 单独读 [w]；例外'),
    'huit': ('ɥit', 'h 不发音、ui 读 [ɥi]、t 发音；例外'),
    'appeler': ('aple', 'pp 后的 e 哑音；例外'),
    'effet': ('efɛ', 'ff 后的 e 哑音；例外'),
    'œil': ('œj', 'œil 整体读音；例外'),
    'noël': ('nɔɛl', 'ë 分读；例外'),
    'sens': ('sɑ̃s', '词尾 s 发音；例外'),
    'ours': ('uʁs', '词尾 s 发音；例外'),
    'mars': ('maʁs', '词尾 s 发音；例外'),
    'six': ('sis', '独立使用时读 [sis]；例外'),
    'dix': ('dis', '独立使用时读 [dis]；例外'),
    'blanc': ('blɑ̃', '词尾 c 静音；例外'),
    'banc': ('bɑ̃', '词尾 c 静音；例外'),
    'franc': ('fʁɑ̃', '词尾 c 静音；例外'),
    'estomac': ('ɛstoma', '词尾 c 静音；例外'),
    'tabac': ('taba', '词尾 c 静音；例外'),
    'photo': ('foto', 'o 在源文件中标注为 [o]；例外'),
    'est': ('ɛst', '词尾 st 发音；例外'),
    'but': ('byt', '词尾 t 发音；例外'),
    'net': ('nɛt', '词尾 t 发音；例外'),
    'sept': ('sɛt', '词尾 t 发音、p 静音；例外'),
}


def norm_ipa(ipa):
    """统一 IPA：g → ɡ（U+0261），NFC。"""
    return unicodedata.normalize('NFC', ipa).replace('g', 'ɡ')


def strip_ipa(ipa):
    """去掉方括号、句点和空格，用于比较。"""
    return re.sub(r'[\[\]\.\s]', '', norm_ipa(ipa))


def parse_source_line(line):
    """解析一行 french.txt，返回音素、F3 描述、规则列表、例词列表。"""
    fields = line.rstrip('\n').split('\t')
    if len(fields) != 4:
        raise ValueError(f'字段数不为 4：{line[:50]!r}')
    phoneme = norm_ipa(fields[0].strip('[] '))
    f2, f3, f4 = fields[1], fields[2], fields[3]

    # 依次扫描 <b>…</b>，收集拼法和紧随的半角括号条件
    rules = []
    pos = 0
    while True:
        m = BOLD_RE.search(f2, pos)
        if not m:
            break
        grapheme = unicodedata.normalize('NFC', m.group(1)).strip().lower()
        grapheme = grapheme.lstrip('-')
        rest = f2[m.end():]
        cond_m = re.match(r'\s*\(([^)]*)\)', rest)
        cond = cond_m.group(1).strip() if cond_m else None
        rules.append((grapheme, cond))
        pos = m.end()
        if cond_m:
            pos += cond_m.end()

    examples = []
    for part in BR_RE.split(f4):
        # 保留 <b> 内文字（整词被高亮时单词本身就在标签里）
        text = BOLD_RE.sub(r'\1', part).strip()
        if not text:
            continue
        m = re.match(r'^(.+?)\s*\[(.+?)\]', text)
        if not m:
            continue
        word = re.sub(r"[’'\-]", '', m.group(1)).strip().lower()
        examples.append((word, norm_ipa(m.group(2).strip()), phoneme))
    return phoneme, f3.strip(), rules, examples


def parse_source():
    with open(SOURCE_FILE, encoding='utf-8') as f:
        raw = f.read()
    phonemes, file_rules, file_examples = [], [], []
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        phoneme, desc, rules, examples = parse_source_line(line)
        phonemes.append({'ipa': phoneme, 'description': desc, 'source': 'french.txt',
                         'sort_order': len(phonemes)})
        for grapheme, cond in rules:
            file_rules.append({'grapheme': grapheme, 'phoneme': phoneme,
                               'condition_raw': cond})
        for word, ipa, phon in examples:
            file_examples.append({'word': word, 'ipa': ipa, 'phoneme': phon,
                                  'source_line': line_no})
    return raw, phonemes, file_rules, file_examples


def make_rule(phoneme, grapheme, condition, output_ipa, desc, priority, silent, source):
    return {
        'grapheme': grapheme, 'phoneme': phoneme, 'output_ipa': output_ipa,
        'condition': condition, 'condition_desc': desc, 'priority': priority,
        'is_silent': silent, 'source': source,
    }


def build_rules_from_source(file_rules):
    rules = []
    for rule in file_rules:
        phoneme, grapheme, cond = rule['phoneme'], rule['grapheme'], rule['condition_raw']
        key = f'[{phoneme}]'
        mapping = SOURCE_CONDITION_MAP.get(key)
        if mapping is None or grapheme not in mapping:
            raise ValueError(f'未识别的源规则映射：{key} {grapheme!r}')
        cond_table = mapping[grapheme]
        if cond not in cond_table:
            raise ValueError(f'未识别的源条件：{key} {grapheme!r} ({cond!r})')
        cond_key, cond_desc = cond_table[cond]
        if grapheme == 'tion':
            output = 'sjɔ̃'
        elif grapheme == 'oi':
            output = 'wa'
        else:
            output = phoneme
        priority = PRIORITY_OVERRIDES.get(
            (key, grapheme, cond_key),
            PRIORITY_OVERRIDES.get(
                (key, grapheme, 'always'), CONDITION_PRIORITY.get(cond_key, 10)))
        rules.append(make_rule(phoneme, grapheme, cond_key, output, cond_desc,
                               priority, 0, 'french.txt'))
    return rules


SOURCE_PHONEME_SUPPLEMENTS = [
    # (grapheme, 音素, 输出, 条件, 说明, 优先级)
    ('gn', '[ɲ]', 'ɲ', 'always', 'gn 发 [ɲ]', 30),
    ('gu', '[ɡ]', 'ɡ', 'before_a_o_u', 'gu 在 a, o, u 前，u 不发音', 30),
]


def build_supplement_rules():
    rules = [make_rule(phon, graph, cond, out, desc, prio, 0, 'supplement')
             for graph, phon, out, cond, desc, prio in SOURCE_PHONEME_SUPPLEMENTS]
    for grapheme, phon_key, output, cond, desc, priority, silent in SUPPLEMENT_RULES:
        rules.append(make_rule(phon_key.strip('[]') if phon_key else None, grapheme,
                               cond, output, desc, priority, silent, 'supplement'))
    # 单音节虚词的词尾 e 读 [ə]（如 le, ce, je）
    rules.append(make_rule('ə', 'e', 'word_in:e_final_words', 'ə',
                           '单音节虚词（le, ce, je…）', 30, 0, 'supplement'))
    return rules


def check_conditions(rules):
    for r in rules:
        cond = r['condition']
        if cond in VALID_CONDITIONS:
            continue
        if cond.startswith('word_in:') and cond.split(':', 1)[1] in WORD_LIST_CONDITIONS:
            continue
        raise ValueError(f'无效条件键：{cond}（规则 {r["grapheme"]}）')


def db_connect(path):
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def create_schema(conn):
    conn.executescript('''
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE phonemes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ipa TEXT NOT NULL UNIQUE,
            description TEXT,
            source TEXT NOT NULL,
            sort_order INTEGER
        );
        CREATE TABLE rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grapheme TEXT NOT NULL,
            phoneme_id INTEGER REFERENCES phonemes(id),
            output_ipa TEXT NOT NULL,
            condition TEXT NOT NULL DEFAULT 'always',
            condition_desc TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 10,
            is_silent INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL,
            UNIQUE(grapheme, output_ipa, condition, source)
        );
        CREATE TABLE exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            ipa TEXT NOT NULL,
            note TEXT
        );
        CREATE TABLE word_lists (
            list_name TEXT NOT NULL,
            word TEXT NOT NULL,
            PRIMARY KEY (list_name, word)
        );
        CREATE TABLE examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            ipa TEXT NOT NULL,
            phoneme_ipa TEXT NOT NULL,
            source_line INTEGER
        );
        CREATE INDEX idx_rules_grapheme ON rules(grapheme);
    ''')


def write_database(phonemes, rules, examples, raw):
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DB_TMP):
        os.remove(DB_TMP)
    conn = db_connect(DB_TMP)
    try:
        create_schema(conn)
        phoneme_ids = {}
        for p in phonemes:
            cur = conn.execute(
                'INSERT INTO phonemes (ipa, description, source, sort_order) VALUES (?,?,?,?)',
                (p['ipa'], p['description'], p['source'], p['sort_order']))
            phoneme_ids[p['ipa']] = cur.lastrowid
        for r in rules:
            conn.execute(
                '''INSERT INTO rules
                   (grapheme, phoneme_id, output_ipa, condition, condition_desc,
                    priority, is_silent, source)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (r['grapheme'], phoneme_ids.get(r['phoneme']), r['output_ipa'],
                 r['condition'], r['condition_desc'], r['priority'],
                 1 if r['is_silent'] else 0, r['source']))
        for word, (ipa, note) in EXCEPTIONS.items():
            conn.execute('INSERT INTO exceptions (word, ipa, note) VALUES (?,?,?)',
                         (word, norm_ipa(ipa), note))
        for list_name, words in WORD_LISTS.items():
            conn.executemany('INSERT INTO word_lists (list_name, word) VALUES (?,?)',
                             [(list_name, w) for w in sorted(words)])
        for e in examples:
            conn.execute(
                'INSERT INTO examples (word, ipa, phoneme_ipa, source_line) VALUES (?,?,?,?)',
                (e['word'], e['ipa'], e['phoneme'], e['source_line']))
        meta = {
            'build_version': BUILD_VERSION,
            'built_at': datetime.now().isoformat(timespec='seconds'),
            'source_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'phonemes': str(len(phonemes)),
            'source_rules': str(sum(1 for r in rules if r['source'] == 'french.txt')),
            'supplement_rules': str(sum(1 for r in rules if r['source'] == 'supplement')),
            'examples': str(len(examples)),
        }
        conn.executemany('INSERT INTO meta (key, value) VALUES (?,?)', meta.items())
        conn.commit()
    finally:
        conn.close()
    os.replace(DB_TMP, DB_FILE)


def verify(conn):
    phoneme_count = conn.execute('SELECT COUNT(*) FROM phonemes').fetchone()[0]
    source_rules = conn.execute(
        "SELECT COUNT(*) FROM rules WHERE source='french.txt'").fetchone()[0]
    example_count = conn.execute('SELECT COUNT(*) FROM examples').fetchone()[0]
    problems = []
    if phoneme_count != 36:
        problems.append(f'音素数应为 36，实际 {phoneme_count}')
    if source_rules != 103:
        problems.append(f'源规则数应为 103，实际 {source_rules}')
    if example_count != 119:
        problems.append(f'例词数应为 119，实际 {example_count}')
    return problems


def run_regression():
    from pronounce_engine import Pronouncer
    p = Pronouncer()
    p.load(DB_FILE)
    wrong = []
    for word, expected in p.iter_examples():
        actual = p.pronounce(word)['ipa']
        if strip_ipa(actual) != strip_ipa(expected):
            wrong.append((word, expected, actual))
    return wrong


def print_regression(wrong):
    total = 119
    if not wrong:
        print(f'F4 回归：{total}/{total} 全部通过')
        return
    print(f'F4 回归：{total - len(wrong)}/{total} 通过，未命中 {len(wrong)} 条：')
    for word, expected, actual in wrong:
        print(f'  {word:14s} 期望 [{expected}]  实际 [{actual}]')


def main():
    parser = argparse.ArgumentParser(description='构建法语拼读规则数据库')
    parser.add_argument('--verify', action='store_true', help='仅校验现有数据库并回归')
    parser.add_argument('--stats', action='store_true', help='只打印源文件解析统计')
    parser.add_argument('--skip-regression', action='store_true', help='构建时不运行回归')
    args = parser.parse_args()

    if args.verify:
        if not os.path.exists(DB_FILE):
            print(f'数据库不存在：{DB_FILE}')
            return 1
        conn = db_connect(DB_FILE)
        problems = verify(conn)
        conn.close()
        if problems:
            print('校验失败：')
            for p in problems:
                print('  -', p)
            return 1
        print('数据库结构校验通过')
        wrong = run_regression()
        print_regression(wrong)
        return 0 if not wrong else 1

    raw, phonemes, file_rules, file_examples = parse_source()
    rules = build_rules_from_source(file_rules)
    rules.extend(build_supplement_rules())
    check_conditions(rules)
    src = sum(1 for r in rules if r['source'] == 'french.txt')
    sup = sum(1 for r in rules if r['source'] == 'supplement')
    print(f'解析统计：音素 {len(phonemes)} · 源规则 {src} · 补充规则 {sup} · 例词 {len(file_examples)}')
    if args.stats:
        return 0

    write_database(phonemes, rules, file_examples, raw)
    print(f'已生成 {DB_FILE}')
    conn = db_connect(DB_FILE)
    problems = verify(conn)
    conn.close()
    if problems:
        print('校验失败：')
        for p in problems:
            print('  -', p)
        return 1
    print('数据库结构校验通过')
    if not args.skip_regression:
        print_regression(run_regression())
    return 0


if __name__ == '__main__':
    sys.exit(main())
