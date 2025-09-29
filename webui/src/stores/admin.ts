import { defineStore } from "pinia";
import axios from "axios";

export interface Group {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  tags: string[];
}

export interface PrivateChat {
  id: string;
  username: string;
  alias?: string | null;
  is_muted: boolean;
  last_message_preview?: string | null;
}

export interface FeatureConfig {
  id: string;
  name: string;
  enabled: boolean;
  description: string;
  options: Record<string, string>;
}

export interface AutomationRule {
  id: string;
  name: string;
  trigger: string;
  action: string;
  enabled: boolean;
}

export interface DashboardStats {
  groups: number;
  active_groups: number;
  private_chats: number;
  muted_chats: number;
  automations: number;
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api"
});

export const useAdminStore = defineStore("admin", {
  state: () => ({
    groups: [] as Group[],
    privateChats: [] as PrivateChat[],
    featureConfigs: [] as FeatureConfig[],
    automationRules: [] as AutomationRule[],
    dashboard: null as DashboardStats | null,
    loading: false
  }),
  actions: {
    async refreshDashboard() {
      this.dashboard = (await api.get<DashboardStats>("/dashboard")).data;
    },
    async fetchGroups() {
      this.groups = (await api.get<Group[]>("/groups")).data;
    },
    async createGroup(payload: Partial<Group>) {
      await api.post<Group>("/groups", payload);
      await this.fetchGroups();
      await this.refreshDashboard();
    },
    async updateGroup(id: string, payload: Partial<Group>) {
      await api.put<Group>(`/groups/${id}`, payload);
      await this.fetchGroups();
      await this.refreshDashboard();
    },
    async deleteGroup(id: string) {
      await api.delete(`/groups/${id}`);
      await this.fetchGroups();
      await this.refreshDashboard();
    },
    async fetchPrivateChats() {
      this.privateChats = (await api.get<PrivateChat[]>("/private-chats")).data;
    },
    async createPrivateChat(payload: Partial<PrivateChat>) {
      await api.post<PrivateChat>("/private-chats", payload);
      await this.fetchPrivateChats();
      await this.refreshDashboard();
    },
    async updatePrivateChat(id: string, payload: Partial<PrivateChat>) {
      await api.put<PrivateChat>(`/private-chats/${id}`, payload);
      await this.fetchPrivateChats();
      await this.refreshDashboard();
    },
    async deletePrivateChat(id: string) {
      await api.delete(`/private-chats/${id}`);
      await this.fetchPrivateChats();
      await this.refreshDashboard();
    },
    async fetchFeatureConfigs() {
      this.featureConfigs = (await api.get<FeatureConfig[]>("/features")).data;
    },
    async upsertFeatureConfig(payload: Partial<FeatureConfig>) {
      await api.post<FeatureConfig>("/features", payload);
      await this.fetchFeatureConfigs();
    },
    async deleteFeatureConfig(id: string) {
      await api.delete(`/features/${id}`);
      await this.fetchFeatureConfigs();
    },
    async fetchAutomationRules() {
      this.automationRules = (await api.get<AutomationRule[]>("/automations")).data;
    },
    async createAutomationRule(payload: Partial<AutomationRule>) {
      await api.post<AutomationRule>("/automations", payload);
      await this.fetchAutomationRules();
      await this.refreshDashboard();
    },
    async updateAutomationRule(id: string, payload: Partial<AutomationRule>) {
      await api.put<AutomationRule>(`/automations/${id}`, payload);
      await this.fetchAutomationRules();
      await this.refreshDashboard();
    },
    async deleteAutomationRule(id: string) {
      await api.delete(`/automations/${id}`);
      await this.fetchAutomationRules();
      await this.refreshDashboard();
    }
  }
});
