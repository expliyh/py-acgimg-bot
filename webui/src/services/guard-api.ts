import axios from "axios";

const client = axios.create({ baseURL: "/api", timeout: 30000 });
export interface GuardPolicy {
  verification_enabled: boolean;
  verification_timeout: number;
  verification_message: string | null;
  kick_on_timeout: boolean;
  keyword_filter_enabled: boolean;
  verification_mode: "button" | "math";
  join_auto_approve: boolean;
  join_requests_enabled: boolean;
  rules_enabled: boolean;
  flood_enabled: boolean;
  flood_window: number;
  flood_limit: number;
  repeat_window: number;
  repeat_limit: number;
  raid_enabled: boolean;
  raid_window: number;
  raid_limit: number;
  raid_duration: number;
  warning_limit: number;
  warning_days: number;
  mute_seconds: number;
  log_days: number;
  domain_allowlist: string[];
  welcome_enabled: boolean;
  welcome_text: string;
  goodbye_enabled: boolean;
  goodbye_text: string;
  rules_text: string;
  replies_enabled: boolean;
  clean_service_messages: boolean;
  ai_spam: boolean;
  ai_abuse: boolean;
  ai_images: boolean;
  ai_auto_threshold: number;
  ai_review_threshold: number;
  ai_daily_limit: number;
  timezone: string;
}
export type GuardCategory = "join" | "rules" | "ai" | "members" | "content";
export interface GuardRule {
  kind: "keyword" | "regex" | "link" | "invite" | "forward" | "media";
  pattern: string;
  case_sensitive: boolean;
  action: "delete" | "delete_warn";
  enabled: boolean;
}
export interface GuardContent {
  kind: "reply" | "note" | "announcement";
  name: string;
  text: string;
  enabled: boolean;
  due_at?: string;
  repeat: "once" | "daily" | "weekly";
  timezone: string;
}
export interface GuardRecord<T = Record<string, unknown>> {
  id: string;
  group_id: number;
  kind: string;
  key: string;
  data: T;
  enabled: boolean;
  created_at: string;
}
export interface GuardEvent {
  id: string;
  action: string;
  status: string;
  reason: string;
  source: string;
  user_id?: number;
  message_id?: number;
  data: Record<string, unknown>;
  created_at: string;
}
export interface GuardPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}
export type GuardAction =
  | "warn"
  | "unwarn"
  | "mute"
  | "unmute"
  | "kick"
  | "ban"
  | "unban"
  | "delete"
  | "pin"
  | "unpin"
  | "purge";
export interface GuardActionRequest {
  action: GuardAction;
  user_id?: number;
  message_id?: number;
  end_message_id?: number;
  duration?: number;
  event_id?: string;
  reason: string;
  request_id: string;
}
export interface GuardActionResult {
  id: string;
  action: GuardAction;
  status: string;
  reason: string;
  data: Record<string, unknown>;
}
export type ReviewDecision =
  "dismiss" | "punish" | "revoke" | "approve_join" | "reject_join";
export interface GuardReview {
  state: string;
  kind: string;
  user_id?: number;
  message_id?: number;
  reason: string;
  confidence?: number;
  evidence?: string;
  results?: unknown[];
}
export interface GuardMember {
  user_id: number;
  exempt: boolean;
  warnings: GuardEvent[];
  restriction: GuardRecord | null;
  verification: Record<string, unknown> | null;
}
export interface GuardStats {
  days: { date: string; counts: Record<string, number> }[];
  actions: Record<string, number>;
  statuses: Record<string, number>;
  total_tokens: number;
}
export interface AIConfig {
  base_url: string;
  api_key?: string | null;
  has_api_key?: boolean;
  text_model: string;
  vision_model: string;
  timeout: number;
  concurrency: number;
}
export interface GuardTask {
  id: string;
  kind: string;
  state: string;
  due_at: string;
  result: string | null;
  data: Record<string, unknown>;
}
const base = (id: number) => `/groups/${id}/guard`;
export const guardApi = {
  policy: async (id: number): Promise<GuardPolicy> =>
    (await client.get(base(id))).data,
  savePolicy: async (
    id: number,
    value: Partial<GuardPolicy>,
  ): Promise<GuardPolicy> => (await client.patch(base(id), value)).data,
  permissions: async (id: number): Promise<Record<string, unknown>> =>
    (await client.get(`${base(id)}/permissions`)).data,
  rules: async (
    id: number,
  ): Promise<{
    items: GuardRecord<GuardRule>[];
    legacy: { id: number; pattern: string; is_regex: boolean }[];
  }> => (await client.get(`${base(id)}/rules`)).data,
  saveRule: async (id: number, name: string, value: GuardRule) =>
    client.put(`${base(id)}/rules/${encodeURIComponent(name)}`, value),
  deleteRule: async (id: number, name: string) =>
    client.delete(`${base(id)}/rules/${encodeURIComponent(name)}`),
  deleteLegacy: async (id: number, rule: number) =>
    client.delete(`${base(id)}/legacy-rules/${rule}`),
  member: async (id: number, user: number): Promise<GuardMember> =>
    (await client.get(`${base(id)}/members/${user}`)).data,
  exempt: async (id: number, user: number, enabled: boolean) =>
    client.put(`${base(id)}/members/${user}/exempt`, null, {
      params: { enabled },
    }),
  action: async (
    id: number,
    value: GuardActionRequest,
  ): Promise<GuardActionResult> =>
    (await client.post(`${base(id)}/actions`, value)).data,
  revoke: async (id: number, event: string): Promise<GuardActionResult> =>
    (await client.post(`${base(id)}/events/${event}/revoke`)).data,
  contents: async (
    id: number,
  ): Promise<Record<string, GuardRecord<GuardContent>[]>> =>
    (await client.get(`${base(id)}/contents`)).data,
  saveContent: async (id: number, value: GuardContent) =>
    client.put(`${base(id)}/contents`, value),
  deleteContent: async (id: number, kind: string, name: string) =>
    client.delete(`${base(id)}/contents/${kind}/${encodeURIComponent(name)}`),
  reviews: async (
    id: number,
    page: number,
  ): Promise<GuardPage<GuardRecord<GuardReview>>> =>
    (await client.get(`${base(id)}/reviews`, { params: { page } })).data,
  decide: async (
    id: number,
    review: string,
    decision: ReviewDecision,
  ): Promise<GuardRecord<GuardReview>> =>
    (await client.post(`${base(id)}/reviews/${review}`, { decision })).data,
  logs: async (
    id: number,
    page: number,
    status?: string,
  ): Promise<GuardPage<GuardEvent>> =>
    (
      await client.get(`${base(id)}/logs`, {
        params: { page, status: status || undefined },
      })
    ).data,
  tasks: async (id: number, page = 1): Promise<GuardPage<GuardTask>> =>
    (await client.get(`${base(id)}/tasks`, { params: { page } })).data,
  stats: async (id: number): Promise<GuardStats> =>
    (await client.get(`${base(id)}/stats`)).data,
  ai: async (): Promise<AIConfig> => (await client.get("/guard-ai")).data,
  saveAI: async (value: AIConfig): Promise<AIConfig> =>
    (await client.put("/guard-ai", value)).data,
};
