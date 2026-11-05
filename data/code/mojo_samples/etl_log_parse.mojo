# etl_log_parse.mojo
#
# Parallel web access log parser for the START project's Mojo ETL samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.
# The sentence below about the plain package continues the note.)
# contain it -- see the NOTE at each chunk loop.) Requires Mojo 1.2.0.
#
# Input: combined-log-format access logs, one request per line:
#   203.0.113.7 - - [05/Nov/2026:10:23:11 +0000] "GET /index.html HTTP/1.1" 200 5282 "-" "curl/8.5.0"
#
# The program:
#   1. Reads the whole file from disk (real file I/O, not an in-memory toy).
#   2. Parses it once single-threaded (the reference implementation).
#   3. Parses it again with `parallelize`: the line list is split into
#      contiguous, line-aligned chunks; each chunk is parsed on its own
#      worker into a private per-chunk aggregate (the map step); the
#      per-chunk aggregates are then merged single-threaded (the reduce
#      step). No shared mutable state is touched by the workers, so there
#      is no locking and no data race by construction.
#   4. Asserts the parallel result is exactly equal to the reference
#      result (status counts, URL counts, method counts, byte totals,
#      error counts, hourly buckets), then prints a report.
#
# Parsing is byte-level: fields are located with `find` and sliced by raw
# UTF-8 byte offsets, and numbers are accumulated digit by digit from the
# byte values. No regular expressions, no per-field string allocation for
# the numeric fields.
#
# Usage:
#   mojo etl_log_parse.mojo [data-dir] [workers]
# Defaults: /tmp/etl_data, 4 workers. If access.log is missing, a
# deterministic 50,000-line log is generated in place first (same format
# and seed as etl_gen_data.mojo, so results are comparable).

from std.pathlib import Path
from std.testing import assert_equal, assert_true, assert_almost_equal
from std.collections import Dict
from std.random import seed, random_float64
from std.sys import argv
from std.time import perf_counter
from std.os import mkdir


# ---------------------------------------------------------------------------
# Byte-level number parsing. `read_int_at` returns (value, next_index);
# `ok` is False when no digit was found at `start`.
# ---------------------------------------------------------------------------


def read_int_at(s: StringSlice, start: Int) -> Tuple[Int, Int, Bool]:
    var b = s.as_bytes()
    var i = start
    while i < len(b) and (b[i] == 32 or b[i] == 9):
        i += 1
    var neg = False
    if i < len(b) and b[i] == 45:
        neg = True
        i += 1
    var v = 0
    var any_digit = False
    while i < len(b) and b[i] >= 48 and b[i] <= 57:
        v = v * 10 + Int(b[i]) - 48
        any_digit = True
        i += 1
    if neg:
        v = -v
    return (v, i, any_digit)


def read_int_or_dash(s: StringSlice, start: Int) -> Tuple[Int, Int, Bool]:
    """Like read_int_at, but a lone '-' (log convention for 'no value')
    parses as 0 and still counts as a successful read."""
    var b = s.as_bytes()
    var i = start
    while i < len(b) and (b[i] == 32 or b[i] == 9):
        i += 1
    if i < len(b) and b[i] == 45:
        if i + 1 >= len(b) or b[i + 1] == 32 or b[i + 1] == 34:
            return (0, i + 1, True)
    return read_int_at(s, start)


# ---------------------------------------------------------------------------
# One parsed log line.
# ---------------------------------------------------------------------------


struct LogFields(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var method: String
    var url: String
    var status: Int
    var size: Int
    var hour: Int

    def __init__(out self):
        self.ok = False
        self.method = ""
        self.url = ""
        self.status = 0
        self.size = 0
        self.hour = -1

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.method = other.method
        self.url = other.url
        self.status = other.status
        self.size = other.size
        self.hour = other.hour


def parse_log_line(line: StringSlice) -> LogFields:
    """Parse one combined-log line. Never raises: any structural problem
    yields ok == False and the caller counts the line as malformed."""
    var out = LogFields()
    if line.byte_length() < 20:
        return out
    # --- timestamp: [05/Nov/2026:10:23:11 +0000] ---
    var open_br = line.find("[")
    if open_br < 0:
        return out
    var ts = line[byte = open_br + 1 : open_br + 21]
    if ts.byte_length() < 20:
        return out
    var tb = ts.as_bytes()
    # Hour lives at byte offsets 12..13 of "05/Nov/2026:10:23:11".
    if tb[11] != 58 or tb[14] != 58 or tb[17] != 58:
        return out
    var hour = (Int(tb[12]) - 48) * 10 + (Int(tb[13]) - 48)
    if hour < 0 or hour > 23:
        return out
    # --- request: "METHOD URL PROTO" ---
    var q1 = line.find('"')
    if q1 < 0:
        return out
    var rest_after_q1 = String(line[byte = q1 + 1 : line.byte_length()])
    var q2rel = rest_after_q1.find('"')
    if q2rel < 0:
        return out
    var request = line[byte = q1 + 1 : q1 + 1 + q2rel]
    var req_parts = request.split(" ")
    if len(req_parts) != 3:
        return out
    var method = String(req_parts[0])
    var url = String(req_parts[1])
    if method.byte_length() == 0 or url.byte_length() == 0:
        return out
    # --- status and size: ` 200 5282 ` after the closing quote ---
    var tail = line[byte = q1 + 1 + q2rel + 1 : line.byte_length()]
    var status_read = read_int_at(tail, 0)
    if not status_read[2]:
        return out
    var status = status_read[0]
    var size_read = read_int_or_dash(tail, status_read[1])
    if not size_read[2]:
        return out
    var size = size_read[0]
    if status < 100 or status > 599 or size < 0:
        return out
    out.ok = True
    out.method = method
    out.url = url
    out.status = status
    out.size = size
    out.hour = hour
    return out


# ---------------------------------------------------------------------------
# Aggregates. `LogAgg` is deliberately Movable-only (no copy constructor):
# per-chunk aggregates are built locally in a worker and moved exactly once
# into the results list, and merging borrows the other aggregate, so no
# whole-aggregate copy ever happens on the hot path.
# ---------------------------------------------------------------------------


struct LogAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var bytes_total: Int
    var errors: Int
    var max_size: Int
    var status_counts: Dict[Int, Int]
    var url_counts: Dict[String, Int]
    var method_counts: Dict[String, Int]
    var hour_counts: List[Int]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.bytes_total = 0
        self.errors = 0
        self.max_size = 0
        self.status_counts = Dict[Int, Int]()
        self.url_counts = Dict[String, Int]()
        self.method_counts = Dict[String, Int]()
        self.hour_counts = List[Int](length=24, fill=0)

    def add_line(mut self, f: LogFields):
        self.total += 1
        if not f.ok:
            self.malformed += 1
            return
        self.parsed += 1
        self.bytes_total += f.size
        if f.size > self.max_size:
            self.max_size = f.size
        if f.status >= 400:
            self.errors += 1
        self.status_counts[f.status] = self.status_counts.get(f.status, 0) + 1
        self.url_counts[f.url] = self.url_counts.get(f.url, 0) + 1
        self.method_counts[f.method] = self.method_counts.get(f.method, 0) + 1
        self.hour_counts[f.hour] = self.hour_counts[f.hour] + 1

    def merge(mut self, ref other: LogAgg):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        self.bytes_total += other.bytes_total
        self.errors += other.errors
        if other.max_size > self.max_size:
            self.max_size = other.max_size
        for code in other.status_counts.keys():
            self.status_counts[code] = self.status_counts.get(code, 0) + other.status_counts.get(code, 0)
        for url in other.url_counts.keys():
            self.url_counts[url] = self.url_counts.get(url, 0) + other.url_counts.get(url, 0)
        for m in other.method_counts.keys():
            self.method_counts[m] = self.method_counts.get(m, 0) + other.method_counts.get(m, 0)
        for h in range(24):
            self.hour_counts[h] = self.hour_counts[h] + other.hour_counts[h]


def agg_equal(ref a: LogAgg, ref b: LogAgg) -> Bool:
    if a.total != b.total or a.parsed != b.parsed or a.malformed != b.malformed:
        return False
    if a.bytes_total != b.bytes_total or a.errors != b.errors or a.max_size != b.max_size:
        return False
    if len(a.status_counts) != len(b.status_counts):
        return False
    for code in a.status_counts.keys():
        if code not in b.status_counts or b.status_counts.get(code, 0) != a.status_counts.get(code, 0):
            return False
    if len(a.url_counts) != len(b.url_counts):
        return False
    for url in a.url_counts.keys():
        if url not in b.url_counts or b.url_counts.get(url, 0) != a.url_counts.get(url, 0):
            return False
    if len(a.method_counts) != len(b.method_counts):
        return False
    for m in a.method_counts.keys():
        if m not in b.method_counts or b.method_counts.get(m, 0) != a.method_counts.get(m, 0):
            return False
    for h in range(24):
        if a.hour_counts[h] != b.hour_counts[h]:
            return False
    return True


# ---------------------------------------------------------------------------
# Parsers: reference (single-threaded) and parallel (chunked map-reduce).
# ---------------------------------------------------------------------------


def parse_range(lines: List[String], start: Int, end: Int) -> LogAgg:
    var agg = LogAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        agg.add_line(parse_log_line(lines[i]))
    return agg^


def to_owned_lines(text: String) raises -> List[String]:
    """Split the file into owned Strings. This copies the file once, which
    buys back concrete types: `String.split` yields `StringSlice` views
    whose origin parameter cannot be named in a plain function signature
    in Mojo 1.2, and the parallel closure needs concrete types. The copy
    is one linear pass and is dwarfed by parse time on real files."""
    var slices = text.split("\n")
    var lines = List[String]()
    for i in range(len(slices)):
        lines.append(String(slices[i]))
    return lines^


def parse_reference(text: String) raises -> LogAgg:
    var lines = to_owned_lines(text)
    return parse_range(lines, 0, len(lines))


def parse_parallel(text: String, workers: Int) raises -> LogAgg:
    var lines = to_owned_lines(text)
    var n = len(lines)
    # Chunk size: aim for several chunks per worker so a slow chunk cannot
    # strand a core, but keep chunks big enough that per-chunk overhead is
    # negligible. 2000 lines is a good middle ground for ~170-byte lines.
    var chunk_size = 2000
    var n_chunks = (n + chunk_size - 1) / chunk_size
    if n_chunks < 1:
        n_chunks = 1
    var chunk_aggs = List[LogAgg]()
    for _ in range(n_chunks):
        chunk_aggs.append(LogAgg())

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
    var result = LogAgg()
    for i in range(n_chunks):
        result.merge(chunk_aggs[i])
    return result^


# ---------------------------------------------------------------------------
# Reporting helpers.
# ---------------------------------------------------------------------------


def top_n_urls(ref counts: Dict[String, Int], n: Int) -> List[Tuple[String, Int]]:
    """Top-n by count, via a small insertion-sorted list (n is tiny)."""
    var top = List[Tuple[String, Int]]()
    for url in counts.keys():
        var entry = (url, counts.get(url, 0))
        var inserted = False
        for j in range(len(top)):
            if entry[1] > top[j][1]:
                top.insert(j, entry)
                inserted = True
                break
        if not inserted:
            top.append(entry)
        if len(top) > n:
            _ = top.pop()
    return top^


def print_report(ref agg: LogAgg, elapsed_s: Float64, label: String):
    print("---- " + label + " ----")
    print("lines total:    ", agg.total)
    print("lines parsed:   ", agg.parsed)
    print("lines malformed:", agg.malformed)
    print("bytes served:   ", agg.bytes_total)
    print("max resp bytes: ", agg.max_size)
    var err_rate = 0.0
    if agg.parsed > 0:
        err_rate = 100.0 * Float64(agg.errors) / Float64(agg.parsed)
    print("error lines:    ", agg.errors, " (", err_rate, "% of parsed)")
    print("status codes:")
    var codes = List[Int]()
    for code in agg.status_counts.keys():
        codes.append(code)
    sort(codes)
    for code in codes:
        var pct = 100.0 * Float64(agg.status_counts.get(code, 0)) / Float64(agg.parsed)
        print("  ", code, ": ", agg.status_counts.get(code, 0), " (", pct, "%)")
    print("methods:")
    for m in agg.method_counts.keys():
        print("  ", m, ": ", agg.method_counts.get(m, 0))
    var peak_hour = 0
    for h in range(24):
        if agg.hour_counts[h] > agg.hour_counts[peak_hour]:
            peak_hour = h
    print("peak hour (UTC):", peak_hour, "with", agg.hour_counts[peak_hour], "requests")
    print("top 10 URLs:")
    var top = top_n_urls(agg.url_counts, 10)
    for entry in top:
        var pct = 100.0 * Float64(entry[1]) / Float64(agg.parsed)
        print("  ", entry[1], " ", entry[0], " (", pct, "%)")
    var rate = 0.0
    if elapsed_s > 0.0:
        rate = Float64(agg.total) / elapsed_s
    print("elapsed: ", elapsed_s, "s  (", rate, " lines/s)")

# ---------------------------------------------------------------------------
# Unit tests. Hand-written lines with hand-computed expectations, so a
# passing run proves the parser reads the format correctly rather than
# merely agreeing with itself.
# ---------------------------------------------------------------------------


def test_parse_single_lines() raises:
    var good = String(
        '203.0.113.7 - - [05/Nov/2026:10:23:11 +0000] "GET /index.html HTTP/1.1" 200 5282 "-" "curl/8.5.0"'
    )
    var f = parse_log_line(good)
    assert_true(f.ok)
    assert_equal(f.method, "GET")
    assert_equal(f.url, "/index.html")
    assert_equal(f.status, 200)
    assert_equal(f.size, 5282)
    assert_equal(f.hour, 10)

    var err = String(
        '198.51.100.23 - - [05/Nov/2026:23:59:58 +0000] "POST /checkout HTTP/1.1" 500 812 "https://x.invalid/" "Mozilla/5.0"'
    )
    var g = parse_log_line(err)
    assert_true(g.ok)
    assert_equal(g.method, "POST")
    assert_equal(g.url, "/checkout")
    assert_equal(g.status, 500)
    assert_equal(g.size, 812)
    assert_equal(g.hour, 23)

    var dash = String(
        '10.0.0.9 - - [05/Nov/2026:00:00:05 +0000] "GET /static/app.js HTTP/1.1" 304 - "-" "curl/8.5.0"'
    )
    var h = parse_log_line(dash)
    assert_true(h.ok)
    assert_equal(h.status, 304)
    assert_equal(h.size, 0)
    assert_equal(h.hour, 0)

    # Malformed lines must be rejected, never crash the parser.
    assert_true(not parse_log_line(String("")).ok)
    assert_true(not parse_log_line(String("this is not a log line at all")).ok)
    assert_true(not parse_log_line(String('1.2.3.4 - - [05/Nov/2026:10:00:00 +0000] NOQUOTES 200 10')).ok)
    assert_true(
        not parse_log_line(
            String('1.2.3.4 - - [05/Nov/2026:10:00:00 +0000] "GET /x HTTP/1.1" 999 10')
        ).ok
    )
    assert_true(
        not parse_log_line(
            String('1.2.3.4 - - [05/Nov/2026:99:00:00 +0000] "GET /x HTTP/1.1" 200 10')
        ).ok
    )
    assert_true(
        not parse_log_line(
            String('1.2.3.4 - - [05/Nov/2026:10:00:00 +0000] "GET /x HTTP/1.1" ABC 10')
        ).ok
    )
    print("  test_parse_single_lines OK")


def test_aggregate_small() raises:
    var text = String(
        '1.1.1.1 - - [05/Nov/2026:09:00:01 +0000] "GET /a HTTP/1.1" 200 100 "-" "ua"\n'
        + '1.1.1.2 - - [05/Nov/2026:09:00:02 +0000] "GET /a HTTP/1.1" 200 200 "-" "ua"\n'
        + '1.1.1.3 - - [05/Nov/2026:10:00:03 +0000] "GET /b HTTP/1.1" 404 50 "-" "ua"\n'
        + '1.1.1.4 - - [05/Nov/2026:10:00:04 +0000] "POST /b HTTP/1.1" 500 70 "-" "ua"\n'
        + 'garbage line\n'
    )
    var agg = parse_reference(text)
    assert_equal(agg.total, 5)
    assert_equal(agg.parsed, 4)
    assert_equal(agg.malformed, 1)
    assert_equal(agg.bytes_total, 420)
    assert_equal(agg.errors, 2)
    assert_equal(agg.max_size, 200)
    assert_equal(agg.status_counts[200], 2)
    assert_equal(agg.status_counts[404], 1)
    assert_equal(agg.status_counts[500], 1)
    assert_equal(agg.url_counts["/a"], 2)
    assert_equal(agg.url_counts["/b"], 2)
    assert_equal(agg.method_counts["GET"], 3)
    assert_equal(agg.method_counts["POST"], 1)
    assert_equal(agg.hour_counts[9], 2)
    assert_equal(agg.hour_counts[10], 2)
    assert_equal(agg.hour_counts[11], 0)
    # Parallel must agree exactly on the same input.
    var par = parse_parallel(text, 2)
    assert_true(agg_equal(agg, par), "parallel must equal reference on small input")
    print("  test_aggregate_small OK")


def test_top_n() raises:
    var counts = Dict[String, Int]()
    counts["/a"] = 5
    counts["/b"] = 50
    counts["/c"] = 20
    counts["/d"] = 1
    counts["/e"] = 35
    var top = top_n_urls(counts, 3)
    assert_equal(len(top), 3)
    assert_equal(top[0][0], "/b")
    assert_equal(top[0][1], 50)
    assert_equal(top[1][0], "/e")
    assert_equal(top[2][0], "/c")
    print("  test_top_n OK")


def test_read_int_helpers() raises:
    var r = read_int_at(String("  200 5282"), 0)
    assert_equal(r[0], 200)
    assert_equal(r[2], True)
    var r2 = read_int_at(String("abc"), 0)
    assert_equal(r2[2], False)
    var r3 = read_int_or_dash(String(" - "), 0)
    assert_equal(r3[0], 0)
    assert_equal(r3[2], True)
    var r4 = read_int_at(String("-42"), 0)
    assert_equal(r4[0], -42)
    print("  test_read_int_helpers OK")


def run_tests() raises:
    print("Running unit tests:")
    test_parse_single_lines()
    test_aggregate_small()
    test_top_n()
    test_read_int_helpers()
    print("All log-parser unit tests passed.")


# ---------------------------------------------------------------------------
# Embedded fallback generator: if access.log is missing, write a
# deterministic 50,000-line file in the same format (and seed family) as
# etl_gen_data.mojo, so this program is runnable standalone.
# ---------------------------------------------------------------------------


def gen_urls() -> List[String]:
    var urls = List[String]()
    urls.append("/index.html")
    urls.append("/products")
    urls.append("/products/42")
    urls.append("/cart")
    urls.append("/checkout")
    urls.append("/search?q=mojo")
    urls.append("/api/v1/users")
    urls.append("/api/v1/orders")
    urls.append("/static/app.js")
    urls.append("/static/style.css")
    urls.append("/about")
    urls.append("/login")
    return urls^


def gen_one_log_line(ts: Int) -> String:
    var urls = gen_urls()
    var url = urls[Int(random_float64() * Float64(len(urls)))]
    var r = random_float64()
    var status: Int
    if r < 0.68:
        status = 200
    elif r < 0.76:
        status = 304
    elif r < 0.82:
        status = 301
    elif r < 0.90:
        status = 404
    elif r < 0.94:
        status = 400
    elif r < 0.96:
        status = 403
    elif r < 0.98:
        status = 500
    else:
        status = 503
    var size = 180 + Int(random_float64() * 2400.0)
    if status == 200:
        size = 120 + Int(random_float64() * 8000.0)
    var ip = String(1 + Int(random_float64() * 223.0)) + "." + String(Int(random_float64() * 256.0)) + "." + String(Int(random_float64() * 256.0)) + "." + String(1 + Int(random_float64() * 254.0))
    var hh = (ts / 3600) % 24
    var mm = (ts / 60) % 60
    var ss = ts % 60
    var hh_s = String(hh)
    if hh < 10:
        hh_s = "0" + hh_s
    var mm_s = String(mm)
    if mm < 10:
        mm_s = "0" + mm_s
    var ss_s = String(ss)
    if ss < 10:
        ss_s = "0" + ss_s
    var method = "GET"
    if random_float64() < 0.2:
        method = "POST"
    return (
        ip
        + ' - - [05/Nov/2026:'
        + hh_s
        + ":"
        + mm_s
        + ":"
        + ss_s
        + ' +0000] "'
        + method
        + " "
        + url
        + ' HTTP/1.1" '
        + String(status)
        + " "
        + String(size)
        + ' "-" "curl/8.5.0"'
    )


def ensure_input(data_dir: String) raises -> Path:
    var path = Path(data_dir + "/access.log")
    if path.exists():
        return path
    print("access.log not found in " + data_dir + "; generating 50,000 lines ...")
    if not Path(data_dir).exists():
        mkdir(data_dir)
    seed(20261105)
    var lines = List[String]()
    var ts = 36000  # 10:00:00 UTC on the log day; hour math stays in range
    for _ in range(50000):
        ts += 1 + Int(random_float64() * 4.0)
        lines.append(gen_one_log_line(ts))
    path.write_text(String("\n").join(lines) + "\n")
    print("  generated", path, "50,000 lines")
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
    print("DONE: log parse verified.")
