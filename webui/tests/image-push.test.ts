import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const view = readFileSync(new URL("../src/views/ImagePushView.vue", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/services/image-push-api.ts", import.meta.url), "utf8");
const router = readFileSync(new URL("../src/router/index.ts", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("image push view exposes all target and assignment modes", () => {
  assert.match(view, /所有群（每次执行动态取当前全量）/);
  assert.match(view, /固定相同图片/);
  assert.match(view, /固定不同图片/);
  assert.match(view, /随机相同图片/);
  assert.match(view, /随机不同图片/);
  assert.match(view, /PID\[:页码\]/);
  assert.match(view, /later|后来新增/);
});

test("image push API and navigation contracts are present", () => {
  assert.match(api, /\/image-push\/plans/);
  assert.match(api, /\/image-push\/manual/);
  assert.match(api, /\/image-push\/batches/);
  assert.match(router, /path: '\/image-push'/);
  assert.match(app, /label: '图片推送'/);
});
