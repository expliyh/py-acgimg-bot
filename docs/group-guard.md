# 智能群管使用与部署

群管提供规则审核、入群验证、防刷屏与突袭、警告处罚、群运营、举报复核和可选 AI 审核。Telegram 与 Web 共用数据库配置。所有新增自动功能默认关闭，升级保留旧进群验证和关键词设置。

## 启用

1. 安装 Python 依赖并构建前端：`pip install -r requirements/requirements.txt`；在 `webui` 执行 `npm ci` 和 `npm run build`。
2. 启动前备份数据库。启动过程自动创建群管表并执行截至第 6 版的迁移，兼容 SQLite 与 MariaDB/MySQL，无需清空现有数据。第 6 版记录验证结束时间；旧的已结束记录从升级时开始计算保留期。
3. 每个数据库/机器人部署运行 **一个 Uvicorn worker**。后台任务与 Telegram 事件由该进程统一管理；当前不支持多实例争抢同一个 Bot Token。
4. 将机器人设置为群管理员。删除消息需要删除权限，验证/禁言/封禁需要限制成员权限，入群申请需要邀请权限，置顶需要置顶权限。
5. 在群里发送 `/guard`，或者在 Web「群组管理」详情打开「智能群管」。Web 也可直接输入负数群 ID。概览显示机器人当前权限。

Web 沿用部署方外部网关身份认证，拥有 Web 访问权限的人员视为部署管理员，可管理全部已登记群。Telegram 管理指令、按钮、旧配置面板及后续文本输入会重新验证真实群管理员身份，不以 Web 可编辑的管理员 ID 列表作为授权依据。

## Telegram 操作

`/guard` 打开分类面板。布尔选项可点击切换，其余配置使用 `/guard set 字段 值`。群内输入 `/guard help` 查看完整格式。

```text
/guard verify on
/guard verify timeout 90
/guard keyword add 旧关键词
/guard set verification_mode math
/guard set join_requests_enabled on
/guard set flood_enabled on
/guard set rules_enabled on
/guard set domain_allowlist example.com,docs.example.org
/guard rule add 广告 keyword 加群返现
/guard rule add 邀请 invite
/guard rule add 文件 media document
/guard rule list
/guard rule remove 广告
/guard exempt 123456789 on
```

规则类型：`keyword`、`regex`、`link`、`invite`、`forward`、`media`。正则使用可中断匹配，每次匹配最多 20 毫秒。白名单按完整域名或其子域名匹配，不接受通配符。隐藏链接、消息编辑和图片说明参与审核。

新规则默认删除并警告；Web 可以改为仅删除。原有 `/guard keyword` 规则仍只删除。旧规则开关为 `keyword_filter_enabled`，新规则开关为 `rules_enabled`，两者独立。

处罚指令支持回复目标消息或填写数字用户 ID：

```text
/warn 123456789 广告引流
/warns 123456789
/unwarn 123456789
/mute 123456789 30m 刷屏
/unmute 123456789
/kick 123456789
/ban 123456789
/unban 123456789
```

禁言时长支持 `m`、`h`、`d`。`/pin`、`/unpin`、`/del` 回复目标消息使用；`/purge` 回复起点消息，删除到命令消息，单次范围不超过 100 条。已删除内容无法由系统恢复。

普通成员通过回复消息 `/report 原因` 举报，同一消息合并复核；同一用户每分钟最多提交 3 次。管理员在群内处理按钮或 Web「举报复核」中批准、拒绝、处罚或忽略。

群主、真实管理员、本机器人免于自动处罚。成员豁免只绕过内容和刷屏审核；不会自动通过入群验证。匿名管理员消息不映射为普通用户处罚，频道署名消息可以按内容删除但不会错误警告其代理机器人身份。

## 群运营

```text
/guard set rules_text 请文明交流，禁止广告。
/rules
/guard set welcome_enabled on
/guard set welcome_text 欢迎 {user} 加入 {chat}！
/guard content note 帮助 联系管理员处理问题。
/notes 帮助
/guard content reply 怎么使用 请查看置顶说明。
/guard set replies_enabled on
/guard content announcement 每日提醒 2026-09-07T09:00:00+08:00 daily 请阅读群规。
/guard content list
/guard content remove note 帮助
```

模板支持 `{user}`、`{chat}`、`{timeout}`，按纯文本发送，不解析 HTML。自动回复按关键词包含匹配，同一触发词每群 10 秒冷却。公告支持 `once`、`daily`、`weekly`，首次时间必须包含时区；周期使用群时区，默认 `Asia/Shanghai`。

## AI 配置与行为

在 Web「AI 审核」中配置兼容 Chat Completions 的 API 基址、文本模型、视觉模型及密钥。基址通常以 `/v1` 结尾，服务会追加 `/chat/completions`。密钥只写不回显；保存时留空保留原密钥，「清除密钥」显式移除。可以使用不需要密钥的本地兼容服务。

模型配置全局共用，以下开关按群独立：广告诈骗/引流、辱骂仇恨、色情暴力图片。启用后仅将待审核消息及图片发送给配置的模型服务，不发送完整群历史。群消息被当作不可信证据，不作为系统指令；模型没有管理工具，只能返回校验后的分类、评分、理由、依据和图片等级。

- 评分 ≥0.95：删除并警告；0.70–0.95：人工复核；更低：放行。评分是模型自报值，不代表统计准确率。
- 图片限制沿用实际代码的 `sanity_level <= sanity_limit` 与独立的 `allow_r18g`。模型将普通图片归为 5、成人图片归为 6，无法判断则进入复核；已有图库图片复用 Telegram 文件 ID 对应的等级。允许的成人内容不会仅因成人属性受罚。
- 照片和图片附件支持视觉审核；视频和音频本体暂不分析，说明文字仍可审核。
- 图片最大 10 MB、2000 万像素，缩放到最长边 1536 后，以 Base64 发给模型。不会把包含 Telegram Bot Token 的文件地址交给模型。
- 默认全局并发 2、请求超时 20 秒、每群每日 500 次；日限额按 UTC 重置。每群最多排队 100 条 AI 消息，排队满后继续规则审核。
- 未配置、超时、拒答、结构错误或超额不会处罚成员。模型调用失败在日志可见，跳过原因在任务结果可见。
- AI 是异步审核，消息可能先被群成员看到；规则明确拦截的消息会停止后续业务处理。AI 处置前重新检查消息版本、群策略与成员权限。

## 默认阈值与恢复

启用反刷屏后，10 秒超过 6 条消息，或 30 秒相同内容达到 3 次，删除并警告。启用防突袭后，60 秒达到 10 次入群或申请，进入 10 分钟保护：新成员加强为算术验证，暂停自动批准申请。

7 天内累计 3 次有效警告触发 1 小时禁言。相同消息/媒体组最多记一次有效警告；命中多条规则不会重复处罚。永久封禁只由管理员执行。

Web 成员警告旁的「撤销」移除选定警告；如果警告减少后未达到阈值，并且限制是本系统自动升级产生的，还会解除该限制。管理员直接设定的禁言不受此影响。解除限制时结合原有权限和当前群默认权限，其他管理员后续变更会阻止自动恢复。

验证、禁言到期、公告、AI 队列及延迟清理由数据库任务驱动。重启恢复未完成的验证和有效禁言；过期验证立即处理。错过超过 5 分钟的公告不补发，周期公告安排下一次。发送中进程中断的任务标为 `uncertain`，避免盲目重发；在 Web「日志与任务」核查，按实际结果重新创建公告或执行明确操作。

处理中断导致验证状态不确定时，管理员可用 `/unmute 用户ID` 或 Web 解除本系统验证限制。机器人权限不足、Telegram 限流及网络结果不确定分别保留实际状态，界面不会把它们显示为成功。运行期间由其他管理员修改权限的限制不自动解除。

成员离群后，清理本系统的限制记录，取消未完成验证及对应到期任务；警告历史和 Telegram 封禁保留。再次入群按当前设置重新验证。重启恢复优先复用同一群、成员及验证令牌或处罚事件对应的待执行任务，合并重复项，只补建缺失任务，并以验证或禁言记录的实际期限校正执行时间。

日志默认保存 90 天；为保证警告有效期完整，事件实际保留至少 `max(log_days, warning_days)` 天。已结束任务按同一期限清理；待复核记录和不确定任务保留供管理员处理。已通过、失败、移出、取消或因外部权限变更结束的验证，从实际结束时间起保留 `log_days` 天；等待中、处理中、仍有限制或结果不确定的验证继续保留。短期消息版本和入群去重记录保存 2 天。刷屏窗口保存在内存，重启后重新累计；验证和禁言状态不受影响。

自动批准入群申请遭 Telegram 限流时会转入人工复核；通知失败不影响 Web 待办。管理员再次批准或拒绝时遭限流，该待办仍可重试。群升级会等待正在执行的群管任务结束；已领取但尚未执行的任务从数据库重新读取迁移后的群 ID，保持审核并发和其他群的正常执行。

## Webhook 与外部网关

轮询模式不需要额外配置。使用 `EXTERNAL_URL` 启用 webhook 时，设置 `TELEGRAM_WEBHOOK_SECRET` 为随机的字母、数字、下划线或短横线字符串（1–256 字符）；机器人注册 webhook 时使用该密钥，后端校验 `X-Telegram-Bot-Api-Secret-Token`。未配置时退回轮询，不接受未鉴权 webhook 请求。

网关应保护 `/admin`、`/api` 和 OpenAPI 页面，仅为 `/tapi/` 保留 Telegram 回调通道。下面展示与已有 Nginx Basic Auth 网关的关系，不包含现有 TLS 配置：

```nginx
# 位于已有 HTTPS server 中；不要绕过已有更严格的访问控制。
auth_basic "ACG administration";
auth_basic_user_file /etc/nginx/acg.htpasswd;

location / {
    proxy_pass http://127.0.0.1:8000;
}
location = /tapi/ {
    auth_basic off;
    proxy_set_header X-Telegram-Bot-Api-Secret-Token $http_x_telegram_bot_api_secret_token;
    proxy_pass http://127.0.0.1:8000;
}
```

后端端口仅向网关开放。API 地址和模型密钥配置属于部署管理员能力，不提供普通群成员使用。

## API 与验证

群管 API 根路径为 `/api/groups/{group_id}/guard`，包含设置、规则、成员状态、操作、群运营内容、复核、日志、任务和统计。模型配置为 `/api/guard-ai`。请求结构在 FastAPI OpenAPI 中可见。

处罚 `POST /actions` 必须携带 `request_id`。网络重试使用原 ID；不同目标或新的明确操作使用新 ID。成功、失败、部分成功和结果不确定分别为 `success`、`failed`、`partial`、`uncertain`。`POST /events/{event_id}/revoke` 撤销指定警告及满足条件的自动禁言。

本地检查：`pytest`；前端 `npm run test`、`npm run typecheck`、`npm run test:typecheck`、`npm run build`。群管测试使用隔离 SQLite、模拟 Telegram 和本地模拟模型 HTTP 服务，不调用真实群或付费模型。MariaDB/MySQL 部署仍应在其测试库验证迁移后再滚动升级。

测试文件、覆盖范围及单独运行命令见 [智能群管测试说明](group-guard-testing.md)。

### 权限恢复与本地审核

原有限时限制仅剩 60 秒以内时，机器人先保存数据库恢复任务，再恢复该限制的权限；原期限到达后由工作器解除，避免 Telegram 把过短的期限当成永久限制。重启会恢复任务，后建立的验证仍需通过验证；提示发送失败时保留验证前已有的禁言。

已知图库元数据的本地分级使用独立的 `image_grade` 审计类型，不消耗每日模型调用预算。图片下载失败时只审核可用文字，不依据模型返回的图片类别处罚。机器人重新配置与关闭串行执行，避免残留旧工作器。
