"""数据库迁移包。

- 有序幂等的 schema 演进 runner：见 ``runner.run_migrations``（接 ``database.init_db``）。
- 一次性「数据修复」CLI 工具：如 ``migrate_language_fields.py``（按需手动运行，
  不随启动自动执行），保留在包内供维护使用。
"""
