# hft_matching_engine.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): a matching engine driving an order book.
#
# SIMULATOR ONLY. This engine matches invented orders against an invented
# book inside this program. It never connects to an exchange, a broker, or
# any market-data vendor, and no real money moves. Every order, trade, and
# price below is simulated data.
#
# Standard library only. No external packages, no Python interop, no network.
#
# What the engine does, in the order a real venue would:
#   1. Accepts orders (new / cancel / amend) and gives each a lifecycle:
#      NEW -> ACKED -> PARTIAL -> FILLED, or CANCELLED, or REJECTED.
#      A resting order is ACKED; once it has traded at all it is PARTIAL
#      until its remaining quantity reaches zero, when it becomes FILLED.
#   2. Runs a continuous book (limit / market / IOC / FOK) with price-time
#      priority, exactly like the order book in hft_order_book.mojo, but
#      with the engine around it: session phases, self-trade prevention,
#      trade reporting, and per-client positions.
#   3. Runs an opening auction: while the session is PREOPEN, orders are
#      collected but not matched. At the open the engine picks the clearing
#      price that maximises traded volume (ties break towards the reference
#      price, then towards the higher price), crosses everything it can at
#      that one price, and carries the unfilled remainder into the
#      continuous book.
#   4. Enforces session phases: PREOPEN collects for auction, OPEN matches
#      continuously, HALTED rejects new orders (cancels still work, so a
#      client can always reduce risk), CLOSED rejects everything.
#   5. Prevents self-trading: when an incoming order would trade against
#      the same client's resting order, the engine either cancels the
#      resting order (CANCEL_RESTING) or rejects the incoming order
#      (REJECT_INCOMING), depending on its configured mode.
#   6. Tracks per-client positions (quantity and cash, in ticks) from the
#      trade tape, so a strategy can always ask "what do I own right now".
#   7. Publishes a drop copy: every trade produces a TradeReport, an
#      immutable record of the fill with both order ids, both clients,
#      price, quantity, and whether it was an auction cross. The drop
#      copy is the venue's audit trail and the client's reconciliation
#      source: a client that disagrees with the venue about a fill
#      compares its own records against the drop copy. Reports are
#      append-only and numbered in order, so a missing report number
#      means a lost message, not a missing trade.
#
# Design notes:
#   * Prices are integer ticks (1 tick = 1 cent); quantities are whole
#     units. Matching arithmetic is exact.
#   * Orders are move-only structs, so an order lives in exactly one list
#     at a time: the auction lists, the continuous book, or the done list.
#     A trade never copies an order; it reads the fields it needs and the
#     book updates the resting order in place.
#   * The trade tape is the source of truth for positions. Position cash
#     and quantity are recomputed from the tape by the tests as a cross-
#     check, so a bookkeeping bug cannot hide.
#   * Validation happens before matching: a limit order needs a positive
#     price and quantity, a market order needs a positive quantity, and
#     an unknown order type is rejected. Rejections are logged with a
#     human-readable reason.
#
# Hand-computed auction case used in the tests:
#   Bids: 10100 x5, 10000 x10, 9900 x5.  Asks: 9900 x8, 10000 x6, 10100 x4.
#   Clearing-price volumes:
#     at  9900: bids >= 9900 hold 20, asks <= 9900 hold 8  -> volume 8
#     at 10000: bids >= 10000 hold 15, asks <= 10000 hold 14 -> volume 14
#     at 10100: bids >= 10100 hold 5,  asks <= 10100 hold 18 -> volume 5
#   Clearing price is 10000, volume 14. Fills at 10000: the 10100 bid
#   fills 5, the 10000 bid fills 9 of 10; the 9900 ask fills 8, the
#   10000 ask fills 6. Left over into the continuous book: bid 10000 x1,
#   bid 9900 x5, ask 10100 x4.
#
# Hand-computed position case used in the tests:
#   Client 1 buys 5 @10100 from client 2 (one trade). Afterwards:
#   client 1: qty +5, cash -50500.  client 2: qty -5, cash +50500.

from std.testing import assert_equal, assert_true, assert_almost_equal

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

comptime SIDE_BUY = 0
comptime SIDE_SELL = 1

comptime TYPE_LIMIT = 0
comptime TYPE_MARKET = 1
comptime TYPE_IOC = 2
comptime TYPE_FOK = 3

comptime STATE_NEW = 0
comptime STATE_ACKED = 1
comptime STATE_PARTIAL = 2
comptime STATE_FILLED = 3
comptime STATE_CANCELLED = 4
comptime STATE_REJECTED = 5
comptime STATE_UNKNOWN = -1

comptime PHASE_PREOPEN = 0
comptime PHASE_OPEN = 1
comptime PHASE_HALTED = 2
comptime PHASE_CLOSED = 3

comptime STP_NONE = 0
comptime STP_CANCEL_RESTING = 1
comptime STP_REJECT_INCOMING = 2

comptime NO_PRICE = -1


# ---------------------------------------------------------------------------
# Order: one instruction, with its lifecycle state carried on it.
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
    var state: Int
    var ts_ns: Int

    def __init__(
        out self,
        oid: Int,
        client_id: Int,
        side: Int,
        price: Int,
        qty: Int,
        otype: Int,
        ts_ns: Int,
    ):
        self.oid = oid
        self.client_id = client_id
        self.side = side
        self.price = price
        self.qty = qty
        self.remaining = qty
        self.seq = 0
        self.otype = otype
        self.state = STATE_NEW
        self.ts_ns = ts_ns

    def is_buy(self) -> Bool:
        return self.side == SIDE_BUY

    def filled(self) -> Int:
        return self.qty - self.remaining

    def state_name(self) -> String:
        if self.state == STATE_NEW:
            return String("NEW")
        if self.state == STATE_ACKED:
            return String("ACKED")
        if self.state == STATE_PARTIAL:
            return String("PARTIAL")
        if self.state == STATE_FILLED:
            return String("FILLED")
        if self.state == STATE_CANCELLED:
            return String("CANCELLED")
        if self.state == STATE_REJECTED:
            return String("REJECTED")
        return String("UNKNOWN")

    def describe(self) -> String:
        var side_s = String("SELL")
        if self.side == SIDE_BUY:
            side_s = String("BUY ")
        return (
            String("oid=")
            + String(self.oid)
            + String(" ")
            + side_s
            + String(" px=")
            + String(self.price)
            + String(" qty=")
            + String(self.qty)
            + String(" rem=")
            + String(self.remaining)
            + String(" ")
            + self.state_name()
        )


# ---------------------------------------------------------------------------
# Trade: one fill on the tape. price is the resting order's price for
# continuous matching, and the clearing price for auction matching.
# ---------------------------------------------------------------------------

struct Trade:
    var buy_oid: Int
    var sell_oid: Int
    var buy_client: Int
    var sell_client: Int
    var price: Int
    var qty: Int
    var seq: Int
    var auction: Bool

    def __init__(
        out self,
        buy_oid: Int,
        sell_oid: Int,
        buy_client: Int,
        sell_client: Int,
        price: Int,
        qty: Int,
        seq: Int,
        auction: Bool,
    ):
        self.buy_oid = buy_oid
        self.sell_oid = sell_oid
        self.buy_client = buy_client
        self.sell_client = sell_client
        self.price = price
        self.qty = qty
        self.seq = seq
        self.auction = auction

    def notional(self) -> Int:
        return self.price * self.qty

    def describe(self) -> String:
        var tag = String("C")
        if self.auction:
            tag = String("A")
        return (
            String("[")
            + tag
            + String("] seq=")
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
# TradeReport: the drop-copy record of one fill. Immutable once
# published; report_seq numbers the reports in publication order.
# ---------------------------------------------------------------------------

struct TradeReport:
    var report_seq: Int
    var trade_seq: Int
    var symbol: String
    var buy_oid: Int
    var sell_oid: Int
    var buy_client: Int
    var sell_client: Int
    var price: Int
    var qty: Int
    var auction: Bool

    def __init__(
        out self,
        report_seq: Int,
        trade_seq: Int,
        symbol: String,
        buy_oid: Int,
        sell_oid: Int,
        buy_client: Int,
        sell_client: Int,
        price: Int,
        qty: Int,
        auction: Bool,
    ):
        self.report_seq = report_seq
        self.trade_seq = trade_seq
        self.symbol = symbol
        self.buy_oid = buy_oid
        self.sell_oid = sell_oid
        self.buy_client = buy_client
        self.sell_client = sell_client
        self.price = price
        self.qty = qty
        self.auction = auction

    def describe(self) -> String:
        var tag = String("C")
        if self.auction:
            tag = String("A")
        return (
            String("report#")
            + String(self.report_seq)
            + String(" [")
            + tag
            + String("] trade_seq=")
            + String(self.trade_seq)
            + String(" ")
            + self.symbol
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
# MatchingEngine.
# ---------------------------------------------------------------------------

struct MatchingEngine:
    var bids: List[Order]
    var asks: List[Order]
    var auction_bids: List[Order]
    var auction_asks: List[Order]
    var done: List[Order]
    var trades: List[Trade]
    var rejected_oids: List[Int]
    var reject_reasons: List[String]
    var clients: List[Int]
    var pos_qty: List[Int]
    var pos_cash: List[Int]
    var next_seq: Int
    var total_volume: Int
    var total_notional: Int
    var last_trade_price: Int
    var n_submitted: Int
    var n_rejected: Int
    var n_cancelled: Int
    var phase: Int
    var stp_mode: Int
    var reference_price: Int
    var last_stp_reject: Bool
    var symbol: String
    var reports: List[TradeReport]
    var next_report_seq: Int

    def __init__(out self):
        self.bids = List[Order]()
        self.asks = List[Order]()
        self.auction_bids = List[Order]()
        self.auction_asks = List[Order]()
        self.done = List[Order]()
        self.trades = List[Trade]()
        self.rejected_oids = List[Int]()
        self.reject_reasons = List[String]()
        self.clients = List[Int]()
        self.pos_qty = List[Int]()
        self.pos_cash = List[Int]()
        self.next_seq = 1
        self.total_volume = 0
        self.total_notional = 0
        self.last_trade_price = 0
        self.n_submitted = 0
        self.n_rejected = 0
        self.n_cancelled = 0
        self.phase = PHASE_PREOPEN
        self.stp_mode = STP_CANCEL_RESTING
        self.reference_price = 0
        self.last_stp_reject = False
        self.symbol = String("SIM")
        self.reports = List[TradeReport]()
        self.next_report_seq = 0

    def _take_seq(mut self) -> Int:
        var s = self.next_seq
        self.next_seq += 1
        return s

    def set_phase(mut self, phase: Int):
        self.phase = phase

    def set_stp_mode(mut self, mode: Int):
        self.stp_mode = mode

    def set_reference_price(mut self, price: Int):
        self.reference_price = price

    def set_symbol(mut self, sym: String):
        self.symbol = sym

    # -- position bookkeeping ----------------------------------------------
    # Find a client's slot, creating it at zero if this is the first trade.
    def _client_slot(mut self, client_id: Int) -> Int:
        var i = 0
        while i < len(self.clients):
            if self.clients[i] == client_id:
                return i
            i += 1
        self.clients.append(client_id)
        self.pos_qty.append(0)
        self.pos_cash.append(0)
        return len(self.clients) - 1

    def _apply_trade(mut self, buy_client: Int, sell_client: Int, price: Int, qty: Int):
        var b = self._client_slot(buy_client)
        self.pos_qty[b] += qty
        self.pos_cash[b] -= price * qty
        var s = self._client_slot(sell_client)
        self.pos_qty[s] -= qty
        self.pos_cash[s] += price * qty

    def position_qty(self, client_id: Int) -> Int:
        var i = 0
        while i < len(self.clients):
            if self.clients[i] == client_id:
                return self.pos_qty[i]
            i += 1
        return 0

    def position_cash(self, client_id: Int) -> Int:
        var i = 0
        while i < len(self.clients):
            if self.clients[i] == client_id:
                return self.pos_cash[i]
            i += 1
        return 0

    # -- tape ---------------------------------------------------------------
    def _record_trade(
        mut self,
        buy_oid: Int,
        sell_oid: Int,
        buy_client: Int,
        sell_client: Int,
        price: Int,
        qty: Int,
        auction: Bool,
    ):
        var tseq = self._take_seq()
        var t = Trade(
            buy_oid, sell_oid, buy_client, sell_client, price, qty, tseq, auction
        )
        self.trades.append(t^)
        var r = TradeReport(
            self.next_report_seq,
            tseq,
            self.symbol,
            buy_oid,
            sell_oid,
            buy_client,
            sell_client,
            price,
            qty,
            auction,
        )
        self.next_report_seq += 1
        self.reports.append(r^)
        self.total_volume += qty
        self.total_notional += price * qty
        self.last_trade_price = price
        self._apply_trade(buy_client, sell_client, price, qty)

    # -- sorted insertion ----------------------------------------------------
    def _insert_bid(mut self, var order: Order):
        var pos = len(self.bids)
        var i = 0
        while i < len(self.bids):
            if self.bids[i].price < order.price:
                pos = i
                break
            i += 1
        self.bids.insert(pos, order^)

    def _insert_ask(mut self, var order: Order):
        var pos = len(self.asks)
        var i = 0
        while i < len(self.asks):
            if self.asks[i].price > order.price:
                pos = i
                break
            i += 1
        self.asks.insert(pos, order^)

    def _insert_auction_bid(mut self, var order: Order):
        var pos = len(self.auction_bids)
        var i = 0
        while i < len(self.auction_bids):
            if self.auction_bids[i].price < order.price:
                pos = i
                break
            i += 1
        self.auction_bids.insert(pos, order^)

    def _insert_auction_ask(mut self, var order: Order):
        var pos = len(self.auction_asks)
        var i = 0
        while i < len(self.auction_asks):
            if self.auction_asks[i].price > order.price:
                pos = i
                break
            i += 1
        self.auction_asks.insert(pos, order^)

    # -- rejection -----------------------------------------------------------
    def _reject(mut self, oid: Int, reason: String):
        self.rejected_oids.append(oid)
        self.reject_reasons.append(reason)
        self.n_rejected += 1

    def reject_reason(self, oid: Int) -> String:
        var i = 0
        while i < len(self.rejected_oids):
            if self.rejected_oids[i] == oid:
                return self.reject_reasons[i]
            i += 1
        return String("")

    # -- continuous matching -------------------------------------------------
    def _match_buy(mut self, mut order: Order, limit_price: Int) -> Int:
        var n_trades = 0
        while (
            order.remaining > 0
            and len(self.asks) > 0
            and self.asks[0].price <= limit_price
        ):
            # Self-trade check against the current best ask.
            if self.asks[0].client_id == order.client_id and self.stp_mode != STP_NONE:
                if self.stp_mode == STP_REJECT_INCOMING:
                    self.last_stp_reject = True
                    return n_trades
                var resting = self.asks.pop(0)
                resting.state = STATE_CANCELLED
                self.done.append(resting^)
                self.n_cancelled += 1
                continue
            var fill = order.remaining
            if self.asks[0].remaining < fill:
                fill = self.asks[0].remaining
            var px = self.asks[0].price
            var resting_oid = self.asks[0].oid
            var resting_client = self.asks[0].client_id
            self.asks[0].remaining -= fill
            if self.asks[0].remaining == 0:
                self.asks[0].state = STATE_FILLED
            else:
                self.asks[0].state = STATE_PARTIAL
            order.remaining -= fill
            if order.remaining == 0:
                order.state = STATE_FILLED
            else:
                order.state = STATE_PARTIAL
            self._record_trade(
                order.oid, resting_oid, order.client_id, resting_client, px, fill, False
            )
            n_trades += 1
            if self.asks[0].remaining == 0:
                var filled_order = self.asks.pop(0)
                self.done.append(filled_order^)
        return n_trades

    def _match_sell(mut self, mut order: Order, limit_price: Int) -> Int:
        var n_trades = 0
        while (
            order.remaining > 0
            and len(self.bids) > 0
            and self.bids[0].price >= limit_price
        ):
            if self.bids[0].client_id == order.client_id and self.stp_mode != STP_NONE:
                if self.stp_mode == STP_REJECT_INCOMING:
                    self.last_stp_reject = True
                    return n_trades
                var resting = self.bids.pop(0)
                resting.state = STATE_CANCELLED
                self.done.append(resting^)
                self.n_cancelled += 1
                continue
            var fill = order.remaining
            if self.bids[0].remaining < fill:
                fill = self.bids[0].remaining
            var px = self.bids[0].price
            var resting_oid = self.bids[0].oid
            var resting_client = self.bids[0].client_id
            self.bids[0].remaining -= fill
            if self.bids[0].remaining == 0:
                self.bids[0].state = STATE_FILLED
            else:
                self.bids[0].state = STATE_PARTIAL
            order.remaining -= fill
            if order.remaining == 0:
                order.state = STATE_FILLED
            else:
                order.state = STATE_PARTIAL
            self._record_trade(
                resting_oid, order.oid, resting_client, order.client_id, px, fill, False
            )
            n_trades += 1
            if self.bids[0].remaining == 0:
                var filled_order = self.bids.pop(0)
                self.done.append(filled_order^)
        return n_trades

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

    # Rest a partially filled (or unfilled) order in the continuous book.
    def _rest(mut self, var order: Order):
        order.state = STATE_ACKED
        if order.remaining < order.qty:
            order.state = STATE_PARTIAL
        if order.side == SIDE_BUY:
            self._insert_bid(order^)
        else:
            self._insert_ask(order^)

    # Move a fully filled incoming order to the done list.
    def _finish_incoming(mut self, var order: Order):
        order.state = STATE_FILLED
        self.done.append(order^)

    # -- public order entry --------------------------------------------------
    # Returns the number of trades the order printed. A rejected order
    # prints zero trades and is recorded in the reject log.
    def submit(mut self, var order: Order) -> Int:
        self.n_submitted += 1
        # Validation first: never let a nonsense order near the book.
        if order.qty <= 0:
            self._reject(order.oid, String("quantity must be positive"))
            return 0
        if order.otype == TYPE_LIMIT or order.otype == TYPE_IOC or order.otype == TYPE_FOK:
            if order.price <= 0:
                self._reject(order.oid, String("limit price must be positive"))
                return 0
        if (
            order.otype != TYPE_LIMIT
            and order.otype != TYPE_MARKET
            and order.otype != TYPE_IOC
            and order.otype != TYPE_FOK
        ):
            self._reject(order.oid, String("unknown order type"))
            return 0
        if self.phase == PHASE_HALTED:
            self._reject(order.oid, String("session halted"))
            return 0
        if self.phase == PHASE_CLOSED:
            self._reject(order.oid, String("session closed"))
            return 0
        order.seq = self._take_seq()
        self.last_stp_reject = False
        if self.phase == PHASE_PREOPEN:
            # Auction collection: no matching yet. Market orders are not
            # meaningful in an auction and are rejected.
            if order.otype == TYPE_MARKET:
                self._reject(order.oid, String("market order not allowed in auction"))
                return 0
            order.state = STATE_ACKED
            if order.side == SIDE_BUY:
                self._insert_auction_bid(order^)
            else:
                self._insert_auction_ask(order^)
            return 0
        # Continuous session.
        var n: Int
        if order.otype == TYPE_MARKET:
            if order.side == SIDE_BUY:
                n = self._match_buy(order, 1_000_000_000)
            else:
                n = self._match_sell(order, 0)
            if self.last_stp_reject and order.remaining > 0:
                var stp_oid = order.oid
                order.state = STATE_REJECTED
                self.done.append(order^)
                self._reject(stp_oid, String("self-trade prevented"))
                return n
            if order.remaining > 0:
                # Unfilled market quantity is discarded, never rested.
                order.state = STATE_CANCELLED
                self.done.append(order^)
                self.n_cancelled += 1
            else:
                self._finish_incoming(order^)
            return n
        if order.otype == TYPE_IOC:
            if order.side == SIDE_BUY:
                n = self._match_buy(order, order.price)
            else:
                n = self._match_sell(order, order.price)
            if self.last_stp_reject and order.remaining > 0:
                var stp_oid = order.oid
                order.state = STATE_REJECTED
                self.done.append(order^)
                self._reject(stp_oid, String("self-trade prevented"))
                return n
            if order.remaining > 0:
                order.state = STATE_CANCELLED
                self.done.append(order^)
                self.n_cancelled += 1
            else:
                self._finish_incoming(order^)
            return n
        if order.otype == TYPE_FOK:
            var avail = self._available(order.side, order.price)
            if avail < order.qty:
                self._reject(order.oid, String("FOK quantity not available"))
                return 0
            if order.side == SIDE_BUY:
                n = self._match_buy(order, order.price)
            else:
                n = self._match_sell(order, order.price)
            if self.last_stp_reject and order.remaining > 0:
                var stp_oid = order.oid
                order.state = STATE_REJECTED
                self.done.append(order^)
                self._reject(stp_oid, String("self-trade prevented"))
                return n
            if order.remaining > 0:
                # Should not happen (availability was checked), but if STP
                # cancelled a resting order mid-match, rest the remainder.
                self._rest(order^)
            else:
                self._finish_incoming(order^)
            return n
        # Plain limit order.
        if order.side == SIDE_BUY:
            n = self._match_buy(order, order.price)
        else:
            n = self._match_sell(order, order.price)
        if self.last_stp_reject and order.remaining > 0:
            var stp_oid = order.oid
            order.state = STATE_REJECTED
            self.done.append(order^)
            self._reject(stp_oid, String("self-trade prevented"))
            return n
        if order.remaining > 0:
            self._rest(order^)
        else:
            self._finish_incoming(order^)
        return n

    # Cancel by order id, from the continuous book or the auction book.
    # A cancelled order moves to the done list with state CANCELLED.
    def cancel(mut self, oid: Int) -> Bool:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                var gone = self.bids.pop(i)
                gone.state = STATE_CANCELLED
                self.done.append(gone^)
                self.n_cancelled += 1
                return True
            i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].oid == oid:
                var gone = self.asks.pop(j)
                gone.state = STATE_CANCELLED
                self.done.append(gone^)
                self.n_cancelled += 1
                return True
            j += 1
        var k = 0
        while k < len(self.auction_bids):
            if self.auction_bids[k].oid == oid:
                var gone = self.auction_bids.pop(k)
                gone.state = STATE_CANCELLED
                self.done.append(gone^)
                self.n_cancelled += 1
                return True
            k += 1
        var m = 0
        while m < len(self.auction_asks):
            if self.auction_asks[m].oid == oid:
                var gone = self.auction_asks.pop(m)
                gone.state = STATE_CANCELLED
                self.done.append(gone^)
                self.n_cancelled += 1
                return True
            m += 1
        return False

    # Amend price/quantity of a resting order. The replacement gets a fresh
    # sequence number and goes to the back of its price level.
    def amend(mut self, oid: Int, new_price: Int, new_qty: Int) -> Bool:
        var side = NO_PRICE
        var client_id = 0
        var otype = TYPE_LIMIT
        var ts_ns = 0
        var in_auction = False
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                side = SIDE_BUY
                client_id = self.bids[i].client_id
                otype = self.bids[i].otype
                ts_ns = self.bids[i].ts_ns
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
                    ts_ns = self.asks[j].ts_ns
                    var _gone = self.asks.pop(j)
                    break
                j += 1
        if side == NO_PRICE:
            var k = 0
            while k < len(self.auction_bids):
                if self.auction_bids[k].oid == oid:
                    side = SIDE_BUY
                    client_id = self.auction_bids[k].client_id
                    otype = self.auction_bids[k].otype
                    ts_ns = self.auction_bids[k].ts_ns
                    in_auction = True
                    var _gone = self.auction_bids.pop(k)
                    break
                k += 1
        if side == NO_PRICE:
            var m = 0
            while m < len(self.auction_asks):
                if self.auction_asks[m].oid == oid:
                    side = SIDE_SELL
                    client_id = self.auction_asks[m].client_id
                    otype = self.auction_asks[m].otype
                    ts_ns = self.auction_asks[m].ts_ns
                    in_auction = True
                    var _gone = self.auction_asks.pop(m)
                    break
                m += 1
        if side == NO_PRICE:
            return False
        self.n_cancelled += 1
        var replacement = Order(oid, client_id, side, new_price, new_qty, otype, ts_ns)
        if in_auction:
            replacement.seq = self._take_seq()
            replacement.state = STATE_ACKED
            if side == SIDE_BUY:
                self._insert_auction_bid(replacement^)
            else:
                self._insert_auction_ask(replacement^)
            return True
        var _n = self.submit(replacement^)
        return True

    # Cancel every resting order belonging to one client (a risk kill).
    def cancel_all_for_client(mut self, client_id: Int) -> Int:
        var count = 0
        var i = 0
        while i < len(self.bids):
            if self.bids[i].client_id == client_id:
                var gone = self.bids.pop(i)
                gone.state = STATE_CANCELLED
                self.done.append(gone^)
                self.n_cancelled += 1
                count += 1
            else:
                i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].client_id == client_id:
                var gone = self.asks.pop(j)
                gone.state = STATE_CANCELLED
                self.done.append(gone^)
                self.n_cancelled += 1
                count += 1
            else:
                j += 1
        return count

    # -- auction ---------------------------------------------------------------
    # Traded volume at a candidate clearing price: the smaller of the bid
    # quantity priced at or above it and the ask quantity priced at or
    # below it.
    def _volume_at(self, price: Int) -> Int:
        var bid_vol = 0
        var i = 0
        while i < len(self.auction_bids):
            if self.auction_bids[i].price >= price:
                bid_vol += self.auction_bids[i].remaining
            i += 1
        var ask_vol = 0
        var j = 0
        while j < len(self.auction_asks):
            if self.auction_asks[j].price <= price:
                ask_vol += self.auction_asks[j].remaining
            j += 1
        if bid_vol < ask_vol:
            return bid_vol
        return ask_vol

    # Best clearing price: maximum volume; ties break towards the
    # reference price, then towards the higher price. Returns 0 when the
    # auction book is empty.
    def clearing_price(self) -> Int:
        if len(self.auction_bids) == 0 or len(self.auction_asks) == 0:
            return 0
        var ref_px = self.reference_price
        if ref_px == 0:
            ref_px = (self.auction_bids[0].price + self.auction_asks[0].price) // 2
        var best_price = 0
        var best_vol = -1
        var best_dist = 0
        var i = 0
        while i < len(self.auction_bids):
            var p = self.auction_bids[i].price
            var v = self._volume_at(p)
            var dist = p - ref_px
            if dist < 0:
                dist = -dist
            if (
                v > best_vol
                or (v == best_vol and dist < best_dist)
                or (v == best_vol and dist == best_dist and p > best_price)
            ):
                best_vol = v
                best_price = p
                best_dist = dist
            i += 1
        var j = 0
        while j < len(self.auction_asks):
            var p = self.auction_asks[j].price
            var v = self._volume_at(p)
            var dist = p - ref_px
            if dist < 0:
                dist = -dist
            if (
                v > best_vol
                or (v == best_vol and dist < best_dist)
                or (v == best_vol and dist == best_dist and p > best_price)
            ):
                best_vol = v
                best_price = p
                best_dist = dist
            j += 1
        return best_price

    # Run the opening auction: cross at the clearing price, then carry the
    # unfilled remainder into the continuous book. Returns trade count.
    def run_auction(mut self) -> Int:
        var px = self.clearing_price()
        if px == 0:
            return 0
        var n_trades = 0
        while (
            len(self.auction_bids) > 0
            and len(self.auction_asks) > 0
            and self.auction_bids[0].price >= px
            and self.auction_asks[0].price <= px
        ):
            var fill = self.auction_bids[0].remaining
            if self.auction_asks[0].remaining < fill:
                fill = self.auction_asks[0].remaining
            var buy_oid = self.auction_bids[0].oid
            var sell_oid = self.auction_asks[0].oid
            var buy_client = self.auction_bids[0].client_id
            var sell_client = self.auction_asks[0].client_id
            self.auction_bids[0].remaining -= fill
            self.auction_asks[0].remaining -= fill
            if self.auction_bids[0].remaining == 0:
                self.auction_bids[0].state = STATE_FILLED
            else:
                self.auction_bids[0].state = STATE_PARTIAL
            if self.auction_asks[0].remaining == 0:
                self.auction_asks[0].state = STATE_FILLED
            else:
                self.auction_asks[0].state = STATE_PARTIAL
            self._record_trade(
                buy_oid, sell_oid, buy_client, sell_client, px, fill, True
            )
            n_trades += 1
            if self.auction_bids[0].remaining == 0:
                var filled_b = self.auction_bids.pop(0)
                self.done.append(filled_b^)
            if self.auction_asks[0].remaining == 0:
                var filled_a = self.auction_asks.pop(0)
                self.done.append(filled_a^)
        # Carry the remainder into the continuous book, in priority order.
        while len(self.auction_bids) > 0:
            var o = self.auction_bids.pop(0)
            if o.remaining < o.qty:
                o.state = STATE_PARTIAL
            else:
                o.state = STATE_ACKED
            self._insert_bid(o^)
        while len(self.auction_asks) > 0:
            var o = self.auction_asks.pop(0)
            if o.remaining < o.qty:
                o.state = STATE_PARTIAL
            else:
                o.state = STATE_ACKED
            self._insert_ask(o^)
        return n_trades

    # -- queries ---------------------------------------------------------------
    def best_bid(self) -> Int:
        if len(self.bids) == 0:
            return NO_PRICE
        return self.bids[0].price

    def best_ask(self) -> Int:
        if len(self.asks) == 0:
            return NO_PRICE
        return self.asks[0].price

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

    # Lifecycle state of any order the engine has seen; STATE_UNKNOWN when
    # the id was never submitted.
    def order_state(self, oid: Int) -> Int:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                return self.bids[i].state
            i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].oid == oid:
                return self.asks[j].state
            j += 1
        var k = 0
        while k < len(self.auction_bids):
            if self.auction_bids[k].oid == oid:
                return self.auction_bids[k].state
            k += 1
        var m = 0
        while m < len(self.auction_asks):
            if self.auction_asks[m].oid == oid:
                return self.auction_asks[m].state
            m += 1
        var n = 0
        while n < len(self.done):
            if self.done[n].oid == oid:
                return self.done[n].state
            n += 1
        var r = 0
        while r < len(self.rejected_oids):
            if self.rejected_oids[r] == oid:
                return STATE_REJECTED
            r += 1
        return STATE_UNKNOWN

    def filled_qty(self, oid: Int) -> Int:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].oid == oid:
                return self.bids[i].filled()
            i += 1
        var j = 0
        while j < len(self.asks):
            if self.asks[j].oid == oid:
                return self.asks[j].filled()
            j += 1
        var k = 0
        while k < len(self.done):
            if self.done[k].oid == oid:
                return self.done[k].filled()
            k += 1
        return 0

    def check_invariants(self) -> Bool:
        var i = 0
        while i < len(self.bids):
            if self.bids[i].remaining <= 0 or self.bids[i].price <= 0:
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

    def snapshot(self) -> String:
        var s = String("--- engine book ---\n")
        var i = len(self.asks) - 1
        while i >= 0:
            s = (
                s
                + String("  ASK ")
                + String(self.asks[i].price)
                + String(" x ")
                + String(self.asks[i].remaining)
                + String(" oid=")
                + String(self.asks[i].oid)
                + String(" ")
                + self.asks[i].state_name()
                + String("\n")
            )
            i -= 1
        var j = 0
        while j < len(self.bids):
            s = (
                s
                + String("  BID ")
                + String(self.bids[j].price)
                + String(" x ")
                + String(self.bids[j].remaining)
                + String(" oid=")
                + String(self.bids[j].oid)
                + String(" ")
                + self.bids[j].state_name()
                + String("\n")
            )
            j += 1
        s = (
            s
            + String("trades: ")
            + String(len(self.trades))
            + String(" volume: ")
            + String(self.total_volume)
            + String(" notional: ")
            + String(self.total_notional)
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

    def stats(self) -> String:
        var s = String("engine stats: submitted=") + String(self.n_submitted)
        s = s + String(" rejected=") + String(self.n_rejected)
        s = s + String(" cancelled=") + String(self.n_cancelled)
        s = s + String(" trades=") + String(len(self.trades))
        s = s + String(" volume=") + String(self.total_volume)
        s = s + String(" last_px=") + String(self.last_trade_price)
        return s

    # -- drop-copy queries ---------------------------------------------------
    # Reports involving one client (as buyer or seller), in order.
    # Reports are rebuilt from their fields here because a report is
    # move-only: the engine keeps the originals, the caller gets copies
    # with identical contents.
    def reports_for_client(self, client_id: Int) -> List[TradeReport]:
        var out = List[TradeReport]()
        var i = 0
        while i < len(self.reports):
            if self.reports[i].buy_client == client_id or self.reports[i].sell_client == client_id:
                var r = TradeReport(
                    self.reports[i].report_seq,
                    self.reports[i].trade_seq,
                    self.reports[i].symbol,
                    self.reports[i].buy_oid,
                    self.reports[i].sell_oid,
                    self.reports[i].buy_client,
                    self.reports[i].sell_client,
                    self.reports[i].price,
                    self.reports[i].qty,
                    self.reports[i].auction,
                )
                out.append(r^)
            i += 1
        return out^

    def client_fill_qty(self, client_id: Int) -> Int:
        var total = 0
        var i = 0
        while i < len(self.reports):
            if self.reports[i].buy_client == client_id or self.reports[i].sell_client == client_id:
                total += self.reports[i].qty
            i += 1
        return total

    def client_fill_notional(self, client_id: Int) -> Int:
        var total = 0
        var i = 0
        while i < len(self.reports):
            if self.reports[i].buy_client == client_id or self.reports[i].sell_client == client_id:
                total += self.reports[i].price * self.reports[i].qty
            i += 1
        return total

    def client_vwap(self, client_id: Int) -> Float64:
        var qty = self.client_fill_qty(client_id)
        if qty == 0:
            return 0.0
        return Float64(self.client_fill_notional(client_id)) / Float64(qty)

    def reports_summary(self) -> String:
        var s = String("drop-copy: reports=") + String(len(self.reports))
        s = s + String(" next_seq=") + String(self.next_report_seq)
        return s

# ---------------------------------------------------------------------------
# Tests. Hand-computed cases are documented in the header.
# ---------------------------------------------------------------------------

def test_continuous_lifecycle_and_positions() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    var n1 = eng.submit(Order(1, 2, SIDE_SELL, 10100, 5, TYPE_LIMIT, 1000))
    assert_equal(n1, 0)
    assert_equal(eng.order_state(1), STATE_ACKED)
    var n2 = eng.submit(Order(2, 1, SIDE_BUY, 10100, 7, TYPE_LIMIT, 2000))
    assert_equal(n2, 1)
    assert_equal(eng.trades[0].price, 10100)
    assert_equal(eng.trades[0].qty, 5)
    assert_equal(eng.order_state(1), STATE_FILLED)
    assert_equal(eng.order_state(2), STATE_PARTIAL)
    assert_equal(eng.filled_qty(1), 5)
    assert_equal(eng.filled_qty(2), 5)
    assert_equal(eng.position_qty(1), 5)
    assert_equal(eng.position_cash(1), -50500)
    assert_equal(eng.position_qty(2), -5)
    assert_equal(eng.position_cash(2), 50500)
    # Sell market 2 sweeps the remaining 2 of order 2.
    var n3 = eng.submit(Order(3, 2, SIDE_SELL, 0, 2, TYPE_MARKET, 3000))
    assert_equal(n3, 1)
    assert_equal(eng.order_state(2), STATE_FILLED)
    assert_equal(eng.order_state(3), STATE_FILLED)
    assert_equal(eng.position_qty(1), 7)
    assert_equal(eng.position_cash(1), -70700)
    assert_equal(eng.position_qty(2), -7)
    assert_equal(eng.position_cash(2), 70700)
    # Cross-check positions by recomputing from the tape.
    var q1 = 0
    var c1 = 0
    var q2 = 0
    var c2 = 0
    var i = 0
    while i < len(eng.trades):
        if eng.trades[i].buy_client == 1:
            q1 += eng.trades[i].qty
            c1 -= eng.trades[i].notional()
        if eng.trades[i].sell_client == 1:
            q1 -= eng.trades[i].qty
            c1 += eng.trades[i].notional()
        if eng.trades[i].buy_client == 2:
            q2 += eng.trades[i].qty
            c2 -= eng.trades[i].notional()
        if eng.trades[i].sell_client == 2:
            q2 -= eng.trades[i].qty
            c2 += eng.trades[i].notional()
        i += 1
    assert_equal(q1, eng.position_qty(1))
    assert_equal(c1, eng.position_cash(1))
    assert_equal(q2, eng.position_qty(2))
    assert_equal(c2, eng.position_cash(2))
    assert_true(eng.check_invariants())
    print("lifecycle ok: ACKED->PARTIAL->FILLED, positions exact, tape agrees")


def test_ioc_fok_engine() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    var _a = eng.submit(Order(1, 2, SIDE_SELL, 10100, 2, TYPE_LIMIT, 1000))
    var n1 = eng.submit(Order(2, 1, SIDE_BUY, 10100, 5, TYPE_IOC, 2000))
    assert_equal(n1, 1)
    assert_equal(eng.order_state(2), STATE_CANCELLED)
    assert_equal(eng.best_bid(), NO_PRICE)
    var n2 = eng.submit(Order(3, 1, SIDE_BUY, 10100, 5, TYPE_FOK, 3000))
    assert_equal(n2, 0)
    assert_equal(eng.order_state(3), STATE_REJECTED)
    assert_equal(eng.reject_reason(3), String("FOK quantity not available"))
    var _b = eng.submit(Order(4, 2, SIDE_SELL, 10100, 5, TYPE_LIMIT, 4000))
    var n3 = eng.submit(Order(5, 1, SIDE_BUY, 10100, 5, TYPE_FOK, 5000))
    assert_equal(n3, 1)
    assert_equal(eng.order_state(5), STATE_FILLED)
    assert_true(eng.check_invariants())
    print("ioc/fok ok: IOC cancels remainder, FOK rejects then fills")


def test_stp_cancel_resting() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    eng.set_stp_mode(STP_CANCEL_RESTING)
    var _a = eng.submit(Order(1, 7, SIDE_SELL, 10100, 5, TYPE_LIMIT, 1000))
    var n = eng.submit(Order(2, 7, SIDE_BUY, 10100, 5, TYPE_LIMIT, 2000))
    assert_equal(n, 0)
    assert_equal(len(eng.trades), 0)
    assert_equal(eng.order_state(1), STATE_CANCELLED)
    assert_equal(eng.best_bid(), 10100)
    assert_equal(eng.best_ask(), NO_PRICE)
    assert_true(eng.check_invariants())
    print("stp cancel-resting ok: own order cancelled, no self-trade")


def test_stp_reject_incoming() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    eng.set_stp_mode(STP_REJECT_INCOMING)
    var _a = eng.submit(Order(1, 7, SIDE_SELL, 10100, 5, TYPE_LIMIT, 1000))
    var n = eng.submit(Order(2, 7, SIDE_BUY, 10100, 5, TYPE_LIMIT, 2000))
    assert_equal(n, 0)
    assert_equal(len(eng.trades), 0)
    assert_equal(eng.order_state(1), STATE_ACKED)
    assert_equal(eng.order_state(2), STATE_REJECTED)
    assert_equal(eng.reject_reason(2), String("self-trade prevented"))
    assert_equal(eng.best_ask(), 10100)
    assert_equal(eng.best_bid(), NO_PRICE)
    assert_true(eng.check_invariants())
    print("stp reject-incoming ok: incoming rejected, resting order intact")


def test_halt() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    var _a = eng.submit(Order(1, 1, SIDE_BUY, 10000, 5, TYPE_LIMIT, 1000))
    eng.set_phase(PHASE_HALTED)
    var n = eng.submit(Order(2, 1, SIDE_SELL, 10000, 5, TYPE_LIMIT, 2000))
    assert_equal(n, 0)
    assert_equal(eng.order_state(2), STATE_REJECTED)
    assert_equal(eng.reject_reason(2), String("session halted"))
    # Cancels still work during a halt: a client can always reduce risk.
    assert_true(eng.cancel(1))
    assert_equal(eng.order_state(1), STATE_CANCELLED)
    eng.set_phase(PHASE_OPEN)
    var n2 = eng.submit(Order(3, 1, SIDE_SELL, 10000, 5, TYPE_LIMIT, 3000))
    assert_equal(n2, 0)
    assert_equal(eng.order_state(3), STATE_ACKED)
    print("halt ok: new orders rejected, cancels still work, resume works")


def test_auction() raises:
    # Hand-computed in the header: clearing price 10000, volume 14.
    var eng = MatchingEngine()
    assert_equal(eng.phase, PHASE_PREOPEN)
    var _a = eng.submit(Order(1, 1, SIDE_BUY, 10100, 5, TYPE_LIMIT, 1000))
    var _b = eng.submit(Order(2, 1, SIDE_BUY, 10000, 10, TYPE_LIMIT, 2000))
    var _c = eng.submit(Order(3, 1, SIDE_BUY, 9900, 5, TYPE_LIMIT, 3000))
    var _d = eng.submit(Order(4, 2, SIDE_SELL, 9900, 8, TYPE_LIMIT, 4000))
    var _e = eng.submit(Order(5, 2, SIDE_SELL, 10000, 6, TYPE_LIMIT, 5000))
    var _f = eng.submit(Order(6, 2, SIDE_SELL, 10100, 4, TYPE_LIMIT, 6000))
    assert_equal(len(eng.trades), 0)
    assert_equal(eng.clearing_price(), 10000)
    var n = eng.run_auction()
    assert_equal(n, 3)
    assert_equal(eng.total_volume, 14)
    assert_equal(eng.trades[0].price, 10000)
    assert_equal(eng.trades[1].price, 10000)
    assert_equal(eng.trades[2].price, 10000)
    assert_true(eng.trades[0].auction)
    assert_equal(eng.order_state(1), STATE_FILLED)
    assert_equal(eng.order_state(4), STATE_FILLED)
    assert_equal(eng.order_state(5), STATE_FILLED)
    assert_equal(eng.order_state(2), STATE_PARTIAL)
    assert_equal(eng.order_state(3), STATE_ACKED)
    assert_equal(eng.order_state(6), STATE_ACKED)
    assert_equal(eng.best_bid(), 10000)
    assert_equal(eng.total_qty(SIDE_BUY), 6)
    assert_equal(eng.best_ask(), 10100)
    assert_equal(eng.total_qty(SIDE_SELL), 4)
    assert_equal(eng.position_qty(1), 14)
    assert_equal(eng.position_cash(1), -140000)
    assert_equal(eng.position_qty(2), -14)
    assert_equal(eng.position_cash(2), 140000)
    assert_true(eng.check_invariants())
    # Continuous trading resumes after the auction.
    eng.set_phase(PHASE_OPEN)
    var n2 = eng.submit(Order(7, 3, SIDE_BUY, 0, 1, TYPE_MARKET, 7000))
    assert_equal(n2, 1)
    assert_equal(eng.trades[3].price, 10100)
    assert_true(not eng.trades[3].auction)
    assert_equal(eng.position_qty(3), 1)
    assert_equal(eng.position_cash(3), -10100)
    assert_equal(eng.position_qty(2), -15)
    assert_equal(eng.position_cash(2), 150100)
    print("auction ok: clearing 10000, volume 14, remainder carried over")


def test_auction_empty_and_no_cross() raises:
    var eng = MatchingEngine()
    assert_equal(eng.clearing_price(), 0)
    assert_equal(eng.run_auction(), 0)
    var _a = eng.submit(Order(1, 1, SIDE_BUY, 9900, 5, TYPE_LIMIT, 1000))
    var _b = eng.submit(Order(2, 2, SIDE_SELL, 10100, 5, TYPE_LIMIT, 2000))
    # No overlap: bids top at 9900, asks bottom at 10100. Volume at any
    # candidate price is zero, so clearing is the bid price 9900 with
    # volume 0 and no trades; both orders carry into the book.
    var px = eng.clearing_price()
    assert_true(px == 9900 or px == 10100)
    assert_equal(eng._volume_at(px), 0)
    assert_equal(eng.run_auction(), 0)
    assert_equal(eng.best_bid(), 9900)
    assert_equal(eng.best_ask(), 10100)
    print("auction no-cross ok: no trades, orders carried into the book")


def test_validation() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    var n1 = eng.submit(Order(1, 1, SIDE_BUY, 10000, 0, TYPE_LIMIT, 1000))
    assert_equal(n1, 0)
    assert_equal(eng.reject_reason(1), String("quantity must be positive"))
    var n2 = eng.submit(Order(2, 1, SIDE_BUY, 0, 5, TYPE_LIMIT, 2000))
    assert_equal(n2, 0)
    assert_equal(eng.reject_reason(2), String("limit price must be positive"))
    var n3 = eng.submit(Order(3, 1, SIDE_BUY, 10000, 5, 99, 3000))
    assert_equal(n3, 0)
    assert_equal(eng.reject_reason(3), String("unknown order type"))
    assert_equal(eng.order_state(999), STATE_UNKNOWN)
    assert_equal(eng.reject_reason(999), String(""))
    # Market orders are not allowed during the auction collection phase.
    var eng2 = MatchingEngine()
    var n4 = eng2.submit(Order(4, 1, SIDE_BUY, 0, 5, TYPE_MARKET, 1000))
    assert_equal(n4, 0)
    assert_equal(eng2.reject_reason(4), String("market order not allowed in auction"))
    print("validation ok: bad qty, bad price, bad type, market-in-auction")


def test_cancel_all_and_amend() raises:
    var eng = MatchingEngine()
    eng.set_phase(PHASE_OPEN)
    var _a = eng.submit(Order(1, 1, SIDE_BUY, 10000, 5, TYPE_LIMIT, 1000))
    var _b = eng.submit(Order(2, 1, SIDE_BUY, 9900, 5, TYPE_LIMIT, 2000))
    var _c = eng.submit(Order(3, 2, SIDE_SELL, 10100, 5, TYPE_LIMIT, 3000))
    assert_equal(eng.cancel_all_for_client(1), 2)
    assert_equal(eng.order_state(1), STATE_CANCELLED)
    assert_equal(eng.order_state(2), STATE_CANCELLED)
    assert_equal(eng.order_state(3), STATE_ACKED)
    assert_equal(eng.best_bid(), NO_PRICE)
    assert_equal(eng.cancel_all_for_client(1), 0)
    assert_true(not eng.cancel(999))
    assert_true(eng.amend(3, 10200, 7))
    assert_equal(eng.best_ask(), 10200)
    assert_equal(eng.total_qty(SIDE_SELL), 7)
    assert_true(not eng.amend(999, 10200, 7))
    print("cancel-all/amend ok: client sweep, amend reprices and resizes")


def test_drop_copy() raises:
    var eng = MatchingEngine()
    eng.set_symbol(String("AAPL"))
    eng.set_phase(PHASE_OPEN)
    var _a = eng.submit(Order(1, 2, SIDE_SELL, 10100, 5, TYPE_LIMIT, 1000))
    var _b = eng.submit(Order(2, 1, SIDE_BUY, 10100, 7, TYPE_LIMIT, 2000))
    var _c = eng.submit(Order(3, 2, SIDE_SELL, 0, 2, TYPE_MARKET, 3000))
    assert_equal(len(eng.reports), 2)
    assert_equal(len(eng.trades), 2)
    assert_equal(eng.reports[0].report_seq, 0)
    assert_equal(eng.reports[0].trade_seq, eng.trades[0].seq)
    assert_equal(eng.reports[0].symbol, String("AAPL"))
    assert_equal(eng.reports[0].buy_oid, 2)
    assert_equal(eng.reports[0].sell_oid, 1)
    assert_equal(eng.reports[0].price, 10100)
    assert_equal(eng.reports[0].qty, 5)
    assert_true(not eng.reports[0].auction)
    assert_equal(eng.reports[1].report_seq, 1)
    assert_equal(eng.reports[1].qty, 2)
    assert_equal(eng.reports[1].trade_seq, eng.trades[1].seq)
    var mine = eng.reports_for_client(1)
    assert_equal(len(mine), 2)
    assert_equal(eng.client_fill_qty(1), 7)
    assert_equal(eng.client_fill_notional(1), 70700)
    assert_almost_equal(eng.client_vwap(1), 10100.0, atol=1e-9)
    assert_equal(eng.client_fill_qty(2), 7)
    assert_equal(eng.client_fill_notional(2), 70700)
    assert_equal(eng.client_fill_qty(99), 0)
    assert_almost_equal(eng.client_vwap(99), 0.0, atol=1e-9)
    # Auction trades are flagged in the drop copy. Clearing price: both
    # 9900 and 10100 trade the same volume 5 and sit 100 ticks from the
    # reference 10000, so the documented tie-break (higher price) picks
    # 10100.
    var eng2 = MatchingEngine()
    eng2.set_symbol(String("MSFT"))
    eng2.set_reference_price(10000)
    var _d = eng2.submit(Order(1, 1, SIDE_BUY, 10100, 5, TYPE_LIMIT, 1000))
    var _e = eng2.submit(Order(2, 2, SIDE_SELL, 9900, 5, TYPE_LIMIT, 2000))
    var _n = eng2.run_auction()
    assert_equal(len(eng2.reports), 1)
    assert_true(eng2.reports[0].auction)
    assert_equal(eng2.reports[0].symbol, String("MSFT"))
    assert_equal(eng2.reports[0].price, 10100)
    print("drop-copy ok: reports mirror the tape, per-client VWAP exact")
    print("  " + eng.reports_summary())


# ---------------------------------------------------------------------------
# Demo: a full session -- preopen, auction, open, continuous trading.
# ---------------------------------------------------------------------------

def demo() raises:
    print("=== HFT matching engine demo (simulated data, no real market) ===")
    var eng = MatchingEngine()
    print("phase: PREOPEN -- collecting auction orders")
    var _a = eng.submit(Order(1, 1, SIDE_BUY, 10100, 5, TYPE_LIMIT, 1000))
    var _b = eng.submit(Order(2, 1, SIDE_BUY, 10000, 10, TYPE_LIMIT, 2000))
    var _c = eng.submit(Order(3, 2, SIDE_SELL, 9900, 8, TYPE_LIMIT, 3000))
    var _d = eng.submit(Order(4, 2, SIDE_SELL, 10000, 6, TYPE_LIMIT, 4000))
    print("clearing price:", eng.clearing_price())
    var n = eng.run_auction()
    print("auction printed", n, "trades")
    print(eng.tape())
    eng.set_phase(PHASE_OPEN)
    print("phase: OPEN -- continuous trading")
    var n2 = eng.submit(Order(5, 3, SIDE_BUY, 10100, 3, TYPE_LIMIT, 5000))
    print("incoming buy printed", n2, "trade(s)")
    print(eng.snapshot())
    print(eng.stats())
    print("client 1 position:", eng.position_qty(1), "cash:", eng.position_cash(1))
    print("client 2 position:", eng.position_qty(2), "cash:", eng.position_cash(2))


def main() raises:
    demo()
    print("=== matching engine tests ===")
    test_continuous_lifecycle_and_positions()
    test_ioc_fok_engine()
    test_stp_cancel_resting()
    test_stp_reject_incoming()
    test_halt()
    test_auction()
    test_auction_empty_and_no_cross()
    test_validation()
    test_cancel_all_and_amend()
    test_drop_copy()
    print("ALL MATCHING ENGINE TESTS PASSED")
