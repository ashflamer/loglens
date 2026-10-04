import type { Anomaly } from '../types';

export function Anomalies({ anomalies }: { anomalies: Anomaly[] }) {
  if (anomalies.length === 0) {
    return (
      <div className="panel">
        <h2>Anomalies</h2>
        <p className="muted">
          Nothing unusual. Error volume stayed within normal variation for the whole window.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>
        Anomalies<span className="muted"> · {anomalies.length} window(s) flagged</span>
      </h2>
      <ul className="anomalies">
        {anomalies.slice(0, 12).map((a, i) => (
          <li key={`${a.start}-${i}`} className={a.severity}>
            <div className="when">{new Date(a.start).toLocaleTimeString()}</div>
            <div className="what">
              <strong>{a.kind === 'silence' ? 'Service went quiet' : 'Error spike'}</strong>
              <span className="muted"> {a.detail}</span>
            </div>
            <div className="z">z={a.z_score}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
