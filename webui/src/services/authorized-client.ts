import type { AxiosInstance } from 'axios';

import { notifyUnauthorized } from './auth-events.ts';

/** Redirect to the login page when an authenticated API call loses its session. */
export function installUnauthorizedInterceptor(client: AxiosInstance): void {
  client.interceptors.response.use(
    (response) => response,
    (error) => {
      if (error?.response?.status === 401) notifyUnauthorized();
      return Promise.reject(error);
    }
  );
}
