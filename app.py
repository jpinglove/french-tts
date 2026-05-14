# -*- coding: utf-8 -*-
import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
import azure.cognitiveservices.speech as speechsdk

app = Flask(__name__)

# ==================== 配置区 ====================
from dotenv import load_dotenv
load_dotenv()
speech_key = os.getenv("AZURE_SPEECH_KEY")
# speech_key = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # ←←← 改成你的 Key

service_region = "westus"
VOICE_NAME = "fr-FR-DeniseNeural"
SPEAKING_RATE = "-25%"
# 确保音频保存目录存在
AUDIO_DIR = os.path.join(app.root_path, 'static', 'audio')
os.makedirs(AUDIO_DIR, exist_ok=True)
DB_FILE = os.path.join(app.root_path, 'history.db')
# ===============================================

def init_db():
    """初始化数据库表"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            filename TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def synthesize_speech(text: str) -> str:
    """调用 Azure 生成语音，并返回文件名"""
    speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
    speech_config.speech_synthesis_voice_name = VOICE_NAME

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"french_{timestamp}.wav"
    filepath = os.path.join(AUDIO_DIR, filename)

    audio_config = speechsdk.audio.AudioOutputConfig(filename=filepath)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    ssml = f"""
    <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="fr-FR">
        <voice name="{VOICE_NAME}">
            <prosody rate="{SPEAKING_RATE}">
                {text}
            </prosody>
        </voice>
    </speak>
    """
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return filename
    else:
        raise Exception("语音合成失败")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'error': '文本不能为空'}), 400

    try:
        filename = synthesize_speech(text)
        # 保存到数据库
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT INTO history (text, filename) VALUES (?, ?)', (text, filename))
        audio_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'id': audio_id,
            'text': text,
            'filename': filename,
            'url': f'/static/audio/{filename}'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/history', methods=['GET'])
def get_history():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # 移除 LIMIT，返回所有数据以便前端精确统计和搜索
    cursor.execute('SELECT id, text, filename, created_at FROM history ORDER BY id DESC')
	# cursor.execute('SELECT id, text, filename, created_at FROM history ORDER BY id DESC LIMIT 50')

    rows = cursor.fetchall()
    conn.close()
    
    history_list = []
    for row in rows:
        history_list.append({
            'id': row[0],
            'text': row[1],
            'url': f'/static/audio/{row[2]}',
            'created_at': row[3]
        })
    return jsonify(history_list)

# ================= 新增：删除接口 =================
@app.route('/history/<int:record_id>', methods=['DELETE'])
def delete_history(record_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 1. 查询对应的音频文件名
        cursor.execute('SELECT filename FROM history WHERE id = ?', (record_id,))
        row = cursor.fetchone()
        
        if row:
            filename = row[0]
            filepath = os.path.join(AUDIO_DIR, filename)
            
            # 2. 如果服务器上存在该文件，则物理删除
            if os.path.exists(filepath):
                os.remove(filepath)
            
            # 3. 从数据库中删除该记录
            cursor.execute('DELETE FROM history WHERE id = ?', (record_id,))
            conn.commit()
            
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
