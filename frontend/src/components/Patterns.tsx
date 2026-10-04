import { Fragment, useState } from 'react';
import type { Level, Pattern } from '../types';

const LEVEL_CLASS: Record<Level, string> = {
  FATAL: 'fatal', ERROR: 'error', WARN: 'warn',
  INFO: 'info', DEBUG: 'debug', TRACE: 'debug', UNKNOWN: 'debug',
};

export function Patterns({ patterns }: { patterns: Pattern[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (patterns.length === 0) return null;
  const peak = patterns[0].count;

  return (
    <div className="panel">
      <h2>
        Patterns
        <span className="muted"> · messages collapsed by shape, loudest first</span>
      </h2>
      <table className="patterns">
        <thead>
          <tr>
            <th>Level</th>
            <th>Template</th>
            <th className="num">Count</th>
            <th className="num">Share</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {patterns.map((p) => (
            <Fragment key={p.template}>
              <tr
                onClick={() => setOpen(open === p.template ? null : p.template)}
                className="clickable"
              >
                <td><span className={`badge ${LEVEL_CLASS[p.level]}`}>{p.level}</span></td>
                <td className="mono">{p.template}</td>
                <td className="num">{p.count.toLocaleString()}</td>
                <td className="num">
                  <div className="share">
                    <div className="share-bar" style={{ width: `${(p.count / peak) * 100}%` }} />
                    <span>{p.share}%</span>
                  </div>
                </td>
                <td className="num muted">{open === p.template ? '▾' : '▸'}</td>
              </tr>
              {open === p.template && (
                <tr className="detail">
                  <td colSpan={5}>
                    <div className="examples">
                      {p.examples.map((ex, i) => (
                        <code key={i}>{ex}</code>
                      ))}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
