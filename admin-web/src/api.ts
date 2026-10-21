export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {super(message);this.status = status;}
}
export async function api<T = any>(path: string, body?: unknown, method: 'GET'|'POST' = body === undefined ? 'GET' : 'POST'): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 115_000);
  try {
    const r = await fetch('/api/proxy?path=' + encodeURIComponent(path), {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: {'Accept': 'application/json', ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      signal: controller.signal
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (r.status === 401 && path !== 'admin/me' && path !== 'admin/login') window.dispatchEvent(new Event('betsightly:session-expired'));
      const raw = data.detail ?? data.error ?? data.message;
      const message = Array.isArray(raw) ? raw.map((item: any) => item.msg ?? item.message).join('; ') : (typeof raw === 'string' ? raw : 'The request could not be completed');
      throw new ApiError(message + ' (HTTP ' + r.status + ')', r.status);
    }
    return data as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error instanceof Error && error.name === 'AbortError' ? 'Request timed out. For publishing, check saved tickets before another attempt.' : 'Connection interrupted. If publishing, do not repeat before checking saved tickets.');
  } finally {window.clearTimeout(timeout);}
}
export const isAmbiguous = (error: unknown) => !(error instanceof ApiError) || error.status === 0 || [502,503,504].includes(error.status);
export const tiers = [
  ['banker','Banker'], ['2_odds','2 Odds'], ['5_odds','5 Odds'], ['10_odds','10 Odds'],
  ['over_1_5','Over Goals'], ['rollover','Rollover']
] as const;
