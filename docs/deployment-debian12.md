# Debian 12 部署文档

> 项目：`french-tts` 法语发音助手（语音合成 + 本地拼读规则查询）
> 适用系统：Debian 12（bookworm）
> 文档版本：1.0（2026-10-21）

---

## 1. 部署架构

```
浏览器
  │  HTTP/HTTPS
  ▼
Nginx（80/443）──静态资源 /static/ ──► /srv/french-tts/static/
  │ 反向代理
  ▼
Gunicorn（127.0.0.1:5000，systemd 管理）──► Flask app:app
                                            ├── history.db（生成语音历史）
                                            ├── data/pronounce.db（拼读规则库）
                                            └── Azure Speech（语音合成）
```

- 拼读功能完全离线，查询 `data/pronounce.db`，不依赖外网。
- 语音合成需要 Azure Speech 订阅 Key，且服务器能访问微软服务。
- `zh_en/` 是另一个子项目，本次部署不涉及。

## 2. 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Debian 12 |
| Python | 3.11（Debian 12 自带） |
| 内存 | ≥ 512MB（Azure Speech SDK 加载后约 150–250MB） |
| 磁盘 | ≥ 200MB（含虚拟环境与依赖） |
| 端口 | 5000（仅本机）、80/443（Nginx） |
| 外网 | Azure 语音接口（如启用语音合成） |

## 3. 安装系统依赖

以具有 sudo 权限的用户执行：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git curl
```

安装 Poetry（项目依赖统一由其管理）：

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

将 `~/.local/bin` 加入 `PATH`（若尚未加入），使 `poetry` 命令可用。

验证：

```bash
python3 --version    # 应显示 Python 3.11.x
poetry --version
nginx -v
```

## 4. 获取代码与创建目录

```bash
sudo mkdir -p /srv/french-tts
sudo chown "$USER":"$USER" /srv/french-tts

git clone <仓库地址> /srv/french-tts
cd /srv/french-tts
```

如果通过压缩包上传，解压后确保以下文件位于 `/srv/french-tts` 根目录：

```
app.py
pronounce_engine.py
build_pronounce_db.py
pyproject.toml
poetry.lock
poetry.toml
templates/index.html
docs/french.txt          ← 构建拼读库的源数据，必须存在
docs/pronunciation-design.md
docs/deployment-debian12.md
```

> `docs/french.txt` 是拼读数据库的源文件，务必纳入部署。`data/pronounce.db` 不入版本库，需要在服务器上构建。

## 5. 用 Poetry 安装依赖

```bash
cd /srv/french-tts
poetry install
```

依赖声明在 `pyproject.toml` 中，精确版本锁定在 `poetry.lock`：

```toml
[project]
dependencies = [
    "Flask==3.0.0",
    "azure-cognitiveservices-speech==1.34.0",
    "gunicorn==21.2.0",
    "dotenv>=0.9.9,<0.10.0",
]
```

> 注意：`dotenv` 是 `app.py` 读取 `.env` 所必需的依赖。它本身是一个很薄的兼容包（PyPI 上标注为 deprecated），并依赖 `python-dotenv`；`poetry.lock` 中实际锁定的 `python-dotenv` 为 1.0.1，与旧环境行为一致。

`poetry.toml` 中设置了 `virtualenvs.in-project = true`，虚拟环境创建在项目内的 `.venv/`，与下文 systemd 的 `ExecStart` 路径一致。

### 5.1 旧部署机迁移

旧部署机上的 `pyproject.toml`、`poetry.lock` 从未纳入版本库，与本仓库的配置不一致。直接 `git pull` 后旧锁文件会让 poetry 拒绝安装（提示 `pyproject.toml changed significantly since poetry.lock was last generated`）。迁移步骤：

```bash
cd /srv/french-tts
sudo -u frenchtts git pull
sudo -u frenchtts rm -f pyproject.toml poetry.lock
sudo -u frenchtts git checkout -- pyproject.toml poetry.lock   # 以仓库版本为准
sudo -u frenchtts poetry install
sudo systemctl restart french-tts
```

- 不要手动合并两份配置：新配置与旧配置的依赖集合一致（`dotenv` 0.9.9 会带入 `python-dotenv`，锁定的仍是 1.0.1），以仓库版本为准即可。
- `poetry install` 只安装锁定包、不删除多余包；旧环境即使残留额外包也不影响运行。若想彻底对齐，可改用 `poetry sync`。

新增依赖使用：

```bash
poetry add <包名>
```

若服务器访问 PyPI 较慢，可先为 poetry 配置国内镜像源：

```bash
poetry source add --priority=primary tuna https://pypi.tuna.tsinghua.edu.cn/simple
poetry lock
poetry install
```

## 6. 构建拼读规则数据库

```bash
cd /srv/french-tts
.venv/bin/python build_pronounce_db.py
```

预期输出：

```
解析统计：音素 36 · 源规则 103 · 补充规则 42 · 例词 119
已生成 /srv/french-tts/data/pronounce.db
数据库结构校验通过
F4 回归：119/119 全部通过
```

说明：

- 数据库生成在 `data/pronounce.db`，已被 `.gitignore` 忽略；**每次更新代码或修改规则后都需要重新执行本步骤**。
- 构建脚本先写临时文件再原子替换，服务运行中重建不会读到半成品。
- 带 `--verify` 可只校验不重建：`.venv/bin/python build_pronounce_db.py --verify`。
- 回归若未达到 119/119，说明规则/例外词表被改动，需要按设计文档检查后再部署。

## 7. 配置环境变量

在项目根目录创建 `.env`（不要提交到版本库，已在 `.gitignore` 中忽略）：

```bash
cat > /srv/french-tts/.env <<'EOF'
AZURE_SPEECH_KEY=你的Azure语音服务Key
EOF
chmod 600 /srv/french-tts/.env
```

- 语音区域与音色在 `app.py` 配置区修改（默认 `westus`、`fr-FR-DeniseNeural`、语速 `-25%`）。
- 未配置 Key 时，拼读功能仍可正常使用，只有「语音」按钮会失败。

## 8. 运行自测

先用开发服务器验证：

```bash
cd /srv/french-tts
.venv/bin/python app.py
```

另开终端：

```bash
curl -s http://127.0.0.1:5000/ -o /dev/null -w '%{http_code}\n'      # 200
curl -s -X POST http://127.0.0.1:5000/pronounce \
     -H 'Content-Type: application/json' -d '{"text":"chat"}'
```

预期返回 `"ipa_display":"[ʃa]"`。确认无误后 `Ctrl+C` 停止。

## 9. 配置 systemd 服务

创建用户与目录（若使用专用用户部署，推荐）：

```bash
sudo useradd --system --home /srv/french-tts --shell /usr/sbin/nologin frenchtts
sudo chown -R frenchtts:frenchtts /srv/french-tts
```

> 如果沿用普通用户 `john` 部署，把下面 unit 文件中的 `User`/`Group` 改为对应用户即可。

```bash
sudo tee /etc/systemd/system/french-tts.service > /dev/null <<'EOF'
[Unit]
Description=French TTS and Pronunciation Web App
After=network.target

[Service]
Type=simple
User=frenchtts
Group=frenchtts
WorkingDirectory=/srv/french-tts
Environment=PYTHONUNBUFFERED=1
ExecStart=/srv/french-tts/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now french-tts
sudo systemctl status french-tts --no-pager
```

常用运维命令：

```bash
sudo systemctl restart french-tts
sudo journalctl -u french-tts -f          # 实时日志
```

> 网页端每次生成音频会写入 `static/audio/`、更新 `history.db`，这两个路径必须对服务用户可写。`data/pronounce.db` 只需只读权限。

## 10. 配置 Nginx 反向代理

```bash
sudo tee /etc/nginx/sites-available/french-tts > /dev/null <<'EOF'
server {
    listen 80;
    server_name your-domain.example.com;   # 无域名可写服务器 IP 或 _

    client_max_body_size 2m;

    location /static/ {
        alias /srv/french-tts/static/;
        expires 7d;
        access_log off;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;   # 语音合成偶发较慢，适当放宽
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/french-tts /etc/nginx/sites-enabled/french-tts
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

浏览器访问 `http://服务器IP/`，检查：

1. 按钮行依次为 **语音 · 拼读 · forvo · Dict · wdRef · frDic**，6 种颜色；
2. 输入 `chat` 点「拼读」，显示 `[ʃa]` 与 3 张规则卡片；
3. 配置了 Azure Key 时，「语音」能生成并播放音频。

### 可选：HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example.com
```

## 11. 防火墙

如启用了 ufw：

```bash
sudo ufw allow 'Nginx Full'
sudo ufw status
```

Gunicorn 只监听 `127.0.0.1:5000`，无需对外开放。

## 12. 升级流程

```bash
cd /srv/french-tts
sudo -u frenchtts git pull
sudo -u frenchtts poetry install                                   # 依赖有变化时
sudo -u frenchtts .venv/bin/python build_pronounce_db.py           # 规则有变化时必须执行
sudo -u frenchtts .venv/bin/python -m unittest discover -s tests   # 可选：跑测试
sudo systemctl restart french-tts
```

- 数据库构建采用原子替换，可在服务运行时执行；但仍建议构建完成后再重启服务。
- 升级后访问 `POST /pronounce` 验证 `chat → [ʃa]`。

## 13. 备份

| 数据 | 路径 | 说明 |
|---|---|---|
| 生成语音历史 | `history.db` | 记录文本、文件名、时间 |
| 音频文件 | `static/audio/*.wav` | 与 `history.db` 一一对应 |
| 拼读规则库 | `data/pronounce.db` | 可由 `docs/french.txt` 重建，备份可选 |

```bash
sudo -u frenchtts tar czf /var/backups/french-tts-$(date +%F).tar.gz \
    -C /srv/french-tts history.db static
```

## 14. 故障排查

| 现象 | 原因与处理 |
|---|---|
| 启动报 `No module named 'dotenv'` | 依赖未装全，执行 `poetry install` |
| 拼读接口返回 503 | `data/pronounce.db` 不存在，执行 `.venv/bin/python build_pronounce_db.py` |
| 构建脚本报“未识别的源条件” | `docs/french.txt` 被改动或版本不匹配，恢复源文件后重建 |
| 回归未达到 119/119 | 规则或例外词被修改未同步，按 `docs/pronunciation-design.md` 检查 |
| 「语音」按钮报“语音合成失败” | `.env` 中 `AZURE_SPEECH_KEY` 无效、区域不匹配或服务器无法访问 Azure |
| 音频生成成功但页面无声 | 检查 Nginx 对 `/static/` 的 `alias` 路径与权限 |
| 删除历史记录时报错 | `static/audio/` 或 `history.db` 对服务用户不可写 |
| 502 Bad Gateway | Gunicorn 未运行：`sudo systemctl status french-tts`、`journalctl -u french-tts` |
| 拼读页面显示“未识别” | 该字母不在规则库中（如外来字母），可通过补充规则扩展 |
| 端口被占用 | `sudo ss -lntp \| grep 5000`，修改 unit 中 `-b` 端口后重启 |

## 15. 卸载

```bash
sudo systemctl disable --now french-tts
sudo rm -f /etc/systemd/system/french-tts.service
sudo rm -f /etc/nginx/sites-enabled/french-tts /etc/nginx/sites-available/french-tts
sudo systemctl daemon-reload
sudo systemctl reload nginx
sudo rm -rf /srv/french-tts        # 会删除历史记录与音频，请先备份
```

---

相关文档：`docs/pronunciation-design.md`（拼读功能设计）、`docs/french.txt`（拼读规则源数据）。
