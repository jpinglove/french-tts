# -*- coding: utf-8 -*-
import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from deep_translator import GoogleTranslator

app = Flask(__name__)

# ==================== 配置区 ====================
DB_FILE = os.path.join(app.root_path, 'history.db')
# ===============================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zh_text TEXT NOT NULL,
            en_text TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/translate', methods=['POST'])
def translate():
    data = request.json
    zh_text = data.get('text', '').strip()
    if not zh_text:
        return jsonify({'error': '要翻译的文本不能为空'}), 400

    try:
        # 调用 python 的 deep-translator 库进行稳定翻译
        en_text = GoogleTranslator(source='zh-CN', target='en').translate(zh_text)
        
        # 存入数据库
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO translations (zh_text, en_text) VALUES (?, ?)', (zh_text, en_text))
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'id': record_id,
            'zh_text': zh_text,
            'en_text': en_text
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/history', methods=['GET'])
def get_history():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # 倒序排列，获取所有记录
    cursor.execute('SELECT id, zh_text, en_text, created_at FROM translations ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    
    history_list = []
    for row in rows:
        history_list.append({
            'id': row[0],
            'zh_text': row[1],
            'en_text': row[2],
            'created_at': row[3]
        })
    return jsonify(history_list)

@app.route('/history/<int:record_id>', methods=['DELETE'])
def delete_history(record_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM translations WHERE id = ?', (record_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # 注意：独立运行时用 5001 端口，避免和法语项目冲突
    app.run(host='0.0.0.0', port=5001, debug=True)