# hft_backtester.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): a backtester that replays recorded ticks
# through a strategy and reports fills, PnL, and position over time.
#
# SIMULATOR ONLY. Every tick, bar, and price in this file is invented
# inside this program. Nothing here connects to an exchange, a broker, or
# any market-data vendor, and no real money is involved anywhere.
#
# Standard library only. No external packages, no Python interop, no network.
#
# What a backtester is for, and what it is not for:
#   A backtester answers one question: "if I had traded this exact set of
#   rules on this exact set of past prices, what would have happened?"
#   It is a research tool, not a promise. A strategy that made money in a
#   backtest has shown that its rules fit the past; it has not shown that
#   they will fit the future. Every honest backtester therefore documents
#   its assumptions, because the assumptions are where the optimism hides.
#
# The assumptions in this file (all explicit, all adjustable):
#   * Prices are integer ticks (1 tick = 1 cent); quantities are whole
#     units; cash is measured in ticks. No floating-point money.
#   * Ticks are aggregated into fixed-width bars (OHLCV) before the
#     strategy sees them. The strategy reads closes, never individual
#     ticks, so it cannot react inside a bar.
#   * No lookahead: a signal computed from bars up to and including bar i
#     is executed at the OPEN of bar i+1. The strategy never trades on a
#     price it could not have known yet. This is the single most common
#     backtesting bug, and this file is built so it cannot happen by
#     accident: execution always reads bars[i].open for a signal formed
#     at bar i-1.
#   * Fills happen at the bar open plus/minus slippage: buys pay open +
#     slippage, sells receive open - slippage. Slippage is the cost of
#     the market moving while the order travels, and of the order itself
#     moving the market. Zero slippage is a choice the caller makes
#     explicitly, never a default the reader might miss.
#   * A fixed commission is charged per fill. A flip (close one position
#     and open the opposite) is two fills and pays twice.
#   * One position at a time, in fixed size: long +Q, flat 0, or short
#     -Q. This keeps the PnL arithmetic hand-checkable, which is the
#     point of this file: every number in the tests is computed by hand
#     in the comments first.
#   * Equity is marked to the close of every bar: cash + position * close.
#     Max drawdown is the largest peak-to-trough fall of that equity
#     curve. The Sharpe ratio is the mean per-bar return divided by its
#     standard deviation (per-bar, not annualised; annualising would
#     require pretending 60-second bars are days).
#
# The strategies in this file:
#   * Momentum (SMA crossover): target +1 when the fast average is above
#     the slow average, -1 when below. It rides trends and loses money
#     in sideways chop -- the tests show both.
#   * Mean reversion (z-score): target +1 when the close is far BELOW its
#     recent mean (z <= -k), -1 when far ABOVE (z >= +k), and otherwise
#     hold the current target (hysteresis: the position only changes on
#     a fresh extreme, it does not flip on every wiggle).
#
# The hand-computed case (momentum, 14 bars, qty 10, no costs):
#   closes: 10000 10100 10200 10300 10200 10100 10000 9900 9800 9700
#           9800 9900 10000 10100.  Fast SMA(2), slow SMA(4).
#   Targets (bar index: target):
#     0-2: 0 (slow average not defined yet), 3: +1, 4: +1, 5: -1, 6: -1,
#     7: -1, 8: -1, 9: -1, 10: -1, 11: +1, 12: +1, 13: +1.
#   Execution at the next bar's open (open = previous close):
#     bar 4:  buy 10 @10300.  bar 6:  sell 10 @10100 (close long, -2000),
#     sell 10 @10100 (open short).  bar 12: buy 10 @9900 (close short,
#     +2000), buy 10 @9900 (open long). End: long 10, marked at 10100
#     (+2000 unrealised). Total PnL = -2000 + 2000 + 2000 = +2000.
#     Final equity = 1,002,000 on 1,000,000 starting cash. 5 fills,
#     2 round trips, 1 win. Max drawdown 2000 (peak 1,002,000 at bar 9
#     to trough 1,000,000 at bar 11; also 1,000,000 to 998,000 at bar 5).
#   With slippage 5 and commission 100 per fill the same run gives:
#     buy @10305, sell @10095 (long -2100 gross), sell @10095
#     (short open), buy @9905 (short close: a buy pays open +
#     slippage, so +1900 gross), buy @9905 (long open). Realised per
#     round trip net of both commissions: -2300 and +1700. Unrealised
#     +1950, minus the open fill's commission 100: total +1250,
#     final equity 1,001,250.
#
# The mean-reversion hand case (window 4, k = 1.0, qty 10, no costs):
#   closes: 10000 10100 9900 10000 9800 10200 9800 10000.
#   Targets: 0 0 0 0 +1 -1 -1 -1 (z at bar 4 is -1.34, at bar 5 +1.52).
#   Execution: bar 5: buy 10 @9800. bar 6: sell 20 @10200 (close long
#   +4000, open short). End: short 10, marked at 10000 (+2000).
#   Total PnL = +6000, final equity 1,006,000.

from std.testing import assert_equal, assert_true, assert_almost_equal
from std.math import sqrt
from std.random import seed, random_ui64

comptime SIDE_BUY = 0
comptime SIDE_SELL = 1


# ---------------------------------------------------------------------------
# Tick and Bar. A tick is one trade print; a bar is a fixed-width summary.
# ---------------------------------------------------------------------------

struct Tick:
    var ts: Int
    var price: Int
    var qty: Int

    def __init__(out self, ts: Int, price: Int, qty: Int):
        self.ts = ts
        self.price = price
        self.qty = qty


struct Bar:
    var start_ts: Int
    var open: Int
    var high: Int
    var low: Int
    var close: Int
    var volume: Int
    var n_ticks: Int

    def __init__(
        out self,
        start_ts: Int,
        open: Int,
        high: Int,
        low: Int,
        close: Int,
        volume: Int,
        n_ticks: Int,
    ):
        self.start_ts = start_ts
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.n_ticks = n_ticks

    def describe(self) -> String:
        return (
            String("bar@")
            + String(self.start_ts)
            + String(" O=")
            + String(self.open)
            + String(" H=")
            + String(self.high)
            + String(" L=")
            + String(self.low)
            + String(" C=")
            + String(self.close)
            + String(" V=")
            + String(self.volume)
        )


# ---------------------------------------------------------------------------
# BarBuilder: aggregates ticks into fixed-width bars. A tick belongs to
# the bar starting at (ts // width) * width. Bars are emitted in time
# order; finish() closes the last open bar.
# ---------------------------------------------------------------------------

struct BarBuilder:
    var width: Int
    var bars: List[Bar]
    var has_cur: Bool
    var cur_start: Int
    var cur_open: Int
    var cur_high: Int
    var cur_low: Int
    var cur_close: Int
    var cur_volume: Int
    var cur_n: Int

    def __init__(out self, width: Int):
        self.width = width
        self.bars = List[Bar]()
        self.has_cur = False
        self.cur_start = 0
        self.cur_open = 0
        self.cur_high = 0
        self.cur_low = 0
        self.cur_close = 0
        self.cur_volume = 0
        self.cur_n = 0

    def _close_cur(mut self):
        var b = Bar(
            self.cur_start,
            self.cur_open,
            self.cur_high,
            self.cur_low,
            self.cur_close,
            self.cur_volume,
            self.cur_n,
        )
        self.bars.append(b^)
        self.has_cur = False

    def add_tick(mut self, tick: Tick):
        var start = (tick.ts // self.width) * self.width
        if not self.has_cur:
            self.cur_start = start
            self.cur_open = tick.price
            self.cur_high = tick.price
            self.cur_low = tick.price
            self.cur_close = tick.price
            self.cur_volume = tick.qty
            self.cur_n = 1
            self.has_cur = True
            return
        if start != self.cur_start:
            self._close_cur()
            self.cur_start = start
            self.cur_open = tick.price
            self.cur_high = tick.price
            self.cur_low = tick.price
            self.cur_close = tick.price
            self.cur_volume = tick.qty
            self.cur_n = 1
            self.has_cur = True
            return
        if tick.price > self.cur_high:
            self.cur_high = tick.price
        if tick.price < self.cur_low:
            self.cur_low = tick.price
        self.cur_close = tick.price
        self.cur_volume += tick.qty
        self.cur_n += 1

    def finish(mut self):
        if self.has_cur:
            self._close_cur()

    def closes(self) -> List[Int]:
        var out = List[Int]()
        var i = 0
        while i < len(self.bars):
            out.append(self.bars[i].close)
            i += 1
        return out^


# ---------------------------------------------------------------------------
# RollingStats (Welford's algorithm): mean and variance in one pass,
# without storing the values. The classic test set [2,4,4,4,5,5,7,9]
# has mean 5, population variance 4, standard deviation 2.
# ---------------------------------------------------------------------------

struct RollingStats:
    var n: Int
    var mean: Float64
    var m2: Float64

    def __init__(out self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def add(mut self, x: Float64):
        self.n += 1
        var delta = x - self.mean
        self.mean += delta / Float64(self.n)
        var delta2 = x - self.mean
        self.m2 += delta * delta2

    def variance(self) -> Float64:
        if self.n == 0:
            return 0.0
        return self.m2 / Float64(self.n)

    def stddev(self) -> Float64:
        return sqrt(self.variance())


# ---------------------------------------------------------------------------
# Indicators. sma() and rolling_std() emit 0.0 until the window is full,
# so the output always lines up index-for-index with the input.
# ---------------------------------------------------------------------------

def sma(values: List[Float64], window: Int) -> List[Float64]:
    var out = List[Float64]()
    var running: Float64 = 0.0
    var i = 0
    while i < len(values):
        running += values[i]
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out.append(running / Float64(window))
        else:
            out.append(0.0)
        i += 1
    return out^


def rolling_std(values: List[Float64], window: Int) -> List[Float64]:
    var out = List[Float64]()
    var i = 0
    while i < len(values):
        if i < window - 1:
            out.append(0.0)
            i += 1
            continue
        var mean: Float64 = 0.0
        var j = i - window + 1
        while j <= i:
            mean += values[j]
            j += 1
        mean = mean / Float64(window)
        var acc: Float64 = 0.0
        var k = i - window + 1
        while k <= i:
            var diff = values[k] - mean
            acc += diff * diff
            k += 1
        out.append(sqrt(acc / Float64(window)))
        i += 1
    return out^


def closes_as_float(bars: List[Bar]) -> List[Float64]:
    var out = List[Float64]()
    var i = 0
    while i < len(bars):
        out.append(Float64(bars[i].close))
        i += 1
    return out^


def closes_as_int(bars: List[Bar]) -> List[Int]:
    var out = List[Int]()
    var i = 0
    while i < len(bars):
        out.append(bars[i].close)
        i += 1
    return out^


# ---------------------------------------------------------------------------
# Strategies. Each returns a target position per bar: +1 long, -1 short,
# 0 flat. Targets are computed from closes only.
# ---------------------------------------------------------------------------

def momentum_targets(closes: List[Int], fast: Int, slow: Int) -> List[Int]:
    var out = List[Int]()
    var i = 0
    while i < len(closes):
        if i < slow - 1:
            out.append(0)
            i += 1
            continue
        var fast_sum = 0
        var j = i - fast + 1
        while j <= i:
            fast_sum += closes[j]
            j += 1
        var slow_sum = 0
        var k = i - slow + 1
        while k <= i:
            slow_sum += closes[k]
            k += 1
        # Compare fast_sum/fast with slow_sum/slow without floats:
        # fast_sum * slow > slow_sum * fast  <=>  fast avg > slow avg.
        if fast_sum * slow > slow_sum * fast:
            out.append(1)
        else:
            out.append(-1)
        i += 1
    return out^


def mean_reversion_targets(closes: List[Int], window: Int, k: Float64) -> List[Int]:
    var out = List[Int]()
    var current = 0
    var i = 0
    while i < len(closes):
        if i < window - 1:
            out.append(0)
            i += 1
            continue
        var mean: Float64 = 0.0
        var j = i - window + 1
        while j <= i:
            mean += Float64(closes[j])
            j += 1
        mean = mean / Float64(window)
        var acc: Float64 = 0.0
        var m = i - window + 1
        while m <= i:
            var diff = Float64(closes[m]) - mean
            acc += diff * diff
            m += 1
        var std = sqrt(acc / Float64(window))
        var z: Float64 = 0.0
        if std > 0.0:
            z = (Float64(closes[i]) - mean) / std
        if z <= -k:
            current = 1
        elif z >= k:
            current = -1
        out.append(current)
        i += 1
    return out^


# ---------------------------------------------------------------------------
# Metrics on an equity curve.
# ---------------------------------------------------------------------------

def max_drawdown(equity: List[Float64]) -> Float64:
    if len(equity) == 0:
        return 0.0
    var peak = equity[0]
    var worst: Float64 = 0.0
    var i = 0
    while i < len(equity):
        if equity[i] > peak:
            peak = equity[i]
        var dd = peak - equity[i]
        if dd > worst:
            worst = dd
        i += 1
    return worst


def sharpe_ratio(equity: List[Float64]) -> Float64:
    if len(equity) < 2:
        return 0.0
    var stats = RollingStats()
    var i = 1
    while i < len(equity):
        if equity[i - 1] != 0.0:
            var r = equity[i] / equity[i - 1] - 1.0
            stats.add(r)
        i += 1
    var std = stats.stddev()
    if std == 0.0:
        return 0.0
    return stats.mean / std

# ---------------------------------------------------------------------------
# Fill and BacktestResult.
# ---------------------------------------------------------------------------

struct Fill:
    var bar_idx: Int
    var side: Int
    var price: Int
    var qty: Int
    var commission: Int

    def __init__(out self, bar_idx: Int, side: Int, price: Int, qty: Int, commission: Int):
        self.bar_idx = bar_idx
        self.side = side
        self.price = price
        self.qty = qty
        self.commission = commission

    def describe(self) -> String:
        var side_s = String("SELL")
        if self.side == SIDE_BUY:
            side_s = String("BUY ")
        return (
            String("bar ")
            + String(self.bar_idx)
            + String(" ")
            + side_s
            + String(" px=")
            + String(self.price)
            + String(" qty=")
            + String(self.qty)
        )


struct BacktestResult:
    var final_equity: Int
    var total_pnl: Int
    var n_fills: Int
    var n_round_trips: Int
    var n_wins: Int
    var max_drawdown: Int
    var sharpe: Float64
    var equity: List[Float64]
    var fills: List[Fill]

    def __init__(
        out self,
        final_equity: Int,
        total_pnl: Int,
        n_fills: Int,
        n_round_trips: Int,
        n_wins: Int,
        max_drawdown: Int,
        sharpe: Float64,
        var equity: List[Float64],
        var fills: List[Fill],
    ):
        self.final_equity = final_equity
        self.total_pnl = total_pnl
        self.n_fills = n_fills
        self.n_round_trips = n_round_trips
        self.n_wins = n_wins
        self.max_drawdown = max_drawdown
        self.sharpe = sharpe
        self.equity = equity^
        self.fills = fills^

    def win_rate(self) -> Float64:
        if self.n_round_trips == 0:
            return 0.0
        return Float64(self.n_wins) / Float64(self.n_round_trips)

    def describe(self) -> String:
        var s = String("backtest: final_equity=") + String(self.final_equity)
        s = s + String(" pnl=") + String(self.total_pnl)
        s = s + String(" fills=") + String(self.n_fills)
        s = s + String(" round_trips=") + String(self.n_round_trips)
        s = s + String(" wins=") + String(self.n_wins)
        s = s + String(" win_rate=") + String(self.win_rate())
        s = s + String(" max_dd=") + String(self.max_drawdown)
        s = s + String(" sharpe=") + String(self.sharpe)
        return s


# ---------------------------------------------------------------------------
# run_backtest: replay bars through a target-position series.
#
# The signal formed at bar i-1 trades at the open of bar i. A flip is
# two fills (close, then open). Commission is charged per fill from
# cash. Round-trip PnL nets both commissions of the trip; the equity
# curve nets every commission automatically because cash carries them.
# ---------------------------------------------------------------------------

def run_backtest(
    bars: List[Bar],
    targets: List[Int],
    qty_per_trade: Int,
    slippage: Int,
    commission: Int,
    initial_cash: Int,
) raises -> BacktestResult:
    return run_backtest_range(
        bars, targets, 0, len(bars), qty_per_trade, slippage, commission, initial_cash
    )


def run_backtest_range(
    bars: List[Bar],
    targets: List[Int],
    start: Int,
    end: Int,
    qty_per_trade: Int,
    slippage: Int,
    commission: Int,
    initial_cash: Int,
) raises -> BacktestResult:
    assert_equal(len(targets), len(bars))
    assert_true(start >= 0)
    assert_true(end <= len(bars))
    assert_true(start < end)
    var position = 0
    var cash = initial_cash
    var entry_price = 0
    var realized = 0
    var n_fills = 0
    var n_round_trips = 0
    var n_wins = 0
    var equity = List[Float64]()
    var fills = List[Fill]()
    var i = start
    while i < end:
        if i > start:
            var target = targets[i - 1] * qty_per_trade
            if target != position:
                if position != 0:
                    # Close the current position first.
                    var exit_px: Int
                    var close_side: Int
                    if position > 0:
                        exit_px = bars[i].open - slippage
                        close_side = SIDE_SELL
                    else:
                        exit_px = bars[i].open + slippage
                        close_side = SIDE_BUY
                    var close_qty = -position
                    cash -= exit_px * close_qty
                    cash -= commission
                    var pnl = (exit_px - entry_price) * position - 2 * commission
                    realized += pnl
                    n_round_trips += 1
                    if pnl > 0:
                        n_wins += 1
                    var q = position
                    if q < 0:
                        q = -q
                    fills.append(Fill(i, close_side, exit_px, q, commission))
                    n_fills += 1
                    position = 0
                if target != 0:
                    # Open the new position.
                    var entry_px: Int
                    var open_side: Int
                    if target > 0:
                        entry_px = bars[i].open + slippage
                        open_side = SIDE_BUY
                    else:
                        entry_px = bars[i].open - slippage
                        open_side = SIDE_SELL
                    cash -= entry_px * target
                    cash -= commission
                    entry_price = entry_px
                    position = target
                    var q = target
                    if q < 0:
                        q = -q
                    fills.append(Fill(i, open_side, entry_px, q, commission))
                    n_fills += 1
        var eq = Float64(cash + position * bars[i].close)
        equity.append(eq)
        i += 1
    var final_equity = Int(equity[len(equity) - 1])
    var total_pnl = final_equity - initial_cash
    var dd = Int(max_drawdown(equity))
    var sh = sharpe_ratio(equity)
    var result = BacktestResult(
        final_equity, total_pnl, n_fills, n_round_trips, n_wins, dd, sh, equity^, fills^
    )
    return result^


# ---------------------------------------------------------------------------
# Test helpers.
# ---------------------------------------------------------------------------

def bars_from_closes(closes: List[Int]) -> List[Bar]:
    var bars = List[Bar]()
    var prev = closes[0]
    var i = 0
    while i < len(closes):
        var open = prev
        var close = closes[i]
        var high = open
        if close > high:
            high = close
        var low = open
        if close < low:
            low = close
        bars.append(Bar(i * 60, open, high, low, close, 1, 1))
        prev = close
        i += 1
    return bars^


def closes_14() -> List[Int]:
    var c = List[Int]()
    c.append(10000)
    c.append(10100)
    c.append(10200)
    c.append(10300)
    c.append(10200)
    c.append(10100)
    c.append(10000)
    c.append(9900)
    c.append(9800)
    c.append(9700)
    c.append(9800)
    c.append(9900)
    c.append(10000)
    c.append(10100)
    return c^


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------

def test_bar_builder() raises:
    var bb = BarBuilder(60)
    var i = 0
    while i < 14:
        bb.add_tick(Tick(i * 10, 10000 + i * 10, 1))
        i += 1
    bb.finish()
    assert_equal(len(bb.bars), 3)
    assert_equal(bb.bars[0].open, 10000)
    assert_equal(bb.bars[0].high, 10050)
    assert_equal(bb.bars[0].low, 10000)
    assert_equal(bb.bars[0].close, 10050)
    assert_equal(bb.bars[0].volume, 6)
    assert_equal(bb.bars[0].n_ticks, 6)
    assert_equal(bb.bars[1].open, 10060)
    assert_equal(bb.bars[1].high, 10110)
    assert_equal(bb.bars[1].low, 10060)
    assert_equal(bb.bars[1].close, 10110)
    assert_equal(bb.bars[1].volume, 6)
    assert_equal(bb.bars[2].open, 10120)
    assert_equal(bb.bars[2].high, 10130)
    assert_equal(bb.bars[2].low, 10120)
    assert_equal(bb.bars[2].close, 10130)
    assert_equal(bb.bars[2].volume, 2)
    assert_equal(bb.bars[2].n_ticks, 2)
    print("bar builder ok: 14 ticks -> 3 bars, OHLCV exact")


def test_welford() raises:
    var st = RollingStats()
    var vals = List[Float64]()
    vals.append(2.0)
    vals.append(4.0)
    vals.append(4.0)
    vals.append(4.0)
    vals.append(5.0)
    vals.append(5.0)
    vals.append(7.0)
    vals.append(9.0)
    var i = 0
    while i < len(vals):
        st.add(vals[i])
        i += 1
    assert_equal(st.n, 8)
    assert_almost_equal(st.mean, 5.0, atol=1e-12)
    assert_almost_equal(st.variance(), 4.0, atol=1e-12)
    assert_almost_equal(st.stddev(), 2.0, atol=1e-12)
    print("welford ok: classic set gives mean 5, variance 4, stddev 2")


def test_sma_and_rolling_std() raises:
    var vals = List[Float64]()
    vals.append(1.0)
    vals.append(2.0)
    vals.append(3.0)
    vals.append(4.0)
    vals.append(5.0)
    var s = sma(vals, 3)
    assert_equal(len(s), 5)
    assert_almost_equal(s[0], 0.0, atol=1e-12)
    assert_almost_equal(s[1], 0.0, atol=1e-12)
    assert_almost_equal(s[2], 2.0, atol=1e-12)
    assert_almost_equal(s[3], 3.0, atol=1e-12)
    assert_almost_equal(s[4], 4.0, atol=1e-12)
    var r = rolling_std(vals, 3)
    assert_almost_equal(r[2], 0.816496580927726, atol=1e-9)
    assert_almost_equal(r[3], 0.816496580927726, atol=1e-9)
    assert_almost_equal(r[4], 0.816496580927726, atol=1e-9)
    print("sma/std ok: windowed values exact")


def test_momentum_targets() raises:
    var closes = closes_14()
    var t = momentum_targets(closes, 2, 4)
    var expected = List[Int]()
    expected.append(0)
    expected.append(0)
    expected.append(0)
    expected.append(1)
    expected.append(1)
    expected.append(-1)
    expected.append(-1)
    expected.append(-1)
    expected.append(-1)
    expected.append(-1)
    expected.append(-1)
    expected.append(1)
    expected.append(1)
    expected.append(1)
    assert_equal(len(t), 14)
    var i = 0
    while i < 14:
        assert_equal(t[i], expected[i])
        i += 1
    print("momentum targets ok: hand-computed crossover sequence")


def test_mean_reversion_targets() raises:
    var closes = List[Int]()
    closes.append(10000)
    closes.append(10100)
    closes.append(9900)
    closes.append(10000)
    closes.append(9800)
    closes.append(10200)
    closes.append(9800)
    closes.append(10000)
    var t = mean_reversion_targets(closes, 4, 1.0)
    assert_equal(len(t), 8)
    assert_equal(t[0], 0)
    assert_equal(t[1], 0)
    assert_equal(t[2], 0)
    assert_equal(t[3], 0)
    assert_equal(t[4], 1)
    assert_equal(t[5], -1)
    assert_equal(t[6], -1)
    assert_equal(t[7], -1)
    print("mean-reversion targets ok: z=-1.34 longs, z=+1.52 shorts")


def test_backtest_momentum_hand() raises:
    var closes = closes_14()
    var bars = bars_from_closes(closes)
    var targets = momentum_targets(closes, 2, 4)
    var res = run_backtest(bars, targets, 10, 0, 0, 1_000_000)
    assert_equal(res.final_equity, 1_002_000)
    assert_equal(res.total_pnl, 2000)
    assert_equal(res.n_fills, 5)
    assert_equal(res.n_round_trips, 2)
    assert_equal(res.n_wins, 1)
    assert_almost_equal(res.win_rate(), 0.5, atol=1e-12)
    assert_equal(res.max_drawdown, 2000)
    assert_equal(len(res.equity), 14)
    assert_almost_equal(res.equity[4], 999000.0, atol=1e-9)
    assert_almost_equal(res.equity[5], 998000.0, atol=1e-9)
    assert_almost_equal(res.equity[9], 1002000.0, atol=1e-9)
    assert_almost_equal(res.equity[13], 1002000.0, atol=1e-9)
    assert_equal(res.fills[0].price, 10300)
    assert_equal(res.fills[0].side, SIDE_BUY)
    assert_equal(res.fills[1].price, 10100)
    assert_equal(res.fills[1].side, SIDE_SELL)
    assert_equal(res.fills[2].price, 10100)
    assert_equal(res.fills[2].side, SIDE_SELL)
    assert_equal(res.fills[3].price, 9900)
    assert_equal(res.fills[3].side, SIDE_BUY)
    assert_equal(res.fills[4].price, 9900)
    assert_equal(res.fills[4].side, SIDE_BUY)
    print("backtest momentum ok: PnL +2000, 5 fills, equity curve exact")
    print("  " + res.describe())


def test_backtest_with_costs() raises:
    var closes = closes_14()
    var bars = bars_from_closes(closes)
    var targets = momentum_targets(closes, 2, 4)
    var res = run_backtest(bars, targets, 10, 5, 100, 1_000_000)
    assert_equal(res.final_equity, 1_001_250)
    assert_equal(res.total_pnl, 1250)
    assert_equal(res.n_fills, 5)
    assert_equal(res.n_round_trips, 2)
    assert_equal(res.n_wins, 1)
    assert_equal(res.fills[0].price, 10305)
    assert_equal(res.fills[1].price, 10095)
    assert_equal(res.fills[3].price, 9905)
    print("backtest with costs ok: slippage 5 + commission 100 -> PnL +1250")


def test_backtest_mean_reversion_hand() raises:
    var closes = List[Int]()
    closes.append(10000)
    closes.append(10100)
    closes.append(9900)
    closes.append(10000)
    closes.append(9800)
    closes.append(10200)
    closes.append(9800)
    closes.append(10000)
    var bars = bars_from_closes(closes)
    var targets = mean_reversion_targets(closes, 4, 1.0)
    var res = run_backtest(bars, targets, 10, 0, 0, 1_000_000)
    assert_equal(res.final_equity, 1_006_000)
    assert_equal(res.total_pnl, 6000)
    assert_equal(res.n_fills, 3)
    assert_equal(res.n_round_trips, 1)
    assert_equal(res.n_wins, 1)
    assert_equal(res.fills[0].price, 9800)
    assert_equal(res.fills[1].price, 10200)
    assert_equal(res.fills[2].price, 10200)
    print("backtest mean-reversion ok: PnL +6000, 3 fills")


def test_metrics_known() raises:
    var eq = List[Float64]()
    eq.append(100.0)
    eq.append(110.0)
    eq.append(105.0)
    eq.append(120.0)
    eq.append(90.0)
    eq.append(100.0)
    assert_almost_equal(max_drawdown(eq), 30.0, atol=1e-12)
    var eq2 = List[Float64]()
    eq2.append(100.0)
    eq2.append(101.0)
    eq2.append(103.02)
    eq2.append(106.1106)
    # Returns 0.01, 0.02, 0.03: mean 0.02, std 0.00816497, ratio 2.44949.
    assert_almost_equal(sharpe_ratio(eq2), 2.449489742783178, atol=1e-6)
    var flat = List[Float64]()
    flat.append(100.0)
    flat.append(100.0)
    flat.append(100.0)
    assert_almost_equal(max_drawdown(flat), 0.0, atol=1e-12)
    assert_almost_equal(sharpe_ratio(flat), 0.0, atol=1e-12)
    print("metrics ok: drawdown 30, sharpe 2.449 on known series")


def test_flat_market() raises:
    var closes = List[Int]()
    var i = 0
    while i < 10:
        closes.append(10000)
        i += 1
    var bars = bars_from_closes(closes)
    var targets = momentum_targets(closes, 2, 4)
    var res = run_backtest(bars, targets, 10, 0, 0, 1_000_000)
    assert_equal(res.final_equity, 1_000_000)
    assert_equal(res.total_pnl, 0)
    print("flat market ok: no movement, no PnL")


# ---------------------------------------------------------------------------
# Demo: a 500-bar synthetic series through both strategies.
# ---------------------------------------------------------------------------

def generate_bars(n: Int) -> List[Bar]:
    seed(99)
    var bars = List[Bar]()
    var prev = 10000
    var i = 0
    while i < n:
        var step = Int(random_ui64(0, 100)) - 50
        var cycle = ((i % 20) - 10) * 3
        var close = prev + step * 2 + cycle
        if close < 9000:
            close = 9000 + Int(random_ui64(0, 50))
        var high = prev
        if close > high:
            high = close
        var low = prev
        if close < low:
            low = close
        bars.append(Bar(i * 60, prev, high, low, close, 100 + (i % 50), 12))
        prev = close
        i += 1
    return bars^


def demo() raises:
    print("=== HFT backtester demo (simulated data, no real market) ===")
    var bars = generate_bars(500)
    print("generated", len(bars), "bars")
    var closes = closes_as_int(bars)
    var mom = momentum_targets(closes, 5, 20)
    var res_mom = run_backtest(bars, mom, 10, 2, 50, 1_000_000)
    print("momentum SMA(5,20), qty 10, slip 2, comm 50:")
    print("  " + res_mom.describe())
    var mr = mean_reversion_targets(closes, 20, 1.5)
    var res_mr = run_backtest(bars, mr, 10, 2, 50, 1_000_000)
    print("mean-reversion window 20, k=1.5, qty 10, slip 2, comm 50:")
    print("  " + res_mr.describe())
    var first = res_mom.equity[0]
    var last = res_mom.equity[len(res_mom.equity) - 1]
    print("momentum equity first/last:", first, last)
    var fasts = List[Int]()
    fasts.append(2)
    fasts.append(3)
    fasts.append(5)
    var slows = List[Int]()
    slows.append(10)
    slows.append(20)
    slows.append(30)
    var wf = walk_forward(bars, closes, 300, 200, 10, 2, 50, 1_000_000, fasts, slows)
    print("walk-forward (train 300 bars, test 200 bars):")
    print("  " + wf.describe())


def main() raises:
    demo()
    print("=== backtester tests ===")
    test_bar_builder()
    test_welford()
    test_sma_and_rolling_std()
    test_momentum_targets()
    test_mean_reversion_targets()
    test_backtest_momentum_hand()
    test_backtest_with_costs()
    test_backtest_mean_reversion_hand()
    test_metrics_known()
    test_flat_market()
    test_walk_forward_small()
    test_walk_forward_500()
    print("ALL BACKTESTER TESTS PASSED")

# ---------------------------------------------------------------------------
# Walk-forward validation: the antidote to overfitting a backtest.
#
# Picking strategy parameters by running them on the same data you then
# report performance on is circular: with enough parameter combinations,
# one of them will always look good by luck. Walk-forward breaks the
# circle. The series is split into a training window and a later test
# window. Parameters are chosen using ONLY the training window (a grid
# search over fast/slow SMA lengths), and the winner is then evaluated
# ONCE on the test window, starting flat with fresh cash. The test
# number is the honest one; the gap between train and test PnL is the
# overfitting gap. A strategy whose test PnL collapses relative to its
# train PnL was fit to noise, not to signal -- and this file says so
# instead of hiding it.
#
# Each window starts flat (no position carried across the boundary),
# because the question is "what would this parameter set have done on
# unseen data", not "what would the training position have earned".
# ---------------------------------------------------------------------------

struct WalkForwardResult:
    var best_fast: Int
    var best_slow: Int
    var train_pnl: Int
    var test_pnl: Int
    var train_final: Int
    var test_final: Int
    var n_tested: Int
    var train_fills: Int
    var test_fills: Int

    def __init__(
        out self,
        best_fast: Int,
        best_slow: Int,
        train_pnl: Int,
        test_pnl: Int,
        train_final: Int,
        test_final: Int,
        n_tested: Int,
        train_fills: Int,
        test_fills: Int,
    ):
        self.best_fast = best_fast
        self.best_slow = best_slow
        self.train_pnl = train_pnl
        self.test_pnl = test_pnl
        self.train_final = train_final
        self.test_final = test_final
        self.n_tested = n_tested
        self.train_fills = train_fills
        self.test_fills = test_fills

    def overfit_gap(self) -> Int:
        return self.train_pnl - self.test_pnl

    def describe(self) -> String:
        var s = String("walk-forward: best SMA(")
        s = s + String(self.best_fast) + String(",") + String(self.best_slow) + String(")")
        s = s + String(" tested=") + String(self.n_tested)
        s = s + String(" train_pnl=") + String(self.train_pnl)
        s = s + String(" test_pnl=") + String(self.test_pnl)
        s = s + String(" gap=") + String(self.overfit_gap())
        return s


def walk_forward(
    bars: List[Bar],
    closes: List[Int],
    train_bars: Int,
    test_bars: Int,
    qty_per_trade: Int,
    slippage: Int,
    commission: Int,
    initial_cash: Int,
    fast_options: List[Int],
    slow_options: List[Int],
) raises -> WalkForwardResult:
    var best_fast = 0
    var best_slow = 0
    var best_train_pnl = 0
    var best_train_final = 0
    var best_train_fills = 0
    var found = False
    var n_tested = 0
    var fi = 0
    while fi < len(fast_options):
        var si = 0
        while si < len(slow_options):
            var fast = fast_options[fi]
            var slow = slow_options[si]
            if fast < slow:
                n_tested += 1
                var targets = momentum_targets(closes, fast, slow)
                var train = run_backtest_range(
                    bars, targets, 0, train_bars, qty_per_trade, slippage, commission, initial_cash
                )
                if not found or train.total_pnl > best_train_pnl:
                    found = True
                    best_fast = fast
                    best_slow = slow
                    best_train_pnl = train.total_pnl
                    best_train_final = train.final_equity
                    best_train_fills = train.n_fills
            si += 1
        fi += 1
    var best_targets = momentum_targets(closes, best_fast, best_slow)
    var test = run_backtest_range(
        bars,
        best_targets,
        train_bars,
        train_bars + test_bars,
        qty_per_trade,
        slippage,
        commission,
        initial_cash,
    )
    var result = WalkForwardResult(
        best_fast,
        best_slow,
        best_train_pnl,
        test.total_pnl,
        best_train_final,
        test.final_equity,
        n_tested,
        best_train_fills,
        test.n_fills,
    )
    return result^


# ---------------------------------------------------------------------------
# Walk-forward tests.
# ---------------------------------------------------------------------------

def test_walk_forward_small() raises:
    # 14 bars, train 7, test 7, grid of one combination: SMA(2,4).
    # Train slice (bars 0-6): buy @10300, flip at bar 6 (sell @10100,
    # close -2000, open short), ends short 10 marked at 10000 (+1000
    # unrealised): train PnL -1000.
    # Test slice (bars 7-13): short @9900 at bar 8, flip at bar 12
    # (close 0, open long @9900), ends long 10 marked at 10100 (+2000):
    # test PnL +2000.
    var closes = closes_14()
    var bars = bars_from_closes(closes)
    var fasts = List[Int]()
    fasts.append(2)
    var slows = List[Int]()
    slows.append(4)
    var res = walk_forward(bars, closes, 7, 7, 10, 0, 0, 1_000_000, fasts, slows)
    assert_equal(res.n_tested, 1)
    assert_equal(res.best_fast, 2)
    assert_equal(res.best_slow, 4)
    assert_equal(res.train_pnl, -1000)
    assert_equal(res.test_pnl, 2000)
    assert_equal(res.overfit_gap(), -3000)
    print("walk-forward small ok: train -1000, test +2000, gap -3000")


def test_walk_forward_500() raises:
    var bars = generate_bars(500)
    var closes = closes_as_int(bars)
    var fasts = List[Int]()
    fasts.append(2)
    fasts.append(3)
    fasts.append(5)
    var slows = List[Int]()
    slows.append(10)
    slows.append(20)
    slows.append(30)
    var res = walk_forward(bars, closes, 300, 200, 10, 2, 50, 1_000_000, fasts, slows)
    assert_equal(res.n_tested, 9)
    assert_true(res.best_fast == 2 or res.best_fast == 3 or res.best_fast == 5)
    assert_true(res.best_slow == 10 or res.best_slow == 20 or res.best_slow == 30)
    assert_true(res.best_fast < res.best_slow)
    # Consistency: recomputing both windows with the winning parameters
    # must reproduce the reported numbers exactly.
    var targets = momentum_targets(closes, res.best_fast, res.best_slow)
    var train = run_backtest_range(bars, targets, 0, 300, 10, 2, 50, 1_000_000)
    var test = run_backtest_range(bars, targets, 300, 500, 10, 2, 50, 1_000_000)
    assert_equal(train.total_pnl, res.train_pnl)
    assert_equal(test.total_pnl, res.test_pnl)
    assert_equal(train.final_equity, res.train_final)
    assert_equal(test.final_equity, res.test_final)
    assert_equal(test.final_equity - 1_000_000, res.test_pnl)
    print("walk-forward 500 ok: 9 combos, winner consistent on re-run")
    print("  " + res.describe())
