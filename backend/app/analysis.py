"""Statistics, message clustering and anomaly detection."""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.models import (
    AnalysisResult,
    Anomaly,
    Bucket,
    Level,
    LogEntry,
    Pattern,
    Summary,
)

# Order matters: UUID before hex, IP before number, or the broader rule wins.
PLACEHOLDERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'), '<UUID>'),
    (re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b'), '<IP>'),
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b'), '<EMAIL>'),
    (re.compile(r'\bhttps?://\S+'), '<URL>'),
    (re.compile(r'\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*'), '<TIME>'),
    (re.compile(r'\b0x[0-9a-fA-F]+\b'), '<HEX>'),
    (re.compile(r'\b[0-9a-fA-F]{16,}\b'), '<HASH>'),
    (re.compile(r'(?<=[/\w])\b\d+\b'), '<NUM>'),
    (re.compile(r'\b\d+(?:\.\d+)?(?:ms|s|m|h|kb|mb|gb|%)\b', re.IGNORECASE), '<QTY>'),
    (re.compile(r'\b\d+(?:\.\d+)?\b'), '<NUM>'),
    (re.compile(r"'[^']{1,80}'"), "'<STR>'"),
    (re.compile(r'"[^"]{1,80}"'), '"<STR>"'),
)

MAX_TEMPLATE_LENGTH = 220

# A spike must clear this many errors before it's worth reporting.
MIN_SPIKE_ERRORS = 3


def templatise(message: str) -> str:
    """Collapse a message to its shape.

    `User 4182 failed login from 10.0.0.7` and
    `User 9931 failed login from 10.0.2.3` both become
    `User <NUM> failed login from <IP>` — so a thousand lines become one row
    with a count of 1000. This is the cheap cousin of Drain/Spell log parsing,
    and in practice it collapses real logs by 50-200x.
    """
    collapsed = message.strip()
    for pattern, token in PLACEHOLDERS:
        collapsed = pattern.sub(token, collapsed)
    collapsed = re.sub(r'\s+', ' ', collapsed).strip()
    if len(collapsed) > MAX_TEMPLATE_LENGTH:
        collapsed = collapsed[:MAX_TEMPLATE_LENGTH] + '…'
    return collapsed


def choose_bucket_size(start: datetime, end: datetime, target_buckets: int = 60) -> timedelta:
    """Pick a human-friendly bucket width for the timeline."""
    span = max((end - start).total_seconds(), 1.0)
    raw = span / target_buckets
    for seconds in (1, 5, 10, 30, 60, 300, 600, 1800, 3600, 10800, 21600, 86400):
        if raw <= seconds:
            return timedelta(seconds=seconds)
    return timedelta(days=max(1, round(raw / 86400)))


def build_timeline(entries: list[LogEntry]) -> list[Bucket]:
    timed = [e for e in entries if e.timestamp is not None]
    if not timed:
        return []

    start = min(e.timestamp for e in timed)
    end = max(e.timestamp for e in timed)
    width = choose_bucket_size(start, end)
    width_seconds = width.total_seconds()

    grouped: dict[int, Counter] = defaultdict(Counter)
    for entry in timed:
        offset = int((entry.timestamp - start).total_seconds() // width_seconds)
        grouped[offset][entry.level.value] += 1

    buckets: list[Bucket] = []
    for offset in range(max(grouped) + 1):
        counts = grouped.get(offset, Counter())
        buckets.append(Bucket(
            start=start + timedelta(seconds=offset * width_seconds),
            total=sum(counts.values()),
            by_level=dict(counts),
        ))
    return buckets


def detect_anomalies(buckets: list[Bucket], *, threshold: float = 2.5) -> list[Anomaly]:
    """Flag buckets where error volume spikes beyond normal variation.

    Uses a modified z-score built on the **median** and **MAD** rather than
    mean and standard deviation. A single catastrophic spike inflates the
    standard deviation enough to hide itself — the median absolute deviation
    is not fooled by that, which is exactly what you want in outlier
    detection.
    """
    if len(buckets) < 5:
        return []

    error_counts = [
        b.by_level.get(Level.ERROR.value, 0) + b.by_level.get(Level.FATAL.value, 0)
        for b in buckets
    ]
    median = statistics.median(error_counts)
    deviations = [abs(c - median) for c in error_counts]
    mad = statistics.median(deviations)

    # 1.4826 rescales MAD so the result is comparable to a standard z-score.
    if mad > 0:
        scale = 1.4826 * mad
    else:
        # MAD collapses to 0 whenever >50% of buckets are identical (very
        # common: lots of quiet windows with zero errors). Fall back to the
        # standard deviation rather than treating every error as infinite.
        stdev = statistics.pstdev(error_counts)
        scale = stdev if stdev > 0 else None

    anomalies: list[Anomaly] = []
    # strict=: error_counts is derived 1:1 from buckets, so a length
    # mismatch means a bug upstream. Fail loudly instead of silently
    # truncating and under-reporting anomalies.
    for bucket, count in zip(buckets, error_counts, strict=True):
        z = (count - median) / scale if scale else 0.0
        bucket.z_score = round(min(z, 99.9), 2) if math.isfinite(z) else 99.9

        # An absolute floor stops "1 error against a baseline of 0" — which is
        # statistically extreme but operationally meaningless — from firing.
        floor = max(MIN_SPIKE_ERRORS, median + 2)

        if count >= floor and z >= threshold:
            bucket.is_anomaly = True
            anomalies.append(Anomaly(
                start=bucket.start,
                kind="error_spike",
                detail=_describe_spike(count, median),
                severity="high" if count >= max(median * 5, 10) else "medium",
                z_score=bucket.z_score,
                observed=count,
                expected=round(median, 2),
            ))

    # Also flag total-volume collapse: a service that goes silent is a problem.
    totals = [b.total for b in buckets]
    median_total = statistics.median(totals)
    if median_total >= 10:
        for bucket in buckets:
            if bucket.total == 0:
                anomalies.append(Anomaly(
                    start=bucket.start, kind="silence",
                    detail=f"No log lines at all (usually ~{median_total:.0f})",
                    severity="medium", z_score=0.0, observed=0,
                    expected=round(median_total, 2),
                ))

    anomalies.sort(key=lambda a: a.start)
    return anomalies


def _describe_spike(count: int, median: float) -> str:
    noun = "error" if count == 1 else "errors"
    if median <= 0:
        return f"{count} {noun} in a window that is normally clean"
    return f"{count} {noun} — {count / median:.1f}x the usual {median:.0f}"


def extract_patterns(entries: list[LogEntry], limit: int = 25) -> list[Pattern]:
    """Group messages by shape and rank by volume."""
    if not entries:
        return []

    groups: dict[str, dict] = {}
    for entry in entries:
        template = templatise(entry.message)
        group = groups.setdefault(template, {
            "count": 0, "levels": Counter(), "examples": [],
            "first": entry.timestamp, "last": entry.timestamp,
        })
        group["count"] += 1
        group["levels"][entry.level] += 1
        if len(group["examples"]) < 3 and entry.raw not in group["examples"]:
            group["examples"].append(entry.raw[:300])
        if entry.timestamp:
            if group["first"] is None or entry.timestamp < group["first"]:
                group["first"] = entry.timestamp
            if group["last"] is None or entry.timestamp > group["last"]:
                group["last"] = entry.timestamp

    total = len(entries)
    patterns = [
        Pattern(
            template=template,
            count=data["count"],
            level=max(data["levels"], key=lambda lv: (lv.severity, data["levels"][lv])),
            share=round(data["count"] / total * 100, 2),
            examples=data["examples"],
            first_seen=data["first"],
            last_seen=data["last"],
        )
        for template, data in groups.items()
    ]
    # Loudest first, but break ties by severity so errors float above noise.
    patterns.sort(key=lambda p: (p.count, p.level.severity), reverse=True)
    return patterns[:limit]


def summarise(
    entries: list[LogEntry], *, total_lines: int, unparsed: int,
    fmt: str, unique_patterns: int,
) -> Summary:
    by_level = Counter(e.level.value for e in entries)
    timestamps = [e.timestamp for e in entries if e.timestamp]

    first = min(timestamps) if timestamps else None
    last = max(timestamps) if timestamps else None
    duration = (last - first).total_seconds() if first and last else None

    errors = by_level.get(Level.ERROR.value, 0) + by_level.get(Level.FATAL.value, 0)

    return Summary(
        total_lines=total_lines,
        parsed_lines=len(entries),
        unparsed_lines=unparsed,
        detected_format=fmt,
        by_level=dict(by_level),
        first_timestamp=first,
        last_timestamp=last,
        duration_seconds=round(duration, 2) if duration is not None else None,
        lines_per_minute=(
            round(len(entries) / (duration / 60), 2) if duration and duration > 0 else None
        ),
        error_rate=round(errors / len(entries) * 100, 2) if entries else 0.0,
        unique_patterns=unique_patterns,
    )


def analyse(
    text: str, *, max_entries: int = 2000, pattern_limit: int = 25,
) -> AnalysisResult:
    """Full pipeline: detect → parse → bucket → cluster → flag."""
    from app.parsers import parse_lines

    lines = text.splitlines()
    entries, parser, unparsed = parse_lines(lines)

    timeline = build_timeline(entries)
    anomalies = detect_anomalies(timeline)
    all_templates = {templatise(e.message) for e in entries}
    patterns = extract_patterns(entries, limit=pattern_limit)

    summary = summarise(
        entries,
        total_lines=len([ln for ln in lines if ln.strip()]),
        unparsed=unparsed,
        fmt=parser.name,
        unique_patterns=len(all_templates),
    )

    # Errors first in the returned sample — that's what people scroll for.
    sampled = sorted(
        entries,
        key=lambda e: (-e.level.severity, e.line_number),
    )[:max_entries]
    sampled.sort(key=lambda e: e.line_number)

    return AnalysisResult(
        summary=summary, timeline=timeline, patterns=patterns,
        anomalies=anomalies, entries=sampled,
    )
