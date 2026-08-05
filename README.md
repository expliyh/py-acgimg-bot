# ACG 图像 Bot 管理端

该项目提供 FastAPI 后端与基于 PrimeVue 的管理控制台。要在本地运行完整的控制台体验，请按以下步骤操作：

1. 安装 Python 依赖并启动 FastAPI 后端：
   ```bash
   uvicorn main:app --reload
   ```
2. 安装前端依赖并启动开发服务器：
   ```bash
   cd webui
   npm install
   npm run dev
   ```
   开发服务器默认运行在 `http://localhost:5173/admin/`，已通过 Vite 代理自动代理到 FastAPI 的 `/api` 路由。
3. 构建生产前端时执行：
   ```bash
   npm run build
   ```
   构建后的静态文件位于 `webui/dist`，FastAPI 会自动检测并通过 `/admin` 提供服务。

## 前端自动启动

后端启动时会自动拉起前端 Vite dev server（无需手动执行 `npm run dev`）：

- 自动启动条件：`webui/dist` 不存在（开发模式）且本机可用 `npm`。
- dev server 运行在 `http://localhost:5173/admin/`，`/api` 请求会自动代理到后端 8000 端口。
- 后端关闭时 dev server 进程会一并被清理。
- 已执行 `npm run build`（存在 `webui/dist`）时，后端直接通过 `/admin` 提供构建产物，不再启动 dev server。
- 通过环境变量关闭自动启动：`AUTO_START_FRONTEND=0`。

## 数据库

- **默认使用 SQLite**，无需任何配置即可启动。数据库文件位于 `storage/acgimg.db`（首次启动自动创建）。
- 如需使用 MariaDB/MySQL，在 `.env` 中设置以下环境变量：

  ```
  DATABASE_TYPE=mysql
  DATABASE_HOST=localhost
  DATABASE_PORT=3306
  DATABASE_USERNAME=acgimg
  DATABASE_PASSWORD=your_password
  DATABASE_NAME=acgimg
  DATABASE_PREFIX=
  EXTERNAL_URL=
  ```

  `DATABASE_TYPE` 缺省为 `sqlite`；设为 `mysql` 或 `mariadb` 时使用 `mariadb+asyncmy` 驱动连接。

后端已实现仪表盘、群组管理、私聊管理以及全局功能开关等 RESTful API，前端控制台通过这些接口实现实时管理能力，并预留了未来功能扩展位置。
