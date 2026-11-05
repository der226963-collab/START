# etl_gen_data.mojo
#
# Synthetic data generator for the START project's Mojo ETL pipeline samples.
#
# Original work, written for this project. Standard library only, no Python
# interop, no network access. Requires Mojo 1.2.0 (stdlib under the `std`
# namespace; `def`, not `fn`). No MAX dependency in this file.
#
# It writes three realistic, deterministic datasets to disk so the other
# pipeline programs have real files to ingest:
#   access.log   - web access logs in combined-log format
#   ticks.csv    - market tick data: timestamp,symbol,price,size,exchange
#   events.jsonl - structured JSON-lines service logs
#
# Determinism: every dataset is produced from a fixed seed, so re-running
# the generator with the same scale reproduces byte-identical files. That
# makes the parallel-vs-reference assertions in the parser programs
# meaningful: the file under test never changes between runs.
#
# Usage:
#   mojo etl_gen_data.mojo [small|medium|large] [output-dir]
# Defaults: medium, /tmp/etl_data
#
# The generator self-checks its output: it re-reads every file it wrote,
# counts lines, spot-checks invariants (prices positive, sizes positive,
# status codes from the known set, JSON lines balanced), and verifies that
# generating the same small sample twice yields identical bytes.

from std.pathlib import Path
from std.testing import assert_equal, assert_true, assert_almost_equal
from std.random import seed, random_float64
from std.sys import argv
from std.os import mkdir

# ---------------------------------------------------------------------------
# Small formatting helpers (no stdlib float formatting exists, so we do our
# own fixed-point rendering).
# ---------------------------------------------------------------------------


def two_digit(n: Int) -> String:
    if n < 10:
        return "0" + String(n)
    return String(n)


def fmt_float2(x: Float64) -> String:
    """Render a float with exactly two digits after the decimal point."""
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


def fmt_float4(x: Float64) -> String:
    """Render a float with exactly four digits after the decimal point."""
    var neg = False
    var v = x
    if v < 0.0:
        neg = True
        v = -v
    var scaled = Int(v * 10000.0 + 0.5)
    var whole = scaled / 10000
    var frac = scaled - whole * 10000
    var frac_str = String(frac)
    while frac_str.byte_length() < 4:
        frac_str = "0" + frac_str
    var out = String(whole) + "." + frac_str
    if neg:
        return "-" + out
    return out


# ---------------------------------------------------------------------------
# Calendar math: epoch seconds -> ISO-8601 UTC timestamp.
# Uses the civil-from-days algorithm (days since 1970-01-01), which handles
# leap years exactly. `days_to_ymd` is the inverse of `ymd_to_days`, and the
# unit tests below check both directions plus a known epoch.
# ---------------------------------------------------------------------------


def days_to_ymd(z: Int) -> Tuple[Int, Int, Int]:
    var zz = z + 719468
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
    return (y, m, d)


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


def format_ts(epoch: Int) -> String:
    """Epoch seconds -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC)."""
    var days = epoch / 86400
    var secs = epoch - days * 86400
    var ymd = days_to_ymd(days)
    var hh = secs / 3600
    var mm = (secs - hh * 3600) / 60
    var ss = secs - hh * 3600 - mm * 60
    return (
        String(ymd[0])
        + "-"
        + two_digit(ymd[1])
        + "-"
        + two_digit(ymd[2])
        + "T"
        + two_digit(hh)
        + ":"
        + two_digit(mm)
        + ":"
        + two_digit(ss)
        + "Z"
    )


def month_name(m: Int) -> String:
    var names = List[String]()
    names.append("Jan")
    names.append("Feb")
    names.append("Mar")
    names.append("Apr")
    names.append("May")
    names.append("Jun")
    names.append("Jul")
    names.append("Aug")
    names.append("Sep")
    names.append("Oct")
    names.append("Nov")
    names.append("Dec")
    return names[m - 1]


def format_log_ts(epoch: Int) -> String:
    """Epoch seconds -> '05/Nov/2026:10:23:11 +0000' (combined log format)."""
    var days = epoch / 86400
    var secs = epoch - days * 86400
    var ymd = days_to_ymd(days)
    var hh = secs / 3600
    var mm = (secs - hh * 3600) / 60
    var ss = secs - hh * 3600 - mm * 60
    return (
        two_digit(ymd[2])
        + "/"
        + month_name(ymd[1])
        + "/"
        + String(ymd[0])
        + ":"
        + two_digit(hh)
        + ":"
        + two_digit(mm)
        + ":"
        + two_digit(ss)
        + " +0000"
    )


# ---------------------------------------------------------------------------
# Random helpers built on the stdlib's seeded global RNG.
# ---------------------------------------------------------------------------


def rand_int(n: Int) -> Int:
    """Uniform integer in [0, n)."""
    return Int(random_float64() * Float64(n))


def pick_str(options: List[String]) -> String:
    return options[rand_int(len(options))]


def rand_ip() -> String:
    # Realistic mix: mostly public ranges, some RFC1918, a few loopback.
    var r = random_float64()
    if r < 0.08:
        return "10." + String(rand_int(256)) + "." + String(rand_int(256)) + "." + String(rand_int(256))
    if r < 0.14:
        return "192.168." + String(rand_int(256)) + "." + String(rand_int(256))
    if r < 0.17:
        return "172." + String(16 + rand_int(16)) + "." + String(rand_int(256)) + "." + String(rand_int(256))
    return (
        String(1 + rand_int(223))
        + "."
        + String(rand_int(256))
        + "."
        + String(rand_int(256))
        + "."
        + String(1 + rand_int(254))
    )


def lognormalish(mean: Float64, spread: Float64) -> Float64:
    """Cheap positive skew: average of uniforms, stretched. Good enough for
    synthetic sizes/latencies; this is a generator, not a statistics library."""
    var u = (random_float64() + random_float64() + random_float64()) / 3.0
    return mean * (1.0 + (u - 0.5) * 2.0 * spread)


# ---------------------------------------------------------------------------
# Static vocabularies. The generator only ever emits values from these
# tables, which is what lets the parsers validate "status in known set"
# and lets the pipeline join on a closed dimension of URLs / symbols.
# ---------------------------------------------------------------------------


def log_urls() -> List[String]:
    var urls = List[String]()
    urls.append("/index.html")
    urls.append("/products")
    urls.append("/products/42")
    urls.append("/products/1087")
    urls.append("/cart")
    urls.append("/checkout")
    urls.append("/search?q=mojo")
    urls.append("/search?q=etl")
    urls.append("/api/v1/users")
    urls.append("/api/v1/orders")
    urls.append("/api/v1/ticks")
    urls.append("/static/app.js")
    urls.append("/static/style.css")
    urls.append("/images/logo.png")
    urls.append("/about")
    urls.append("/login")
    return urls^


def log_methods() -> List[String]:
    var m = List[String]()
    m.append("GET")
    m.append("GET")
    m.append("GET")
    m.append("GET")
    m.append("GET")
    m.append("POST")
    m.append("POST")
    m.append("PUT")
    m.append("DELETE")
    m.append("HEAD")
    return m^


def log_status() -> Int:
    # Weighted status distribution: mostly 200, a long tail of errors.
    var r = random_float64()
    if r < 0.68:
        return 200
    if r < 0.76:
        return 304
    if r < 0.82:
        return 301
    if r < 0.90:
        return 404
    if r < 0.94:
        return 400
    if r < 0.96:
        return 403
    if r < 0.98:
        return 500
    return 503


def log_user_agents() -> List[String]:
    var uas = List[String]()
    uas.append("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36")
    uas.append("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 Version/18.2 Safari/605.1.15")
    uas.append("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0")
    uas.append("curl/8.5.0")
    uas.append("MojoETL-Monitor/1.2 (+https://example.invalid/health)")
    uas.append("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148")
    return uas^


def log_referrers() -> List[String]:
    var refs = List[String]()
    refs.append("-")
    refs.append("-")
    refs.append("https://search.example.com/")
    refs.append("https://news.example.org/article/8812")
    refs.append("/products")
    refs.append("/index.html")
    return refs^


def tick_symbols() -> List[String]:
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


def tick_base_price(symbol: String) -> Float64:
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


def tick_exchanges() -> List[String]:
    var e = List[String]()
    e.append("NYSE")
    e.append("NASDAQ")
    e.append("NYSE")
    e.append("NASDAQ")
    e.append("BATS")
    return e^


def json_services() -> List[String]:
    var s = List[String]()
    s.append("gateway")
    s.append("auth")
    s.append("orders")
    s.append("pricing")
    s.append("inventory")
    s.append("notify")
    return s^


def json_level() -> String:
    var r = random_float64()
    if r < 0.62:
        return "INFO"
    if r < 0.82:
        return "DEBUG"
    if r < 0.93:
        return "WARN"
    return "ERROR"


def json_regions() -> List[String]:
    var r = List[String]()
    r.append("us-east-1")
    r.append("us-west-2")
    r.append("eu-west-1")
    r.append("ap-south-1")
    return r^


def json_message(level: String, service: String) -> String:
    if level == "ERROR":
        var msgs = List[String]()
        msgs.append("upstream timeout after 3000ms")
        msgs.append("connection reset by peer")
        msgs.append("order validation failed: negative quantity")
        msgs.append("payment gateway returned 502")
        msgs.append("cache stampede detected on hot key")
        return pick_str(msgs)
    if level == "WARN":
        var msgs = List[String]()
        msgs.append("retrying upstream request (attempt 2)")
        msgs.append("slow query: 812ms on orders table")
        msgs.append("rate limit approaching for client")
        msgs.append("deprecated endpoint called")
        return pick_str(msgs)
    if level == "DEBUG":
        var msgs = List[String]()
        msgs.append("cache hit for key")
        msgs.append("request headers parsed")
        msgs.append("connection pool checkout ok")
        return pick_str(msgs)
    var msgs = List[String]()
    msgs.append("request completed")
    msgs.append("order placed")
    msgs.append("price snapshot published")
    msgs.append("user session refreshed")
    msgs.append("inventory reserved")
    return pick_str(msgs)

# ---------------------------------------------------------------------------
# Generators. Each one returns the full file content as one String built
# from a List of lines (join is linear; repeated `+` on a growing String
# would be quadratic). Lines are produced in timestamp order so downstream
# time-bucketing never has to sort.
# ---------------------------------------------------------------------------


def gen_access_log(n_lines: Int, start_epoch: Int) -> String:
    var urls = log_urls()
    var methods = log_methods()
    var uas = log_user_agents()
    var refs = log_referrers()
    var lines = List[String]()
    var ts = start_epoch
    for _ in range(n_lines):
        ts += 1 + rand_int(4)
        var method = pick_str(methods)
        var url = pick_str(urls)
        var status = log_status()
        var size: Int
        if status == 200:
            size = Int(lognormalish(4200.0, 0.9))
            if size < 120:
                size = 120
        elif status == 304 or status == 301:
            size = rand_int(400)
        else:
            size = 180 + rand_int(2400)
        var referrer = pick_str(refs)
        var ua = pick_str(uas)
        var line = (
            rand_ip()
            + " - - ["
            + format_log_ts(ts)
            + '] "'
            + method
            + " "
            + url
            + ' HTTP/1.1" '
            + String(status)
            + " "
            + String(size)
            + ' "'
            + referrer
            + '" "'
            + ua
            + '"'
        )
        lines.append(line)
    return String("\n").join(lines) + "\n"


def gen_ticks(n_lines: Int, start_epoch: Int) -> String:
    var symbols = tick_symbols()
    var exchanges = tick_exchanges()
    # Random-walk state per symbol, kept in parallel lists.
    var prices = List[Float64]()
    for s in symbols:
        prices.append(tick_base_price(s))
    var lines = List[String]()
    var ts = start_epoch
    for _ in range(n_lines):
        ts += rand_int(3)
        var si = rand_int(len(symbols))
        var sym = symbols[si]
        var price = prices[si]
        # Random walk: small drift plus a shock, reflected at a floor so
        # prices stay strictly positive (a parser invariant).
        var shock = (random_float64() - 0.5) * 0.02 * price
        var drift = 0.00002 * price
        price = price + drift + shock
        if price < 1.0:
            price = 1.0 + random_float64() * 2.0
        prices[si] = price
        var size = 1 + rand_int(500)
        if random_float64() < 0.05:
            size = 1000 + rand_int(9000)
        var line = (
            String(ts)
            + ","
            + sym
            + ","
            + fmt_float2(price)
            + ","
            + String(size)
            + ","
            + pick_str(exchanges)
        )
        lines.append(line)
    var header = "timestamp,symbol,price,size,exchange\n"
    return header + String("\n").join(lines) + "\n"


def gen_jsonl(n_lines: Int, start_epoch: Int) -> String:
    var services = json_services()
    var regions = json_regions()
    var lines = List[String]()
    var ts = start_epoch
    for _ in range(n_lines):
        ts += 1 + rand_int(3)
        var level = json_level()
        var service = pick_str(services)
        var latency = lognormalish(42.0, 1.4)
        if latency < 0.5:
            latency = 0.5
        if level == "ERROR":
            latency = latency + 900.0 + random_float64() * 1800.0
        elif level == "WARN":
            latency = latency + 120.0 + random_float64() * 500.0
        var req = "req-" + String(100000 + rand_int(900000))
        var msg = json_message(level, service)
        var statuses = List[Int]()
        statuses.append(200)
        statuses.append(200)
        statuses.append(200)
        statuses.append(201)
        statuses.append(204)
        statuses.append(301)
        statuses.append(400)
        statuses.append(401)
        statuses.append(403)
        statuses.append(404)
        statuses.append(500)
        statuses.append(502)
        statuses.append(503)
        var status = statuses[rand_int(len(statuses))]
        if level == "ERROR":
            status = 500 + rand_int(4)
        var line = (
            '{"ts":"'
            + format_ts(ts)
            + '","level":"'
            + level
            + '","service":"'
            + service
            + '","msg":"'
            + msg
            + '","latency_ms":'
            + fmt_float2(latency)
            + ',"status":'
            + String(status)
            + ',"request_id":"'
            + req
            + '","meta":{"region":"'
            + pick_str(regions)
            + '"}}'
        )
        lines.append(line)
    return String("\n").join(lines) + "\n"


# ---------------------------------------------------------------------------
# Verification: re-read what was written and check invariants.
# ---------------------------------------------------------------------------


def count_lines(text: String) -> Int:
    var n = 0
    for line in text.split("\n"):
        if line.byte_length() > 0:
            n += 1
    return n


def verify_access_log(path: Path, expect_lines: Int) raises:
    var text = path.read_text()
    var lines = text.split("\n")
    var seen = 0
    var bad_status = 0
    for line in lines:
        if line.byte_length() == 0:
            continue
        seen += 1
        # Status is the token after the closing quote of the request.
        var q = line.find('"')
        # Second quote: search the remainder of the line.
        var after_first = String(line[byte = q + 1 : line.byte_length()])
        var q2rel = after_first.find('"')
        var q2 = q + 1 + q2rel
        assert_true(q >= 0 and q2 > q, "log line must contain a quoted request")
        var rest = String(line[byte = q2 + 2 : line.byte_length()])
        var parts = rest.split(" ")
        var status = Int(String(parts[0]))
        if status != 200 and status != 301 and status != 304 and status != 400 and status != 403 and status != 404 and status != 500 and status != 503:
            bad_status += 1
    assert_equal(seen, expect_lines)
    assert_equal(bad_status, 0)
    print("  access.log OK:", seen, "lines, all statuses in the known set")


def verify_ticks(path: Path, expect_lines: Int) raises:
    var text = path.read_text()
    var lines = text.split("\n")
    var seen = 0
    var bad = 0
    for line in lines:
        if line.byte_length() == 0:
            continue
        if String(line) == "timestamp,symbol,price,size,exchange":
            continue
        seen += 1
        var parts = line.split(",")
        if len(parts) != 5:
            bad += 1
            continue
        var price = Float64(String(parts[2]))
        var size = Int(String(parts[3]))
        if price <= 0.0 or size <= 0:
            bad += 1
    assert_equal(seen, expect_lines)
    assert_equal(bad, 0)
    print("  ticks.csv OK:", seen, "trades, all prices/sizes positive")


def verify_jsonl(path: Path, expect_lines: Int) raises:
    var text = path.read_text()
    var lines = text.split("\n")
    var seen = 0
    var bad = 0
    for line in lines:
        if line.byte_length() == 0:
            continue
        seen += 1
        var s = String(line)
        if not s.startswith("{") or not s.endswith("}"):
            bad += 1
        if s.find('"level":"') < 0 or s.find('"service":"') < 0 or s.find('"latency_ms":') < 0:
            bad += 1
    assert_equal(seen, expect_lines)
    assert_equal(bad, 0)
    print("  events.jsonl OK:", seen, "events, all objects well-formed")


# ---------------------------------------------------------------------------
# Unit tests (run on every invocation; they use tiny inputs and no files
# except the determinism check, which compares two in-memory generations).
# ---------------------------------------------------------------------------


def test_calendar() raises:
    assert_equal(format_ts(0), "1970-01-01T00:00:00Z")
    assert_equal(format_ts(1793836800), "2026-11-05T00:00:00Z")
    assert_equal(format_ts(1768465800), "2026-01-15T08:30:00Z")
    assert_equal(format_ts(86400), "1970-01-02T00:00:00Z")
    assert_equal(format_log_ts(1793836800), "05/Nov/2026:00:00:00 +0000")
    # Round-trip: ymd -> days -> ymd for a spread of dates incl. leap day.
    var dates = List[Tuple[Int, Int, Int]]()
    dates.append((1970, 1, 1))
    dates.append((2000, 2, 29))
    dates.append((2024, 2, 29))
    dates.append((2026, 11, 5))
    dates.append((1999, 12, 31))
    dates.append((2100, 3, 1))
    for d in dates:
        var back = days_to_ymd(ymd_to_days(d[0], d[1], d[2]))
        assert_equal(back[0], d[0])
        assert_equal(back[1], d[1])
        assert_equal(back[2], d[2])
    print("  test_calendar OK")


def test_formatting() raises:
    assert_equal(fmt_float2(0.0), "0.00")
    assert_equal(fmt_float2(123.456), "123.46")
    assert_equal(fmt_float2(3.1), "3.10")
    assert_equal(fmt_float2(-2.5), "-2.50")
    assert_equal(fmt_float4(1.23456), "1.2346")
    assert_equal(fmt_float4(0.5), "0.5000")
    assert_equal(two_digit(5), "05")
    assert_equal(two_digit(12), "12")
    print("  test_formatting OK")


def test_determinism() raises:
    seed(777)
    var a = gen_access_log(200, 1793836800)
    seed(777)
    var b = gen_access_log(200, 1793836800)
    assert_equal(a, b)
    seed(777)
    var c = gen_ticks(200, 1793836800)
    seed(777)
    var d = gen_ticks(200, 1793836800)
    assert_equal(c, d)
    seed(777)
    var e = gen_jsonl(200, 1793836800)
    seed(777)
    var f = gen_jsonl(200, 1793836800)
    assert_equal(e, f)
    # Different seeds must differ (guards against a silently constant RNG).
    seed(778)
    var g = gen_access_log(200, 1793836800)
    assert_true(a != g, "different seeds must produce different logs")
    print("  test_determinism OK")


def test_generated_line_shapes() raises:
    seed(99)
    var log = gen_access_log(1, 1793836800)
    var parts = log.split(" ")
    assert_true(len(parts) >= 10, "combined log line has many fields")
    assert_true(String(parts[3]).startswith("[05/Nov/2026:00:00:0"), "log ts is in range")
    seed(99)
    var ticks = gen_ticks(1, 1793836800)
    var tlines = ticks.split("\n")
    assert_equal(String(tlines[0]), "timestamp,symbol,price,size,exchange")
    assert_equal(len(tlines[1].split(",")), 5)
    seed(99)
    var ev = gen_jsonl(1, 1793836800)
    assert_true(ev.startswith('{"ts":"2026-11-05'), "jsonl starts with ts")
    assert_true(ev.find('"meta":{"region":"') >= 0, "jsonl has nested meta")
    print("  test_generated_line_shapes OK")


def run_tests() raises:
    print("Running unit tests:")
    test_calendar()
    test_formatting()
    test_determinism()
    test_generated_line_shapes()
    print("All generator unit tests passed.")


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def main() raises:
    run_tests()
    var args = argv()
    var scale = "medium"
    if len(args) > 1:
        scale = String(args[1])
    var out_dir = "/tmp/etl_data"
    if len(args) > 2:
        out_dir = String(args[2])
    var n_log = 100000
    var n_tick = 250000
    var n_json = 50000
    if scale == "small":
        n_log = 5000
        n_tick = 10000
        n_json = 3000
    elif scale == "large":
        n_log = 500000
        n_tick = 1000000
        n_json = 250000
    elif scale != "medium":
        print("Unknown scale '" + scale + "', expected small|medium|large.")
        print("Usage: mojo etl_gen_data.mojo [small|medium|large] [output-dir]")
        return
    print("Generating " + scale + " datasets in " + out_dir + " ...")
    if not Path(out_dir).exists():
        mkdir(out_dir)
    var start_epoch = 1793836800  # 2026-11-05T00:00:00Z
    seed(20261105)
    var log_text = gen_access_log(n_log, start_epoch)
    var log_path = Path(out_dir + "/access.log")
    log_path.write_text(log_text)
    print("  wrote access.log:", log_text.byte_length(), "bytes")
    seed(20261106)
    var tick_text = gen_ticks(n_tick, start_epoch)
    var tick_path = Path(out_dir + "/ticks.csv")
    tick_path.write_text(tick_text)
    print("  wrote ticks.csv:", tick_text.byte_length(), "bytes")
    seed(20261107)
    var json_text = gen_jsonl(n_json, start_epoch)
    var json_path = Path(out_dir + "/events.jsonl")
    json_path.write_text(json_text)
    print("  wrote events.jsonl:", json_text.byte_length(), "bytes")
    print("Verifying written files:")
    verify_access_log(log_path, n_log)
    verify_ticks(tick_path, n_tick)
    verify_jsonl(json_path, n_json)
    print("DONE: generated", n_log, "log lines,", n_tick, "ticks,", n_json, "events in", out_dir)
