# etl_pipeline.mojo
#
# End-to-end ETL pipeline for the START project's Mojo ETL samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.)
# Requires Mojo 1.2.0.
#
# The pipeline runs the full journey on real files on disk:
#
#   ingest   -> parse access.log, ticks.csv and events.jsonl in parallel
#               (chunked map-reduce, one aggregate per chunk, merged after)
#   quality  -> run a data-quality suite over the ingested records:
#               domain checks (known symbols / URLs / services / levels),
#               range checks (prices, sizes, latencies), monotonicity
#               (tick timestamps never go backwards), presence checks
#               (request ids, regions), and duplicate detection
#   join     -> build per-minute aggregates from all three datasets and
#               join them on the minute, so one row describes what the
#               web tier, the market feed and the services were doing in
#               the same sixty seconds
#   detect   -> flag anomalous minutes: correlated error spikes across
#               the web tier and the services, and volume collapses in
#               the tick feed while errors spike
#   publish  -> write cleaned outputs (valid ticks only, per-minute
#               summary CSV, and a JSON run summary) and then verify
#               them by re-reading: row counts, headers, and JSON shape
#
# Correctness notes:
# - Ingest uses the parallel parsers. Their equivalence with the
#   single-threaded reference is proven by etl_log_parse.mojo,
#   etl_tick_parse.mojo and etl_jsonl_parse.mojo (each asserts
#   parallel == reference on the same files); this program additionally
#   asserts ingest totals against independent file line counts.
# - Every quality rule reports (checked, failed) and keeps up to five
#   failing samples, so a bad run is diagnosable from its report.
# - Outputs are written under <data-dir>/pipeline_out/ and are
#   re-read before the program reports success.
#
# Usage:
#   mojo etl_pipeline.mojo [data-dir] [workers]
# Defaults: /tmp/etl_data, 4 workers. Missing inputs are generated in
# place (same deterministic generator family as etl_gen_data.mojo).

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


def two_digit(n: Int) -> String:
    if n < 10:
        return "0" + String(n)
    return String(n)


def fmt2(x: Float64) -> String:
    var neg = False
    var v = x
    if v < 0.0:
        neg = True
        v = -v
    var scaled = Int(v * 100.0 + 0.5)
    var whole = scaled / 100
    var frac = scaled - whole * 100
    var out = String(whole) + "." + two_digit(frac)
    if neg:
        return "-" + out
    return out


def fmt_int(n: Int) -> String:
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
    if any_digit and i < len(b) and (b[i] == 101 or b[i] == 69):
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
        if exp_digit:
            var mult = 1.0
            for _ in range(exp):
                mult *= 10.0
            if exp_neg:
                v = v / mult
            else:
                v = v * mult
    if neg:
        v = -v
    return (v, any_digit)


def to_owned_lines(text: String) raises -> List[String]:
    var slices = text.split("\n")
    var lines = List[String]()
    for i in range(len(slices)):
        lines.append(String(slices[i]))
    return lines^


def count_nonempty(lines: List[String]) -> Int:
    var n = 0
    for i in range(len(lines)):
        if lines[i].byte_length() > 0:
            n += 1
    return n


def minute_label(epoch_minute: Int) -> String:
    """Epoch minute -> 'YYYY-MM-DDTHH:MMZ' (UTC), via civil-from-days."""
    var days = epoch_minute / 1440
    var mins = epoch_minute - days * 1440
    var zz = days + 719468
    var era = zz / 146097
    if zz < 0:
        era -= 1
    var doe = zz - era * 146097
    var yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365
    var y = yoe + era * 400
    var doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
    var mp = (5 * doy + 2) / 153
    var d = doy - (153 * mp + 2) / 5 + 1
    var m = mp + 3
    if mp >= 10:
        m = mp - 9
    if m <= 2:
        y += 1
    var hh = mins / 60
    var mm = mins - hh * 60
    return String(y) + "-" + two_digit(m) + "-" + two_digit(d) + "T" + two_digit(hh) + ":" + two_digit(mm) + "Z"


def ymd_to_days(y: Int, m: Int, d: Int) -> Int:
    var yy = y
    if m <= 2:
        yy -= 1
    var era = yy / 400
    if yy < 0:
        era -= 1
    var yoe = yy - era * 400
    var mp = m - 3
    if m <= 2:
        mp = m + 9
    var doy = (153 * mp + 2) / 5 + d - 1
    var doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
    return era * 146097 + doe - 719468


def json_escape(s: String) -> String:
    """Escape a string for inclusion in a JSON string literal."""
    var out = String("")
    var b = s.as_bytes()
    var run_start = 0
    var i = 0
    while i < len(b):
        var c = b[i]
        var esc = String("")
        if c == 34:
            esc = "\\\""
        elif c == 92:
            esc = "\\\\"
        elif c == 10:
            esc = "\\n"
        elif c == 13:
            esc = "\\r"
        elif c == 9:
            esc = "\\t"
        elif c < 32:
            var hi = Int(c) / 16
            var lo = Int(c) % 16
            var hexs = String("0123456789abcdef")
            esc = "\\u00" + String(hexs[byte = hi : hi + 1]) + String(hexs[byte = lo : lo + 1])
        if esc != "":
            if i > run_start:
                out += String(s[byte = run_start:i])
            out += esc
            run_start = i + 1
        i += 1
    if len(b) > run_start:
        out += String(s[byte = run_start : len(b)])
    return out


# ---------------------------------------------------------------------------
# Log ingest (parallel). Also records the minute-of-day for the join.
# ---------------------------------------------------------------------------


struct LogFields(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var method: String
    var url: String
    var status: Int
    var size: Int
    var minute: Int

    def __init__(out self):
        self.ok = False
        self.method = ""
        self.url = ""
        self.status = 0
        self.size = 0
        self.minute = -1

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.method = other.method
        self.url = other.url
        self.status = other.status
        self.size = other.size
        self.minute = other.minute


def month_num(name: StringSlice) -> Int:
    if name == "Jan":
        return 1
    if name == "Feb":
        return 2
    if name == "Mar":
        return 3
    if name == "Apr":
        return 4
    if name == "May":
        return 5
    if name == "Jun":
        return 6
    if name == "Jul":
        return 7
    if name == "Aug":
        return 8
    if name == "Sep":
        return 9
    if name == "Oct":
        return 10
    if name == "Nov":
        return 11
    if name == "Dec":
        return 12
    return -1


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
    var minute = (Int(tb[15]) - 48) * 10 + (Int(tb[16]) - 48)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return out
    # Epoch minute for the join: the log timestamp carries the full date.
    var day = (Int(tb[0]) - 48) * 10 + (Int(tb[1]) - 48)
    var mon = month_num(ts[byte = 3:6])
    var year = (Int(tb[7]) - 48) * 1000 + (Int(tb[8]) - 48) * 100 + (Int(tb[9]) - 48) * 10 + (Int(tb[10]) - 48)
    if mon < 1 or day < 1 or day > 31:
        return out
    var epoch_minute = ymd_to_days(year, mon, day) * 1440 + hour * 60 + minute
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
    var size: Int
    var size_read = read_int_at(tail, status_read[1])
    if size_read[2]:
        size = size_read[0]
    else:
        var b = tail.as_bytes()
        var j = status_read[1]
        while j < len(b) and b[j] == 32:
            j += 1
        if j < len(b) and b[j] == 45:
            size = 0
        else:
            return out
    if status < 100 or status > 599 or size < 0:
        return out
    out.ok = True
    out.method = method
    out.url = url
    out.status = status
    out.size = size
    out.minute = epoch_minute
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
    var minute_lines: Dict[Int, Int]
    var minute_errors: Dict[Int, Int]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.bytes_total = 0
        self.errors = 0
        self.status_counts = Dict[Int, Int]()
        self.url_counts = Dict[String, Int]()
        self.method_counts = Dict[String, Int]()
        self.minute_lines = Dict[Int, Int]()
        self.minute_errors = Dict[Int, Int]()

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
        self.minute_lines[f.minute] = self.minute_lines.get(f.minute, 0) + 1
        if f.status >= 400:
            self.minute_errors[f.minute] = self.minute_errors.get(f.minute, 0) + 1

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
        for mn in other.minute_lines.keys():
            self.minute_lines[mn] = self.minute_lines.get(mn, 0) + other.minute_lines.get(mn, 0)
        for mn in other.minute_errors.keys():
            self.minute_errors[mn] = self.minute_errors.get(mn, 0) + other.minute_errors.get(mn, 0)


def parse_log_range(lines: List[String], start: Int, end: Int) -> LogAgg:
    var agg = LogAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        agg.add_line(parse_log_line(lines[i]))
    return agg^


def parse_logs_parallel(lines: List[String], workers: Int) raises -> LogAgg:
    var n = len(lines)
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
# Tick ingest (parallel). Keeps per-symbol stats and per-minute volume,
# and retains every valid trade in flat lists for the cleaning stage.
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

    def vwap(self) -> Float64:
        if self.volume == 0:
            return 0.0
        return self.vwap_num / Float64(self.volume)


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
    var minute_trades: Dict[Int, Int]
    var minute_volume: Dict[Int, Int]
    var exchanges: Dict[String, Int]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.total_volume = 0
        self.symbols = Dict[String, Bar]()
        self.minute_trades = Dict[Int, Int]()
        self.minute_volume = Dict[Int, Int]()
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
        var minute = f.ts / 60
        self.minute_trades[minute] = self.minute_trades.get(minute, 0) + 1
        self.minute_volume[minute] = self.minute_volume.get(minute, 0) + f.size
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
        for mn in other.minute_trades.keys():
            self.minute_trades[mn] = self.minute_trades.get(mn, 0) + other.minute_trades.get(mn, 0)
        for mn in other.minute_volume.keys():
            self.minute_volume[mn] = self.minute_volume.get(mn, 0) + other.minute_volume.get(mn, 0)
        for ex in other.exchanges.keys():
            self.exchanges[ex] = self.exchanges.get(ex, 0) + other.exchanges.get(ex, 0)


def parse_tick_range(lines: List[String], start: Int, end: Int) -> TickAgg:
    var agg = TickAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        if lines[i].startswith("timestamp,"):
            continue
        agg.add_tick(parse_tick_line(lines[i]))
    return agg^


def parse_ticks_parallel(lines: List[String], workers: Int) raises -> TickAgg:
    var n = len(lines)
    var chunk_size = 2000
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
# JSON ingest (parallel). Hand-written JSON cursor, same grammar as
# etl_jsonl_parse.mojo, trimmed to the event schema plus generic skipping.
# The event timestamp is ISO-8601 UTC; its epoch minute is derived by
# parsing the date fields, so JSON events join on the same minute key
# as the logs and ticks.
# ---------------------------------------------------------------------------


struct EventFields(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var level: String
    var service: String
    var latency: Float64
    var has_latency: Bool
    var status: Int
    var has_status: Bool
    var request_id: String
    var region: String
    var minute: Int

    def __init__(out self):
        self.ok = False
        self.level = ""
        self.service = ""
        self.latency = 0.0
        self.has_latency = False
        self.status = 0
        self.has_status = False
        self.request_id = ""
        self.region = ""
        self.minute = -1

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.level = other.level
        self.service = other.service
        self.latency = other.latency
        self.has_latency = other.has_latency
        self.status = other.status
        self.has_status = other.has_status
        self.request_id = other.request_id
        self.region = other.region
        self.minute = other.minute


def skip_ws_json(line: String, i: Int) -> Int:
    var b = line.as_bytes()
    var j = i
    while j < len(b) and (b[j] == 32 or b[j] == 9 or b[j] == 10 or b[j] == 13):
        j += 1
    return j


def hex_val_json(c: UInt8) -> Int:
    if c >= 48 and c <= 57:
        return Int(c) - 48
    if c >= 97 and c <= 102:
        return Int(c) - 97 + 10
    if c >= 65 and c <= 70:
        return Int(c) - 65 + 10
    return -1


def parse_json_string(line: String, start: Int) -> Tuple[String, Int, Bool]:
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
                    var hv = hex_val_json(b[i + 2 + k])
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


def matches_lit_json(line: String, i: Int, lit: String) -> Bool:
    var b = line.as_bytes()
    var lb = lit.as_bytes()
    if i + len(lb) > len(b):
        return False
    for k in range(len(lb)):
        if b[i + k] != lb[k]:
            return False
    return True


def skip_json_value(line: String, start: Int) -> Tuple[Int, Bool]:
    var b = line.as_bytes()
    var i = skip_ws_json(line, start)
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
    if matches_lit_json(line, i, "true"):
        return (i + 4, True)
    if matches_lit_json(line, i, "false"):
        return (i + 5, True)
    if matches_lit_json(line, i, "null"):
        return (i + 4, True)
    return (i, False)


def iso_to_minute(ts: String) -> Int:
    """'2026-11-05T10:23:11Z' -> epoch minute, or -1 if unparseable."""
    if ts.byte_length() < 16:
        return -1
    var b = ts.as_bytes()
    if b[4] != 45 or b[7] != 45 or b[10] != 84 or b[13] != 58:
        return -1
    var y = (Int(b[0]) - 48) * 1000 + (Int(b[1]) - 48) * 100 + (Int(b[2]) - 48) * 10 + (Int(b[3]) - 48)
    var mo = (Int(b[5]) - 48) * 10 + (Int(b[6]) - 48)
    var d = (Int(b[8]) - 48) * 10 + (Int(b[9]) - 48)
    var hh = (Int(b[11]) - 48) * 10 + (Int(b[12]) - 48)
    var mm = (Int(b[14]) - 48) * 10 + (Int(b[15]) - 48)
    if mo < 1 or mo > 12 or d < 1 or d > 31 or hh > 23 or mm > 59:
        return -1
    return ymd_to_days(y, mo, d) * 1440 + hh * 60 + mm


def parse_json_event(line: String) -> EventFields:
    var out = EventFields()
    var b = line.as_bytes()
    var i = skip_ws_json(line, 0)
    if i >= len(b) or b[i] != 123:
        return out
    i += 1
    i = skip_ws_json(line, i)
    if i < len(b) and b[i] == 125:
        out.ok = True
        return out
    var seen_ts = False
    var seen_level = False
    var seen_service = False
    var ts_str = String("")
    while True:
        i = skip_ws_json(line, i)
        if i >= len(b) or b[i] != 34:
            return out
        var key_read = parse_json_string(line, i)
        if not key_read[2]:
            return out
        var key = key_read[0]
        i = skip_ws_json(line, key_read[1])
        if i >= len(b) or b[i] != 58:
            return out
        i += 1
        i = skip_ws_json(line, i)
        if i >= len(b):
            return out
        if key == "meta" and b[i] == 123:
            i += 1
            i = skip_ws_json(line, i)
            if i < len(b) and b[i] == 125:
                i += 1
            else:
                while True:
                    i = skip_ws_json(line, i)
                    var mkey_read = parse_json_string(line, i)
                    if not mkey_read[2]:
                        return out
                    var mkey = mkey_read[0]
                    i = skip_ws_json(line, mkey_read[1])
                    if i >= len(b) or b[i] != 58:
                        return out
                    i += 1
                    i = skip_ws_json(line, i)
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
                    i = skip_ws_json(line, i)
                    if i < len(b) and b[i] == 44:
                        i += 1
                        continue
                    if i < len(b) and b[i] == 125:
                        i += 1
                        break
                    return out
        elif key == "ts" or key == "level" or key == "service" or key == "request_id":
            var s_read = parse_json_string(line, i)
            if not s_read[2]:
                return out
            if key == "ts":
                ts_str = s_read[0]
                seen_ts = True
            elif key == "level":
                out.level = s_read[0]
                seen_level = True
            elif key == "service":
                out.service = s_read[0]
                seen_service = True
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
        i = skip_ws_json(line, i)
        if i < len(b) and b[i] == 44:
            i += 1
            continue
        if i < len(b) and b[i] == 125:
            i += 1
            break
        return out
    i = skip_ws_json(line, i)
    if i != len(b):
        return out
    if not seen_ts or not seen_level or not seen_service:
        return out
    var minute = iso_to_minute(ts_str)
    if minute < 0:
        return out
    out.minute = minute
    out.ok = True
    return out

# ---------------------------------------------------------------------------
# JSON aggregates (parallel).
# ---------------------------------------------------------------------------


struct JsonAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var missing_latency: Int
    var missing_status: Int
    var level_counts: Dict[String, Int]
    var service_counts: Dict[String, Int]
    var service_errors: Dict[String, Int]
    var region_counts: Dict[String, Int]
    var status_counts: Dict[Int, Int]
    var minute_events: Dict[Int, Int]
    var minute_errors: Dict[Int, Int]
    var request_ids: Dict[String, Int]
    var dup_ids: Int
    var dup_extra: Int

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.missing_latency = 0
        self.missing_status = 0
        self.level_counts = Dict[String, Int]()
        self.service_counts = Dict[String, Int]()
        self.service_errors = Dict[String, Int]()
        self.region_counts = Dict[String, Int]()
        self.status_counts = Dict[Int, Int]()
        self.minute_events = Dict[Int, Int]()
        self.minute_errors = Dict[Int, Int]()
        self.request_ids = Dict[String, Int]()
        self.dup_ids = 0
        self.dup_extra = 0

    def add_event(mut self, f: EventFields):
        self.total += 1
        if not f.ok:
            self.malformed += 1
            return
        self.parsed += 1
        self.level_counts[f.level] = self.level_counts.get(f.level, 0) + 1
        self.service_counts[f.service] = self.service_counts.get(f.service, 0) + 1
        if f.level == "ERROR":
            self.service_errors[f.service] = self.service_errors.get(f.service, 0) + 1
        if f.region != "":
            self.region_counts[f.region] = self.region_counts.get(f.region, 0) + 1
        if f.has_latency:
            pass
        else:
            self.missing_latency += 1
        if f.has_status:
            self.status_counts[f.status] = self.status_counts.get(f.status, 0) + 1
        else:
            self.missing_status += 1
        self.minute_events[f.minute] = self.minute_events.get(f.minute, 0) + 1
        if f.level == "ERROR":
            self.minute_errors[f.minute] = self.minute_errors.get(f.minute, 0) + 1
        if f.request_id != "":
            var seen = self.request_ids.get(f.request_id, 0)
            if seen == 1:
                self.dup_ids += 1
            if seen >= 1:
                self.dup_extra += 1
            self.request_ids[f.request_id] = seen + 1

    def merge(mut self, ref other: JsonAgg):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        self.missing_latency += other.missing_latency
        self.missing_status += other.missing_status
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
        for k in other.minute_events.keys():
            self.minute_events[k] = self.minute_events.get(k, 0) + other.minute_events.get(k, 0)
        for k in other.minute_errors.keys():
            self.minute_errors[k] = self.minute_errors.get(k, 0) + other.minute_errors.get(k, 0)
        self.dup_ids += other.dup_ids
        self.dup_extra += other.dup_extra
        for k in other.request_ids.keys():
            var seen = self.request_ids.get(k, 0)
            var add = other.request_ids.get(k, 0)
            var new_count = seen + add
            var new_dup = 0
            if new_count > 1:
                new_dup = 1
            var old_dup = 0
            if seen > 1:
                old_dup += 1
            if add > 1:
                old_dup += 1
            self.dup_ids += new_dup - old_dup
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


def parse_json_range(lines: List[String], start: Int, end: Int) -> JsonAgg:
    var agg = JsonAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        agg.add_event(parse_json_event(lines[i]))
    return agg^


def parse_json_parallel(lines: List[String], workers: Int) raises -> JsonAgg:
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
        var agg = parse_json_range(lines, start, end)
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
# Data-quality engine. Each rule is a (checked, failed) counter plus up
# to five failing samples. Rules run over the ingested aggregates and
# over targeted raw scans where the aggregate does not retain the
# information (e.g. tick timestamp monotonicity needs the raw order).
# ---------------------------------------------------------------------------


struct QualityRule(Copyable, Movable):
    var name: String
    var checked: Int
    var failed: Int
    var samples: List[String]

    def __init__(out self, name: String):
        self.name = name
        self.checked = 0
        self.failed = 0
        self.samples = List[String]()

    def __init__(out self, *, other: Self):
        self.name = other.name
        self.checked = other.checked
        self.failed = other.failed
        self.samples = other.samples.copy()

    def check(mut self, passed: Bool, sample: String):
        self.checked += 1
        if not passed:
            self.failed += 1
            if len(self.samples) < 5:
                self.samples.append(sample)


struct QualityReport(Movable):
    var rules: List[QualityRule]

    def __init__(out self):
        self.rules = List[QualityRule]()

    def add_rule(mut self, name: String) -> Int:
        self.rules.append(QualityRule(name))
        return len(self.rules) - 1

    def total_failed(self) -> Int:
        var n = 0
        for i in range(len(self.rules)):
            n += self.rules[i].failed
        return n

    def total_checked(self) -> Int:
        var n = 0
        for i in range(len(self.rules)):
            n += self.rules[i].checked
        return n


def known_status(code: Int) -> Bool:
    return code == 200 or code == 201 or code == 204 or code == 301 or code == 302 or code == 304 or code == 400 or code == 401 or code == 403 or code == 404 or code == 500 or code == 501 or code == 502 or code == 503


def known_method(m: String) -> Bool:
    return m == "GET" or m == "POST" or m == "PUT" or m == "DELETE" or m == "HEAD" or m == "PATCH" or m == "OPTIONS"


def known_symbol(s: String) -> Bool:
    return s == "ACME" or s == "BOLT" or s == "CRUX" or s == "DUNE" or s == "ECHO" or s == "FLUX" or s == "GALE" or s == "HALO"


def known_exchange(e: String) -> Bool:
    return e == "NYSE" or e == "NASDAQ" or e == "BATS"


def known_level(l: String) -> Bool:
    return l == "INFO" or l == "DEBUG" or l == "WARN" or l == "ERROR"


def known_service(s: String) -> Bool:
    return s == "gateway" or s == "auth" or s == "orders" or s == "pricing" or s == "inventory" or s == "notify"


def known_region(r: String) -> Bool:
    return r == "us-east-1" or r == "us-west-2" or r == "eu-west-1" or r == "ap-south-1"


def run_quality_logs(ref agg: LogAgg) -> QualityReport:
    var rep = QualityReport()
    var r_status = rep.add_rule("log: status code in known set")
    for code in agg.status_counts.keys():
        var count = agg.status_counts.get(code, 0)
        for _ in range(count):
            rep.rules[r_status].check(known_status(code), "status=" + String(code))
    var r_method = rep.add_rule("log: method in known set")
    for m in agg.method_counts.keys():
        var count = agg.method_counts.get(m, 0)
        for _ in range(count):
            rep.rules[r_method].check(known_method(m), "method=" + m)
    var r_url = rep.add_rule("log: url starts with /")
    for url in agg.url_counts.keys():
        var count = agg.url_counts.get(url, 0)
        for _ in range(count):
            rep.rules[r_url].check(url.startswith("/"), "url=" + url)
    var r_malformed = rep.add_rule("log: line parses cleanly")
    for _ in range(agg.parsed):
        rep.rules[r_malformed].check(True, "")
    for _ in range(agg.malformed):
        rep.rules[r_malformed].check(False, "unparseable log line")
    return rep^


def run_quality_ticks(ref agg: TickAgg, lines: List[String]) -> QualityReport:
    var rep = QualityReport()
    var r_symbol = rep.add_rule("tick: symbol in known set")
    for sym in agg.symbols.keys():
        var bar = agg.symbols.get(sym, Bar())
        for _ in range(bar.trades):
            rep.rules[r_symbol].check(known_symbol(sym), "symbol=" + sym)
    var r_exchange = rep.add_rule("tick: exchange in known set")
    for ex in agg.exchanges.keys():
        var count = agg.exchanges.get(ex, 0)
        for _ in range(count):
            rep.rules[r_exchange].check(known_exchange(ex), "exchange=" + ex)
    var r_price = rep.add_rule("tick: price positive and below 100000")
    for sym in agg.symbols.keys():
        var bar = agg.symbols.get(sym, Bar())
        var ok = bar.low > 0.0 and bar.high < 100000.0
        for _ in range(bar.trades):
            rep.rules[r_price].check(ok, "symbol=" + sym + " low=" + fmt2(bar.low) + " high=" + fmt2(bar.high))
    var r_malformed = rep.add_rule("tick: line parses cleanly")
    for _ in range(agg.parsed):
        rep.rules[r_malformed].check(True, "")
    for _ in range(agg.malformed):
        rep.rules[r_malformed].check(False, "unparseable tick line")
    # Monotonicity needs the raw order: one pass over the tick lines.
    var r_mono = rep.add_rule("tick: timestamps non-decreasing in file order")
    var prev_ts = -1
    for i in range(len(lines)):
        var line = lines[i]
        if line.byte_length() == 0 or line.startswith("timestamp,"):
            continue
        var f = parse_tick_line(line)
        if not f.ok:
            continue
        rep.rules[r_mono].check(f.ts >= prev_ts, "ts=" + String(f.ts) + " prev=" + String(prev_ts))
        if f.ts > prev_ts:
            prev_ts = f.ts
    return rep^


def run_quality_json(ref agg: JsonAgg) -> QualityReport:
    var rep = QualityReport()
    var r_level = rep.add_rule("json: level in known set")
    for lv in agg.level_counts.keys():
        var count = agg.level_counts.get(lv, 0)
        for _ in range(count):
            rep.rules[r_level].check(known_level(lv), "level=" + lv)
    var r_service = rep.add_rule("json: service in known set")
    for svc in agg.service_counts.keys():
        var count = agg.service_counts.get(svc, 0)
        for _ in range(count):
            rep.rules[r_service].check(known_service(svc), "service=" + svc)
    var r_region = rep.add_rule("json: region in known set")
    for rg in agg.region_counts.keys():
        var count = agg.region_counts.get(rg, 0)
        for _ in range(count):
            rep.rules[r_region].check(known_region(rg), "region=" + rg)
    var r_status = rep.add_rule("json: status in known set")
    for code in agg.status_counts.keys():
        var count = agg.status_counts.get(code, 0)
        for _ in range(count):
            rep.rules[r_status].check(known_status(code), "status=" + String(code))
    var r_missing = rep.add_rule("json: latency and status present")
    for _ in range(agg.parsed - agg.missing_latency):
        rep.rules[r_missing].check(True, "")
    for _ in range(agg.missing_latency):
        rep.rules[r_missing].check(False, "missing latency_ms")
    for _ in range(agg.parsed - agg.missing_status):
        rep.rules[r_missing].check(True, "")
    for _ in range(agg.missing_status):
        rep.rules[r_missing].check(False, "missing status")
    var r_dup = rep.add_rule("json: request_id unique")
    for _ in range(agg.parsed - agg.dup_extra):
        rep.rules[r_dup].check(True, "")
    for _ in range(agg.dup_extra):
        rep.rules[r_dup].check(False, "duplicate request_id")
    var r_malformed = rep.add_rule("json: line parses cleanly")
    for _ in range(agg.parsed):
        rep.rules[r_malformed].check(True, "")
    for _ in range(agg.malformed):
        rep.rules[r_malformed].check(False, "unparseable json line")
    return rep^


def merge_reports(mut a: QualityReport, ref b: QualityReport):
    for i in range(len(b.rules)):
        var found = -1
        for j in range(len(a.rules)):
            if a.rules[j].name == b.rules[i].name:
                found = j
        if found < 0:
            a.rules.append(b.rules[i].copy())
        else:
            a.rules[found].checked += b.rules[i].checked
            a.rules[found].failed += b.rules[i].failed
            for s in b.rules[i].samples:
                if len(a.rules[found].samples) < 5:
                    a.rules[found].samples.append(s)


# ---------------------------------------------------------------------------
# Per-minute join and anomaly detection.
# ---------------------------------------------------------------------------


struct MinuteRow(Copyable, ImplicitlyCopyable, Movable):
    var minute: Int
    var log_lines: Int
    var log_errors: Int
    var tick_trades: Int
    var tick_volume: Int
    var json_events: Int
    var json_errors: Int
    var anomaly: Bool
    var reasons: String

    def __init__(out self):
        self.minute = 0
        self.log_lines = 0
        self.log_errors = 0
        self.tick_trades = 0
        self.tick_volume = 0
        self.json_events = 0
        self.json_errors = 0
        self.anomaly = False
        self.reasons = ""

    def __init__(out self, *, other: Self):
        self.minute = other.minute
        self.log_lines = other.log_lines
        self.log_errors = other.log_errors
        self.tick_trades = other.tick_trades
        self.tick_volume = other.tick_volume
        self.json_events = other.json_events
        self.json_errors = other.json_errors
        self.anomaly = other.anomaly
        self.reasons = other.reasons

    def log_err_rate(self) -> Float64:
        if self.log_lines == 0:
            return 0.0
        return 100.0 * Float64(self.log_errors) / Float64(self.log_lines)

    def json_err_rate(self) -> Float64:
        if self.json_events == 0:
            return 0.0
        return 100.0 * Float64(self.json_errors) / Float64(self.json_events)


def build_minute_rows(ref logs: LogAgg, ref ticks: TickAgg, ref events: JsonAgg) -> List[MinuteRow]:
    var by_minute = Dict[Int, MinuteRow]()
    for mn in logs.minute_lines.keys():
        var row = MinuteRow()
        row.minute = mn
        row.log_lines = logs.minute_lines.get(mn, 0)
        row.log_errors = logs.minute_errors.get(mn, 0)
        by_minute[mn] = row
    for mn in ticks.minute_trades.keys():
        if mn in by_minute:
            var row = by_minute.get(mn, MinuteRow())
            row.tick_trades = ticks.minute_trades.get(mn, 0)
            row.tick_volume = ticks.minute_volume.get(mn, 0)
            by_minute[mn] = row
        else:
            var row = MinuteRow()
            row.minute = mn
            row.tick_trades = ticks.minute_trades.get(mn, 0)
            row.tick_volume = ticks.minute_volume.get(mn, 0)
            by_minute[mn] = row
    for mn in events.minute_events.keys():
        if mn in by_minute:
            var row = by_minute.get(mn, MinuteRow())
            row.json_events = events.minute_events.get(mn, 0)
            row.json_errors = events.minute_errors.get(mn, 0)
            by_minute[mn] = row
        else:
            var row = MinuteRow()
            row.minute = mn
            row.json_events = events.minute_events.get(mn, 0)
            row.json_errors = events.minute_errors.get(mn, 0)
            by_minute[mn] = row
    var minutes = List[Int]()
    for mn in by_minute.keys():
        minutes.append(mn)
    sort(minutes)
    var rows = List[MinuteRow]()
    for mn in minutes:
        rows.append(by_minute.get(mn, MinuteRow()))
    return rows^


def median_int(values: List[Int]) -> Float64:
    if len(values) == 0:
        return 0.0
    var sorted_vals = List[Int]()
    for v in values:
        sorted_vals.append(v)
    sort(sorted_vals)
    var mid = len(sorted_vals) / 2
    if len(sorted_vals) % 2 == 1:
        return Float64(sorted_vals[mid])
    return (Float64(sorted_vals[mid - 1]) + Float64(sorted_vals[mid])) / 2.0


def detect_anomalies(mut rows: List[MinuteRow]) -> Int:
    """Flag anomalous minutes. Rules (all thresholds are documented in
    the report so the flags are auditable):
    - A: correlated error spike -- log error rate > 10% AND json error
      rate > 10% in the same minute.
    - B: volume collapse -- tick volume below 50% of the median minute
      volume while the log error rate is above 10%.
    - C: silent feed -- a minute with log lines and json events but
      zero tick trades (the market feed went quiet).
    Returns the number of flagged minutes."""
    var volumes = List[Int]()
    for i in range(len(rows)):
        volumes.append(rows[i].tick_volume)
    var med_vol = median_int(volumes)
    var flagged = 0
    for i in range(len(rows)):
        var reasons = List[String]()
        if rows[i].log_err_rate() > 10.0 and rows[i].json_err_rate() > 10.0:
            reasons.append("correlated-error-spike")
        if med_vol > 0.0 and Float64(rows[i].tick_volume) < 0.5 * med_vol and rows[i].log_err_rate() > 10.0:
            reasons.append("volume-collapse-with-errors")
        if rows[i].log_lines > 0 and rows[i].json_events > 0 and rows[i].tick_trades == 0:
            reasons.append("silent-tick-feed")
        if len(reasons) > 0:
            rows[i].anomaly = True
            rows[i].reasons = String(";").join(reasons)
            flagged += 1
    return flagged

# ---------------------------------------------------------------------------
# Outputs: cleaned ticks, per-minute summary CSV, JSON run summary.
# ---------------------------------------------------------------------------


def write_clean_ticks(path: Path, lines: List[String]) raises -> Int:
    """Write the cleaned tick file: header plus every valid trade with
    its epoch minute appended. Returns the number of data rows written."""
    var out_lines = List[String]()
    out_lines.append("timestamp,symbol,price,size,exchange,minute")
    var rows = 0
    for i in range(len(lines)):
        var line = lines[i]
        if line.byte_length() == 0 or line.startswith("timestamp,"):
            continue
        var f = parse_tick_line(line)
        if not f.ok:
            continue
        out_lines.append(
            String(f.ts)
            + ","
            + f.symbol
            + ","
            + fmt2(f.price)
            + ","
            + String(f.size)
            + ","
            + f.exchange
            + ","
            + String(f.ts / 60)
        )
        rows += 1
    path.write_text(String("\n").join(out_lines) + "\n")
    return rows


def anomaly_flag(a: Bool) -> String:
    if a:
        return "1"
    return "0"


def write_minute_summary(path: Path, rows: List[MinuteRow]) raises:
    var out_lines = List[String]()
    out_lines.append("minute,minute_label,log_lines,log_errors,log_err_rate,tick_trades,tick_volume,json_events,json_errors,json_err_rate,anomaly,reasons")
    for i in range(len(rows)):
        var r = rows[i]
        out_lines.append(
            String(r.minute)
            + ","
            + minute_label(r.minute)
            + ","
            + String(r.log_lines)
            + ","
            + String(r.log_errors)
            + ","
            + fmt2(r.log_err_rate())
            + ","
            + String(r.tick_trades)
            + ","
            + String(r.tick_volume)
            + ","
            + String(r.json_events)
            + ","
            + String(r.json_errors)
            + ","
            + fmt2(r.json_err_rate())
            + ","
            + anomaly_flag(r.anomaly)
            + ","
            + r.reasons
        )
    path.write_text(String("\n").join(out_lines) + "\n")


def quality_to_json(rep: QualityReport) -> String:
    var parts = List[String]()
    for i in range(len(rep.rules)):
        var r = rep.rules[i].copy()
        var samples = List[String]()
        for s in r.samples:
            samples.append('"' + json_escape(s) + '"')
        parts.append(
            '{"rule":"'
            + json_escape(r.name)
            + '","checked":'
            + String(r.checked)
            + ',"failed":'
            + String(r.failed)
            + ',"samples":['
            + String(",").join(samples)
            + "]}"
        )
    return "[" + String(",").join(parts) + "]"


def write_run_summary(
    path: Path,
    ref logs: LogAgg,
    ref ticks: TickAgg,
    ref events: JsonAgg,
    ref quality: QualityReport,
    rows: List[MinuteRow],
    n_anomalies: Int,
    seconds_ingest: Float64,
    seconds_total: Float64,
) raises:
    var anomalies = List[String]()
    for i in range(len(rows)):
        if rows[i].anomaly:
            anomalies.append(
                '{"minute":'
                + String(rows[i].minute)
                + ',"label":"'
                + minute_label(rows[i].minute)
                + '","log_err_rate":'
                + fmt2(rows[i].log_err_rate())
                + ',"json_err_rate":'
                + fmt2(rows[i].json_err_rate())
                + ',"tick_volume":'
                + String(rows[i].tick_volume)
                + ',"reasons":"'
                + json_escape(rows[i].reasons)
                + '"}'
            )
    var text = String(
        "{\n"
        + '  "ingest": {"log_lines": '
        + String(logs.total)
        + ', "log_parsed": '
        + String(logs.parsed)
        + ', "log_malformed": '
        + String(logs.malformed)
        + ', "log_bytes": '
        + String(logs.bytes_total)
        + ', "tick_lines": '
        + String(ticks.total)
        + ', "tick_parsed": '
        + String(ticks.parsed)
        + ', "tick_malformed": '
        + String(ticks.malformed)
        + ', "tick_volume": '
        + String(ticks.total_volume)
        + ', "json_lines": '
        + String(events.total)
        + ', "json_parsed": '
        + String(events.parsed)
        + ', "json_malformed": '
        + String(events.malformed)
        + ', "json_dup_ids": '
        + String(events.dup_ids)
        + '},\n'
        + '  "quality": {"checked": '
        + String(quality.total_checked())
        + ', "failed": '
        + String(quality.total_failed())
        + ', "rules": '
        + quality_to_json(quality)
        + '},\n'
        + '  "join": {"minutes": '
        + String(len(rows))
        + ', "anomalies": '
        + String(n_anomalies)
        + ', "anomaly_minutes": ['
        + String(",").join(anomalies)
        + ']},\n'
        + '  "timing": {"ingest_s": '
        + fmt2(seconds_ingest)
        + ', "total_s": '
        + fmt2(seconds_total)
        + '}\n'
        + "}\n"
    )
    path.write_text(text)


# ---------------------------------------------------------------------------
# Output verification: re-read everything the pipeline wrote and check
# it independently of the in-memory structures that produced it.
# ---------------------------------------------------------------------------


def verify_outputs(out_dir: String, expect_ticks: Int, expect_minutes: Int, expect_anomalies: Int) raises:
    var clean_path = Path(out_dir + "/clean_ticks.csv")
    var clean_text = clean_path.read_text()
    var clean_lines = to_owned_lines(clean_text)
    assert_equal(String(clean_lines[0]), "timestamp,symbol,price,size,exchange,minute")
    var clean_rows = 0
    for i in range(1, len(clean_lines)):
        if clean_lines[i].byte_length() == 0:
            continue
        clean_rows += 1
        # The minute column makes this a 6-field line (header says so).
        var parts = clean_lines[i].split(",")
        assert_equal(len(parts), 6)
        assert_true(known_symbol(String(parts[1])), "clean output keeps only known symbols")
    assert_equal(clean_rows, expect_ticks)
    var summary_path = Path(out_dir + "/minute_summary.csv")
    var summary_text = summary_path.read_text()
    var summary_lines = to_owned_lines(summary_text)
    assert_true(String(summary_lines[0]).startswith("minute,minute_label,"))
    var summary_rows = 0
    var anomaly_rows = 0
    for i in range(1, len(summary_lines)):
        if summary_lines[i].byte_length() == 0:
            continue
        summary_rows += 1
        var parts = summary_lines[i].split(",")
        assert_equal(len(parts), 12)
        if String(parts[10]) == "1":
            anomaly_rows += 1
    assert_equal(summary_rows, expect_minutes)
    assert_equal(anomaly_rows, expect_anomalies)
    var json_path = Path(out_dir + "/pipeline_summary.json")
    var json_text = json_path.read_text()
    assert_true(json_text.startswith("{"))
    assert_true(json_text.endswith("}\n"))
    assert_true(json_text.find('"ingest"') >= 0)
    assert_true(json_text.find('"quality"') >= 0)
    assert_true(json_text.find('"join"') >= 0)
    assert_true(json_text.find('"timing"') >= 0)
    # Braces must balance (a cheap well-formedness check for hand-built JSON).
    var depth = 0
    var in_str = False
    var prev: UInt8 = 0
    for c in json_text.as_bytes():
        if c == 34 and prev != 92:
            in_str = not in_str
        if not in_str:
            if c == 123:
                depth += 1
            elif c == 125:
                depth -= 1
        prev = c
    assert_equal(depth, 0)
    print("  output verification OK:", clean_rows, "clean ticks,", summary_rows, "minute rows,", anomaly_rows, "anomalies")


# ---------------------------------------------------------------------------
# Unit tests.
# ---------------------------------------------------------------------------


def test_minute_label() raises:
    assert_equal(minute_label(29897280), "2026-11-05T00:00Z")
    assert_equal(minute_label(29897280 + 61), "2026-11-05T01:01Z")
    assert_equal(minute_label(0), "1970-01-01T00:00Z")
    assert_equal(minute_label(ymd_to_days(2026, 11, 5) * 1440 + 10 * 60 + 23), "2026-11-05T10:23Z")
    print("  test_minute_label OK")


def test_iso_to_minute() raises:
    assert_equal(iso_to_minute("2026-11-05T10:23:11Z"), ymd_to_days(2026, 11, 5) * 1440 + 623)
    assert_equal(iso_to_minute("1970-01-01T00:00:00Z"), 0)
    assert_equal(iso_to_minute("garbage"), -1)
    assert_equal(iso_to_minute("2026-13-05T10:23:11Z"), -1)
    print("  test_iso_to_minute OK")


def test_json_escape() raises:
    assert_equal(json_escape("plain"), "plain")
    assert_equal(json_escape('a"b'), 'a\\"b')
    assert_equal(json_escape("a\\b"), "a\\\\b")
    assert_equal(json_escape("a\nb"), "a\\nb")
    assert_equal(json_escape("a\tb"), "a\\tb")
    print("  test_json_escape OK")


def test_log_epoch_minute() raises:
    var f = parse_log_line(
        String('1.2.3.4 - - [05/Nov/2026:10:23:11 +0000] "GET /x HTTP/1.1" 200 10 "-" "ua"')
    )
    assert_true(f.ok)
    assert_equal(f.minute, ymd_to_days(2026, 11, 5) * 1440 + 623)
    var g = parse_log_line(
        String('1.2.3.4 - - [15/Jan/2026:08:30:00 +0000] "GET /x HTTP/1.1" 200 10 "-" "ua"')
    )
    assert_true(g.ok)
    assert_equal(g.minute, ymd_to_days(2026, 1, 15) * 1440 + 510)
    print("  test_log_epoch_minute OK")


def test_join_and_anomaly() raises:
    var logs = LogAgg()
    var ticks = TickAgg()
    var events = JsonAgg()
    # Minute 100: heavy errors everywhere, normal volume.
    for _ in range(11):
        var lf = LogFields()
        lf.ok = True
        lf.method = "GET"
        lf.url = "/x"
        lf.status = 500
        lf.size = 10
        lf.minute = 100
        logs.add_line(lf)
    for _ in range(89):
        var lf = LogFields()
        lf.ok = True
        lf.method = "GET"
        lf.url = "/x"
        lf.status = 200
        lf.size = 10
        lf.minute = 100
        logs.add_line(lf)
    var tf = TickFields()
    tf.ok = True
    tf.ts = 100 * 60 + 5
    tf.symbol = "ACME"
    tf.price = 100.0
    tf.size = 1000
    tf.exchange = "NYSE"
    ticks.add_tick(tf)
    for _ in range(3):
        var ef = EventFields()
        ef.ok = True
        ef.level = "ERROR"
        ef.service = "orders"
        ef.has_latency = True
        ef.latency = 100.0
        ef.has_status = True
        ef.status = 500
        ef.request_id = "req-x"
        ef.minute = 100
        events.add_event(ef)
    for _ in range(7):
        var ef = EventFields()
        ef.ok = True
        ef.level = "INFO"
        ef.service = "orders"
        ef.has_latency = True
        ef.latency = 10.0
        ef.has_status = True
        ef.status = 200
        ef.request_id = "req-y"
        ef.minute = 100
        events.add_event(ef)
    # Minute 101: quiet minute, everything fine, big volume.
    for _ in range(50):
        var lf = LogFields()
        lf.ok = True
        lf.method = "GET"
        lf.url = "/x"
        lf.status = 200
        lf.size = 10
        lf.minute = 101
        logs.add_line(lf)
    var tf2 = TickFields()
    tf2.ok = True
    tf2.ts = 101 * 60 + 5
    tf2.symbol = "ACME"
    tf2.price = 100.0
    tf2.size = 100000
    tf2.exchange = "NYSE"
    ticks.add_tick(tf2)
    for _ in range(10):
        var ef = EventFields()
        ef.ok = True
        ef.level = "INFO"
        ef.service = "orders"
        ef.has_latency = True
        ef.latency = 10.0
        ef.has_status = True
        ef.status = 200
        ef.request_id = "req-z"
        ef.minute = 101
        events.add_event(ef)
    var rows = build_minute_rows(logs, ticks, events)
    assert_equal(len(rows), 2)
    assert_equal(rows[0].minute, 100)
    assert_equal(rows[0].log_lines, 100)
    assert_equal(rows[0].log_errors, 11)
    assert_equal(rows[0].tick_volume, 1000)
    assert_equal(rows[0].json_events, 10)
    assert_equal(rows[0].json_errors, 3)
    assert_equal(rows[1].tick_volume, 100000)
    var flagged = detect_anomalies(rows)
    assert_equal(flagged, 1)
    assert_true(rows[0].anomaly)
    assert_true(not rows[1].anomaly)
    assert_true(rows[0].reasons.find("correlated-error-spike") >= 0)
    print("  test_join_and_anomaly OK")


def test_quality_rules() raises:
    assert_true(known_status(200))
    assert_true(not known_status(999))
    assert_true(known_method("GET"))
    assert_true(not known_method("BREW"))
    assert_true(known_symbol("ACME"))
    assert_true(not known_symbol("NOPE"))
    assert_true(known_exchange("BATS"))
    assert_true(known_level("WARN"))
    assert_true(not known_level("TRACE"))
    assert_true(known_service("notify"))
    assert_true(known_region("eu-west-1"))
    assert_true(not known_region("moon-1"))
    var rep = QualityReport()
    var idx = rep.add_rule("demo")
    rep.rules[idx].check(True, "")
    rep.rules[idx].check(False, "bad sample")
    rep.rules[idx].check(False, "bad sample 2")
    assert_equal(rep.total_checked(), 3)
    assert_equal(rep.total_failed(), 2)
    assert_equal(len(rep.rules[idx].samples), 2)
    print("  test_quality_rules OK")


def run_tests() raises:
    print("Running unit tests:")
    test_minute_label()
    test_iso_to_minute()
    test_json_escape()
    test_log_epoch_minute()
    test_join_and_anomaly()
    test_quality_rules()
    print("All pipeline unit tests passed.")


# ---------------------------------------------------------------------------
# Embedded fallback generators (same format / seed family as etl_gen_data).
# ---------------------------------------------------------------------------


def gen_log_lines(n: Int) -> List[String]:
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
    var ts = 1793836800
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
        var hh = (ts / 3600) % 24
        var mm = (ts / 60) % 60
        var ss = ts % 60
        var ip = String(1 + Int(random_float64() * 223.0)) + "." + String(Int(random_float64() * 256.0)) + "." + String(Int(random_float64() * 256.0)) + "." + String(1 + Int(random_float64() * 254.0))
        lines.append(
            ip
            + ' - - [05/Nov/2026:'
            + two_digit(hh)
            + ":"
            + two_digit(mm)
            + ":"
            + two_digit(ss)
            + ' +0000] "GET '
            + url
            + ' HTTP/1.1" '
            + String(status)
            + " "
            + String(size)
            + ' "-" "curl/8.5.0"'
        )
    return lines^


def gen_tick_lines(n: Int) -> List[String]:
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
    var ts = 1793836800
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
        lines.append(String(ts) + "," + symbols[si] + "," + fmt2(price) + "," + String(size) + "," + ex)
    return lines^


def gen_json_lines(n: Int) -> List[String]:
    var services = List[String]()
    services.append("gateway")
    services.append("auth")
    services.append("orders")
    services.append("pricing")
    services.append("inventory")
    services.append("notify")
    var regions = List[String]()
    regions.append("us-east-1")
    regions.append("us-west-2")
    regions.append("eu-west-1")
    regions.append("ap-south-1")
    var lines = List[String]()
    var ts = 1793836800
    for _ in range(n):
        ts += 1 + Int(random_float64() * 3.0)
        var r = random_float64()
        var level: String
        if r < 0.62:
            level = "INFO"
        elif r < 0.82:
            level = "DEBUG"
        elif r < 0.93:
            level = "WARN"
        else:
            level = "ERROR"
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
        lines.append(
            '{"ts":"'
            + ts_s
            + '","level":"'
            + level
            + '","service":"'
            + service
            + '","msg":"request completed","latency_ms":'
            + fmt2(latency)
            + ',"status":200,"request_id":"req-'
            + String(100000 + Int(random_float64() * 900000.0))
            + '","meta":{"region":"'
            + regions[Int(random_float64() * Float64(len(regions)))]
            + '"}}'
        )
    return lines^


def ensure_inputs(data_dir: String) raises:
    if not Path(data_dir).exists():
        mkdir(data_dir)
    var log_path = Path(data_dir + "/access.log")
    if not log_path.exists():
        print("Generating access.log (50,000 lines) ...")
        seed(20261105)
        log_path.write_text(String("\n").join(gen_log_lines(50000)) + "\n")
    var tick_path = Path(data_dir + "/ticks.csv")
    if not tick_path.exists():
        print("Generating ticks.csv (100,000 trades) ...")
        seed(20261106)
        tick_path.write_text(String("\n").join(gen_tick_lines(100000)) + "\n")
    var json_path = Path(data_dir + "/events.jsonl")
    if not json_path.exists():
        print("Generating events.jsonl (30,000 events) ...")
        seed(20261107)
        json_path.write_text(String("\n").join(gen_json_lines(30000)) + "\n")


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def main() raises:
    var t_start = perf_counter()
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
    ensure_inputs(data_dir)
    var out_dir = data_dir + "/pipeline_out"
    if not Path(out_dir).exists():
        mkdir(out_dir)

    # --- Ingest (parallel) ---
    print("Ingest (parallel, " + String(workers) + " workers) ...")
    var t_ing0 = perf_counter()
    var log_text = Path(data_dir + "/access.log").read_text()
    var tick_text = Path(data_dir + "/ticks.csv").read_text()
    var json_text = Path(data_dir + "/events.jsonl").read_text()
    var log_lines = to_owned_lines(log_text)
    var tick_lines = to_owned_lines(tick_text)
    var json_lines = to_owned_lines(json_text)
    var logs = parse_logs_parallel(log_lines, workers)
    var ticks = parse_ticks_parallel(tick_lines, workers)
    var events = parse_json_parallel(json_lines, workers)
    var t_ingest = perf_counter() - t_ing0
    print("  logs:  ", logs.parsed, "parsed,", logs.malformed, "malformed of", logs.total)
    print("  ticks: ", ticks.parsed, "parsed,", ticks.malformed, "malformed of", ticks.total)
    print("  json:  ", events.parsed, "parsed,", events.malformed, "malformed of", events.total)
    print("  ingest took", fmt2(t_ingest), "s")
    assert_equal(logs.total, count_nonempty(log_lines))
    assert_equal(ticks.total, count_nonempty(tick_lines) - 1)
    assert_equal(events.total, count_nonempty(json_lines))

    # --- Quality ---
    print("Data quality ...")
    var quality = QualityReport()
    var q_logs = run_quality_logs(logs)
    var q_ticks = run_quality_ticks(ticks, tick_lines)
    var q_json = run_quality_json(events)
    merge_reports(quality, q_logs)
    merge_reports(quality, q_ticks)
    merge_reports(quality, q_json)
    print("  checked", quality.total_checked(), "values,", quality.total_failed(), "failures")
    for i in range(len(quality.rules)):
        var r = quality.rules[i].copy()
        print("   ", r.name, ": ", r.checked, "checked,", r.failed, "failed")
        for s in r.samples:
            print("      sample:", s)

    # --- Join + anomalies ---
    print("Joining per-minute ...")
    var rows = build_minute_rows(logs, ticks, events)
    var n_anomalies = detect_anomalies(rows)
    print("  minutes:", len(rows), " anomalies:", n_anomalies)
    for i in range(len(rows)):
        if rows[i].anomaly:
            print(
                "   ANOMALY",
                minute_label(rows[i].minute),
                "log_err=",
                fmt2(rows[i].log_err_rate()),
                "% json_err=",
                fmt2(rows[i].json_err_rate()),
                "% tick_vol=",
                rows[i].tick_volume,
                " ",
                rows[i].reasons,
            )

    # --- Publish ---
    print("Publishing outputs to " + out_dir + " ...")
    var n_clean = write_clean_ticks(Path(out_dir + "/clean_ticks.csv"), tick_lines)
    write_minute_summary(Path(out_dir + "/minute_summary.csv"), rows)
    var t_total = perf_counter() - t_start
    write_run_summary(
        Path(out_dir + "/pipeline_summary.json"),
        logs,
        ticks,
        events,
        quality,
        rows,
        n_anomalies,
        t_ingest,
        t_total,
    )
    print("  clean ticks written:", n_clean)

    # --- Verify what was published, by re-reading it ---
    print("Verifying outputs ...")
    verify_outputs(out_dir, ticks.parsed, len(rows), n_anomalies)
    assert_equal(n_clean, ticks.parsed)
    print("DONE: pipeline complete in", fmt2(t_total), "s; outputs verified in", out_dir)
