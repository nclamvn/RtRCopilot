// TIP-012 Task 5 — S3 upload-accept latency for a 1 MB body.
// Streams a 1 MB payload to POST /api/v1/files/uploads through the ingress and
// measures the accept (HTTP 202) latency: stream receive + malware-scan hand-off
// + object store + upload_session/ingestion_job insert + audit. The heavy
// parse/rendition work is async in the worker and NOT in this number.
//
// Tunables (env): VUS (default 5), DURATION (default 30s),
//   UPLOAD_TARGET_ID (optional; else discovered via /upload-targets).

import http from 'k6/http';
import { check, sleep } from 'k6';
import {
  BASE, login, firstUploadTarget, uploadDuration, errors, SUMMARY_TREND_STATS,
} from './lib/common.js';

const VUS = Number(__ENV.VUS || 5);
const DURATION = __ENV.DURATION || '30s';

// 1 MB body built once in the init context (shared, read-only).
const PAYLOAD = new Uint8Array(1024 * 1024).fill(65).buffer; // 1 MiB of 'A'

export const options = {
  insecureSkipTLSVerify: true,
  summaryTrendStats: SUMMARY_TREND_STATS,
  scenarios: {
    upload_stream: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
};

export function setup() {
  const cookie = login();
  const target = __ENV.UPLOAD_TARGET_ID || firstUploadTarget(cookie);
  if (!target) {
    throw new Error('no upload target available (seed a source or set UPLOAD_TARGET_ID)');
  }
  return { cookie, target };
}

export default function (data) {
  const name = `lt-${__VU}-${__ITER}-${Date.now()}`;
  const res = http.post(`${BASE}/api/v1/files/uploads`, PAYLOAD, {
    headers: {
      Cookie: data.cookie,
      'Content-Type': 'application/octet-stream',
      'X-Parent-Resource-ID': data.target,
      'X-Logical-Name': name,
      'X-Original-Filename': `${name}.txt`,
      'X-Declared-MIME': 'text/plain',
    },
    tags: { name: 'upload' },
  });
  uploadDuration.add(res.timings.duration);
  const ok = check(res, { 'upload 202': (r) => r.status === 202 });
  errors.add(!ok);
  sleep(0.2 + Math.random() * 0.3);
}
