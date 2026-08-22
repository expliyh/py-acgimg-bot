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

export interface CommandHistoryItem {
  id: number;
  command: string;
  user_id: number | null;
  chat_id: number | null;
  chat_type: string | null;
  message_id: number | null;
  arguments: string[] | null;
  raw_text: string | null;
  success: boolean;
  error_message: string | null;
  duration_ms: number | null;
  triggered_at: string;
}

export interface CommandHistoryResponse {
  total: number;
  items: CommandHistoryItem[];
  page: number;
  page_size: number;
  pages: number;
}

export interface CommandHistoryQuery {
  command?: string;
  user_id?: number;
  success?: boolean;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
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
  page: number;
  page_size: number;
  pages: number;
}

export interface GroupDetail extends GroupListItem {
  recent_messages: ChatMessage[];
}

export interface GroupListQuery {
  q?: string;
  enable?: boolean;
  chat_enabled?: boolean;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
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
  page: number;
  page_size: number;
  pages: number;
}

export interface PrivateUserDetail extends PrivateUserListItem {
  recent_messages: PrivateMessage[];
}

export interface PrivateUserListQuery {
  q?: string;
  chat_enabled?: boolean;
  status?: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
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

export interface BotTokenInfo {
  configured: boolean;
  token: string | null;
  masked: string | null;
  enabled: boolean | null;
}

export interface PixivTokenItem {
  id: number;
  token: string;
  masked: string;
  enabled: boolean;
}

export interface PixivTokenListResponse {
  total: number;
  items: PixivTokenItem[];
  page: number;
  page_size: number;
  pages: number;
}

export interface IllustrationPreview {
  id: string;
  title: string | null;
  author_id: string;
  author_name: string | null;
  page_count: number;
  sanity_level: number;
  r18g: boolean;
  x_restrict: number;
  tags: string[];
  caption: string | null;
  is_ai: boolean;
  exists: boolean;
  preview_urls: string[];
}

export interface IllustrationImportPayload {
  pixiv_id: number;
  title?: string | null;
  caption?: string | null;
  tags?: string[] | null;
  sanity_level?: number | null;
  r18g?: boolean | null;
  is_ai?: boolean | null;
}

export interface ImportedPageInfo {
  index: number;
  storage_url: string;
  compressed_file_id: string | null;
  original_file_id: string | null;
}

export interface IllustrationImportResult {
  id: string;
  title: string | null;
  author_id: string;
  author_name: string | null;
  page_count: number;
  created: boolean;
  telegram_cache_enabled: boolean;
  pages: ImportedPageInfo[];
}

export interface IllustrationImportTask {
  id: number;
  pixiv_id: string;
  title: string | null;
  status: 'pending' | 'running' | 'success' | 'failed';
  created: boolean | null;
  total_pages: number | null;
  current_page: number | null;
  error_message: string | null;
  result: IllustrationImportResult | null;
  created_at: string;
  finished_at: string | null;
}

export interface IllustrationImportTaskListResponse {
  total: number;
  items: IllustrationImportTask[];
  page: number;
  page_size: number;
  pages: number;
}

export interface ManualIllustrationPayload {
  image: File;
  title: string;
  author_name?: string;
  source_url?: string;
  author_url?: string;
  caption?: string;
  tags?: string;
  is_ai: boolean;
  is_r18: boolean;
  is_r18g: boolean;
}

export interface ManualIllustrationResult {
  id: string;
  title: string;
  storage_url: string;
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
  const { data } = await client.patch<GroupDetail>(`/groups/${id}`, payload);
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
  const { data } = await client.patch<PrivateUserDetail>(`/private/users/${id}`, payload);
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

export async function listCommandHistory(
  params: CommandHistoryQuery
): Promise<CommandHistoryResponse> {
  const { data } = await client.get<CommandHistoryResponse>('/commands/history', { params });
  return data;
}

export async function fetchBotToken(): Promise<BotTokenInfo> {
  const { data } = await client.get<BotTokenInfo>('/bot-tokens');
  return data;
}

export async function setBotToken(token: string, enabled: boolean): Promise<BotTokenInfo> {
  const { data } = await client.put<BotTokenInfo>('/bot-tokens', { token, enabled });
  return data;
}

export async function setBotTokenEnabled(enabled: boolean): Promise<BotTokenInfo> {
  const { data } = await client.patch<BotTokenInfo>('/bot-tokens/status', { enabled });
  return data;
}

export async function deleteBotToken(): Promise<BotTokenInfo> {
  const { data } = await client.delete<BotTokenInfo>('/bot-tokens');
  return data;
}

export async function reloadBotToken(): Promise<BotTokenInfo> {
  const { data } = await client.post<BotTokenInfo>('/bot-tokens/reload');
  return data;
}

export async function listPixivTokens(page = 1, pageSize = 25): Promise<PixivTokenListResponse> {
  const { data } = await client.get<PixivTokenListResponse>('/pixiv-tokens', { params: { page, page_size: pageSize } });
  return data;
}

export async function addPixivToken(token: string, enabled: boolean): Promise<PixivTokenItem> {
  const { data } = await client.post<PixivTokenItem>('/pixiv-tokens', { token, enabled });
  return data;
}

export async function updatePixivToken(id: number, token: string): Promise<PixivTokenItem> {
  const { data } = await client.put<PixivTokenItem>(`/pixiv-tokens/${id}`, { token, enabled: true });
  return data;
}

export async function setPixivTokenEnabled(id: number, enabled: boolean): Promise<PixivTokenItem> {
  const { data } = await client.patch<PixivTokenItem>(`/pixiv-tokens/${id}/status`, { enabled });
  return data;
}

export async function setAllPixivTokensEnabled(enabled: boolean): Promise<PixivTokenListResponse> {
  const { data } = await client.patch<PixivTokenListResponse>('/pixiv-tokens', { enabled });
  return data;
}

export async function deletePixivToken(id: number): Promise<PixivTokenItem> {
  const { data } = await client.delete<PixivTokenItem>(`/pixiv-tokens/${id}`);
  return data;
}

export async function reloadPixivTokens(): Promise<PixivTokenListResponse> {
  const { data } = await client.post<PixivTokenListResponse>('/pixiv-tokens/reload');
  return data;
}

export async function previewIllustration(pixivId: number): Promise<IllustrationPreview> {
  const { data } = await client.post<IllustrationPreview>('/illustrations/preview', { pixiv_id: pixivId });
  return data;
}

export async function importIllustration(
  payload: IllustrationImportPayload
): Promise<IllustrationImportTask> {
  const { data } = await client.post<IllustrationImportTask>('/illustrations/import', payload);
  return data;
}

export async function listIllustrationTasks(page = 1, pageSize = 20): Promise<IllustrationImportTaskListResponse> {
  const { data } = await client.get<IllustrationImportTaskListResponse>('/illustrations/tasks', { params: { page, page_size: pageSize } });
  return data;
}

export async function getIllustrationTask(taskId: number): Promise<IllustrationImportTask> {
  const { data } = await client.get<IllustrationImportTask>(`/illustrations/tasks/${taskId}`);
  return data;
}

export async function importManualIllustration(
  payload: ManualIllustrationPayload
): Promise<ManualIllustrationResult> {
  const body = new FormData();
  Object.entries(payload).forEach(([key, value]) => body.append(key, value instanceof File ? value : String(value)));
  const { data } = await client.post<ManualIllustrationResult>('/illustrations/manual', body, {
    timeout: 30000
  });
  return data;
}
