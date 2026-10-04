import type { Summary } from '../types';

const fmt = (n: number) => n.toLocaleString();

function duration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function StatCards({ summary }: { summary: Summary }) {
  const errorTone =
    summary.error_rate >= 10 ? 'bad' : summary.error_rate >= 2 ? 'warn' : 'good';

  const cards = [
    { k: 'Lines parsed', v: fmt(summary.parsed_lines), n: `${fmt(summary.unparsed_lines)} fell back` },
    { k: 'Format', v: summary.detected_format, n: 'auto-detected' },
    { k: 'Error rate', v: `${summary.error_rate}%`, n: 'of all lines', tone: errorTone },
    { k: 'Unique patterns', v: fmt(summary.unique_patterns), n: `from ${fmt(summary.parsed_lines)} lines` },
    { k: 'Time span', v: duration(summary.duration_seconds), n: summary.lines_per_minute ? `${fmt(Math.round(summary.lines_per_minute))} lines/min` : '' },
  ];

  return (
    <div className="cards">
      {cards.map((card) => (
        <div className={`card ${card.tone ?? ''}`} key={card.k}>
          <div className="k">{card.k}</div>
          <div className="v">{card.v}</div>
          <div className="n">{card.n}</div>
        </div>
      ))}
    </div>
  );
}
