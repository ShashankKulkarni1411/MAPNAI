// Thin fetch wrapper. Errors become ApiError with the HTTP status so screens can pick plain-words copy.
import { useSession } from '@/state/session';

export type ApiMode = 'mock' | 'hybrid' | 'live';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
export const API_MODE: ApiMode = ((): ApiMode => {
  const m = process.env.EXPO_PUBLIC_API_MODE;
  return m === 'hybrid' || m === 'live' ? m : 'mock';
})();

export class ApiError extends Error {
  constructor(public status: number, message: string, public offline = false) {
    super(message);
  }
}

type Opts = { method?: string; body?: unknown; query?: Record<string, string | number | boolean | undefined>; timeoutMs?: number };

export async function http<T>(path: string, opts: Opts = {}): Promise<T> {
  const q = opts.query
    ? '?' +
      Object.entries(opts.query)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : '';
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 15000);
  const token = useSession.getState().accessToken;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}${q}`, {
      method: opts.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: ctrl.signal,
    });
  } catch (e) {
    throw new ApiError(0, 'network', true);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = j?.error?.message ?? j?.detail ?? msg;
    } catch {}
    throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

// Plain-words copy for an error (spec §29: no codes)
export function errorCopy(e: unknown, fallback = "Couldn't load. Try again."): string {
  if (e instanceof ApiError) {
    if (e.offline) return "You're offline.";
    if (e.status === 503) return 'Personalization is temporarily unavailable.';
  }
  return fallback;
}
