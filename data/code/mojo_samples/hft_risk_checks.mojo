# hft_risk_checks.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): pre-trade risk checks.
#
# SIMULATOR ONLY. This file checks invented orders against invented limits
# inside this program. It never connects to an exchange, a broker, or any
# market-data vendor, and no real money is involved anywhere.
#
# Standard library only. No external packages, no Python interop, no network.
#
# Why pre-trade risk exists: a matching engine will happily execute any
# well-formed order it is given, including a typo that buys ten million
# shares or an order priced a hundred times above the market. Real venues
# and brokers therefore run every order through a risk gateway BEFORE it
# reaches the book. An order that fails any check is rejected with a
# reason code; nothing about it touches the market. The checks here are
# the standard set, rebuilt from scratch:
#
#   1. Kill switch: when set, every order is rejected. The kill switch is
#      the big red button for a runaway strategy or a bad deploy.
#   2. Symbol allowlist: only symbols the desk is approved to trade.
#   3. Quantity bounds: a minimum (no dust) and a maximum (no fat finger).
#   4. Price sanity: prices must be positive and below an absurdity cap.
#   5. Price band: the price must sit within +/- band_pct of the reference
#      price (usually the last trade or the mid-price). A 5% band at a
#      reference of 10000 allows 9500..10500 inclusive.
#   6. Order notional: price * quantity must not exceed the per-order cap.
#   7. Position limit: the position AFTER this order (|current + delta|)
#      must not exceed the per-symbol cap. Sells reduce a long position,
#      so they usually pass; a sell that would flip a desk deeply short
#      does not.
#   8. Position notional: |position after| * price must not exceed the cap.
#   9. Duplicate detection: the same client order id seen twice inside
#      the duplicate window is rejected. Retries are normal in real
#      systems; executing the same order twice is not.
#  10. Rate limit: at most N orders per rolling second. A burst above the
#      limit is rejected, which protects the venue and the strategy alike.
#  11. Daily loss limit: if the account's estimated total PnL (realised
#      plus unrealised, marked to the reference price) is below
#      -max_daily_loss, new orders are rejected until the position is
#      flat or the market recovers.
#  12. Cancel throttle: cancels are rate-limited just like orders. A
#      client cancelling hundreds of orders a second is either broken
#      or probing the book; either way the gateway slows it down with
#      REASON_CANCEL_THROTTLE. The throttle is per rolling second, the
#      same window as the order rate limit.
#  13. Audit log: every decision (approve or reject, with its code and
#      timestamp) is kept in a bounded log. After an incident the desk
#      can replay exactly what the gateway decided and when -- which is
#      why the log records the code, not just the outcome.
#
# Checks run in the order above; the first failure wins and its reason is
# recorded. That ordering is deliberate: the kill switch must beat
# everything (it is the emergency stop), and cheap syntactic checks run
# before the ones that need position state.
#
# PnL model (documented so the tests can assert exact numbers): every
# position carries a signed cost basis. A buy adds price*qty to the cost,
# a sell subtracts price*qty. Total PnL for a position is
# qty * reference_price - cost. Example: buy 5 @10100 (cost 50500), then
# the reference moves to 10200: PnL = 5*10200 - 50500 = 500. Sell 3
# @10200: qty 2, cost 50500 - 30600 = 19900, PnL = 2*10200 - 19900 = 500.
# When a position is flat (qty 0) the same formula gives -cost, which is
# exactly the realised PnL. No separate realised/unrealised split is
# needed, and the tests verify the formula both ways.
#
# Timestamps are nanoseconds supplied by the caller. The engine never
# reads a wall clock, which makes every check deterministic and testable:
# the tests drive time explicitly.

from std.testing import assert_equal, assert_true, assert_almost_equal

# ---------------------------------------------------------------------------
# Reject reason codes. 0 means approved.
# ---------------------------------------------------------------------------

comptime REASON_OK = 0
comptime REASON_KILL_SWITCH = 1
comptime REASON_SYMBOL_NOT_ALLOWED = 2
comptime REASON_QTY_INVALID = 3
comptime REASON_QTY_TOO_SMALL = 4
comptime REASON_QTY_TOO_LARGE = 5
comptime REASON_NOTIONAL_TOO_LARGE = 6
comptime REASON_PRICE_NONPOSITIVE = 7
comptime REASON_PRICE_ABSURD = 8
comptime REASON_PRICE_BAND = 9
comptime REASON_POSITION_LIMIT = 10
comptime REASON_POSITION_NOTIONAL = 11
comptime REASON_DUPLICATE_ORDER = 12
comptime REASON_RATE_LIMIT = 13
comptime REASON_DAILY_LOSS = 14
comptime REASON_CANCEL_THROTTLE = 15
comptime N_REASONS = 16


def reason_name(code: Int) -> String:
    if code == REASON_OK:
        return String("OK")
    if code == REASON_KILL_SWITCH:
        return String("KILL_SWITCH")
    if code == REASON_SYMBOL_NOT_ALLOWED:
        return String("SYMBOL_NOT_ALLOWED")
    if code == REASON_QTY_INVALID:
        return String("QTY_INVALID")
    if code == REASON_QTY_TOO_SMALL:
        return String("QTY_TOO_SMALL")
    if code == REASON_QTY_TOO_LARGE:
        return String("QTY_TOO_LARGE")
    if code == REASON_NOTIONAL_TOO_LARGE:
        return String("NOTIONAL_TOO_LARGE")
    if code == REASON_PRICE_NONPOSITIVE:
        return String("PRICE_NONPOSITIVE")
    if code == REASON_PRICE_ABSURD:
        return String("PRICE_ABSURD")
    if code == REASON_PRICE_BAND:
        return String("PRICE_BAND")
    if code == REASON_POSITION_LIMIT:
        return String("POSITION_LIMIT")
    if code == REASON_POSITION_NOTIONAL:
        return String("POSITION_NOTIONAL")
    if code == REASON_DUPLICATE_ORDER:
        return String("DUPLICATE_ORDER")
    if code == REASON_RATE_LIMIT:
        return String("RATE_LIMIT")
    if code == REASON_DAILY_LOSS:
        return String("DAILY_LOSS")
    if code == REASON_CANCEL_THROTTLE:
        return String("CANCEL_THROTTLE")
    return String("UNKNOWN_REASON")


# ---------------------------------------------------------------------------
# RiskLimits: the desk's limits, as one bundle. Prices are integer ticks,
# quantities are whole units, notionals are price*qty (tick-units), and
# times are nanoseconds.
# ---------------------------------------------------------------------------

struct RiskLimits:
    var max_order_qty: Int
    var min_order_qty: Int
    var max_order_notional: Int
    var max_position_qty: Int
    var max_position_notional: Int
    var price_band_pct: Int
    var max_abs_price: Int
    var max_orders_per_sec: Int
    var max_cancels_per_sec: Int
    var duplicate_window_ns: Int
    var max_daily_loss: Int
    var allowed_symbols: List[String]

    def __init__(out self):
        self.max_order_qty = 1000
        self.min_order_qty = 1
        self.max_order_notional = 10_000_000
        self.max_position_qty = 5000
        self.max_position_notional = 50_000_000
        self.price_band_pct = 5
        self.max_abs_price = 1_000_000
        self.max_orders_per_sec = 100
        self.max_cancels_per_sec = 100
        self.duplicate_window_ns = 60_000_000_000
        self.max_daily_loss = 100_000
        self.allowed_symbols = List[String]()

    def describe(self) -> String:
        var s = String("limits: max_qty=") + String(self.max_order_qty)
        s = s + String(" min_qty=") + String(self.min_order_qty)
        s = s + String(" max_notional=") + String(self.max_order_notional)
        s = s + String(" max_pos=") + String(self.max_position_qty)
        s = s + String(" max_pos_notional=") + String(self.max_position_notional)
        s = s + String(" band_pct=") + String(self.price_band_pct)
        s = s + String(" max_price=") + String(self.max_abs_price)
        s = s + String(" max_per_sec=") + String(self.max_orders_per_sec)
        s = s + String(" max_cancels_per_sec=") + String(self.max_cancels_per_sec)
        s = s + String(" max_daily_loss=") + String(self.max_daily_loss)
        return s


# ---------------------------------------------------------------------------
# RiskOrder: one order asking for permission. client_oid is the client's
# own id for the order (used for duplicate detection); ts_ns is the
# arrival time the caller observed.
# ---------------------------------------------------------------------------

struct RiskOrder:
    var client_oid: String
    var client_id: Int
    var symbol: String
    var side: Int
    var price: Int
    var qty: Int
    var ts_ns: Int

    def __init__(
        out self,
        client_oid: String,
        client_id: Int,
        symbol: String,
        side: Int,
        price: Int,
        qty: Int,
        ts_ns: Int,
    ):
        self.client_oid = client_oid
        self.client_id = client_id
        self.symbol = symbol
        self.side = side
        self.price = price
        self.qty = qty
        self.ts_ns = ts_ns

    def describe(self) -> String:
        var side_s = String("SELL")
        if self.side == 0:
            side_s = String("BUY ")
        return (
            String("oid=")
            + self.client_oid
            + String(" client=")
            + String(self.client_id)
            + String(" ")
            + self.symbol
            + String(" ")
            + side_s
            + String(" px=")
            + String(self.price)
            + String(" qty=")
            + String(self.qty)
        )


# ---------------------------------------------------------------------------
# RiskDecision: the answer to one check.
# ---------------------------------------------------------------------------

struct RiskDecision:
    var approved: Bool
    var code: Int
    var reason: String

    def __init__(out self, approved: Bool, code: Int, reason: String):
        self.approved = approved
        self.code = code
        self.reason = reason

    def describe(self) -> String:
        if self.approved:
            return String("APPROVED")
        return String("REJECTED ") + self.reason


def _deny(code: Int) -> RiskDecision:
    return RiskDecision(False, code, reason_name(code))


def _approve() -> RiskDecision:
    return RiskDecision(True, REASON_OK, reason_name(REASON_OK))


# ---------------------------------------------------------------------------
# RiskEngine.
# ---------------------------------------------------------------------------

struct RiskEngine:
    var limits: RiskLimits
    var kill_switch: Bool
    # Reference prices, per symbol (parallel lists).
    var ref_symbols: List[String]
    var ref_prices: List[Int]
    # Positions, per (client, symbol) (parallel lists).
    var pos_clients: List[Int]
    var pos_symbols: List[String]
    var pos_qty: List[Int]
    var pos_cost: List[Int]
    # Duplicate detection: client order ids and when they were seen.
    var seen_oids: List[String]
    var seen_ts: List[Int]
    # Rate limiting: arrival timestamps of approved-or-checked orders.
    var rate_ts: List[Int]
    # Cancel throttle: arrival timestamps of cancels.
    var cancel_ts: List[Int]
    # Audit log: the last decisions, newest last (bounded by pruning
    # to the most recent 1000 entries).
    var audit_codes: List[Int]
    var audit_ts: List[Int]
    var audit_oids: List[String]
    # Counters.
    var n_checked: Int
    var n_approved: Int
    var n_rejected: Int
    var reject_counts: List[Int]
    var decision_codes: List[Int]
    var decision_oids: List[String]

    def __init__(out self):
        self.limits = RiskLimits()
        self.kill_switch = False
        self.ref_symbols = List[String]()
        self.ref_prices = List[Int]()
        self.pos_clients = List[Int]()
        self.pos_symbols = List[String]()
        self.pos_qty = List[Int]()
        self.pos_cost = List[Int]()
        self.seen_oids = List[String]()
        self.seen_ts = List[Int]()
        self.rate_ts = List[Int]()
        self.cancel_ts = List[Int]()
        self.audit_codes = List[Int]()
        self.audit_ts = List[Int]()
        self.audit_oids = List[String]()
        self.n_checked = 0
        self.n_approved = 0
        self.n_rejected = 0
        self.reject_counts = List[Int]()
        var i = 0
        while i < N_REASONS:
            self.reject_counts.append(0)
            i += 1
        self.decision_codes = List[Int]()
        self.decision_oids = List[String]()

    # -- configuration -------------------------------------------------------
    def set_kill_switch(mut self, on: Bool):
        self.kill_switch = on

    def allow_symbol(mut self, sym: String):
        var i = 0
        while i < len(self.limits.allowed_symbols):
            if self.limits.allowed_symbols[i] == sym:
                return
            i += 1
        self.limits.allowed_symbols.append(sym)

    def set_ref_price(mut self, sym: String, price: Int):
        var i = 0
        while i < len(self.ref_symbols):
            if self.ref_symbols[i] == sym:
                self.ref_prices[i] = price
                return
            i += 1
        self.ref_symbols.append(sym)
        self.ref_prices.append(price)

    def ref_price(self, sym: String) -> Int:
        var i = 0
        while i < len(self.ref_symbols):
            if self.ref_symbols[i] == sym:
                return self.ref_prices[i]
            i += 1
        return 0

    def has_ref_price(self, sym: String) -> Bool:
        return self.ref_price(sym) != 0

    def set_max_order_qty(mut self, v: Int):
        self.limits.max_order_qty = v

    def set_min_order_qty(mut self, v: Int):
        self.limits.min_order_qty = v

    def set_max_order_notional(mut self, v: Int):
        self.limits.max_order_notional = v

    def set_max_position_qty(mut self, v: Int):
        self.limits.max_position_qty = v

    def set_max_position_notional(mut self, v: Int):
        self.limits.max_position_notional = v

    def set_price_band_pct(mut self, v: Int):
        self.limits.price_band_pct = v

    def set_max_abs_price(mut self, v: Int):
        self.limits.max_abs_price = v

    def set_max_orders_per_sec(mut self, v: Int):
        self.limits.max_orders_per_sec = v

    def set_max_cancels_per_sec(mut self, v: Int):
        self.limits.max_cancels_per_sec = v

    def set_duplicate_window_ns(mut self, v: Int):
        self.limits.duplicate_window_ns = v

    def set_max_daily_loss(mut self, v: Int):
        self.limits.max_daily_loss = v

    # -- positions -----------------------------------------------------------
    def _pos_slot(mut self, client_id: Int, sym: String) -> Int:
        var i = 0
        while i < len(self.pos_clients):
            if self.pos_clients[i] == client_id and self.pos_symbols[i] == sym:
                return i
            i += 1
        self.pos_clients.append(client_id)
        self.pos_symbols.append(sym)
        self.pos_qty.append(0)
        self.pos_cost.append(0)
        return len(self.pos_clients) - 1

    def position_qty(self, client_id: Int, sym: String) -> Int:
        var i = 0
        while i < len(self.pos_clients):
            if self.pos_clients[i] == client_id and self.pos_symbols[i] == sym:
                return self.pos_qty[i]
            i += 1
        return 0

    def position_cost(self, client_id: Int, sym: String) -> Int:
        var i = 0
        while i < len(self.pos_clients):
            if self.pos_clients[i] == client_id and self.pos_symbols[i] == sym:
                return self.pos_cost[i]
            i += 1
        return 0

    # Total PnL of one position, marked to the reference price. When there
    # is no reference price the position is valued at its cost basis, so
    # PnL reads as zero rather than as a wild guess.
    def position_pnl(self, client_id: Int, sym: String) -> Int:
        var qty = self.position_qty(client_id, sym)
        var cost = self.position_cost(client_id, sym)
        var ref_px = self.ref_price(sym)
        if ref_px == 0:
            return 0
        return qty * ref_px - cost

    # Total PnL of a client across every symbol it holds.
    def account_pnl(self, client_id: Int) -> Int:
        var total = 0
        var i = 0
        while i < len(self.pos_clients):
            if self.pos_clients[i] == client_id:
                total += self.position_pnl(client_id, self.pos_symbols[i])
            i += 1
        return total

    # Record a fill: update quantity and signed cost basis. side 0 = buy.
    def apply_fill(mut self, client_id: Int, sym: String, side: Int, price: Int, qty: Int):
        var slot = self._pos_slot(client_id, sym)
        if side == 0:
            self.pos_qty[slot] += qty
            self.pos_cost[slot] += price * qty
        else:
            self.pos_qty[slot] -= qty
            self.pos_cost[slot] -= price * qty

    # -- duplicate / rate-limit bookkeeping ----------------------------------
    def _prune_seen(mut self, now_ns: Int):
        var cutoff = now_ns - self.limits.duplicate_window_ns
        while len(self.seen_ts) > 0 and self.seen_ts[0] < cutoff:
            var _old_oid = self.seen_oids.pop(0)
            var _old_ts = self.seen_ts.pop(0)

    def _is_duplicate(mut self, client_oid: String, now_ns: Int) -> Bool:
        self._prune_seen(now_ns)
        var i = 0
        while i < len(self.seen_oids):
            if self.seen_oids[i] == client_oid:
                return True
            i += 1
        return False

    def _record_seen(mut self, client_oid: String, ts_ns: Int):
        self.seen_oids.append(client_oid)
        self.seen_ts.append(ts_ns)

    def _prune_rate(mut self, now_ns: Int):
        var cutoff = now_ns - 1_000_000_000
        while len(self.rate_ts) > 0 and self.rate_ts[0] < cutoff:
            var _old = self.rate_ts.pop(0)

    def _rate_exceeded(mut self, now_ns: Int) -> Bool:
        self._prune_rate(now_ns)
        return len(self.rate_ts) >= self.limits.max_orders_per_sec

    def _record_rate(mut self, ts_ns: Int):
        self.rate_ts.append(ts_ns)

    # Cancel throttle: at most max_cancels_per_sec cancels per rolling
    # second. Returns a decision so the caller gets the same shape of
    # answer as check().
    def check_cancel(mut self, client_oid: String, ts_ns: Int) -> RiskDecision:
        var cutoff = ts_ns - 1_000_000_000
        while len(self.cancel_ts) > 0 and self.cancel_ts[0] < cutoff:
            var _old = self.cancel_ts.pop(0)
        var result = _approve()
        if len(self.cancel_ts) >= self.limits.max_cancels_per_sec:
            result = _deny(REASON_CANCEL_THROTTLE)
        else:
            self.cancel_ts.append(ts_ns)
        self._audit(result.code, ts_ns, client_oid)
        return result^

    def _audit(mut self, code: Int, ts_ns: Int, client_oid: String):
        if len(self.audit_codes) >= 1000:
            var _c = self.audit_codes.pop(0)
            var _t = self.audit_ts.pop(0)
            var _o = self.audit_oids.pop(0)
        self.audit_codes.append(code)
        self.audit_ts.append(ts_ns)
        self.audit_oids.append(client_oid)

    # -- the check -------------------------------------------------------------
    # Runs the checks in documented order; the first failure wins. An
    # approved order is recorded for duplicate detection and rate
    # limiting; a rejected order is counted but its client id is not
    # reserved (a retry with the same id after fixing the problem must be
    # allowed to pass the duplicate check).
    def check(mut self, order: RiskOrder) -> RiskDecision:
        self.n_checked += 1
        var result = self._check_inner(order)
        self.decision_codes.append(result.code)
        self.decision_oids.append(order.client_oid)
        self._audit(result.code, order.ts_ns, order.client_oid)
        if result.approved:
            self.n_approved += 1
            self._record_seen(order.client_oid, order.ts_ns)
            self._record_rate(order.ts_ns)
        else:
            self.n_rejected += 1
            self.reject_counts[result.code] += 1
        return result^

    def _check_inner(mut self, order: RiskOrder) -> RiskDecision:
        if self.kill_switch:
            return _deny(REASON_KILL_SWITCH)
        if len(self.limits.allowed_symbols) > 0:
            var allowed = False
            var i = 0
            while i < len(self.limits.allowed_symbols):
                if self.limits.allowed_symbols[i] == order.symbol:
                    allowed = True
                    break
                i += 1
            if not allowed:
                return _deny(REASON_SYMBOL_NOT_ALLOWED)
        if order.qty <= 0:
            return _deny(REASON_QTY_INVALID)
        if order.qty < self.limits.min_order_qty:
            return _deny(REASON_QTY_TOO_SMALL)
        if order.qty > self.limits.max_order_qty:
            return _deny(REASON_QTY_TOO_LARGE)
        if order.price <= 0:
            return _deny(REASON_PRICE_NONPOSITIVE)
        if order.price > self.limits.max_abs_price:
            return _deny(REASON_PRICE_ABSURD)
        if self.has_ref_price(order.symbol):
            var ref_px = self.ref_price(order.symbol)
            var band_ticks = ref_px * self.limits.price_band_pct // 100
            if order.price < ref_px - band_ticks or order.price > ref_px + band_ticks:
                return _deny(REASON_PRICE_BAND)
        var notional = order.price * order.qty
        if notional > self.limits.max_order_notional:
            return _deny(REASON_NOTIONAL_TOO_LARGE)
        var delta = order.qty
        if order.side != 0:
            delta = -order.qty
        var pos_after = self.position_qty(order.client_id, order.symbol) + delta
        if pos_after > self.limits.max_position_qty or pos_after < -self.limits.max_position_qty:
            return _deny(REASON_POSITION_LIMIT)
        var pos_notional = pos_after * order.price
        if pos_notional < 0:
            pos_notional = -pos_notional
        if pos_notional > self.limits.max_position_notional:
            return _deny(REASON_POSITION_NOTIONAL)
        if self._is_duplicate(order.client_oid, order.ts_ns):
            return _deny(REASON_DUPLICATE_ORDER)
        if self._rate_exceeded(order.ts_ns):
            return _deny(REASON_RATE_LIMIT)
        if self.account_pnl(order.client_id) < -self.limits.max_daily_loss:
            return _deny(REASON_DAILY_LOSS)
        return _approve()

    # -- reporting ---------------------------------------------------------------
    def summary(self) -> String:
        var s = String("risk summary: checked=") + String(self.n_checked)
        s = s + String(" approved=") + String(self.n_approved)
        s = s + String(" rejected=") + String(self.n_rejected)
        s = s + String(" kill_switch=")
        if self.kill_switch:
            s = s + String("ON")
        else:
            s = s + String("off")
        return s

    def reject_breakdown(self) -> String:
        var s = String("rejects by reason:")
        var code = 1
        while code < N_REASONS:
            if self.reject_counts[code] > 0:
                s = s + String(" ") + reason_name(code) + String("=") + String(
                    self.reject_counts[code]
                )
            code += 1
        if self.n_rejected == 0:
            s = s + String(" none")
        return s

# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------

def fresh_engine() -> RiskEngine:
    var eng = RiskEngine()
    eng.allow_symbol(String("AAPL"))
    eng.set_ref_price(String("AAPL"), 10000)
    eng.set_max_order_qty(1000)
    eng.set_min_order_qty(1)
    eng.set_max_order_notional(1_000_000)
    eng.set_max_position_qty(100)
    eng.set_max_position_notional(1_000_000)
    eng.set_price_band_pct(5)
    eng.set_max_abs_price(1_000_000)
    eng.set_max_orders_per_sec(100)
    eng.set_max_cancels_per_sec(100)
    eng.set_duplicate_window_ns(60_000_000_000)
    eng.set_max_daily_loss(100_000)
    return eng^


def test_pass() raises:
    var eng = fresh_engine()
    var o = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 100, 1000)
    var d = eng.check(o)
    assert_true(d.approved)
    assert_equal(d.code, REASON_OK)
    assert_equal(eng.n_checked, 1)
    assert_equal(eng.n_approved, 1)
    assert_equal(eng.n_rejected, 0)
    print("pass ok: a clean order is approved")


def test_kill_switch() raises:
    var eng = fresh_engine()
    eng.set_kill_switch(True)
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 10, 1000)
    var d1 = eng.check(o1)
    assert_true(not d1.approved)
    assert_equal(d1.code, REASON_KILL_SWITCH)
    assert_equal(d1.reason, String("KILL_SWITCH"))
    eng.set_kill_switch(False)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10000, 10, 2000)
    var d2 = eng.check(o2)
    assert_true(d2.approved)
    print("kill switch ok: blocks everything, then releases")


def test_symbol_allowlist() raises:
    var eng = fresh_engine()
    var o1 = RiskOrder(String("C-1"), 1, String("MSFT"), 0, 10000, 10, 1000)
    var d1 = eng.check(o1)
    assert_true(not d1.approved)
    assert_equal(d1.code, REASON_SYMBOL_NOT_ALLOWED)
    eng.allow_symbol(String("MSFT"))
    eng.set_ref_price(String("MSFT"), 20000)
    var o2 = RiskOrder(String("C-2"), 1, String("MSFT"), 0, 20000, 10, 2000)
    var d2 = eng.check(o2)
    assert_true(d2.approved)
    print("allowlist ok: unknown symbol rejected, allowed symbol passes")


def test_qty_bounds() raises:
    var eng = fresh_engine()
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 0, 1000)
    assert_equal(eng.check(o1).code, REASON_QTY_INVALID)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10000, 1001, 2000)
    assert_equal(eng.check(o2).code, REASON_QTY_TOO_LARGE)
    eng.set_min_order_qty(10)
    var o3 = RiskOrder(String("C-3"), 1, String("AAPL"), 0, 10000, 5, 3000)
    assert_equal(eng.check(o3).code, REASON_QTY_TOO_SMALL)
    var o4 = RiskOrder(String("C-4"), 1, String("AAPL"), 0, 10000, 10, 4000)
    assert_true(eng.check(o4).approved)
    print("qty bounds ok: zero, too big, too small, and the exact minimum")


def test_price_sanity() raises:
    var eng = fresh_engine()
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 0, 10, 1000)
    assert_equal(eng.check(o1).code, REASON_PRICE_NONPOSITIVE)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, -5, 10, 2000)
    assert_equal(eng.check(o2).code, REASON_PRICE_NONPOSITIVE)
    var o3 = RiskOrder(String("C-3"), 1, String("AAPL"), 0, 1_000_001, 10, 3000)
    assert_equal(eng.check(o3).code, REASON_PRICE_ABSURD)
    print("price sanity ok: zero, negative, and absurd prices rejected")


def test_price_band() raises:
    var eng = fresh_engine()
    # Reference 10000, band 5% -> allowed 9500..10500 inclusive.
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 9500, 10, 1000)
    assert_true(eng.check(o1).approved)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10500, 10, 2000)
    assert_true(eng.check(o2).approved)
    var o3 = RiskOrder(String("C-3"), 1, String("AAPL"), 0, 9499, 10, 3000)
    assert_equal(eng.check(o3).code, REASON_PRICE_BAND)
    var o4 = RiskOrder(String("C-4"), 1, String("AAPL"), 0, 10501, 10, 4000)
    assert_equal(eng.check(o4).code, REASON_PRICE_BAND)
    # Integer edge: reference 10001, band 5% -> band ticks = 50005//100
    # = 500, so the top of the band is 10501 inclusive.
    eng.set_ref_price(String("AAPL"), 10001)
    var o5 = RiskOrder(String("C-5"), 1, String("AAPL"), 0, 10501, 10, 5000)
    assert_true(eng.check(o5).approved)
    var o6 = RiskOrder(String("C-6"), 1, String("AAPL"), 0, 10502, 10, 6000)
    assert_equal(eng.check(o6).code, REASON_PRICE_BAND)
    print("price band ok: edges inclusive, one tick outside rejected")


def test_notional() raises:
    var eng = fresh_engine()
    # 10000 x 100 = 1,000,000, exactly the cap: passes.
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 100, 1000)
    assert_true(eng.check(o1).approved)
    # 10000 x 101 = 1,010,000: over the cap.
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10000, 101, 2000)
    assert_equal(eng.check(o2).code, REASON_NOTIONAL_TOO_LARGE)
    print("notional ok: exact cap passes, one unit over is rejected")


def test_position_limit() raises:
    var eng = fresh_engine()
    eng.apply_fill(1, String("AAPL"), 0, 10000, 90)
    assert_equal(eng.position_qty(1, String("AAPL")), 90)
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 11, 1000)
    assert_equal(eng.check(o1).code, REASON_POSITION_LIMIT)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10000, 10, 2000)
    assert_true(eng.check(o2).approved)
    var o3 = RiskOrder(String("C-3"), 1, String("AAPL"), 1, 10000, 5, 3000)
    assert_true(eng.check(o3).approved)
    # Short side: -90, selling 11 more would reach -101.
    eng.apply_fill(2, String("AAPL"), 1, 10000, 90)
    var o4 = RiskOrder(String("C-4"), 2, String("AAPL"), 1, 10000, 11, 4000)
    assert_equal(eng.check(o4).code, REASON_POSITION_LIMIT)
    var o5 = RiskOrder(String("C-5"), 2, String("AAPL"), 1, 10000, 10, 5000)
    assert_true(eng.check(o5).approved)
    print("position limit ok: long and short, exact cap passes")


def test_position_notional() raises:
    var eng = fresh_engine()
    eng.set_max_order_notional(100_000_000)
    eng.set_max_position_qty(10000)
    # Position after: 101 units at 10000 = 1,010,000 notional, over the
    # 1,000,000 position-notional cap, while the order itself is fine.
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 101, 1000)
    assert_equal(eng.check(o1).code, REASON_POSITION_NOTIONAL)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10000, 100, 2000)
    assert_true(eng.check(o2).approved)
    print("position notional ok: big position blocked even when order is small")


def test_duplicate_detection() raises:
    var eng = fresh_engine()
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 10, 1000)
    assert_true(eng.check(o1).approved)
    var o2 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 10, 2000)
    assert_equal(eng.check(o2).code, REASON_DUPLICATE_ORDER)
    # After the 60-second window the same id is usable again.
    var o3 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 10, 61_000_001_000)
    assert_true(eng.check(o3).approved)
    var o4 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10000, 10, 3000)
    assert_true(eng.check(o4).approved)
    print("duplicate ok: same id inside the window rejected, later allowed")


def test_rate_limit() raises:
    var eng = fresh_engine()
    eng.set_max_orders_per_sec(3)
    var base = 1_000_000_000
    var i = 0
    while i < 3:
        var o = RiskOrder(
            String("R-") + String(i), 1, String("AAPL"), 0, 10000, 1, base + i
        )
        assert_true(eng.check(o).approved)
        i += 1
    var o4 = RiskOrder(String("R-3"), 1, String("AAPL"), 0, 10000, 1, base + 3)
    assert_equal(eng.check(o4).code, REASON_RATE_LIMIT)
    # One second later the oldest entry slides out of the window.
    var o5 = RiskOrder(String("R-4"), 1, String("AAPL"), 0, 10000, 1, base + 1_000_000_001)
    assert_true(eng.check(o5).approved)
    print("rate limit ok: 3 per second, 4th rejected, window slides")


def test_daily_loss() raises:
    var eng = fresh_engine()
    eng.set_max_daily_loss(5000)
    eng.apply_fill(1, String("AAPL"), 0, 10000, 10)
    eng.set_ref_price(String("AAPL"), 9000)
    # PnL = 10*9000 - 100000 = -10000, worse than -5000.
    assert_equal(eng.account_pnl(1), -10000)
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 9000, 1, 1000)
    assert_equal(eng.check(o1).code, REASON_DAILY_LOSS)
    eng.set_ref_price(String("AAPL"), 9900)
    # PnL = 10*9900 - 100000 = -1000, inside the limit.
    assert_equal(eng.account_pnl(1), -1000)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 9900, 1, 2000)
    assert_true(eng.check(o2).approved)
    print("daily loss ok: losing account blocked, recovering account passes")


def test_pnl_formula() raises:
    var eng = fresh_engine()
    eng.apply_fill(1, String("AAPL"), 0, 10100, 5)
    assert_equal(eng.position_qty(1, String("AAPL")), 5)
    assert_equal(eng.position_cost(1, String("AAPL")), 50500)
    eng.set_ref_price(String("AAPL"), 10200)
    assert_equal(eng.position_pnl(1, String("AAPL")), 500)
    eng.apply_fill(1, String("AAPL"), 1, 10200, 3)
    assert_equal(eng.position_qty(1, String("AAPL")), 2)
    assert_equal(eng.position_cost(1, String("AAPL")), 19900)
    assert_equal(eng.position_pnl(1, String("AAPL")), 500)
    eng.apply_fill(1, String("AAPL"), 1, 10300, 2)
    assert_equal(eng.position_qty(1, String("AAPL")), 0)
    assert_equal(eng.position_cost(1, String("AAPL")), -700)
    # Flat: PnL = 0*ref - (-700) = 700 realised. Bought 50500, sold
    # 30600 + 20600 = 51200, profit 700. The formula agrees.
    assert_equal(eng.position_pnl(1, String("AAPL")), 700)
    print("pnl formula ok: unrealised and realised agree with hand math")


def test_no_ref_skips_band() raises:
    var eng = fresh_engine()
    eng.allow_symbol(String("MSFT"))
    # No reference price for MSFT: the band check is skipped rather than
    # guessed, so a far-from-anything price still passes the other checks.
    var o = RiskOrder(String("C-1"), 1, String("MSFT"), 0, 500000, 1, 1000)
    assert_true(eng.check(o).approved)
    print("no-ref ok: band skipped when there is no reference price")


def test_cancel_throttle() raises:
    var eng = fresh_engine()
    eng.set_max_cancels_per_sec(3)
    var base = 1_000_000_000
    var i = 0
    while i < 3:
        var d = eng.check_cancel(String("X-") + String(i), base + i)
        assert_true(d.approved)
        i += 1
    var d4 = eng.check_cancel(String("X-3"), base + 3)
    assert_true(not d4.approved)
    assert_equal(d4.code, REASON_CANCEL_THROTTLE)
    # One second later the oldest cancel slides out of the window.
    var d5 = eng.check_cancel(String("X-4"), base + 1_000_000_001)
    assert_true(d5.approved)
    print("cancel throttle ok: 3 per second, 4th rejected, window slides")


def test_audit_log() raises:
    var eng = fresh_engine()
    var o1 = RiskOrder(String("A-1"), 1, String("AAPL"), 0, 10000, 10, 1000)
    var _d1 = eng.check(o1)
    var o2 = RiskOrder(String("A-2"), 1, String("AAPL"), 0, 10501, 10, 2000)
    var _d2 = eng.check(o2)
    var _d3 = eng.check_cancel(String("A-3"), 3000)
    assert_equal(len(eng.audit_codes), 3)
    assert_equal(eng.audit_codes[0], REASON_OK)
    assert_equal(eng.audit_codes[1], REASON_PRICE_BAND)
    assert_equal(eng.audit_codes[2], REASON_OK)
    assert_equal(eng.audit_ts[0], 1000)
    assert_equal(eng.audit_ts[1], 2000)
    assert_equal(eng.audit_ts[2], 3000)
    assert_equal(eng.audit_oids[0], String("A-1"))
    assert_equal(eng.audit_oids[1], String("A-2"))
    assert_equal(eng.audit_oids[2], String("A-3"))
    print("audit log ok: every decision recorded with code, time, and id")


def test_reject_breakdown() raises:
    var eng = fresh_engine()
    eng.set_kill_switch(True)
    var o1 = RiskOrder(String("C-1"), 1, String("AAPL"), 0, 10000, 10, 1000)
    assert_equal(eng.check(o1).code, REASON_KILL_SWITCH)
    eng.set_kill_switch(False)
    var o2 = RiskOrder(String("C-2"), 1, String("AAPL"), 0, 10501, 10, 2000)
    assert_equal(eng.check(o2).code, REASON_PRICE_BAND)
    var o3 = RiskOrder(String("C-3"), 1, String("AAPL"), 0, 10000, 2000, 3000)
    assert_equal(eng.check(o3).code, REASON_QTY_TOO_LARGE)
    var o4 = RiskOrder(String("C-4"), 1, String("AAPL"), 0, 10000, 10, 4000)
    assert_true(eng.check(o4).approved)
    assert_equal(eng.n_checked, 4)
    assert_equal(eng.n_approved, 1)
    assert_equal(eng.n_rejected, 3)
    assert_equal(eng.reject_counts[REASON_KILL_SWITCH], 1)
    assert_equal(eng.reject_counts[REASON_PRICE_BAND], 1)
    assert_equal(eng.reject_counts[REASON_QTY_TOO_LARGE], 1)
    assert_equal(eng.reject_counts[REASON_OK], 0)
    print("breakdown ok: per-reason counts are exact")
    print("  " + eng.summary())
    print("  " + eng.reject_breakdown())


# ---------------------------------------------------------------------------
# Demo: a batch of orders through the gateway, good and bad.
# ---------------------------------------------------------------------------

def demo() raises:
    print("=== HFT pre-trade risk demo (simulated data, no real market) ===")
    var eng = fresh_engine()
    print(eng.limits.describe())
    var orders = List[RiskOrder]()
    orders.append(RiskOrder(String("D-1"), 1, String("AAPL"), 0, 10000, 100, 1000))
    orders.append(RiskOrder(String("D-2"), 1, String("AAPL"), 0, 12000, 100, 2000))
    orders.append(RiskOrder(String("D-3"), 1, String("AAPL"), 0, 10000, 5000, 3000))
    orders.append(RiskOrder(String("D-4"), 1, String("MSFT"), 0, 10000, 10, 4000))
    orders.append(RiskOrder(String("D-1"), 1, String("AAPL"), 0, 10000, 100, 5000))
    orders.append(RiskOrder(String("D-5"), 1, String("AAPL"), 1, 10000, 40, 6000))
    var i = 0
    while i < len(orders):
        var d = eng.check(orders[i])
        print("  ", orders[i].describe(), "->", d.describe())
        i += 1
    eng.apply_fill(1, String("AAPL"), 0, 10000, 100)
    print("  after fill: AAPL position", eng.position_qty(1, String("AAPL")))
    print(eng.summary())
    print(eng.reject_breakdown())


def main() raises:
    demo()
    print("=== pre-trade risk tests ===")
    test_pass()
    test_kill_switch()
    test_symbol_allowlist()
    test_qty_bounds()
    test_price_sanity()
    test_price_band()
    test_notional()
    test_position_limit()
    test_position_notional()
    test_duplicate_detection()
    test_rate_limit()
    test_daily_loss()
    test_pnl_formula()
    test_no_ref_skips_band()
    test_cancel_throttle()
    test_audit_log()
    test_reject_breakdown()
    print("ALL PRE-TRADE RISK TESTS PASSED")
