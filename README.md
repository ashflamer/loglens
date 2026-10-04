# loglens

**Drop in a log file, get answers.** loglens auto-detects the format, collapses thousands of lines into a handful of message patterns, plots volume over time, and flags the windows where something actually went wrong.

[![CI](https://github.com/ashflamer/loglens/actions/workflows/ci.yml/badge.svg)](https://github.com/ashflamer/loglens/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![Tests: 82](https://img.shields.io/badge/tests-82-brightgreen.svg)](backend/tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

FastAPI + React + TypeScript. No database, no account, no log shipping — point it at a file and it works.

---

## The problem

You have a 50 MB log file and a customer complaining about "around 2pm". `grep ERROR` returns 4,000 lines. Scrolling is hopeless, and standing up an ELK stack for a one-off investigation is absurd.

loglens turns those 4,000 lines into **12 distinct message patterns** and points at the four-minute window where the error rate went 20x above baseline.

## What it does

| | |
| --- | --- |
| **Auto-detects format** | JSON lines · nginx/Apache access logs · syslog · logfmt · plain text. No configuration. |
| **Clusters messages** | `User 4182 failed login from 10.0.0.7` and 2,000 siblings collapse into one row: `User <NUM> failed login from <IP>` ×2001. |
| **Flags anomalies** | Modified z-score over error volume per time bucket, plus detection of windows where the service went *silent*. |
| **Plots a timeline** | Stacked-by-severity SVG chart, auto-bucketed, anomalies marked in red. |
| **Filters fast** | Full-text search and level toggles over the parsed entries. |

## Quick start

```bash
git clone https://github.com/ashflamer/loglens && cd loglens

# Docker — the whole stack on http://localhost:8080
docker compose up --build
```

Or run the two halves yourself:

```bash
# backend → http://localhost:8000  (docs at /docs)
cd backend && pip install -r requirements-dev.txt && uvicorn app.api:app --reload

# frontend → http://localhost:5173
cd frontend && npm install && npm run dev
```

The UI loads a seeded demo log on first paint — a quiet checkout service, a four-minute database incident, then recovery — so there's something to look at before you upload anything. Then drag any log file onto the window.

Sample files to try live in [`samples/`](samples/).

## API

```bash
# analyse a file
curl -F "file=@/var/log/app.log" http://localhost:8000/api/upload | jq '.summary'

# analyse raw text
curl -X POST http://localhost:8000/api/analyse \
  -H 'Content-Type: application/json' \
  -d '{"text":"2026-01-14T09:12:03Z ERROR [api] db unreachable"}'

# the seeded demo
curl http://localhost:8000/api/sample | jq '.anomalies'
```

| Endpoint | Purpose |
| --- | --- |
| `POST /api/analyse` | Analyse raw log text |
| `POST /api/upload` | Analyse an uploaded file (25 MB cap) |
| `GET /api/sample` | Seeded demo log, already analysed |
| `GET /api/health` | Liveness probe |
| `GET /docs` | Interactive OpenAPI docs, free from FastAPI |

## How it works

### 1. Format detection by vote

Each parser is asked to claim a 200-line sample. The one that parses the highest share wins — but only if it clears **60% confidence**, otherwise the generic parser takes over. That bar matters: the generic parser matches almost anything, so without it, one stray JSON line in a plaintext file would hijack the whole run. (There's a test for exactly that.)

Lines the chosen parser rejects — stack traces, blank-ish junk, a rogue format — still go through the generic fallback rather than being silently dropped, and get counted in `unparsed_lines`. **Nothing disappears.**

### 2. Message templating

```python
"User 4182 failed login from 10.0.0.7"   ─┐
"User 9931 failed login from 10.0.2.44"  ─┼─→  "User <NUM> failed login from <IP>"  ×2001
"User 7765 failed login from 10.0.1.9"   ─┘
```

Ordered regex substitution replaces UUIDs, IPs, emails, URLs, timestamps, hex, hashes, quantities and bare numbers with placeholders. **Order matters** — UUID before hex, IP before number — or the broader rule eats the narrower one. It's the cheap cousin of [Drain](https://github.com/logpai/Drain3), and on real logs it collapses volume 50–200x.

### 3. Anomaly detection with MAD, not standard deviation

The obvious approach — flag buckets more than 2.5σ above the mean — **fails on exactly the case you care about**. A single catastrophic spike inflates σ so much that the spike itself scores below threshold and hides.

So loglens uses a **modified z-score** built on the median and the Median Absolute Deviation:

```
z = (count − median) / (1.4826 × MAD)
```

MAD has a 50% breakdown point: up to half your data can be garbage before it budges. There's a test asserting a `[1,1,1,1,1,1,1,1,1,500]` series flags the 500 — which the mean/σ version misses.

Two refinements that came out of using it on real data:

- **MAD collapses to zero** whenever over half the buckets are identical (very common — lots of quiet windows with zero errors). It falls back to standard deviation there rather than treating every error as infinitely anomalous.
- **An absolute floor.** "1 error against a baseline of 0" is statistically extreme and operationally meaningless. A spike needs at least 3 errors, and at least 2 above the median, before it's reported.

It also flags **silence**: a bucket with zero lines in a service that normally logs 40/window is usually worse news than an error spike.

### 4. Timeline bucketing

Bucket width is chosen from a ladder of human-friendly intervals (1s, 5s, 30s, 1m, 5m, 1h, …) targeting ~60 buckets for whatever span the log covers. Empty buckets are emitted explicitly, so a gap in the chart is a real gap and not a missing bar.

## Architecture

```
backend/
  app/
    models.py     pydantic schemas + level normalisation (WARNING→WARN, CRIT→FATAL…)
    parsers.py    5 parsers + confidence-based format detection
    analysis.py   templating, bucketing, MAD anomaly detection
    sample.py     seeded demo log generator
    api.py        FastAPI routes
  tests/          82 tests
frontend/
  src/
    components/   StatCards · Timeline · Anomalies · Patterns · LogTable
    api.ts        relative URLs only
    types.ts      mirrors the pydantic models
```

**No chart library.** The timeline is hand-written SVG — a stacked bar chart is about 40 lines, and it keeps the bundle at **49 kB gzipped** instead of pulling in 300 kB of Chart.js.

**No hardcoded hosts.** The client only ever calls `/api/...`. Vite proxies that to the backend in dev; nginx proxies it in production. There is no CORS configuration to get wrong and nothing to change between environments.

**Responsive filtering.** The log table uses `useDeferredValue`, so typing in the search box stays smooth even when the filter is churning through thousands of entries.

## Testing

```bash
cd backend && pytest        # 82 tests
cd frontend && npm run typecheck
```

The suite covers the stuff that actually breaks: timestamp parsing across 7 formats, epoch-seconds vs epoch-millis, year-less syslog dates, invalid UTF-8 uploads, empty files, logs with no timestamps at all, and the statistical edge cases in the anomaly detector.

## Roadmap

- [ ] Streaming analysis for files larger than memory
- [ ] Saved investigations with shareable URLs
- [ ] Trace-ID correlation across services
- [ ] `loglens` CLI that reuses the same analysis engine
- [ ] Drain3-style hierarchical clustering to replace the regex templater

## License

MIT © ashflamer
