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

后端已实现仪表盘、群组管理、私聊管理以及全局功能开关等 RESTful API，前端控制台通过这些接口实现实时管理能力，并预留了未来功能扩展位置。
