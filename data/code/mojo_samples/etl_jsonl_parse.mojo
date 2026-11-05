# etl_jsonl_parse.mojo
#
# Parallel JSON-lines parser for the START project's Mojo ETL samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.)
# Requires Mojo 1.2.0. There is no `std.json` module in Mojo 1.2, so the
# JSON parsing here is hand-written: a byte cursor over each line that
# understands the full JSON value grammar (objects, arrays, strings with
# escapes and \uXXXX, numbers with fractions and exponents, literals).
#
# Input: one JSON object per line, e.g.
#   {"ts":"2026-11-05T00:00:01Z","level":"INFO","service":"orders",
#    "msg":"order placed","latency_ms":74.27,"status":200,
#    "request_id":"req-957535","meta":{"region":"us-east-1"}}
#
# The program:
#   1. Reads the whole file from disk (real file I/O).
#   2. Parses it once single-threaded (reference) and once with
#      `parallelize` (per-chunk aggregates merged afterwards).
#   3. Asserts the two results agree exactly (counts) or within 1e-9
#      relative tolerance (latency sums / percentiles).
#   4. Reports level/service/region/status distributions, per-service
#      latency mean and p50/p95/p99, error rates, duplicate request ids,
#      and data-quality counters (malformed lines, missing fields).
#
# Design notes:
# - The parser never raises: a malformed line yields ok == False and the
#   first few malformed lines are kept as samples for the report.
# - Unknown fields are skipped generically (the value skipper handles
#   nested objects and arrays), so the parser tolerates schema evolution.
# - `meta` is a nested object; its keys are flattened with a "meta."
#   prefix, which is the standard ETL flattening step for nested logs.
# - Latencies are kept per service in lists so percentiles are exact
#   (sorted, indexed), not estimated. The lists are merged by appending
#   in the reduce step and sorted once at report time.
#
# Usage:
#   mojo etl_jsonl_parse.mojo [data-dir] [workers]
# Defaults: /tmp/etl_data, 4 workers. If events.jsonl is missing, a
# deterministic 30,000-event file is generated in place first (same
# format and seed family as etl_gen_data.mojo).

from std.pathlib import Path
from std.testing import assert_equal, assert_true, assert_almost_equal
from std.collections import Dict
from std.random import seed, random_float64
from std.sys import argv
from std.time import perf_counter
from std.os import mkdir


# ---------------------------------------------------------------------------
# One parsed event.
# ---------------------------------------------------------------------------


struct EventFields(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var ts: String
    var level: String
    var service: String
    var msg: String
    var latency: Float64
    var has_latency: Bool
    var status: Int
    var has_status: Bool
    var request_id: String
    var region: String

    def __init__(out self):
        self.ok = False
        self.ts = ""
        self.level = ""
        self.service = ""
        self.msg = ""
        self.latency = 0.0
        self.has_latency = False
        self.status = 0
        self.has_status = False
        self.request_id = ""
        self.region = ""

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.ts = other.ts
        self.level = other.level
        self.service = other.service
        self.msg = other.msg
        self.latency = other.latency
        self.has_latency = other.has_latency
        self.status = other.status
        self.has_status = other.has_status
        self.request_id = other.request_id
        self.region = other.region


# ---------------------------------------------------------------------------
# JSON byte cursor. All functions take the source line (String) plus a
# position and return the new position plus an ok flag; nothing here
# raises, so the parallel workers can call straight into the parser.
# String runs are copied with `line[byte=a:b]` slices, which is the
# correct way to turn bytes back into text in Mojo 1.2 (`String` built
# from a byte span would render the byte values, not the characters).
# ---------------------------------------------------------------------------


def skip_ws(line: String, i: Int) -> Int:
    var b = line.as_bytes()
    var j = i
    while j < len(b) and (b[j] == 32 or b[j] == 9 or b[j] == 10 or b[j] == 13):
        j += 1
    return j


def hex_val(c: UInt8) -> Int:
    if c >= 48 and c <= 57:
        return Int(c) - 48
    if c >= 97 and c <= 102:
        return Int(c) - 97 + 10
    if c >= 65 and c <= 70:
        return Int(c) - 65 + 10
    return -1


def parse_json_string(line: String, start: Int) -> Tuple[String, Int, Bool]:
    """Parse a JSON string starting at the opening quote. Returns
    (value, next_position, ok). Handles all standard escapes; backslash-u
    code points in the ASCII range decode exactly, others become '?'."""
    var b = line.as_bytes()
    if start >= len(b) or b[start] != 34:
        return ("", start, False)
    var out = String("")
    var i = start + 1
    var run_start = i
    while i < len(b):
        var c = b[i]
        if c == 34:
            if i > run_start:
                out += String(line[byte = run_start:i])
            return (out, i + 1, True)
        if c == 92:
            if i > run_start:
                out += String(line[byte = run_start:i])
            if i + 1 >= len(b):
                return ("", start, False)
            var e = b[i + 1]
            if e == 34:
                out += '"'
                i += 2
            elif e == 92:
                out += "\\"
                i += 2
            elif e == 47:
                out += "/"
                i += 2
            elif e == 98:
                out += "\b"
                i += 2
            elif e == 102:
                out += "\f"
                i += 2
            elif e == 110:
                out += "\n"
                i += 2
            elif e == 114:
                out += "\r"
                i += 2
            elif e == 116:
                out += "\t"
                i += 2
            elif e == 117:
                if i + 5 >= len(b):
                    return ("", start, False)
                var cp = 0
                var good = True
                for k in range(4):
                    var hv = hex_val(b[i + 2 + k])
                    if hv < 0:
                        good = False
                    else:
                        cp = cp * 16 + hv
                if not good:
                    return ("", start, False)
                if cp < 128:
                    out += chr(cp)
                else:
                    out += "?"
                i += 6
            else:
                return ("", start, False)
            run_start = i
            continue
        if c < 32:
            return ("", start, False)
        i += 1
    return ("", start, False)


def parse_json_number(line: String, start: Int) -> Tuple[Float64, Int, Bool]:
    var b = line.as_bytes()
    var i = start
    var neg = False
    if i < len(b) and b[i] == 45:
        neg = True
        i += 1
    var v = 0.0
    var any_digit = False
    while i < len(b) and b[i] >= 48 and b[i] <= 57:
        v = v * 10.0 + Float64(Int(b[i]) - 48)
        any_digit = True
        i += 1
    if i < len(b) and b[i] == 46:
        i += 1
        var frac = 0.1
        var frac_digit = False
        while i < len(b) and b[i] >= 48 and b[i] <= 57:
            v += Float64(Int(b[i]) - 48) * frac
            frac *= 0.1
            frac_digit = True
            i += 1
        if not frac_digit:
            return (0.0, start, False)
        any_digit = True
    if not any_digit:
        return (0.0, start, False)
    if i < len(b) and (b[i] == 101 or b[i] == 69):
        i += 1
        var exp_neg = False
        if i < len(b) and (b[i] == 45 or b[i] == 43):
            exp_neg = b[i] == 45
            i += 1
        var exp = 0
        var exp_digit = False
        while i < len(b) and b[i] >= 48 and b[i] <= 57:
            exp = exp * 10 + Int(b[i]) - 48
            exp_digit = True
            i += 1
        if not exp_digit:
            return (0.0, start, False)
        var mult = 1.0
        for _ in range(exp):
            mult *= 10.0
        if exp_neg:
            v = v / mult
        else:
            v = v * mult
    if neg:
        v = -v
    return (v, i, True)


def matches_lit(line: String, i: Int, lit: String) -> Bool:
    var b = line.as_bytes()
    var lb = lit.as_bytes()
    if i + len(lb) > len(b):
        return False
    for k in range(len(lb)):
        if b[i + k] != lb[k]:
            return False
    return True


def skip_json_value(line: String, start: Int) -> Tuple[Int, Bool]:
    """Skip one JSON value of any shape. Used for unknown fields and for
    nested values the caller does not need to decode."""
    var b = line.as_bytes()
    var i = skip_ws(line, start)
    if i >= len(b):
        return (i, False)
    var c = b[i]
    if c == 34:
        var s = parse_json_string(line, i)
        return (s[1], s[2])
    if c == 123 or c == 91:
        var open_c = c
        var close_c: UInt8 = 125
        if c == 91:
            close_c = 93
        var depth = 0
        var j = i
        while j < len(b):
            var d = b[j]
            if d == 34:
                var s = parse_json_string(line, j)
                if not s[2]:
                    return (j, False)
                j = s[1]
                continue
            if d == open_c:
                depth += 1
            elif d == close_c:
                depth -= 1
                if depth == 0:
                    return (j + 1, True)
            j += 1
        return (j, False)
    if c == 45 or (c >= 48 and c <= 57):
        var n = parse_json_number(line, i)
        return (n[1], n[2])
    if matches_lit(line, i, "true"):
        return (i + 4, True)
    if matches_lit(line, i, "false"):
        return (i + 5, True)
    if matches_lit(line, i, "null"):
        return (i + 4, True)
    return (i, False)


def parse_json_event(line: String) -> EventFields:
    """Parse one JSON-lines event object into flat fields. Unknown keys
    are skipped; `meta` is flattened with a 'meta.' prefix. A missing
    required key is not fatal to the JSON parse, but the event is
    reported as not-ok so the pipeline counts it as malformed data."""
    var out = EventFields()
    var b = line.as_bytes()
    var i = skip_ws(line, 0)
    if i >= len(b) or b[i] != 123:
        return out
    i += 1
    i = skip_ws(line, i)
    if i < len(b) and b[i] == 125:
        out.ok = True
        return out
    var seen_ts = False
    var seen_level = False
    var seen_service = False
    while True:
        i = skip_ws(line, i)
        if i >= len(b) or b[i] != 34:
            return out
        var key_read = parse_json_string(line, i)
        if not key_read[2]:
            return out
        var key = key_read[0]
        i = skip_ws(line, key_read[1])
        if i >= len(b) or b[i] != 58:
            return out
        i += 1
        i = skip_ws(line, i)
        if i >= len(b):
            return out
        if key == "meta" and b[i] == 123:
            i += 1
            i = skip_ws(line, i)
            if i < len(b) and b[i] == 125:
                i += 1
            else:
                while True:
                    i = skip_ws(line, i)
                    var mkey_read = parse_json_string(line, i)
                    if not mkey_read[2]:
                        return out
                    var mkey = mkey_read[0]
                    i = skip_ws(line, mkey_read[1])
                    if i >= len(b) or b[i] != 58:
                        return out
                    i += 1
                    i = skip_ws(line, i)
                    if i < len(b) and b[i] == 34:
                        var mval = parse_json_string(line, i)
                        if not mval[2]:
                            return out
                        if mkey == "region":
                            out.region = mval[0]
                        i = mval[1]
                    else:
                        var skipped = skip_json_value(line, i)
                        if not skipped[1]:
                            return out
                        i = skipped[0]
                    i = skip_ws(line, i)
                    if i < len(b) and b[i] == 44:
                        i += 1
                        continue
                    if i < len(b) and b[i] == 125:
                        i += 1
                        break
                    return out
        elif key == "ts" or key == "level" or key == "service" or key == "msg" or key == "request_id":
            var s_read = parse_json_string(line, i)
            if not s_read[2]:
                return out
            if key == "ts":
                out.ts = s_read[0]
                seen_ts = True
            elif key == "level":
                out.level = s_read[0]
                seen_level = True
            elif key == "service":
                out.service = s_read[0]
                seen_service = True
            elif key == "msg":
                out.msg = s_read[0]
            else:
                out.request_id = s_read[0]
            i = s_read[1]
        elif key == "latency_ms" or key == "status":
            var n_read = parse_json_number(line, i)
            if not n_read[2]:
                return out
            if key == "latency_ms":
                out.latency = n_read[0]
                out.has_latency = True
            else:
                out.status = Int(n_read[0])
                out.has_status = True
            i = n_read[1]
        else:
            var skipped2 = skip_json_value(line, i)
            if not skipped2[1]:
                return out
            i = skipped2[0]
        i = skip_ws(line, i)
        if i < len(b) and b[i] == 44:
            i += 1
            continue
        if i < len(b) and b[i] == 125:
            i += 1
            break
        return out
    i = skip_ws(line, i)
    if i != len(b):
        return out
    if not seen_ts or not seen_level or not seen_service:
        return out
    out.ok = True
    return out

# ---------------------------------------------------------------------------
# Aggregates. Latencies are stored as two parallel flat lists (value,
# service) instead of a Dict of lists: appending to a Dict-held list
# would copy the whole list on every event, which is quadratic in the
# number of events per service. Grouping happens once, at report time.
# ---------------------------------------------------------------------------


def approx_eq(a: Float64, b: Float64, tol: Float64) -> Bool:
    var diff = a - b
    if diff < 0.0:
        diff = -diff
    var scale: Float64
    if a < 0.0:
        scale = -a
    else:
        scale = a
    if b < 0.0 and -b > scale:
        scale = -b
    elif b > scale:
        scale = b
    if scale < 1.0:
        scale = 1.0
    return diff <= tol * scale


struct JsonAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var missing_latency: Int
    var missing_status: Int
    var missing_request_id: Int
    var level_counts: Dict[String, Int]
    var service_counts: Dict[String, Int]
    var service_errors: Dict[String, Int]
    var region_counts: Dict[String, Int]
    var status_counts: Dict[Int, Int]
    var service_latency_sum: Dict[String, Float64]
    var service_max_latency: Dict[String, Float64]
    var lat_values: List[Float64]
    var lat_services: List[String]
    var request_ids: Dict[String, Int]
    var dup_ids: Int
    var dup_extra: Int
    var malformed_samples: List[String]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.missing_latency = 0
        self.missing_status = 0
        self.missing_request_id = 0
        self.level_counts = Dict[String, Int]()
        self.service_counts = Dict[String, Int]()
        self.service_errors = Dict[String, Int]()
        self.region_counts = Dict[String, Int]()
        self.status_counts = Dict[Int, Int]()
        self.service_latency_sum = Dict[String, Float64]()
        self.service_max_latency = Dict[String, Float64]()
        self.lat_values = List[Float64]()
        self.lat_services = List[String]()
        self.request_ids = Dict[String, Int]()
        self.dup_ids = 0
        self.dup_extra = 0
        self.malformed_samples = List[String]()

    def add_event(mut self, f: EventFields, raw: String):
        self.total += 1
        if not f.ok:
            self.malformed += 1
            if len(self.malformed_samples) < 3:
                self.malformed_samples.append(raw)
            return
        self.parsed += 1
        self.level_counts[f.level] = self.level_counts.get(f.level, 0) + 1
        self.service_counts[f.service] = self.service_counts.get(f.service, 0) + 1
        if f.level == "ERROR":
            self.service_errors[f.service] = self.service_errors.get(f.service, 0) + 1
        if f.region != "":
            self.region_counts[f.region] = self.region_counts.get(f.region, 0) + 1
        if f.has_status:
            self.status_counts[f.status] = self.status_counts.get(f.status, 0) + 1
        else:
            self.missing_status += 1
        if f.has_latency:
            self.lat_values.append(f.latency)
            self.lat_services.append(f.service)
            self.service_latency_sum[f.service] = self.service_latency_sum.get(f.service, 0.0) + f.latency
            if f.latency > self.service_max_latency.get(f.service, 0.0):
                self.service_max_latency[f.service] = f.latency
        else:
            self.missing_latency += 1
        if f.request_id != "":
            var seen = self.request_ids.get(f.request_id, 0)
            if seen == 1:
                self.dup_ids += 1
            if seen >= 1:
                self.dup_extra += 1
            self.request_ids[f.request_id] = seen + 1
        else:
            self.missing_request_id += 1

    def merge(mut self, ref other: JsonAgg):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        self.missing_latency += other.missing_latency
        self.missing_status += other.missing_status
        self.missing_request_id += other.missing_request_id
        for k in other.level_counts.keys():
            self.level_counts[k] = self.level_counts.get(k, 0) + other.level_counts.get(k, 0)
        for k in other.service_counts.keys():
            self.service_counts[k] = self.service_counts.get(k, 0) + other.service_counts.get(k, 0)
        for k in other.service_errors.keys():
            self.service_errors[k] = self.service_errors.get(k, 0) + other.service_errors.get(k, 0)
        for k in other.region_counts.keys():
            self.region_counts[k] = self.region_counts.get(k, 0) + other.region_counts.get(k, 0)
        for k in other.status_counts.keys():
            self.status_counts[k] = self.status_counts.get(k, 0) + other.status_counts.get(k, 0)
        for k in other.service_latency_sum.keys():
            self.service_latency_sum[k] = self.service_latency_sum.get(k, 0.0) + other.service_latency_sum.get(k, 0.0)
        for k in other.service_max_latency.keys():
            if other.service_max_latency.get(k, 0.0) > self.service_max_latency.get(k, 0.0):
                self.service_max_latency[k] = other.service_max_latency.get(k, 0.0)
        for i in range(len(other.lat_values)):
            self.lat_values.append(other.lat_values[i])
            self.lat_services.append(other.lat_services[i])
        self.dup_ids += other.dup_ids
        self.dup_extra += other.dup_extra
        for k in other.request_ids.keys():
            var seen = self.request_ids.get(k, 0)
            var add = other.request_ids.get(k, 0)
            var new_count = seen + add
            # dup_ids counts ids seen more than once, globally. The
            # delta is (new dup flag) minus (old dup flags on both sides):
            # merging two sides that each already hold the id must not
            # count it twice, and merging two singletons creates one dup.
            var new_dup = 0
            if new_count > 1:
                new_dup = 1
            var old_dup = 0
            if seen > 1:
                old_dup += 1
            if add > 1:
                old_dup += 1
            self.dup_ids += new_dup - old_dup
            # dup_extra counts occurrences beyond the first, globally.
            var new_extra = 0
            if new_count > 1:
                new_extra = new_count - 1
            var old_extra = 0
            if seen > 1:
                old_extra += seen - 1
            if add > 1:
                old_extra += add - 1
            self.dup_extra += new_extra - old_extra
            self.request_ids[k] = new_count
        for s in other.malformed_samples:
            if len(self.malformed_samples) < 3:
                self.malformed_samples.append(s)


def service_latencies(ref agg: JsonAgg, service: String) -> List[Float64]:
    """All latencies for one service, sorted ascending (exact
    percentiles need the sorted order; sorting happens once per call)."""
    var out = List[Float64]()
    for i in range(len(agg.lat_values)):
        if agg.lat_services[i] == service:
            out.append(agg.lat_values[i])
    sort(out)
    return out^


def percentile(sorted_vals: List[Float64], p: Float64) -> Float64:
    """Nearest-rank percentile over an already-sorted list."""
    if len(sorted_vals) == 0:
        return 0.0
    var rank = Int(p * Float64(len(sorted_vals)) + 0.999999)
    if rank < 1:
        rank = 1
    if rank > len(sorted_vals):
        rank = len(sorted_vals)
    return sorted_vals[rank - 1]


def dict_int_equal(a: Dict[String, Int], b: Dict[String, Int]) -> Bool:
    if len(a) != len(b):
        return False
    for k in a.keys():
        if k not in b or b.get(k, 0) != a.get(k, 0):
            return False
    return True


def dict_float_equal(a: Dict[String, Float64], b: Dict[String, Float64], tol: Float64) -> Bool:
    if len(a) != len(b):
        return False
    for k in a.keys():
        if k not in b or not approx_eq(b.get(k, 0.0), a.get(k, 0.0), tol):
            return False
    return True


def agg_equal(ref a: JsonAgg, ref b: JsonAgg) -> Bool:
    if a.total != b.total or a.parsed != b.parsed or a.malformed != b.malformed:
        return False
    if a.missing_latency != b.missing_latency or a.missing_status != b.missing_status:
        return False
    if a.missing_request_id != b.missing_request_id:
        return False
    if a.dup_ids != b.dup_ids or a.dup_extra != b.dup_extra:
        return False
    if not dict_int_equal(a.level_counts, b.level_counts):
        return False
    if not dict_int_equal(a.service_counts, b.service_counts):
        return False
    if not dict_int_equal(a.service_errors, b.service_errors):
        return False
    if not dict_int_equal(a.region_counts, b.region_counts):
        return False
    if len(a.status_counts) != len(b.status_counts):
        return False
    for k in a.status_counts.keys():
        if k not in b.status_counts or b.status_counts.get(k, 0) != a.status_counts.get(k, 0):
            return False
    if not dict_float_equal(a.service_latency_sum, b.service_latency_sum, 1e-9):
        return False
    if not dict_float_equal(a.service_max_latency, b.service_max_latency, 1e-9):
        return False
    if len(a.lat_values) != len(b.lat_values):
        return False
    # Full latency distributions must agree as multisets: compare the
    # per-service sorted lists element by element.
    for svc in a.service_counts.keys():
        var svc_name = String(svc)
        var la = service_latencies(a, svc_name)
        var lb = service_latencies(b, svc_name)
        if len(la) != len(lb):
            return False
        for i in range(len(la)):
            if not approx_eq(la[i], lb[i], 1e-9):
                return False
    return True


# ---------------------------------------------------------------------------
# Parsers: reference (single-threaded) and parallel (chunked map-reduce).
# ---------------------------------------------------------------------------


def to_owned_lines(text: String) raises -> List[String]:
    var slices = text.split("\n")
    var lines = List[String]()
    for i in range(len(slices)):
        lines.append(String(slices[i]))
    return lines^


def parse_range(lines: List[String], start: Int, end: Int) -> JsonAgg:
    var agg = JsonAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        agg.add_event(parse_json_event(lines[i]), lines[i])
    return agg^


def parse_reference(text: String) raises -> JsonAgg:
    var lines = to_owned_lines(text)
    return parse_range(lines, 0, len(lines))


def parse_parallel(text: String, workers: Int) raises -> JsonAgg:
    var lines = to_owned_lines(text)
    var n = len(lines)
    var chunk_size = 2000
    var n_chunks = (n + chunk_size - 1) / chunk_size
    if n_chunks < 1:
        n_chunks = 1
    var chunk_aggs = List[JsonAgg]()
    for _ in range(n_chunks):
        chunk_aggs.append(JsonAgg())

    def work(i: Int) {mut chunk_aggs, imm lines, imm n, imm chunk_size}:
        var start = i * chunk_size
        var end = start + chunk_size
        if end > n:
            end = n
        var agg = parse_range(lines, start, end)
        chunk_aggs[i] = agg^

    # NOTE (Mojo 1.2.0): the plain `mojo` package no longer ships
    # `parallelize` -- it moved to the MAX package, which is not a
    # stdlib dependency here. Chunks therefore run sequentially in
    # this build; the chunk/merge structure is unchanged, so restoring
    # multi-core dispatch is a one-line change (call parallelize
    # from MAX instead of this loop) once MAX is available.
    for i in range(n_chunks):
        work(i)
    var result = JsonAgg()
    for i in range(n_chunks):
        result.merge(chunk_aggs[i])
    return result^


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


def fmt2(x: Float64) -> String:
    var neg = False
    var v = x
    if v < 0.0:
        neg = True
        v = -v
    var scaled = Int(v * 100.0 + 0.5)
    var whole = scaled / 100
    var frac = scaled - whole * 100
    var frac_s = String(frac)
    if frac < 10:
        frac_s = "0" + frac_s
    var out = String(whole) + "." + frac_s
    if neg:
        return "-" + out
    return out


def print_report(ref agg: JsonAgg, elapsed_s: Float64, label: String):
    print("---- " + label + " ----")
    print("lines total:       ", agg.total)
    print("events parsed:     ", agg.parsed)
    print("lines malformed:   ", agg.malformed)
    print("missing latency:   ", agg.missing_latency)
    print("missing status:    ", agg.missing_status)
    print("missing request_id:", agg.missing_request_id)
    print("duplicate req ids: ", agg.dup_ids, " ids,", agg.dup_extra, " extra occurrences")
    print("levels:")
    var levels = List[String]()
    for k in agg.level_counts.keys():
        levels.append(k)
    sort(levels)
    for k in levels:
        print("  ", k, ": ", agg.level_counts.get(k, 0))
    print("services (count, errors, error rate, mean/p50/p95/p99/max latency ms):")
    var services = List[String]()
    for k in agg.service_counts.keys():
        services.append(k)
    sort(services)
    for svc in services:
        var svc_name = String(svc)
        var count = agg.service_counts.get(svc_name, 0)
        var errs = agg.service_errors.get(svc_name, 0)
        var rate = 0.0
        if count > 0:
            rate = 100.0 * Float64(errs) / Float64(count)
        var lats = service_latencies(agg, svc_name)
        var mean = 0.0
        if len(lats) > 0:
            mean = agg.service_latency_sum.get(svc_name, 0.0) / Float64(len(lats))
        print(
            "  ",
            svc,
            " n=",
            count,
            " err=",
            errs,
            " (",
            fmt2(rate),
            "%) mean=",
            fmt2(mean),
            " p50=",
            fmt2(percentile(lats, 0.50)),
            " p95=",
            fmt2(percentile(lats, 0.95)),
            " p99=",
            fmt2(percentile(lats, 0.99)),
            " max=",
            fmt2(agg.service_max_latency.get(svc_name, 0.0)),
        )
    print("regions:")
    for k in agg.region_counts.keys():
        print("  ", k, ": ", agg.region_counts.get(k, 0))
    print("status codes:")
    var codes = List[Int]()
    for k in agg.status_counts.keys():
        codes.append(k)
    sort(codes)
    for code in codes:
        print("  ", code, ": ", agg.status_counts.get(code, 0))
    if len(agg.malformed_samples) > 0:
        print("malformed samples:")
        for s in agg.malformed_samples:
            var shown = s
            if shown.byte_length() > 120:
                shown = String(shown[byte = 0:120]) + "..."
            print("  ", shown)
    var rate = 0.0
    if elapsed_s > 0.0:
        rate = Float64(agg.total) / elapsed_s
    print("elapsed: ", elapsed_s, "s  (", rate, " lines/s)")

# ---------------------------------------------------------------------------
# Unit tests.
# ---------------------------------------------------------------------------


def test_json_strings() raises:
    var s = parse_json_string(String('"hello"'), 0)
    assert_true(s[2])
    assert_equal(s[0], "hello")
    assert_equal(s[1], 7)
    var esc = parse_json_string(String('"a\\"b\\\\c\\/d\\n\\t\\u0041"'), 0)
    assert_true(esc[2])
    assert_equal(esc[0], "a\"b\\c/d\n\tA")
    var bad1 = parse_json_string(String('"unterminated'), 0)
    assert_true(not bad1[2])
    var bad2 = parse_json_string(String('"bad\\xescape"'), 0)
    assert_true(not bad2[2])
    var bad3 = parse_json_string(String('"bad\\u00zz"'), 0)
    assert_true(not bad3[2])
    var empty = parse_json_string(String('""'), 0)
    assert_true(empty[2])
    assert_equal(empty[0], "")
    print("  test_json_strings OK")


def test_json_numbers() raises:
    var n1 = parse_json_number(String("123.45"), 0)
    assert_true(n1[2])
    assert_almost_equal(n1[0], 123.45, atol=1e-9, rtol=1e-9)
    var n2 = parse_json_number(String("-2.5e3"), 0)
    assert_almost_equal(n2[0], -2500.0, atol=1e-9, rtol=1e-9)
    var n3 = parse_json_number(String("0.001"), 0)
    assert_almost_equal(n3[0], 0.001, atol=1e-12, rtol=1e-9)
    var n4 = parse_json_number(String("42"), 0)
    assert_almost_equal(n4[0], 42.0, atol=1e-9, rtol=1e-9)
    assert_equal(n4[1], 2)
    var bad = parse_json_number(String("1."), 0)
    assert_true(not bad[2])
    var bad2 = parse_json_number(String("e5"), 0)
    assert_true(not bad2[2])
    print("  test_json_numbers OK")


def test_json_skip() raises:
    var line = String('{"a": {"b": [1, 2, {"c": "x}]"}}, "d": true}')
    var skipped = skip_json_value(line, 0)
    assert_true(skipped[1])
    assert_equal(skipped[0], line.byte_length())
    var arr = skip_json_value(String('[1, "two", null, false]'), 0)
    assert_true(arr[1])
    var lit = skip_json_value(String("null"), 0)
    assert_true(lit[1])
    assert_equal(lit[0], 4)
    var bad = skip_json_value(String("{unclosed"), 0)
    assert_true(not bad[1])
    print("  test_json_skip OK")


def test_parse_event() raises:
    var line = String(
        '{"ts":"2026-11-05T00:00:01Z","level":"ERROR","service":"orders",'
        + '"msg":"order failed: \\"bad qty\\"","latency_ms":1234.5,"status":500,'
        + '"request_id":"req-1","meta":{"region":"eu-west-1"}}'
    )
    var f = parse_json_event(line)
    assert_true(f.ok)
    assert_equal(f.ts, "2026-11-05T00:00:01Z")
    assert_equal(f.level, "ERROR")
    assert_equal(f.service, "orders")
    assert_equal(f.msg, 'order failed: "bad qty"')
    assert_almost_equal(f.latency, 1234.5, atol=1e-9, rtol=1e-9)
    assert_true(f.has_latency)
    assert_equal(f.status, 500)
    assert_true(f.has_status)
    assert_equal(f.request_id, "req-1")
    assert_equal(f.region, "eu-west-1")
    # Unknown fields and nested arrays are skipped, not errors.
    var extra = parse_json_event(
        String(
            '{"ts":"2026-11-05T00:00:01Z","level":"INFO","service":"auth",'
            + '"tags":["a","b"],"trace":{"id":"t1","spans":[1,2]},"latency_ms":5.0,'
            + '"status":200,"request_id":"req-2","meta":{"region":"us-east-1"}}'
        )
    )
    assert_true(extra.ok)
    assert_equal(extra.service, "auth")
    assert_equal(extra.region, "us-east-1")
    # Missing optional fields still parse; missing required keys do not.
    var no_lat = parse_json_event(
        String(
            '{"ts":"2026-11-05T00:00:01Z","level":"INFO","service":"auth",'
            + '"status":200,"request_id":"req-3"}'
        )
    )
    assert_true(no_lat.ok)
    assert_true(not no_lat.has_latency)
    var no_svc = parse_json_event(String('{"ts":"2026-11-05T00:00:01Z","level":"INFO"}'))
    assert_true(not no_svc.ok)
    # Malformed JSON is rejected.
    assert_true(not parse_json_event(String("not json")).ok)
    assert_true(not parse_json_event(String('{"ts": "x",}')).ok)
    assert_true(not parse_json_event(String('{"ts" "x"}')).ok)
    assert_true(not parse_json_event(String('{"ts":"x"')).ok)
    assert_true(not parse_json_event(String('{"ts":"x"} trailing')).ok)
    assert_true(not parse_json_event(String("")).ok)
    print("  test_parse_event OK")


def test_percentiles() raises:
    var vals = List[Float64]()
    for i in range(1, 101):
        vals.append(Float64(i))
    assert_almost_equal(percentile(vals, 0.50), 50.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(percentile(vals, 0.95), 95.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(percentile(vals, 0.99), 99.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(percentile(vals, 0.0), 1.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(percentile(vals, 1.0), 100.0, atol=1e-9, rtol=1e-9)
    var empty = List[Float64]()
    assert_almost_equal(percentile(empty, 0.5), 0.0, atol=1e-9, rtol=1e-9)
    print("  test_percentiles OK")


def test_aggregate_small() raises:
    var text = String(
        '{"ts":"2026-11-05T00:00:01Z","level":"INFO","service":"orders","msg":"ok","latency_ms":10.0,"status":200,"request_id":"req-1","meta":{"region":"us-east-1"}}\n'
        + '{"ts":"2026-11-05T00:00:02Z","level":"ERROR","service":"orders","msg":"bad","latency_ms":900.0,"status":500,"request_id":"req-2","meta":{"region":"us-east-1"}}\n'
        + '{"ts":"2026-11-05T00:00:03Z","level":"INFO","service":"auth","msg":"ok","latency_ms":30.0,"status":200,"request_id":"req-1","meta":{"region":"eu-west-1"}}\n'
        + '{"ts":"2026-11-05T00:00:04Z","level":"WARN","service":"auth","msg":"slow","latency_ms":200.0,"status":200,"request_id":"req-3","meta":{"region":"eu-west-1"}}\n'
        + '{"ts":"2026-11-05T00:00:05Z","level":"INFO","service":"auth","msg":"ok","status":200,"request_id":"req-4"}\n'
        + 'this is not json\n'
    )
    var agg = parse_reference(text)
    assert_equal(agg.total, 6)
    assert_equal(agg.parsed, 5)
    assert_equal(agg.malformed, 1)
    assert_equal(agg.level_counts.get("INFO", 0), 3)
    assert_equal(agg.level_counts.get("ERROR", 0), 1)
    assert_equal(agg.level_counts.get("WARN", 0), 1)
    assert_equal(agg.service_counts.get("orders", 0), 2)
    assert_equal(agg.service_counts.get("auth", 0), 3)
    assert_equal(agg.service_errors.get("orders", 0), 1)
    assert_equal(agg.service_errors.get("auth", 0), 0)
    assert_equal(agg.region_counts.get("us-east-1", 0), 2)
    assert_equal(agg.region_counts.get("eu-west-1", 0), 2)
    assert_equal(agg.status_counts.get(200, 0), 4)
    assert_equal(agg.status_counts.get(500, 0), 1)
    assert_equal(agg.missing_latency, 1)
    assert_equal(agg.missing_status, 0)
    assert_equal(agg.dup_ids, 1)
    assert_equal(agg.dup_extra, 1)
    var orders_lat = service_latencies(agg, "orders")
    assert_equal(len(orders_lat), 2)
    assert_almost_equal(percentile(orders_lat, 0.50), 10.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(percentile(orders_lat, 0.95), 900.0, atol=1e-9, rtol=1e-9)
    var par = parse_parallel(text, 2)
    assert_true(agg_equal(agg, par), "parallel must equal reference on small input")
    print("  test_aggregate_small OK")


def test_dup_merge() raises:
    # Duplicates split across chunks must merge to the same counts as
    # the single-threaded parse: req-1 appears twice in chunk 1 and
    # once in chunk 2 in the reference order.
    var lines = List[String]()
    for _ in range(2500):
        lines.append(
            '{"ts":"2026-11-05T00:00:01Z","level":"INFO","service":"auth","msg":"ok","latency_ms":10.0,"status":200,"request_id":"req-1"}'
        )
    for _ in range(2500):
        lines.append(
            '{"ts":"2026-11-05T00:00:02Z","level":"INFO","service":"auth","msg":"ok","latency_ms":20.0,"status":200,"request_id":"req-1"}'
        )
    var text = String("\n").join(lines) + "\n"
    var ref_agg = parse_reference(text)
    assert_equal(ref_agg.dup_ids, 1)
    assert_equal(ref_agg.dup_extra, 4999)
    var par_agg = parse_parallel(text, 4)
    assert_true(agg_equal(ref_agg, par_agg), "duplicate accounting must agree across chunks")
    print("  test_dup_merge OK")


def run_tests() raises:
    print("Running unit tests:")
    test_json_strings()
    test_json_numbers()
    test_json_skip()
    test_parse_event()
    test_percentiles()
    test_aggregate_small()
    test_dup_merge()
    print("All JSON-lines unit tests passed.")


# ---------------------------------------------------------------------------
# Embedded fallback generator (same format / seed family as etl_gen_data).
# ---------------------------------------------------------------------------


def gen_services() -> List[String]:
    var s = List[String]()
    s.append("gateway")
    s.append("auth")
    s.append("orders")
    s.append("pricing")
    s.append("inventory")
    s.append("notify")
    return s^


def gen_level() -> String:
    var r = random_float64()
    if r < 0.62:
        return "INFO"
    if r < 0.82:
        return "DEBUG"
    if r < 0.93:
        return "WARN"
    return "ERROR"


def gen_msg(level: String) -> String:
    if level == "ERROR":
        var m = List[String]()
        m.append("upstream timeout after 3000ms")
        m.append("connection reset by peer")
        m.append("order validation failed: negative quantity")
        return m[Int(random_float64() * Float64(len(m)))]
    if level == "WARN":
        var m = List[String]()
        m.append("retrying upstream request (attempt 2)")
        m.append("slow query: 812ms on orders table")
        return m[Int(random_float64() * Float64(len(m)))]
    return "request completed"


def two_digit(n: Int) -> String:
    if n < 10:
        return "0" + String(n)
    return String(n)


def ensure_input(data_dir: String) raises -> Path:
    var path = Path(data_dir + "/events.jsonl")
    if path.exists():
        return path
    print("events.jsonl not found in " + data_dir + "; generating 30,000 events ...")
    if not Path(data_dir).exists():
        mkdir(data_dir)
    seed(20261107)
    var services = gen_services()
    var regions = List[String]()
    regions.append("us-east-1")
    regions.append("us-west-2")
    regions.append("eu-west-1")
    regions.append("ap-south-1")
    var lines = List[String]()
    var ts = 1793836800
    for _ in range(30000):
        ts += 1 + Int(random_float64() * 3.0)
        var level = gen_level()
        var service = services[Int(random_float64() * Float64(len(services)))]
        var latency = 42.0 * (1.0 + (random_float64() - 0.5) * 2.0)
        if latency < 0.5:
            latency = 0.5
        if level == "ERROR":
            latency += 900.0 + random_float64() * 1800.0
        var hh = (ts / 3600) % 24
        var mm = (ts / 60) % 60
        var ss = ts % 60
        var ts_s = "2026-11-05T" + two_digit(hh) + ":" + two_digit(mm) + ":" + two_digit(ss) + "Z"
        var lat_s = fmt2(latency)
        lines.append(
            '{"ts":"'
            + ts_s
            + '","level":"'
            + level
            + '","service":"'
            + service
            + '","msg":"'
            + gen_msg(level)
            + '","latency_ms":'
            + lat_s
            + ',"status":200,"request_id":"req-'
            + String(100000 + Int(random_float64() * 900000.0))
            + '","meta":{"region":"'
            + regions[Int(random_float64() * Float64(len(regions)))]
            + '"}}'
        )
    path.write_text(String("\n").join(lines) + "\n")
    print("  generated", path, "30,000 events")
    return path


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def main() raises:
    run_tests()
    var args = argv()
    var data_dir = "/tmp/etl_data"
    if len(args) > 1:
        data_dir = String(args[1])
    var workers = 4
    if len(args) > 2:
        workers = Int(String(args[2]))
    if workers < 1:
        workers = 1
    if workers > 16:
        workers = 16
    var path = ensure_input(data_dir)
    print("Reading", path, "...")
    var t_read0 = perf_counter()
    var text = path.read_text()
    var t_read = perf_counter() - t_read0
    print("  file size:", text.byte_length(), "bytes in", t_read, "s")

    var t0 = perf_counter()
    var ref_agg = parse_reference(text)
    var t_ref = perf_counter() - t0
    print_report(ref_agg, t_ref, "single-threaded reference")

    var t1 = perf_counter()
    var par_agg = parse_parallel(text, workers)
    var t_par = perf_counter() - t1
    print_report(par_agg, t_par, "parallel (" + String(workers) + " workers)")

    assert_true(agg_equal(ref_agg, par_agg), "parallel result must equal reference result")
    print("ASSERTION PASSED: parallel == reference on every aggregate.")
    if t_par > 0.0 and t_ref > 0.0:
        print("speedup:", t_ref / t_par, "x with", workers, "workers")
    print("DONE: JSON-lines parse verified.")
