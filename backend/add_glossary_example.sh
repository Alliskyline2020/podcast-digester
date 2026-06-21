#!/bin/bash
# 添加词库条目示例脚本

curl -X POST http://localhost:8000/api/glossary/add \
  -H "Content-Type: application/json" \
  -d '{
    "correct": "张小珺",
    "wrong": ["小军", "张小君", "小珺"]
  }'

echo ""
echo "✅ 词库条目已添加"
echo ""
echo "查看词库："
curl -s -X POST http://localhost:8000/api/glossary/entries | python3 -m json.tool
