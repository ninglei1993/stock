#!/bin/bash

echo "=========================================="
echo "ThemeRadar 服务诊断脚本"
echo "=========================================="
echo ""

echo "1. 检查 Docker 容器状态..."
docker compose ps
echo ""

echo "2. 检查 API 服务日志（最近50行）..."
docker compose logs api --tail=50
echo ""

echo "3. 检查 Web 服务日志..."
docker compose logs web --tail=20
echo ""

echo "4. 检查 PostgreSQL 服务..."
docker compose logs postgres --tail=20
echo ""

echo "5. 测试 API 连接..."
curl -s http://localhost:8000/health || echo "API 服务未响应"
echo ""

echo "6. 测试前端连接..."
curl -s http://localhost:3000/ | head -20 || echo "前端服务未响应"
echo ""

echo "=========================================="
echo "诊断完成"
echo "=========================================="
