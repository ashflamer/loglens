from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Level(str, Enum):
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"
    UNKNOWN = "UNKNOWN"

    @property
    def severity(self) -> int:
        return _SEVERITY[self]

    @classmethod
    def parse(cls, raw: str | None) -> Level:
        if not raw:
            return cls.UNKNOWN
        return _ALIASES.get(raw.strip().upper(), cls.UNKNOWN)


_SEVERITY = {
    Level.TRACE: 0, Level.DEBUG: 1, Level.INFO: 2,
    Level.WARN: 3, Level.ERROR: 4, Level.FATAL: 5, Level.UNKNOWN: 2,
}

_ALIASES = {
    "TRACE": Level.TRACE, "VERBOSE": Level.TRACE,
    "DEBUG": Level.DEBUG, "DBG": Level.DEBUG, "FINE": Level.DEBUG,
    "INFO": Level.INFO, "INFORMATION": Level.INFO, "NOTICE": Level.INFO, "I": Level.INFO,
    "WARN": Level.WARN, "WARNING": Level.WARN, "W": Level.WARN,
    "ERROR": Level.ERROR, "ERR": Level.ERROR, "SEVERE": Level.ERROR, "E": Level.ERROR,
    "FATAL": Level.FATAL, "CRITICAL": Level.FATAL, "CRIT": Level.FATAL,
    "EMERG": Level.FATAL, "ALERT": Level.FATAL, "PANIC": Level.FATAL,
}


class LogEntry(BaseModel):
    line_number: int
    timestamp: Optional[datetime] = None
    level: Level = Level.UNKNOWN
    message: str = ""
    source: Optional[str] = None
    fields: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""


class Bucket(BaseModel):
    start: datetime
    total: int
    by_level: dict[str, int]
    is_anomaly: bool = False
    z_score: float = 0.0


class Pattern(BaseModel):
    template: str
    count: int
    level: Level
    share: float
    examples: list[str]
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


class Anomaly(BaseModel):
    start: datetime
    kind: str
    detail: str
    severity: str
    z_score: float
    observed: int
    expected: float


class Summary(BaseModel):
    total_lines: int
    parsed_lines: int
    unparsed_lines: int
    detected_format: str
    by_level: dict[str, int]
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    lines_per_minute: Optional[float] = None
    error_rate: float = 0.0
    unique_patterns: int = 0


class AnalysisResult(BaseModel):
    summary: Summary
    timeline: list[Bucket]
    patterns: list[Pattern]
    anomalies: list[Anomaly]
    entries: list[LogEntry]
