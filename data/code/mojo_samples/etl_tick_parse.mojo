# etl_tick_parse.mojo
#
# Parallel market tick parser for the START project's Mojo ETL samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.)
# Requires Mojo 1.2.0.
#
# Input: tick CSV, one trade per line, header first:
#   timestamp,symbol,price,size,exchange
#   1793836802,ACME,143.55,367,NYSE
#
# The program builds, per symbol:
#   - OHLCV over the whole file (open = first trade's price, close = last
#     trade's price, high/low over all trades, volume = total shares)
#   - VWAP (volume-weighted average price)
#   - 5-minute OHLCV bars, keyed by a composite "SYMBOL|bucket" key
#   - trade-size statistics and the five largest trades
# and, per exchange, a trade count.
#
# As in the log parser, a single-threaded reference parse is compared
# exactly against a chunked parallel parse (map: per-chunk aggregates,
# reduce: merge). Integer fields must match exactly; floating-point
# fields (VWAP numerators) are compared with a 1e-9 relative tolerance,
# because parallel chunking changes the order of floating-point addition.
#
# Bars merge order-sensitively: a bar's open is the price of its earliest
# trade and its close the price of its latest trade, so merging compares
# first/last timestamps instead of blindly overwriting.
#
# Usage:
#   mojo etl_tick_parse.mojo [data-dir] [workers]
# Defaults: /tmp/etl_data, 4 workers. If ticks.csv is missing, a
# deterministic 100,000-trade file is generated in place first (same
# format and seed family as etl_gen_data.mojo).

from std.pathlib import Path
from std.testing import assert_equal, assert_true, assert_almost_equal
from std.collections import Dict
from std.random import seed, random_float64
from std.sys import argv
from std.time import perf_counter
from std.os import mkdir


# ---------------------------------------------------------------------------
# Byte-level number parsing over StringSlice (no per-field String
# allocation for the numeric columns).
# ---------------------------------------------------------------------------


def parse_int_slice(s: StringSlice) -> Tuple[Int, Bool]:
    var b = s.as_bytes()
    var i = 0
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
    return (v, any_digit)


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
    # Optional exponent: 1.5e3, 2E-2.
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


# ---------------------------------------------------------------------------
# One parsed trade, and one OHLCV bar.
# ---------------------------------------------------------------------------


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
            # Open/close are time-ordered, not arrival-ordered: an
            # out-of-order trade only moves open/close if it extends the
            # time range. Ties on the last timestamp go to the later
            # arrival (it is the later trade); ties on the first keep the
            # earlier arrival as the open.
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


def parse_tick_line(line: StringSlice) -> TickFields:
    """Parse `timestamp,symbol,price,size,exchange`. Never raises; bad
    lines yield ok == False."""
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


# ---------------------------------------------------------------------------
# Aggregates.
# ---------------------------------------------------------------------------

def bar_key(symbol: String, ts: Int) -> String:
    # 5-minute bars: 300 seconds per bucket.
    return symbol + "|" + String(ts / 300)


struct TickAgg(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var total_volume: Int
    var symbols: Dict[String, Bar]
    var bars: Dict[String, Bar]
    var exchanges: Dict[String, Int]
    var largest: List[Tuple[Int, String, Float64, Int]]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.total_volume = 0
        self.symbols = Dict[String, Bar]()
        self.bars = Dict[String, Bar]()
        self.exchanges = Dict[String, Int]()
        self.largest = List[Tuple[Int, String, Float64, Int]]()

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
        var key = bar_key(f.symbol, f.ts)
        var bar = self.bars.get(key, Bar())
        bar.update(f.price, f.size, f.ts)
        self.bars[key] = bar
        self.exchanges[f.exchange] = self.exchanges.get(f.exchange, 0) + 1
        # Keep the five largest trades, insertion-sorted by size.
        var entry = (f.size, f.symbol, f.price, f.ts)
        var inserted = False
        for j in range(len(self.largest)):
            if entry[0] > self.largest[j][0]:
                self.largest.insert(j, entry)
                inserted = True
                break
        if not inserted:
            self.largest.append(entry)
        if len(self.largest) > 5:
            _ = self.largest.pop()

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
        for entry in other.largest:
            var inserted = False
            for j in range(len(self.largest)):
                if entry[0] > self.largest[j][0]:
                    self.largest.insert(j, entry)
                    inserted = True
                    break
            if not inserted:
                self.largest.append(entry)
            if len(self.largest) > 5:
                _ = self.largest.pop()


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


def agg_equal(ref a: TickAgg, ref b: TickAgg) -> Bool:
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
    if len(a.largest) != len(b.largest):
        return False
    for i in range(len(a.largest)):
        if a.largest[i][0] != b.largest[i][0] or a.largest[i][1] != b.largest[i][1]:
            return False
        if not approx_eq(a.largest[i][2], b.largest[i][2], 1e-9):
            return False
        if a.largest[i][3] != b.largest[i][3]:
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


def parse_range(lines: List[String], start: Int, end: Int) -> TickAgg:
    var agg = TickAgg()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        if lines[i].startswith("timestamp,"):
            continue
        agg.add_tick(parse_tick_line(lines[i]))
    return agg^


def parse_reference(text: String) raises -> TickAgg:
    var lines = to_owned_lines(text)
    return parse_range(lines, 0, len(lines))


def parse_parallel(text: String, workers: Int) raises -> TickAgg:
    var lines = to_owned_lines(text)
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
    var result = TickAgg()
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


def print_report(ref agg: TickAgg, elapsed_s: Float64, label: String):
    print("---- " + label + " ----")
    print("lines total:    ", agg.total)
    print("trades parsed:  ", agg.parsed)
    print("lines malformed:", agg.malformed)
    print("total volume:   ", agg.total_volume, "shares")
    print("symbols:        ", len(agg.symbols), "  5-min bars:", len(agg.bars))
    var syms = List[String]()
    for sym in agg.symbols.keys():
        syms.append(sym)
    sort(syms)
    print("per-symbol OHLCV + VWAP:")
    for sym in syms:
        var bar = agg.symbols.get(sym, Bar())
        var avg_size = 0.0
        if bar.trades > 0:
            avg_size = Float64(bar.volume) / Float64(bar.trades)
        print(
            "  ",
            sym,
            " trades=",
            bar.trades,
            " vol=",
            bar.volume,
            " O=",
            fmt2(bar.open),
            " H=",
            fmt2(bar.high),
            " L=",
            fmt2(bar.low),
            " C=",
            fmt2(bar.close),
            " VWAP=",
            fmt2(bar.vwap()),
            " avg_size=",
            fmt2(avg_size),
        )
    print("per-exchange trades:")
    for ex in agg.exchanges.keys():
        print("  ", ex, ": ", agg.exchanges.get(ex, 0))
    print("five largest trades (size, symbol, price, ts):")
    for entry in agg.largest:
        print("  ", entry[0], " ", entry[1], " @ ", fmt2(entry[2]), " ts=", entry[3])
    # Busiest 5-minute bar overall.
    var best_key = ""
    var best_vol = -1
    for key in agg.bars.keys():
        var b = agg.bars.get(key, Bar())
        if b.volume > best_vol:
            best_vol = b.volume
            best_key = key
    if best_key != "":
        var bb = agg.bars.get(best_key, Bar())
        print(
            "busiest 5-min bar:",
            best_key,
            " vol=",
            best_vol,
            " trades=",
            bb.trades,
            " VWAP=",
            fmt2(bb.vwap()),
        )
    var rate = 0.0
    if elapsed_s > 0.0:
        rate = Float64(agg.total) / elapsed_s
    print("elapsed: ", elapsed_s, "s  (", rate, " lines/s)")


# ---------------------------------------------------------------------------
# Unit tests with hand-computed expectations.
# ---------------------------------------------------------------------------


def test_parse_numbers() raises:
    var pi = parse_int_slice(String("1793836802"))
    assert_equal(pi[0], 1793836802)
    assert_true(pi[1])
    var pf = parse_float_slice(String("143.55"))
    assert_true(pf[1])
    assert_almost_equal(pf[0], 143.55, atol=1e-9, rtol=1e-9)
    var pe = parse_float_slice(String("1.5e3"))
    assert_almost_equal(pe[0], 1500.0, atol=1e-9, rtol=1e-9)
    var pn = parse_float_slice(String("-2.5"))
    assert_almost_equal(pn[0], -2.5, atol=1e-9, rtol=1e-9)
    var bad = parse_int_slice(String("abc"))
    assert_true(not bad[1])
    print("  test_parse_numbers OK")


def test_parse_tick_lines() raises:
    var f = parse_tick_line(String("1793836802,ACME,143.55,367,NYSE"))
    assert_true(f.ok)
    assert_equal(f.ts, 1793836802)
    assert_equal(f.symbol, "ACME")
    assert_almost_equal(f.price, 143.55, atol=1e-9, rtol=1e-9)
    assert_equal(f.size, 367)
    assert_equal(f.exchange, "NYSE")
    assert_true(not parse_tick_line(String("")).ok)
    assert_true(not parse_tick_line(String("1,ACME,10.0,5")).ok)
    assert_true(not parse_tick_line(String("1,ACME,-10.0,5,NYSE")).ok)
    assert_true(not parse_tick_line(String("1,ACME,10.0,0,NYSE")).ok)
    assert_true(not parse_tick_line(String("1,ACME,xx,5,NYSE")).ok)
    assert_true(not parse_tick_line(String("0,ACME,10.0,5,NYSE")).ok)
    assert_true(not parse_tick_line(String("timestamp,symbol,price,size,exchange")).ok)
    print("  test_parse_tick_lines OK")


def test_ohlcv_small() raises:
    # Hand-computed: ACME trades 100, 110, 105 with sizes 10, 20, 30.
    # VWAP = (100*10 + 110*20 + 105*30) / 60 = 6350/60 = 105.8333...
    # BOLT trades 50, 45 with sizes 5, 15: VWAP = (250+675)/20 = 46.25.
    var text = String(
        "timestamp,symbol,price,size,exchange\n"
        + "1000,ACME,100.00,10,NYSE\n"
        + "1010,ACME,110.00,20,NYSE\n"
        + "1020,ACME,105.00,30,NASDAQ\n"
        + "1005,BOLT,50.00,5,NYSE\n"
        + "1015,BOLT,45.00,15,NYSE\n"
        + "bad,line,here\n"
    )
    var agg = parse_reference(text)
    assert_equal(agg.total, 6)
    assert_equal(agg.parsed, 5)
    assert_equal(agg.malformed, 1)
    assert_equal(agg.total_volume, 80)
    var acme = agg.symbols.get("ACME", Bar())
    assert_equal(acme.trades, 3)
    assert_equal(acme.volume, 60)
    assert_almost_equal(acme.open, 100.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(acme.high, 110.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(acme.low, 100.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(acme.close, 105.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(acme.vwap(), 6350.0 / 60.0, atol=1e-9, rtol=1e-9)
    var bolt = agg.symbols.get("BOLT", Bar())
    assert_equal(bolt.trades, 2)
    assert_almost_equal(bolt.vwap(), 46.25, atol=1e-9, rtol=1e-9)
    assert_equal(agg.exchanges.get("NYSE", 0), 4)
    assert_equal(agg.exchanges.get("NASDAQ", 0), 1)
    # 5-minute bars: ts 1000..1020 all fall in bucket 3 (900..1199),
    # so one bar per symbol.
    assert_equal(len(agg.bars), 2)
    var abar = agg.bars.get("ACME|3", Bar())
    assert_equal(abar.trades, 3)
    assert_almost_equal(abar.vwap(), 6350.0 / 60.0, atol=1e-9, rtol=1e-9)
    # Parallel must agree.
    var par = parse_parallel(text, 2)
    assert_true(agg_equal(agg, par), "parallel must equal reference on small input")
    print("  test_ohlcv_small OK")


def test_bars_split() raises:
    # Trades straddling a 5-minute boundary (bucket 3 vs bucket 4).
    var text = String(
        "timestamp,symbol,price,size,exchange\n"
        + "1199,ACME,100.00,10,NYSE\n"
        + "1200,ACME,102.00,10,NYSE\n"
        + "1499,ACME,101.00,10,NYSE\n"
        + "1500,ACME,103.00,10,NYSE\n"
    )
    var agg = parse_reference(text)
    assert_equal(len(agg.bars), 3)
    assert_equal(agg.bars.get("ACME|3", Bar()).trades, 1)
    assert_equal(agg.bars.get("ACME|4", Bar()).trades, 2)
    assert_equal(agg.bars.get("ACME|5", Bar()).trades, 1)
    assert_almost_equal(agg.bars.get("ACME|4", Bar()).close, 101.0, atol=1e-9, rtol=1e-9)
    var par = parse_parallel(text, 2)
    assert_true(agg_equal(agg, par), "parallel must equal reference across bar boundary")
    print("  test_bars_split OK")


def test_bar_merge_order() raises:
    # Out-of-order trades inside one bar: open is the earliest trade's
    # price, close the latest trade's price, regardless of file order.
    var b = Bar()
    b.update(110.0, 10, 1020)
    b.update(100.0, 10, 1000)
    b.update(105.0, 10, 1010)
    assert_almost_equal(b.open, 100.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(b.close, 110.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(b.high, 110.0, atol=1e-9, rtol=1e-9)
    assert_almost_equal(b.low, 100.0, atol=1e-9, rtol=1e-9)
    var c = Bar()
    c.update(108.0, 5, 1030)
    b.merge_from(c)
    assert_almost_equal(b.close, 108.0, atol=1e-9, rtol=1e-9)
    assert_equal(b.trades, 4)
    assert_equal(b.volume, 35)
    print("  test_bar_merge_order OK")


def run_tests() raises:
    print("Running unit tests:")
    test_parse_numbers()
    test_parse_tick_lines()
    test_ohlcv_small()
    test_bars_split()
    test_bar_merge_order()
    print("All tick-parser unit tests passed.")


# ---------------------------------------------------------------------------
# Embedded fallback generator (same format / seed family as etl_gen_data).
# ---------------------------------------------------------------------------


def gen_symbols() -> List[String]:
    var s = List[String]()
    s.append("ACME")
    s.append("BOLT")
    s.append("CRUX")
    s.append("DUNE")
    s.append("ECHO")
    s.append("FLUX")
    s.append("GALE")
    s.append("HALO")
    return s^


def gen_base(symbol: String) -> Float64:
    if symbol == "ACME":
        return 142.35
    if symbol == "BOLT":
        return 87.10
    if symbol == "CRUX":
        return 231.80
    if symbol == "DUNE":
        return 45.60
    if symbol == "ECHO":
        return 312.25
    if symbol == "FLUX":
        return 19.95
    if symbol == "GALE":
        return 178.40
    return 64.75


def ensure_input(data_dir: String) raises -> Path:
    var path = Path(data_dir + "/ticks.csv")
    if path.exists():
        return path
    print("ticks.csv not found in " + data_dir + "; generating 100,000 trades ...")
    if not Path(data_dir).exists():
        mkdir(data_dir)
    seed(20261106)
    var symbols = gen_symbols()
    var prices = List[Float64]()
    for sym in symbols:
        prices.append(gen_base(sym))
    var lines = List[String]()
    lines.append("timestamp,symbol,price,size,exchange")
    var ts = 1793836800
    for _ in range(100000):
        ts += Int(random_float64() * 3.0)
        var si = Int(random_float64() * Float64(len(symbols)))
        var sym = symbols[si]
        var price = prices[si] + (random_float64() - 0.5) * 0.02 * prices[si]
        if price < 1.0:
            price = 1.0 + random_float64() * 2.0
        prices[si] = price
        var size = 1 + Int(random_float64() * 500.0)
        var ex = "NYSE"
        if random_float64() < 0.5:
            ex = "NASDAQ"
        lines.append(
            String(ts)
            + ","
            + sym
            + ","
            + fmt2(price)
            + ","
            + String(size)
            + ","
            + ex
        )
    path.write_text(String("\n").join(lines) + "\n")
    print("  generated", path, "100,000 trades")
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
    print("DONE: tick parse verified.")
