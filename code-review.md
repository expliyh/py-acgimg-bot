# 代码审查报告

审查版本：`34ac5de`（工作区无未提交改动，按全量代码审查）。

审查范围：`main.py`、bot/handlers、`services/`（moderation、storage、file、image、importer、pixiv、permissions）、`routers/` 以及 registries/models。其中第 1 项已在本仓库虚拟环境中实际复现。

按严重程度排序。每条包含：文件位置、问题代码、原因、触发场景、严重程度、修复建议。

---

## 高

### 1. 枚举“值/名称”不匹配，保存群组/用户配置时写坏数据

- 位置：`routers/groups.py:75,254-256`、`routers/private.py:68,231-233`，相关模型 `models/groups.py:16`、`models/users.py:17`

```python
class GroupUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)   # groups.py:75
    chat_mode: GroupChatMode | None = ...             # groups.py:80
...
update_data = payload.model_dump(exclude_unset=True)  # groups.py:254
for field, value in update_data.items():
    setattr(group, field, value)                       # groups.py:256
```

- 原因：`use_enum_values=True` 会让 `model_dump()` 输出枚举的 **value**（`"Mixed"`、`"Blocked"`）。而两个列是 `Column(Enum(GroupChatMode))` / `Column(Enum(UserStatus))`，未设置 `values_callable`，SQLAlchemy 默认存储枚举的 **name**（`"MIXED"`、`"BLOCKED"`）。把 value 字符串写进该列后，随后的 `session.refresh(...)` 会失败，因为 `"Mixed"` 不是合法的存储取值。
- 已在本仓库虚拟环境复现：

```
raw stored: Blocked
REFRESH ERROR: LookupError 'Blocked' is not among the defined enum values.
             Possible values: NORMAL, INACTIVE, BLOCKED
```

- 影响：`commit()` 会成功，所以该行数据被 **永久写坏**（之后任何读取该群组/用户的接口、bot handler 都会抛 `LookupError`），而本次 PATCH 请求返回 500。
- 触发场景：后台界面保存群组配置（`GroupsView.vue` 发送 `...form`，其中 `chat_mode` 来自详情响应，而 `GroupBase` 同样设置了 `use_enum_values=True`，所以响应里就是 `"Mixed"`）；或 `PATCH /api/private/users/{id}` 传 `{"status":"Blocked"}`。目前不存在任何可用的输入值。
- 修复建议：从这两个 **更新** 模型中移除 `use_enum_values=True`（这样 `model_dump` 返回枚举成员，SQLAlchemy 会正确写入 name），响应模型保留该配置即可。或者在 `setattr` 前把字段值转回对应枚举成员。注意：只有希望数据库改存 value 时才需要给 `Enum(...)` 加 `values_callable`，但那需要数据迁移，因此上面的方案更安全。

### 2. `/admin` 与 bot 配置回调整棵调用树缺少鉴权

- 位置：`handlers/command_handlers/admin_handler.py:17-48`；`handlers/callback_handlers/conf_handlers/bot/bot_conf_handler.py:31-64`（以及 `bot/{feature_flags,storage,pixiv,cache}.py`）
- 原因：与同类命令不同（`add_pixiv_handler.py:62`、`add_manual_handler.py:44`、`p_info_handler.py:14` 都有 `has_super_user_access` 检查），`/admin` 只拒绝群组内使用；在私聊中会无条件发送完整控制面板。`bot_conf_handler_func` 分发 `conf:bot:*` 时也没有任何用户校验。
- 触发场景：任意 Telegram 用户私聊 bot 发送 `/admin`，随后点击按钮即可：更换全局存储驱动、添加/替换/清空全部 Pixiv token、切换缓存后端或注入任意 Redis URL、切换功能开关。这构成 bot 级别的配置与凭证接管。
- 严重程度：若 `/admin` 与同类命令一样本应仅限 owner，则为高；若部署本身依赖 Telegram 层面的隔离，则较低——建议先确认设计意图。

---

## 中

### 3. 超级管理员配置解析失败时仍会放行所有人

- 位置：`services/permissions.py:33-35`

```python
allowed = _parse_super_user_ids(config_value)
if not allowed:
    return True
```

- 原因：`_parse_super_user_ids` 会静默跳过无法 `int()` 的 token（如 `"@1285315854"`、`"admin"`）。因此当 `super_user` 在存储中是一个无法解析的值时，`allowed` 为空，**所有**用户都会被授予 super user 权限（`/addpixiv`、`/addimage`、`/pinfo`、`/push`）。
- 现状与边界：新增的 `PUT /api/config/access` 会用 `AccessSettings.user_ids` 校验器把 `super_user` 规范为逗号分隔的正整数并拒绝非法值（`routers/configs.py:94-102`，测试见 `tests/system/test_api_global_config.py:162`），因此经该接口写入的值不会触发本问题。“未配置 → 放行”按 `tests/test_permissions.py` 是刻意设计；但 `has_super_user_access` 本身仍把“已配置却解析失败”与“未配置”混为一谈，只要存储中出现非法/历史值（直接改库、环境默认值、其它写入路径）仍会全量放行。
- 修复建议：在 `has_super_user_access` 层区分“未配置”与“已配置但解析失败”，对后者返回 `False`（或直接抛错），仅在确实未配置时才按现有语义放行。
- 严重程度：中低（安全；需存储中存在非法值才触发）。

### 4. 重新触发验证并通过后，成员仍然被禁言

- 位置：`services/moderation/verification.py:369-384`
- 原因：当 `kick_on_timeout=False` 时，超时分支会创建一条无 `deadline` 的持久 `restriction` 记录（357-367 行）。`_RETRIGGERABLE_STATES` 包含 `"restricted"`（第 20 行），`start` 会复用这条记录作为恢复快照（128-132 行）但不删除它。成员之后验证通过时，`finish` 命中 `if restriction:` 分支，只重写 `original`，**从不** 调用 `restore_permissions`（371-379 行）。该分支注释写的是“后来的管理禁言必须在验证通过后保留”，但判断条件同样命中了验证自身产生的超时记录。`worker.recover` 只会为带 `deadline` 的记录重建 `unmute` 任务（`worker.py:300`），所以没有任何机制解除该禁言。
- 触发场景：开启验证且 `kick_on_timeout=False` 的群 → 新成员验证超时（被限制）→ 管理员执行 `/verify` → 成员通过，界面显示“验证通过”，但实际仍被禁言，直到管理员手动 `/unmute`。
- 严重程度：中。

### 5. `patch_plan` 可能抛出未捕获的 `ValidationError` → HTTP 500

- 位置：`routers/image_push.py:286`

```python
config = PushConfig.model_validate(merged)
```

- 原因：`PushConfig` 的 `mode="after"` 校验器抛出 `ValueError`，Pydantic 会将其包装为 `ValidationError`。`main.py:115` 只注册了 `RequestValidationError`，因此这个普通 `ValidationError` 不会被转成 422。第 261-264 行的 `create_plan` 调用了 `try/except ValueError`，但这一行没有。对比：`routers/group_guard.py:99-102` 的 `patch_policy` 已按同样思路加了 `except ValueError → HTTPException(422)`。
- 触发场景：`PATCH /api/image-push/plans/{id}`，例如在无映射时 `{"mode":"fixed_different"}`、scope 为 `"selected"` 时传 `{"group_ids":[]}`、已存 `group_ids` 时传 `{"target_scope":"all"}`、或对 `fixed_same` 计划传 `{"pid":null}` → 返回 500 并带堆栈，而非预期的 422。

### 6. `download_file` 在状态码 < 400 且非 200 时可能死循环

- 位置：`services/file_service/download_file.py:23-47`
- 原因：`attempt` 只在 `except aiohttp.ClientError` 分支里自增（第 40 行）。对于非 200 的 2xx/3xx 状态（例如 `204 No Content`），`response.raise_for_status()` 不会抛异常而是返回 `None`，于是循环以相同的 `attempt` 无限重试，且每次新建 `ClientSession`。由于协程在整个循环期间持有该文件的 `asyncio.Lock`（第 15 行），同文件名的其它 `get_file`/`get_image` 也会被永久阻塞。
- 触发场景：图片源/代理对下载地址返回任何非 200 的最终 2xx 状态。
- 严重程度：中。

### 7. b2sdk 同步调用阻塞事件循环

- 位置：`services/storage_service/backblaze.py:39-40,52-56`
- 原因：`authorize_account`、`get_bucket_by_name`、`bucket.upload_bytes` 都是同步网络请求，却直接在 `async` 方法中执行（既未 `await` 也未下放线程池）。每次 Backblaze 上传都会冻结整个 bot + FastAPI 服务。
- 对比：`services/illustration_media.py:292` 对同样的 SDK 调用使用了 `asyncio.to_thread`，应参照该写法。
- 严重程度：中（可用性）。

### 8. `/pinfo` 不带参数会抛 `IndexError`

- 位置：`handlers/command_handlers/p_info_handler.py:26`

```python
pixiv_id = context.args[0]
```

- 原因：命令不带参数时 `context.args` 为 `[]`，与 `/addpixiv`（有 `if not args` 判断）不同。`IndexError` 会穿过 `command_logger` 抛出，用户得不到任何回复。
- 严重程度：中低。

### 9. 对非空列显式传 `null` 会触发未捕获的 `IntegrityError`（500）

- 位置：`routers/groups.py:254-256`、`routers/private.py:231-233`
- 原因：`model_dump(exclude_unset=True)` 会保留显式传入的 `null`，随后 `setattr` 把 `None` 写入非空列（`Group.enable`、`chat_mode`、`sanity_limit`、`allow_r18g`、`allow_setu`、`admin_ids`；`User.enable_chat`、`sanity_limit`、`allow_r18g`、`status`），flush 时抛 `IntegrityError` → 500。
- 触发场景：`PATCH /api/groups/1 {"allow_setu": null}`，或清空聊天模式下拉框。目前部分被第 1 项掩盖，但独立存在。
- 严重程度：中低。

### 10. 文件缓存从不失效；导入与读取使用了不同的文件名

- 位置：`services/file_service/get_file.py:64-67,74-77`，`services/illustration_importer.py:197` 对比 `services/image_service/get_image.py:122,147,178`
- 原因一：`_ensure_cached_file` 只要 `tmp/<name>` 存在就直接返回；且 `download_file` 使用默认 `replace=False`（唯一调用点是 `get_file.py:75`），所以重新导入/刷新时会静默复用旧字节，甚至掩盖源图已删除/404 的情况。
- 原因二：导入端写 `f"{illust.id}_{page_index:02d}{ext}"`（补零，`123_00.jpg`），而读取端构造 `f"{illust.id}_{resolved_page_id}{ext}"`（`123_0.jpg`），因此对第 0–9 页，读取缓存永远命中不了导入时缓存的文件，造成重复下载/拷贝。
- 严重程度：中低。

---

## 低

- `services/illustration_importer.py:208-234`：当 `pixiv_cache_to_telegram` 开启（默认）且 `bot=None` 时，`if` 与 `elif not telegram_cache_enabled` 两个分支都不执行，`compressed_id`/`original_id` 变成 `None` 并覆盖已缓存的 `file_id`。两个 Web 界面调用点都传 `bot=None`（`illustration_import_runner.py:288`、`image_push.py:355`），因此经界面重新导入总会清空缓存。
- `handlers/message_handlers/guard_set_timeout.py:32`：`logger.info(..., user.id)` 在第 34 行的 `user is None` 判断之前执行。频道帖子（`effective_user is None`，`filters.TEXT` 也匹配 `channel_post`）会抛 `AttributeError`，中断后续 message handler 并跳过 update 日志。同类 handler 都是先判断再使用。
- `utils/delete_messages.py:11-12`：逐条删除没有错误处理；若第一条 `delete_message` 失败（用户已自行删除命令消息），bot 自己的回复就永远不会被删除，且异常会以未回收的后台任务错误形式出现。调用方通过 `asyncio.create_task` 执行（`option_handler.py:44`、`admin_handler.py:32`）。
- `handlers/callback_handlers/callback_handler.py:27`：面向用户的提示串 `"δ֪������"` 是乱码（`δ`、`U+05AA`、六个 `U+FFFD`），本应为“未知的操作”。当回调前缀不在 `handler_map` 时触发。
- `routers/dashboard.py:45`：`limit: int = 10` 未加 `Query(ge=…, le=…)`，与其它分页接口不一致；`GET /api/dashboard/summary?limit=-1` 在 SQLite 上表示“不限制”，在 MySQL 上是 SQL 错误（500）。
- `messase_generator/bot_admin.py:71,97` / `handlers/.../bot/feature_flags.py:14`：全局 `allow_r18g` 开关只被显示/更新，该配置键除了展示（`bot_admin.py:71`）之外没有功能读取点；实际放行使用的是 `user.allow_r18g`/`group.allow_r18g`（`setu_handler.py`、`image_push.py`）。因此该“全局开关”看起来没有实际作用，建议确认接线意图。
- `handlers/registry.py:131-133`：`if handler.block:` 的提前返回写在 `if handler.check_update(update):` 之外，因此任何 `block=True` 且过滤器不匹配的 handler 仍会中断后续 handler。当前无 handler 传 `block=True`，属于潜在隐患。

---

## 已核查但未列为问题（避免误报）

- `main.py:167-173` 的 webhook secret 校验存在且正确。
- 在声明支持的 Python 3.13 下，导入期创建 `aiosqlite`/`RWLock` 的模式没有问题。
- `illustration_media` 的路径净化与部分文件加锁是可靠的。
- `image_push.py:684-704` 的 `_claim_batch` FIFO 行为按其注释是刻意设计。
- `models/configs.py` 的 `value_str` 已为 `Text`（并在 `schema_migrator.py` 迁移 9 中对 MySQL 执行 `MODIFY COLUMN`），可容纳较长的 URL/密码，不再有长度溢出问题。

---

## 审查范围说明

本报告未覆盖新增的 AI provider / 全局配置相关实现（`services/ai/*`、`routers/ai_providers.py`、`routers/configs.py` 的全局配置部分）的缺陷审计。

审查过程中未修改任何源文件。
