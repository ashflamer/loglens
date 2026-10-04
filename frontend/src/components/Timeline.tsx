import { useMemo, useState } from 'react';
import type { Bucket, Level } from '../types';

const STACK: Level[] = ['FATAL', 'ERROR', 'WARN', 'INFO', 'DEBUG', 'TRACE', 'UNKNOWN'];

const COLOR: Record<Level, string> = {
  FATAL: '#ff4d6d', ERROR: '#ff7b54', WARN: '#ffc93c',
  INFO: '#4da3ff', DEBUG: '#5c6f8a', TRACE: '#3d4a5e', UNKNOWN: '#3d4a5e',
};

/** Hand-rolled SVG chart — no charting library, no 300 kB of dependencies. */
export function Timeline({ buckets }: { buckets: Bucket[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const peak = useMemo(
    () => Math.max(1, ...buckets.map((b) => b.total)),
    [buckets],
  );

  if (buckets.length === 0) {
    return (
      <div className="panel">
        <h2>Timeline</h2>
        <p className="muted">No timestamps found in this log, so there's nothing to plot.</p>
      </div>
    );
  }

  const width = 1000;
  const height = 180;
  const gap = buckets.length > 120 ? 0 : 1;
  const barWidth = width / buckets.length;
  const active = hover !== null ? buckets[hover] : null;

  return (
    <div className="panel">
      <h2>
        Timeline
        <span className="muted"> · {buckets.length} buckets · red marks a detected anomaly</span>
      </h2>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart"
        preserveAspectRatio="none"
        role="img"
        aria-label="Log volume over time, stacked by severity"
        onMouseLeave={() => setHover(null)}
      >
        {buckets.map((bucket, i) => {
          let y = height;
          const segments = STACK.map((level) => {
            const count = bucket.by_level[level] ?? 0;
            if (!count) return null;
            const h = (count / peak) * (height - 8);
            y -= h;
            return (
              <rect key={level} x={i * barWidth} y={y} width={Math.max(barWidth - gap, 0.5)}
                height={h} fill={COLOR[level]} />
            );
          });

          return (
            <g key={bucket.start} onMouseEnter={() => setHover(i)}>
              <rect x={i * barWidth} y={0} width={Math.max(barWidth, 1)} height={height}
                fill={hover === i ? 'rgba(255,255,255,.07)' : 'transparent'} />
              {segments}
              {bucket.is_anomaly && (
                <rect x={i * barWidth} y={0} width={Math.max(barWidth - gap, 1)} height={3}
                  fill="#ff4d6d" />
              )}
            </g>
          );
        })}
      </svg>

      <div className="chart-footer">
        {active ? (
          <span>
            <strong>{new Date(active.start).toLocaleTimeString()}</strong> · {active.total} lines
            {Object.entries(active.by_level).map(([level, count]) => (
              <span key={level} className="chip" style={{ borderColor: COLOR[level as Level] }}>
                {level} {count}
              </span>
            ))}
            {active.is_anomaly && <span className="chip bad">anomaly z={active.z_score}</span>}
          </span>
        ) : (
          <span className="muted">
            {new Date(buckets[0].start).toLocaleString()} →{' '}
            {new Date(buckets[buckets.length - 1].start).toLocaleString()}
          </span>
        )}
      </div>
    </div>
  );
}
