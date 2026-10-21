# 法语拼读功能设计文档

> 文档版本：1.0
> 创建日期：2026-10-21
> 适用项目：`french-tts`（法语发音助手）
> 状态：已审核通过，作为本功能的原始设计文档；后续功能调整、新增或修改均需同步更新本文档并在「变更日志」中记录。

---

## 1. 功能概述

### 1.1 需求来源

用户希望在现有的法语 TTS 工具中加入「拼读」能力：

- 输入一个法语单词（或短语），点击「拼读」按钮，应用根据本地整理的拼读规则库给出该词的音标；
- 同时按单词中字母组合从左到右的顺序，列出每一条被应用的拼读规则，说明该字母组合发什么音、应用了哪条规则；
- 规则数据来自 `docs/french.txt`，但不能在运行时直接查询该原始文件（含 HTML 标记、末行无换行等），必须预先整理为可快速查询的结构化数据（SQLite 数据库）；
- 按钮区调整为 6 个按钮：`语音`（原「生成语音」改名）、`拼读`（新增，位于第二位）、`forvo`、`Dict`、`wdRef`、`frDic`，6 个按钮颜色明显不同、易于区分；
- 拼读结果上方居中显示单词音标，下方以引用块样式展示应用的拼读规则，视觉上与现有界面协调美观；
- 不修改 `zh_en/` 子项目目录中的任何内容。

### 1.2 已确认的设计决策

| 决策项 | 结论 |
|---|---|
| 规则范围 | 以 `french.txt` 的 103 条规则为骨干，补充源文件缺失的必要规则（静音词尾、哑音 e、h 不发音、x→[ks]/[gz]、œ、-ent、ill 系列等），并建立例外词表。界面标注规则来源（`french.txt` / `补充` / `例外词`）。 |
| 规则卡片内容 | 只显示「字母组合 → 音标」、该音素的全部拼法、触发条件与来源；**不展示** F3 发音方法描述（F3 仍解析入库，以便以后启用）。 |
| 输入范围 | 支持单词与短语。短语按空格拆成词，词内再按撇号/连字符拆分分析；每个词独立显示音标与规则分解。 |
| 拼读按钮颜色 | 洋红 `#d63384`，与现有蓝、青、橙、紫、墨绿明显区分。 |

### 1.3 验收标准

1. 输入 `chat` 点击「拼读」，显示居中大字 `[ʃa]`，下方依次列出 `ch → [ʃ]`、`a → [a]`、`t → 静音` 三张规则卡片。
2. 输入 `bonjour tout le monde` 时逐词展示音标与规则卡片。
3. `temps`、`fille`、`maison`、`avec`、`les` 等演示词输出符合标准法语。
4. 6 个按钮顺序、颜色、移动端布局正常，`语音` 按钮原功能不受影响。
5. `docs/french.txt` 的 119 条例词回归全部通过（源文件已知错误除外，见 §9.3）。
6. 数据库缺失时拼读接口返回 503 并给出构建提示，TTS 功能不受影响。

---

## 2. 总体架构

```
构建期：
docs/french.txt ─┐
补充规则/例外词（build_pronounce_db.py 内常量）─┼→ build_pronounce_db.py → data/pronounce.db
                                                                    │
运行期：                                                             ▼
app.py 启动 → Pronouncer.load(data/pronounce.db)（一次性载入内存）
浏览器 ──POST /pronounce {text}──→ Pronouncer.pronounce(text) ──→ JSON
   └─ 渲染：居中大字音标 + 引用块式规则卡片
```

- **构建期**：`build_pronounce_db.py` 解析源文件、合并补充规则与例外词、校验数据一致性，原子生成 `data/pronounce.db`。
- **运行期**：`app.py` 启动时通过 `pronounce_engine.Pronouncer` 把规则、例外词载入内存字典；每次请求只在内存中做最左最长匹配，查询耗时为毫秒级。数据库是持久化产物与唯一事实源，原始 `french.txt` 不参与运行时查询。
- **数据库不入版本库**（`data/*.db` 已加入 `.gitignore`），部署流程中必须执行构建脚本（见部署文档）。

### 2.1 文件变更清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `docs/pronunciation-design.md` | 新增 | 本文档 |
| `docs/deployment-debian12.md` | 新增 | Debian 12 部署文档 |
| `build_pronounce_db.py` | 新增 | 解析源文件、补充规则、例外词、建库、`--verify` 回归 |
| `pronounce_engine.py` | 新增 | 规范化、切词、规则匹配、条件判定、结果组装 |
| `data/pronounce.db` | 生成产物 | 由构建脚本生成，不入版本库 |
| `.gitignore` | 修改 | 追加 `data/*.db`、`data/*.db.tmp` |
| `app.py` | 修改 | 加载拼读数据库；新增 `POST /pronounce` |
| `templates/index.html` | 修改 | 6 按钮配色布局、拼读结果面板、前端逻辑 |
| `tests/test_pronounce_engine.py` | 新增 | 引擎单元测试 |
| `tests/test_pronounce_api.py` | 新增 | API 测试 |
| `tests/test_regression_f4.py` | 新增 | 源文件例词自动回归 |
| `requirements.txt` | 修改 | 补充 `python-dotenv`（`app.py` 已 import 但缺失，属既有缺陷修复） |
| `docs/french.txt` | 纳入版本库 | 文件内容不修改 |

---

## 3. 数据源解析

### 3.1 `docs/french.txt` 格式

- UTF-8 无 BOM，36 行（最后一行无换行符），TAB 分隔 4 个字段。
- 一行代表**一个法语音素**（不是单词），共 36 个音素：16 个元音 + 3 个半元音 + 17 个辅音。

| 字段 | 含义 | 示例 |
|---|---|---|
| F1 | 音标 | `[ʃ]` |
| F2 | 拼写规则，逗号分隔，可带半角括号条件 | `ch, sch` |
| F3 | 发音口型/方法中文描述（无 HTML） | `清硬腭龈摩擦音…` |
| F4 | 例词，`<br>` 分隔 | `chat [ʃa] (猫)` |

- F2 拼法以 `<b style="color:#d9534f">…</b>` 包裹，括号内为条件，如 `c(在 a, o, u 前)`、`-er(词尾)`。
- F4 每条例词 = 高亮拼法 + `[音标]` + `(中文释义)`。
- 统计：F2 规则 **103** 条，F4 例词 **119** 条。
- IPA 特殊点：`[g]` 使用 IPA 脚本体 `ɡ`(U+0261)；`œ`、`ɑ̃/ɛ̃/ɔ̃/œ̃` 等字符需原样保留。

### 3.2 解析规则

1. **F2 规则拆分**：不能按逗号直接拆分——括号内含有逗号（如「在 a, o, u 前」）。采用扫描器：先按 `<b>…</b>` 切出拼法与尾随括号条件，再把多个 `<b>` 段按顺序识别。
2. **条件文本 → 结构化条件键**：依据「音素 + 拼法 + 括号原文」映射（见 §6.2）。映射不到的规则构建失败（防止静默丢失规则）。
3. **F4 例词抽取**：`<br>` 拆分；去除 `<b>` 高亮标签后按 `单词 [音标] (释义)` 正则提取单词与音标，入库作为回归验证集。
4. **特殊规则**：`-tion` 条件原位标记为「中的 t」，解析时记录整段拼法 `tion` 输出 `sjɔ̃`，避免与 `t`、`on` 冲突。

---

## 4. 数据库设计（SQLite）

数据库路径：`data/pronounce.db`。

```sql
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL              -- build_version / source_sha256 / built_stats
);

CREATE TABLE phonemes (              -- 36 张音素卡
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ipa TEXT NOT NULL UNIQUE,        -- 归一化 IPA（g→ɡ）
    description TEXT,                -- F3 原文（备用，当前界面不展示）
    source TEXT NOT NULL,            -- 'french.txt' | 'supplement'
    sort_order INTEGER
);

CREATE TABLE rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grapheme TEXT NOT NULL,          -- 归一化拼法，如 'ch'、'c'、'tion'、'ill'
    phoneme_id INTEGER REFERENCES phonemes(id),   -- 所属音素卡；静音规则为 NULL
    output_ipa TEXT NOT NULL,        -- 实际输出，如 'ʃ'、'ks'、'sjɔ̃'、'ij'；静音为 ''
    condition TEXT NOT NULL DEFAULT 'always',
    condition_desc TEXT NOT NULL DEFAULT '',      -- 中文说明，用于界面
    priority INTEGER NOT NULL DEFAULT 10,         -- 越大越优先
    is_silent INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,            -- 'french.txt' | 'supplement'
    UNIQUE(grapheme, output_ipa, condition, source)
);

CREATE TABLE exceptions (            -- 整词例外
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,       -- 归一化小写
    ipa TEXT NOT NULL,
    note TEXT
);

CREATE TABLE examples (              -- 源文件 F4 例词，用于回归
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    ipa TEXT NOT NULL,               -- 去掉句点的音标
    phoneme_ipa TEXT NOT NULL,
    source_line INTEGER
);
```

- 构建采用「先写 `data/pronounce.db.tmp`，成功后再原子替换」的方式，避免半成品数据库。
- `--verify` 校验：音素数 36、源规则数 103、例词数 119、未知条件键为 0，并运行 §9 的回归。
- 例外词表与补充规则在构建脚本中以常量维护，每次构建写入数据库；运行时一切以数据库为准。

---

## 5. 规则引擎设计（`pronounce_engine.py`）

### 5.1 规范化

- Unicode NFC → 小写 → 去首尾空白。
- `oeu` 视作 `œu` 别名；保留单独的 `œ`；不把一般 `oe` 映射为 `œ`。
- IPA 统一：`g`(U+0067) → `ɡ`(U+0261)；比较时忽略 `.`、空格、方括号。
- 输入校验：空串、纯数字/符号、长度 > 200 返回 400。

### 5.2 切词

- 按空白拆成词；词内按 `'`、`’`、`-` 拆成片段，分隔符作为静音片段展示（`l'école` → `l` + `'` + `école`）。
- 每个片段独立匹配；词级音标为各片段输出拼接；短语音标按词用空格分隔后展示。

### 5.3 匹配算法

1. **预扫描**：标记候选静音位置（词尾 `e/s/t/d/x/z/p`、`-ent` 词表、`h`、`mn` 中的 m、词尾 `c` 等），供后续「下一个字母是否发音」判断使用。
2. **最左最长匹配**：从位置 i 出发，按「组合长度降序 → priority 降序」取候选规则，逐条验证条件；第一条通过即采用，输出该规则的 IPA 并前进到 `i + len(grapheme)`。
3. **回退**：长组合条件不满足时自动尝试更短组合（如 `an` 不构成鼻化时回退为 `a` + `n`）。
4. **未识别**：无规则可匹配的字符输出 `?`，状态 `unknown`，整体 `complete=false`，接口仍返回 200。
5. **例外词**：整词命中例外词表时直接返回例外音标，规则区展示「例外词，整体发音 […]」，不做拆解。
6. **优先示例**：`ill/aill/eill/ouill` > `il`；`tion` > `t`；`qu/gu` > `u`；`ch` > `c`；`eau` > `au`。

### 5.4 条件判定键

| 条件键 | 含义 |
|---|---|
| `always` | 无条件 |
| `word_final` | 位于词末 |
| `word_initial` | 位于词首 |
| `before_vowel` | 后接任意元音字母 |
| `before_pronounced_vowel` | 后接发音元音（排除会构成鼻化的 n/m 等） |
| `before_e_i_y` | 后接 e/i/y（含带符变体） |
| `before_a_o_u` | 后接 a/o/u（含带符变体） |
| `before_r` | 后接 r |
| `before_z` | 后接 z 或后接 s 且 s 位于元音之间 |
| `before_z_or_t` | 后接 z 或 t |
| `before_pronounced_consonant` | 后接发音辅音 |
| `before_pronounced_consonant_except_z` | 后接发音辅音，且不为 z |
| `open_final_or_before_z_t` | 词尾开音节，或在 [z]、[t] 前（œu 的 [ø]） |
| `o_final` | 到词尾全部静音，或后接 z / 元音间的 s |
| `i_between_vowels` | i 位于两个元音之间（→[j]） |
| `y_glide` | y 后接元音，或 y 后接 e + 元音（→[j]） |
| `intervocalic` | 前后字母均为元音（s→[z]） |
| `closed_syllable` | 到下一个元音之间至少有一个发音辅音；音节边界遇词尾或下一鼻化元音截断 |
| `open_syllable` | 到下一个元音之间没有发音辅音 |
| `nasal_context` | 后无元音；排除同字母双写，以及 n/m 后接元音的情况 |
| `before_double_consonant` | 后接双写辅音 |
| `after_vowel` | 前接元音字母 |
| `word_final_et` | 词尾为 `et`（连词 `et` 除外） |
| `schwa_context` | 单词的第一个元音，且后面还有可发音元音 |
| `e_silent` | 词尾 e 且不是 `le/ce/je...` 等虚词 |
| `silent_final_x` | 词尾 -eux/-aux 的 x 不发音 |
| `ends_with_ent` | 动词变位词尾 -ent |
| `word_in:{列表}` | 必须属于数据库 `word_lists` 中的指定词表 |

### 5.5 手工推演（验收样例）

| 输入 | 分解（左→右） | 音标 | 关键规则 |
|---|---|---|---|
| chat | ch→[ʃ] · a→[a] · t→静音 | [ʃa] | ch；词尾 t 静音 |
| marché | m · a · r · ch→[ʃ] · é→[e] | [maʁʃe] | é→[e] |
| maison | m · ai→[ɛ] · s→[z] · on→[ɔ̃] | [mɛzɔ̃] | s 元音间浊化 |
| porte | p · o→[ɔ] · r · t · e→静音 | [pɔʁt] | o 闭音节；词尾 e 静音 |
| temps | t · em→[ɑ̃] · p→静音 · s→静音 | [tɑ̃] | 鼻化；词尾 p/s 静音 |
| fille | f · ill→[ij] · e→静音 | [fij] | ill 规则 |
| avec | a · v · e→[ɛ] · c→[k] | [avɛk] | 词尾 c 发音 |
| bonjour | b · on→[ɔ̃] · j→[ʒ] · ou→[u] · r | [bɔ̃ʒuʁ] | 鼻化 |
| les | l · es→[e] | [le] | 虚词 -es 规则 |
| mer | 例外词表 | [mɛʁ] | -er 词尾规则例外 |

---

## 6. 规则映射

### 6.1 源规则条件映射（french.txt → 条件键）

| 音素 | 源拼法 / 条件 | 条件键 |
|---|---|---|
| [e] | `é`；`-er/-ez/-ed`(词尾) | `always` / `word_final` |
| [e] | `-es`(单音节虚词) | `word_final` + `word_in` 虚词表 |
| [ɛ] | `è/ê/ë/ei/ai/aî` | `always` |
| [ɛ] | `e`(闭音节/双辅音前/-et词尾) | `closed_syllable` / `before_double_consonant` / `word_final_et` |
| [ɑ] | `-as/-az`(词尾) | `word_final` |
| [ɔ] | `o`(在发音辅音前) | `closed_syllable` |
| [ɔ] | `au`(仅在 r 前) | `before_r` |
| [o] | `ô/au/eau`；`o`(词尾或 [z] 前) | `always` / `word_final` / `before_z` |
| [ø] | `eu`；`œu`(词尾开音节或在 [z][t] 前) | `always` / `open_syllable` / `before_z_or_t` |
| [œ] | `eu/œu`(除 [z] 外发音辅音前) | `before_pronounced_consonant` |
| [ə] | `e`(单音节词/词首开音节) | `schwa_context` |
| [ɑ̃] | `an/am/en/em` | `nasal_context` |
| [ɛ̃] | `in/im/ain/aim/ein/eim/yn/ym` | `nasal_context` |
| [ɔ̃] | `on/om` | `nasal_context` |
| [œ̃] | `un/um` | `nasal_context` |
| [j] | `y`；`i`(后接元音)；`ill`(元音后)；`-il`(词尾元音后) | `always` / `before_pronounced_vowel` / `after_vowel` + `word_final` |
| [w] | `ou`(后接元音)；`oi`(固定 [wa]) | `before_pronounced_vowel` / `always`（输出 `wa`） |
| [ɥ] | `u`(后接发音元音) | `before_pronounced_vowel` |
| [k] | `k/qu/cc`；`c`(a,o,u 前)；`ch`(希腊词源) | `always` / `before_a_o_u` / `word_in` 希腊词表 |
| [g] | `g`(a,o,u 前)；`gu`(e,i 前) | `before_a_o_u` / `before_e_i` |
| [s] | `s`(词首或辅音旁)/`ss`/`-tion`(中的 t) | `word_initial` / `always` / `always`（`tion`→`sjɔ̃`） |
| [s] | `c`(e,i,y 前)/`ç`(a,o,u 前) | `before_e_i_y` / `always` |
| [z] | `z`；`s`(元音之间)；`x`(某些词) | `always` / `intervocalic` / `word_in` 词表 |
| [ʃ] | `ch`/`sch` | `always` |
| [ʒ] | `j`；`g`(e,i,y 前)；`ge`(a,o 前保音) | `always` / `before_e_i_y` / `before_a_o` |
| 其余辅音 | `p/b/t/d/f/v/l/r/m/n` 及双写、`ph`、`th`、`gn` | `always` |

实现细节（最终版）：

- `-es`（虚词）、`ch`（希腊词源）映射为 `word_in:final_es_words` / `word_in:greek_ch_words`。
- `oi` 输出整段 `wa`，由 [w] 卡片的规则承担。
- `-et` 的实现：词尾 `et` 统一读 `[ɛ]`，连词 `et` 进入例外词表（读 `[e]`）。
- `y`→[j] 需要 y 后接元音（或 y + e + 元音），词尾 y 走 `[i]`；`i`→[j] 仅限两个元音之间。
- `gn`→[ɲ]、`gu`(a/o/u 前)→[ɡ] 作为补充规则加入（源文件只给了 gn 的独立卡片与 gu 在 e/i 前）。
- `eur`（词尾或后接发音辅音）整段输出 `œʁ`，用于处理 eu 在 r 前读 [œ] 的情形。

说明：源文件括号中的「(在 a, o, u 前)」等只是**该拼法的一种情况**，例如 `c` 还有默认 `[k]` 情形；因此这些拼法的默认读音作为补充规则加入。

### 6.2 补充规则（来源 `supplement`）

共 42 条（构建时统计）。要点：

- **静音类**：词尾 `e`（虚词白名单 `le/ce/je/me/te/se/que/ne/de` 除外）、词尾 `es`（虚词 `-es` 先命中 [e] 规则）、词尾 `s/t/d/z/p`、词尾静音辅音簇（如 `temps` 的 p）、`-ent`（动词变位）、单独的 `h`、`mn` 中的 m（与双写 `mm` 同为 [m] 展示）、部分词尾 `c`（`blanc/banc/franc/tronc/suc/duc` 词表）、`-eux/-aux` 的 x。
- **发音类**：`x → [ks]`（`ex-` + 元音词表 → `[gz]`）；`œ → [œ]`；`ill → [ij]`、元音后 `ill → [j]`（`ville/mille/tranquille` 例外）；`ail/eil/euil` 词尾 → `[aj]/[ɛj]/[œj]`；`aill/eill/ouill/euill` → 对应半元音 + `[j]`；`ien → [jɛ̃]`；`oin → [wɛ̃]`；`ay/ey → [ɛj]`；`oy → [waj]`；`cc` + e/i → `[ks]`；`geons → [ʒɔ̃]`；`ph → [f]`；`eur → [œʁ]`；`g` 默认 `[ɡ]`、`c` 默认 `[k]`、`w → [v]`；`o` 开音节 → `[o]`；`-et` → `[ɛ]`；`gn → [ɲ]`、`gu`(a/o/u 前) → `[ɡ]`；单音节虚词词尾 `e → [ə]`。
- **匹配顺序**：先按组合长度降序，再按优先级降序。静音规则优先级低于语境规则、高于默认读音；希腊词源的 `ch`(50) 高于普通 `ch`(40)，且仅在词表命中时生效。

### 6.3 例外词表

初始集合（共 39 词，可随回归结果追加，追加时注明原因）：

`hier`、`mer`、`fer`、`cher`、`hiver`、`femme`、`monsieur`、`mademoiselle`、`fils`、`pays`、`pied`、`maïs`、`projet`、`ville`、`mille`、`tranquille`、`ouest`、`huit`、`appeler`、`effet`、`œil`、`noël`、`sens`、`ours`、`mars`、`six`、`dix`、`blanc`、`banc`、`franc`、`estomac`、`tabac`、`est`、`but`、`net`、`sept`、`photo`、`merci`、`et`。

---

## 7. API 设计

### 7.1 `POST /pronounce`

请求：

```json
{ "text": "chat" }
```

响应（200）：

```json
{
  "text": "chat",
  "ipa": "ʃa",
  "ipa_display": "[ʃa]",
  "complete": true,
  "words": [
    {
      "word": "chat",
      "display": "chat",
      "ipa": "[ʃa]",
      "exception": null,
      "segments": [
        {
          "grapheme": "ch",
          "ipa": "ʃ",
          "display": "[ʃ]",
          "status": "matched",
          "silent": false,
          "spellings": ["ch", "sch"],
          "condition_desc": "",
          "source": "french.txt",
          "phoneme": "ʃ",
          "rule_id": 42
        },
        {
          "grapheme": "a",
          "ipa": "a",
          "display": "[a]",
          "status": "matched",
          "silent": false,
          "spellings": ["a", "à"],
          "condition_desc": "",
          "source": "french.txt",
          "phoneme": "a",
          "rule_id": 7
        },
        {
          "grapheme": "t",
          "ipa": "",
          "display": "静音",
          "status": "silent",
          "silent": true,
          "spellings": [],
          "condition_desc": "词尾辅音不发音",
          "source": "supplement",
          "phoneme": null,
          "rule_id": 130
        }
      ]
    }
  ],
  "stats": { "rules_applied": 3, "silent": 1, "unknown": 0 }
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `ipa` / `ipa_display` | 整句音标（不含方括号 / 含方括号） |
| `complete` | 是否所有字符均被识别且无静音歧义 |
| `words[].exception` | 命中例外词时为说明文字，否则 `null` |
| `segments[].status` | `matched` / `silent` / `unknown` / `separator`（撇号、连字符） |
| `segments[].spellings` | 该音素卡的全部拼法（来自 F2） |
| `segments[].condition_desc` | 触发条件的中文说明，无条件时为空串 |
| `segments[].source` | `french.txt` / `supplement` / `exception` |

### 7.2 错误响应

| 状态码 | 场景 |
|---|---|
| 400 | 空输入、纯数字/符号、含非法字符、长度超过 200 |
| 503 | 拼读数据库未构建（提示执行 `python3 build_pronounce_db.py`） |
| 500 | 其它内部错误 |

数据库缺失仅在启动时告警，不影响 `/generate` 等原有功能。

---

## 8. 前端设计

### 8.1 按钮区

HTML（`templates/index.html`）：

```html
<div class="btn-row">
    <button id="generateBtn" class="btn-generate" onclick="generateAudio()">语音</button>
    <button id="pronounceBtn" class="btn-ext btn-pronounce" onclick="pronounceText()">拼读</button>
    <button class="btn-ext btn-forvo" onclick="openForvo()">forvo</button>
    <button class="btn-ext btn-dict" onclick="openDict()">Dict</button>
    <button class="btn-ext btn-wd" onclick="openWordReference()">wdRef</button>
    <button class="btn-ext btn-frdic" onclick="openFrDic()">frDic</button>
</div>
```

布局：`.btn-row { display:flex; gap:6px }`，`.btn-generate { flex:1.4 }`，`.btn-ext { flex:1 }`；窄屏用 `clamp()` 控制字号，保证 375px 宽度不溢出。

| 按钮 | 颜色 | hover |
|---|---|---|
| 语音 | `#007bff` 蓝 | 现有 |
| 拼读 | `#d63384` 洋红 | `#b02a6c` |
| forvo | `#17a2b8` 青 | `#138496` |
| Dict | `#fd7e14` 橙 | `#e46a05` |
| wdRef | `#6f42c1` 紫 | `#59359a` |
| frDic | `#0f766e` 墨绿 | `#0d5f58` |

### 8.2 拼读结果面板

位置：按钮行下方、播放器上方，默认隐藏。

- 顶部：单词（18px 灰，居中）；
- 音标：32px 加粗洋红，居中，`[ʃa]` 形式；
- 规则卡片：引用块样式——左侧 4px 洋红色条、`#fdf2f8` 浅洋红底、圆角 `0 8px 8px 0`，内容为：
  - 第一行：`ch → [ʃ]`（组合与音标加粗）；
  - 第二行：`拼写规则：ch, sch`；
  - 第三行：触发条件（如「后接元音」）；
  - 第四行：`来源：french.txt · [ʃ] 音素卡`。
- 静音片段卡片：灰色左边条（`#adb5bd`）与 `#f8f9fa` 底部，显示 `t → 静音`。
- 未识别片段：琥珀色卡片。
- 例外词：显示例外说明替代规则卡片。
- 短语：逐词显示「词 + 居中音标 + 该词规则卡片」，词间留白。
- 音标使用字体 `"DejaVu Sans", "Noto Sans", sans-serif`，保证 IPA 字符显示。

### 8.3 前端逻辑

`pronounceText()`：读取输入 → 空输入 alert → 按钮禁用并显示「查询中...」→ `fetch('/pronounce', POST)` → 成功使用 DOM API（`textContent`）构建结果，避免 XSS → 失败在面板内展示错误提示 → 恢复按钮。点击面板外其它按钮不清空结果，重新查询时替换。

---

## 9. 验证方案

### 9.1 构建校验

`python3 build_pronounce_db.py --verify`：音素 36、源规则 103、例词 119、未知条件 0，且 F4 回归通过。

### 9.2 自动回归

对 119 条 F4 例词逐一比对本引擎输出与源文件音标（忽略 `.`、空格、`ɡ/g` 差异），目标 119/119。未命中项：优先修规则，确属源文件错误或不可推导的例外词则入例外词表并在本文档记录。

**实现结果（2026-10-21）**：`python3 build_pronounce_db.py --verify` → `F4 回归：119/119 全部通过`。

### 9.3 源文件已知错误

| 词 | 源文件标注 | 标准法语 | 处理 |
|---|---|---|---|
| `mer`（[ɛ] 卡） | 词条 `[mɛʁ]` 正确，但被列为 `-er`→[e] 的例证 | `-er` 规则并不适用此词 | 归入例外词表 `mer [mɛʁ]` |
| `pied`（[e] 卡） | 例词标为 `pied [pje]`，但 pied 并不属于 `é` 规则 | 读音正确；只是规则归类牵强 | 归入例外词表 `pied [pje]` |
| `photo`（[o] 卡） | 标注 `[fo.to]`，首音节 o 在闭音节中通常为 [ɔ] | 标准 `[fɔto]`；源标注与自身“o 在发音辅音前读 [ɔ]”规则矛盾 | 依源文件标注，列入例外词表 `photo [foto]` |
| `hier`（[j] 卡） | 标注 `[jɛʁ]`；按规则推导为 `[ijɛʁ]`（i 在两个元音间） | 标准 `[jɛʁ]` | 归入例外词表 |
| `merci`（[ɛ] 卡） | 标注 `[mɛʁ.si]`；规则推导为 `[məʁsi]`（e 首音节弱化为 [ə]） | 标准 `[mɛʁsi]` | 归入例外词表 |
| `projet`（[ɛ] 卡） | 标注 `[pʁɔ.ʒɛ]`；规则推导为 `[pʁɔʒe]`（-et 规则与 o 规则） | 标准 `[pʁɔʒɛ]` | 归入例外词表 |
| `maïs`（[i] 卡） | 标注 `[ma.is]`；规则推导会静音词尾 s | 标准 `[mais]` | 归入例外词表（并记录词尾 s 发音） |
| `pâte` | 标注 `[pɑt]`（â→[ɑ] 卡片标准）；口语常并入 [a] | 两种均可 | 按源文件输出 [pɑt] |
| 其他回归暴露项 | — | — | 已在例外词表与 §6.3 记录 |

### 9.4 测试清单

- 引擎单测（`tests/test_pronounce_engine.py`）：§5.5 十个推演词；`café/ce/garçon/guide/gare/poisson/nation/rose/yeux/oiseau/château/sœur`；静音边界 `vous/grand/grande/parlent/deux/huit/pomme/anneau`；例外词；`l'école` 短语；`CHAT` 大小写；规则分段字段；未知字符。
- 回归测试（`tests/test_regression_f4.py`）：119 条例词全部一致。
- API 测试（`tests/test_pronounce_api.py`，Azure SDK 用桩模块替代）：成功响应、短语、空输入/非法字符/超长 400、数据库缺失 503、GET 405、首页包含「拼读」与「语音」。
- 端到端（jsdom 驱动真实页面）：按钮顺序与数量、`chat`/`temps`/`bonjour tout le monde`/`femme`/`l'école` 渲染、按钮状态复位。
- 全部测试：`python3 -m unittest discover -s tests` → 19 项通过。

---

## 10. 已知限制

- 不做联诵、连读、h aspiré 与跨词音变。
- 静音 `-ent` 依赖动词变位词表，而非词性分析。
- 例外词表为闭合集合，未收录的例外词会按规则推导（界面展示推导依据）。
- 音标不输出音节分隔点；`château` 按源文件的 â→[ɑ] 输出 `[ʃɑto]`。
- 双写辅音在界面中合并为一条（如 `mm → [m]`），不展示“前一个字母静音”的细节。
- 词尾静音簇（`temps` 的 p）通过“其后字母全部静音”的启发式推导。
- 源文件个别标注与标准法语不一致时，以例外词表修正并在 §9.3 记录。
- F3 发音方法当前不展示，已入库以备扩展。
- 联诵、h aspiré 等跨词现象不处理：`les amis` 按 `[le‿ami]` 的逐词音标显示，不做联诵替换。

---

## 11. 变更日志

| 日期 | 版本 | 变更内容 |
|---|---|---|
| 2026-10-21 | 1.0 | 初始设计：拼读按钮、SQLite 规则库、规则引擎、API、前端面板与验证方案。 |
| 2026-10-21 | 1.1 | 实现落地：条件键最终清单（`o_final`/`i_between_vowels`/`y_glide` 等）、补充规则 42 条、例外词 39 词、F4 回归 119/119、测试 19 项通过；记录源文件与规则冲突的处理方式；部署文档 `deployment-debian12.md` 完成。 |
