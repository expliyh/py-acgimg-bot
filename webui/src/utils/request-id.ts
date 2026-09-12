interface RequestIdCrypto {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => Uint8Array;
}

let fallbackCounter = 0;

function formatUuid(bytes: Uint8Array): string {
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Generate an idempotency key in browsers without crypto.randomUUID(). */
export function createRequestId(
  cryptoSource: RequestIdCrypto | undefined = (globalThis as { crypto?: RequestIdCrypto }).crypto,
): string {
  if (typeof cryptoSource?.randomUUID === "function") return cryptoSource.randomUUID();

  if (typeof cryptoSource?.getRandomValues === "function") {
    const bytes = cryptoSource.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return formatUuid(bytes);
  }

  const timestamp = Date.now().toString(36);
  const counter = (fallbackCounter++).toString(36).padStart(4, "0");
  const random = Math.random().toString(36).slice(2, 12);
  return `${timestamp}-${counter}-${random}`;
}
