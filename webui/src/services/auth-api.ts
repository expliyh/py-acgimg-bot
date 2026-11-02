import axios from 'axios';

export interface AdminIdentity {
  authenticated: boolean;
  username: string | null;
}

const client = axios.create({
  baseURL: '/api/auth',
  timeout: 15000,
  withCredentials: true
});

export async function loginAdmin(username: string, password: string): Promise<AdminIdentity> {
  const { data } = await client.post<AdminIdentity>('/login', { username, password });
  return data;
}

export async function fetchCurrentAdmin(): Promise<AdminIdentity> {
  const { data } = await client.get<AdminIdentity>('/me');
  return data;
}

export async function logoutAdmin(): Promise<AdminIdentity> {
  const { data } = await client.post<AdminIdentity>('/logout');
  return data;
}

export async function changeAdminPassword(
  currentPassword: string,
  newPassword: string
): Promise<AdminIdentity> {
  const { data } = await client.post<AdminIdentity>('/password', {
    current_password: currentPassword,
    new_password: newPassword
  });
  return data;
}
