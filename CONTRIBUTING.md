# 贡献指南

Podcast Digester 是一个**个人项目**，主要面向作者本人的播客消费工作流，处于活跃迭代中。欢迎以下形式的贡献。

## 欢迎的贡献

- 🐛 **Bug 报告**：通过 [Issues](https://github.com/Alliskyline2020/podcast-digester/issues) 提交，请附复现步骤、平台、日志片段。
- 🌐 **新平台支持**：新增源解析器，参考 `backend/app/sources/` 下现有实现（实现统一的 `SourceHandler` 接口）。
- 📚 **文档改进**：错别字、不准确描述、缺失说明。
- 🐎 **质量 / 性能优化**：Pipeline 各阶段的 prompt 调优，或分章 / 摘要 / 翻译策略改进。

## 开发准备

详见 [README](./README.md) 的「快速开始」。额外约定：

- 后端测试：`cd backend && source venv/bin/activate && pytest tests`（~370 用例，须保持绿色）
- 前端测试：`cd frontend && npm test`（Vitest）
- Apple AFM 3 相关集成测试依赖 macOS 26+，其他平台会跳过。

## 代码风格

- **Python**：PEP 8 + 类型注解
- **前端**：Vue 3 Composition API + 语义化 HTML + 设计令牌（CSS 变量，不硬编码色值 / 间距）
- **命名**：组件 PascalCase，hooks 用 `use` 前缀，CSS 类 kebab-case

## 提交规范

约定式提交（Conventional Commits）：

```
<type>(<scope>): <description>
```

常用 type：`feat` `fix` `refactor` `perf` `docs` `test` `chore` `ci`

## 提交 PR 前

1. 新增 / 修改的功能配上测试（项目目标 ≥ 80% 覆盖）
2. 后端 `pytest tests` 全绿、前端 `npm test` 全绿
3. **不要提交** `.env`、`data/` 运行时数据、编译产物（`.gitignore` 已覆盖，但仍请自查 `git diff`）
4. PR 描述写清动机与测试方式

## 定位说明

这是一个**单用户、本地优先**的工具，不是产品。作者会按自身需要选择性合入 PR；涉及大幅架构变动、或偏离「本地单用户」定位的提议，建议先开 Issue 讨论。感谢理解 🙏
