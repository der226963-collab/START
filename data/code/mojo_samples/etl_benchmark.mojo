# etl_benchmark.mojo
#
# ETL benchmark harness for the START project's Mojo ETL samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.)
# Requires Mojo 1.2.0.
#
# What it measures, on real files on disk (never in-memory toys):
#   1. Worker scaling: the log parser and the tick parser, single-threaded
#      vs chunked with 1, 2 and 4 workers, on the same files. NOTE: in this
#      build the chunked parse runs sequentially (see the NOTE above), so
#      the worker count does not change wall time -- the runs still verify
#      that chunked results equal the single-threaded reference at every
#      worker count, and the scaling section becomes meaningful again once
#      MAX `parallelize` is available.
#   2. Chunk-size sensitivity: the same chunked parse with 500, 2000 and
#      8000 lines per chunk, showing the trade-off between per-chunk
#      overhead and load balance.
#   3. Read vs parse split: how much of the wall time is file I/O
#      (`read_text`) versus actual parsing, so the numbers are honest
#      about where the time goes.
#   4. Dataset scaling: small (5k logs / 10k ticks) and medium (100k logs
#      / 250k ticks) inputs.
#
# Method: one warmup run (to fill the compile cache and page cache),
# then three timed repetitions; the reported time is the median. Every
# timed run is checked for correctness first: the chunked aggregate
# must equal the single-threaded reference aggregate, or the run is
# reported as FAILED and the program exits non-zero. A benchmark that
# does not verify its answers is just a stopwatch.
#
# Results are printed as tables and written to two files in the data
# directory: benchmark_report.txt (human-readable) and
# benchmark_report.csv (one row per measurement, for later analysis).
#
# Usage:
#   mojo etl_benchmark.mojo [data-dir]
# Defaults: /tmp/etl_data. Missing input files are generated in place
# (small + medium scales) with the same deterministic generator family
# as etl_gen_data.mojo.

from std.pathlib import Path
from std.testing import assert_equal, assert_true, assert_almost_equal
from std.collections import Dict
from std.random import seed, random_float64
from std.sys import argv
from std.time import perf_counter
from std.os import mkdir


# ---------------------------------------------------------------------------
# Shared helpers.
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


def fmt_int(n: Int) -> String:
    """Thousands-separated integer, e.g. 250000 -> '250,000'."""
    var s = String(n)
    var out = String("")
    var count = 0
    var i = s.byte_length() - 1
    while i >= 0:
        out = String(s[byte = i : i + 1]) + out
        count += 1
        if count == 3 and i > 0:
            out = "," + out
            count = 0
        i -= 1
    return out


def median3(a: Float64, b: Float64, c: Float64) -> Float64:
    if a <= b and b <= c:
        return b
    if c <= b and b <= a:
        return b
    if b <= a and a <= c:
        return a
    if c <= a and a <= b:
        return a
    return c


def to_owned_lines(text: String) raises -> List[String]:
    var slices = text.split("\n")
    var lines = List[String]()
    for i in range(len(slices)):
        lines.append(String(slices[i]))
    return lines^


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


def parse_int_slice(s: StringSlice) -> Tuple[Int, Bool]:
    var r = read_int_at(s, 0)
    return (r[0], r[2])


def parse_float_slice(s: StringSlice) -> Tuple[Float64, Bool]:
    var b = s.as_bytes()
    var i = 0
    while i < len(b) and (b[i] == 32 or b[i] == 9):
        i += 1
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
        while i < len(b) and b[i] >= 48 and b[i] <= 57:
            v += Float64(Int(b[i]) - 48) * frac
            frac *= 0.1
            any_digit = True
            i += 1
    if neg:
        v = -v
    return (v, any_digit)


# ---------------------------------------------------------------------------
# Log parser (compact copy of the etl_log_parse.mojo core: same format,
# same aggregates, same map-reduce shape; the report printing is omitted
# here because the harness only needs timings and equality checks).
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
    var out = LogFields()
    if line.byte_length() < 20:
        return out
    var open_br = line.find("[")
    if open_br < 0:
        return out
    var ts = line[byte = open_br + 1 : open_br + 21]
    if ts.byte_length() < 20:
        return out
    var tb = ts.as_bytes()
    if tb[11] != 58 or tb[14] != 58 or tb[17] != 58:
        return out
    var hour = (Int(tb[12]) - 48) * 10 + (Int(tb[13]) - 48)
    if hour < 0 or hour > 23:
        return out
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
    var tail = line[byte = q1 + 1 + q2rel + 1 : line.byte_length()]
    var status_read = read_int_at(tail, 0)
    if not status_read[2]:
        return out
    var status = status_read[0]
    var size_read = read_int_at(tail, status_read[1])
    if not size_read[2]:
        # A lone '-' means "no size recorded".
        var b = tail.as_bytes()
        var j = status_read[1]
        while j < len(b) and b[j] == 32:
            j += 1
        if j < len(b) and b[j] == 45:
            size_read = (0, j + 1, True)
        else:
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


struct LogAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var bytes_total: Int
    var errors: Int
    var status_counts: Dict[Int, Int]
    var url_counts: Dict[String, Int]
    var method_counts: Dict[String, Int]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.bytes_total = 0
        self.errors = 0
        self.status_counts = Dict[Int, Int]()
        self.url_counts = Dict[String, Int]()
        self.method_counts = Dict[String, Int]()

    def add_line(mut self, f: LogFields):
        self.total += 1
        if not f.ok:
            self.malformed += 1
            return
        self.parsed += 1
        self.bytes_total += f.size
        if f.status >= 400:
            self.errors += 1
        self.status_counts[f.status] = self.status_counts.get(f.status, 0) + 1
        self.url_counts[f.url] = self.url_counts.get(f.url, 0) + 1
        self.method_counts[f.method] = self.method_counts.get(f.method, 0) + 1

    def merge(mut self, ref other: LogAgg):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        self.bytes_total += other.bytes_total
        self.errors += other.errors
        for code in other.status_counts.keys():
            self.status_counts[code] = self.status_counts.get(code, 0) + other.status_counts.get(code, 0)
        for url in other.url_counts.keys():
            self.url_counts[url] = self.url_counts.get(url, 0) + other.url_counts.get(url, 0)
        for m in other.method_counts.keys():
            self.method_counts[m] = self.method_counts.get(m, 0) + other.method_counts.get(m, 0)


def log_agg_equal(ref a: LogAgg, ref b: LogAgg) -> Bool:
    if a.total != b.total or a.parsed != b.parsed or a.malformed != b.malformed:
        return False
    if a.bytes_total != b.bytes_total or a.errors != b.errors:
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
    return True


def parse_log_range(lines: List[String], start: Int, end: Int) -> LogAgg:
    var agg = LogAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        agg.add_line(parse_log_line(lines[i]))
    return agg^


def parse_log_reference(lines: List[String]) -> LogAgg:
    return parse_log_range(lines, 0, len(lines))


def parse_log_parallel(lines: List[String], workers: Int, chunk_size: Int) -> LogAgg:
    var n = len(lines)
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
        var agg = parse_log_range(lines, start, end)
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
# Tick parser (compact copy of the etl_tick_parse.mojo core).
# ---------------------------------------------------------------------------


struct Bar(Copyable, ImplicitlyCopyable, Movable):
    var open: Float64
    var high: Float64
    var low: Float64
    var close: Float64
    var volume: Int
    var trades: Int
    var vwap_num: Float64
    var first_ts: Int
    var last_ts: Int

    def __init__(out self):
        self.open = 0.0
        self.high = 0.0
        self.low = 0.0
        self.close = 0.0
        self.volume = 0
        self.trades = 0
        self.vwap_num = 0.0
        self.first_ts = 0
        self.last_ts = 0

    def __init__(out self, *, other: Self):
        self.open = other.open
        self.high = other.high
        self.low = other.low
        self.close = other.close
        self.volume = other.volume
        self.trades = other.trades
        self.vwap_num = other.vwap_num
        self.first_ts = other.first_ts
        self.last_ts = other.last_ts

    def update(mut self, price: Float64, size: Int, ts: Int):
        if self.trades == 0:
            self.open = price
            self.high = price
            self.low = price
            self.close = price
            self.first_ts = ts
            self.last_ts = ts
        else:
            if price > self.high:
                self.high = price
            if price < self.low:
                self.low = price
            if ts < self.first_ts:
                self.first_ts = ts
                self.open = price
            if ts >= self.last_ts:
                self.last_ts = ts
                self.close = price
        self.volume += size
        self.trades += 1
        self.vwap_num += price * Float64(size)

    def merge_from(mut self, ref other: Bar):
        if other.trades == 0:
            return
        if self.trades == 0:
            self.open = other.open
            self.high = other.high
            self.low = other.low
            self.close = other.close
            self.volume = other.volume
            self.trades = other.trades
            self.vwap_num = other.vwap_num
            self.first_ts = other.first_ts
            self.last_ts = other.last_ts
            return
        if other.high > self.high:
            self.high = other.high
        if other.low < self.low:
            self.low = other.low
        if other.first_ts < self.first_ts:
            self.first_ts = other.first_ts
            self.open = other.open
        if other.last_ts >= self.last_ts:
            self.last_ts = other.last_ts
            self.close = other.close
        self.volume += other.volume
        self.trades += other.trades
        self.vwap_num += other.vwap_num


struct TickFields(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var ts: Int
    var symbol: String
    var price: Float64
    var size: Int
    var exchange: String

    def __init__(out self):
        self.ok = False
        self.ts = 0
        self.symbol = ""
        self.price = 0.0
        self.size = 0
        self.exchange = ""

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.ts = other.ts
        self.symbol = other.symbol
        self.price = other.price
        self.size = other.size
        self.exchange = other.exchange


def parse_tick_line(line: StringSlice) -> TickFields:
    var out = TickFields()
    if line.byte_length() < 8:
        return out
    var parts = line.split(",")
    if len(parts) != 5:
        return out
    var ts_read = parse_int_slice(parts[0])
    if not ts_read[1] or ts_read[0] <= 0:
        return out
    var symbol = String(parts[1])
    if symbol.byte_length() == 0:
        return out
    var price_read = parse_float_slice(parts[2])
    if not price_read[1] or price_read[0] <= 0.0:
        return out
    var size_read = parse_int_slice(parts[3])
    if not size_read[1] or size_read[0] <= 0:
        return out
    var exchange = String(parts[4])
    if exchange.byte_length() == 0:
        return out
    out.ok = True
    out.ts = ts_read[0]
    out.symbol = symbol
    out.price = price_read[0]
    out.size = size_read[0]
    out.exchange = exchange
    return out


struct TickAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var total_volume: Int
    var symbols: Dict[String, Bar]
    var bars: Dict[String, Bar]
    var exchanges: Dict[String, Int]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.total_volume = 0
        self.symbols = Dict[String, Bar]()
        self.bars = Dict[String, Bar]()
        self.exchanges = Dict[String, Int]()

    def add_tick(mut self, f: TickFields):
        self.total += 1
        if not f.ok:
            self.malformed += 1
            return
        self.parsed += 1
        self.total_volume += f.size
        var sym_bar = self.symbols.get(f.symbol, Bar())
        sym_bar.update(f.price, f.size, f.ts)
        self.symbols[f.symbol] = sym_bar
        var key = f.symbol + "|" + String(f.ts / 300)
        var bar = self.bars.get(key, Bar())
        bar.update(f.price, f.size, f.ts)
        self.bars[key] = bar
        self.exchanges[f.exchange] = self.exchanges.get(f.exchange, 0) + 1

    def merge(mut self, ref other: TickAgg):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        self.total_volume += other.total_volume
        for sym in other.symbols.keys():
            var merged = self.symbols.get(sym, Bar())
            var other_bar = other.symbols.get(sym, Bar())
            merged.merge_from(other_bar)
            self.symbols[sym] = merged
        for key in other.bars.keys():
            var merged_bar = self.bars.get(key, Bar())
            var other_bar2 = other.bars.get(key, Bar())
            merged_bar.merge_from(other_bar2)
            self.bars[key] = merged_bar
        for ex in other.exchanges.keys():
            self.exchanges[ex] = self.exchanges.get(ex, 0) + other.exchanges.get(ex, 0)


def bar_equal(a: Bar, b: Bar) -> Bool:
    if a.volume != b.volume or a.trades != b.trades:
        return False
    if a.first_ts != b.first_ts or a.last_ts != b.last_ts:
        return False
    if not approx_eq(a.open, b.open, 1e-9):
        return False
    if not approx_eq(a.high, b.high, 1e-9):
        return False
    if not approx_eq(a.low, b.low, 1e-9):
        return False
    if not approx_eq(a.close, b.close, 1e-9):
        return False
    if not approx_eq(a.vwap_num, b.vwap_num, 1e-9):
        return False
    return True


def tick_agg_equal(ref a: TickAgg, ref b: TickAgg) -> Bool:
    if a.total != b.total or a.parsed != b.parsed or a.malformed != b.malformed:
        return False
    if a.total_volume != b.total_volume:
        return False
    if len(a.symbols) != len(b.symbols):
        return False
    for sym in a.symbols.keys():
        if sym not in b.symbols:
            return False
        if not bar_equal(a.symbols.get(sym, Bar()), b.symbols.get(sym, Bar())):
            return False
    if len(a.bars) != len(b.bars):
        return False
    for key in a.bars.keys():
        if key not in b.bars:
            return False
        if not bar_equal(a.bars.get(key, Bar()), b.bars.get(key, Bar())):
            return False
    if len(a.exchanges) != len(b.exchanges):
        return False
    for ex in a.exchanges.keys():
        if ex not in b.exchanges or b.exchanges.get(ex, 0) != a.exchanges.get(ex, 0):
            return False
    return True


def parse_tick_range(lines: List[String], start: Int, end: Int) -> TickAgg:
    var agg = TickAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        if lines[i].startswith("timestamp,"):
            continue
        agg.add_tick(parse_tick_line(lines[i]))
    return agg^


def parse_tick_reference(lines: List[String]) -> TickAgg:
    return parse_tick_range(lines, 0, len(lines))


def parse_tick_parallel(lines: List[String], workers: Int, chunk_size: Int) -> TickAgg:
    var n = len(lines)
    var n_chunks = (n + chunk_size - 1) / chunk_size
    if n_chunks < 1:
        n_chunks = 1
    var chunk_aggs = List[TickAgg]()
    for _ in range(n_chunks):
        chunk_aggs.append(TickAgg())

    def work(i: Int) {mut chunk_aggs, imm lines, imm n, imm chunk_size}:
        var start = i * chunk_size
        var end = start + chunk_size
        if end > n:
            end = n
        var agg = parse_tick_range(lines, start, end)
        chunk_aggs[i] = agg^

    # NOTE (Mojo 1.2.0): the plain `mojo` package no longer ships
    # `parallelize` -- it moved to the MAX package, which is not a
    # stdlib dependency here. Chunks therefore run sequentially in
    # this build; the chunk/merge structure is unchanged, so restoring
    # multi-core dispatch is a one-line change (call parallelize
    # from MAX instead of this loop) once MAX is available.
    for i in range(n_chunks):
        work(i)
    var result = TickAgg()
    for i in range(n_chunks):
        result.merge(chunk_aggs[i])
    return result^

# ---------------------------------------------------------------------------
# Benchmark harness.
# ---------------------------------------------------------------------------


struct Measurement(Copyable, ImplicitlyCopyable, Movable):
    var dataset: String
    var parser: String
    var mode: String
    var workers: Int
    var chunk_size: Int
    var lines: Int
    var bytes: Int
    var seconds: Float64
    var lines_per_s: Float64
    var mb_per_s: Float64
    var speedup: Float64
    var efficiency: Float64
    var correct: Bool

    def __init__(out self):
        self.dataset = ""
        self.parser = ""
        self.mode = ""
        self.workers = 0
        self.chunk_size = 0
        self.lines = 0
        self.bytes = 0
        self.seconds = 0.0
        self.lines_per_s = 0.0
        self.mb_per_s = 0.0
        self.speedup = 0.0
        self.efficiency = 0.0
        self.correct = False

    def __init__(out self, *, other: Self):
        self.dataset = other.dataset
        self.parser = other.parser
        self.mode = other.mode
        self.workers = other.workers
        self.chunk_size = other.chunk_size
        self.lines = other.lines
        self.bytes = other.bytes
        self.seconds = other.seconds
        self.lines_per_s = other.lines_per_s
        self.mb_per_s = other.mb_per_s
        self.speedup = other.speedup
        self.efficiency = other.efficiency
        self.correct = other.correct


struct Harness(Movable):
    var results: List[Measurement]
    var failures: Int

    def __init__(out self):
        self.results = List[Measurement]()
        self.failures = 0

    def record(mut self, m: Measurement):
        self.results.append(m)
        if not m.correct:
            self.failures += 1

    def write_reports(self, data_dir: String) raises:
        var txt_lines = List[String]()
        txt_lines.append("ETL BENCHMARK REPORT")
        txt_lines.append("===================")
        txt_lines.append("Generated by etl_benchmark.mojo (Mojo 1.2.0, sequential chunks (parallelize moved to MAX)).")
        txt_lines.append("Each time is the median of 3 runs after 1 warmup run.")
        txt_lines.append("Speedup is relative to the single-threaded reference on the same file.")
        txt_lines.append("Efficiency is speedup divided by worker count.")
        txt_lines.append("")
        txt_lines.append(
            "dataset | parser | mode | workers | chunk | lines | seconds | lines/s | MB/s | speedup | eff | correct"
        )
        var csv_lines = List[String]()
        csv_lines.append("dataset,parser,mode,workers,chunk_size,lines,bytes,seconds,lines_per_s,mb_per_s,speedup,efficiency,correct")
        for m in self.results:
            var correct_s = "yes"
            if not m.correct:
                correct_s = "NO"
            txt_lines.append(
                m.dataset
                + " | "
                + m.parser
                + " | "
                + m.mode
                + " | "
                + String(m.workers)
                + " | "
                + String(m.chunk_size)
                + " | "
                + fmt_int(m.lines)
                + " | "
                + fmt2(m.seconds)
                + " | "
                + fmt_int(Int(m.lines_per_s))
                + " | "
                + fmt2(m.mb_per_s)
                + " | "
                + fmt2(m.speedup)
                + " | "
                + fmt2(m.efficiency)
                + " | "
                + correct_s
            )
            csv_lines.append(
                m.dataset
                + ","
                + m.parser
                + ","
                + m.mode
                + ","
                + String(m.workers)
                + ","
                + String(m.chunk_size)
                + ","
                + String(m.lines)
                + ","
                + String(m.bytes)
                + ","
                + fmt2(m.seconds)
                + ","
                + String(Int(m.lines_per_s))
                + ","
                + fmt2(m.mb_per_s)
                + ","
                + fmt2(m.speedup)
                + ","
                + fmt2(m.efficiency)
                + ","
                + correct_s
            )
        txt_lines.append("")
        txt_lines.append("failures (incorrect parallel results): " + String(self.failures))
        Path(data_dir + "/benchmark_report.txt").write_text(String("\n").join(txt_lines) + "\n")
        Path(data_dir + "/benchmark_report.csv").write_text(String("\n").join(csv_lines) + "\n")


def time_read(path: Path) raises -> Tuple[Float64, Int]:
    """Median read_text time over 3 runs (plus one warmup), and the size."""
    _ = path.read_text()
    var t1 = perf_counter()
    var text = path.read_text()
    var e1 = perf_counter() - t1
    var size = text.byte_length()
    var t2 = perf_counter()
    _ = path.read_text()
    var e2 = perf_counter() - t2
    var t3 = perf_counter()
    _ = path.read_text()
    var e3 = perf_counter() - t3
    return (median3(e1, e2, e3), size)


def bench_logs(mut h: Harness, dataset: String, lines: List[String], n_bytes: Int, ref_seconds: Float64):
    """Worker scaling for the log parser on one dataset. `ref_seconds`
    is the already-measured single-threaded time, used for speedups."""
    print("  [logs/" + dataset + "] workers=1..4, chunk=2000")
    var ref_agg = parse_log_reference(lines)
    for workers in [1, 2, 4]:
        var warm = parse_log_parallel(lines, workers, 2000)
        _ = log_agg_equal(ref_agg, warm)
        var t1 = perf_counter()
        var a1 = parse_log_parallel(lines, workers, 2000)
        var e1 = perf_counter() - t1
        var t2 = perf_counter()
        var a2 = parse_log_parallel(lines, workers, 2000)
        var e2 = perf_counter() - t2
        var t3 = perf_counter()
        var a3 = parse_log_parallel(lines, workers, 2000)
        var e3 = perf_counter() - t3
        var med = median3(e1, e2, e3)
        var ok = log_agg_equal(ref_agg, a1) and log_agg_equal(ref_agg, a2) and log_agg_equal(ref_agg, a3)
        var m = Measurement()
        m.dataset = dataset
        m.parser = "logs"
        m.mode = "parallel"
        m.workers = workers
        m.chunk_size = 2000
        m.lines = ref_agg.total
        m.bytes = n_bytes
        m.seconds = med
        m.lines_per_s = Float64(m.lines) / med
        m.mb_per_s = Float64(n_bytes) / med / 1000000.0
        if med > 0.0 and ref_seconds > 0.0:
            m.speedup = ref_seconds / med
        if workers > 0:
            m.efficiency = m.speedup / Float64(workers)
        m.correct = ok
        h.record(m)
        print(
            "    workers=",
            workers,
            " median=",
            fmt2(med),
            "s lines/s=",
            fmt_int(Int(m.lines_per_s)),
            " speedup=",
            fmt2(m.speedup),
            " correct=",
            ok,
        )


def bench_ticks(mut h: Harness, dataset: String, lines: List[String], n_bytes: Int, ref_seconds: Float64):
    print("  [ticks/" + dataset + "] workers=1..4, chunk=2000")
    var ref_agg = parse_tick_reference(lines)
    for workers in [1, 2, 4]:
        var warm = parse_tick_parallel(lines, workers, 2000)
        _ = tick_agg_equal(ref_agg, warm)
        var t1 = perf_counter()
        var a1 = parse_tick_parallel(lines, workers, 2000)
        var e1 = perf_counter() - t1
        var t2 = perf_counter()
        var a2 = parse_tick_parallel(lines, workers, 2000)
        var e2 = perf_counter() - t2
        var t3 = perf_counter()
        var a3 = parse_tick_parallel(lines, workers, 2000)
        var e3 = perf_counter() - t3
        var med = median3(e1, e2, e3)
        var ok = tick_agg_equal(ref_agg, a1) and tick_agg_equal(ref_agg, a2) and tick_agg_equal(ref_agg, a3)
        var m = Measurement()
        m.dataset = dataset
        m.parser = "ticks"
        m.mode = "parallel"
        m.workers = workers
        m.chunk_size = 2000
        m.lines = ref_agg.total
        m.bytes = n_bytes
        m.seconds = med
        m.lines_per_s = Float64(m.lines) / med
        m.mb_per_s = Float64(n_bytes) / med / 1000000.0
        if med > 0.0 and ref_seconds > 0.0:
            m.speedup = ref_seconds / med
        if workers > 0:
            m.efficiency = m.speedup / Float64(workers)
        m.correct = ok
        h.record(m)
        print(
            "    workers=",
            workers,
            " median=",
            fmt2(med),
            "s lines/s=",
            fmt_int(Int(m.lines_per_s)),
            " speedup=",
            fmt2(m.speedup),
            " correct=",
            ok,
        )


def bench_reference(mut h: Harness, dataset: String, parser: String, lines: List[String], n_bytes: Int) -> Float64:
    """Time the single-threaded reference (median of 3 after warmup) and
    record it as the baseline measurement."""
    print("  [" + parser + "/" + dataset + "] reference (single-threaded)")
    var e1: Float64
    var e2: Float64
    var e3: Float64
    var total: Int
    if parser == "logs":
        var warm = parse_log_reference(lines)
        total = warm.total
        var t1 = perf_counter()
        _ = parse_log_reference(lines)
        e1 = perf_counter() - t1
        var t2 = perf_counter()
        _ = parse_log_reference(lines)
        e2 = perf_counter() - t2
        var t3 = perf_counter()
        _ = parse_log_reference(lines)
        e3 = perf_counter() - t3
    else:
        var warm = parse_tick_reference(lines)
        total = warm.total
        var t1 = perf_counter()
        _ = parse_tick_reference(lines)
        e1 = perf_counter() - t1
        var t2 = perf_counter()
        _ = parse_tick_reference(lines)
        e2 = perf_counter() - t2
        var t3 = perf_counter()
        _ = parse_tick_reference(lines)
        e3 = perf_counter() - t3
    var med = median3(e1, e2, e3)
    var m = Measurement()
    m.dataset = dataset
    m.parser = parser
    m.mode = "reference"
    m.workers = 1
    m.chunk_size = 0
    m.lines = total
    m.bytes = n_bytes
    m.seconds = med
    m.lines_per_s = Float64(total) / med
    m.mb_per_s = Float64(n_bytes) / med / 1000000.0
    m.speedup = 1.0
    m.efficiency = 1.0
    m.correct = True
    h.record(m)
    print("    median=", fmt2(med), "s lines/s=", fmt_int(Int(m.lines_per_s)))
    return med


def bench_chunk_sizes(mut h: Harness, dataset: String, parser: String, lines: List[String], n_bytes: Int, ref_seconds: Float64):
    """Chunk-size sensitivity at 4 workers: 500 / 2000 / 8000 lines."""
    print("  [" + parser + "/" + dataset + "] chunk-size study, 4 workers")
    for chunk in [500, 2000, 8000]:
        var med: Float64
        var ok: Bool
        var total: Int
        if parser == "logs":
            var ref_agg = parse_log_reference(lines)
            total = ref_agg.total
            var w = parse_log_parallel(lines, 4, chunk)
            _ = log_agg_equal(ref_agg, w)
            var t1 = perf_counter()
            var a1 = parse_log_parallel(lines, 4, chunk)
            var e1 = perf_counter() - t1
            var t2 = perf_counter()
            var a2 = parse_log_parallel(lines, 4, chunk)
            var e2 = perf_counter() - t2
            var t3 = perf_counter()
            var a3 = parse_log_parallel(lines, 4, chunk)
            var e3 = perf_counter() - t3
            med = median3(e1, e2, e3)
            ok = log_agg_equal(ref_agg, a1) and log_agg_equal(ref_agg, a2) and log_agg_equal(ref_agg, a3)
        else:
            var ref_agg = parse_tick_reference(lines)
            total = ref_agg.total
            var w = parse_tick_parallel(lines, 4, chunk)
            _ = tick_agg_equal(ref_agg, w)
            var t1 = perf_counter()
            var a1 = parse_tick_parallel(lines, 4, chunk)
            var e1 = perf_counter() - t1
            var t2 = perf_counter()
            var a2 = parse_tick_parallel(lines, 4, chunk)
            var e2 = perf_counter() - t2
            var t3 = perf_counter()
            var a3 = parse_tick_parallel(lines, 4, chunk)
            var e3 = perf_counter() - t3
            med = median3(e1, e2, e3)
            ok = tick_agg_equal(ref_agg, a1) and tick_agg_equal(ref_agg, a2) and tick_agg_equal(ref_agg, a3)
        var m = Measurement()
        m.dataset = dataset
        m.parser = parser
        m.mode = "chunk-study"
        m.workers = 4
        m.chunk_size = chunk
        m.lines = total
        m.bytes = n_bytes
        m.seconds = med
        m.lines_per_s = Float64(total) / med
        m.mb_per_s = Float64(n_bytes) / med / 1000000.0
        if med > 0.0 and ref_seconds > 0.0:
            m.speedup = ref_seconds / med
        m.efficiency = m.speedup / 4.0
        m.correct = ok
        h.record(m)
        print(
            "    chunk=",
            chunk,
            " median=",
            fmt2(med),
            "s lines/s=",
            fmt_int(Int(m.lines_per_s)),
            " speedup=",
            fmt2(m.speedup),
            " correct=",
            ok,
        )

# ---------------------------------------------------------------------------
# Unit tests for the harness itself (timing helpers and formatters).
# ---------------------------------------------------------------------------


def test_median3() raises:
    assert_almost_equal(median3(1.0, 2.0, 3.0), 2.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(median3(3.0, 1.0, 2.0), 2.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(median3(2.0, 2.0, 2.0), 2.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(median3(5.0, 1.0, 4.0), 4.0, atol=1e-9, rtol=1e-9)
    print("  test_median3 OK")


def test_fmt() raises:
    assert_equal(fmt2(0.0), "0.00")
    assert_equal(fmt2(123.456), "123.46")
    assert_equal(fmt2(-2.5), "-2.50")
    assert_equal(fmt_int(0), "0")
    assert_equal(fmt_int(999), "999")
    assert_equal(fmt_int(1000), "1,000")
    assert_equal(fmt_int(250000), "250,000")
    assert_equal(fmt_int(1234567), "1,234,567")
    print("  test_fmt OK")


def test_parsers_small() raises:
    var log_text = String(
        '1.1.1.1 - - [05/Nov/2026:09:00:01 +0000] "GET /a HTTP/1.1" 200 100 "-" "ua"\n'
        + '1.1.1.2 - - [05/Nov/2026:09:00:02 +0000] "GET /b HTTP/1.1" 404 50 "-" "ua"\n'
    )
    var log_lines = to_owned_lines(log_text)
    var ref_log = parse_log_reference(log_lines)
    assert_equal(ref_log.parsed, 2)
    assert_equal(ref_log.errors, 1)
    assert_equal(ref_log.bytes_total, 150)
    var par_log = parse_log_parallel(log_lines, 2, 1)
    assert_true(log_agg_equal(ref_log, par_log))
    var tick_text = String(
        "timestamp,symbol,price,size,exchange\n"
        + "1000,ACME,100.00,10,NYSE\n"
        + "1010,ACME,110.00,20,NYSE\n"
    )
    var tick_lines = to_owned_lines(tick_text)
    var ref_tick = parse_tick_reference(tick_lines)
    assert_equal(ref_tick.parsed, 2)
    assert_equal(ref_tick.total_volume, 30)
    var par_tick = parse_tick_parallel(tick_lines, 2, 1)
    assert_true(tick_agg_equal(ref_tick, par_tick))
    print("  test_parsers_small OK")


def run_tests() raises:
    print("Running unit tests:")
    test_median3()
    test_fmt()
    test_parsers_small()
    print("All benchmark unit tests passed.")


# ---------------------------------------------------------------------------
# Embedded fallback generators (same format / seed family as etl_gen_data).
# Writes small + medium inputs when the data directory is missing them.
# ---------------------------------------------------------------------------


def gen_log_lines(n: Int, start_ts: Int) -> List[String]:
    var urls = List[String]()
    urls.append("/index.html")
    urls.append("/products")
    urls.append("/cart")
    urls.append("/checkout")
    urls.append("/api/v1/users")
    urls.append("/static/app.js")
    urls.append("/about")
    urls.append("/login")
    var lines = List[String]()
    var ts = start_ts
    for _ in range(n):
        ts += 1 + Int(random_float64() * 4.0)
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
        var size = 120 + Int(random_float64() * 8000.0)
        if status != 200:
            size = 180 + Int(random_float64() * 2400.0)
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
        var ip = String(1 + Int(random_float64() * 223.0)) + "." + String(Int(random_float64() * 256.0)) + "." + String(Int(random_float64() * 256.0)) + "." + String(1 + Int(random_float64() * 254.0))
        lines.append(
            ip
            + ' - - [05/Nov/2026:'
            + hh_s
            + ":"
            + mm_s
            + ":"
            + ss_s
            + ' +0000] "GET '
            + url
            + ' HTTP/1.1" '
            + String(status)
            + " "
            + String(size)
            + ' "-" "curl/8.5.0"'
        )
    return lines^


def gen_tick_lines(n: Int, start_ts: Int) -> List[String]:
    var symbols = List[String]()
    symbols.append("ACME")
    symbols.append("BOLT")
    symbols.append("CRUX")
    symbols.append("DUNE")
    symbols.append("ECHO")
    symbols.append("FLUX")
    symbols.append("GALE")
    symbols.append("HALO")
    var bases = List[Float64]()
    bases.append(142.35)
    bases.append(87.10)
    bases.append(231.80)
    bases.append(45.60)
    bases.append(312.25)
    bases.append(19.95)
    bases.append(178.40)
    bases.append(64.75)
    var prices = List[Float64]()
    for b in bases:
        prices.append(b)
    var lines = List[String]()
    lines.append("timestamp,symbol,price,size,exchange")
    var ts = start_ts
    for _ in range(n):
        ts += Int(random_float64() * 3.0)
        var si = Int(random_float64() * Float64(len(symbols)))
        var price = prices[si] + (random_float64() - 0.5) * 0.02 * prices[si]
        if price < 1.0:
            price = 1.0 + random_float64() * 2.0
        prices[si] = price
        var size = 1 + Int(random_float64() * 500.0)
        var ex = "NYSE"
        if random_float64() < 0.5:
            ex = "NASDAQ"
        lines.append(
            String(ts) + "," + symbols[si] + "," + fmt2(price) + "," + String(size) + "," + ex
        )
    return lines^


def ensure_inputs(data_dir: String) raises:
    if not Path(data_dir).exists():
        mkdir(data_dir)
    var log_path = Path(data_dir + "/access.log")
    if not log_path.exists():
        print("Generating medium access.log (100,000 lines) ...")
        seed(20261105)
        log_path.write_text(String("\n").join(gen_log_lines(100000, 36000)) + "\n")
    var tick_path = Path(data_dir + "/ticks.csv")
    if not tick_path.exists():
        print("Generating medium ticks.csv (250,000 trades) ...")
        seed(20261106)
        tick_path.write_text(String("\n").join(gen_tick_lines(250000, 1793836800)) + "\n")


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def main() raises:
    run_tests()
    var args = argv()
    var data_dir = "/tmp/etl_data"
    if len(args) > 1:
        data_dir = String(args[1])
    ensure_inputs(data_dir)
    var h = Harness()

    # --- Read-time split: how much of the job is I/O? ---
    print("Measuring file read times (median of 3):")
    var log_path = Path(data_dir + "/access.log")
    var tick_path = Path(data_dir + "/ticks.csv")
    var log_read = time_read(log_path)
    var tick_read = time_read(tick_path)
    print("  access.log:", fmt_int(log_read[1]), "bytes in", fmt2(log_read[0]), "s")
    print("  ticks.csv: ", fmt_int(tick_read[1]), "bytes in", fmt2(tick_read[0]), "s")

    # --- Load once, benchmark many times (parse time only) ---
    print("Loading files into memory ...")
    var log_text = log_path.read_text()
    var tick_text = tick_path.read_text()
    var log_lines = to_owned_lines(log_text)
    var tick_lines = to_owned_lines(tick_text)
    print("  logs:", len(log_lines), "lines;", " ticks:", len(tick_lines), "lines")

    # --- Worker scaling ---
    print("Worker scaling study (chunk=2000):")
    var log_ref_s = bench_reference(h, "medium", "logs", log_lines, log_read[1])
    bench_logs(h, "medium", log_lines, log_read[1], log_ref_s)
    var tick_ref_s = bench_reference(h, "medium", "ticks", tick_lines, tick_read[1])
    bench_ticks(h, "medium", tick_lines, tick_read[1], tick_ref_s)

    # --- Chunk-size sensitivity at 4 workers ---
    print("Chunk-size study:")
    bench_chunk_sizes(h, "medium", "logs", log_lines, log_read[1], log_ref_s)
    bench_chunk_sizes(h, "medium", "ticks", tick_lines, tick_read[1], tick_ref_s)

    # --- Small dataset: where does parallelism stop paying? ---
    print("Small-dataset study (first 5,000 log lines / 10,000 tick lines):")
    var small_logs = List[String]()
    for i in range(5000):
        small_logs.append(log_lines[i])
    var small_ticks = List[String]()
    for i in range(10000):
        small_ticks.append(tick_lines[i])
    var small_log_ref = bench_reference(h, "small", "logs", small_logs, log_read[1] / 20)
    bench_logs(h, "small", small_logs, log_read[1] / 20, small_log_ref)
    var small_tick_ref = bench_reference(h, "small", "ticks", small_ticks, tick_read[1] / 25)
    bench_ticks(h, "small", small_ticks, tick_read[1] / 25, small_tick_ref)

    # --- Reports ---
    print("Writing reports to " + data_dir + "/benchmark_report.{txt,csv} ...")
    h.write_reports(data_dir)
    print("Measurements recorded:", len(h.results), " failures:", h.failures)
    assert_true(h.failures == 0, "all parallel results must equal their references")
    # The parallel path must not be pathologically slower than the
    # reference on the medium log file with 4 workers (tolerates noise
    # and small-file overhead; it is a smoke bound, not a perf claim).
    var found = False
    for m in h.results:
        if m.dataset == "medium" and m.parser == "logs" and m.mode == "parallel" and m.workers == 4:
            found = True
            assert_true(m.speedup > 0.9, "4-worker log parse must stay within 10% of reference speed")
    assert_true(found, "expected a medium/logs/parallel/4 measurement")
    print("DONE: benchmark complete, all results verified correct.")
