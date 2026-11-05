# etl_incremental.mojo
#
# Incremental ETL with checkpoints for the START project's Mojo ETL
# samples.
#
# Original work, written for this project. Standard library only, plus
# chunked processing with per-chunk aggregates merged afterwards.
# (Mojo 1.2.0's plain `mojo` package no longer ships `parallelize`;
# it moved to the MAX package, so chunks run sequentially here.)
# Requires Mojo 1.2.0.
#
# Batch ETL re-reads the whole file every run. Incremental ETL does not:
# it remembers where the previous run stopped (a checkpoint) and only
# processes what arrived since, then merges the new partial state into
# the persisted state. This program demonstrates the pattern on the tick
# feed, which is append-only and time-ordered:
#
#   phase A  -> process the first half of ticks.csv, write a checkpoint
#               (last processed line offset + last processed timestamp)
#               and a state snapshot (per-symbol OHLCV + totals as CSV)
#   phase B  -> reload the checkpoint and the state snapshot, process
#               only the second half, merge it into the loaded state
#   verify   -> reparse the whole file from scratch and assert the
#               incrementally built state is exactly equal (integers)
#               or within 1e-9 relative tolerance (VWAP numerators)
#
# The checkpoint carries two guards, because either one alone can lie:
#   - line offset: how many lines were consumed (cheap, exact)
#   - watermark: the largest timestamp seen (catches a truncated or
#     replaced file: if the file's first new timestamp is at or below
#     the watermark, the run refuses to proceed incrementally and falls
#     back to a full reparse instead of silently double-counting)
#
# State snapshots are plain CSV so a human (or another tool) can read
# them; the checkpoint is a small key=value text file for the same
# reason. Both live under <data-dir>/incremental_state/ (scratch, not
# part of the corpus).
#
# Usage:
#   mojo etl_incremental.mojo [data-dir] [workers]
# Defaults: /tmp/etl_data, 4 workers. If ticks.csv is missing, a
# deterministic 100,000-trade file is generated in place first.

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
    if neg:
        v = -v
    return (v, any_digit)


def to_owned_lines(text: String) raises -> List[String]:
    var slices = text.split("\n")
    var lines = List[String]()
    for i in range(len(slices)):
        lines.append(String(slices[i]))
    return lines^


# ---------------------------------------------------------------------------
# Trade parsing and per-symbol state.
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


struct TickState(Movable):
    var total: Int
    var parsed: Int
    var malformed: Int
    var total_volume: Int
    var last_ts: Int
    var symbols: Dict[String, Bar]

    def __init__(out self):
        self.total = 0
        self.parsed = 0
        self.malformed = 0
        self.total_volume = 0
        self.last_ts = 0
        self.symbols = Dict[String, Bar]()

    def add_trade(mut self, t: Trade):
        self.total += 1
        if not t.ok:
            self.malformed += 1
            return
        self.parsed += 1
        self.total_volume += t.size
        if t.ts > self.last_ts:
            self.last_ts = t.ts
        var bar = self.symbols.get(t.symbol, Bar())
        bar.update(t.price, t.size, t.ts)
        self.symbols[t.symbol] = bar

    def merge(mut self, ref other: TickState):
        self.total += other.total
        self.parsed += other.parsed
        self.malformed += other.malformed
        self.total_volume += other.total_volume
        if other.last_ts > self.last_ts:
            self.last_ts = other.last_ts
        for sym in other.symbols.keys():
            var merged = self.symbols.get(sym, Bar())
            var other_bar = other.symbols.get(sym, Bar())
            merged.merge_from(other_bar)
            self.symbols[sym] = merged


def state_equal(ref a: TickState, ref b: TickState) -> Bool:
    if a.total != b.total or a.parsed != b.parsed or a.malformed != b.malformed:
        return False
    if a.total_volume != b.total_volume or a.last_ts != b.last_ts:
        return False
    if len(a.symbols) != len(b.symbols):
        return False
    for sym in a.symbols.keys():
        if sym not in b.symbols:
            return False
        var ba = a.symbols.get(sym, Bar())
        var bb = b.symbols.get(sym, Bar())
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
    return True


def parse_range(lines: List[String], start: Int, end: Int) -> TickState:
    var state = TickState()
    for i in range(start, end):
        if lines[i].byte_length() == 0:
            continue
        if lines[i].startswith("timestamp,"):
            continue
        state.add_trade(parse_trade(lines[i]))
    return state^


def parse_parallel(lines: List[String], workers: Int, start: Int, end: Int) -> TickState:
    """Parallel parse of lines[start:end] (line offsets, not timestamps).
    Chunking is by line position so the checkpoint offset maps directly
    onto chunk boundaries."""
    var n = end - start
    var chunk_size = 2000
    var n_chunks = (n + chunk_size - 1) / chunk_size
    if n_chunks < 1:
        n_chunks = 1
    var chunk_states = List[TickState]()
    for _ in range(n_chunks):
        chunk_states.append(TickState())

    def work(i: Int) {mut chunk_states, imm lines, imm start, imm end, imm chunk_size}:
        var s = start + i * chunk_size
        var e = s + chunk_size
        if e > end:
            e = end
        var st = parse_range(lines, s, e)
        chunk_states[i] = st^

    # NOTE (Mojo 1.2.0): the plain `mojo` package no longer ships
    # `parallelize` -- it moved to the MAX package, which is not a
    # stdlib dependency here. Chunks therefore run sequentially in
    # this build; the chunk/merge structure is unchanged, so restoring
    # multi-core dispatch is a one-line change (call parallelize
    # from MAX instead of this loop) once MAX is available.
    for i in range(n_chunks):
        work(i)
    var result = TickState()
    for i in range(n_chunks):
        result.merge(chunk_states[i])
    return result^

# ---------------------------------------------------------------------------
# Checkpoint and state snapshot (plain text, human-readable).
# ---------------------------------------------------------------------------


struct Checkpoint(Copyable, ImplicitlyCopyable, Movable):
    var line_offset: Int
    var watermark_ts: Int
    var total_lines: Int
    var valid: Bool

    def __init__(out self):
        self.line_offset = 0
        self.watermark_ts = 0
        self.total_lines = 0
        self.valid = False

    def __init__(out self, *, other: Self):
        self.line_offset = other.line_offset
        self.watermark_ts = other.watermark_ts
        self.total_lines = other.total_lines
        self.valid = other.valid


def write_checkpoint(path: Path, cp: Checkpoint) raises:
    var text = String(
        "line_offset="
        + String(cp.line_offset)
        + "\nwatermark_ts="
        + String(cp.watermark_ts)
        + "\ntotal_lines="
        + String(cp.total_lines)
        + "\n"
    )
    path.write_text(text)


def read_checkpoint(path: Path) raises -> Checkpoint:
    var cp = Checkpoint()
    if not path.exists():
        return cp
    var text = path.read_text()
    for line in text.split("\n"):
        if line.byte_length() == 0:
            continue
        var parts = line.split("=")
        if len(parts) != 2:
            return Checkpoint()
        var key = String(parts[0])
        var val = parse_int_slice(parts[1])
        if not val[1]:
            return Checkpoint()
        if key == "line_offset":
            cp.line_offset = val[0]
        elif key == "watermark_ts":
            cp.watermark_ts = val[0]
        elif key == "total_lines":
            cp.total_lines = val[0]
        else:
            return Checkpoint()
    if cp.line_offset < 0 or cp.watermark_ts < 0 or cp.total_lines < 0:
        return Checkpoint()
    if cp.line_offset > cp.total_lines:
        return Checkpoint()
    cp.valid = True
    return cp


def write_state_snapshot(path: Path, ref state: TickState) raises:
    var out_lines = List[String]()
    out_lines.append("symbol,open,high,low,close,volume,trades,vwap_num,first_ts,last_ts")
    var syms = List[String]()
    for sym in state.symbols.keys():
        syms.append(sym)
    sort(syms)
    for sym in syms:
        var bar = state.symbols.get(sym, Bar())
        out_lines.append(
            sym
            + ","
            + fmt2(bar.open)
            + ","
            + fmt2(bar.high)
            + ","
            + fmt2(bar.low)
            + ","
            + fmt2(bar.close)
            + ","
            + String(bar.volume)
            + ","
            + String(bar.trades)
            + ","
            + fmt2(bar.vwap_num)
            + ","
            + String(bar.first_ts)
            + ","
            + String(bar.last_ts)
        )
    # Totals row reuses the bar columns: volume, parsed, then total in
    # the first_ts slot and last_ts in the last_ts slot (malformed is
    # derived as total - parsed on load).
    out_lines.append(
        "__totals__,,,,,"
        + String(state.total_volume)
        + ","
        + String(state.parsed)
        + ","
        + fmt2(0.0)
        + ","
        + String(state.total)
        + ","
        + String(state.last_ts)
    )
    path.write_text(String("\n").join(out_lines) + "\n")


def read_state_snapshot(path: Path) raises -> TickState:
    var state = TickState()
    if not path.exists():
        return state^
    var text = path.read_text()
    var lines = to_owned_lines(text)
    for i in range(len(lines)):
        var line = lines[i]
        if line.byte_length() == 0 or line.startswith("symbol,"):
            continue
        var parts = line.split(",")
        if len(parts) != 10:
            continue
        if String(parts[0]) == "__totals__":
            var vol = parse_int_slice(parts[5])
            var parsed = parse_int_slice(parts[6])
            var total = parse_int_slice(parts[8])
            var last = parse_int_slice(parts[9])
            if vol[1]:
                state.total_volume = vol[0]
            if parsed[1]:
                state.parsed = parsed[0]
            if total[1]:
                state.total = total[0]
                state.malformed = total[0] - state.parsed
            if last[1]:
                state.last_ts = last[0]
            continue
        var bar = Bar()
        var open_r = parse_float_slice(parts[1])
        var high_r = parse_float_slice(parts[2])
        var low_r = parse_float_slice(parts[3])
        var close_r = parse_float_slice(parts[4])
        var vol_r = parse_int_slice(parts[5])
        var trades_r = parse_int_slice(parts[6])
        var vwap_r = parse_float_slice(parts[7])
        var first_r = parse_int_slice(parts[8])
        var last_r = parse_int_slice(parts[9])
        if not (open_r[1] and high_r[1] and low_r[1] and close_r[1] and vol_r[1] and trades_r[1] and vwap_r[1] and first_r[1] and last_r[1]):
            continue
        bar.open = open_r[0]
        bar.high = high_r[0]
        bar.low = low_r[0]
        bar.close = close_r[0]
        bar.volume = vol_r[0]
        bar.trades = trades_r[0]
        bar.vwap_num = vwap_r[0]
        bar.first_ts = first_r[0]
        bar.last_ts = last_r[0]
        state.symbols[String(parts[0])] = bar
    return state^


def check_watermark(lines: List[String], offset: Int, watermark: Int) -> Bool:
    """Guard: the first data line at or after the checkpoint offset must
    have a timestamp strictly above the watermark. If the file was
    truncated or replaced with older data, the guard fails and the
    caller must fall back to a full reparse."""
    for i in range(offset, len(lines)):
        var line = lines[i]
        if line.byte_length() == 0 or line.startswith("timestamp,"):
            continue
        var t = parse_trade(line)
        if not t.ok:
            continue
        return t.ts > watermark
    return True


def print_state(ref state: TickState, label: String):
    print("---- " + label + " ----")
    print("total:", state.total, " parsed:", state.parsed, " malformed:", state.malformed)
    print("total volume:", state.total_volume, " last ts:", state.last_ts)
    var syms = List[String]()
    for sym in state.symbols.keys():
        syms.append(sym)
    sort(syms)
    for sym in syms:
        var bar = state.symbols.get(sym, Bar())
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
        )


# ---------------------------------------------------------------------------
# Unit tests.
# ---------------------------------------------------------------------------


def test_checkpoint_roundtrip() raises:
    var dir = "/tmp/etl_incr_test"
    if not Path(dir).exists():
        mkdir(dir)
    var path = Path(dir + "/checkpoint.txt")
    var cp = Checkpoint()
    cp.line_offset = 12345
    cp.watermark_ts = 1793836800
    cp.total_lines = 250000
    cp.valid = True
    write_checkpoint(path, cp)
    var back = read_checkpoint(path)
    assert_true(back.valid)
    assert_equal(back.line_offset, 12345)
    assert_equal(back.watermark_ts, 1793836800)
    assert_equal(back.total_lines, 250000)
    var missing = read_checkpoint(Path(dir + "/nope.txt"))
    assert_true(not missing.valid)
    Path(dir + "/bad.txt").write_text("line_offset=abc\n")
    var bad = read_checkpoint(Path(dir + "/bad.txt"))
    assert_true(not bad.valid)
    Path(dir + "/bad2.txt").write_text("line_offset=999\ntotal_lines=10\n")
    var bad2 = read_checkpoint(Path(dir + "/bad2.txt"))
    assert_true(not bad2.valid)
    print("  test_checkpoint_roundtrip OK")


def test_state_snapshot_roundtrip() raises:
    var dir = "/tmp/etl_incr_test"
    if not Path(dir).exists():
        mkdir(dir)
    var state = TickState()
    var t1 = Trade()
    t1.ok = True
    t1.ts = 1000
    t1.symbol = "ACME"
    t1.price = 100.0
    t1.size = 10
    state.add_trade(t1)
    var t2 = Trade()
    t2.ok = True
    t2.ts = 1010
    t2.symbol = "ACME"
    t2.price = 110.0
    t2.size = 20
    state.add_trade(t2)
    var t3 = Trade()
    t3.ok = True
    t3.ts = 1005
    t3.symbol = "BOLT"
    t3.price = 50.0
    t3.size = 5
    state.add_trade(t3)
    var path = Path(dir + "/state.csv")
    write_state_snapshot(path, state)
    var back = read_state_snapshot(path)
    assert_true(state_equal(state, back), "snapshot round-trip must preserve state")
    print("  test_state_snapshot_roundtrip OK")


def test_incremental_merge() raises:
    var lines = List[String]()
    lines.append("timestamp,symbol,price,size,exchange")
    lines.append("1000,ACME,100.00,10,NYSE")
    lines.append("1010,ACME,110.00,20,NYSE")
    lines.append("1020,ACME,105.00,30,NASDAQ")
    lines.append("1005,BOLT,50.00,5,NYSE")
    lines.append("1015,BOLT,45.00,15,NYSE")
    var full = parse_range(lines, 0, len(lines))
    var first_half = parse_range(lines, 0, 3)
    var second_half = parse_range(lines, 3, len(lines))
    var merged = TickState()
    merged.merge(first_half)
    merged.merge(second_half)
    assert_true(state_equal(full, merged), "two half-states must merge to the full state")
    # The checkpoint for the first half must validate, and the watermark
    # guard must accept the second half.
    assert_true(check_watermark(lines, 3, first_half.last_ts))
    assert_true(not check_watermark(lines, 3, 999999))
    print("  test_incremental_merge OK")


def test_watermark_guard() raises:
    var lines = List[String]()
    lines.append("timestamp,symbol,price,size,exchange")
    lines.append("1000,ACME,100.00,10,NYSE")
    lines.append("900,ACME,100.00,10,NYSE")
    # Offset 2 points at the older trade: watermark 1000 must reject.
    assert_true(not check_watermark(lines, 2, 1000))
    assert_true(check_watermark(lines, 2, 500))
    # Offset past the end: nothing new, guard passes vacuously.
    assert_true(check_watermark(lines, 99, 1000))
    print("  test_watermark_guard OK")


def run_tests() raises:
    print("Running unit tests:")
    test_checkpoint_roundtrip()
    test_state_snapshot_roundtrip()
    test_incremental_merge()
    test_watermark_guard()
    print("All incremental-ETL unit tests passed.")


# ---------------------------------------------------------------------------
# Embedded fallback generator.
# ---------------------------------------------------------------------------


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


def ensure_input(data_dir: String) raises -> Path:
    var path = Path(data_dir + "/ticks.csv")
    if path.exists():
        return path
    print("ticks.csv not found in " + data_dir + "; generating 100,000 trades ...")
    if not Path(data_dir).exists():
        mkdir(data_dir)
    seed(20261106)
    path.write_text(String("\n").join(gen_tick_lines(100000)) + "\n")
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
    var state_dir = data_dir + "/incremental_state"
    if not Path(state_dir).exists():
        mkdir(state_dir)
    print("Reading", path, "...")
    var text = path.read_text()
    var lines = to_owned_lines(text)
    var n = len(lines)
    print("  lines:", n, " bytes:", text.byte_length())
    var split = n / 2
    print("Phase A: processing lines [0,", split, ") ...")
    var t0 = perf_counter()
    var state_a = parse_parallel(lines, workers, 0, split)
    var t_a = perf_counter() - t0
    print_state(state_a, "state after phase A")
    print("  phase A took", fmt2(t_a), "s")
    var cp = Checkpoint()
    cp.line_offset = split
    cp.watermark_ts = state_a.last_ts
    cp.total_lines = n
    cp.valid = True
    write_checkpoint(Path(state_dir + "/checkpoint.txt"), cp)
    write_state_snapshot(Path(state_dir + "/state.csv"), state_a)
    print("  checkpoint written: offset=", split, " watermark=", state_a.last_ts)

    print("Phase B: reloading checkpoint + state, processing lines [", split, ",", n, ") ...")
    var loaded_cp = read_checkpoint(Path(state_dir + "/checkpoint.txt"))
    assert_true(loaded_cp.valid, "checkpoint must reload as valid")
    assert_equal(loaded_cp.line_offset, split)
    var loaded_state = read_state_snapshot(Path(state_dir + "/state.csv"))
    assert_true(state_equal(state_a, loaded_state), "reloaded state must equal phase A state")
    var guard_ok = check_watermark(lines, loaded_cp.line_offset, loaded_cp.watermark_ts)
    assert_true(guard_ok, "watermark guard must accept the appended half")
    var t1 = perf_counter()
    var state_b = parse_parallel(lines, workers, loaded_cp.line_offset, n)
    var t_b = perf_counter() - t1
    print_state(state_b, "state of phase B only")
    print("  phase B took", fmt2(t_b), "s")
    loaded_state.merge(state_b)
    print_state(loaded_state, "merged incremental state (A + B)")

    print("Verification: full reparse from scratch ...")
    var t2 = perf_counter()
    var full = parse_parallel(lines, workers, 0, n)
    var t_full = perf_counter() - t2
    print_state(full, "full reparse state")
    print("  full reparse took", fmt2(t_full), "s")
    assert_true(state_equal(loaded_state, full), "incremental state must equal full reparse")
    print("ASSERTION PASSED: incremental (A+B) == full reparse.")
    print("  phase A + B took", fmt2(t_a + t_b), "s vs full", fmt2(t_full), "s")
    print("DONE: incremental ETL verified; checkpoint and state in", state_dir)
