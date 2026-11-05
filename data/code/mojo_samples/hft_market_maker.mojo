# hft_market_maker.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): a market-making quoting engine.
#
# SIMULATOR ONLY. This file simulates a market maker quoting against an
# invented price path inside this program. It never connects to an
# exchange, a broker, or any market-data vendor, and no real money is
# involved anywhere.
#
# Standard library only. No external packages, no Python interop, no network.
#
# What a market maker does: it always shows a price to buy at (the bid)
# and a price to sell at (the ask), and earns the spread between them.
# The naive version of this loses money, because the market does not buy
# and sell at random: it buys from the maker when the price is about to
# rise (so the maker sells cheap) and sells to the maker when the price
# is about to fall (so the maker buys dear). That is adverse selection,
# and surviving it is the whole job. This file implements the three
# standard defences, each testable in isolation:
#
#   1. Fair value from the microprice. The mid-price (bid+ask)/2 treats
#      both sides equally, but the book is rarely balanced. The
#      microprice weights each side by the OTHER side's size:
#        microprice = (bid * ask_qty + ask * bid_qty) / (bid_qty + ask_qty)
#      When the bid is much larger than the ask, the microprice sits
#      above the mid: the weight of money says the next move is up.
#      Hand check: bid 10000 x30, ask 10100 x10 ->
#      (10000*10 + 10100*30) / 40 = 403000/40 = 10075.
#      Quoting around the microprice instead of the mid means the
#      maker's quotes already lean the way the book leans.
#
#   2. Inventory skew. A market maker that is long 50 units does not
#      want to buy 10 more; it wants to sell. So it shifts BOTH quotes
#      down by a skew that grows with inventory: lower ask (easier for
#      others to buy from it) and lower bid (harder for others to sell
#      to it). A short maker shifts both quotes up. The skew pulls
#      inventory back towards zero, which is the maker's risk control:
#      inventory is risk, and the quotes are the tool that manages it.
#      The size skew does the same job on quantities: a long maker
#      shows a smaller bid and a larger ask.
#
#   3. Spread widening with inventory. The further inventory is from
#      zero, the wider the quotes: a wide quote is a reluctant quote.
#      At the inventory limit the maker stops quoting on the side that
#      would make inventory worse (a hard stop, not a suggestion).
#
# The simulation in this file replays a price path bar by bar. At each
# bar the maker refreshes its quotes around the new fair value, then the
# bar's trade is applied: a trade at or below the maker's bid fills the
# bid (the maker buys), a trade at or above the maker's ask fills the
# ask (the maker sells). Fills update inventory and cash. Two PnL views
# are kept, because a market maker needs both:
#   * Mark-to-market equity: cash + inventory * current mark. This is
#     what the maker is worth right now.
#   * Adverse-selection accounting: every fill is marked again a few
#     bars later. A fill that looked like spread capture at the time
#     but loses money five bars later was adverse selection, and the
#     difference between "edge at fill" and "edge after five bars" is
#     the maker's most honest performance number.
#
# The file also runs the same path through a naive maker (fixed spread,
# no skew, no size adjustment, no inventory limit) so the reader can
# see what the three defences are worth. On a trending path the naive
# maker accumulates a large inventory against the trend and loses; the
# skewing maker stays near flat and keeps the spread. The demo prints
# both; the tests assert the structural guarantees (inventory limits,
# accounting identities, quote arithmetic) exactly, and assert the
# comparison only where the test path makes it a theorem rather than
# a hope (the trend path below is constructed so the naive maker must
# accumulate inventory: every bar trades above its ask).
#
#   4. Jump guard (volatility guard). When the fair value jumps by
#      more than `jump_threshold` ticks between refreshes, the maker
#      widens its quotes by `jump_widen` ticks for that refresh. A
#      fast market is an uncertain market, and a quote placed on stale
#      information is the one that gets picked off. The guard is the
#      maker's way of saying "I do not trust this price yet".
#
# A note on what is NOT simulated: queue position (in reality a quote
# only fills if it is at the front of its price level when the trade
# arrives), latency (in reality a quote can be stale when it is hit),
# and fees/rebates (in reality the exchange pays the maker a small
# rebate per fill). Each would change the numbers; none changes the
# structure, and the file says where each would plug in.

from std.testing import assert_equal, assert_true, assert_almost_equal
from std.math import sqrt

comptime SIDE_BUY = 0
comptime SIDE_SELL = 1


# ---------------------------------------------------------------------------
# Microprice: the size-weighted fair value of a two-sided book.
# ---------------------------------------------------------------------------

def microprice(bid: Int, bid_qty: Int, ask: Int, ask_qty: Int) -> Float64:
    var total = bid_qty + ask_qty
    if total <= 0:
        return (Float64(bid) + Float64(ask)) / 2.0
    var num = Float64(bid) * Float64(ask_qty) + Float64(ask) * Float64(bid_qty)
    return num / Float64(total)


def mid_price(bid: Int, ask: Int) -> Float64:
    return (Float64(bid) + Float64(ask)) / 2.0


# ---------------------------------------------------------------------------
# QuoteParams: the maker's policy, in ticks and units.
#
#   base_half_spread  half the quoted spread at zero inventory.
#   base_size         units shown per level at zero inventory.
#   n_levels          levels quoted per side (ladder: half-spread
#                     grows by one base_half_spread per level out).
#   skew_num/skew_den skew ticks = inventory * skew_num // skew_den.
#   size_step         inventory units per one unit of size skew.
#   widen_ticks        extra half-spread ticks at maximum inventory.
#   max_inventory     hard cap on |inventory|.
#   jump_threshold    fair-value move (ticks) that triggers the guard.
#   jump_widen        extra half-spread ticks while the guard is on.
# ---------------------------------------------------------------------------

struct QuoteParams:
    var base_half_spread: Int
    var base_size: Int
    var n_levels: Int
    var skew_num: Int
    var skew_den: Int
    var size_step: Int
    var widen_ticks: Int
    var max_inventory: Int
    var jump_threshold: Int
    var jump_widen: Int

    def __init__(out self):
        self.base_half_spread = 10
        self.base_size = 10
        self.n_levels = 3
        self.skew_num = 1
        self.skew_den = 10
        self.size_step = 5
        self.widen_ticks = 5
        self.max_inventory = 100
        self.jump_threshold = 20
        self.jump_widen = 15

    def describe(self) -> String:
        var s = String("params: half_spread=") + String(self.base_half_spread)
        s = s + String(" size=") + String(self.base_size)
        s = s + String(" levels=") + String(self.n_levels)
        s = s + String(" skew=") + String(self.skew_num) + String("/")
        s = s + String(self.skew_den) + String(" widen=") + String(self.widen_ticks)
        s = s + String(" max_inv=") + String(self.max_inventory)
        s = s + String(" jump=") + String(self.jump_threshold)
        s = s + String("+") + String(self.jump_widen)
        return s


# ---------------------------------------------------------------------------
# Quote: one live order the maker is showing. quote_id is assigned by
# the maker; ts is the bar index when it was placed (its age).
# ---------------------------------------------------------------------------

struct Quote:
    var quote_id: Int
    var side: Int
    var price: Int
    var qty: Int
    var level: Int
    var placed_bar: Int

    def __init__(
        out self, quote_id: Int, side: Int, price: Int, qty: Int, level: Int, placed_bar: Int
    ):
        self.quote_id = quote_id
        self.side = side
        self.price = price
        self.qty = qty
        self.level = level
        self.placed_bar = placed_bar

    def describe(self) -> String:
        var side_s = String("ASK")
        if self.side == SIDE_BUY:
            side_s = String("BID")
        return (
            String("q")
            + String(self.quote_id)
            + String(" ")
            + side_s
            + String(" L")
            + String(self.level)
            + String(" px=")
            + String(self.price)
            + String(" qty=")
            + String(self.qty)
        )


# ---------------------------------------------------------------------------
# Quote computation (pure functions, so the tests can check the arithmetic
# without running a simulation).
#
#   half_spread(inventory): base half-spread plus widening that grows
#     linearly with |inventory|/max_inventory.
#   skew_ticks(inventory): signed shift applied to BOTH quotes. Positive
#     inventory (long) shifts quotes down; negative shifts them up.
#   bid_size / ask_size: size skew, clamped to [0, 3 * base_size].
#   compute_quotes: the full ladder. Returns (bid prices, bid sizes,
#     ask prices, ask sizes) as four parallel lists, best level first.
#     A side with size 0 at a level is skipped (no quote there).
# ---------------------------------------------------------------------------

def half_spread(params: QuoteParams, inventory: Int) -> Int:
    var abs_inv = inventory
    if abs_inv < 0:
        abs_inv = -abs_inv
    if abs_inv > params.max_inventory:
        abs_inv = params.max_inventory
    return params.base_half_spread + (abs_inv * params.widen_ticks) // params.max_inventory


def skew_ticks(params: QuoteParams, inventory: Int) -> Int:
    return inventory * params.skew_num // params.skew_den


def bid_size(params: QuoteParams, inventory: Int) -> Int:
    var s = params.base_size - inventory // params.size_step
    if s < 0:
        s = 0
    var cap = 3 * params.base_size
    if s > cap:
        s = cap
    return s


def ask_size(params: QuoteParams, inventory: Int) -> Int:
    var s = params.base_size + inventory // params.size_step
    if s < 0:
        s = 0
    var cap = 3 * params.base_size
    if s > cap:
        s = cap
    return s


struct QuoteLadder:
    var bid_px: List[Int]
    var bid_qty: List[Int]
    var ask_px: List[Int]
    var ask_qty: List[Int]

    def __init__(out self):
        self.bid_px = List[Int]()
        self.bid_qty = List[Int]()
        self.ask_px = List[Int]()
        self.ask_qty = List[Int]()


def compute_quotes(
    params: QuoteParams, fair: Float64, inventory: Int, extra_half: Int = 0
) -> QuoteLadder:
    var ladder = QuoteLadder()
    var h = half_spread(params, inventory) + extra_half
    var sk = skew_ticks(params, inventory)
    var centre = Int(fair)
    var bs = bid_size(params, inventory)
    var asize = ask_size(params, inventory)
    var level = 0
    while level < params.n_levels:
        var half = h + level * params.base_half_spread
        if bs > 0:
            ladder.bid_px.append(centre - half - sk)
            ladder.bid_qty.append(bs)
        if asize > 0:
            ladder.ask_px.append(centre + half - sk)
            ladder.ask_qty.append(asize)
        level += 1
    return ladder^

# ---------------------------------------------------------------------------
# MakerFill: one fill of a maker quote, with the fair value at the time
# (for edge accounting) and the bar index (for later marking).
# ---------------------------------------------------------------------------

struct MakerFill:
    var bar_idx: Int
    var side: Int
    var price: Int
    var qty: Int
    var fair_at_fill: Float64

    def __init__(out self, bar_idx: Int, side: Int, price: Int, qty: Int, fair_at_fill: Float64):
        self.bar_idx = bar_idx
        self.side = side
        self.price = price
        self.qty = qty
        self.fair_at_fill = fair_at_fill

    # Edge captured at the moment of the fill: how far inside the fair
    # value the trade happened. Positive means the maker bought below
    # fair value or sold above it.
    def edge_ticks(self) -> Float64:
        if self.side == SIDE_BUY:
            return (self.fair_at_fill - Float64(self.price)) * Float64(self.qty)
        return (Float64(self.price) - self.fair_at_fill) * Float64(self.qty)


# ---------------------------------------------------------------------------
# MarketMaker: inventory, cash, live quotes, and statistics.
#
# The maker is deliberately simple about the market: the simulation
# hands it a fair value and a trade price each bar. The maker refreshes
# its quotes around the fair value, then any trade at or through a
# quote fills it. A real maker would also manage queue position and
# latency; the hooks for those are the quote age (placed_bar) and the
# refresh cadence (one refresh per bar here).
# ---------------------------------------------------------------------------

struct MarketMaker:
    var params: QuoteParams
    var use_skew: Bool
    var inventory: Int
    var cash: Int
    var quotes: List[Quote]
    var fills: List[MakerFill]
    var next_quote_id: Int
    var n_refreshes: Int
    var n_fills: Int
    var volume_traded: Int
    var last_fair: Float64
    var last_mark: Int
    var marks: List[Int]

    def __init__(out self, use_skew: Bool):
        self.params = QuoteParams()
        self.use_skew = use_skew
        self.inventory = 0
        self.cash = 0
        self.quotes = List[Quote]()
        self.fills = List[MakerFill]()
        self.next_quote_id = 1
        self.n_refreshes = 0
        self.n_fills = 0
        self.volume_traded = 0
        self.last_fair = 0.0
        self.last_mark = 0
        self.marks = List[Int]()

    def set_params(mut self, var p: QuoteParams):
        self.params = p^

    def equity(self) -> Int:
        return self.cash + self.inventory * self.last_mark

    def abs_inventory(self) -> Int:
        if self.inventory < 0:
            return -self.inventory
        return self.inventory

    # Cancel every live quote.
    def cancel_all(mut self) -> Int:
        var n = len(self.quotes)
        self.quotes = List[Quote]()
        return n

    # Refresh quotes around a new fair value: cancel everything, then
    # place the new ladder. A side that would increase inventory beyond
    # the cap is not quoted at all (the hard stop).
    def refresh(mut self, fair: Float64, bar_idx: Int):
        var extra_half = 0
        if self.last_fair != 0.0:
            var move = fair - self.last_fair
            if move < 0.0:
                move = -move
            if Int(move) > self.params.jump_threshold:
                extra_half = self.params.jump_widen
        self.last_fair = fair
        var _cancelled = self.cancel_all()
        self.n_refreshes += 1
        var inv = self.inventory
        if not self.use_skew:
            inv = 0
        var ladder = compute_quotes(self.params, fair, inv, extra_half)
        var i = 0
        while i < len(ladder.bid_px):
            if self.inventory < self.params.max_inventory:
                var q = Quote(
                    self.next_quote_id, SIDE_BUY, ladder.bid_px[i], ladder.bid_qty[i], i, bar_idx
                )
                self.next_quote_id += 1
                self.quotes.append(q^)
            i += 1
        var j = 0
        while j < len(ladder.ask_px):
            if self.inventory > -self.params.max_inventory:
                var q = Quote(
                    self.next_quote_id, SIDE_SELL, ladder.ask_px[j], ladder.ask_qty[j], j, bar_idx
                )
                self.next_quote_id += 1
                self.quotes.append(q^)
            j += 1

    def best_bid(self) -> Int:
        var best = -1
        var i = 0
        while i < len(self.quotes):
            if self.quotes[i].side == SIDE_BUY:
                if best < 0 or self.quotes[i].price > best:
                    best = self.quotes[i].price
            i += 1
        return best

    def best_ask(self) -> Int:
        var best = -1
        var i = 0
        while i < len(self.quotes):
            if self.quotes[i].side == SIDE_SELL:
                if best < 0 or self.quotes[i].price < best:
                    best = self.quotes[i].price
            i += 1
        return best

    def bid_qty_at_best(self) -> Int:
        var best = self.best_bid()
        var total = 0
        var i = 0
        while i < len(self.quotes):
            if self.quotes[i].side == SIDE_BUY and self.quotes[i].price == best:
                total += self.quotes[i].qty
            i += 1
        return total

    def ask_qty_at_best(self) -> Int:
        var best = self.best_ask()
        var total = 0
        var i = 0
        while i < len(self.quotes):
            if self.quotes[i].side == SIDE_SELL and self.quotes[i].price == best:
                total += self.quotes[i].qty
            i += 1
        return total

    # Apply one market trade. A trade priced at or below the best bid
    # fills the maker's bid (the maker buys); at or above the best ask
    # it fills the ask (the maker sells). Fills consume the best level
    # first, then deeper levels. Returns the filled quantity.
    def on_trade(mut self, price: Int, qty: Int, bar_idx: Int) -> Int:
        var filled = 0
        var remaining = qty
        # Sell trades hitting the bid: the maker buys.
        if len(self.quotes) > 0 and price <= self.best_bid():
            while remaining > 0:
                var idx = -1
                var best = -1
                var i = 0
                while i < len(self.quotes):
                    if self.quotes[i].side == SIDE_BUY:
                        if best < 0 or self.quotes[i].price > best:
                            best = self.quotes[i].price
                            idx = i
                    i += 1
                if idx < 0:
                    break
                var take = remaining
                if self.quotes[idx].qty < take:
                    take = self.quotes[idx].qty
                var px = self.quotes[idx].price
                self.quotes[idx].qty -= take
                if self.quotes[idx].qty == 0:
                    var _gone = self.quotes.pop(idx)
                self.inventory += take
                self.cash -= px * take
                self.n_fills += 1
                self.volume_traded += take
                filled += take
                remaining -= take
                var f = MakerFill(bar_idx, SIDE_BUY, px, take, self.last_fair)
                self.fills.append(f^)
                if remaining > 0 and (len(self.quotes) == 0 or price > self.best_bid()):
                    break
        # Buy trades hitting the ask: the maker sells.
        if len(self.quotes) > 0 and price >= self.best_ask():
            while remaining > 0:
                var idx = -1
                var best = -1
                var i = 0
                while i < len(self.quotes):
                    if self.quotes[i].side == SIDE_SELL:
                        if best < 0 or self.quotes[i].price < best:
                            best = self.quotes[i].price
                            idx = i
                    i += 1
                if idx < 0:
                    break
                var take = remaining
                if self.quotes[idx].qty < take:
                    take = self.quotes[idx].qty
                var px = self.quotes[idx].price
                self.quotes[idx].qty -= take
                if self.quotes[idx].qty == 0:
                    var _gone = self.quotes.pop(idx)
                self.inventory -= take
                self.cash += px * take
                self.n_fills += 1
                self.volume_traded += take
                filled += take
                remaining -= take
                var f = MakerFill(bar_idx, SIDE_SELL, px, take, self.last_fair)
                self.fills.append(f^)
                if remaining > 0 and (len(self.quotes) == 0 or price < self.best_ask()):
                    break
        return filled

    # Total edge captured at fill time, summed over all fills.
    def total_edge(self) -> Float64:
        var total: Float64 = 0.0
        var i = 0
        while i < len(self.fills):
            total += self.fills[i].edge_ticks()
            i += 1
        return total

    # Adverse-selection accounting: re-mark every fill at the mark
    # `lag` bars after it filled. A buy that the market then trades
    # below was adverse; a sell the market then trades above was too.
    # Returns the summed later PnL of all fills old enough to mark.
    def later_pnl(self, lag: Int) -> Float64:
        var total: Float64 = 0.0
        var i = 0
        while i < len(self.fills):
            var mark_idx = self.fills[i].bar_idx + lag
            if mark_idx < len(self.marks):
                var mark = Float64(self.marks[mark_idx])
                if self.fills[i].side == SIDE_BUY:
                    total += (mark - Float64(self.fills[i].price)) * Float64(self.fills[i].qty)
                else:
                    total += (Float64(self.fills[i].price) - mark) * Float64(self.fills[i].qty)
            i += 1
        return total

    def describe(self) -> String:
        var s = String("maker: inv=") + String(self.inventory)
        s = s + String(" cash=") + String(self.cash)
        s = s + String(" equity=") + String(self.equity())
        s = s + String(" fills=") + String(self.n_fills)
        s = s + String(" volume=") + String(self.volume_traded)
        s = s + String(" edge=") + String(self.total_edge())
        return s


# ---------------------------------------------------------------------------
# Simulation: replay a mark path through a maker.
#
# Each bar: the maker refreshes quotes around the current mark (the book
# is synthesised as mark - 5 / mark + 5 with size 20/20, so the
# microprice equals the mark and the test path is neutral about the
# book), then the mark moves by `drift_per_bar` and a trade prints at
# the NEW mark. When the mark rises through the maker's ask the ask is
# lifted (the maker sells); when it falls through the bid the bid is
# hit (the maker buys). With a drift of +10 and a base half-spread of
# 10, the new mark lands exactly on the best ask every bar, so a naive
# maker sells 10 units a bar until its inventory cap stops it, while a
# skewing maker's ask has moved one tick higher after the first sale
# and is never hit again. That is the comparison the tests assert.
# ---------------------------------------------------------------------------

def run_maker_sim(
    use_skew: Bool, start_mark: Int, n_bars: Int, drift_per_bar: Int, trade_qty: Int
) -> MarketMaker:
    var maker = MarketMaker(use_skew)
    var mark = start_mark
    var bar = 0
    while bar < n_bars:
        maker.marks.append(mark)
        maker.last_mark = mark
        var fair = microprice(mark - 5, 20, mark + 5, 20)
        maker.refresh(fair, bar)
        mark += drift_per_bar
        var _filled = maker.on_trade(mark, trade_qty, bar)
        maker.last_mark = mark
        bar += 1
    return maker^

# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------

def test_microprice() raises:
    # (10000*10 + 10100*30) / 40 = 403000/40 = 10075.
    assert_almost_equal(microprice(10000, 30, 10100, 10), 10075.0, atol=1e-9)
    assert_almost_equal(microprice(10000, 10, 10100, 10), 10050.0, atol=1e-9)
    assert_almost_equal(microprice(10000, 0, 10100, 0), 10050.0, atol=1e-9)
    assert_almost_equal(mid_price(10000, 10100), 10050.0, atol=1e-9)
    print("microprice ok: size-weighted fair value, balanced case is the mid")


def test_spread_skew_sizes() raises:
    var p = QuoteParams()
    assert_equal(half_spread(p, 0), 10)
    assert_equal(half_spread(p, 100), 15)
    assert_equal(half_spread(p, -100), 15)
    assert_equal(half_spread(p, 50), 12)
    assert_equal(skew_ticks(p, 50), 5)
    assert_equal(skew_ticks(p, -30), -3)
    assert_equal(skew_ticks(p, 0), 0)
    assert_equal(bid_size(p, 0), 10)
    assert_equal(ask_size(p, 0), 10)
    assert_equal(bid_size(p, 50), 0)
    assert_equal(ask_size(p, 50), 20)
    assert_equal(bid_size(p, -30), 16)
    assert_equal(ask_size(p, -30), 4)
    assert_equal(bid_size(p, 200), 0)
    assert_equal(ask_size(p, 200), 30)
    print("spread/skew/sizes ok: widening, skew direction, size clamps")


def test_compute_quotes_flat() raises:
    var p = QuoteParams()
    var q = compute_quotes(p, 10050.0, 0)
    assert_equal(len(q.bid_px), 3)
    assert_equal(q.bid_px[0], 10040)
    assert_equal(q.bid_px[1], 10030)
    assert_equal(q.bid_px[2], 10020)
    assert_equal(q.bid_qty[0], 10)
    assert_equal(len(q.ask_px), 3)
    assert_equal(q.ask_px[0], 10060)
    assert_equal(q.ask_px[1], 10070)
    assert_equal(q.ask_px[2], 10080)
    assert_equal(q.ask_qty[2], 10)
    print("quotes flat ok: ladder 10040/10060, 10030/10070, 10020/10080")


def test_compute_quotes_skewed() raises:
    var p = QuoteParams()
    # Long 50: half-spread 12, skew 5 down, bid size 0, ask size 20.
    var q = compute_quotes(p, 10050.0, 50)
    assert_equal(len(q.bid_px), 0)
    assert_equal(len(q.ask_px), 3)
    assert_equal(q.ask_px[0], 10057)
    assert_equal(q.ask_px[1], 10067)
    assert_equal(q.ask_px[2], 10077)
    assert_equal(q.ask_qty[0], 20)
    # Short 30: half-spread 11, skew 3 up, bid size 16, ask size 4.
    var r = compute_quotes(p, 10050.0, -30)
    assert_equal(r.bid_px[0], 10042)
    assert_equal(r.ask_px[0], 10064)
    assert_equal(r.bid_qty[0], 16)
    assert_equal(r.ask_qty[0], 4)
    print("quotes skewed ok: long maker drops bids, short maker lifts asks")


def test_refresh_and_fill() raises:
    var maker = MarketMaker(True)
    maker.refresh(10050.0, 0)
    assert_equal(maker.best_bid(), 10040)
    assert_equal(maker.best_ask(), 10060)
    assert_equal(len(maker.quotes), 6)
    var f1 = maker.on_trade(10040, 5, 0)
    assert_equal(f1, 5)
    assert_equal(maker.inventory, 5)
    assert_equal(maker.cash, -50200)
    assert_equal(maker.bid_qty_at_best(), 5)
    var f2 = maker.on_trade(10060, 4, 0)
    assert_equal(f2, 4)
    assert_equal(maker.inventory, 1)
    assert_equal(maker.cash, -9960)
    assert_equal(maker.n_fills, 2)
    assert_equal(maker.volume_traded, 9)
    # A trade inside the spread touches nothing.
    var f3 = maker.on_trade(10050, 100, 0)
    assert_equal(f3, 0)
    assert_equal(maker.inventory, 1)
    print("refresh/fill ok: fills consume the best level, spread is safe")


def test_jump_guard() raises:
    var maker = MarketMaker(True)
    # First refresh: no previous fair value, no widening.
    maker.refresh(10050.0, 0)
    assert_equal(maker.best_bid(), 10040)
    assert_equal(maker.best_ask(), 10060)
    # A 30-tick jump exceeds the threshold of 20: half-spread grows
    # from 10 to 25 for this refresh only.
    maker.refresh(10080.0, 1)
    assert_equal(maker.best_bid(), 10055)
    assert_equal(maker.best_ask(), 10105)
    # A 5-tick move does not trigger the guard: spread back to normal.
    maker.refresh(10085.0, 2)
    assert_equal(maker.best_bid(), 10075)
    assert_equal(maker.best_ask(), 10095)
    # Exactly at the threshold (20) does not trigger it either: the
    # guard needs a move strictly greater than the threshold.
    maker.refresh(10105.0, 3)
    assert_equal(maker.best_bid(), 10095)
    assert_equal(maker.best_ask(), 10115)
    print("jump guard ok: wide quotes after a jump, normal after calm")


def test_hard_stop() raises:
    var maker = MarketMaker(True)
    var p = QuoteParams()
    p.max_inventory = 10
    maker.set_params(p^)
    maker.refresh(10050.0, 0)
    var f = maker.on_trade(10060, 10, 0)
    assert_equal(f, 10)
    assert_equal(maker.inventory, -10)
    maker.refresh(10050.0, 1)
    # At the short cap the ask side is not quoted at all; the bid side
    # is still there, skewed up by 1 tick with a widened spread.
    assert_equal(maker.best_ask(), -1)
    assert_equal(maker.best_bid(), 10036)
    assert_true(maker.bid_qty_at_best() > 0)
    print("hard stop ok: capped side stops quoting, the other side continues")


def test_adverse_selection() raises:
    var maker = MarketMaker(True)
    maker.refresh(10050.0, 0)
    var f = maker.on_trade(10040, 10, 0)
    assert_equal(f, 10)
    # Edge at fill: bought 10 ticks below fair value -> +100.
    assert_almost_equal(maker.total_edge(), 100.0, atol=1e-9)
    maker.marks.append(10050)
    maker.marks.append(10030)
    maker.marks.append(10000)
    # Two bars later the mark is 10000: the fill is worth -400.
    assert_almost_equal(maker.later_pnl(2), -400.0, atol=1e-9)
    maker.last_mark = 10000
    assert_equal(maker.equity(), -400)
    print("adverse selection ok: edge +100 at fill, -400 two bars later")


def test_sim_uptrend() raises:
    var smart = run_maker_sim(True, 10000, 30, 10, 25)
    var naive = run_maker_sim(False, 10000, 30, 10, 25)
    # The naive maker sells 10 a bar until its cap: inventory -100.
    assert_equal(naive.inventory, -100)
    assert_equal(naive.n_fills, 10)
    assert_equal(naive.volume_traded, 100)
    assert_equal(naive.equity(), -24500)
    # The skewing maker sells once and is then never hit: inventory -10.
    assert_equal(smart.inventory, -10)
    assert_equal(smart.n_fills, 1)
    assert_equal(smart.volume_traded, 10)
    assert_equal(smart.equity(), -2900)
    assert_true(smart.equity() > naive.equity())
    assert_true(smart.abs_inventory() < naive.abs_inventory())
    # Accounting identity: cash + inventory * mark == equity.
    assert_equal(smart.cash + smart.inventory * smart.last_mark, smart.equity())
    assert_equal(naive.cash + naive.inventory * naive.last_mark, naive.equity())
    print("sim uptrend ok: naive -24500 at -100, smart -2900 at -10")


def test_sim_downtrend() raises:
    var smart = run_maker_sim(True, 10000, 30, -10, 25)
    var naive = run_maker_sim(False, 10000, 30, -10, 25)
    assert_equal(naive.inventory, 100)
    assert_equal(naive.equity(), -24500)
    assert_equal(smart.inventory, 10)
    assert_equal(smart.equity(), -2900)
    assert_true(smart.equity() > naive.equity())
    print("sim downtrend ok: mirror image, naive -24500, smart -2900")


def test_sim_flat() raises:
    var smart = run_maker_sim(True, 10000, 30, 0, 25)
    var naive = run_maker_sim(False, 10000, 30, 0, 25)
    assert_equal(smart.inventory, 0)
    assert_equal(smart.equity(), 0)
    assert_equal(smart.n_fills, 0)
    assert_equal(naive.inventory, 0)
    assert_equal(naive.equity(), 0)
    print("sim flat ok: no drift, no fills, no PnL")


# ---------------------------------------------------------------------------
# Demo: the three regimes, both makers.
# ---------------------------------------------------------------------------

def demo() raises:
    print("=== HFT market maker demo (simulated data, no real market) ===")
    var p = QuoteParams()
    print(p.describe())
    var maker = MarketMaker(True)
    maker.refresh(10050.0, 0)
    print("ladder around fair 10050, flat inventory:")
    var i = 0
    while i < len(maker.quotes):
        print("  " + maker.quotes[i].describe())
        i += 1
    var regimes = List[Int]()
    regimes.append(10)
    regimes.append(0)
    regimes.append(-10)
    var r = 0
    while r < len(regimes):
        var drift = regimes[r]
        var smart = run_maker_sim(True, 10000, 30, drift, 25)
        var naive = run_maker_sim(False, 10000, 30, drift, 25)
        print("drift", drift, "per bar, 30 bars:")
        print("  smart: " + smart.describe())
        print("  naive: " + naive.describe())
        print("  smart edge at fill:", smart.total_edge(), " later PnL(5):", smart.later_pnl(5))
        print("  naive edge at fill:", naive.total_edge(), " later PnL(5):", naive.later_pnl(5))
        r += 1


def main() raises:
    demo()
    print("=== market maker tests ===")
    test_microprice()
    test_spread_skew_sizes()
    test_compute_quotes_flat()
    test_compute_quotes_skewed()
    test_refresh_and_fill()
    test_jump_guard()
    test_hard_stop()
    test_adverse_selection()
    test_sim_uptrend()
    test_sim_downtrend()
    test_sim_flat()
    print("ALL MARKET MAKER TESTS PASSED")
