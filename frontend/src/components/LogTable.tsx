import { useDeferredValue, useMemo, useState } from 'react';
import type { Level, LogEntry } from '../types';

const LEVELS: Level[] = ['FATAL', 'ERROR', 'WARN', 'INFO', 'DEBUG'];

const LEVEL_CLASS: Record<Level, string> = {
  FATAL: 'fatal', ERROR: 'error', WARN: 'warn',
  INFO: 'info', DEBUG: 'debug', TRACE: 'debug', UNKNOWN: 'debug',
};

const PAGE = 100;

export function LogTable({ entries }: { entries: LogEntry[] }) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState<Set<Level>>(new Set());
  const [limit, setLimit] = useState(PAGE);

  // Keeps typing responsive on big logs: the input updates immediately,
  // the (expensive) filtered list catches up a frame later.
  const deferredQuery = useDeferredValue(query);

  const filtered = useMemo(() => {
    const needle = deferredQuery.trim().toLowerCase();
    return entries.filter((e) => {
      if (active.size > 0 && !active.has(e.level)) return false;
      if (!needle) return true;
      return (
        e.message.toLowerCase().includes(needle) ||
        (e.source ?? '').toLowerCase().includes(needle) ||
        e.raw.toLowerCase().includes(needle)
      );
    });
  }, [entries, deferredQuery, active]);

  const toggle = (level: Level) => {
    const next = new Set(active);
    if (next.has(level)) next.delete(level);
    else next.add(level);
    setActive(next);
    setLimit(PAGE);
  };

  const counts = useMemo(() => {
    const out = {} as Record<Level, number>;
    for (const e of entries) out[e.level] = (out[e.level] ?? 0) + 1;
    return out;
  }, [entries]);

  return (
    <div className="panel">
      <h2>
        Log lines
        <span className="muted"> · {filtered.length.toLocaleString()} matching</span>
      </h2>

      <div className="filters">
        <input
          type="search"
          placeholder="Search messages, sources, raw text…"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }}
          aria-label="Search log lines"
        />
        <div className="chips">
          {LEVELS.map((level) => (
            <button
              key={level}
              className={`chip toggle ${LEVEL_CLASS[level]} ${active.has(level) ? 'on' : ''}`}
              onClick={() => toggle(level)}
              disabled={!counts[level]}
            >
              {level} <span className="muted">{counts[level] ?? 0}</span>
            </button>
          ))}
          {active.size > 0 && (
            <button className="chip" onClick={() => setActive(new Set())}>clear</button>
          )}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="muted">No lines match those filters.</p>
      ) : (
        <>
          <div className="logs">
            {filtered.slice(0, limit).map((entry) => (
              <div className="log-row" key={entry.line_number}>
                <span className="ln">{entry.line_number}</span>
                <span className="ts">
                  {entry.timestamp
                    ? new Date(entry.timestamp).toLocaleTimeString()
                    : '—'}
                </span>
                <span className={`badge ${LEVEL_CLASS[entry.level]}`}>{entry.level}</span>
                {entry.source && <span className="src">{entry.source}</span>}
                <span className="msg">{entry.message}</span>
              </div>
            ))}
          </div>
          {limit < filtered.length && (
            <button className="more" onClick={() => setLimit(limit + PAGE * 5)}>
              Show {Math.min(PAGE * 5, filtered.length - limit).toLocaleString()} more
            </button>
          )}
        </>
      )}
    </div>
  );
}
