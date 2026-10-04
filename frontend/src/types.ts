export type Level = 'TRACE' | 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'FATAL' | 'UNKNOWN';

export interface LogEntry {
  line_number: number;
  timestamp: string | null;
  level: Level;
  message: string;
  source: string | null;
  fields: Record<string, unknown>;
  raw: string;
}

export interface Bucket {
  start: string;
  total: number;
  by_level: Partial<Record<Level, number>>;
  is_anomaly: boolean;
  z_score: number;
}

export interface Pattern {
  template: string;
  count: number;
  level: Level;
  share: number;
  examples: string[];
  first_seen: string | null;
  last_seen: string | null;
}

export interface Anomaly {
  start: string;
  kind: string;
  detail: string;
  severity: string;
  z_score: number;
  observed: number;
  expected: number;
}

export interface Summary {
  total_lines: number;
  parsed_lines: number;
  unparsed_lines: number;
  detected_format: string;
  by_level: Partial<Record<Level, number>>;
  first_timestamp: string | null;
  last_timestamp: string | null;
  duration_seconds: number | null;
  lines_per_minute: number | null;
  error_rate: number;
  unique_patterns: number;
}

export interface AnalysisResult {
  summary: Summary;
  timeline: Bucket[];
  patterns: Pattern[];
  anomalies: Anomaly[];
  entries: LogEntry[];
}
