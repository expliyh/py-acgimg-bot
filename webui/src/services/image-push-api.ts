import axios from "axios";

const client = axios.create({ baseURL: "/api", timeout: 30000 });

export type ImagePushMode = "fixed_same" | "fixed_different" | "random_same" | "random_different";
export type ImagePushRepeat = "once" | "daily" | "weekly" | "interval";

export interface ImagePushConfig {
  target_scope: "selected" | "all";
  group_ids: number[];
  mode: ImagePushMode;
  pid?: string | null;
  pid_by_group?: Record<string, string> | null;
}

export interface ImagePushPlanPayload extends ImagePushConfig {
  name: string;
  enabled: boolean;
  repeat: ImagePushRepeat;
  due_at: string;
  interval_seconds?: number | null;
  timezone: string;
}

export interface ImagePushPlan extends ImagePushPlanPayload {
  id: string;
  next_run_at: string;
  created_at: string;
  updated_at: string;
  latest_batch_id: string | null;
  latest_batch_state: string | null;
}

export interface ImagePushDelivery {
  id: string;
  batch_id: string;
  group_id: number;
  state: string;
  pixiv_id: string | null;
  page: number | null;
  telegram_message_id: number | null;
  reason: string | null;
  attempts: number;
  next_attempt_at: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ImagePushBatch {
  id: string;
  plan_id: string | null;
  trigger: "manual" | "auto";
  state: string;
  due_at: string;
  config_snapshot: ImagePushConfig;
  summary: Record<string, number>;
  result: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  deliveries?: ImagePushDelivery[];
}

export interface ImagePushPage<T> {
  total: number;
  items: T[];
  page: number;
  page_size: number;
  pages: number;
}

export async function listImagePushPlans(page = 1, pageSize = 25): Promise<ImagePushPage<ImagePushPlan>> {
  const { data } = await client.get<ImagePushPage<ImagePushPlan>>("/image-push/plans", {
    params: { page, page_size: pageSize },
  });
  return data;
}

export async function createImagePushPlan(payload: ImagePushPlanPayload): Promise<ImagePushPlan> {
  const { data } = await client.post<ImagePushPlan>("/image-push/plans", payload);
  return data;
}

export async function updateImagePushPlan(id: string, payload: Partial<ImagePushPlanPayload>): Promise<ImagePushPlan> {
  const { data } = await client.patch<ImagePushPlan>(`/image-push/plans/${encodeURIComponent(id)}`, payload);
  return data;
}

export async function deleteImagePushPlan(id: string): Promise<{ removed: boolean }> {
  const { data } = await client.delete<{ removed: boolean }>(`/image-push/plans/${encodeURIComponent(id)}`);
  return data;
}

export async function runImagePushPlan(id: string): Promise<ImagePushBatch> {
  const { data } = await client.post<ImagePushBatch>(`/image-push/plans/${encodeURIComponent(id)}/run`);
  return data;
}

export async function createManualImagePush(payload: ImagePushConfig): Promise<ImagePushBatch> {
  const { data } = await client.post<ImagePushBatch>("/image-push/manual", payload);
  return data;
}

export async function listImagePushBatches(page = 1, pageSize = 25): Promise<ImagePushPage<ImagePushBatch>> {
  const { data } = await client.get<ImagePushPage<ImagePushBatch>>("/image-push/batches", {
    params: { page, page_size: pageSize },
  });
  return data;
}

export async function getImagePushBatch(id: string): Promise<ImagePushBatch> {
  const { data } = await client.get<ImagePushBatch>(`/image-push/batches/${encodeURIComponent(id)}`);
  return data;
}
