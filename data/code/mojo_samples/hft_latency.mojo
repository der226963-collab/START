# hft_latency.mojo
#
# Original code written for the START project's Mojo code samples.
# Component 3 (HFT FRAMEWORKS): a latency-measurement harness.
#
# SIMULATOR ONLY. This file measures how long simulated matching, parsing
# and risk-checking operations take on this machine. It never connects to
# an exchange, a broker, or any market-data vendor, and no real money is
# involved anywhere.
#
# Standard library only. No external packages, no Python interop, no network.
#
# Why latency is measured this way (the ideas behind the harness):
#
#   * Wall-clock time is measured in nanoseconds with a monotonic counter
#     (perf_counter_ns). A monotonic counter never jumps when the system
#     clock is adjusted, so differences between two readings are real
#     elapsed time. One nanosecond is one billionth of a second; a modern
#     CPU executes roughly one simple instruction per nanosecond, so
#     nanoseconds are the honest unit for this work.
#   * A single operation is timed, not a batch average. Batch averages
#     hide the slow operations, and in trading the slow operations are
#     the ones that lose money. Every sample is kept, then summarised.
#   * The summary is a distribution, not a single number. The mean is
#     reported, but the mean lies: a thousand 100 ns operations and one
#     100,000 ns operation average to about 200 ns, which describes
#     neither group. Percentiles describe the distribution honestly:
#     p50 is the median (half the operations were faster), p99 is the
#     latency that 99% of operations beat (the "almost worst" case), and
#     p999 is the near-worst case. A venue that promises "under a
#     microsecond" is promising a p99, not a mean.
#   * A histogram shows the shape: how many operations landed in each
#     latency bucket. A healthy harness shows one tight cluster; a
#     second cluster far to the right usually means garbage collection,
#     a context switch, or a cache miss.
#   * Warmup matters. The first few operations pay for cold caches and
#     just-in-time compilation, so the harness runs untimed warmup
#     iterations before it starts recording. Without warmup the p99 is
#     dominated by startup effects that never recur in steady state.
#   * The empty-loop benchmark measures the measurement itself: two
#     counter reads plus a loop iteration. If the empty loop costs 40 ns
#     and the operation under test costs 60 ns, the operation really
#     costs about 20 ns of work. Every other number in this file should
#     be read with that floor in mind.
#   * Throughput is derived from the same samples: operations per second
#     is (number of operations) / (total time). It is the inverse view of
#     the same data, useful when sizing how many orders a gateway can
#     absorb.
#   * Determinism: the workloads are generated from a fixed seed, so two
#     runs of this program exercise the same operations in the same
#     order. The absolute nanosecond values will still differ between
#     machines and runs (that is the nature of timing), but the structure
#     -- sample counts, percentile ordering, histogram totals, and the
#     comparison-count advantage of binary search over linear search --
#     is asserted exactly, because it does not depend on the clock.
#
# What this file benchmarks (all on simulated data):
#   1. Level lookup: linear scan vs binary search in a 1,000-level book.
#      The comparison counts are deterministic and asserted; the timings
#      are reported for the reader to see the constant-factor story.
#   2. Top-of-book matching: a market order consuming part of the best
#      level, restored after every timed operation.
#   3. A multi-level sweep: a market order consuming fifteen levels,
#      with the book rebuilt after every timed operation.
#   4. Text tick parsing: splitting and converting a wire message.
#   5. A risk-check pass: the integer arithmetic of quantity, notional
#      and price-band checks.
#   6. The empty loop: the measurement floor.
#
# What this file does NOT do (and says so honestly): it does not claim
# these numbers are what a production venue would see. A benchmark on a
# shared virtual machine with an untuned allocator is a teaching tool,
# not a service-level agreement. The harness is the deliverable; the
# numbers are an example of its output.

from std.testing import assert_equal, assert_true, assert_almost_equal
from std.time import perf_counter_ns
from std.math import sqrt
from std.random import seed, random_ui64
from std.builtin.sort import sort

comptime NS_PER_SEC = 1_000_000_000


# ---------------------------------------------------------------------------
# LatencyStats: a collected distribution of nanosecond samples.
#
# Usage: add() samples in any order, then call finalize() once, which
# sorts the samples in place. Percentiles, min/max and the histogram all
# read the sorted order; mean and standard deviation do not need it.
# ---------------------------------------------------------------------------

struct LatencyStats:
    var label: String
    var samples: List[Int]
    var sorted: Bool

    def __init__(out self, label: String):
        self.label = label
        self.samples = List[Int]()
        self.sorted = False

    def add(mut self, ns: Int):
        self.samples.append(ns)
        self.sorted = False

    def count(self) -> Int:
        return len(self.samples)

    def finalize(mut self):
        if not self.sorted:
            sort(self.samples)
            self.sorted = True

    def min_ns(mut self) -> Int:
        self.finalize()
        if len(self.samples) == 0:
            return 0
        return self.samples[0]

    def max_ns(mut self) -> Int:
        self.finalize()
        if len(self.samples) == 0:
            return 0
        return self.samples[len(self.samples) - 1]

    def mean_ns(self) -> Float64:
        if len(self.samples) == 0:
            return 0.0
        var total: Float64 = 0.0
        var i = 0
        while i < len(self.samples):
            total += Float64(self.samples[i])
            i += 1
        return total / Float64(len(self.samples))

    # Nearest-rank percentile: the smallest sample such that at least p
    # percent of samples are <= it. p50 of [10,20,30,40,50] is 30.
    def percentile(mut self, p: Float64) -> Int:
        self.finalize()
        var n = len(self.samples)
        if n == 0:
            return 0
        var target = p * Float64(n) / 100.0
        var rank = Int(target)
        if Float64(rank) < target:
            rank += 1
        if rank < 1:
            rank = 1
        if rank > n:
            rank = n
        return self.samples[rank - 1]

    def p50(mut self) -> Int:
        return self.percentile(50.0)

    def p90(mut self) -> Int:
        return self.percentile(90.0)

    def p99(mut self) -> Int:
        return self.percentile(99.0)

    def p999(mut self) -> Int:
        return self.percentile(99.9)

    def stddev_ns(self) -> Float64:
        if len(self.samples) == 0:
            return 0.0
        var mean = self.mean_ns()
        var acc: Float64 = 0.0
        var i = 0
        while i < len(self.samples):
            var diff = Float64(self.samples[i]) - mean
            acc += diff * diff
            i += 1
        return sqrt(acc / Float64(len(self.samples)))

    def total_ns(self) -> Int:
        var total = 0
        var i = 0
        while i < len(self.samples):
            total += self.samples[i]
            i += 1
        return total

    # Throughput implied by the samples: operations per second.
    def ops_per_sec(self) -> Float64:
        var total = self.total_ns()
        if total <= 0:
            return 0.0
        return Float64(len(self.samples)) * Float64(NS_PER_SEC) / Float64(total)

    # Histogram: counts per bucket. edges are the upper bounds of the
    # first buckets; the last bucket holds everything above the last edge.
    # With edges [10, 20, 30, 40] and samples [5, 15, 25, 35, 45] the
    # counts are [1, 1, 1, 1, 1].
    def histogram(mut self, edges: List[Int]) -> List[Int]:
        self.finalize()
        var counts = List[Int]()
        var b = 0
        while b < len(edges) + 1:
            counts.append(0)
            b += 1
        var i = 0
        while i < len(self.samples):
            var v = self.samples[i]
            var bucket = len(edges)
            var e = 0
            while e < len(edges):
                if v <= edges[e]:
                    bucket = e
                    break
                e += 1
            counts[bucket] += 1
            i += 1
        return counts^

    def summary(mut self) -> String:
        var s = String("[") + self.label + String("] n=") + String(self.count())
        s = s + String(" mean=") + String(self.mean_ns()) + String("ns")
        s = s + String(" min=") + String(self.min_ns()) + String("ns")
        s = s + String(" p50=") + String(self.p50()) + String("ns")
        s = s + String(" p90=") + String(self.p90()) + String("ns")
        s = s + String(" p99=") + String(self.p99()) + String("ns")
        s = s + String(" p999=") + String(self.p999()) + String("ns")
        s = s + String(" max=") + String(self.max_ns()) + String("ns")
        s = s + String(" stddev=") + String(self.stddev_ns()) + String("ns")
        s = s + String(" throughput=") + String(self.ops_per_sec()) + String(" ops/s")
        return s


# ---------------------------------------------------------------------------
# LevelBook: a minimal ask-side book used as the benchmark workload.
# Prices are integer ticks, strictly increasing; quantities are whole
# units. Two lookup strategies are implemented so the harness can compare
# them on identical data: a linear scan and a binary search. Both return
# (index, comparisons) so the algorithmic difference is measurable
# without any clock at all.
# ---------------------------------------------------------------------------

struct LevelBook:
    var px: List[Int]
    var qty: List[Int]
    var init_px: List[Int]
    var init_qty: List[Int]

    def __init__(out self):
        self.px = List[Int]()
        self.qty = List[Int]()
        self.init_px = List[Int]()
        self.init_qty = List[Int]()

    def build(mut self, n_levels: Int, base: Int, step: Int, qty_each: Int):
        self.px = List[Int]()
        self.qty = List[Int]()
        self.init_px = List[Int]()
        self.init_qty = List[Int]()
        var i = 0
        while i < n_levels:
            var p = base + i * step
            self.px.append(p)
            self.qty.append(qty_each)
            self.init_px.append(p)
            self.init_qty.append(qty_each)
            i += 1

    # Restore the book to its built state (used outside timed regions).
    def refill(mut self):
        self.px = List[Int]()
        self.qty = List[Int]()
        var i = 0
        while i < len(self.init_px):
            self.px.append(self.init_px[i])
            self.qty.append(self.init_qty[i])
            i += 1

    def n_levels(self) -> Int:
        return len(self.px)

    def total_qty(self) -> Int:
        var total = 0
        var i = 0
        while i < len(self.qty):
            total += self.qty[i]
            i += 1
        return total

    # Index of the first level priced >= target, or len(px) if none.
    # Returns (index, comparisons made).
    def find_linear(self, target: Int) -> Tuple[Int, Int]:
        var comps = 0
        var i = 0
        while i < len(self.px):
            comps += 1
            if self.px[i] >= target:
                return (i, comps)
            i += 1
        return (len(self.px), comps)

    def find_binary(self, target: Int) -> Tuple[Int, Int]:
        var comps = 0
        var lo = 0
        var hi = len(self.px)
        while lo < hi:
            var mid = (lo + hi) // 2
            comps += 1
            if self.px[mid] < target:
                lo = mid + 1
            else:
                hi = mid
        return (lo, comps)

    def insert_linear(mut self, price: Int, qty: Int):
        var idx, _comps = self.find_linear(price)
        if idx < len(self.px) and self.px[idx] == price:
            self.qty[idx] += qty
        else:
            self.px.insert(idx, price)
            self.qty.insert(idx, qty)

    def insert_binary(mut self, price: Int, qty: Int):
        var idx, _comps = self.find_binary(price)
        if idx < len(self.px) and self.px[idx] == price:
            self.qty[idx] += qty
        else:
            self.px.insert(idx, price)
            self.qty.insert(idx, qty)

    # Consume qty from the front of the book (best prices first).
    # Returns the quantity actually filled.
    def match_market(mut self, qty: Int) -> Int:
        var remaining = qty
        var filled = 0
        while remaining > 0 and len(self.px) > 0:
            var take = remaining
            if self.qty[0] < take:
                take = self.qty[0]
            self.qty[0] -= take
            remaining -= take
            filled += take
            if self.qty[0] == 0:
                var _dead_px = self.px.pop(0)
                var _dead_qty = self.qty.pop(0)
        return filled

# ---------------------------------------------------------------------------
# Workloads under test.
# ---------------------------------------------------------------------------

def _atoi(s: String) -> Int:
    var value = 0
    for b in s.bytes():
        value = value * 10 + (Int(b) - 48)
    return value


def parse_tick_fields(msg: String) -> Tuple[Int, Int]:
    var parts = msg.split("|")
    var price = _atoi(String(parts[5]))
    var qty = _atoi(String(parts[6]))
    return (price, qty)


def risk_check_inline(price: Int, qty: Int) -> Bool:
    if qty <= 0 or qty > 1000:
        return False
    if price <= 0 or price > 1_000_000:
        return False
    var band = 10000 * 5 // 100
    if price < 10000 - band or price > 10000 + band:
        return False
    if price * qty > 1_000_000:
        return False
    return True


def bench_find_linear(n_ops: Int, n_levels: Int) -> LatencyStats:
    var book = LevelBook()
    book.build(n_levels, 10000, 1, 10)
    seed(20261105)
    var w = 0
    while w < 1000:
        var _i1, _c1 = book.find_linear(10000 + Int(random_ui64(0, 1000)))
        w += 1
    var st = LatencyStats("find-linear")
    var i = 0
    while i < n_ops:
        var target = 10000 + Int(random_ui64(0, 1000))
        var t0 = perf_counter_ns()
        var _idx, _comps = book.find_linear(target)
        var dt = perf_counter_ns() - t0
        st.add(dt)
        i += 1
    return st^


def bench_find_binary(n_ops: Int, n_levels: Int) -> LatencyStats:
    var book = LevelBook()
    book.build(n_levels, 10000, 1, 10)
    seed(20261105)
    var w = 0
    while w < 1000:
        var _i1, _c1 = book.find_binary(10000 + Int(random_ui64(0, 1000)))
        w += 1
    var st = LatencyStats("find-binary")
    var i = 0
    while i < n_ops:
        var target = 10000 + Int(random_ui64(0, 1000))
        var t0 = perf_counter_ns()
        var _idx, _comps = book.find_binary(target)
        var dt = perf_counter_ns() - t0
        st.add(dt)
        i += 1
    return st^


def bench_match_top(n_ops: Int) raises -> LatencyStats:
    var book = LevelBook()
    book.build(200, 10000, 1, 10)
    var w = 0
    while w < 100:
        var _f = book.match_market(7)
        book.qty[0] += 7
        w += 1
    var st = LatencyStats("match-top")
    var filled_total = 0
    var i = 0
    while i < n_ops:
        var t0 = perf_counter_ns()
        var filled = book.match_market(7)
        var dt = perf_counter_ns() - t0
        st.add(dt)
        filled_total += filled
        book.qty[0] += 7
        i += 1
    assert_equal(filled_total, n_ops * 7)
    return st^


def bench_match_sweep(n_ops: Int) raises -> LatencyStats:
    var book = LevelBook()
    book.build(200, 10000, 1, 10)
    var w = 0
    while w < 10:
        var _f = book.match_market(150)
        book.refill()
        w += 1
    var st = LatencyStats("match-sweep-15-levels")
    var filled_total = 0
    var i = 0
    while i < n_ops:
        var t0 = perf_counter_ns()
        var filled = book.match_market(150)
        var dt = perf_counter_ns() - t0
        st.add(dt)
        filled_total += filled
        book.refill()
        i += 1
    assert_equal(filled_total, n_ops * 150)
    return st^


def bench_parse(n_ops: Int) raises -> LatencyStats:
    var msgs = List[String]()
    var expected = 0
    var i = 0
    while i < n_ops:
        var price = 10000 + (i % 50)
        var qty = 1 + (i % 9)
        expected += price + qty
        var msg = (
            String("T|")
            + String(i)
            + String("|1700000000|AAPL|B|")
            + String(price)
            + String("|")
            + String(qty)
        )
        msgs.append(msg)
        i += 1
    var st = LatencyStats("parse-tick")
    var total = 0
    var j = 0
    while j < n_ops:
        var t0 = perf_counter_ns()
        var p, q = parse_tick_fields(msgs[j])
        var dt = perf_counter_ns() - t0
        st.add(dt)
        total += p + q
        j += 1
    assert_equal(total, expected)
    return st^


def bench_risk(n_ops: Int) raises -> LatencyStats:
    seed(777)
    var prices = List[Int]()
    var qtys = List[Int]()
    var expected_ok = 0
    var i = 0
    while i < n_ops:
        var price = 9000 + Int(random_ui64(0, 2000))
        var qty = 1 + Int(random_ui64(0, 1200))
        prices.append(price)
        qtys.append(qty)
        if risk_check_inline(price, qty):
            expected_ok += 1
        i += 1
    var st = LatencyStats("risk-check")
    var ok_count = 0
    var j = 0
    while j < n_ops:
        var t0 = perf_counter_ns()
        var ok = risk_check_inline(prices[j], qtys[j])
        var dt = perf_counter_ns() - t0
        st.add(dt)
        if ok:
            ok_count += 1
        j += 1
    assert_equal(ok_count, expected_ok)
    return st^


def bench_empty(n_ops: Int) -> LatencyStats:
    var st = LatencyStats("empty-loop")
    var i = 0
    while i < n_ops:
        var t0 = perf_counter_ns()
        var dt = perf_counter_ns() - t0
        st.add(dt)
        i += 1
    return st^


# ---------------------------------------------------------------------------
# Tests. The timing assertions are structural (counts, ordering, totals);
# the algorithmic assertions are exact (comparison counts, percentiles of
# a known sample, histogram buckets of a known sample).
# ---------------------------------------------------------------------------

def test_percentiles_known() raises:
    var st = LatencyStats("known")
    st.add(10)
    st.add(20)
    st.add(30)
    st.add(40)
    st.add(50)
    assert_equal(st.count(), 5)
    assert_almost_equal(st.mean_ns(), 30.0, atol=1e-9)
    assert_equal(st.min_ns(), 10)
    assert_equal(st.p50(), 30)
    assert_equal(st.p90(), 50)
    assert_equal(st.p99(), 50)
    assert_equal(st.p999(), 50)
    assert_equal(st.max_ns(), 50)
    assert_almost_equal(st.stddev_ns(), 14.142135623730951, atol=1e-6)
    assert_equal(st.total_ns(), 150)
    assert_almost_equal(st.ops_per_sec(), 33333333.333333336, atol=1.0)
    print("percentiles ok: known sample gives exact mean/p50/p99/stddev")


def test_histogram_known() raises:
    var st = LatencyStats("hist")
    st.add(5)
    st.add(15)
    st.add(25)
    st.add(35)
    st.add(45)
    var edges = List[Int]()
    edges.append(10)
    edges.append(20)
    edges.append(30)
    edges.append(40)
    var counts = st.histogram(edges)
    assert_equal(len(counts), 5)
    assert_equal(counts[0], 1)
    assert_equal(counts[1], 1)
    assert_equal(counts[2], 1)
    assert_equal(counts[3], 1)
    assert_equal(counts[4], 1)
    var total = 0
    var i = 0
    while i < len(counts):
        total += counts[i]
        i += 1
    assert_equal(total, 5)
    print("histogram ok: known sample lands one per bucket")


def test_find_counts() raises:
    var book = LevelBook()
    book.build(1000, 10000, 1, 10)
    var idx1, comps1 = book.find_linear(10999)
    assert_equal(idx1, 999)
    assert_equal(comps1, 1000)
    var idx2, comps2 = book.find_binary(10999)
    assert_equal(idx2, 999)
    assert_true(comps2 <= 10)
    assert_true(comps2 < comps1)
    var idx3, comps3 = book.find_linear(10000)
    assert_equal(idx3, 0)
    assert_equal(comps3, 1)
    var idx4, comps4 = book.find_binary(10000)
    assert_equal(idx4, 0)
    assert_true(comps4 <= 10)
    var idx5, comps5 = book.find_linear(20000)
    assert_equal(idx5, 1000)
    assert_equal(comps5, 1000)
    var idx6, comps6 = book.find_binary(20000)
    assert_equal(idx6, 1000)
    assert_true(comps6 <= 10)
    print("find counts ok: linear 1000 vs binary <=10 on a 1000-level book")


def test_match_correctness() raises:
    var book = LevelBook()
    book.build(5, 10000, 1, 10)
    assert_equal(book.total_qty(), 50)
    assert_equal(book.match_market(7), 7)
    assert_equal(book.total_qty(), 43)
    assert_equal(book.qty[0], 3)
    assert_equal(book.match_market(25), 25)
    assert_equal(book.total_qty(), 18)
    book.refill()
    assert_equal(book.total_qty(), 50)
    assert_equal(book.qty[0], 10)
    print("match correctness ok: partial fills, sweep, refill")


def test_insert_find() raises:
    var book = LevelBook()
    book.build(3, 10000, 1, 10)
    book.insert_linear(10001, 5)
    assert_equal(book.qty[1], 15)
    assert_equal(book.n_levels(), 3)
    book.insert_linear(9999, 4)
    assert_equal(book.n_levels(), 4)
    assert_equal(book.px[0], 9999)
    assert_equal(book.qty[0], 4)
    var book2 = LevelBook()
    book2.build(3, 10000, 1, 10)
    book2.insert_binary(10001, 5)
    assert_equal(book2.qty[1], 15)
    book2.insert_binary(10005, 2)
    assert_equal(book2.n_levels(), 4)
    assert_equal(book2.px[3], 10005)
    print("insert/find ok: merge at existing level, insert at both ends")


def test_benchmarks_small() raises:
    var n = 200
    var s1 = bench_find_linear(n, 200)
    assert_equal(s1.count(), n)
    assert_true(s1.min_ns() <= s1.p50())
    assert_true(s1.p50() <= s1.p90())
    assert_true(s1.p90() <= s1.p99())
    assert_true(s1.p99() <= s1.max_ns())
    assert_true(s1.mean_ns() >= Float64(s1.min_ns()))
    assert_true(s1.mean_ns() <= Float64(s1.max_ns()))
    assert_true(s1.stddev_ns() >= 0.0)
    assert_true(s1.ops_per_sec() > 0.0)
    var edges = List[Int]()
    edges.append(100)
    edges.append(500)
    edges.append(2000)
    var counts = s1.histogram(edges)
    var total = 0
    var i = 0
    while i < len(counts):
        total += counts[i]
        i += 1
    assert_equal(total, n)
    var s2 = bench_find_binary(n, 200)
    assert_equal(s2.count(), n)
    assert_true(s2.p50() <= s2.p99())
    var s3 = bench_match_top(n)
    assert_equal(s3.count(), n)
    var s4 = bench_parse(n)
    assert_equal(s4.count(), n)
    var s5 = bench_risk(n)
    assert_equal(s5.count(), n)
    print("benchmarks small ok: distributions are well-formed, fills exact")


def test_empty_overhead() raises:
    var st = bench_empty(1000)
    assert_equal(st.count(), 1000)
    assert_true(st.p50() < 100000)
    assert_true(st.min_ns() >= 0)
    print("empty overhead ok: measurement floor p50 =", st.p50(), "ns")


# ---------------------------------------------------------------------------
# Demo: the full benchmark suite.
# ---------------------------------------------------------------------------

def demo() raises:
    print("=== HFT latency harness demo (simulated data, no real market) ===")
    print("measuring on this machine; absolute ns values vary by run,")
    print("the structure (counts, ordering, ratios) is what is asserted.")
    var empty = bench_empty(20000)
    print(empty.summary())
    var lin = bench_find_linear(20000, 1000)
    print(lin.summary())
    var bs = bench_find_binary(20000, 1000)
    print(bs.summary())
    var ratio = Float64(lin.p50()) / Float64(bs.p50())
    print("find speedup (linear p50 / binary p50):", ratio, "x")
    print("note: the ~50ns timer floor dominates both searches at this")
    print("size, so the honest comparison is the comparison count")
    print("(linear ~500 avg vs binary <=10, asserted in the tests),")
    print("not the wall-clock ratio on this machine.")
    var top = bench_match_top(20000)
    print(top.summary())
    var sweep = bench_match_sweep(5000)
    print(sweep.summary())
    var parsed = bench_parse(20000)
    print(parsed.summary())
    var risk = bench_risk(20000)
    print(risk.summary())
    var edges = List[Int]()
    edges.append(100)
    edges.append(200)
    edges.append(500)
    edges.append(1000)
    edges.append(2000)
    edges.append(5000)
    var qs = bench_queue_scan(20000, 1000)
    print(qs.summary())
    var qd = bench_queue_dict(20000, 1000)
    print(qd.summary())
    print("queue speedup (scan p50 / dict p50):", Float64(qs.p50()) / Float64(qd.p50()), "x")
    var pipe = bench_pipeline(20000)
    print(pipe.summary())
    var stab = bench_stability(5000)
    print("match-top p50 across 3 runs:", stab[0], stab[1], stab[2], "ns")
    var hist = lin.histogram(edges)
    print("find-linear histogram, edges [100,200,500,1000,2000,5000]ns:")
    print("  <=100:", hist[0], " <=200:", hist[1], " <=500:", hist[2])
    print("  <=1000:", hist[3], " <=2000:", hist[4], " <=5000:", hist[5])
    print("  >5000:", hist[6])


def main() raises:
    demo()
    print("=== latency harness tests ===")
    test_percentiles_known()
    test_histogram_known()
    test_find_counts()
    test_match_correctness()
    test_insert_find()
    test_benchmarks_small()
    test_empty_overhead()
    test_queue_position_counts()
    test_pipeline_small()
    test_stability_small()
    print("ALL LATENCY HARNESS TESTS PASSED")

# ---------------------------------------------------------------------------
# Queue position: finding one order inside a price level.
#
# A matching engine constantly asks "where in the queue is order X?"
# (to cancel it, or to report its position). Two ways to answer: scan
# the level's order ids in order, or keep a map from order id to index.
# The scan is O(n) comparisons; the map is O(1). The comparison counts
# are deterministic and asserted; the timings show the constant-factor
# story on top. (A real engine keeps the map, and pays for it by
# updating the map on every insert and cancel -- there is no free lunch,
# only a choice of where to pay.)
# ---------------------------------------------------------------------------

def bench_queue_scan(n_ops: Int, n_orders: Int) raises -> LatencyStats:
    var ids = List[Int]()
    var i = 0
    while i < n_orders:
        ids.append(i)
        i += 1
    seed(4242)
    var targets = List[Int]()
    var expected = 0
    var j = 0
    while j < n_ops:
        var t = Int(random_ui64(0, UInt64(n_orders - 1)))
        targets.append(t)
        expected += t
        j += 1
    var st = LatencyStats("queue-scan")
    var found_total = 0
    var k = 0
    while k < n_ops:
        var target = targets[k]
        var t0 = perf_counter_ns()
        var idx = -1
        var m = 0
        while m < len(ids):
            if ids[m] == target:
                idx = m
                break
            m += 1
        var dt = perf_counter_ns() - t0
        st.add(dt)
        found_total += idx
        k += 1
    assert_equal(found_total, expected)
    return st^


def bench_queue_dict(n_ops: Int, n_orders: Int) raises -> LatencyStats:
    var index = Dict[Int, Int]()
    var i = 0
    while i < n_orders:
        index[i] = i
        i += 1
    seed(4242)
    var targets = List[Int]()
    var expected = 0
    var j = 0
    while j < n_ops:
        var t = Int(random_ui64(0, UInt64(n_orders - 1)))
        targets.append(t)
        expected += t
        j += 1
    var st = LatencyStats("queue-dict")
    var found_total = 0
    var k = 0
    while k < n_ops:
        var target = targets[k]
        var t0 = perf_counter_ns()
        var idx = index.get(target, -1)
        var dt = perf_counter_ns() - t0
        st.add(dt)
        found_total += idx
        k += 1
    assert_equal(found_total, expected)
    return st^


# ---------------------------------------------------------------------------
# Pipeline: the whole order path in one timed operation -- parse the
# wire message, run the risk arithmetic, match against the book, and
# write the fill report. The stage benchmarks above time each piece
# alone; this one times them together, which is the number a gateway
# actually has to meet. (Percentiles do not add, so the pipeline p50
# is not the sum of the stage p50s; the MEANS roughly are, and the
# demo prints both so the reader can see the difference.)
# ---------------------------------------------------------------------------

def bench_pipeline(n_ops: Int) raises -> LatencyStats:
    var book = LevelBook()
    book.build(200, 10000, 1, 10)
    var msgs = List[String]()
    var expected = 0
    var i = 0
    while i < n_ops:
        var price = 10000 + (i % 50)
        var qty = 1 + (i % 9)
        expected += price + qty
        var msg = (
            String("T|")
            + String(i)
            + String("|1700000000|AAPL|B|")
            + String(price)
            + String("|")
            + String(qty)
        )
        msgs.append(msg)
        i += 1
    var st = LatencyStats("pipeline-parse-risk-match-report")
    var parsed_total = 0
    var filled_total = 0
    var report_px = List[Int]()
    var report_qty = List[Int]()
    var j = 0
    while j < n_ops:
        var t0 = perf_counter_ns()
        var p, q = parse_tick_fields(msgs[j])
        var ok = risk_check_inline(p, q)
        var filled = 0
        if ok:
            filled = book.match_market(q)
            report_px.append(p)
            report_qty.append(filled)
        var dt = perf_counter_ns() - t0
        st.add(dt)
        parsed_total += p + q
        filled_total += filled
        book.qty[0] += filled
        j += 1
    assert_equal(parsed_total, expected)
    assert_equal(len(report_px), n_ops)
    return st^


# ---------------------------------------------------------------------------
# Stability: the same benchmark three times. A benchmark that cannot
# reproduce its own numbers is not measuring the code, it is measuring
# the weather. The p50s of three identical runs should cluster; if
# they do not, the machine was busy and the numbers should be
# re-run, not believed.
# ---------------------------------------------------------------------------

def bench_stability(n_ops: Int) raises -> List[Int]:
    var p50s = List[Int]()
    var r = 0
    while r < 3:
        var st = bench_match_top(n_ops)
        p50s.append(st.p50())
        r += 1
    return p50s^


# ---------------------------------------------------------------------------
# Extra tests.
# ---------------------------------------------------------------------------

def test_queue_position_counts() raises:
    var ids = List[Int]()
    var i = 0
    while i < 1000:
        ids.append(i)
        i += 1
    # Linear scan for the last id costs 1000 comparisons; a dict costs 1.
    var comps = 0
    var idx = -1
    var j = 0
    while j < len(ids):
        comps += 1
        if ids[j] == 999:
            idx = j
            break
        j += 1
    assert_equal(idx, 999)
    assert_equal(comps, 1000)
    var index = Dict[Int, Int]()
    var k = 0
    while k < 1000:
        index[k] = k
        k += 1
    assert_equal(index.get(999, -1), 999)
    assert_equal(index.get(12345, -1), -1)
    print("queue position ok: scan 1000 comparisons, dict 1 lookup")


def test_pipeline_small() raises:
    var st = bench_pipeline(200)
    assert_equal(st.count(), 200)
    assert_true(st.min_ns() <= st.p50())
    assert_true(st.p50() <= st.p99())
    assert_true(st.ops_per_sec() > 0.0)
    var s1 = bench_queue_scan(200, 200)
    var s2 = bench_queue_dict(200, 200)
    assert_equal(s1.count(), 200)
    assert_equal(s2.count(), 200)
    print("pipeline small ok: full path timed, queue scan vs dict timed")


def test_stability_small() raises:
    var p50s = bench_stability(200)
    assert_equal(len(p50s), 3)
    var lo = p50s[0]
    var hi = p50s[0]
    var i = 0
    while i < 3:
        if p50s[i] < lo:
            lo = p50s[i]
        if p50s[i] > hi:
            hi = p50s[i]
        i += 1
    assert_true(lo > 0)
    assert_true(hi <= lo * 10)
    print("stability ok: three runs, p50s within 10x of each other")
