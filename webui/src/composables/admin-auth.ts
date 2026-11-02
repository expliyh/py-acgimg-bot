import { reactive, readonly } from 'vue';

import {
  changeAdminPassword,
  fetchCurrentAdmin,
  loginAdmin,
  logoutAdmin,
  type AdminIdentity
} from '@/services/auth-api';

interface AdminAuthState {
  checked: boolean;
  authenticated: boolean;
  username: string | null;
}

const state = reactive<AdminAuthState>({
  checked: false,
  authenticated: false,
  username: null
});

let pendingCheck: Promise<boolean> | null = null;

function applyIdentity(identity: AdminIdentity): boolean {
  state.checked = true;
  state.authenticated = identity.authenticated;
  state.username = identity.username;
  return identity.authenticated;
}

export function markUnauthenticated(): void {
  state.checked = true;
  state.authenticated = false;
  state.username = null;
}

export async function refreshAdminAuth(force = false): Promise<boolean> {
  if (state.checked && !force) return state.authenticated;
  if (pendingCheck) return pendingCheck;

  pendingCheck = fetchCurrentAdmin()
    .then(applyIdentity)
    .catch(() => {
      markUnauthenticated();
      return false;
    })
    .finally(() => {
      pendingCheck = null;
    });

  return pendingCheck;
}

export async function signIn(username: string, password: string): Promise<AdminIdentity> {
  const identity = await loginAdmin(username, password);
  applyIdentity(identity);
  return identity;
}

export async function signOut(): Promise<void> {
  try {
    await logoutAdmin();
  } finally {
    markUnauthenticated();
  }
}

export async function updatePassword(currentPassword: string, newPassword: string): Promise<void> {
  const identity = await changeAdminPassword(currentPassword, newPassword);
  applyIdentity(identity);
}

export function useAdminAuth() {
  return {
    state: readonly(state),
    refreshAdminAuth,
    signIn,
    signOut,
    updatePassword,
    markUnauthenticated
  };
}
