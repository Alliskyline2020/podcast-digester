# 🔧 字幕显示问题修复

## 问题原因

**字段不匹配：**
- 后端返回：`paragraph_mappings[].text_original`
- 前端模板使用：`para.text_clean`（不存在）
- 结果：字幕内容为空，不显示

## 修复方案

**修改模板字段映射：**
```diff
- {{ para.text_clean }}
+ {{ para.text_original || para.text_clean }}
```

**兼容性：**
- 后端 paragraph_mappings：使用 `text_original`
- 前端 fallback：使用 `text_clean`（有冗余字段）
- 两种情况都能正常工作

## Background Task 说明

**什么是 Background Task？**

Background task（后台任务）是指我在后台启动的长时间运行的进程，用于：

1. **启动前端服务器：**
   ```bash
   npm run dev &  # 在后台运行
   ```
   - 进程ID：bb90c56
   - 输出文件：`/private/tmp/claude/-Users-alli/tasks/bb90c56.output`
   - 作用：提供前端开发服务器

2. **启动后端服务器：**
   ```bash
   uvicorn app.main:app --reload &  # 在后台运行
   ```
   - 进程ID：bb06555
   - 输出文件：`/private/tmp/claude/-Users-alli/tasks/bb06555.output`
   - 作用：提供后端API服务

**为什么要用后台任务？**

- ✅ 不阻塞当前对话
- ✅ 服务持续运行
- ✅ 可以随时查看日志
- ✅ 不占用主线程

**查看后台任务输出：**
```bash
cat /private/tmp/claude/-Users-alli/tasks/bb90c56.output
```

**停止后台任务：**
```bash
# 通过 TaskOutput 工具或 KillShell
kill <PID>
```

## 验证修复

刷新浏览器 http://localhost:5173，应该能看到：

```
✅ 00:13 - 00:33
✅ 大家好我是小军。本集节目，我们来到了美国纽约...
```

字幕应该正常显示了！
