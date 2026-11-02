export const AUTH_EXPIRED_EVENT = 'acgimg:auth-expired';

export function notifyUnauthorized(): void {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}
