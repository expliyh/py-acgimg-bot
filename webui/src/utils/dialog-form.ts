import type {
  GroupDetail,
  GroupUpdatePayload,
  PrivateUserDetail,
  PrivateUserUpdatePayload,
} from '../services/api';

export function groupFormSnapshot(group: GroupDetail | null): GroupUpdatePayload {
  if (!group) return {};

  return {
    name: group.name,
    enable: group.enable,
    enable_chat: group.enable_chat,
    chat_mode: group.chat_mode,
    sanity_limit: group.sanity_limit,
    allow_r18g: group.allow_r18g,
    allow_setu: group.allow_setu,
    admin_ids: [...group.admin_ids],
  };
}

export function privateUserFormSnapshot(user: PrivateUserDetail | null): PrivateUserUpdatePayload {
  if (!user) return {};

  return {
    nick_name: user.nick_name,
    enable_chat: user.enable_chat,
    sanity_limit: user.sanity_limit,
    allow_r18g: user.allow_r18g,
    status: user.status,
  };
}

export function normalizeAdminIds(values: readonly unknown[] | null | undefined): number[] {
  return (values ?? [])
    .map((value) => {
      if (typeof value === 'number') {
        return Number.isSafeInteger(value) && value >= 0 ? value : null;
      }
      if (typeof value !== 'string' || !/^\d+$/.test(value)) return null;

      const parsed = Number(value);
      return Number.isSafeInteger(parsed) ? parsed : null;
    })
    .filter((value): value is number => value !== null);
}
