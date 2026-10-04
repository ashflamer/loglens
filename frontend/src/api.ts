import type { AnalysisResult } from './types';

/** Relative URLs only — Vite proxies /api to the backend in dev, and in
 *  production the same origin serves both. No hardcoded hosts anywhere. */
const BASE = '/api';

async function unwrap(response: Response): Promise<AnalysisResult> {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return response.json();
}

export const fetchSample = (lines = 1200) =>
  fetch(`${BASE}/sample?lines=${lines}`).then(unwrap);

export const analyseText = (text: string) =>
  fetch(`${BASE}/analyse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).then(unwrap);

export const uploadFile = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${BASE}/upload`, { method: 'POST', body: form }).then(unwrap);
};
