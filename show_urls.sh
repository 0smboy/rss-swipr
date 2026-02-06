#!/bin/bash
# Quick script to show all access URLs for RSS Swipr

# Get port from environment variable or use default
PORT="${PORT:-5000}"

echo "================================"
echo "   RSS Swipr 访问地址"
echo "================================"
echo ""
echo "📱 本机访问："
echo "   http://127.0.0.1:$PORT"
echo "   http://localhost:$PORT"
echo ""
echo "🌐 局域网访问（手机/平板/其他设备）："

# Get local IP addresses (excluding localhost)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    ifconfig | grep "inet " | grep -v 127.0.0.1 | awk -v port="$PORT" '{print "   http://" $2 ":" port}'
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    hostname -I | awk -v port="$PORT" '{for(i=1;i<=NF;i++) print "   http://" $i ":" port}'
else
    # Windows (Git Bash)
    ipconfig | grep "IPv4" | awk -v port="$PORT" '{print "   http://" $NF ":" port}'
fi

echo ""
echo "💡 提示："
echo "   1. 确保手机和电脑连接同一个 WiFi"
echo "   2. 使用上面的局域网地址在手机浏览器访问"
echo "   3. 可以添加到主屏幕，体验更好！"
echo ""
if [ "$PORT" != "5000" ]; then
    echo "ℹ️  使用自定义端口: $PORT"
    echo ""
fi
echo "================================"
