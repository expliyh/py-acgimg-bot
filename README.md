# ACG Image Bot Admin Suite

This repository now ships with an administrative dashboard built with Vue 3 + PrimeVue and a RESTful API implemented with FastAPI. The UI covers dashboard analytics, group management, private chat curation, feature configuration (including non-image extensions), and automation rules.

## Backend (FastAPI)

* **Launch**: `uvicorn main:app --reload`
* **Key endpoints**
  * `GET /api/dashboard` – aggregate metrics for the control panel
  * `GET|POST|PUT|DELETE /api/groups` – manage Telegram groups served by the bot
  * `GET|POST|PUT|DELETE /api/private-chats` – curate one-to-one conversations
  * `GET|POST|DELETE /api/features` – configure image and non-image features
  * `GET|POST|PUT|DELETE /api/automations` – maintain automation rules such as scheduled inspections
* **CORS** is enabled for local development so the Vue application can communicate with the API.

On startup the API seeds sample groups, private chats, feature toggles, and automation rules so the dashboard has data immediately. All data is stored in an in-memory store (`services/admin_store.py`) that uses async locks to remain concurrency-safe.

## Frontend (Vue 3 + PrimeVue)

The dashboard lives inside the [`webui/`](webui/) directory and was scaffolded manually for easy integration into existing workflows.

```bash
cd webui
npm install
npm run dev
```

The development server listens on `http://localhost:5173` by default. Set `VITE_API_BASE_URL` in a `.env` file if the FastAPI server runs on a different host or port.

### Screens

* **仪表盘** – metrics, health hints, and maintenance reminders
* **群组管理** – CRUD for groups with tags and status toggles
* **私聊管理** – per-user notes, mute toggles, and deletion workflows
* **功能配置** – extensible configuration cards with key/value options for NSFW and additional features such as translation or event push
* **自动化规则** – manage triggers/actions to automate operations

The UI relies on PrimeVue components (Menubar, DataTable, Dialog, etc.), Pinia for shared state, and Axios for API integration.

## Development Tips

* Run `pytest` to execute backend tests (none are defined yet, but this ensures the environment is ready).
* The in-memory admin store can be replaced with a persistent backend by implementing the same methods and wiring it up in `main.py`.
