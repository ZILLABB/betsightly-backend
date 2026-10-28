/** Versioned private V2 NBA backup handler for the separate Vercel scheduler.
 * Never make this a public Blob, never emit data/tokens to logs or responses.
 * Deploy as a separate /api/backup-v2 route and verify privately BEFORE
 * considering promotion over the already working /api/backup V1 cron.
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import { put, get } from '@vercel/blob';

const HOST = 'https://betsightly-nba-research-stage-20261025.onrender.com';
const EXPORT = HOST + '/api/growth/internal/nba-research/backup-full';
const ACK = HOST + '/api/growth/internal/nba-research/backup-full/ack';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function authorized(given, expected) {
  if (typeof given !== 'string' || typeof expected !== 'string') return false;
  const a = Buffer.from(given), b = Buffer.from(expected);
  return a.length >= 39 && a.length === b.length && timingSafeEqual(a, b);
}
function bounded(n) { return Number.isSafeInteger(n) && n >= 0 && n <= 10000; }

// Keep the NBA V2 backup as the primary job. This is a separate,
 // source-freshness-acknowledged private Blob snapshot within the same cron.
async function backupLicensedHistory(token, blobToken) {
  const exportUrl = HOST + '/api/growth/internal/nba-research/backup-licensed';
  const ackUrl = HOST + '/api/growth/internal/nba-research/backup-licensed/ack';
  const response = await fetch(exportUrl, {
    method:'GET', redirect:'error', signal:AbortSignal.timeout(130000),
    headers:{'accept':'application/json','x-betsightly-nba-backup-token':token}
  });
  if (!response.ok) throw new Error('LICENSED_HISTORY_EXPORT_UNAVAILABLE');
  const raw = Buffer.from(await response.arrayBuffer());
  if (raw.byteLength < 128 || raw.byteLength > 40_000_000)
    throw new Error('LICENSED_HISTORY_EXPORT_BYTES_INVALID');
  const body = JSON.parse(raw.toString('utf8'));
  const kinds = ['rights','imports','games','probes'];
  if (body.version !== 'betsightly-basketball-private-licensed-history-v1' ||
      body.research_only !== true || body.not_bookable !== true ||
      !/^[0-9a-f]{64}$/.test(body.sha256 || '') ||
      !/^[0-9a-f]{64}$/.test(body.tables_sha256 || '') ||
      !body.tables || !body.counts ||
      kinds.some(k => !Array.isArray(body.tables[k]) ||
                 !bounded(body.counts[k]) ||
                 body.counts[k] !== body.tables[k].length)) {
    throw new Error('LICENSED_HISTORY_ENVELOPE_INVALID');
  }
  const filename = 'basketball-licensed-history-v1/' +
                   new Date().toISOString().replace(/[:.]/g,'-') + '.json';
  const blob = await put(filename, raw, {
    access:'private', contentType:'application/json',
    addRandomSuffix:true, token:blobToken
  });
  const retrieved = await get(blob.url, {access:'private', token:blobToken});
  if (!retrieved?.stream) throw new Error('LICENSED_HISTORY_BLOB_MISSING');
  const readback = Buffer.from(await new Response(retrieved.stream).arrayBuffer());
  if (readback.byteLength !== raw.byteLength || hash(readback) !== hash(raw))
    throw new Error('LICENSED_HISTORY_BLOB_READBACK_HASH_MISMATCH');
  const ack = await fetch(ackUrl, {
    method:'POST', redirect:'error', signal:AbortSignal.timeout(60000),
    headers:{'content-type':'application/json',
             'x-betsightly-nba-backup-token':token},
    body: JSON.stringify({
      verified:true, store:'private_vercel_blob_licensed_history_v1',
      tables_sha256:body.tables_sha256, blob_sha256:hash(raw),
      counts:body.counts, export_created_at:body.created_at
    })
  });
  if (!ack.ok) throw new Error('LICENSED_HISTORY_BLOB_ACK_FAILED');
  const confirmed = await ack.json();
  if (confirmed.status !== 'verified_licensed_history_private_blob_readback')
    throw new Error('LICENSED_HISTORY_ACK_NOT_CONFIRMED');
  return confirmed.status;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'private, no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method !== 'GET') return res.status(405).json({status:'method_not_allowed'});
  const cron = process.env.CRON_SECRET || '';
  const token = process.env.NBA_BACKUP_JOB_TOKEN || '';
  const blobToken = process.env.BLOB_READ_WRITE_TOKEN || '';
  if (cron.length < 32 || token.length < 48 || !blobToken ||
      !authorized(req.headers.authorization || '', 'Bearer ' + cron)) {
    return res.status(404).json({status:'not_found'});
  }
  try {
    const upstream = await fetch(EXPORT, {
      method:'GET', headers:{'accept':'application/json',
         'x-betsightly-nba-backup-token':token},
      redirect:'error', signal:AbortSignal.timeout(130000)
    });
    if (!upstream.ok) return res.status(502).json({status:'export_not_verified'});
    const raw = Buffer.from(await upstream.arrayBuffer());
    if (raw.byteLength < 128 || raw.byteLength > 30_000_000)
      return res.status(502).json({status:'export_size_invalid'});
    const data = JSON.parse(raw.toString('utf8'));
    if (data.version !== 'betsightly-nba-private-full-recovery-v2' ||
        data.research_only !== true || data.not_bookable !== true ||
        !Array.isArray(data.job_receipts) ||
        data.job_receipts.length !== data.job_receipt_count ||
        !bounded(data.job_receipt_count) ||
        !bounded(data.portable_backup_v1?.market_receipt_count) ||
        !/^[0-9a-f]{64}$/.test(data.sha256 || '') ||
        !/^[0-9a-f]{64}$/.test(data.portable_backup_v1?.archive_digest || '')) {
      return res.status(502).json({status:'full_recovery_envelope_invalid'});
    }
    const filename = 'nba-private-v2/' + new Date().toISOString().replace(/[:.]/g,'-') + '.json';
    const saved = await put(filename, raw, {
      access:'private', contentType:'application/json',
      addRandomSuffix:true, token:blobToken
    });
    const restored = await get(saved.url, {access:'private', token:blobToken});
    if (!restored?.stream) throw new Error('NBA_BLOB_READBACK_EMPTY');
    const reread = Buffer.from(await new Response(restored.stream).arrayBuffer());
    if (reread.byteLength !== raw.byteLength ||
        hash(reread) !== hash(raw)) throw new Error('NBA_BLOB_READBACK_HASH_MISMATCH');
    const ack = await fetch(ACK, {
      method:'POST', redirect:'error', signal:AbortSignal.timeout(60000),
      headers: {'content-type':'application/json',
        'x-betsightly-nba-backup-token':token},
      body: JSON.stringify({
        verified:true,store:'private_vercel_blob_v2',
        archive_digest:data.portable_backup_v1.archive_digest,
        blob_sha256:hash(raw),
        market_receipt_count:data.portable_backup_v1.market_receipt_count,
        job_receipt_count:data.job_receipt_count,
        last_job_id:data.job_receipts.at(-1)?.id || 0
      })
    });
    if (!ack.ok) throw new Error('NBA_BLOB_BACKUP_ACK_FAILED');
    const receipt = await ack.json();
    if (receipt.status !== 'verified_full_private_blob_readback') {
      throw new Error('NBA_BLOB_BACKUP_ACK_UNVERIFIED');
    }
    // Separate licensed-history/rights source snapshot; failure is explicit.
    // NBA V2 archive above remains stored and independently ACKed.
    const historyStatus = await backupLicensedHistory(token, blobToken);
    // Do not disclose private URL, source records, grants or tokens.
    return res.status(200).json({status:'verified_full_private_blob_readback',
      licensed_history_status:historyStatus,
      research_only:true, not_bookable:true,
      job_receipt_count:data.job_receipt_count,
      market_receipt_count:data.portable_backup_v1.market_receipt_count});
  } catch (error) {
    console.error('Private NBA V2 backup failed: ' +
      (error instanceof SyntaxError ? 'invalid_json' : 'backup_or_readback_failed'));
    return res.status(503).json({status:'full_private_backup_failed'});
  }
}
