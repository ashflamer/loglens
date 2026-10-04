"""Format detection and line parsing.

Nobody wants to tell a log viewer what format their logs are in. loglens
sniffs it from a sample of lines and picks the parser that claims the most.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from app.models import Level, LogEntry

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
    "%d/%b/%Y:%H:%M:%S %z", "%d/%b/%Y %H:%M:%S",
)


SYSLOG_TIME_RE = re.compile(r"^[A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2}$")


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Best-effort timestamp parsing across the formats people actually use."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Heuristic: anything past ~2001 in ms is really ms, not seconds.
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    text = str(value).strip().replace("Z", "+0000")

    # Syslog omits the year entirely ("Jan 14 09:12:03"). Rather than let
    # strptime default to 1900 (deprecated in 3.15, and wrong anyway), assume
    # the current year explicitly.
    syslog = SYSLOG_TIME_RE.match(text)
    if syslog:
        year = datetime.now(tz=timezone.utc).year
        try:
            return datetime.strptime(f"{year} {text}", "%Y %b %d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None

    for fmt in TIMESTAMP_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Parser(ABC):
    name: str = "unknown"

    @abstractmethod
    def parse(self, line: str, line_number: int) -> Optional[LogEntry]:
        """Return an entry, or None when this parser doesn't recognise the line."""


class JsonParser(Parser):
    """Structured JSON lines - the easiest and most informative case."""

    name = "json"

    TIME_KEYS = ("timestamp", "time", "ts", "@timestamp", "datetime", "eventTime")
    LEVEL_KEYS = ("level", "severity", "lvl", "levelname", "log.level", "loglevel")
    MESSAGE_KEYS = ("message", "msg", "event", "text", "log", "body")
    SOURCE_KEYS = ("logger", "service", "source", "component", "name", "module")

    def parse(self, line: str, line_number: int) -> Optional[LogEntry]:
        stripped = line.strip()
        if not stripped.startswith("{"):
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None

        def pick(keys):
            for key in keys:
                if key in payload and payload[key] not in (None, ""):
                    return payload[key]
            return None

        message = pick(self.MESSAGE_KEYS)
        consumed = set()
        for group in (self.TIME_KEYS, self.LEVEL_KEYS, self.MESSAGE_KEYS, self.SOURCE_KEYS):
            for key in group:
                if key in payload:
                    consumed.add(key)
                    break

        return LogEntry(
            line_number=line_number,
            timestamp=parse_timestamp(pick(self.TIME_KEYS)),
            level=Level.parse(str(pick(self.LEVEL_KEYS) or "")),
            message=str(message) if message is not None else stripped,
            source=str(pick(self.SOURCE_KEYS)) if pick(self.SOURCE_KEYS) else None,
            fields={k: v for k, v in payload.items() if k not in consumed},
            raw=stripped,
        )


class LogfmtParser(Parser):
    """key=value pairs, as emitted by Go services and Heroku."""

    name = "logfmt"
    PAIR_RE = re.compile(r'(\w[\w.\-]*)=("([^"]*)"|\S+)')

    def parse(self, line: str, line_number: int) -> Optional[LogEntry]:
        stripped = line.strip()
        matches = list(self.PAIR_RE.finditer(stripped))
        if len(matches) < 2:
            return None
        # Reject lines that are mostly prose with one stray `x=1`.
        covered = sum(m.end() - m.start() for m in matches)
        if covered < len(stripped) * 0.5:
            return None

        fields = {m.group(1): (m.group(3) if m.group(3) is not None else m.group(2))
                  for m in matches}
        message = fields.pop("msg", None) or fields.pop("message", None) or stripped

        return LogEntry(
            line_number=line_number,
            timestamp=parse_timestamp(
                fields.pop("ts", None) or fields.pop("time", None) or fields.pop("timestamp", None)
            ),
            level=Level.parse(fields.pop("level", None) or fields.pop("lvl", None)),
            message=str(message),
            source=fields.pop("service", None) or fields.pop("logger", None),
            fields=fields,
            raw=stripped,
        )


class CommonLogParser(Parser):
    """nginx / Apache combined access logs."""

    name = "access-log"
    LINE_RE = re.compile(
        r'^(?P<ip>\S+) \S+ (?P<user>\S+) \[(?P<time>[^\]]+)\] '
        r'"(?P<method>[A-Z]+) (?P<path>\S*) ?(?P<proto>[^"]*)" '
        r'(?P<status>\d{3}) (?P<size>\S+)'
        r'(?: "(?P<referer>[^"]*)" "(?P<agent>[^"]*)")?'
    )

    def parse(self, line: str, line_number: int) -> Optional[LogEntry]:
        match = self.LINE_RE.match(line.strip())
        if not match:
            return None
        data = match.groupdict()
        status = int(data["status"])

        # HTTP status is the real severity signal in an access log.
        if status >= 500:
            level = Level.ERROR
        elif status >= 400:
            level = Level.WARN
        else:
            level = Level.INFO

        return LogEntry(
            line_number=line_number,
            timestamp=parse_timestamp(data["time"]),
            level=level,
            message=f"{data['method']} {data['path']} → {status}",
            source=data["ip"],
            fields={
                "ip": data["ip"], "method": data["method"], "path": data["path"],
                "status": status,
                "size": int(data["size"]) if data["size"].isdigit() else 0,
                "user_agent": data.get("agent") or "",
                "referer": data.get("referer") or "",
            },
            raw=line.strip(),
        )


class SyslogParser(Parser):
    """RFC3164-ish syslog: `Jan 14 09:12:03 host service[pid]: message`."""

    name = "syslog"
    LINE_RE = re.compile(
        r'^(?P<time>[A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2}) '
        r'(?P<host>\S+) (?P<proc>[\w./-]+)(?:\[(?P<pid>\d+)\])?: (?P<message>.*)$'
    )

    def parse(self, line: str, line_number: int) -> Optional[LogEntry]:
        match = self.LINE_RE.match(line.strip())
        if not match:
            return None
        data = match.groupdict()
        return LogEntry(
            line_number=line_number,
            timestamp=parse_timestamp(data["time"]),
            level=_level_from_text(data["message"]),
            message=data["message"],
            source=data["proc"],
            fields={"host": data["host"], "pid": data.get("pid")},
            raw=line.strip(),
        )


class GenericParser(Parser):
    """Last resort: pull a leading timestamp and a level word out of the line."""

    name = "plain"
    TIME_RE = re.compile(
        r'^\[?(?P<time>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?'
    )
    LEVEL_RE = re.compile(
        r'\b(TRACE|DEBUG|INFO|INFORMATION|NOTICE|WARN|WARNING|ERROR|ERR|SEVERE|FATAL|CRITICAL)\b',
        re.IGNORECASE,
    )
    BRACKET_SOURCE_RE = re.compile(r'^\[([\w.\-/]{1,40})\]\s*')

    def parse(self, line: str, line_number: int) -> Optional[LogEntry]:
        stripped = line.strip()
        if not stripped:
            return None

        rest = stripped
        timestamp = None
        time_match = self.TIME_RE.match(stripped)
        if time_match:
            timestamp = parse_timestamp(time_match.group("time"))
            rest = stripped[time_match.end():].strip(" -\t|")

        level = Level.UNKNOWN
        level_match = self.LEVEL_RE.search(rest[:60])
        if level_match:
            level = Level.parse(level_match.group(1))
            rest = (rest[:level_match.start()] + rest[level_match.end():]).strip(" -\t|:")

        # A leading `[service]` is a source, not part of the message. Pulling it
        # out keeps templates clean instead of leaving a dangling bracket.
        source = None
        source_match = self.BRACKET_SOURCE_RE.match(rest)
        if source_match:
            source = source_match.group(1)
            rest = rest[source_match.end():].strip(" -\t|:")

        return LogEntry(
            line_number=line_number,
            timestamp=timestamp,
            level=level,
            message=rest or stripped,
            source=source,
            raw=stripped,
        )


def _level_from_text(text: str) -> Level:
    lowered = text.lower()
    if any(w in lowered for w in ("fatal", "panic", "critical")):
        return Level.FATAL
    if any(w in lowered for w in ("error", "failed", "failure", "exception", "refused")):
        return Level.ERROR
    if any(w in lowered for w in ("warn", "deprecat", "retry", "timeout")):
        return Level.WARN
    return Level.INFO


# Ordered most-specific first.
PARSERS: tuple[Parser, ...] = (
    JsonParser(), CommonLogParser(), SyslogParser(), LogfmtParser(), GenericParser(),
)


def detect_format(lines: list[str], sample_size: int = 200) -> Parser:
    """Pick the parser that successfully claims the most of a sample.

    GenericParser matches nearly everything, so it's only chosen when no
    structured parser clears a 60% confidence bar.
    """
    sample = [ln for ln in lines[:sample_size] if ln.strip()]
    if not sample:
        return GenericParser()

    best: Parser = GenericParser()
    best_score = 0.0

    for parser in PARSERS[:-1]:
        hits = sum(1 for ln in sample if parser.parse(ln, 0) is not None)
        score = hits / len(sample)
        if score > best_score:
            best, best_score = parser, score

    return best if best_score >= 0.6 else GenericParser()


def parse_lines(lines: list[str], parser: Parser | None = None) -> tuple[list[LogEntry], Parser, int]:
    """Parse every line, falling back to the generic parser per-line.

    Returns (entries, parser_used, unparsed_count). Real log files are messy:
    stack traces, blank lines, a stray JSON blob in a plaintext file. A line
    the chosen parser rejects still becomes an entry via the fallback, so
    nothing is silently dropped.
    """
    chosen = parser or detect_format(lines)
    fallback = GenericParser()
    entries: list[LogEntry] = []
    unparsed = 0

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        entry = chosen.parse(line, number)
        if entry is None:
            entry = fallback.parse(line, number)
            unparsed += 1
        if entry is not None:
            entries.append(entry)

    return entries, chosen, unparsed
