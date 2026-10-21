// Same-origin BFF for the existing FastAPI administrator session.
// The browser NEVER receives the Render origin or a backend credential.
const GET = new Set([
 'admin/config','admin/me','analytics','status','market-readiness','daily',
 'manual-tiers','homepage-campaign','content','publications','settings','referrals'
]);
const POST = new Set([
 'admin/login','admin/logout','generate','retry','manual-tiers/import-code',
 'manual-tiers/preview','manual-tiers/inspect','manual-tiers/publish','manual-tiers/publish-imported',
 'homepage-campaign','settings','referrals'
]);
function allowed(method, route) {
 return method === 'GET' ? GET.has(route) :
   method === 'POST' && (POST.has(route) || /^content\/[0-9]+\/(approve|cancel|publish)$/.test(route));
}

// Vercel normally parses JSON into req.body. Some adapters surface it as
// a UTF-8 Buffer or JSON string. Normalize those formats explicitly rather
// than silently forwarding {} and reporting a real password as incorrect.
async function decodeBody(req) {
  let value = req.body;
  if (value == null && typeof req[Symbol.asyncIterator] === 'function') {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) {
      size += Buffer.byteLength(chunk);
      if (size > 16384) throw Error('Request body too large');
      chunks.push(Buffer.from(chunk));
    }
    value = Buffer.concat(chunks).toString('utf8');
  }
  if (Buffer.isBuffer(value)) value = value.toString('utf8');
  if (typeof value === 'string') {
    if (value.length > 16384) throw Error('Request body too large');
    try {value = JSON.parse(value);} catch {throw Error('Request body is not valid JSON');}
  }
  if (value == null) throw Error('Missing request body');
  if (typeof value !== 'object' || Array.isArray(value)) throw Error('Expected JSON object');
  return value;
}
export default async function handler(req, res) {
  res.setHeader('Cache-Control','no-store');
  res.setHeader('X-Content-Type-Options','nosniff');
  const originText = process.env.ADMIN_BACKEND_ORIGIN;
  if (!originText) return res.status(503).json({detail:'Admin API proxy is not configured.'});
  let backend;
  try {
    backend = new URL(originText);
    if(backend.protocol !== 'https:' || backend.pathname !== '/' || backend.search || backend.hash || backend.username || backend.password || !/^(betsightly-api|betsightly-backend)\.onrender\.com$/.test(backend.hostname)) throw Error('invalid');
  } catch {return res.status(503).json({detail:'Admin API proxy origin is invalid.'});}
  const incoming = new URL(req.url, 'https://' + req.headers.host);
  const raw = incoming.searchParams.get('path') || '';
  const [route, query = ''] = raw.split('?');
  if (!/^[a-z0-9/_-]{1,100}$/.test(route) || !allowed(req.method,route) || raw.split('?').length > 2) {
    return res.status(404).json({detail:'Unknown admin operation.'});
  }
  // Every browser mutation MUST originate from the exact Vercel admin host.
  if (req.method !== 'GET') {
    const expected = 'https://' + req.headers.host;
    if (req.headers.origin !== expected || !/^(?:[a-z0-9-]+\.vercel\.app|admin\.betsightly\.com)$/.test(req.headers.host || '')) {
      return res.status(403).json({detail:'Admin request origin rejected.'});
    }
  }
  const upstream = new URL('/api/growth/' + route, backend);
  const requestedQuery = new URLSearchParams(query);
  const permitted = new Set(['days','start','end','limit','platform','status','publish','force']);
  for (const [key,value] of requestedQuery) {
    if (!permitted.has(key) || value.length > 100) return res.status(400).json({detail:'Unsupported query argument.'});
    upstream.searchParams.append(key,value);
  }
  let payload;
  if (req.method === 'POST') {
    try { payload = await decodeBody(req); }
    catch { return res.status(400).json({detail:'Invalid request format. No change was submitted.'}); }
    if (route === 'admin/login' && (typeof payload.password !== 'string' || payload.password.length === 0)) {
      return res.status(400).json({detail:'The admin password was not received. Please refresh and retry once.'});
    }
  }
  const headers = {'accept':'application/json'};
  if (req.headers.cookie) headers.cookie = req.headers.cookie;
  if (req.headers['user-agent']) headers['user-agent'] = req.headers['user-agent'];
  if (req.method === 'POST') {
    headers['content-type']='application/json';
    // Validate the original browser origin above, then present the proxy as same-origin to FastAPI.
    headers.origin = backend.origin;
  }
  try {
    const upstreamResponse = await fetch(upstream, {
      method: req.method, headers,
      ...(req.method === 'POST' ? {body: JSON.stringify(payload)} : {}),
      redirect:'manual', signal: AbortSignal.timeout(110000)
    });
    const cookie = upstreamResponse.headers.get('set-cookie');
    if (cookie) res.setHeader('Set-Cookie',cookie);
    const contentType = upstreamResponse.headers.get('content-type') || 'application/json';
    res.status(upstreamResponse.status).setHeader('Content-Type',contentType);
    res.send(await upstreamResponse.text());
  } catch {
    // A timed-out publication may already have committed. Never auto-retry POSTs.
    res.status(502).json({detail:'Backend request interrupted. For publishing, check saved tickets before trying again.'});
  }
}