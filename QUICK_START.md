# 🚀 快速测试指南

## 📍 访问地址

**前端：** http://localhost:5173
**后端：** http://127.0.0.1:8000
**API文档：** http://127.0.0.1:8000/docs

---

## 🧪 快速功能测试

### 1. 测试字幕映射显示（30秒）

```
1. 打开浏览器访问：http://localhost:5173
2. 点击第一个节目："A 7-hour marathon interview..."
3. 切换到 "Transcript"（字幕）标签
4. 向下滚动查看段落

✅ 预期结果：每个段落下方显示 "X 段原始字幕 #起始-#结束"
```

**示例显示：**
```
大家好 我是小军。本集节目...
9 段原始字幕 #0 - #8     ← 这是新功能！
```

### 2. 测试映射详情展开（10秒）

```
1. 点击 "9 段原始字幕 #0 - #8"
2. 查看展开的详细信息

✅ 预期结果：显示 segment_indices 和 segment_ids 列表
```

**展开显示：**
```
段落索引：[0, 1, 2, 3, 4, 5, 6, 7, 8]
段落ID：[0, 1, 2, 3, 4, 5, 6, 7, 8]
```

### 3. 测试自动滚动（1分钟）

```
1. 点击播放按钮 ▶️
2. 观察字幕列表的滚动行为

✅ 预期结果：
- 当前播放段落的卡片高亮
- 字幕自动滚动到视图中心
- 滚动流畅无卡顿
```

---

## 🔧 API 测试命令

### 测试单个字幕同步
```bash
curl -X POST "http://127.0.0.1:8000/api/episodes/ep_1781109978390/sync-subtitles" \
  -H "Content-Type: application/json"
```

**预期响应：**
```json
{
  "episode_id": "ep_1781109978390",
  "paragraph_count": 1151,
  "paragraph_mappings": [...]
}
```

### 测试批量字幕同步
```bash
curl -X POST "http://127.0.0.1:8000/api/admin/batch-sync-subtitles" \
  -H "Content-Type: application/json" \
  -d '{"episode_ids": ["ep_1781109978390"]}'
```

### 获取节目数据（含映射）
```bash
curl -s "http://127.0.0.1:8000/api/episode/ep_1781109978390" | python3 -m json.tool
```

---

## 🎮 键盘快捷键

在 PlayerView 中可以使用：

- `空格`：播放/暂停
- `←/→`：快退/快进 10秒
- `↑/↓`：音量调节
- `?`：显示快捷键帮助

---

## 📊 验证数据

### 检查数据库中的映射
```bash
sqlite3 data/podcast_digester.db "SELECT length(paragraph_mappings) FROM episode WHERE id='ep_1781109978390'"
```

### 检查 API 响应
```bash
curl -s "http://127.0.0.1:8000/api/episode/ep_1781109978390" | python3 -c "
import sys, json
data = json.load(sys.stdin)
mappings = data['episode']['episode']['paragraph_mappings']
print(f'Paragraph mappings: {len(mappings)} entries')
print(f'First entry: {mappings[0]}')
"
```

---

## 🐛 故障排除

### 前端无法访问
```bash
# 检查前端进程
ps aux | grep vite

# 重启前端
cd /Users/alli/podcast-digester/frontend
npm run dev
```

### 后端无法访问
```bash
# 检查后端进程
ps aux | grep uvicorn

# 重启后端
cd /Users/alli/podcast-digester/backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 映射不显示
```bash
# 重新生成映射
curl -X POST "http://127.0.0.1:8000/api/episodes/ep_1781109978390/sync-subtitles"

# 刷新浏览器页面
```

---

## 📱 浏览器测试

### 推荐浏览器
- ✅ Chrome/Edge（最佳体验）
- ✅ Safari（良好）
- ✅ Firefox（良好）

### 开发者工具
按 `F12` 或 `Cmd+Option+I` 打开开发者工具查看：
- Console：查看前端日志
- Network：查看 API 请求
- Elements：检查 DOM 结构

---

## ✅ 成功标志

如果看到以下内容，说明功能正常：

1. **Library 页面**：显示节目列表
2. **PlayerView**：播放器正常加载
3. **字幕 Tab**：显示段落列表
4. **映射信息**：显示 "X 段原始字幕" 标签
5. **自动滚动**：播放时字幕自动滚动

---

## 📞 获取帮助

- 完整文档：`docs/superpowers/README.md`
- 部署指南：`docs/superpowers/deployment-guide.md`
- 用户手册：`docs/superpowers/user-guide.md`
- API文档：http://127.0.0.1:8000/docs

---

**祝测试愉快！🎉**
