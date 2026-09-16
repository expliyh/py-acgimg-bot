# 图片图库管理

管理端的「图片图库」（`/admin/illustrations`）用于浏览和维护已经添加的 Pixiv 插画与手动图片；「插画导入」页面仍然保留，用于添加新记录。

## API

图库接口位于 `/api/illustrations`：

- `GET /api/illustrations`：服务端分页、搜索和筛选。默认按 `id desc`、每页 24 条，最多 100 条；搜索覆盖 ID、标题、作者、描述和 JSON 标签。
- `GET/PATCH/DELETE /api/illustrations/{id}`：读取详情、编辑可编辑元数据或删除记录。
- `POST /api/illustrations/bulk/update`、`POST /api/illustrations/bulk/delete`：对当前页选中的记录执行统一修改或删除，单次最多 100 条。
- `POST /api/illustrations/{id}/refresh`、`POST /api/illustrations/bulk/refresh`：刷新 Pixiv 源信息和页面文件。批量刷新按选择顺序串行执行；手动图片、未知 ID 或已有活动任务会在创建任务前整体拒绝。
- `GET /api/illustrations/{id}/pages/{page}/media`：读取受控媒体流。详情和列表只返回该接口的地址，不回退到 Pixiv `origin_urls`。

ID、页数、来源类型、文件地址和 Telegram 文件 ID 不属于可编辑字段。`x_restrict` 与 `r18g` 分开保存，修改其中一个不会隐式改写另一个；显式提交空字符串或空标签列表可清空对应文本/标签字段。

## 存储与删除安全

媒体读取和删除只接受数据库中已经指向已配置存储提供商的地址：

- 本地文件必须位于配置的 `local_storage_root` 下，并拒绝路径穿越。
- Backblaze 和 WebDAV 只匹配已配置的公共地址/端点；接口不会代理任意外部 URL，也不会跟随重定向。
- 缺失的本地文件返回 404；远程读取或提供商清理失败返回明确错误。详情不会把失效文件替换成 Pixiv 原始地址。

删除会先在数据库事务中校验全部 ID、拒绝有进行中导入/刷新的记录并提交删除，再清理未被其他记录共享的文件。同一个共享地址不会重复删除；数据库删除成功但文件清理失败时，响应会返回结构化 `cleanup_failures`，同时写入服务端日志。Telegram 文件 ID 无法通过 Bot API 撤销，管理端会在删除确认中提示这一点；下次发送刷新后的 Pixiv 页面时会重新缓存文件 ID。

刷新会先保存本地可编辑元数据，成功后只替换 Pixiv 源字段和页面文件；旧页面会在不再被引用时清理，旧 Telegram 缓存 ID 会失效。失败时不会提交新的插画记录或本地元数据。当前版本不提供文件替换，手动图片需要重新上传为新记录。

管理端 API 仍依赖现有外部网关鉴权；本项目本身不新增一套认证机制，也不新增数据库字段或迁移。
