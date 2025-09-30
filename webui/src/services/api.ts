import axios from 'axios';

const client = axios.create({
  baseURL: '/api',
  timeout: 15000
});

export interface DashboardActivityEntry {
  message_id: number;
  scope: string;
  scope_id: number;
  preview: string | null;
  sent_at: string | null;
}

export interface DashboardSummary {
  total_groups: number;
  active_groups: number;
  chat_enabled_groups: number;
  total_users: number;
  chat_enabled_users: number;
  total_group_messages: number;
  total_private_messages: number;
  recent_activity: DashboardActivityEntry[];
}

export interface EnumOption {
  label: string;
  value: string;
}

export interface GroupMeta {
  chat_modes: EnumOption[];
  statuses: EnumOption[];
}

export interface ChatMessage {
  message_id: number;
  user_id: number | null;
  type: string;
  bot_send: boolean;
  text: string | null;
  sent_at: string | null;
}

export interface GroupListItem {
  id: number;
  name: string;
  status: string;
  enable: boolean;
  enable_chat: boolean;
  chat_mode: string | null;
  sanity_limit: number;
  allow_r18g: boolean;
  allow_setu: boolean;
  admin_ids: number[];
  message_count: number;
  last_activity: string | null;
}

export interface GroupListResponse {
  total: number;
  items: GroupListItem[];
}

export interface GroupDetail extends GroupListItem {
  recent_messages: ChatMessage[];
}

export interface GroupListQuery {
  q?: string;
  enable?: boolean;
  chat_enabled?: boolean;
  limit?: number;
  offset?: number;
}

export interface GroupUpdatePayload {
  name?: string | null;
  enable?: boolean | null;
  enable_chat?: boolean | null;
  chat_mode?: string | null;
  sanity_limit?: number | null;
  allow_r18g?: boolean | null;
  allow_setu?: boolean | null;
  admin_ids?: number[] | null;
}

export interface PrivateMeta {
  statuses: EnumOption[];
}

export interface PrivateMessage {
  message_id: number;
  user_id: number | null;
  bot_send: boolean;
  text: string | null;
  sent_at: string | null;
}

export interface PrivateUserListItem {
  id: number;
  nick_name: string | null;
  status: string;
  enable_chat: boolean;
  sanity_limit: number;
  allow_r18g: boolean;
  message_count: number;
  last_activity: string | null;
}

export interface PrivateUserListResponse {
  total: number;
  items: PrivateUserListItem[];
}

export interface PrivateUserDetail extends PrivateUserListItem {
  recent_messages: PrivateMessage[];
}

export interface PrivateUserListQuery {
  q?: string;
  chat_enabled?: boolean;
  status?: string;
  limit?: number;
  offset?: number;
}

export interface PrivateUserUpdatePayload {
  nick_name?: string | null;
  enable_chat?: boolean | null;
  sanity_limit?: number | null;
  allow_r18g?: boolean | null;
  status?: string | null;
}

export interface FeatureFlag {
  key: string;
  label: string;
  description: string;
  value: boolean | null;
  editable: boolean;
  category: string;
}

export interface FeatureFlagResponse {
  features: FeatureFlag[];
  placeholders: FeatureFlag[];
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const { data } = await client.get<DashboardSummary>('/dashboard/summary');
  return data;
}

export async function fetchGroupMeta(): Promise<GroupMeta> {
  const { data } = await client.get<GroupMeta>('/groups/meta');
  return data;
}

export async function listGroups(params: GroupListQuery): Promise<GroupListResponse> {
  const { data } = await client.get<GroupListResponse>('/groups', { params });
  return data;
}

export async function getGroupDetail(id: number): Promise<GroupDetail> {
  const { data } = await client.get<GroupDetail>(`/groups/${id}`);
  return data;
}

export async function updateGroup(id: number, payload: GroupUpdatePayload): Promise<GroupDetail> {
  const { data } = await client.put<GroupDetail>(`/groups/${id}`, payload);
  return data;
}

export async function fetchPrivateMeta(): Promise<PrivateMeta> {
  const { data } = await client.get<PrivateMeta>('/private/meta');
  return data;
}

export async function listPrivateUsers(params: PrivateUserListQuery): Promise<PrivateUserListResponse> {
  const { data } = await client.get<PrivateUserListResponse>('/private/users', { params });
  return data;
}

export async function getPrivateUserDetail(id: number): Promise<PrivateUserDetail> {
  const { data } = await client.get<PrivateUserDetail>(`/private/users/${id}`);
  return data;
}

export async function updatePrivateUser(
  id: number,
  payload: PrivateUserUpdatePayload
): Promise<PrivateUserDetail> {
  const { data } = await client.put<PrivateUserDetail>(`/private/users/${id}`, payload);
  return data;
}

export async function fetchFeatureFlags(): Promise<FeatureFlagResponse> {
  const { data } = await client.get<FeatureFlagResponse>('/config/features');
  return data;
}

export async function updateFeatureFlag(key: string, value: boolean): Promise<FeatureFlag> {
  const { data } = await client.put<FeatureFlag>(`/config/features/${key}`, { value });
  return data;
}
