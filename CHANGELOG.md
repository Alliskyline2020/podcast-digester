# 更新日志 / Changelog

本项目版本号记录在 `backend/app/config.py`（`app_version`）。本文件记录用户可感知的变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### 新增
- **数据库迁移 runner**：基于 `PRAGMA user_version` 的有序、幂等迁移框架，接到 `init_db`；baseline schema 仍在 `CREATE TABLE IF NOT EXISTS`，演进走 runner。后续 schema 变更有唯一明确落点。
- **启动恢复补全 ASR 阶段**：服务重启时撞见「ASR 未完成」的任务，现能从 `source`/`usage_log` 解析原始输入并经 `resume_episode` 重跑；解析不到时置 `failed` 并给出可操作的错误提示。
- **CI（GitHub Actions）**：后端 pytest（带覆盖率闸门 `fail-under=45`）+ 前端 vitest + 前端构建冒烟；Dependabot 周更。
- **应用启动冒烟测试**：真实 HTTP 打 `GET /` 健康端点。

### 修复
- **DeepSeek 成本计价表**：补 `deepseek-v4-flash`（$0.14/$0.28 per 1M）与 `deepseek-v4-pro`（$0.435/$0.87）两档；把 `deepseek-reasoner` 由过期的 R1 价（$0.55/$2.19）更正为 v4-flash 思考模式价（$0.14/$0.28）。此前在设置页选 `deepseek-v4-flash` 时会命中「未知模型」分支、全程按 $0 计费，使每集成本预算守护失效；选 `deepseek-reasoner` 则高估成本近 8 倍。背景：`deepseek-chat` / `deepseek-reasoner` 旧名将于 2026/07/24 废弃，分别别名映射到 `deepseek-v4-flash` 的非思考 / 思考模式。
- 清理 3 个一次性 schema 搬运脚本（其建表工作已被 `init_db` 的 `CREATE TABLE IF NOT EXISTS` 覆盖），消除「看着该自动跑实则没接」的迁移脚本造成的 schema 漂移。
- `.gitignore` 补 `.worker_pid` / `*_pid`（原 `*.pid` 不匹配）。

## [0.2.1] — 转录可读性 + 多 Provider

### 新增
- **LLM 多 Provider**：OpenAI / Anthropic / DeepSeek / GLM / Moonshot / Qwen，按「国内 / 国际」分流，设置页可填 API key 与 base_url；运行时 `complete()` 路由 + 模型自动拉取。
- **字幕可读性 Phase 1**：5 项 LLM 清洗（标点规整 / 去口水词叠词 / 专业名词矫正 / 人名矫正 / 口语顺滑），逐段清洗 + 实体收割统一人名术语写法。
- **导出原始字幕**：导出可选「包含完整字幕」，输出 LLM 清洗后的全文；亮点句子加粗。
- **音频下载后按标题命名**：下载音频落盘到独立目录并按标题重命名。
- **设置页**：齿轮入口，填入并保存 API key / base_url。

### 修复
- 数据库 schema 漂移（`title_zh` / `transcript` / 派生表 / `glossary` 等建表缺失）。
- 异步连接 `database is locked`（统一 `_connect()` 设 `busy_timeout=30s`）。

## [0.2.0] — 初始公开版本

本地优先的播客 / 视频蒸馏器：粘贴链接 → 下载 / 转录 / 分章 / 摘要 / 亮点 → 双语字幕点击跳转播放。
