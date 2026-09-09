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
| `tests/moderation/test_member_lifecycle.py` | 离群后的限制与任务清理、快速重新入群、延迟离群事件、保留外部权限修改、连续重启复用任务、缺失任务补建、旧重复任务合并及群间隔离 |
| `tests/moderation/test_migration_retention.py` | 自动批准连续限流与通知失败、验证结束时间及重复迁移、仅清理过期终态、验证与定时禁言叠加、迁移前任务快照与正在执行的任务协调 |
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
- 图片安全回归使用小 PNG 并临时降低 Pillow 像素阈值，实际触发解压炸弹异常及提升为异常的警告；验证纯图片失败会结束审核事件，有说明文字时仍可继续文本审核。
- 异常模型结构通过本机模拟 HTTP 服务验证，包括空用量、错误的用量/消息/响应类型；不允许失败事件在重启后变成不确定处罚。
- 禁言回归检查重复请求或权限丢失不删除已有恢复记录，并模拟到期任务检查后、取得操作锁前的禁言替换。旧 AI 任务缺少阶段标记时保留不确定状态，仅明确处于分类阶段的任务自动重试。
- 解禁测试覆盖读取权限及恢复权限时的连续限流、整数和 timedelta 等待时间、重启后保留等待期限，以及结果不确定时重建任务也不会重复调用 Telegram。
- 验证提示测试覆盖新保存及旧数据库中的纯空白值；外部权限修改分别检查所有未完成验证状态，防止手动解禁恢复过时快照。
- 已知图库分级测试覆盖禁止和允许的成人图片、独立暴力内容开关、缺失元数据复核及说明文字审核，不依赖图片下载或视觉模型可用性。
- 规则已明确拦截的消息即使在处罚前查询成员权限失败或遭到限流，也必须记录失败并停止后续命令、自动回复和图片业务；重复更新同样停止处理。
- 这些测试不替代真实 Telegram 权限联调、浏览器交互验收、外部网关鉴权测试或 MariaDB/MySQL 实库迁移验证。
- 独立审查回归覆盖原限制仅剩 1/20/30/59 秒时的恢复、限流和超时后重启、验证重试与旧恢复任务的先后顺序，以及提示发送失败保留既有禁言。
- 重复、延迟及同秒权限更新不得清除新限制；并发机器人配置和关闭不得遗留工作器。
- 本地图库分级不消耗模型预算；图片下载失败后的文本审核不能采信图片类别。分类阶段恢复同时覆盖模型调用与本地分级审计事件。
