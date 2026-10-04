import { useCallback, useEffect, useRef, useState } from 'react';
import { analyseText, fetchSample, uploadFile } from './api';
import { Anomalies } from './components/Anomalies';
import { LogTable } from './components/LogTable';
import { Patterns } from './components/Patterns';
import { StatCards } from './components/StatCards';
import { Timeline } from './components/Timeline';
import type { AnalysisResult } from './types';

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasted, setPasted] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  const run = useCallback(async (work: () => Promise<AnalysisResult>) => {
    setLoading(true);
    setError(null);
    try {
      setResult(await work());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run(() => fetchSample(1200));
  }, [run]);

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void run(() => uploadFile(file));
  };

  return (
    <div
      className={`app ${dragging ? 'dragging' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <header className="topbar">
        <div>
          <h1>log<span>lens</span></h1>
          <p className="muted">Drop in a log file, get answers.</p>
        </div>
        <div className="actions">
          <button onClick={() => fileInput.current?.click()}>Upload file</button>
          <button onClick={() => setPasteOpen((v) => !v)}>Paste logs</button>
          <button className="primary" onClick={() => void run(() => fetchSample(1200))}>
            Load sample
          </button>
          <input
            ref={fileInput}
            type="file"
            hidden
            accept=".log,.txt,.json,.ndjson,text/*"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void run(() => uploadFile(file));
            }}
          />
        </div>
      </header>

      {pasteOpen && (
        <div className="panel">
          <textarea
            rows={8}
            value={pasted}
            placeholder="Paste log lines here — any format."
            onChange={(e) => setPasted(e.target.value)}
          />
          <button
            className="primary"
            disabled={!pasted.trim()}
            onClick={() => { void run(() => analyseText(pasted)); setPasteOpen(false); }}
          >
            Analyse
          </button>
        </div>
      )}

      {error && <div className="panel error-panel">⚠ {error}</div>}
      {loading && <div className="panel muted">Analysing…</div>}

      {result && !loading && (
        <>
          <StatCards summary={result.summary} />
          <Timeline buckets={result.timeline} />
          <Anomalies anomalies={result.anomalies} />
          <Patterns patterns={result.patterns} />
          <LogTable entries={result.entries} />
        </>
      )}

      <footer className="muted">
        loglens · FastAPI + React · <a href="https://github.com/ashflamer/loglens">source</a>
        {' · '}
        <a href="/docs">API docs</a>
      </footer>

      {dragging && <div className="dropzone">Drop a log file to analyse</div>}
    </div>
  );
}
