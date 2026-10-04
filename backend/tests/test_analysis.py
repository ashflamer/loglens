from datetime import datetime, timedelta, timezone

import pytest

from app.analysis import (
    analyse, build_timeline, choose_bucket_size, detect_anomalies,
    extract_patterns, templatise,
)
from app.models import Bucket, Level, LogEntry


def entry(line, message, level=Level.INFO, ts=None):
    return LogEntry(line_number=line, message=message, level=level, timestamp=ts, raw=message)


class TestTemplatise:
    def test_collapses_numbers(self):
        assert templatise("User 4182 logged in") == templatise("User 9931 logged in")

    def test_collapses_ip_addresses(self):
        a = templatise("Connection from 10.0.0.7 refused")
        b = templatise("Connection from 192.168.1.44 refused")
        assert a == b
        assert "<IP>" in a

    def test_collapses_uuids(self):
        a = templatise("Order 3f2504e0-4f89-11d3-9a0c-0305e82c3301 shipped")
        b = templatise("Order 7c9e6679-7425-40de-944b-e07fc1f90ae7 shipped")
        assert a == b and "<UUID>" in a

    def test_collapses_emails_and_urls(self):
        assert "<EMAIL>" in templatise("Invite sent to bob@example.com")
        assert "<URL>" in templatise("Fetching https://api.example.com/v1/x")

    def test_distinct_messages_stay_distinct(self):
        assert templatise("Payment failed") != templatise("Payment succeeded")

    def test_long_templates_are_truncated(self):
        assert len(templatise("word " * 200)) <= 230

    def test_whitespace_is_normalised(self):
        assert templatise("a    b\tc") == "a b c"


class TestTimeline:
    def test_buckets_are_contiguous_even_when_empty(self):
        base = datetime(2026, 1, 14, 9, 0, tzinfo=timezone.utc)
        entries = [
            entry(1, "a", ts=base),
            entry(2, "b", ts=base + timedelta(minutes=30)),
        ]
        buckets = build_timeline(entries)
        assert len(buckets) >= 2
        assert sum(b.total for b in buckets) == 2
        gaps = [b for b in buckets if b.total == 0]
        assert len(gaps) > 0, "expected empty buckets in the middle"

    def test_entries_without_timestamps_are_ignored(self):
        assert build_timeline([entry(1, "no time")]) == []

    def test_level_breakdown_per_bucket(self):
        base = datetime(2026, 1, 14, 9, 0, tzinfo=timezone.utc)
        entries = [entry(i, "x", Level.ERROR, base) for i in range(3)]
        entries += [entry(9, "y", Level.INFO, base)]
        buckets = build_timeline(entries)
        assert buckets[0].by_level["ERROR"] == 3
        assert buckets[0].by_level["INFO"] == 1

    @pytest.mark.parametrize("minutes,expected_max", [(1, 60), (60, 3600), (1440, 86400)])
    def test_bucket_size_scales_with_span(self, minutes, expected_max):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        width = choose_bucket_size(start, start + timedelta(minutes=minutes))
        assert width.total_seconds() <= expected_max


class TestAnomalies:
    """Unit-tests the detector directly.

    Building buckets via build_timeline would interleave auto-sized empty
    windows and silently change the distribution under test, so these
    construct Bucket objects explicitly.
    """

    def _buckets(self, error_counts, baseline_info=5):
        base = datetime(2026, 1, 14, 9, 0, tzinfo=timezone.utc)
        return [
            Bucket(
                start=base + timedelta(minutes=i),
                total=count + baseline_info,
                by_level={"ERROR": count, "INFO": baseline_info},
            )
            for i, count in enumerate(error_counts)
        ]

    def test_detects_a_spike(self):
        buckets = self._buckets([1, 1, 2, 1, 1, 2, 1, 80, 1, 1, 2, 1])
        anomalies = detect_anomalies(buckets)
        assert any(a.kind == "error_spike" for a in anomalies)
        assert max(a.observed for a in anomalies) == 80

    def test_steady_noise_is_not_an_anomaly(self):
        buckets = self._buckets([4, 5, 4, 6, 5, 4, 5, 6, 4, 5, 5, 4])
        assert [a for a in detect_anomalies(buckets) if a.kind == "error_spike"] == []

    def test_mad_is_not_fooled_by_the_outlier_it_should_catch(self):
        # With mean/stddev a single 500 inflates sigma enough that the spike
        # scores below threshold and hides itself. MAD is immune to that.
        buckets = self._buckets([1, 1, 1, 1, 1, 1, 1, 1, 1, 500])
        assert any(a.observed == 500 for a in detect_anomalies(buckets))

    def test_a_single_error_against_a_zero_baseline_is_not_a_spike(self):
        # Statistically extreme, operationally meaningless.
        buckets = self._buckets([0, 0, 0, 0, 0, 0, 0, 0, 1, 0])
        assert [a for a in detect_anomalies(buckets) if a.kind == "error_spike"] == []

    def test_a_real_burst_against_a_zero_baseline_is_a_spike(self):
        buckets = self._buckets([0, 0, 0, 0, 0, 0, 0, 0, 40, 0])
        assert any(a.observed == 40 for a in detect_anomalies(buckets))

    def test_a_perfectly_flat_series_has_no_anomalies(self):
        assert detect_anomalies(self._buckets([5] * 12)) == []

    def test_too_few_buckets_returns_nothing(self):
        assert detect_anomalies(self._buckets([1, 50])) == []

    def test_severity_escalates_with_magnitude(self):
        buckets = self._buckets([1, 1, 1, 1, 1, 1, 1, 1, 200])
        assert any(a.severity == "high" for a in detect_anomalies(buckets))

    def test_silence_is_flagged_when_the_service_is_normally_busy(self):
        base = datetime(2026, 1, 14, 9, 0, tzinfo=timezone.utc)
        buckets = [
            Bucket(start=base + timedelta(minutes=i),
                   total=0 if i == 6 else 40,
                   by_level={} if i == 6 else {"INFO": 40})
            for i in range(12)
        ]
        assert any(a.kind == "silence" for a in detect_anomalies(buckets))


class TestPatterns:
    def test_groups_similar_messages(self):
        entries = [entry(i, f"User {i} failed login from 10.0.0.{i}", Level.ERROR)
                   for i in range(1, 51)]
        patterns = extract_patterns(entries)
        assert len(patterns) == 1
        assert patterns[0].count == 50
        assert patterns[0].share == 100.0
        assert patterns[0].level is Level.ERROR

    def test_ranks_by_volume(self):
        entries = [entry(i, f"common {i}") for i in range(30)]
        entries += [entry(100 + i, f"rare {i}") for i in range(3)]
        patterns = extract_patterns(entries)
        assert patterns[0].count == 30

    def test_keeps_examples_but_caps_them(self):
        entries = [entry(i, f"thing {i}") for i in range(20)]
        assert len(extract_patterns(entries)[0].examples) == 3

    def test_empty_input(self):
        assert extract_patterns([]) == []

    def test_respects_limit(self):
        entries = [entry(i, f"unique message alpha{i} beta") for i in range(50)]
        assert len(extract_patterns(entries, limit=5)) == 5


class TestEndToEnd:
    def test_analyses_json_logs(self):
        text = "\n".join(
            f'{{"timestamp":"2026-01-14T09:{i:02d}:00Z","level":"info","message":"req {i} ok"}}'
            for i in range(30)
        )
        result = analyse(text)
        assert result.summary.detected_format == "json"
        assert result.summary.parsed_lines == 30
        assert result.summary.unique_patterns == 1
        assert result.summary.error_rate == 0.0

    def test_computes_error_rate(self):
        lines = ['{"level":"info","message":"ok","timestamp":"2026-01-14T09:00:00Z"}'] * 9
        lines += ['{"level":"error","message":"bad","timestamp":"2026-01-14T09:01:00Z"}']
        result = analyse("\n".join(lines))
        assert result.summary.error_rate == 10.0

    def test_handles_empty_input(self):
        result = analyse("")
        assert result.summary.total_lines == 0
        assert result.entries == []

    def test_handles_a_file_of_only_blank_lines(self):
        result = analyse("\n\n   \n\n")
        assert result.summary.parsed_lines == 0

    def test_sample_log_contains_a_detectable_incident(self):
        from app.sample import generate
        result = analyse(generate(1200))
        assert result.summary.parsed_lines > 1000
        assert result.summary.error_rate > 0
        assert len(result.anomalies) > 0, "the seeded incident should be detected"
        assert len(result.patterns) > 3

    def test_entries_are_returned_in_line_order(self):
        result = analyse("\n".join(f"line {i}" for i in range(100)))
        numbers = [e.line_number for e in result.entries]
        assert numbers == sorted(numbers)

    def test_max_entries_is_respected(self):
        text = "\n".join(f"2026-01-14T09:00:00Z INFO line {i}" for i in range(500))
        assert len(analyse(text, max_entries=50).entries) == 50
