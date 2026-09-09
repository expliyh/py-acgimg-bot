export function shouldRetainActionRequest(status: string): boolean {
  return status === "uncertain";
}
