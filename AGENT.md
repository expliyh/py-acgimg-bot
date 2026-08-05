# AGENT.md — 本项目开发经验

本文件记录在本仓库开发/调试中踩过的坑与可用经验，供后续会话直接复用。

## 异步脚本退出时"卡住"（aiosqlite worker 线程）

**现象**：用 `asyncio.run()` 跑一个创建了 SQLAlchemy async engine（`sqlite+aiosqlite`）的测试脚本，逻辑全部正常（打印完结果），但进程不退出，`timeout` 杀进程后才结束。

**根因**：`aiosqlite` 每个连接有一个后台 worker 线程；脚本结束时连接池未关闭，worker 线程仍存活，解释器 shutdown 时 `threading._shutdown` 等待非 daemon 线程 → 无限挂起。uvicorn 等常驻服务不会触发此问题，所以只有独立脚本会中招。

**解决**：脚本退出前显式关闭连接池：

```python
await engine.engine.dispose()   # 关闭所有连接 → worker 线程退出 → 解释器正常退出
```

**排查技巧**：用 `faulthandler.dump_traceback_later(15, exit=True)` 在卡住时 dump 全部线程栈，可区分"业务逻辑卡住"与"解释器 shutdown 卡住"（后者栈顶是 `threading._shutdown` / `aiosqlite.core._connection_worker_thread`）。

## SQLite 文件锁被残留进程占用

**现象**：测试脚本的写操作（`session.commit()` / `refresh()`）无限等待；SQLAlchemy 日志停在某条 INSERT/SELECT 后不再前进。

**根因**：先前启动的 uvicorn / python 进程未退出干净，仍持有 `storage/acgimg.db` 的写锁，新进程写同一文件时等锁。

**排查/解决**（Windows）：

```bash
tasklist //FI "IMAGENAME eq python.exe"   # 找出残留进程
taskkill //F //PID <pid>                  # 全部清理（node.exe 同理）
```

端口释放（`netstat`）≠ 进程退出，两个都要查。

## 管道过滤日志的误判教训

**教训**：用 `python xxx.py 2>&1 | grep -v sqlalchemy | tail -20` 排错时，`tail` 截断和 `grep` 过滤可能把关键结果（如 `RESULT PASS`）吞掉，或把"等待中被 kill"误判为"正常完成"（比如最后一行恰好是 SQL 日志）。判断脚本是否成功以 `exit code` 为准，并用 `grep -E "^RESULT"` 这类精确匹配代替 `tail`。

## 本仓库开发要点速查

- 默认 SQLite（`storage/acgimg.db`，已被 .gitignore 忽略），无需任何配置即可启动后端；`DATABASE_TYPE=mysql` 切换 MySQL。
- 后端启动会自动拉起 Vite dev server（`AUTO_START_FRONTEND=0` 关闭）；`webui/dist` 存在时走静态托管、不启动 dev server。
- 修改 Bot Token / Pixiv Token 后调用对应 `/reload` 端点即可生效，无需重启。
- 管理端 API 无鉴权，敏感字段（token 等）在响应中明文返回（前端默认打码显示）。
- Python 3.14 下 `asyncmy`/`aiohttp` 无预编译 wheel，需本机 MSVC 编译（已装）；`mariadb` 驱动因缺 Connector/C 未安装，代码也未 import 它。
- 本机 `python` 命令是无效商店 stub，一律用 `py` 或 `.venv/Scripts/python.exe`。
