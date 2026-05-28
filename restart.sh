#!/bin/bash

echo "重启 ThemeRadar 服务..."
echo ""

# 停止所有服务
echo "1. 停止所有容器..."
docker compose down
echo ""

# 清理可能的旧数据
echo "2. 清理构建缓存..."
docker compose down --remove-orphans
echo ""

# 重新启动服务
echo "3. 启动所有服务..."
docker compose up -d --build
echo ""

# 等待服务启动
echo "4. 等待服务启动（10秒）..."
sleep 10
echo ""

# 检查服务状态
echo "5. 检查服务状态..."
docker compose ps
echo ""

# 测试连接
echo "6. 测试 API 连接..."
curl -s http://localhost:8000/health && echo "" || echo "API 服务未响应"
echo ""

echo "7. 测试前端连接..."
curl -s http://localhost:3000/ | head -20 || echo "前端服务未响应"
echo ""

echo "=========================================="
echo "重启完成！"
echo "如果仍有问题，请运行: ./diagnose.sh 查看详细日志"
echo "=========================================="
