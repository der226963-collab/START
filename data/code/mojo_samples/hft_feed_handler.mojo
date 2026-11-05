# hft_feed_handler.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): a market-data feed handler.
#
# SIMULATOR ONLY. This file parses invented tick messages that are built
# inside this program. It never connects to an exchange, a broker, or a
# market-data vendor, and no real money is involved anywhere.
#
# Standard library only. No external packages, no Python interop, no network.
#
# The wire protocol (text form), designed for this simulator and documented
# here so the parser and the tests can never drift apart:
#
#   Fields are separated by "|". The last field is always a checksum: the
#   sum of the UTF-8 bytes of everything before the final "|", modulo 1000,
#   written in decimal with no padding. A message whose checksum does not
#   match is rejected before any field is trusted.
#
#   T|seq|ts_ns|symbol|side|price|qty|chk
#       Trade. side is B or S (the aggressor's side). price is integer
#       ticks (1 tick = 1 cent), qty is whole units.
#   Q|seq|ts_ns|symbol|bid|bid_qty|ask|ask_qty|chk
#       Quote (top of book). Requires 0 < bid < ask.
#   N|seq|ts_ns|symbol|side|price|qty|oid|chk
#       New order announcement. oid is the venue's order id.
#   X|seq|ts_ns|symbol|oid|chk
#       Cancel announcement.
#   S|seq|ts_ns|symbol|code|chk
#       Session status. code is one of OPEN, HALT, CLOSE, PREOPEN.
#   H|seq|ts_ns|chk
#       Heartbeat: proof the feed is alive, carries no market data.
#   P|seq|ts_ns|symbol|bid|bid_qty|ask|ask_qty|chk
#       Snapshot: the full top-of-book state at `seq`, sent by the
#       venue when a consumer asks to recover. A snapshot heals a gap:
#       the consumer throws away its stale book, takes the snapshot as
#       truth, and resumes expecting seq+1. The snapshot's own seq is
#       the last sequence number it includes, so nothing is double
#       counted. See the recovery section in the handler below.
#
#   seq is a per-session sequence number starting at 1. The handler tracks
#   the expected sequence, counts gaps (missing seq numbers) and duplicates
#   (seq numbers already seen), and keeps a bounded replay buffer of raw
#   lines so a downstream consumer can re-read the recent feed.
#
# The same file also implements a compact binary tick frame, the shape a
# real feed would use on the wire when every byte costs latency:
#
#   byte  0     message type, 0x54 ('T')
#   bytes 1-4   seq, unsigned 32-bit little-endian
#   bytes 5-12  ts_ns, unsigned 64-bit little-endian
#   bytes 13-16 price, signed 32-bit little-endian (ticks)
#   bytes 17-20 qty, unsigned 32-bit little-endian
#   byte  21    side, 'B' (0x42) or 'S' (0x53)
#   byte  22    CRC: XOR of bytes 0..21
#
# What this file demonstrates:
#   1. Strict parsing: checksum first, then field counts, then numeric
#      validation, then business rules (price > 0, qty > 0, bid < ask).
#   2. Sequence-gap and duplicate detection with exact counters.
#   3. Per-symbol last-quote tracking and a bounded replay buffer.
#   4. A binary frame encoder/decoder with CRC, verified by round-trip.
#   5. A scripted feed (including a gap, a duplicate, a corrupt line and a
#      heartbeat) whose handler statistics are asserted exactly.
#   6. Gap recovery: a snapshot heals an open gap, and a simulated
#      retransmission replays the missing lines in order.

from std.testing import assert_equal, assert_true, assert_almost_equal

# ---------------------------------------------------------------------------
# Event kinds. A parsed line becomes exactly one FeedEvent; a line that
# fails validation becomes kind EVT_BAD with ok == False and an error string.
# ---------------------------------------------------------------------------

comptime EVT_BAD = 0
comptime EVT_TRADE = 1
comptime EVT_QUOTE = 2
comptime EVT_NEW_ORDER = 3
comptime EVT_CANCEL = 4
comptime EVT_STATUS = 5
comptime EVT_HEARTBEAT = 6
comptime EVT_SNAPSHOT = 7

comptime SIDE_BUY = 0
comptime SIDE_SELL = 1
comptime SIDE_NONE = -1


# ---------------------------------------------------------------------------
# Checksum: sum of the UTF-8 bytes of a message body, modulo 1000.
# ---------------------------------------------------------------------------

def checksum_of(body: String) -> Int:
    var total = 0
    for b in body.bytes():
        total += Int(b)
    return total % 1000


def make_message(body: String) -> String:
    return body + String("|") + String(checksum_of(body))


# ---------------------------------------------------------------------------
# Strict integer parsing. Returns (ok, value). Rejects empty strings,
# non-digits, and values that would overflow a 64-bit accumulator.
# A single leading "-" is allowed so negative values can be detected and
# then rejected by the caller's business rules with a clear error.
# ---------------------------------------------------------------------------

def parse_int(s: String) -> Tuple[Bool, Int]:
    var n_bytes = s.byte_length()
    if n_bytes == 0:
        return (False, 0)
    var negative = False
    var start = 0
    if s[byte=0] == "-":
        negative = True
        start = 1
        if n_bytes == 1:
            return (False, 0)
    var value = 0
    var i = start
    while i < n_bytes:
        var ch = s[byte=i]
        if ch < "0" or ch > "9":
            return (False, 0)
        var digit = 9
        if ch == "0":
            digit = 0
        elif ch == "1":
            digit = 1
        elif ch == "2":
            digit = 2
        elif ch == "3":
            digit = 3
        elif ch == "4":
            digit = 4
        elif ch == "5":
            digit = 5
        elif ch == "6":
            digit = 6
        elif ch == "7":
            digit = 7
        elif ch == "8":
            digit = 8
        value = value * 10 + digit
        if value > 900_000_000_000_000:
            return (False, 0)
        i += 1
    if negative:
        value = -value
    return (True, value)


def parse_side(s: String) -> Tuple[Bool, Int]:
    if s == "B":
        return (True, SIDE_BUY)
    if s == "S":
        return (True, SIDE_SELL)
    return (False, SIDE_NONE)


# ---------------------------------------------------------------------------
# FeedEvent: the parsed form of one wire message. Fields that a message
# type does not use stay at their defaults (0 or "").
# ---------------------------------------------------------------------------

struct FeedEvent:
    var kind: Int
    var ok: Bool
    var error: String
    var seq: Int
    var ts_ns: Int
    var symbol: String
    var side: Int
    var price: Int
    var qty: Int
    var bid: Int
    var bid_qty: Int
    var ask: Int
    var ask_qty: Int
    var oid: Int
    var status: String

    def __init__(out self):
        self.kind = EVT_BAD
        self.ok = False
        self.error = String("")
        self.seq = 0
        self.ts_ns = 0
        self.symbol = String("")
        self.side = SIDE_NONE
        self.price = 0
        self.qty = 0
        self.bid = 0
        self.bid_qty = 0
        self.ask = 0
        self.ask_qty = 0
        self.oid = 0
        self.status = String("")

    def kind_name(self) -> String:
        if self.kind == EVT_TRADE:
            return String("TRADE")
        if self.kind == EVT_QUOTE:
            return String("QUOTE")
        if self.kind == EVT_NEW_ORDER:
            return String("NEW")
        if self.kind == EVT_CANCEL:
            return String("CANCEL")
        if self.kind == EVT_STATUS:
            return String("STATUS")
        if self.kind == EVT_HEARTBEAT:
            return String("HEARTBEAT")
        if self.kind == EVT_SNAPSHOT:
            return String("SNAPSHOT")
        return String("BAD")

    def describe(self) -> String:
        var s = self.kind_name()
        s = s + String(" seq=") + String(self.seq)
        s = s + String(" ts=") + String(self.ts_ns)
        if self.symbol != "":
            s = s + String(" sym=") + self.symbol
        if self.kind == EVT_TRADE or self.kind == EVT_NEW_ORDER:
            var side_s = String("S")
            if self.side == SIDE_BUY:
                side_s = String("B")
            s = s + String(" side=") + side_s
            s = s + String(" px=") + String(self.price)
            s = s + String(" qty=") + String(self.qty)
        if self.kind == EVT_QUOTE or self.kind == EVT_SNAPSHOT:
            s = s + String(" bid=") + String(self.bid)
            s = s + String("x") + String(self.bid_qty)
            s = s + String(" ask=") + String(self.ask)
            s = s + String("x") + String(self.ask_qty)
        if self.kind == EVT_NEW_ORDER or self.kind == EVT_CANCEL:
            s = s + String(" oid=") + String(self.oid)
        if self.kind == EVT_STATUS:
            s = s + String(" code=") + self.status
        if not self.ok:
            s = s + String(" ERROR: ") + self.error
        return s


# ---------------------------------------------------------------------------
# parse_line: the text parser. Order of checks matters and is deliberate:
#   1. checksum (never trust a corrupted line),
#   2. message type and field count,
#   3. numeric syntax,
#   4. business rules (positive prices/quantities, bid < ask, known side).
# The first failure wins and names itself in `error`.
# ---------------------------------------------------------------------------

def parse_line(line: String) -> FeedEvent:
    var ev = FeedEvent()
    if line.byte_length() == 0:
        ev.error = String("empty line")
        return ev^
    var parts = line.split("|")
    var n = len(parts)
    if n < 3:
        ev.error = String("too few fields")
        return ev^
    # Last field is the checksum; the body is everything before it.
    var chk_ok, chk_given = parse_int(String(parts[n - 1]))
    if not chk_ok:
        ev.error = String("checksum is not numeric")
        return ev^
    var body = String(parts[0])
    var i = 1
    while i < n - 1:
        body = body + String("|") + String(parts[i])
        i += 1
    if checksum_of(body) != chk_given:
        ev.error = String("checksum mismatch")
        return ev^
    var mtype = String(parts[0])
    if mtype == "H":
        if n != 4:
            ev.error = String("heartbeat needs 4 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        if not sok or not tok:
            ev.error = String("heartbeat seq/ts not numeric")
            return ev^
        ev.kind = EVT_HEARTBEAT
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        return ev^
    if mtype == "T":
        if n != 8:
            ev.error = String("trade needs 8 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        var side_ok, side = parse_side(String(parts[4]))
        var pok, price = parse_int(String(parts[5]))
        var qok, qty = parse_int(String(parts[6]))
        if not sok or not tok or not pok or not qok:
            ev.error = String("trade numeric field invalid")
            return ev^
        if not side_ok:
            ev.error = String("trade side must be B or S")
            return ev^
        if price <= 0:
            ev.error = String("trade price must be positive")
            return ev^
        if qty <= 0:
            ev.error = String("trade qty must be positive")
            return ev^
        ev.kind = EVT_TRADE
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        ev.symbol = String(parts[3])
        ev.side = side
        ev.price = price
        ev.qty = qty
        return ev^
    if mtype == "Q":
        if n != 9:
            ev.error = String("quote needs 9 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        var bok, bid = parse_int(String(parts[4]))
        var bqok, bid_qty = parse_int(String(parts[5]))
        var aok, ask = parse_int(String(parts[6]))
        var aqok, ask_qty = parse_int(String(parts[7]))
        if not sok or not tok or not bok or not bqok or not aok or not aqok:
            ev.error = String("quote numeric field invalid")
            return ev^
        if bid <= 0 or ask <= 0:
            ev.error = String("quote prices must be positive")
            return ev^
        if bid >= ask:
            ev.error = String("quote bid must be below ask")
            return ev^
        if bid_qty < 0 or ask_qty < 0:
            ev.error = String("quote qty must not be negative")
            return ev^
        ev.kind = EVT_QUOTE
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        ev.symbol = String(parts[3])
        ev.bid = bid
        ev.bid_qty = bid_qty
        ev.ask = ask
        ev.ask_qty = ask_qty
        return ev^
    if mtype == "P":
        if n != 9:
            ev.error = String("snapshot needs 9 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        var bok, bid = parse_int(String(parts[4]))
        var bqok, bid_qty = parse_int(String(parts[5]))
        var aok, ask = parse_int(String(parts[6]))
        var aqok, ask_qty = parse_int(String(parts[7]))
        if not sok or not tok or not bok or not bqok or not aok or not aqok:
            ev.error = String("snapshot numeric field invalid")
            return ev^
        if bid <= 0 or ask <= 0:
            ev.error = String("snapshot prices must be positive")
            return ev^
        if bid >= ask:
            ev.error = String("snapshot bid must be below ask")
            return ev^
        if bid_qty < 0 or ask_qty < 0:
            ev.error = String("snapshot qty must not be negative")
            return ev^
        ev.kind = EVT_SNAPSHOT
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        ev.symbol = String(parts[3])
        ev.bid = bid
        ev.bid_qty = bid_qty
        ev.ask = ask
        ev.ask_qty = ask_qty
        return ev^
    if mtype == "N":
        if n != 9:
            ev.error = String("new order needs 9 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        var side_ok, side = parse_side(String(parts[4]))
        var pok, price = parse_int(String(parts[5]))
        var qok, qty = parse_int(String(parts[6]))
        var ook, oid = parse_int(String(parts[7]))
        if not sok or not tok or not pok or not qok or not ook:
            ev.error = String("new order numeric field invalid")
            return ev^
        if not side_ok:
            ev.error = String("new order side must be B or S")
            return ev^
        if price <= 0:
            ev.error = String("new order price must be positive")
            return ev^
        if qty <= 0:
            ev.error = String("new order qty must be positive")
            return ev^
        ev.kind = EVT_NEW_ORDER
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        ev.symbol = String(parts[3])
        ev.side = side
        ev.price = price
        ev.qty = qty
        ev.oid = oid
        return ev^
    if mtype == "X":
        if n != 6:
            ev.error = String("cancel needs 6 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        var ook, oid = parse_int(String(parts[4]))
        if not sok or not tok or not ook:
            ev.error = String("cancel numeric field invalid")
            return ev^
        ev.kind = EVT_CANCEL
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        ev.symbol = String(parts[3])
        ev.oid = oid
        return ev^
    if mtype == "S":
        if n != 6:
            ev.error = String("status needs 6 fields")
            return ev^
        var sok, seq = parse_int(String(parts[1]))
        var tok, ts = parse_int(String(parts[2]))
        if not sok or not tok:
            ev.error = String("status seq/ts not numeric")
            return ev^
        var code = String(parts[4])
        if code != "OPEN" and code != "HALT" and code != "CLOSE" and code != "PREOPEN":
            ev.error = String("status code unknown")
            return ev^
        ev.kind = EVT_STATUS
        ev.ok = True
        ev.seq = seq
        ev.ts_ns = ts
        ev.symbol = String(parts[3])
        ev.status = code
        return ev^
    ev.error = String("unknown message type")
    return ev^

# ---------------------------------------------------------------------------
# Binary tick frames (23 bytes, little-endian, XOR CRC in the last byte).
# encode_tick / decode_tick are exact inverses for every in-range input;
# decode rejects wrong lengths, wrong types and CRC failures.
# ---------------------------------------------------------------------------

struct BinTick:
    var ok: Bool
    var error: String
    var seq: Int
    var ts_ns: Int
    var price: Int
    var qty: Int
    var side: Int

    def __init__(out self):
        self.ok = False
        self.error = String("")
        self.seq = 0
        self.ts_ns = 0
        self.price = 0
        self.qty = 0
        self.side = SIDE_NONE


def _put_u32_le(mut frame: List[UInt8], value: Int):
    frame.append(UInt8(value & 0xFF))
    frame.append(UInt8((value >> 8) & 0xFF))
    frame.append(UInt8((value >> 16) & 0xFF))
    frame.append(UInt8((value >> 24) & 0xFF))


def _put_u64_le(mut frame: List[UInt8], value: Int):
    var i = 0
    while i < 8:
        frame.append(UInt8((value >> (i * 8)) & 0xFF))
        i += 1


def _put_i32_le(mut frame: List[UInt8], value: Int):
    # Two's complement: negative values wrap into the unsigned range.
    var u = value
    if u < 0:
        u = u + 4294967296
    _put_u32_le(frame, u)


def _get_u32_le(frame: List[UInt8], off: Int) -> Int:
    return (
        Int(frame[off])
        + Int(frame[off + 1]) * 256
        + Int(frame[off + 2]) * 65536
        + Int(frame[off + 3]) * 16777216
    )


def _get_u64_le(frame: List[UInt8], off: Int) -> Int:
    var v = 0
    var i = 7
    while i >= 0:
        v = v * 256 + Int(frame[off + i])
        i -= 1
    return v


def _get_i32_le(frame: List[UInt8], off: Int) -> Int:
    var u = _get_u32_le(frame, off)
    if u >= 2147483648:
        return u - 4294967296
    return u


def encode_tick(seq: Int, ts_ns: Int, price: Int, qty: Int, side: Int) -> List[UInt8]:
    var frame = List[UInt8]()
    frame.append(0x54)  # 'T'
    _put_u32_le(frame, seq)
    _put_u64_le(frame, ts_ns)
    _put_i32_le(frame, price)
    _put_u32_le(frame, qty)
    if side == SIDE_BUY:
        frame.append(0x42)  # 'B'
    else:
        frame.append(0x53)  # 'S'
    var crc = 0
    var i = 0
    while i < len(frame):
        crc = crc ^ Int(frame[i])
        i += 1
    frame.append(UInt8(crc & 0xFF))
    return frame^


def decode_tick(frame: List[UInt8]) -> BinTick:
    var t = BinTick()
    if len(frame) != 23:
        t.error = String("binary frame must be 23 bytes")
        return t^
    if frame[0] != 0x54:
        t.error = String("binary frame type must be T")
        return t^
    var crc = 0
    var i = 0
    while i < 22:
        crc = crc ^ Int(frame[i])
        i += 1
    if crc != Int(frame[22]):
        t.error = String("binary frame CRC mismatch")
        return t^
    var side_byte = frame[21]
    if side_byte != 0x42 and side_byte != 0x53:
        t.error = String("binary frame side must be B or S")
        return t^
    t.ok = True
    t.seq = _get_u32_le(frame, 1)
    t.ts_ns = _get_u64_le(frame, 5)
    t.price = _get_i32_le(frame, 13)
    t.qty = _get_u32_le(frame, 17)
    if side_byte == 0x42:
        t.side = SIDE_BUY
    else:
        t.side = SIDE_SELL
    return t^


# ---------------------------------------------------------------------------
# FeedHandler: sequence tracking, per-symbol last quotes, bounded replay
# buffer, per-kind counters, and a queue of parsed events for a consumer.
#
# Sequence rules, applied to every well-formed message:
#   seq == expected  -> in order, expected advances by one.
#   seq >  expected  -> a gap: (seq - expected) messages are missing.
#   seq <  expected  -> a duplicate (or late) message; counted, not queued
#                       as new data, but still returned to the caller.
# The first message sets the session: call set_expected_seq before the
# first ingest, or leave the default of 1.
# ---------------------------------------------------------------------------

struct FeedHandler:
    var expected_seq: Int
    var total: Int
    var n_trades: Int
    var n_quotes: Int
    var n_new_orders: Int
    var n_cancels: Int
    var n_statuses: Int
    var n_heartbeats: Int
    var n_gaps: Int
    var gap_messages: Int
    var n_duplicates: Int
    var n_malformed: Int
    var n_bad_checksum: Int
    var n_snapshots: Int
    var n_recovered: Int
    var healed_gaps: Int
    var needs_snapshot: Bool
    var gap_start_seq: Int
    var gap_missing: Int
    var gap_recovered: Int
    var max_replay: Int
    var symbols: List[String]
    var last_bid: List[Int]
    var last_bid_qty: List[Int]
    var last_ask: List[Int]
    var last_ask_qty: List[Int]
    var last_seq: List[Int]
    var replay: List[String]
    var queue: List[FeedEvent]

    def __init__(out self):
        self.expected_seq = 1
        self.total = 0
        self.n_trades = 0
        self.n_quotes = 0
        self.n_new_orders = 0
        self.n_cancels = 0
        self.n_statuses = 0
        self.n_heartbeats = 0
        self.n_gaps = 0
        self.gap_messages = 0
        self.n_duplicates = 0
        self.n_malformed = 0
        self.n_bad_checksum = 0
        self.n_snapshots = 0
        self.n_recovered = 0
        self.healed_gaps = 0
        self.needs_snapshot = False
        self.gap_start_seq = 0
        self.gap_missing = 0
        self.gap_recovered = 0
        self.max_replay = 500
        self.symbols = List[String]()
        self.last_bid = List[Int]()
        self.last_bid_qty = List[Int]()
        self.last_ask = List[Int]()
        self.last_ask_qty = List[Int]()
        self.last_seq = List[Int]()
        self.replay = List[String]()
        self.queue = List[FeedEvent]()

    def set_expected_seq(mut self, seq: Int):
        self.expected_seq = seq

    def set_max_replay(mut self, n: Int):
        self.max_replay = n

    # Index of a symbol in the parallel per-symbol lists, or -1.
    def _sym_index(self, sym: String) -> Int:
        var i = 0
        while i < len(self.symbols):
            if self.symbols[i] == sym:
                return i
            i += 1
        return -1

    # Index of a symbol, creating its slot if this is the first sighting.
    def _touch_symbol(mut self, sym: String) -> Int:
        var idx = self._sym_index(sym)
        if idx >= 0:
            return idx
        self.symbols.append(sym)
        self.last_bid.append(0)
        self.last_bid_qty.append(0)
        self.last_ask.append(0)
        self.last_ask_qty.append(0)
        self.last_seq.append(0)
        return len(self.symbols) - 1

    def ingest(mut self, line: String) -> FeedEvent:
        var ev = parse_line(line)
        self.total += 1
        if not ev.ok:
            self.n_malformed += 1
            if ev.error == "checksum mismatch":
                self.n_bad_checksum += 1
            return ev^
        # Snapshot recovery: a snapshot is the venue's full book state
        # at its seq. It supersedes any missing messages, heals an open
        # gap, and resets the expected sequence to seq + 1. It is not
        # subject to the ordinary gap/duplicate bookkeeping, because it
        # is the recovery mechanism, not ordinary flow.
        if ev.kind == EVT_SNAPSHOT:
            self.n_snapshots += 1
            var sidx = self._touch_symbol(ev.symbol)
            self.last_bid[sidx] = ev.bid
            self.last_bid_qty[sidx] = ev.bid_qty
            self.last_ask[sidx] = ev.ask
            self.last_ask_qty[sidx] = ev.ask_qty
            self.last_seq[sidx] = ev.seq
            if self.needs_snapshot:
                self.healed_gaps += 1
                self.needs_snapshot = False
            if ev.seq + 1 > self.expected_seq:
                self.expected_seq = ev.seq + 1
            if len(self.replay) >= self.max_replay and self.max_replay > 0:
                var _old = self.replay.pop(0)
            self.replay.append(line)
            self.queue.append(ev^)
            var echo = parse_line(line)
            return echo^
        # Retransmission: while a gap is open, a message whose seq lies
        # inside the missing range is a re-sent original, not a
        # duplicate. It is applied to state and queued, and when the
        # whole missing range has arrived the gap is healed.
        var is_retrans = False
        if (
            self.needs_snapshot
            and ev.seq >= self.gap_start_seq
            and ev.seq < self.expected_seq
        ):
            is_retrans = True
            self.n_recovered += 1
            self.gap_recovered += 1
            if self.gap_recovered >= self.gap_missing:
                self.healed_gaps += 1
                self.needs_snapshot = False
        # Sequence bookkeeping (skipped for retransmissions).
        if not is_retrans:
            if ev.seq > self.expected_seq:
                self.n_gaps += 1
                self.gap_messages += ev.seq - self.expected_seq
                self.needs_snapshot = True
                self.gap_start_seq = self.expected_seq
                self.gap_missing = ev.seq - self.expected_seq
                self.gap_recovered = 0
                self.expected_seq = ev.seq + 1
            elif ev.seq < self.expected_seq:
                self.n_duplicates += 1
                return ev^
            else:
                self.expected_seq += 1
        # Per-kind counters and per-symbol state.
        if ev.kind == EVT_TRADE:
            self.n_trades += 1
        elif ev.kind == EVT_QUOTE:
            self.n_quotes += 1
            var idx = self._touch_symbol(ev.symbol)
            self.last_bid[idx] = ev.bid
            self.last_bid_qty[idx] = ev.bid_qty
            self.last_ask[idx] = ev.ask
            self.last_ask_qty[idx] = ev.ask_qty
            self.last_seq[idx] = ev.seq
        elif ev.kind == EVT_NEW_ORDER:
            self.n_new_orders += 1
        elif ev.kind == EVT_CANCEL:
            self.n_cancels += 1
        elif ev.kind == EVT_STATUS:
            self.n_statuses += 1
        elif ev.kind == EVT_HEARTBEAT:
            self.n_heartbeats += 1
        # Bounded replay buffer: drop the oldest line when full.
        if len(self.replay) >= self.max_replay and self.max_replay > 0:
            var _old = self.replay.pop(0)
        self.replay.append(line)
        self.queue.append(ev^)
        # NOTE: the event above was moved into the queue, so return a fresh
        # copy of its key fields via a second parse-free construction. The
        # caller that needs the event should use drain(); ingest's return
        # value is only a status echo. Re-parse is cheap and unambiguous.
        var echo = parse_line(line)
        return echo^

    # Take all queued events out of the handler, in arrival order.
    def drain(mut self) -> List[FeedEvent]:
        var out = List[FeedEvent]()
        while len(self.queue) > 0:
            out.append(self.queue.pop(0))
        return out^

    def last_quote_bid(self, sym: String) -> Int:
        var idx = self._sym_index(sym)
        if idx < 0:
            return 0
        return self.last_bid[idx]

    def last_quote_ask(self, sym: String) -> Int:
        var idx = self._sym_index(sym)
        if idx < 0:
            return 0
        return self.last_ask[idx]

    def last_quote_spread(self, sym: String) -> Int:
        var idx = self._sym_index(sym)
        if idx < 0:
            return -1
        return self.last_ask[idx] - self.last_bid[idx]

    def summary(self) -> String:
        var s = String("feed summary: total=") + String(self.total)
        s = s + String(" trades=") + String(self.n_trades)
        s = s + String(" quotes=") + String(self.n_quotes)
        s = s + String(" new=") + String(self.n_new_orders)
        s = s + String(" cancels=") + String(self.n_cancels)
        s = s + String(" status=") + String(self.n_statuses)
        s = s + String(" heartbeats=") + String(self.n_heartbeats)
        s = s + String(" gaps=") + String(self.n_gaps)
        s = s + String(" missing_msgs=") + String(self.gap_messages)
        s = s + String(" duplicates=") + String(self.n_duplicates)
        s = s + String(" malformed=") + String(self.n_malformed)
        s = s + String(" bad_checksum=") + String(self.n_bad_checksum)
        s = s + String(" snapshots=") + String(self.n_snapshots)
        s = s + String(" recovered=") + String(self.n_recovered)
        s = s + String(" healed_gaps=") + String(self.healed_gaps)
        s = s + String(" expected_next=") + String(self.expected_seq)
        return s

# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------

def test_checksum() raises:
    # Hand-computed byte sums: 'A' is 65; 'A' + 'B' is 65 + 66 = 131.
    assert_equal(checksum_of(String("A")), 65)
    assert_equal(checksum_of(String("AB")), 131)
    assert_equal(checksum_of(String("")), 0)
    var msg = make_message(String("H|1|100"))
    var ev = parse_line(msg)
    assert_true(ev.ok)
    assert_equal(ev.kind, EVT_HEARTBEAT)
    assert_equal(ev.seq, 1)
    assert_equal(ev.ts_ns, 100)
    print("checksum ok: byte-sum checks and a self-consistent message")


def test_parse_int() raises:
    var ok1, v1 = parse_int(String("123"))
    assert_true(ok1)
    assert_equal(v1, 123)
    var ok2, v2 = parse_int(String("-45"))
    assert_true(ok2)
    assert_equal(v2, -45)
    var ok3, _v3 = parse_int(String(""))
    assert_true(not ok3)
    var ok4, _v4 = parse_int(String("12a"))
    assert_true(not ok4)
    var ok5, _v5 = parse_int(String("-"))
    assert_true(not ok5)
    var ok6, v6 = parse_int(String("007"))
    assert_true(ok6)
    assert_equal(v6, 7)
    var ok7, _v7 = parse_int(String("9999999999999999"))
    assert_true(not ok7)
    print("parse_int ok: signs, leading zeros, garbage, overflow")


def test_parse_all_types() raises:
    var t = parse_line(make_message(String("T|7|1000000|AAPL|B|10125|250")))
    assert_true(t.ok)
    assert_equal(t.kind, EVT_TRADE)
    assert_equal(t.seq, 7)
    assert_equal(t.ts_ns, 1000000)
    assert_equal(t.symbol, String("AAPL"))
    assert_equal(t.side, SIDE_BUY)
    assert_equal(t.price, 10125)
    assert_equal(t.qty, 250)
    var q = parse_line(make_message(String("Q|8|1000001|AAPL|10000|5|10100|7")))
    assert_true(q.ok)
    assert_equal(q.kind, EVT_QUOTE)
    assert_equal(q.bid, 10000)
    assert_equal(q.bid_qty, 5)
    assert_equal(q.ask, 10100)
    assert_equal(q.ask_qty, 7)
    var n = parse_line(make_message(String("N|9|1000002|MSFT|S|20200|3|77")))
    assert_true(n.ok)
    assert_equal(n.kind, EVT_NEW_ORDER)
    assert_equal(n.side, SIDE_SELL)
    assert_equal(n.oid, 77)
    var x = parse_line(make_message(String("X|10|1000003|MSFT|77")))
    assert_true(x.ok)
    assert_equal(x.kind, EVT_CANCEL)
    assert_equal(x.oid, 77)
    var s = parse_line(make_message(String("S|11|1000004|AAPL|HALT")))
    assert_true(s.ok)
    assert_equal(s.kind, EVT_STATUS)
    assert_equal(s.status, String("HALT"))
    print("parse-all-types ok: trade, quote, new, cancel, status, heartbeat")


def test_rejections() raises:
    # Tampered body, original checksum: must fail on the checksum.
    var good_chk = checksum_of(String("T|1|100|AAPL|B|10100|5"))
    var bad = (
        String("T|1|100|AAPL|B|10101|5|") + String(good_chk)
    )
    var e1 = parse_line(bad)
    assert_true(not e1.ok)
    assert_equal(e1.error, String("checksum mismatch"))
    var e2 = parse_line(make_message(String("Z|1|100")))
    assert_true(not e2.ok)
    assert_equal(e2.error, String("unknown message type"))
    var e3 = parse_line(make_message(String("T|1|100|AAPL|B|10100")))
    assert_true(not e3.ok)
    assert_equal(e3.error, String("trade needs 8 fields"))
    var e4 = parse_line(make_message(String("T|1|100|AAPL|X|10100|5")))
    assert_true(not e4.ok)
    assert_equal(e4.error, String("trade side must be B or S"))
    var e5 = parse_line(make_message(String("T|1|100|AAPL|B|10100|0")))
    assert_true(not e5.ok)
    assert_equal(e5.error, String("trade qty must be positive"))
    var e6 = parse_line(make_message(String("T|1|100|AAPL|B|-10100|5")))
    assert_true(not e6.ok)
    assert_equal(e6.error, String("trade price must be positive"))
    var e7 = parse_line(make_message(String("T|xx|100|AAPL|B|10100|5")))
    assert_true(not e7.ok)
    assert_equal(e7.error, String("trade numeric field invalid"))
    var e8 = parse_line(make_message(String("Q|1|100|AAPL|10100|5|10000|5")))
    assert_true(not e8.ok)
    assert_equal(e8.error, String("quote bid must be below ask"))
    var e9 = parse_line(make_message(String("S|1|100|AAPL|PAUSED")))
    assert_true(not e9.ok)
    assert_equal(e9.error, String("status code unknown"))
    var e10 = parse_line(String("T|1|100|AAPL|B|10100|5|abc"))
    assert_true(not e10.ok)
    assert_equal(e10.error, String("checksum is not numeric"))
    var e11 = parse_line(String(""))
    assert_true(not e11.ok)
    assert_equal(e11.error, String("empty line"))
    var e12 = parse_line(String("GARBAGE"))
    assert_true(not e12.ok)
    assert_equal(e12.error, String("too few fields"))
    print("rejections ok: 12 malformed messages, each with its own error")


def test_parse_snapshot() raises:
    var p = parse_line(make_message(String("P|9|9000|AAPL|10090|30|10110|25")))
    assert_true(p.ok)
    assert_equal(p.kind, EVT_SNAPSHOT)
    assert_equal(p.seq, 9)
    assert_equal(p.symbol, String("AAPL"))
    assert_equal(p.bid, 10090)
    assert_equal(p.bid_qty, 30)
    assert_equal(p.ask, 10110)
    assert_equal(p.ask_qty, 25)
    var e1 = parse_line(make_message(String("P|9|9000|AAPL|10110|30|10090|25")))
    assert_true(not e1.ok)
    assert_equal(e1.error, String("snapshot bid must be below ask"))
    var e2 = parse_line(make_message(String("P|9|9000|AAPL|10090|30")))
    assert_true(not e2.ok)
    assert_equal(e2.error, String("snapshot needs 9 fields"))
    print("parse snapshot ok: fields, crossed book, wrong field count")


def test_gap_healed_by_snapshot() raises:
    var h = FeedHandler()
    var _a = h.ingest(make_message(String("H|1|100")))
    var _b = h.ingest(make_message(String("Q|2|200|AAPL|10000|5|10100|7")))
    var _c = h.ingest(make_message(String("T|5|500|AAPL|B|10050|10")))
    assert_equal(h.n_gaps, 1)
    assert_equal(h.gap_messages, 2)
    assert_true(h.needs_snapshot)
    # The venue answers with a snapshot covering everything up to 5.
    var _d = h.ingest(make_message(String("P|5|550|AAPL|10090|30|10110|25")))
    assert_equal(h.n_snapshots, 1)
    assert_equal(h.healed_gaps, 1)
    assert_true(not h.needs_snapshot)
    assert_equal(h.expected_seq, 6)
    assert_equal(h.last_quote_bid(String("AAPL")), 10090)
    assert_equal(h.last_quote_ask(String("AAPL")), 10110)
    # Flow resumes cleanly at 6.
    var _e = h.ingest(make_message(String("T|6|600|AAPL|S|10090|4")))
    assert_equal(h.n_gaps, 1)
    assert_equal(h.expected_seq, 7)
    print("snapshot recovery ok: gap healed, book replaced, flow resumes")


def test_gap_healed_by_retransmission() raises:
    var h = FeedHandler()
    var _a = h.ingest(make_message(String("H|1|100")))
    var _b = h.ingest(make_message(String("Q|2|200|AAPL|10000|5|10100|7")))
    var _c = h.ingest(make_message(String("T|5|500|AAPL|B|10050|10")))
    assert_true(h.needs_snapshot)
    # The venue re-sends the two missing messages, in order.
    var _d = h.ingest(make_message(String("T|3|300|AAPL|S|10020|6")))
    assert_equal(h.n_recovered, 1)
    assert_equal(h.healed_gaps, 0)
    var _e = h.ingest(make_message(String("Q|4|400|AAPL|10020|8|10120|9")))
    assert_equal(h.n_recovered, 2)
    assert_equal(h.healed_gaps, 1)
    assert_true(not h.needs_snapshot)
    assert_equal(h.n_duplicates, 0)
    assert_equal(h.expected_seq, 6)
    assert_equal(h.last_quote_bid(String("AAPL")), 10020)
    assert_equal(h.last_quote_ask(String("AAPL")), 10120)
    # Flow resumes at 6; a further re-send of 3 is now a real duplicate.
    var _f = h.ingest(make_message(String("T|6|600|AAPL|B|10120|2")))
    assert_equal(h.expected_seq, 7)
    var _g = h.ingest(make_message(String("T|3|300|AAPL|S|10020|6")))
    assert_equal(h.n_duplicates, 1)
    print("retransmission ok: missing range replayed, gap healed, late dup caught")


def test_snapshot_without_gap() raises:
    var h = FeedHandler()
    var _a = h.ingest(make_message(String("H|1|100")))
    var _b = h.ingest(make_message(String("Q|2|200|AAPL|10000|5|10100|7")))
    var _c = h.ingest(make_message(String("P|3|300|AAPL|10020|8|10120|9")))
    assert_equal(h.n_snapshots, 1)
    assert_equal(h.healed_gaps, 0)
    assert_equal(h.expected_seq, 4)
    assert_equal(h.last_quote_bid(String("AAPL")), 10020)
    print("snapshot without gap ok: state replaced, no healing claimed")


def test_binary_round_trip() raises:
    var f1 = encode_tick(123456, 1700000000123456789, 10125, 250, SIDE_BUY)
    assert_equal(len(f1), 23)
    assert_equal(Int(f1[0]), 0x54)
    var d1 = decode_tick(f1)
    assert_true(d1.ok)
    assert_equal(d1.seq, 123456)
    assert_equal(d1.ts_ns, 1700000000123456789)
    assert_equal(d1.price, 10125)
    assert_equal(d1.qty, 250)
    assert_equal(d1.side, SIDE_BUY)
    # Sell side, minimal values, and a negative price (two's complement).
    var f2 = encode_tick(1, 0, -50, 1, SIDE_SELL)
    var d2 = decode_tick(f2)
    assert_true(d2.ok)
    assert_equal(d2.seq, 1)
    assert_equal(d2.ts_ns, 0)
    assert_equal(d2.price, -50)
    assert_equal(d2.qty, 1)
    assert_equal(d2.side, SIDE_SELL)
    # Flipping one payload bit breaks the CRC.
    var f3 = encode_tick(9, 5000, 10000, 10, SIDE_BUY)
    var b = f3[10]
    f3[10] = b ^ UInt8(1)
    var d3 = decode_tick(f3)
    assert_true(not d3.ok)
    assert_equal(d3.error, String("binary frame CRC mismatch"))
    # Truncated frame.
    var short = List[UInt8]()
    var i = 0
    while i < 22:
        short.append(f3[i])
        i += 1
    var d4 = decode_tick(short)
    assert_true(not d4.ok)
    assert_equal(d4.error, String("binary frame must be 23 bytes"))
    # Wrong type byte.
    var f5 = encode_tick(9, 5000, 10000, 10, SIDE_BUY)
    f5[0] = UInt8(0x51)
    var d5 = decode_tick(f5)
    assert_true(not d5.ok)
    assert_equal(d5.error, String("binary frame type must be T"))
    print("binary ok: round-trips, CRC failure, truncation, wrong type")


def test_handler_stream() raises:
    # Scripted stream: heartbeat, quote, a GAP (seq 3 missing), a
    # duplicate (seq 2 again), new, cancel, status, a bad-checksum line,
    # a garbage line, and a final heartbeat. Note the final heartbeat
    # (seq 10) is itself a second gap: seqs 8 and 9 never arrived as
    # valid messages, because the two corrupt lines carry those seqs
    # but are rejected before sequence bookkeeping.
    var h = FeedHandler()
    var _r1 = h.ingest(make_message(String("H|1|100")))
    var _r2 = h.ingest(make_message(String("Q|2|200|AAPL|10000|5|10100|7")))
    var _r3 = h.ingest(make_message(String("T|4|400|AAPL|B|10050|10")))
    var _r4 = h.ingest(make_message(String("Q|2|250|AAPL|10001|5|10101|7")))
    var _r5 = h.ingest(make_message(String("N|5|500|AAPL|S|10100|3|77")))
    var _r6 = h.ingest(make_message(String("X|6|600|AAPL|77")))
    var _r7 = h.ingest(make_message(String("S|7|700|AAPL|OPEN")))
    var tampered = String("T|8|800|AAPL|B|10050|10|") + String(
        checksum_of(String("T|8|800|AAPL|B|10051|10"))
    )
    var _r8 = h.ingest(tampered)
    var _r9 = h.ingest(String("GARBAGE"))
    var _r10 = h.ingest(make_message(String("H|10|1000")))
    assert_equal(h.total, 10)
    assert_equal(h.n_heartbeats, 2)
    assert_equal(h.n_quotes, 1)
    assert_equal(h.n_trades, 1)
    assert_equal(h.n_new_orders, 1)
    assert_equal(h.n_cancels, 1)
    assert_equal(h.n_statuses, 1)
    assert_equal(h.n_gaps, 2)
    assert_equal(h.gap_messages, 3)
    assert_equal(h.n_duplicates, 1)
    assert_equal(h.n_malformed, 2)
    assert_equal(h.n_bad_checksum, 1)
    assert_equal(h.expected_seq, 11)
    assert_equal(h.last_quote_bid(String("AAPL")), 10000)
    assert_equal(h.last_quote_ask(String("AAPL")), 10100)
    assert_equal(h.last_quote_spread(String("AAPL")), 100)
    assert_equal(len(h.replay), 7)
    var drained = h.drain()
    assert_equal(len(drained), 7)
    assert_equal(drained[0].kind, EVT_HEARTBEAT)
    assert_equal(drained[1].kind, EVT_QUOTE)
    assert_equal(drained[2].kind, EVT_TRADE)
    assert_equal(drained[3].kind, EVT_NEW_ORDER)
    assert_equal(drained[4].kind, EVT_CANCEL)
    assert_equal(drained[5].kind, EVT_STATUS)
    assert_equal(drained[6].kind, EVT_HEARTBEAT)
    assert_equal(len(h.drain()), 0)
    print("handler stream ok: gap, duplicate, corrupt lines counted exactly")
    print("  " + h.summary())


def test_replay_bound_and_expected_seq() raises:
    var h = FeedHandler()
    h.set_max_replay(3)
    h.set_expected_seq(100)
    var _a = h.ingest(make_message(String("H|100|1")))
    var _b = h.ingest(make_message(String("H|101|2")))
    var _c = h.ingest(make_message(String("H|102|3")))
    var _d = h.ingest(make_message(String("H|103|4")))
    var _e = h.ingest(make_message(String("H|104|5")))
    assert_equal(len(h.replay), 3)
    assert_equal(h.expected_seq, 105)
    assert_equal(h.n_heartbeats, 5)
    # Unknown symbol has no quote.
    assert_equal(h.last_quote_spread(String("NOPE")), -1)
    print("replay bound ok: buffer holds the newest 3 of 5 lines")


def test_per_symbol_quotes() raises:
    var h = FeedHandler()
    var _a = h.ingest(make_message(String("Q|1|100|AAPL|10000|5|10100|7")))
    var _b = h.ingest(make_message(String("Q|2|200|MSFT|20000|9|20100|11")))
    var _c = h.ingest(make_message(String("Q|3|300|AAPL|10010|6|10090|8")))
    assert_equal(h.last_quote_bid(String("AAPL")), 10010)
    assert_equal(h.last_quote_ask(String("AAPL")), 10090)
    assert_equal(h.last_quote_spread(String("AAPL")), 80)
    assert_equal(h.last_quote_bid(String("MSFT")), 20000)
    assert_equal(h.last_quote_ask(String("MSFT")), 20100)
    assert_equal(len(h.symbols), 2)
    print("per-symbol ok: two symbols tracked independently")


# ---------------------------------------------------------------------------
# Demo: a tiny scripted feed through the handler.
# ---------------------------------------------------------------------------

def demo() raises:
    print("=== HFT feed handler demo (simulated data, no real market) ===")
    var h = FeedHandler()
    var lines = List[String]()
    lines.append(make_message(String("S|1|1000|AAPL|PREOPEN")))
    lines.append(make_message(String("Q|2|2000|AAPL|10000|50|10100|40")))
    lines.append(make_message(String("N|3|3000|AAPL|B|10000|25|1001")))
    lines.append(make_message(String("T|4|4000|AAPL|B|10100|25")))
    lines.append(make_message(String("H|5|5000")))
    lines.append(make_message(String("T|8|8000|AAPL|B|10100|25")))
    lines.append(make_message(String("P|8|8001|AAPL|10090|30|10110|25")))
    var i = 0
    while i < len(lines):
        var ev = h.ingest(lines[i])
        print("  <-", ev.describe())
        i += 1
    print(h.summary())
    var f = encode_tick(42, 1700000000000000000, 10100, 25, SIDE_BUY)
    var t = decode_tick(f)
    print("binary tick round-trip ok:", t.ok, " seq:", t.seq, " px:", t.price)


def main() raises:
    demo()
    print("=== feed handler tests ===")
    test_checksum()
    test_parse_int()
    test_parse_all_types()
    test_parse_snapshot()
    test_gap_healed_by_snapshot()
    test_gap_healed_by_retransmission()
    test_snapshot_without_gap()
    test_rejections()
    test_binary_round_trip()
    test_handler_stream()
    test_replay_bound_and_expected_seq()
    test_per_symbol_quotes()
    print("ALL FEED HANDLER TESTS PASSED")
