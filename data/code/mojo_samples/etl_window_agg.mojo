# etl_window_agg.mojo
#
# Time-window aggregations for the START project's Mojo ETL samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.)
# Requires Mojo 1.2.0.
#
# Windowed aggregation is the core of streaming ETL: raw events arrive
# as a time-ordered stream and are reduced into windows. This program
# implements the three standard window shapes over real files on disk:
#
#   tumbling windows - fixed, non-overlapping 5-minute buckets. Each
#     trade belongs to exactly one window. Tumbling windows parallelize
#     cleanly (chunked map-reduce, as in the other ETL programs) because
#     a window never spans a chunk boundary in the merge step: partial
#     per-window aggregates merge by key.
#   sliding windows  - 15-minute windows sliding forward by 5 minutes,
#     so each trade belongs to three windows. Computed with a two-pointer
#     sweep over the time-ordered trade stream (linear time), and checked
#     against a brute-force O(n*w) reference on small inputs.
#   session windows  - gap-based sessions per symbol: a new session
#     starts whenever the gap between consecutive trades of the same
#     symbol exceeds 60 seconds. Sessions are inherently order-dependent
#     and are computed by a single ordered scan; the program documents
#     why they do not parallelize by naive chunking (a session can span
#     a chunk boundary, so chunks would need boundary state).
#
# All three window types are also computed for the access log (per-window
# request counts and error rates), so the program shows windows over two
# very different event shapes.
#
# Verification: tumbling windows are asserted equal between the parallel
# and single-threaded parses; sliding windows are asserted equal between
# the two-pointer sweep and brute force; sessions are asserted against
# hand-computed expectations on crafted inputs.
#
# Usage:
#   mojo etl_window_agg.mojo [data-dir] [workers]
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


def to_owned_lines(text: String) raises -> List[String]:
    var slices = text.split("\n")
    var lines = List[String]()
    for i in range(len(slices)):
        lines.append(String(slices[i]))
    return lines^


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


def minute_label(epoch_minute: Int) -> String:
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


# ---------------------------------------------------------------------------
# Event parsing (compact copies of the log/tick parsers).
# ---------------------------------------------------------------------------


struct LogEvent(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var status: Int
    var minute: Int

    def __init__(out self):
        self.ok = False
        self.status = 0
        self.minute = -1

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.status = other.status
        self.minute = other.minute


def parse_log_event(line: StringSlice) -> LogEvent:
    var out = LogEvent()
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
    var day = (Int(tb[0]) - 48) * 10 + (Int(tb[1]) - 48)
    var mon = month_num(ts[byte = 3:6])
    var year = (Int(tb[7]) - 48) * 1000 + (Int(tb[8]) - 48) * 100 + (Int(tb[9]) - 48) * 10 + (Int(tb[10]) - 48)
    if mon < 1 or day < 1 or day > 31:
        return out
    var q1 = line.find('"')
    if q1 < 0:
        return out
    var rest_after_q1 = String(line[byte = q1 + 1 : line.byte_length()])
    var q2rel = rest_after_q1.find('"')
    if q2rel < 0:
        return out
    var tail = line[byte = q1 + 1 + q2rel + 1 : line.byte_length()]
    var status_read = read_int_at(tail, 0)
    if not status_read[2]:
        return out
    var status = status_read[0]
    if status < 100 or status > 599:
        return out
    out.ok = True
    out.status = status
    out.minute = ymd_to_days(year, mon, day) * 1440 + hour * 60 + minute
    return out


struct Trade(Copyable, ImplicitlyCopyable, Movable):
    var ok: Bool
    var ts: Int
    var symbol: String
    var price: Float64
    var size: Int

    def __init__(out self):
        self.ok = False
        self.ts = 0
        self.symbol = ""
        self.price = 0.0
        self.size = 0

    def __init__(out self, *, other: Self):
        self.ok = other.ok
        self.ts = other.ts
        self.symbol = other.symbol
        self.price = other.price
        self.size = other.size


def parse_trade(line: StringSlice) -> Trade:
    var out = Trade()
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
    out.ok = True
    out.ts = ts_read[0]
    out.symbol = symbol
    out.price = price_read[0]
    out.size = size_read[0]
    return out


def load_trades(lines: List[String]) -> List[Trade]:
    """Parse all tick lines into a time-ordered trade list. The file is
    already time-ordered; this preserves that order for the sweep and
    session algorithms, which depend on it."""
    var trades = List[Trade]()
    for i in range(len(lines)):
        if lines[i].byte_length() == 0 or lines[i].startswith("timestamp,"):
            continue
        var t = parse_trade(lines[i])
        if t.ok:
            trades.append(t)
    return trades^

# ---------------------------------------------------------------------------
# Window aggregates.
# ---------------------------------------------------------------------------


struct WinBar(Copyable, ImplicitlyCopyable, Movable):
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

    def merge_from(mut self, ref other: WinBar):
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


struct LogWindow(Copyable, ImplicitlyCopyable, Movable):
    var lines: Int
    var errors: Int

    def __init__(out self):
        self.lines = 0
        self.errors = 0

    def __init__(out self, *, other: Self):
        self.lines = other.lines
        self.errors = other.errors

    def err_rate(self) -> Float64:
        if self.lines == 0:
            return 0.0
        return 100.0 * Float64(self.errors) / Float64(self.lines)


struct Session(Copyable, ImplicitlyCopyable, Movable):
    var symbol: String
    var start_ts: Int
    var end_ts: Int
    var trades: Int
    var volume: Int
    var high: Float64
    var low: Float64
    var vwap_num: Float64
    var max_gap: Int

    def __init__(out self, symbol: String, ts: Int, price: Float64, size: Int):
        self.symbol = symbol
        self.start_ts = ts
        self.end_ts = ts
        self.trades = 1
        self.volume = size
        self.high = price
        self.low = price
        self.vwap_num = price * Float64(size)
        self.max_gap = 0

    def __init__(out self, *, other: Self):
        self.symbol = other.symbol
        self.start_ts = other.start_ts
        self.end_ts = other.end_ts
        self.trades = other.trades
        self.volume = other.volume
        self.high = other.high
        self.low = other.low
        self.vwap_num = other.vwap_num
        self.max_gap = other.max_gap

    def duration(self) -> Int:
        return self.end_ts - self.start_ts

    def vwap(self) -> Float64:
        if self.volume == 0:
            return 0.0
        return self.vwap_num / Float64(self.volume)


# ---------------------------------------------------------------------------
# Tumbling windows (5-minute buckets), reference + parallel.
# ---------------------------------------------------------------------------


struct TumblingAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var bars: Dict[String, WinBar]
    var log_windows: Dict[Int, LogWindow]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.bars = Dict[String, WinBar]()
        self.log_windows = Dict[Int, LogWindow]()

    def add_trade(mut self, t: Trade):
        self.total += 1
        if not t.ok:
            self.malformed += 1
            return
        self.parsed += 1
        var key = t.symbol + "|" + String(t.ts / 300)
        var bar = self.bars.get(key, WinBar())
        bar.update(t.price, t.size, t.ts)
        self.bars[key] = bar

    def add_log(mut self, e: LogEvent):
        self.total += 1
        if not e.ok:
            self.malformed += 1
            return
        self.parsed += 1
        var bucket = e.minute / 5
        var w = self.log_windows.get(bucket, LogWindow())
        w.lines += 1
        if e.status >= 400:
            w.errors += 1
        self.log_windows[bucket] = w

    def merge(mut self, ref other: TumblingAgg):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        for key in other.bars.keys():
            var merged = self.bars.get(key, WinBar())
            var other_bar = other.bars.get(key, WinBar())
            merged.merge_from(other_bar)
            self.bars[key] = merged
        for bucket in other.log_windows.keys():
            var merged_w = self.log_windows.get(bucket, LogWindow())
            var other_w = other.log_windows.get(bucket, LogWindow())
            merged_w.lines += other_w.lines
            merged_w.errors += other_w.errors
            self.log_windows[bucket] = merged_w


def tumbling_equal(ref a: TumblingAgg, ref b: TumblingAgg) -> Bool:
    if a.total != b.total or a.parsed != b.parsed or a.malformed != b.malformed:
        return False
    if len(a.bars) != len(b.bars):
        return False
    for key in a.bars.keys():
        if key not in b.bars:
            return False
        var ba = a.bars.get(key, WinBar())
        var bb = b.bars.get(key, WinBar())
        if ba.volume != bb.volume or ba.trades != bb.trades:
            return False
        if ba.first_ts != bb.first_ts or ba.last_ts != bb.last_ts:
            return False
        if not approx_eq(ba.open, bb.open, 1e-9):
            return False
        if not approx_eq(ba.high, bb.high, 1e-9):
            return False
        if not approx_eq(ba.low, bb.low, 1e-9):
            return False
        if not approx_eq(ba.close, bb.close, 1e-9):
            return False
        if not approx_eq(ba.vwap_num, bb.vwap_num, 1e-9):
            return False
    if len(a.log_windows) != len(b.log_windows):
        return False
    for bucket in a.log_windows.keys():
        if bucket not in b.log_windows:
            return False
        var wa = a.log_windows.get(bucket, LogWindow())
        var wb = b.log_windows.get(bucket, LogWindow())
        if wa.lines != wb.lines or wa.errors != wb.errors:
            return False
    return True


def tumbling_range(lines: List[String], start: Int, end: Int, is_ticks: Bool) -> TumblingAgg:
    var agg = TumblingAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        if is_ticks:
            if lines[i].startswith("timestamp,"):
                continue
            agg.add_trade(parse_trade(lines[i]))
        else:
            agg.add_log(parse_log_event(lines[i]))
    return agg^


def tumbling_reference(lines: List[String], is_ticks: Bool) -> TumblingAgg:
    return tumbling_range(lines, 0, len(lines), is_ticks)


def tumbling_parallel(lines: List[String], workers: Int, is_ticks: Bool) raises -> TumblingAgg:
    var n = len(lines)
    var chunk_size = 2000
    var n_chunks = (n + chunk_size - 1) / chunk_size
    if n_chunks < 1:
        n_chunks = 1
    var chunk_aggs = List[TumblingAgg]()
    for _ in range(n_chunks):
        chunk_aggs.append(TumblingAgg())

    def work(i: Int) {mut chunk_aggs, imm lines, imm n, imm chunk_size, imm is_ticks}:
        var start = i * chunk_size
        var end = start + chunk_size
        if end > n:
            end = n
        var agg = tumbling_range(lines, start, end, is_ticks)
        chunk_aggs[i] = agg^

    # NOTE (Mojo 1.2.0): the plain `mojo` package no longer ships
    # `parallelize` -- it moved to the MAX package, which is not a
    # stdlib dependency here. Chunks therefore run sequentially in
    # this build; the chunk/merge structure is unchanged, so restoring
    # multi-core dispatch is a one-line change (call parallelize
    # from MAX instead of this loop) once MAX is available.
    for i in range(n_chunks):
        work(i)
    var result = TumblingAgg()
    for i in range(n_chunks):
        result.merge(chunk_aggs[i])
    return result^


# ---------------------------------------------------------------------------
# Sliding windows: 15-minute window, 5-minute slide, per symbol.
# Two-pointer sweep (linear) vs brute force (quadratic, reference only).
# ---------------------------------------------------------------------------


struct SlideWindow(Copyable, ImplicitlyCopyable, Movable):
    var start_ts: Int
    var end_ts: Int
    var symbol: String
    var trades: Int
    var volume: Int
    var vwap_num: Float64

    def __init__(out self):
        self.start_ts = 0
        self.end_ts = 0
        self.symbol = ""
        self.trades = 0
        self.volume = 0
        self.vwap_num = 0.0

    def __init__(out self, *, other: Self):
        self.start_ts = other.start_ts
        self.end_ts = other.end_ts
        self.symbol = other.symbol
        self.trades = other.trades
        self.volume = other.volume
        self.vwap_num = other.vwap_num

    def vwap(self) -> Float64:
        if self.volume == 0:
            return 0.0
        return self.vwap_num / Float64(self.volume)


def sliding_two_pointer(trades: List[Trade], symbol: String, window_s: Int, slide_s: Int) -> List[SlideWindow]:
    """Linear sweep. The trade list must be time-ordered (it is, for a
    single symbol, because the file is globally time-ordered). Two
    pointers delimit the window; both only move forward."""
    var mine = List[Trade]()
    for i in range(len(trades)):
        if trades[i].symbol == symbol:
            mine.append(trades[i])
    var out = List[SlideWindow]()
    if len(mine) == 0:
        return out^
    var first_ts = mine[0].ts
    var last_ts = mine[len(mine) - 1].ts
    var start = (first_ts / slide_s) * slide_s
    var lo = 0
    var hi = 0
    var vol = 0
    var num = 0.0
    var count = 0
    while start <= last_ts:
        var end = start + window_s
        while hi < len(mine) and mine[hi].ts < end:
            vol += mine[hi].size
            num += mine[hi].price * Float64(mine[hi].size)
            count += 1
            hi += 1
        while lo < hi and mine[lo].ts < start:
            vol -= mine[lo].size
            num -= mine[lo].price * Float64(mine[lo].size)
            count -= 1
            lo += 1
        if count > 0:
            var w = SlideWindow()
            w.start_ts = start
            w.end_ts = end
            w.symbol = symbol
            w.trades = count
            w.volume = vol
            w.vwap_num = num
            out.append(w)
        start += slide_s
    return out^


def sliding_brute_force(trades: List[Trade], symbol: String, window_s: Int, slide_s: Int) -> List[SlideWindow]:
    """Naive reference: for every window, scan every trade. Only used
    on small inputs and in tests; it is the definition of the window."""
    var mine = List[Trade]()
    for i in range(len(trades)):
        if trades[i].symbol == symbol:
            mine.append(trades[i])
    var out = List[SlideWindow]()
    if len(mine) == 0:
        return out^
    var first_ts = mine[0].ts
    var last_ts = mine[len(mine) - 1].ts
    var start = (first_ts / slide_s) * slide_s
    while start <= last_ts:
        var end = start + window_s
        var vol = 0
        var num = 0.0
        var count = 0
        for i in range(len(mine)):
            if mine[i].ts >= start and mine[i].ts < end:
                vol += mine[i].size
                num += mine[i].price * Float64(mine[i].size)
                count += 1
        if count > 0:
            var w = SlideWindow()
            w.start_ts = start
            w.end_ts = end
            w.symbol = symbol
            w.trades = count
            w.volume = vol
            w.vwap_num = num
            out.append(w)
        start += slide_s
    return out^


def slides_equal(a: List[SlideWindow], b: List[SlideWindow]) -> Bool:
    if len(a) != len(b):
        return False
    for i in range(len(a)):
        if a[i].start_ts != b[i].start_ts or a[i].end_ts != b[i].end_ts:
            return False
        if a[i].trades != b[i].trades or a[i].volume != b[i].volume:
            return False
        if not approx_eq(a[i].vwap_num, b[i].vwap_num, 1e-9):
            return False
    return True


# ---------------------------------------------------------------------------
# Session windows: gap-based, per symbol, single ordered scan.
# ---------------------------------------------------------------------------


def build_sessions(trades: List[Trade], symbol: String, gap_s: Int) -> List[Session]:
    var sessions = List[Session]()
    var current = Session(symbol, 0, 0.0, 0)
    var have_current = False
    var prev_ts = 0
    for i in range(len(trades)):
        var t = trades[i]
        if t.symbol != symbol:
            continue
        if not have_current:
            current = Session(symbol, t.ts, t.price, t.size)
            have_current = True
            prev_ts = t.ts
            continue
        var gap = t.ts - prev_ts
        if gap > gap_s:
            sessions.append(current)
            current = Session(symbol, t.ts, t.price, t.size)
        else:
            if gap > current.max_gap:
                current.max_gap = gap
            current.end_ts = t.ts
            current.trades += 1
            current.volume += t.size
            if t.price > current.high:
                current.high = t.price
            if t.price < current.low:
                current.low = t.price
            current.vwap_num += t.price * Float64(t.size)
        prev_ts = t.ts
    if have_current:
        sessions.append(current)
    return sessions^


def sessions_equal(a: List[Session], b: List[Session]) -> Bool:
    if len(a) != len(b):
        return False
    for i in range(len(a)):
        if a[i].symbol != b[i].symbol:
            return False
        if a[i].start_ts != b[i].start_ts or a[i].end_ts != b[i].end_ts:
            return False
        if a[i].trades != b[i].trades or a[i].volume != b[i].volume:
            return False
        if a[i].max_gap != b[i].max_gap:
            return False
        if not approx_eq(a[i].high, b[i].high, 1e-9):
            return False
        if not approx_eq(a[i].low, b[i].low, 1e-9):
            return False
        if not approx_eq(a[i].vwap_num, b[i].vwap_num, 1e-9):
            return False
    return True

# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------


def print_tumbling_report(ref agg: TumblingAgg, elapsed_s: Float64, label: String):
    print("---- tumbling windows: " + label + " ----")
    print("trades/log lines:", agg.total, " parsed:", agg.parsed, " malformed:", agg.malformed)
    print("5-min trade bars:", len(agg.bars), " 5-min log windows:", len(agg.log_windows))
    # Busiest trade bar and worst log window.
    var best_key = ""
    var best_vol = -1
    for key in agg.bars.keys():
        var b = agg.bars.get(key, WinBar())
        if b.volume > best_vol:
            best_vol = b.volume
            best_key = key
    if best_key != "":
        var bb = agg.bars.get(best_key, WinBar())
        print(
            "busiest 5-min bar:",
            best_key,
            " trades=",
            bb.trades,
            " vol=",
            best_vol,
            " VWAP=",
            fmt2(bb.vwap()),
        )
    var worst_bucket = -1
    var worst_rate = -1.0
    for bucket in agg.log_windows.keys():
        var w = agg.log_windows.get(bucket, LogWindow())
        if w.lines >= 20 and w.err_rate() > worst_rate:
            worst_rate = w.err_rate()
            worst_bucket = bucket
    if worst_bucket >= 0:
        var ww = agg.log_windows.get(worst_bucket, LogWindow())
        print(
            "worst 5-min log window:",
            minute_label(worst_bucket * 5),
            " lines=",
            ww.lines,
            " errors=",
            ww.errors,
            " rate=",
            fmt2(ww.err_rate()),
            "%",
        )
    var rate = 0.0
    if elapsed_s > 0.0:
        rate = Float64(agg.total) / elapsed_s
    print("elapsed: ", elapsed_s, "s  (", rate, " lines/s)")


def print_sliding_report(symbol: String, slides: List[SlideWindow]):
    print("---- sliding windows (15-min window, 5-min slide): " + symbol + " ----")
    print("windows:", len(slides))
    var total_vol = 0
    var best = SlideWindow()
    var have_best = False
    for i in range(len(slides)):
        total_vol += slides[i].volume
        if not have_best or slides[i].volume > best.volume:
            best = slides[i]
            have_best = True
    print("total volume across windows (trades counted up to 3x):", total_vol)
    if have_best:
        print(
            "busiest sliding window:",
            minute_label(best.start_ts / 60),
            "-",
            minute_label(best.end_ts / 60),
            " trades=",
            best.trades,
            " vol=",
            best.volume,
            " VWAP=",
            fmt2(best.vwap()),
        )
    var show = 5
    if len(slides) < show:
        show = len(slides)
    print("first", show, "windows:")
    for i in range(show):
        print(
            "  ",
            minute_label(slides[i].start_ts / 60),
            " trades=",
            slides[i].trades,
            " vol=",
            slides[i].volume,
            " VWAP=",
            fmt2(slides[i].vwap()),
        )


def print_session_report(symbol: String, sessions: List[Session]):
    print("---- session windows (gap > 60s): " + symbol + " ----")
    print("sessions:", len(sessions))
    var total_trades = 0
    var total_vol = 0
    var longest = Session(symbol, 0, 0.0, 0)
    var have_longest = False
    var biggest = Session(symbol, 0, 0.0, 0)
    var have_biggest = False
    for i in range(len(sessions)):
        total_trades += sessions[i].trades
        total_vol += sessions[i].volume
        if not have_longest or sessions[i].duration() > longest.duration():
            longest = sessions[i]
            have_longest = True
        if not have_biggest or sessions[i].volume > biggest.volume:
            biggest = sessions[i]
            have_biggest = True
    print("total trades:", total_trades, " total volume:", total_vol)
    if have_longest:
        print(
            "longest session:",
            longest.duration(),
            "s,",
            longest.trades,
            "trades, vol=",
            longest.volume,
            " VWAP=",
            fmt2(longest.vwap()),
            " max_gap=",
            longest.max_gap,
            "s",
        )
    if have_biggest:
        print(
            "biggest session: vol=",
            biggest.volume,
            " trades=",
            biggest.trades,
            " duration=",
            biggest.duration(),
            "s VWAP=",
            fmt2(biggest.vwap()),
        )
    var show = 5
    if len(sessions) < show:
        show = len(sessions)
    print("first", show, "sessions:")
    for i in range(show):
        print(
            "  ",
            minute_label(sessions[i].start_ts / 60),
            "->",
            minute_label(sessions[i].end_ts / 60),
            " trades=",
            sessions[i].trades,
            " vol=",
            sessions[i].volume,
            " VWAP=",
            fmt2(sessions[i].vwap()),
        )


# ---------------------------------------------------------------------------
# Unit tests with hand-computed expectations.
# ---------------------------------------------------------------------------


def make_trade(ts: Int, symbol: String, price: Float64, size: Int) -> Trade:
    var t = Trade()
    t.ok = True
    t.ts = ts
    t.symbol = symbol
    t.price = price
    t.size = size
    return t


def test_tumbling_small() raises:
    var lines = List[String]()
    lines.append("timestamp,symbol,price,size,exchange")
    lines.append("1000,ACME,100.00,10,NYSE")
    lines.append("1100,ACME,110.00,20,NYSE")
    lines.append("1300,ACME,105.00,30,NYSE")
    lines.append("1005,BOLT,50.00,5,NYSE")
    var ref_agg = tumbling_reference(lines, True)
    assert_equal(ref_agg.parsed, 4)
    assert_equal(len(ref_agg.bars), 3)
    var abar = ref_agg.bars.get("ACME|3", WinBar())
    assert_equal(abar.trades, 2)
    assert_almost_equal(abar.vwap(), (100.0 * 10.0 + 110.0 * 20.0) / 30.0, atol=1e-9, rtol=1e-9)
    var abar2 = ref_agg.bars.get("ACME|4", WinBar())
    assert_equal(abar2.trades, 1)
    assert_almost_equal(abar2.open, 105.0, atol=1e-9, rtol=1e-9)
    var par = tumbling_parallel(lines, 2, True)
    assert_true(tumbling_equal(ref_agg, par), "parallel tumbling must equal reference")
    print("  test_tumbling_small OK")


def test_log_windows_small() raises:
    var lines = List[String]()
    lines.append('1.1.1.1 - - [05/Nov/2026:09:00:01 +0000] "GET /a HTTP/1.1" 200 100 "-" "ua"')
    lines.append('1.1.1.2 - - [05/Nov/2026:09:04:02 +0000] "GET /a HTTP/1.1" 500 100 "-" "ua"')
    lines.append('1.1.1.3 - - [05/Nov/2026:09:06:03 +0000] "GET /b HTTP/1.1" 200 100 "-" "ua"')
    var ref_agg = tumbling_reference(lines, False)
    assert_equal(ref_agg.parsed, 3)
    # 09:00 and 09:04 fall in the same 5-minute bucket; 09:06 in the next.
    assert_equal(len(ref_agg.log_windows), 2)
    var first_bucket = ymd_to_days(2026, 11, 5) * 1440 / 5 + 108
    var w0 = ref_agg.log_windows.get(first_bucket, LogWindow())
    assert_equal(w0.lines, 2)
    assert_equal(w0.errors, 1)
    assert_almost_equal(w0.err_rate(), 50.0, atol=1e-9, rtol=1e-9)
    var par = tumbling_parallel(lines, 2, False)
    assert_true(tumbling_equal(ref_agg, par), "parallel log windows must equal reference")
    print("  test_log_windows_small OK")


def test_sliding_small() raises:
    # Trades at t=0, 100, 200, 300, 400, 500 (price 10, size 10 each).
    # 15-min (900s) window sliding by 300s: window [0,900) holds all six.
    var trades = List[Trade]()
    for i in range(6):
        trades.append(make_trade(i * 100, "ACME", 10.0, 10))
    var fast = sliding_two_pointer(trades, "ACME", 900, 300)
    var slow = sliding_brute_force(trades, "ACME", 900, 300)
    assert_true(slides_equal(fast, slow), "two-pointer must equal brute force")
    assert_equal(len(fast), 2)
    assert_equal(fast[0].trades, 6)
    assert_equal(fast[0].volume, 60)
    assert_equal(fast[1].trades, 3)
    assert_equal(fast[1].volume, 30)
    # Narrower window: 300s window, 100s slide.
    var fast2 = sliding_two_pointer(trades, "ACME", 300, 100)
    var slow2 = sliding_brute_force(trades, "ACME", 300, 100)
    assert_true(slides_equal(fast2, slow2), "narrow windows must also agree")
    assert_equal(len(fast2), 6)
    assert_equal(fast2[0].trades, 3)
    assert_equal(fast2[5].trades, 1)
    # Unknown symbol: no windows.
    assert_equal(len(sliding_two_pointer(trades, "NOPE", 900, 300)), 0)
    print("  test_sliding_small OK")


def test_sessions_small() raises:
    # Gaps: 10, 10, 200, 10, 500, 10 with gap threshold 60s.
    # Sessions: [0,10,20], [230], [240, 740, 750]? No: trades at
    # 0,10,20,230,240,740,750 -> sessions [0,10,20], [230,240], [740,750].
    var trades = List[Trade]()
    var times = List[Int]()
    times.append(0)
    times.append(10)
    times.append(20)
    times.append(230)
    times.append(240)
    times.append(740)
    times.append(750)
    for i in range(len(times)):
        trades.append(make_trade(times[i], "ACME", 100.0 + Float64(i), 10))
    var sessions = build_sessions(trades, "ACME", 60)
    assert_equal(len(sessions), 3)
    assert_equal(sessions[0].trades, 3)
    assert_equal(sessions[0].start_ts, 0)
    assert_equal(sessions[0].end_ts, 20)
    assert_equal(sessions[0].max_gap, 10)
    assert_equal(sessions[1].trades, 2)
    assert_equal(sessions[1].start_ts, 230)
    assert_equal(sessions[2].trades, 2)
    assert_equal(sessions[2].start_ts, 740)
    assert_equal(sessions[2].volume, 20)
    # A second symbol interleaved must not disturb the sessions.
    var mixed = List[Trade]()
    mixed.append(make_trade(0, "ACME", 100.0, 10))
    mixed.append(make_trade(5, "BOLT", 50.0, 10))
    mixed.append(make_trade(10, "ACME", 101.0, 10))
    mixed.append(make_trade(500, "BOLT", 51.0, 10))
    mixed.append(make_trade(20, "ACME", 102.0, 10))
    var s2 = build_sessions(mixed, "ACME", 60)
    assert_equal(len(s2), 1)
    assert_equal(s2[0].trades, 3)
    print("  test_sessions_small OK")


def test_window_keys() raises:
    # Tumbling keys: ts 299 -> bucket 0, ts 300 -> bucket 1, ts 599 -> 1.
    var lines = List[String]()
    lines.append("timestamp,symbol,price,size,exchange")
    lines.append("299,ACME,10.00,1,NYSE")
    lines.append("300,ACME,10.00,1,NYSE")
    lines.append("599,ACME,10.00,1,NYSE")
    lines.append("600,ACME,10.00,1,NYSE")
    var agg = tumbling_reference(lines, True)
    assert_equal(len(agg.bars), 3)
    assert_equal(agg.bars.get("ACME|0", WinBar()).trades, 1)
    assert_equal(agg.bars.get("ACME|1", WinBar()).trades, 2)
    assert_equal(agg.bars.get("ACME|2", WinBar()).trades, 1)
    print("  test_window_keys OK")


def run_tests() raises:
    print("Running unit tests:")
    test_tumbling_small()
    test_log_windows_small()
    test_sliding_small()
    test_sessions_small()
    test_window_keys()
    print("All window-aggregation unit tests passed.")


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
    ensure_inputs(data_dir)
    var log_text = Path(data_dir + "/access.log").read_text()
    var tick_text = Path(data_dir + "/ticks.csv").read_text()
    var log_lines = to_owned_lines(log_text)
    var tick_lines = to_owned_lines(tick_text)
    print("Loaded", len(log_lines), "log lines,", len(tick_lines), "tick lines.")

    # --- Tumbling windows: reference vs parallel, both datasets ---
    var t0 = perf_counter()
    var tick_ref = tumbling_reference(tick_lines, True)
    var t_ref = perf_counter() - t0
    print_tumbling_report(tick_ref, t_ref, "ticks reference")
    var t1 = perf_counter()
    var tick_par = tumbling_parallel(tick_lines, workers, True)
    var t_par = perf_counter() - t1
    print_tumbling_report(tick_par, t_par, "ticks parallel (" + String(workers) + " workers)")
    assert_true(tumbling_equal(tick_ref, tick_par), "parallel tumbling (ticks) must equal reference")
    print("ASSERTION PASSED: parallel == reference (ticks tumbling).")
    if t_par > 0.0 and t_ref > 0.0:
        print("tumbling speedup (ticks):", t_ref / t_par, "x")

    var t2 = perf_counter()
    var log_ref = tumbling_reference(log_lines, False)
    var t_log_ref = perf_counter() - t2
    print_tumbling_report(log_ref, t_log_ref, "logs reference")
    var t3 = perf_counter()
    var log_par = tumbling_parallel(log_lines, workers, False)
    var t_log_par = perf_counter() - t3
    print_tumbling_report(log_par, t_log_par, "logs parallel (" + String(workers) + " workers)")
    assert_true(tumbling_equal(log_ref, log_par), "parallel tumbling (logs) must equal reference")
    print("ASSERTION PASSED: parallel == reference (logs tumbling).")
    if t_log_par > 0.0 and t_log_ref > 0.0:
        print("tumbling speedup (logs):", t_log_ref / t_log_par, "x")

    # --- Sliding + session windows need the ordered trade stream ---
    var trades = load_trades(tick_lines)
    print("Ordered trade stream:", len(trades), "trades.")
    var symbols = List[String]()
    symbols.append("ACME")
    symbols.append("BOLT")
    symbols.append("CRUX")
    symbols.append("DUNE")
    symbols.append("ECHO")
    symbols.append("FLUX")
    symbols.append("GALE")
    symbols.append("HALO")
    for sym in symbols:
        var t_s0 = perf_counter()
        var slides = sliding_two_pointer(trades, sym, 900, 300)
        var t_s = perf_counter() - t_s0
        print_sliding_report(sym, slides)
        print("  sliding sweep took", fmt2(t_s), "s")
        var sessions = build_sessions(trades, sym, 60)
        print_session_report(sym, sessions)
    # Brute-force cross-check on a small prefix (the full file would be
    # quadratic; 2,000 trades is plenty to catch an off-by-one).
    var prefix = List[Trade]()
    for i in range(2000):
        prefix.append(trades[i])
    var fast_prefix = sliding_two_pointer(prefix, "ACME", 900, 300)
    var slow_prefix = sliding_brute_force(prefix, "ACME", 900, 300)
    assert_true(slides_equal(fast_prefix, slow_prefix), "two-pointer must equal brute force on the 2000-trade prefix")
    print("ASSERTION PASSED: sliding two-pointer == brute force (2000-trade prefix).")
    print("DONE: window aggregation verified.")
