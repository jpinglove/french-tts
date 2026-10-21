#!/bin/bash

echo "=========================================="
echo "🔄 开始彻底重启并清理所有 Web 服务..."
echo "=========================================="

# 1. 正常停止 Systemd 服务
echo "⏳ [1/4] 正在停止后台服务..."
sudo systemctl stop french-tts
sudo systemctl stop zh-en-translator

# 2. 物理超度：强制清理所有 Gunicorn 残留进程
echo "🔪 [2/4] 正在强制清理内存中残留的 Gunicorn 进程..."
# 使用 -9 参数进行绝对强制的物理击杀
sudo pkill -9 gunicorn

# 稍微等待1秒，确保操作系统完全释放 5000 和 5001 端口
sleep 1 

# 3. 干净地重新启动后台服务
echo "🚀 [3/4] 正在使用新代码启动后端服务..."
sudo systemctl start french-tts
if [ $? -eq 0 ]; then
    echo "✅ 法语服务重启成功"
else
    echo "❌ 法语服务重启失败"
fi

# 2. 重启中英翻译服务
echo "⏳ 正在重启 [中英翻译] 服务 (zh-en-translator)..."
sudo systemctl start zh-en-translator
if [ $? -eq 0 ]; then
    echo "✅ 翻译服务重启成功"
else
    echo "❌ 翻译服务重启失败"
fi

# 3. 重启 Nginx (可选，如果修改了Nginx配置时很有用)
# sudo systemctl restart nginx

CONF_PATH="/var/www/111142.conf"

echo "⏳ 正在检查并重启 Nginx..."

# 使用 pgrep 精准查找是否已经有使用该配置文件的 nginx 进程在运行
# 这里用 -f 匹配完整的命令行，排除 grep 自身
if pgrep -f "nginx -c $CONF_PATH" > /dev/null; then
    echo "发现正在运行的 Nginx 实例，尝试平滑重载配置..."
    sudo nginx -s reload -c "$CONF_PATH"
else
    echo "未发现运行中的实例（或 pid 已丢失），正在执行全新冷启动..."
    sudo nginx -c "$CONF_PATH"
fi

# 再次验证是否真正启动成功
if pgrep -f "nginx -c $CONF_PATH" > /dev/null; then
    echo "==================================="
    echo "✅ Nginx 已经成功运行！"
    echo "==================================="
else
    echo "❌ 错误：Nginx 启动失败，请检查端口是否被占用或查看 /var/log/nginx/error.log"
fi

# sudo nginx -s reload -c /var/www/111142.conf
echo "✅ Nginx 重启成功"

echo "==================================="
echo "🎉 所有服务重启完毕！"
echo "==================================="
