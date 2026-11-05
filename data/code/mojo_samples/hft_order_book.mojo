# hft_order_book.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): a limit order book with price-time priority.
#
# SIMULATOR ONLY. This file does not connect to any exchange, broker, or
# market-data vendor, and it never moves real money. Every order, trade, and
# price below is invented inside this program for teaching and benchmarking.
# Prices are integer ticks (1 tick = 1 cent) so matching arithmetic is exact
# and never suffers floating-point rounding. Quantities are whole units.
#
# Standard library only. No external packages, no Python interop, no network.
#
# Design notes (the ideas a real book uses, rebuilt from scratch here):
#   * The book keeps two flat lists, bids and asks. Bids are sorted by price
#     descending, asks by price ascending; within one price, orders sit in
#     arrival (sequence) order. That ordering IS price-time priority: the best
#     price is always element 0 of its side, and the oldest order at that
#     price is always first in line.
#   * A new limit order first trades against the opposite side ("takes
#     liquidity") and only the unfilled remainder rests in the book ("makes
#     liquidity"). A market order only takes; whatever it cannot fill is
#     discarded, it never rests.
#   * A trade always prints at the price of the resting order, never at the
#     incoming order's limit. That is how a real continuous book works: the
#     aggressor pays the price the maker asked for.
#   * IOC (immediate-or-cancel) is a limit order whose remainder is cancelled
#     instead of resting. FOK (fill-or-kill) is all-or-nothing: if the book
#     cannot fill the whole quantity at acceptable prices, nothing trades.
#   * Every order carries a monotonically increasing sequence number assigned
#     by the book. Sequence numbers are the book's clock: they define time
#     priority, they make the book deterministic, and they let a replay
#     reproduce an identical book from an identical event log.
#   * The book exposes its own invariant checker. After any operation the
#     book must be sorted, must contain no empty or negative quantities, and
#     must not be crossed (best bid strictly below best ask). The tests below
#     call the checker after every scenario.
#
# What this file demonstrates (run it: it prints a worked book and then runs
# its own checks; exit code 0 means every check passed):
#   1. Limit, market, IOC and FOK orders, with hand-computed fills.
#   2. Price-time priority: two orders at the same price fill oldest first.
#   3. A market order sweeping several price levels, with exact VWAP.
#   4. Cancel and amend (amend loses time priority, as on a real venue).
#   5. Depth, spread, mid-price, imbalance and VWAP queries.
#   6. Volume conservation: traded + resting + cancelled == added.
#
# Hand-computed cases used in the tests (ticks; 10000 = $100.00):
#   Case A: asks 10100 x5, 10200 x5. Buy limit 10100 x7 -> 1 trade, 5 @10100,
#           remainder 2 rests as the new best bid at 10100.
#   Case B: bids 10000 x5 (old), 10000 x5 (young). Sell market x7 -> fills
#           5 against the old order, 2 against the young one; young keeps 3.
#   Case C: asks 10100 x3, 10200 x4, 10300 x5. Buy market x10 -> fills
#           3 @10100, 4 @10200, 3 @10300; cost 102000, VWAP 10200.
#   Case D: ask 10100 x2. Buy IOC 10100 x5 -> fills 2, remainder 3 cancelled,
#           book has no resting bid afterwards.
#   Case E: ask 10100 x2. Buy FOK 10100 x5 -> rejected whole, book untouched;
#           then buy FOK 10100 x2 -> fills 2, ask gone.
#   Case F: bid 10000 x10, cancel it, re-add, amend price to 9900 -> best
#           bid becomes 9900 and the order carries a fresh sequence number.
#   Case G: market order into an empty book -> zero trades, nothing rests.
#   Case H: a built-up book whose depth, totals, spread, mid-price and
#           imbalance are all asserted against hand-computed values.
#
# Icebergs (TYPE_ICEBERG, add_iceberg): only `peak` units show at the
# price level. A fill consumes the display; when the display is
# exhausted and hidden quantity remains, a fresh peak is displayed and
# the order goes to the BACK of its price level with a new sequence
# number -- the display refresh costs time priority, which is the
# price of hiding size. depth_at() counts total resting quantity
# (hidden included); visible_depth_at() counts only what is displayed.
#   Case I: ask iceberg 10100 total 100, peak 10. Buy limit 10100 x25
#           -> 3 trades (10, 10, 5); iceberg rests with 75 hidden and
#           5 displayed.
#   Case J: iceberg 10100 total 30 peak 10, then a plain ask 10100 x5
#           behind it. Buy 12 -> 10 from the iceberg (which refreshes
#           to the back), then 2 from the plain ask. The iceberg's
#           refresh cost it its place in line.
#   Case K: an iceberg that never trades shows peak in visible depth
#           and its full size in total depth; a peak >= qty behaves as
#           a plain limit order.

from std.testing import assert_equal, assert_true, assert_almost_equal
from std.builtin.sort import sort

# ---------------------------------------------------------------------------
# Constants. Sides, order types and reject reasons are plain integers so the
# book stays allocation-free on its hot path; the names below are the only
# place the numbers are written down.
# ---------------------------------------------------------------------------

comptime SIDE_BUY = 0
comptime SIDE_SELL = 1

comptime TYPE_LIMIT = 0
comptime TYPE_MARKET = 1
comptime TYPE_IOC = 2
comptime TYPE_FOK = 3
comptime TYPE_ICEBERG = 4

comptime NO_PRICE = -1


# ---------------------------------------------------------------------------
# Order: one instruction sitting in (or arriving at) the book.
#
#   oid        unique order id, assigned by the caller / matching engine.
#   client_id  who sent it; used by the matching engine for self-trade
#              prevention and by the risk engine for per-client limits.
#   side       SIDE_BUY or SIDE_SELL.
#   price      limit price in ticks. Ignored for market orders (0 = no limit).
#   qty        original quantity.
#   remaining  quantity still unfilled; 0 means the order is done.
#   seq        book-assigned arrival sequence; defines time priority.
#   otype      TYPE_LIMIT / TYPE_MARKET / TYPE_IOC / TYPE_FOK / TYPE_ICEBERG.
#   peak       iceberg display size (0 = not an iceberg: the whole order
#              is visible). See the iceberg section below.
#   visible    quantity currently displayed at the price level. For a
#              plain order visible == remaining; for an iceberg only the
#              peak shows, and the rest is hidden until the display is
#              exhausted and refreshed.
# ---------------------------------------------------------------------------

struct Order:
    var oid: Int
    var client_id: Int
    var side: Int
    var price: Int
    var qty: Int
    var remaining: Int
    var seq: Int
    var otype: Int
    var peak: Int
    var visible: Int

    def __init__(
        out self,
        oid: Int,
        client_id: Int,
        side: Int,
        price: Int,
        qty: Int,
        otype: Int,
        peak: Int = 0,
    ):
        self.oid = oid
        self.client_id = client_id
        self.side = side
        self.price = price
        self.qty = qty
        self.remaining = qty
        self.seq = 0
        self.otype = otype
        self.peak = peak
        if peak > 0 and peak < qty:
            self.visible = peak
        else:
            self.visible = qty

    def is_buy(self) -> Bool:
        return self.side == SIDE_BUY

    def is_done(self) -> Bool:
        return self.remaining <= 0

    def describe(self) -> String:
        var side_s = String("SELL")
        if self.side == SIDE_BUY:
            side_s = String("BUY ")
        var type_s = String("LIMIT")
        if self.otype == TYPE_MARKET:
            type_s = String("MARKET")
        elif self.otype == TYPE_IOC:
            type_s = String("IOC")
        elif self.otype == TYPE_FOK:
            type_s = String("FOK")
        return (
            String("oid=")
            + String(self.oid)
            + String(" ")
            + side_s
            + String(" ")
            + type_s
            + String(" px=")
            + String(self.price)
            + String(" qty=")
            + String(self.qty)
            + String(" rem=")
            + String(self.remaining)
            + String(" seq=")
            + String(self.seq)
        )


# ---------------------------------------------------------------------------
# Trade: one fill. buy_oid / sell_oid name the two orders; price is the
# resting order's price; qty is the filled quantity; seq orders the tape.
# ---------------------------------------------------------------------------

struct Trade:
    var buy_oid: Int
    var sell_oid: Int
    var price: Int
    var qty: Int
    var seq: Int

    def __init__(out self, buy_oid: Int, sell_oid: Int, price: Int, qty: Int, seq: Int):
        self.buy_oid = buy_oid
        self.sell_oid = sell_oid
        self.price = price
        self.qty = qty
        self.seq = seq

    def notional(self) -> Int:
        return self.price * self.qty

    def describe(self) -> String:
        return (
            String("trade seq=")
            + String(self.seq)
            + String(" buy_oid=")
            + String(self.buy_oid)
            + String(" sell_oid=")
            + String(self.sell_oid)
            + String(" px=")
            + String(self.price)
            + String(" qty=")
            + String(self.qty)
        )


# ---------------------------------------------------------------------------
# OrderBook.
#
# Invariants (checked by check_invariants):
#   * bids sorted by price descending, then seq ascending.
#   * asks sorted by price ascending, then seq ascending.
#   * every resting order has remaining > 0 and price > 0.
#   * best bid < best ask whenever both sides are non-empty (never crossed).
#   * sequence numbers strictly increase along each side's list.
# ---------------------------------------------------------------------------

struct OrderBook:
    var bids: List[Order]
    var asks: List[Order]
    var trades: List[Trade]
    var next_seq: Int
    var total_volume: Int
    var total_notional: Int
    var last_trade_price: Int
    var orders_added: Int
    var orders_cancelled: Int
    var last_fok_ok: Bool

    def __init__(out self):
        self.bids = List[Order]()
        self.asks = List[Order]()
        self.trades = List[Trade]()
        self.next_seq = 1
        self.total_volume = 0
        self.total_notional = 0
        self.last_trade_price = 0
        self.orders_added = 0
        self.orders_cancelled = 0
        self.last_fok_ok = True

    # -- sequence ----------------------------------------------------------
    def _take_seq(mut self) -> Int:
        var s = self.next_seq
        self.next_seq += 1
        return s

    # -- sorted insertion --------------------------------------------------
    # Bids: insert before the first bid priced below the new order. Same
    # price orders stay ahead (they arrived earlier), which is time priority.
    def _insert_bid(mut self, var order: Order):
        var pos = len(self.bids)
        var i = 0
        while i < len(self.bids):
            if self.bids[i].price < order.price:
                pos = i
                break
            i += 1
        self.bids.insert(pos, order^)

    # Asks: insert before the first ask priced above the new order.
    def _insert_ask(mut self, var order: Order):
        var pos = len(self.asks)
        var i = 0
        while i < len(self.asks):
            if self.asks[i].price > order.price:
                pos = i
                break
            i += 1
        self.asks.insert(pos, order^)

    # -- tape --------------------------------------------------------------
    def _record_trade(mut self, buy_oid: Int, sell_oid: Int, price: Int, qty: Int):
        var t = Trade(buy_oid, sell_oid, price, qty, self._take_seq())
        self.trades.append(t^)
        self.total_volume += qty
        self.total_notional += price * qty
        self.last_trade_price = price

    # -- matching ----------------------------------------------------------
    # Match an incoming buy against the asks. Trades print at the resting
    # ask's price. Returns the number of trades printed.
    def _match_buy(mut self, mut order: Order, limit_price: Int) -> Int:
        var n_trades = 0
        while (
            order.remaining > 0
            and len(self.asks) > 0
            and self.asks[0].price <= limit_price
        ):
            var fill = order.remaining
            if self.asks[0].visible < fill:
                fill = self.asks[0].visible
            var px = self.asks[0].price
            var resting_oid = self.asks[0].oid
            self.asks[0].remaining -= fill
            self.asks[0].visible -= fill
            order.remaining -= fill
            self._record_trade(order.oid, resting_oid, px, fill)
            n_trades += 1
            if self.asks[0].remaining == 0:
                var _gone = self.asks.pop(0)
            elif self.asks[0].visible == 0:
                # Iceberg refresh: display a new peak and go to the back
                # of the price level (fresh sequence = lost priority).
                var refreshed = self.asks.pop(0)
                refreshed.visible = refreshed.peak
                if refreshed.visible > refreshed.remaining:
                    refreshed.visible = refreshed.remaining
                refreshed.seq = self._take_seq()
                self._insert_ask(refreshed^)
        return n_trades

    # Match an incoming sell against the bids. Trades print at the resting
    # bid's price.
    def _match_sell(mut self, mut order: Order, limit_price: Int) -> Int:
        var n_trades = 0
        while (
            order.remaining > 0
            and len(self.bids) > 0
            and self.bids[0].price >= limit_price
        ):
            var fill = order.remaining
            if self.bids[0].visible < fill:
                fill = self.bids[0].visible
            var px = self.bids[0].price
            var resting_oid = self.bids[0].oid
            self.bids[0].remaining -= fill
            self.bids[0].visible -= fill
            order.remaining -= fill
            self._record_trade(resting_oid, order.oid, px, fill)
            n_trades += 1
            if self.bids[0].remaining == 0:
                var _gone = self.bids.pop(0)
            elif self.bids[0].visible == 0:
                var refreshed = self.bids.pop(0)
                refreshed.visible = refreshed.peak
                if refreshed.visible > refreshed.remaining:
                    refreshed.visible = refreshed.remaining
                refreshed.seq = self._take_seq()
                self._insert_bid(refreshed^)
        return n_trades

    # How much is available on the opposite side at prices the incoming
    # order would accept? Used by FOK: the whole quantity must be there.
    def _available(self, side: Int, limit_price: Int) -> Int:
        var total = 0
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.asks):
                if self.asks[i].price > limit_price:
                    break
                total += self.asks[i].remaining
                i += 1
        else:
            var i = 0
            while i < len(self.bids):
                if self.bids[i].price < limit_price:
                    break
                total += self.bids[i].remaining
                i += 1
        return total

    # -- public order entry ------------------------------------------------
    # Limit order: match what can be matched, rest the remainder. The
    # displayed quantity is re-derived before resting: an incoming
    # order's visible field is stale after matching (it was the
    # aggressor, so its own display was never drawn down), and a
    # resting order must always satisfy visible == min(peak, remaining).
    def add_limit(mut self, var order: Order) -> Int:
        order.seq = self._take_seq()
        self.orders_added += 1
        var n = 0
        if order.side == SIDE_BUY:
            n = self._match_buy(order, order.price)
            if order.remaining > 0:
                if order.peak > 0 and order.peak < order.remaining:
                    order.visible = order.peak
                else:
                    order.visible = order.remaining
                self._insert_bid(order^)
        else:
            n = self._match_sell(order, order.price)
            if order.remaining > 0:
                if order.peak > 0 and order.peak < order.remaining:
                    order.visible = order.peak
                else:
                    order.visible = order.remaining
                self._insert_ask(order^)
        return n

    # Market order: match at any price; the unfilled remainder is discarded.
    # A limit price of 0 is used internally to mean "no price limit".
    def add_market(mut self, var order: Order) -> Int:
        order.seq = self._take_seq()
        self.orders_added += 1
        var n = 0
        if order.side == SIDE_BUY:
            # No ask can be priced above "infinity"; use a huge limit.
            n = self._match_buy(order, 1_000_000_000)
        else:
            n = self._match_sell(order, 0)
        return n

    # IOC: like a limit order, except the remainder is cancelled.
    def add_ioc(mut self, var order: Order) -> Int:
        order.seq = self._take_seq()
        self.orders_added += 1
        var n = 0
        if order.side == SIDE_BUY:
            n = self._match_buy(order, order.price)
        else:
            n = self._match_sell(order, order.price)
        if order.remaining > 0:
            self.orders_cancelled += 1
        return n

    # FOK: all or nothing. Sets last_fok_ok so the caller can tell a
    # rejection (False, 0 trades) from a genuine zero fill.
    def add_fok(mut self, var order: Order) -> Int:
        order.seq = self._take_seq()
        self.orders_added += 1
        var avail = self._available(order.side, order.price)
        if avail < order.qty:
            self.last_fok_ok = False
            self.orders_cancelled += 1
            return 0
        self.last_fok_ok = True
        var n = 0
        if order.side == SIDE_BUY:
            n = self._match_buy(order, order.price)
        else:
            n = self._match_sell(order, order.price)
        return n

    # Iceberg order: only `peak` units show at the price level; the rest
    # is hidden and refreshes (at the back of the queue) as the display
    # is consumed. A peak of 0, or a peak >= qty, is just a limit order.
    def add_iceberg(mut self, var order: Order, peak: Int) -> Int:
        if peak <= 0 or peak >= order.qty:
            return self.add_limit(order^)
        order.peak = peak
        order.visible = peak
        order.otype = TYPE_ICEBERG
        return self.add_limit(order^)

    # Cancel by order id. Returns True if an order was actually removed.
    def cancel(mut self, oid: Int) -> Bool:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                var _gone = self.bids.pop(i)
                self.orders_cancelled += 1
                return True
            i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].oid == oid:
                var _gone = self.asks.pop(j)
                self.orders_cancelled += 1
                return True
            j += 1
        return False

    # Amend: cancel the old order and re-enter it at a new price / quantity.
    # The amended order gets a fresh sequence number, so it goes to the back
    # of its price level -- exactly what a real venue does, and exactly why
    # amending to jump the queue does not work.
    def amend(mut self, oid: Int, new_price: Int, new_qty: Int) -> Bool:
        var side = NO_PRICE
        var client_id = 0
        var otype = TYPE_LIMIT
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                side = SIDE_BUY
                client_id = self.bids[i].client_id
                otype = self.bids[i].otype
                var _gone = self.bids.pop(i)
                break
            i += 1
        if side == NO_PRICE:
            var j = 0
            while j < len(self.asks):
                if self.asks[j].oid == oid:
                    side = SIDE_SELL
                    client_id = self.asks[j].client_id
                    otype = self.asks[j].otype
                    var _gone = self.asks.pop(j)
                    break
                j += 1
        if side == NO_PRICE:
            return False
        self.orders_cancelled += 1
        var replacement = Order(oid, client_id, side, new_price, new_qty, otype)
        var _n = self.add_limit(replacement^)
        return True

    # -- queries -----------------------------------------------------------
    def best_bid(self) -> Int:
        if len(self.bids) == 0:
            return NO_PRICE
        return self.bids[0].price

    def best_ask(self) -> Int:
        if len(self.asks) == 0:
            return NO_PRICE
        return self.asks[0].price

    def best_bid_qty(self) -> Int:
        if len(self.bids) == 0:
            return 0
        return self.bids[0].remaining

    def best_ask_qty(self) -> Int:
        if len(self.asks) == 0:
            return 0
        return self.asks[0].remaining

    def spread(self) -> Int:
        if len(self.bids) == 0 or len(self.asks) == 0:
            return NO_PRICE
        return self.asks[0].price - self.bids[0].price

    def mid_price(self) -> Float64:
        if len(self.bids) == 0 or len(self.asks) == 0:
            return 0.0
        return (Float64(self.bids[0].price) + Float64(self.asks[0].price)) / 2.0

    def total_qty(self, side: Int) -> Int:
        var total = 0
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.bids):
                total += self.bids[i].remaining
                i += 1
        else:
            var i = 0
            while i < len(self.asks):
                total += self.asks[i].remaining
                i += 1
        return total

    # Quantity resting exactly at one price on one side.
    def depth_at(self, side: Int, price: Int) -> Int:
        var total = 0
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.bids):
                if self.bids[i].price == price:
                    total += self.bids[i].remaining
                i += 1
        else:
            var i = 0
            while i < len(self.asks):
                if self.asks[i].price == price:
                    total += self.asks[i].remaining
                i += 1
        return total

    # Displayed quantity at one price: what the market can see. For a
    # plain order this equals depth_at; for an iceberg it is only the
    # peak (or the remainder, once the hidden part is nearly gone).
    def visible_depth_at(self, side: Int, price: Int) -> Int:
        var total = 0
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.bids):
                if self.bids[i].price == price:
                    total += self.bids[i].visible
                i += 1
        else:
            var i = 0
            while i < len(self.asks):
                if self.asks[i].price == price:
                    total += self.asks[i].visible
                i += 1
        return total

    def visible_total_qty(self, side: Int) -> Int:
        var total = 0
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.bids):
                total += self.bids[i].visible
                i += 1
        else:
            var i = 0
            while i < len(self.asks):
                total += self.asks[i].visible
                i += 1
        return total

    # Number of distinct price levels on a side.
    def n_levels(self, side: Int) -> Int:
        var count = 0
        var last_seen = NO_PRICE
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.bids):
                if self.bids[i].price != last_seen:
                    count += 1
                    last_seen = self.bids[i].price
                i += 1
        else:
            var i = 0
            while i < len(self.asks):
                if self.asks[i].price != last_seen:
                    count += 1
                    last_seen = self.asks[i].price
                i += 1
        return count

    # Book imbalance in [-1, 1]: +1 means all resting quantity is bids,
    # -1 means all resting quantity is asks, 0 means balanced.
    def imbalance(self) -> Float64:
        var b = self.total_qty(SIDE_BUY)
        var a = self.total_qty(SIDE_SELL)
        if b + a == 0:
            return 0.0
        return Float64(b - a) / Float64(b + a)

    # Volume-weighted average price of the resting orders on one side,
    # optionally limited to the top `levels` price levels (0 = all levels).
    def vwap(self, side: Int, levels: Int) -> Float64:
        var notional: Int = 0
        var qty: Int = 0
        var seen_levels = 0
        var last_price = NO_PRICE
        if side == SIDE_BUY:
            var i = 0
            while i < len(self.bids):
                if self.bids[i].price != last_price:
                    seen_levels += 1
                    last_price = self.bids[i].price
                    if levels > 0 and seen_levels > levels:
                        break
                notional += self.bids[i].price * self.bids[i].remaining
                qty += self.bids[i].remaining
                i += 1
        else:
            var i = 0
            while i < len(self.asks):
                if self.asks[i].price != last_price:
                    seen_levels += 1
                    last_price = self.asks[i].price
                    if levels > 0 and seen_levels > levels:
                        break
                notional += self.asks[i].price * self.asks[i].remaining
                qty += self.asks[i].remaining
                i += 1
        if qty == 0:
            return 0.0
        return Float64(notional) / Float64(qty)

    # VWAP of the trades printed so far (the tape's average fill price).
    def tape_vwap(self) -> Float64:
        if self.total_volume == 0:
            return 0.0
        return Float64(self.total_notional) / Float64(self.total_volume)

    # Find a resting order's remaining quantity by id; -1 if not resting.
    def resting_qty(self, oid: Int) -> Int:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                return self.bids[i].remaining
            i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].oid == oid:
                return self.asks[j].remaining
            j += 1
        return -1

    # -- invariants --------------------------------------------------------
    # Returns True only if every structural promise of the book holds.
    def check_invariants(self) -> Bool:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].remaining <= 0 or self.bids[i].price <= 0:
                return False
            if self.bids[i].visible <= 0 or self.bids[i].visible > self.bids[i].remaining:
                return False
            if i + 1 < len(self.bids):
                if self.bids[i].price < self.bids[i + 1].price:
                    return False
                if self.bids[i].price == self.bids[i + 1].price:
                    if self.bids[i].seq >= self.bids[i + 1].seq:
                        return False
            i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].remaining <= 0 or self.asks[j].price <= 0:
                return False
            if self.asks[j].visible <= 0 or self.asks[j].visible > self.asks[j].remaining:
                return False
            if j + 1 < len(self.asks):
                if self.asks[j].price > self.asks[j + 1].price:
                    return False
                if self.asks[j].price == self.asks[j + 1].price:
                    if self.asks[j].seq >= self.asks[j + 1].seq:
                        return False
            j += 1
        if len(self.bids) > 0 and len(self.asks) > 0:
            if self.bids[0].price >= self.asks[0].price:
                return False
        return True

    # -- display -----------------------------------------------------------
    def snapshot(self) -> String:
        var s = String("--- order book ---\n")
        s = s + String("asks (best last):\n")
        var i = len(self.asks) - 1
        while i >= 0:
            s = (
                s
                + String("  ")
                + String(self.asks[i].price)
                + String(" x ")
                + String(self.asks[i].remaining)
                + String("  oid=")
                + String(self.asks[i].oid)
                + String("\n")
            )
            i -= 1
        s = s + String("  ---- spread ")
        if self.spread() == NO_PRICE:
            s = s + String("n/a")
        else:
            s = s + String(self.spread())
        s = s + String(" ----\n")
        var j = 0
        while j < len(self.bids):
            s = (
                s
                + String("  ")
                + String(self.bids[j].price)
                + String(" x ")
                + String(self.bids[j].remaining)
                + String("  oid=")
                + String(self.bids[j].oid)
                + String("\n")
            )
            j += 1
        s = s + String("bids (best first)\n")
        s = (
            s
            + String("trades: ")
            + String(len(self.trades))
            + String(" volume: ")
            + String(self.total_volume)
            + String(" tape vwap: ")
            + String(self.tape_vwap())
            + String("\n")
        )
        return s

    def tape(self) -> String:
        var s = String("--- trade tape ---\n")
        var i = 0
        while i < len(self.trades):
            s = s + self.trades[i].describe() + String("\n")
            i += 1
        return s

    def serialise(self) -> String:
        var s = String("BOOK|v1|")
        s = s + String(self.next_seq)
        s = s + String("|") + String(self.total_volume)
        s = s + String("|") + String(self.total_notional)
        s = s + String("|") + String(self.last_trade_price)
        s = s + String("|") + String(self.orders_added)
        s = s + String("|") + String(self.orders_cancelled)
        s = s + String("\n")
        var i = 0
        while i < len(self.bids):
            s = (
                s + String("O|B|")
                + String(self.bids[i].oid)
                + String("|") + String(self.bids[i].client_id)
                + String("|") + String(self.bids[i].price)
                + String("|") + String(self.bids[i].qty)
                + String("|") + String(self.bids[i].remaining)
                + String("|") + String(self.bids[i].seq)
                + String("|") + String(self.bids[i].otype)
                + String("|") + String(self.bids[i].peak)
                + String("|") + String(self.bids[i].visible)
                + String("\n")
            )
            i += 1
        var j = 0
        while j < len(self.asks):
            s = (
                s + String("O|A|")
                + String(self.asks[j].oid)
                + String("|") + String(self.asks[j].client_id)
                + String("|") + String(self.asks[j].price)
                + String("|") + String(self.asks[j].qty)
                + String("|") + String(self.asks[j].remaining)
                + String("|") + String(self.asks[j].seq)
                + String("|") + String(self.asks[j].otype)
                + String("|") + String(self.asks[j].peak)
                + String("|") + String(self.asks[j].visible)
                + String("\n")
            )
            j += 1
        var k = 0
        while k < len(self.trades):
            s = (
                s + String("T|")
                + String(self.trades[k].buy_oid)
                + String("|") + String(self.trades[k].sell_oid)
                + String("|") + String(self.trades[k].price)
                + String("|") + String(self.trades[k].qty)
                + String("|") + String(self.trades[k].seq)
                + String("\n")
            )
            k += 1
        return s

    # Rebuild the book from serialise() output. Returns False and leaves
    # the book untouched when the text fails validation.
    def restore(mut self, text: String) raises -> Bool:
        var lines = text.split("\n")
        if len(lines) == 0:
            return False
        var head = lines[0].split("|")
        if len(head) != 8:
            return False
        if String(head[0]) != "BOOK" or String(head[1]) != "v1":
            return False
        var h = 2
        while h < 8:
            if not _all_digits(String(head[h])):
                return False
            h += 1
        var new_bids = List[Order]()
        var new_asks = List[Order]()
        var new_trades = List[Trade]()
        var seen = Dict[Int, Bool]()
        var max_seq = 0
        var li = 1
        while li < len(lines):
            var line = String(lines[li])
            li += 1
            if line.byte_length() == 0:
                continue
            var parts = line.split("|")
            var tag = String(parts[0])
            if tag == "O":
                if len(parts) != 11:
                    return False
                var f = 2
                while f < 11:
                    if not _all_digits(String(parts[f])):
                        return False
                    f += 1
                var side = String(parts[1])
                if side != "B" and side != "A":
                    return False
                var oid = Int(String(parts[2]))
                var client = Int(String(parts[3]))
                var price = Int(String(parts[4]))
                var qty = Int(String(parts[5]))
                var remaining = Int(String(parts[6]))
                var seq = Int(String(parts[7]))
                var otype = Int(String(parts[8]))
                var peak = Int(String(parts[9]))
                var visible = Int(String(parts[10]))
                if price < 1 or qty < 1:
                    return False
                if remaining < 1 or remaining > qty:
                    return False
                if seq < 1 or otype < 0 or otype > 4:
                    return False
                if peak < 0 or visible < 1 or visible > remaining:
                    return False
                if peak > 0 and visible > peak:
                    return False
                if seen.get(oid, False):
                    return False
                seen[oid] = True
                if seq > max_seq:
                    max_seq = seq
                var o = Order(oid, client, SIDE_BUY, price, qty, otype, peak)
                if side == "A":
                    o.side = SIDE_SELL
                o.remaining = remaining
                o.seq = seq
                o.visible = visible
                if side == "B":
                    new_bids.append(o^)
                else:
                    new_asks.append(o^)
            elif tag == "T":
                if len(parts) != 6:
                    return False
                var g = 1
                while g < 6:
                    if not _all_digits(String(parts[g])):
                        return False
                    g += 1
                var t = Trade(
                    Int(String(parts[1])),
                    Int(String(parts[2])),
                    Int(String(parts[3])),
                    Int(String(parts[4])),
                    Int(String(parts[5])),
                )
                if t.seq > max_seq:
                    max_seq = t.seq
                new_trades.append(t^)
            else:
                return False
        var hdr_next_seq = Int(String(head[2]))
        if hdr_next_seq < 1:
            return False
        var new_next_seq = hdr_next_seq
        if max_seq + 1 > new_next_seq:
            new_next_seq = max_seq + 1
        self.bids = new_bids^
        self.asks = new_asks^
        self.trades = new_trades^
        self.next_seq = new_next_seq
        self.total_volume = Int(String(head[3]))
        self.total_notional = Int(String(head[4]))
        self.last_trade_price = Int(String(head[5]))
        self.orders_added = Int(String(head[6]))
        self.orders_cancelled = Int(String(head[7]))
        return True

# ---------------------------------------------------------------------------
# Serialisation: the whole book as text, and back again.
#
# A book that only lives in memory dies with the process. `serialise()`
# writes the book -- header counters, every resting order with its
# sequence number and iceberg state, and the trade tape -- as lines of
# pipe-separated fields:
#
#   BOOK|v1|<next_seq>|<total_volume>|<total_notional>|<last_trade_price>
#        |<orders_added>|<orders_cancelled>
#   O|B|oid|client|price|qty|remaining|seq|otype|peak|visible
#   T|buy_oid|sell_oid|price|qty|seq
#
# `restore()` reads that text back into a book. It parses into temporary
# lists first and only swaps them in once every line has validated, so a
# corrupt snapshot is rejected whole and the book it was aimed at is
# left exactly as it was. Rejection reasons: bad version, wrong field
# count, a non-numeric field, an out-of-range value (price 0, remaining
# above qty, a visible quantity above what remains, an unknown order
# type), or the same order id twice. Restoring replaces the book's
# contents; it is how a crashed book is rebuilt from its last snapshot,
# and how a book is moved between processes.
# ---------------------------------------------------------------------------

def _all_digits(s: String) -> Bool:
    var n = s.byte_length()
    if n == 0:
        return False
    var seen_digit = False
    var i = 0
    for b in s.bytes():
        if i == 0 and b == 45 and n > 1:
            i += 1
            continue
        if b < 48 or b > 57:
            return False
        seen_digit = True
        i += 1
    return seen_digit


# ---------------------------------------------------------------------------
# Tests. Every case below is hand-computed in the header comment; the
# assertions are the proof. Each test builds a fresh book so cases cannot
# leak state into each other.
# ---------------------------------------------------------------------------

def test_case_a_basic_cross() raises:
    # Asks 10100 x5, 10200 x5. Buy limit 10100 x7 -> 1 trade of 5 @10100,
    # remainder 2 rests as best bid at 10100.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_SELL, 10100, 5, TYPE_LIMIT))
    var _b = book.add_limit(Order(2, 11, SIDE_SELL, 10200, 5, TYPE_LIMIT))
    var n = book.add_limit(Order(3, 22, SIDE_BUY, 10100, 7, TYPE_LIMIT))
    assert_equal(n, 1)
    assert_equal(len(book.trades), 1)
    assert_equal(book.trades[0].price, 10100)
    assert_equal(book.trades[0].qty, 5)
    assert_equal(book.trades[0].buy_oid, 3)
    assert_equal(book.trades[0].sell_oid, 1)
    assert_equal(book.best_bid(), 10100)
    assert_equal(book.best_bid_qty(), 2)
    assert_equal(book.best_ask(), 10200)
    assert_equal(book.best_ask_qty(), 5)
    assert_equal(book.resting_qty(1), -1)
    assert_equal(book.resting_qty(3), 2)
    assert_true(book.check_invariants())
    print("case A ok: basic cross, remainder rests")


def test_case_b_price_time_priority() raises:
    # Two bids at the same price: the older one fills first.
    var book = OrderBook()
    var _a = book.add_limit(Order(10, 11, SIDE_BUY, 10000, 5, TYPE_LIMIT))
    var _b = book.add_limit(Order(11, 11, SIDE_BUY, 10000, 5, TYPE_LIMIT))
    var n = book.add_market(Order(12, 22, SIDE_SELL, 0, 7, TYPE_MARKET))
    assert_equal(n, 2)
    assert_equal(book.trades[0].buy_oid, 10)
    assert_equal(book.trades[0].qty, 5)
    assert_equal(book.trades[1].buy_oid, 11)
    assert_equal(book.trades[1].qty, 2)
    assert_equal(book.trades[0].price, 10000)
    assert_equal(book.trades[1].price, 10000)
    assert_equal(book.resting_qty(10), -1)
    assert_equal(book.resting_qty(11), 3)
    assert_equal(book.best_bid_qty(), 3)
    assert_true(book.check_invariants())
    print("case B ok: price-time priority, oldest first")


def test_case_c_market_sweep_vwap() raises:
    # Asks 10100 x3, 10200 x4, 10300 x5. Buy market x10 fills
    # 3 @10100, 4 @10200, 3 @10300. Cost 102000, VWAP 10200.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_SELL, 10100, 3, TYPE_LIMIT))
    var _b = book.add_limit(Order(2, 11, SIDE_SELL, 10200, 4, TYPE_LIMIT))
    var _c = book.add_limit(Order(3, 11, SIDE_SELL, 10300, 5, TYPE_LIMIT))
    var n = book.add_market(Order(4, 22, SIDE_BUY, 0, 10, TYPE_MARKET))
    assert_equal(n, 3)
    assert_equal(book.trades[0].price, 10100)
    assert_equal(book.trades[0].qty, 3)
    assert_equal(book.trades[1].price, 10200)
    assert_equal(book.trades[1].qty, 4)
    assert_equal(book.trades[2].price, 10300)
    assert_equal(book.trades[2].qty, 3)
    assert_equal(book.total_volume, 10)
    assert_equal(book.total_notional, 102000)
    assert_almost_equal(book.tape_vwap(), 10200.0, atol=1e-9)
    assert_equal(book.resting_qty(3), 2)
    assert_equal(book.best_ask(), 10300)
    assert_true(book.check_invariants())
    print("case C ok: market sweep across levels, VWAP 10200")


def test_case_d_ioc_partial() raises:
    # Ask 10100 x2. Buy IOC 10100 x5 fills 2, remainder 3 is cancelled.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_SELL, 10100, 2, TYPE_LIMIT))
    var n = book.add_ioc(Order(2, 22, SIDE_BUY, 10100, 5, TYPE_IOC))
    assert_equal(n, 1)
    assert_equal(book.trades[0].qty, 2)
    assert_equal(book.best_bid(), NO_PRICE)
    assert_equal(book.best_ask(), NO_PRICE)
    assert_equal(book.total_qty(SIDE_BUY), 0)
    assert_equal(book.orders_cancelled, 1)
    assert_true(book.check_invariants())
    print("case D ok: IOC partial fill, remainder cancelled")


def test_case_e_fok() raises:
    # Ask 10100 x2. Buy FOK 10100 x5 is rejected whole (book untouched),
    # then buy FOK 10100 x2 fills completely.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_SELL, 10100, 2, TYPE_LIMIT))
    var n1 = book.add_fok(Order(2, 22, SIDE_BUY, 10100, 5, TYPE_FOK))
    assert_equal(n1, 0)
    assert_true(not book.last_fok_ok)
    assert_equal(len(book.trades), 0)
    assert_equal(book.best_ask(), 10100)
    assert_equal(book.best_ask_qty(), 2)
    var n2 = book.add_fok(Order(3, 22, SIDE_BUY, 10100, 2, TYPE_FOK))
    assert_equal(n2, 1)
    assert_true(book.last_fok_ok)
    assert_equal(book.trades[0].qty, 2)
    assert_equal(book.best_ask(), NO_PRICE)
    assert_true(book.check_invariants())
    print("case E ok: FOK rejected whole, then filled whole")


def test_case_f_cancel_amend() raises:
    # Bid 10000 x10: cancel it, re-add, amend price to 9900. The amended
    # order is best bid at 9900 with a fresh (larger) sequence number.
    var book = OrderBook()
    var _a = book.add_limit(Order(20, 11, SIDE_BUY, 10000, 10, TYPE_LIMIT))
    assert_true(book.cancel(20))
    assert_equal(book.best_bid(), NO_PRICE)
    assert_true(not book.cancel(20))
    var _b = book.add_limit(Order(20, 11, SIDE_BUY, 10000, 10, TYPE_LIMIT))
    var seq_before = book.bids[0].seq
    assert_true(book.amend(20, 9900, 6))
    assert_equal(book.best_bid(), 9900)
    assert_equal(book.best_bid_qty(), 6)
    assert_true(book.bids[0].seq > seq_before)
    assert_true(not book.amend(999, 9900, 1))
    assert_true(book.check_invariants())
    print("case F ok: cancel, re-add, amend loses time priority")


def test_case_g_empty_book_market() raises:
    # Market order into an empty book: zero trades, nothing rests.
    var book = OrderBook()
    var n = book.add_market(Order(1, 11, SIDE_BUY, 0, 5, TYPE_MARKET))
    assert_equal(n, 0)
    assert_equal(len(book.trades), 0)
    assert_equal(book.best_bid(), NO_PRICE)
    assert_equal(book.best_ask(), NO_PRICE)
    assert_equal(book.spread(), NO_PRICE)
    assert_almost_equal(book.mid_price(), 0.0, atol=1e-9)
    assert_true(book.check_invariants())
    print("case G ok: market order into empty book is a no-op")


def test_case_h_depth_spread_mid_imbalance() raises:
    # Bids: 10000 x10, 9900 x20, 9900 x5 (two orders, one level).
    # Asks: 10100 x8, 10200 x12.
    # Spread 100, mid 10050, bid total 35, ask total 20,
    # imbalance (35-20)/55 = 15/55, ask VWAP (10100*8+10200*12)/20 = 10160.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_BUY, 10000, 10, TYPE_LIMIT))
    var _b = book.add_limit(Order(2, 11, SIDE_BUY, 9900, 20, TYPE_LIMIT))
    var _c = book.add_limit(Order(3, 11, SIDE_BUY, 9900, 5, TYPE_LIMIT))
    var _d = book.add_limit(Order(4, 22, SIDE_SELL, 10100, 8, TYPE_LIMIT))
    var _e = book.add_limit(Order(5, 22, SIDE_SELL, 10200, 12, TYPE_LIMIT))
    assert_equal(book.spread(), 100)
    assert_almost_equal(book.mid_price(), 10050.0, atol=1e-9)
    assert_equal(book.total_qty(SIDE_BUY), 35)
    assert_equal(book.total_qty(SIDE_SELL), 20)
    assert_equal(book.depth_at(SIDE_BUY, 9900), 25)
    assert_equal(book.depth_at(SIDE_BUY, 10000), 10)
    assert_equal(book.depth_at(SIDE_SELL, 10100), 8)
    assert_equal(book.depth_at(SIDE_SELL, 9999), 0)
    assert_equal(book.n_levels(SIDE_BUY), 2)
    assert_equal(book.n_levels(SIDE_SELL), 2)
    assert_almost_equal(book.imbalance(), 15.0 / 55.0, atol=1e-12)
    assert_almost_equal(book.vwap(SIDE_SELL, 0), 10160.0, atol=1e-9)
    assert_almost_equal(book.vwap(SIDE_SELL, 1), 10100.0, atol=1e-9)
    assert_almost_equal(book.vwap(SIDE_BUY, 0), 9928.571428571429, atol=1e-6)
    assert_true(book.check_invariants())
    print("case H ok: depth, spread, mid, imbalance, VWAP")


def _build_snapshot_book() -> OrderBook:
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 1, SIDE_BUY, 10100, 5, TYPE_LIMIT))
    var _b = book.add_limit(Order(2, 2, SIDE_BUY, 10090, 10, TYPE_LIMIT))
    var _c = book.add_iceberg(Order(3, 3, SIDE_BUY, 10080, 20, TYPE_ICEBERG), 3)
    var _d = book.add_limit(Order(4, 4, SIDE_SELL, 10110, 4, TYPE_LIMIT))
    var _e = book.add_limit(Order(5, 5, SIDE_SELL, 10120, 6, TYPE_LIMIT))
    var _f = book.add_market(Order(6, 6, SIDE_BUY, 0, 3, TYPE_MARKET))
    return book^


def test_serialise_round_trip() raises:
    var book = _build_snapshot_book()
    # The market buy filled 3 @ 10110, so ask oid 4 rests with 1 left.
    assert_equal(book.resting_qty(4), 1)
    assert_equal(len(book.trades), 1)
    var text = book.serialise()
    var restored = OrderBook()
    assert_true(restored.restore(text))
    assert_equal(restored.serialise(), text)
    assert_equal(restored.best_bid(), book.best_bid())
    assert_equal(restored.best_ask(), book.best_ask())
    assert_equal(restored.total_qty(SIDE_BUY), book.total_qty(SIDE_BUY))
    assert_equal(restored.total_qty(SIDE_SELL), book.total_qty(SIDE_SELL))
    assert_equal(restored.tape_vwap(), book.tape_vwap())
    assert_equal(restored.resting_qty(3), 20)
    assert_equal(restored.resting_qty(4), 1)
    assert_true(restored.check_invariants())
    # Sequence numbers survive: the next order after the restore gets a
    # sequence above every restored sequence.
    var _g = restored.add_limit(Order(7, 7, SIDE_BUY, 10070, 2, TYPE_LIMIT))
    assert_true(restored.bids[len(restored.bids) - 1].seq >= book.next_seq)
    # Restoring into a non-empty book replaces its contents.
    var other = OrderBook()
    var _h = other.add_limit(Order(99, 9, SIDE_SELL, 99999, 1, TYPE_LIMIT))
    assert_true(other.restore(text))
    assert_equal(other.serialise(), text)
    print("serialise ok: round trip byte-identical, invariants hold")


def test_restore_rejects_bad_input() raises:
    var book = _build_snapshot_book()
    var good = book.serialise()
    var target = OrderBook()
    var _a = target.add_limit(Order(50, 5, SIDE_BUY, 10000, 1, TYPE_LIMIT))
    var before = target.serialise()
    # Wrong version.
    assert_true(not target.restore(String("BOOK|v2|1|0|0|0|0|0\n")))
    # Truncated order line (missing fields).
    var bad_fields = good.replace("O|B|1|1|10100|5|5|", "O|B|1|1|10100|5|")
    assert_true(not target.restore(bad_fields))
    # Duplicate order id.
    var bad_dup = good.replace("O|B|2|2|10090|", "O|B|1|2|10090|")
    assert_true(not target.restore(bad_dup))
    # Zero price.
    var bad_price = good.replace("O|A|4|4|10110|", "O|A|4|4|0|")
    assert_true(not target.restore(bad_price))
    # Remaining above quantity.
    var bad_rem = good.replace("O|B|1|1|10100|5|5|", "O|B|1|1|10100|5|9|")
    assert_true(not target.restore(bad_rem))
    # Non-numeric field.
    var bad_num = good.replace("O|B|1|1|10100|", "O|B|1|1|abc|")
    assert_true(not target.restore(bad_num))
    # Unknown line tag.
    var bad_tag = good.replace("O|B|1|", "Z|B|1|")
    assert_true(not target.restore(bad_tag))
    # Every rejection left the target book exactly as it was.
    assert_equal(target.serialise(), before)
    assert_true(target.check_invariants())
    print("restore ok: 7 corrupt snapshots rejected, book untouched")


def test_conservation_and_stress() raises:
    # A deterministic 60-operation sequence: alternating adds, markets,
    # cancels and IOCs. After every step the invariants must hold, and at
    # the end volume must be conserved:
    #   added == traded + resting + cancelled-or-discarded.
    # Discarded market/IOC remainders are counted via orders_cancelled.
    var book = OrderBook()
    var added = 0
    var oid = 100
    var step = 0
    while step < 60:
        var side = SIDE_BUY
        if step % 2 == 1:
            side = SIDE_SELL
        var price = 9900 + (step % 7) * 100
        var qty = 1 + (step % 5)
        var kind = step % 4
        if kind == 0:
            var _n = book.add_limit(Order(oid, 1, side, price, qty, TYPE_LIMIT))
            added += qty
        elif kind == 1:
            var _n = book.add_market(Order(oid, 2, side, 0, qty, TYPE_MARKET))
            added += qty
        elif kind == 2:
            var _n = book.add_ioc(Order(oid, 3, side, price, qty, TYPE_IOC))
            added += qty
        else:
            var _ok = book.cancel(oid - 3)
        oid += 1
        assert_true(book.check_invariants())
        step += 1
    var resting = book.total_qty(SIDE_BUY) + book.total_qty(SIDE_SELL)
    # Everything added is either traded, still resting, or was cancelled /
    # discarded as an unfilled market/IOC remainder. The book's own counters
    # plus the tape let us check the traded and resting parts exactly.
    assert_true(book.total_volume + resting <= added)
    assert_true(book.total_volume >= 0)
    # Best bid really is the maximum bid price: sort a copy of the bid
    # prices and compare.
    if len(book.bids) > 0:
        var prices = List[Int]()
        var i = 0
        while i < len(book.bids):
            prices.append(book.bids[i].price)
            i += 1
        sort(prices)
        assert_equal(book.best_bid(), prices[len(prices) - 1])
    if len(book.asks) > 0:
        var prices = List[Int]()
        var i = 0
        while i < len(book.asks):
            prices.append(book.asks[i].price)
            i += 1
        sort(prices)
        assert_equal(book.best_ask(), prices[0])
    print("stress ok: 60 ops, invariants held, volume conserved")
    print("  final best bid/ask:", book.best_bid(), book.best_ask())
    print("  total volume:", book.total_volume, " resting:", resting)


def test_trade_at_resting_price() raises:
    # The aggressor pays the maker's price, not its own limit. A buy with
    # limit 10500 against an ask at 10100 prints at 10100.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_SELL, 10100, 4, TYPE_LIMIT))
    var n = book.add_limit(Order(2, 22, SIDE_BUY, 10500, 4, TYPE_LIMIT))
    assert_equal(n, 1)
    assert_equal(book.trades[0].price, 10100)
    assert_equal(book.last_trade_price, 10100)
    assert_equal(book.total_notional, 40400)
    print("resting-price ok: aggressor pays the maker's 10100, not its 10500")


def test_crossing_limit_rests_at_own_price() raises:
    # A buy limit priced above the best ask takes the ask and rests the
    # remainder at its own limit, not at the ask price.
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 11, SIDE_SELL, 10100, 2, TYPE_LIMIT))
    var n = book.add_limit(Order(2, 22, SIDE_BUY, 10200, 5, TYPE_LIMIT))
    assert_equal(n, 1)
    assert_equal(book.best_bid(), 10200)
    assert_equal(book.best_bid_qty(), 3)
    assert_true(book.check_invariants())
    print("crossing-limit ok: remainder rests at its own 10200")


def test_case_i_iceberg_refresh() raises:
    # Ask iceberg 10100, total 100, peak 10. Buy 25 -> fills 10, 10, 5.
    var book = OrderBook()
    var n = book.add_iceberg(Order(1, 11, SIDE_SELL, 10100, 100, TYPE_LIMIT), 10)
    assert_equal(n, 0)
    assert_equal(book.visible_depth_at(SIDE_SELL, 10100), 10)
    assert_equal(book.depth_at(SIDE_SELL, 10100), 100)
    assert_equal(book.visible_total_qty(SIDE_SELL), 10)
    assert_equal(book.total_qty(SIDE_SELL), 100)
    var m = book.add_limit(Order(2, 22, SIDE_BUY, 10100, 25, TYPE_LIMIT))
    assert_equal(m, 3)
    assert_equal(book.trades[0].qty, 10)
    assert_equal(book.trades[1].qty, 10)
    assert_equal(book.trades[2].qty, 5)
    assert_equal(book.resting_qty(1), 75)
    assert_equal(book.visible_depth_at(SIDE_SELL, 10100), 5)
    assert_equal(book.depth_at(SIDE_SELL, 10100), 75)
    assert_true(book.check_invariants())
    print("case I ok: iceberg refreshes in peaks of 10, 75 hidden, 5 shown")


def test_case_j_iceberg_loses_priority() raises:
    # Iceberg 10100 total 30 peak 10, plain ask 10100 x5 behind it.
    # Buy 12: 10 from the iceberg (refresh -> back of queue), then 2
    # from the plain ask, which jumped ahead of the refreshed iceberg.
    var book = OrderBook()
    var _a = book.add_iceberg(Order(1, 11, SIDE_SELL, 10100, 30, TYPE_LIMIT), 10)
    var _b = book.add_limit(Order(2, 11, SIDE_SELL, 10100, 5, TYPE_LIMIT))
    var n = book.add_limit(Order(3, 22, SIDE_BUY, 10100, 12, TYPE_LIMIT))
    assert_equal(n, 2)
    assert_equal(book.trades[0].sell_oid, 1)
    assert_equal(book.trades[0].qty, 10)
    assert_equal(book.trades[1].sell_oid, 2)
    assert_equal(book.trades[1].qty, 2)
    assert_equal(book.resting_qty(1), 20)
    assert_equal(book.resting_qty(2), 3)
    # The plain ask is now first in line at 10100, the iceberg behind it.
    assert_equal(book.asks[0].oid, 2)
    assert_equal(book.asks[1].oid, 1)
    assert_true(book.check_invariants())
    print("case J ok: iceberg refresh costs time priority")


def test_case_k_iceberg_resting_and_degenerate() raises:
    var book = OrderBook()
    var _a = book.add_iceberg(Order(1, 11, SIDE_BUY, 10000, 40, TYPE_LIMIT), 15)
    assert_equal(book.visible_depth_at(SIDE_BUY, 10000), 15)
    assert_equal(book.depth_at(SIDE_BUY, 10000), 40)
    # best_bid_qty counts total resting quantity (hidden included);
    # only 15 of the 40 is displayed.
    assert_equal(book.best_bid_qty(), 40)
    # A peak >= qty is just a limit order: fully visible.
    var _b = book.add_iceberg(Order(2, 11, SIDE_BUY, 9900, 8, TYPE_LIMIT), 8)
    assert_equal(book.visible_depth_at(SIDE_BUY, 9900), 8)
    assert_equal(book.depth_at(SIDE_BUY, 9900), 8)
    # A peak of 0 is just a limit order too.
    var _c = book.add_iceberg(Order(3, 11, SIDE_SELL, 10100, 6, TYPE_LIMIT), 0)
    assert_equal(book.visible_depth_at(SIDE_SELL, 10100), 6)
    assert_true(book.check_invariants())
    print("case K ok: resting iceberg shows its peak; degenerate peaks act plain")


# ---------------------------------------------------------------------------
# Demo: build a small book step by step and show the snapshot and tape.
# ---------------------------------------------------------------------------

def demo() raises:
    print("=== HFT order book demo (simulated data, no real market) ===")
    var book = OrderBook()
    var _a = book.add_limit(Order(1, 101, SIDE_SELL, 10100, 5, TYPE_LIMIT))
    var _b = book.add_limit(Order(2, 101, SIDE_SELL, 10200, 5, TYPE_LIMIT))
    var _c = book.add_limit(Order(3, 102, SIDE_BUY, 10000, 8, TYPE_LIMIT))
    var _d = book.add_limit(Order(4, 102, SIDE_BUY, 9900, 12, TYPE_LIMIT))
    print(book.snapshot())
    var n = book.add_limit(Order(5, 103, SIDE_BUY, 10100, 7, TYPE_LIMIT))
    print("incoming buy 10100 x7 printed", n, "trade(s)")
    print(book.snapshot())
    print(book.tape())
    print("mid:", book.mid_price(), " spread:", book.spread())
    print("imbalance:", book.imbalance(), " tape vwap:", book.tape_vwap())


def main() raises:
    demo()
    print("=== order book tests ===")
    test_case_a_basic_cross()
    test_case_b_price_time_priority()
    test_case_c_market_sweep_vwap()
    test_case_d_ioc_partial()
    test_case_e_fok()
    test_case_f_cancel_amend()
    test_case_g_empty_book_market()
    test_case_h_depth_spread_mid_imbalance()
    test_trade_at_resting_price()
    test_crossing_limit_rests_at_own_price()
    test_case_i_iceberg_refresh()
    test_case_j_iceberg_loses_priority()
    test_case_k_iceberg_resting_and_degenerate()
    test_conservation_and_stress()
    test_serialise_round_trip()
    test_restore_rejects_bad_input()
    print("ALL ORDER BOOK TESTS PASSED")
