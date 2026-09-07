# 智能群管测试

群管测试由原有的 `tests/test_moderation.py`、新增的 `tests/moderation/` 和 `webui/tests/guard-api.test.ts` 组成。新增测试直接调用生产服务、Telegram 命令处理器和 ASGI 路由，并检查数据库状态与实际发出的模拟请求。

GitHub Actions 的 service 测试任务包含 `tests/moderation/`，其执行结果及覆盖率会进入 PR 自动报告。

## 覆盖范围

| 测试文件 | 主要验证行为 |
| --- | --- |
| `tests/test_moderation.py` | 旧配置兼容、规则与命令拦截、媒体组去重、警告升级、验证竞争、SQLite 迁移、防突袭、AI 分数和图片分级 |
| `tests/moderation/test_ai.py` | 图片下载与缩放、大小限制、模型拒答/异常/重定向、文本截断、用量记录、执行前权限与策略复查、复核与处罚幂等、失败计入预算、图片附件与已知分级 |
| `tests/moderation/test_tasks.py` | 重启后过期验证、旧验证/解禁任务失效、公告五分钟边界、夏令时与错过周期、公告修改、发送结果不确定、AI 并发与停止、日志保留 |
| `tests/moderation/test_telegram.py` | 管理员/群主/匿名消息/成员豁免、分项机器人权限、回复和 ID 处罚、时长、回调群归属与权限撤销、他人点击验证、解除失败、举报限流、并发复核、编辑后复核、清理部分失败 |
| `tests/moderation/test_api.py` | Telegram 配置缓存失效、部分更新校验、操作幂等、未连接与失败结果、群间隔离、分页与统计、公告 UTC、密钥保留和清空、webhook secret |
| `tests/moderation/test_review_regressions.py` | 入群事件顺序与重复事件、后续权限变更、AI 按启用类别筛选内容、遗留任务不扣预算、无事件群的临时记录与任务清理、举报后的消息版本复查 |
| `webui/tests/guard-api.test.ts` | 请求路径与名称编码、群 ID、部分更新、处罚幂等标识、超时传播、分页参数、复核与豁免、模型密钥语义、公告时区 |

## 运行

在已安装开发依赖的项目 Python 环境中，从仓库根目录运行：

```sh
python -m pytest tests/test_moderation.py tests/moderation
python -m pytest
```

如需群管服务、管理 API 和 Telegram 命令的行覆盖率：

```sh
python -m pytest --cov=services.moderation --cov=routers.group_guard --cov=handlers.command_handlers.moderation_handler --cov-report=term-missing
```

在 `webui` 目录安装项目依赖后运行：

```sh
npm test
npm run typecheck
npm run test:typecheck
npm run build
```

只运行 Web 群管 API 测试：

```sh
node --test --experimental-strip-types tests/guard-api.test.ts
```

## 隔离与边界

- 后端沿用共享 fixture：使用临时 SQLite，每个测试重建表，不访问实际业务数据库；群管缓存和频率窗口在新测试之间清空。
- Telegram 请求由 `AsyncMock` 接收；模型协议测试只访问随机端口的本机 aiohttp 服务，不发送真实 Bot Token，也不调用付费模型。
- 前端通过 Axios 自定义 adapter 捕获真实客户端的序列化请求，不向管理 API 发起网络请求。
- 并发测试使用 `asyncio.Event` 和有界等待，公告边界使用固定 UTC 时钟；不等待实际验证或禁言时长。
- 这些测试不替代真实 Telegram 权限联调、浏览器交互验收、外部网关鉴权测试或 MariaDB/MySQL 实库迁移验证。
