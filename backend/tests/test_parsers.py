from datetime import timezone

import pytest

from app.models import Level
from app.parsers import (
    CommonLogParser, GenericParser, JsonParser, LogfmtParser, SyslogParser,
    detect_format, parse_lines, parse_timestamp,
)


class TestTimestamps:
    @pytest.mark.parametrize("value", [
        "2026-01-14T09:12:03.482Z",
        "2026-01-14T09:12:03Z",
        "2026-01-14 09:12:03",
        "2026-01-14 09:12:03,482",
        "14/Jan/2026:09:12:03 +0000",
    ])
    def test_parses_common_formats(self, value):
        parsed = parse_timestamp(value)
        assert parsed is not None
        assert parsed.year == 2026 and parsed.month == 1 and parsed.day == 14

    def test_epoch_seconds_and_millis(self):
        assert parse_timestamp(1768381923).year == 2026
        assert parse_timestamp(1768381923000).year == 2026

    def test_returns_none_for_junk(self):
        assert parse_timestamp("not a date") is None
        assert parse_timestamp(None) is None
        assert parse_timestamp("") is None

    def test_always_timezone_aware(self):
        assert parse_timestamp("2026-01-14 09:12:03").tzinfo is not None


class TestJsonParser:
    parser = JsonParser()

    def test_extracts_standard_fields(self):
        line = '{"timestamp":"2026-01-14T09:12:03Z","level":"error","message":"boom","logger":"api"}'
        entry = self.parser.parse(line, 1)
        assert entry.level is Level.ERROR
        assert entry.message == "boom"
        assert entry.source == "api"
        assert entry.timestamp.hour == 9

    def test_handles_alternative_key_names(self):
        line = '{"ts":1768381923,"severity":"WARN","msg":"slow","service":"db"}'
        entry = self.parser.parse(line, 1)
        assert entry.level is Level.WARN
        assert entry.message == "slow"
        assert entry.source == "db"

    def test_keeps_extra_fields(self):
        line = '{"msg":"ok","level":"info","user_id":42,"latency_ms":13}'
        entry = self.parser.parse(line, 1)
        assert entry.fields == {"user_id": 42, "latency_ms": 13}

    def test_rejects_non_json(self):
        assert self.parser.parse("plain text line", 1) is None
        assert self.parser.parse('{"broken": ', 1) is None
        assert self.parser.parse('[1,2,3]', 1) is None


class TestAccessLogParser:
    parser = CommonLogParser()

    def test_parses_combined_format(self):
        line = ('10.0.0.5 - frank [14/Jan/2026:09:12:03 +0000] '
                '"GET /api/users?page=2 HTTP/1.1" 200 2326 "-" "curl/8.4"')
        entry = self.parser.parse(line, 1)
        assert entry.fields["status"] == 200
        assert entry.fields["method"] == "GET"
        assert entry.fields["ip"] == "10.0.0.5"
        assert entry.level is Level.INFO

    @pytest.mark.parametrize("status,level", [
        (200, Level.INFO), (301, Level.INFO),
        (404, Level.WARN), (403, Level.WARN),
        (500, Level.ERROR), (503, Level.ERROR),
    ])
    def test_status_maps_to_severity(self, status, level):
        line = f'1.2.3.4 - - [14/Jan/2026:09:12:03 +0000] "GET / HTTP/1.1" {status} 10'
        assert self.parser.parse(line, 1).level is level

    def test_rejects_other_formats(self):
        assert self.parser.parse('{"json": true}', 1) is None


class TestSyslogParser:
    parser = SyslogParser()

    def test_parses_syslog_line(self):
        line = "Jan 14 09:12:03 web-01 sshd[1234]: Connection refused from 10.0.0.9"
        entry = self.parser.parse(line, 1)
        assert entry.source == "sshd"
        assert entry.fields["host"] == "web-01"
        assert entry.fields["pid"] == "1234"
        assert entry.level is Level.ERROR  # "refused"

    def test_pid_is_optional(self):
        entry = self.parser.parse("Jan 14 09:12:03 web-01 cron: job started", 1)
        assert entry is not None and entry.fields["pid"] is None


class TestLogfmtParser:
    parser = LogfmtParser()

    def test_parses_key_values(self):
        line = 'ts=2026-01-14T09:12:03Z level=error msg="db unreachable" service=api retries=3'
        entry = self.parser.parse(line, 1)
        assert entry.level is Level.ERROR
        assert entry.message == "db unreachable"
        assert entry.source == "api"
        assert entry.fields["retries"] == "3"

    def test_rejects_prose_with_one_pair(self):
        assert self.parser.parse("the server returned status=500 after a while", 1) is None


class TestGenericParser:
    parser = GenericParser()

    def test_pulls_timestamp_and_level(self):
        entry = self.parser.parse("2026-01-14T09:12:03Z ERROR [worker] job failed", 1)
        assert entry.level is Level.ERROR
        assert entry.timestamp is not None
        assert "job failed" in entry.message

    def test_survives_a_bare_line(self):
        entry = self.parser.parse("something happened", 1)
        assert entry.message == "something happened"
        assert entry.level is Level.UNKNOWN

    def test_extracts_bracketed_source_and_leaves_no_stray_bracket(self):
        entry = self.parser.parse(
            "2026-01-14T09:12:03Z ERROR [payment-worker] Charged order 1234", 1
        )
        assert entry.source == "payment-worker"
        assert entry.message == "Charged order 1234"
        assert "]" not in entry.message

    def test_message_without_a_source_is_untouched(self):
        entry = self.parser.parse("2026-01-14T09:12:03Z INFO plain message here", 1)
        assert entry.source is None
        assert entry.message == "plain message here"


class TestDetection:
    def test_detects_json(self):
        lines = ['{"msg":"a","level":"info"}'] * 10
        assert detect_format(lines).name == "json"

    def test_detects_access_log(self):
        line = '10.0.0.1 - - [14/Jan/2026:09:12:03 +0000] "GET / HTTP/1.1" 200 5'
        assert detect_format([line] * 10).name == "access-log"

    def test_detects_syslog(self):
        line = "Jan 14 09:12:03 host app[1]: hello"
        assert detect_format([line] * 10).name == "syslog"

    def test_falls_back_to_plain_for_mixed_content(self):
        lines = ["random line one", "another thing entirely", "no structure here"] * 4
        assert detect_format(lines).name == "plain"

    def test_empty_input(self):
        assert detect_format([]).name == "plain"

    def test_minority_format_does_not_win(self):
        lines = ['{"msg":"a"}'] + ["plain line"] * 20
        assert detect_format(lines).name == "plain"


class TestParseLines:
    def test_blank_lines_are_skipped(self):
        entries, _, _ = parse_lines(["a", "", "   ", "b"])
        assert len(entries) == 2

    def test_line_numbers_track_the_original_file(self):
        entries, _, _ = parse_lines(["first", "", "third"])
        assert [e.line_number for e in entries] == [1, 3]

    def test_unparseable_lines_fall_back_rather_than_vanish(self):
        lines = ['{"msg":"ok","level":"info"}'] * 10 + ["  at com.example.Foo.bar(Foo.java:42)"]
        entries, parser, unparsed = parse_lines(lines)
        assert parser.name == "json"
        assert unparsed == 1
        assert len(entries) == 11   # nothing dropped
