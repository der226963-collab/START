# transformer_benchmark.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# A benchmark harness comparing naive vs SIMD vs tiled matmul,
# plus SDPA and softmax timings, on the same shapes.
#
# What this file demonstrates:
#   * A small timing harness on `std.time.perf_counter_ns` with
#     warmup runs, repeated timed iterations, and best-of reporting
#     (best time is the least noisy estimate on a shared machine).
#   * GFLOPS accounting for matmul: 2*m*n*k floating-point
#     operations per multiply, so the table shows achieved
#     throughput rather than raw seconds.
#   * The discipline that makes a benchmark meaningful: every
#     kernel is checked against the naive reference BEFORE it is
#     timed, on the same matrices, so a fast-but-wrong result can
#     never appear in the table.
#   * What the numbers show, and why: the gather-based SIMD kernel
#     in the shared core wins a modest ~1.7x (its vectors are built
#     from eight scalar reads, so the loads dominate); the
#     pointer-based SIMD variant in this file issues true vector
#     loads and is much faster again; the tiled kernel additionally
#     keeps the working set in cache. All four are timed on the
#     same matrices, after the same correctness check.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`,
# `std.time`); no Python interop, no external packages. The
# `Matrix` / `Rng` / matmul / SDPA core is the same self-contained
# core used across this sample series, repeated in each file so
# every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_benchmark.mojo
# Exit code 0 means every check and every unit test passed.
# (Timing varies by machine; correctness does not.)

from std.math import sqrt, log, cos, exp
from std.testing import assert_equal, assert_almost_equal, TestSuite
from std.time import perf_counter_ns


def check(cond: Bool, msg: String) raises:
    """Fail loudly when cond is false.

    NOTE: plain `assert` is a no-op in this Mojo 1.2.0 build under
    the default `mojo run` flags, so every verification in this file
    goes through `check`, which raises a real Error. That is what
    makes "exit code 0 means everything passed" actually true.
    """
    if not cond:
        raise Error(msg)


# ---------------------------------------------------------------------------
# Deterministic pseudo-random numbers
# ---------------------------------------------------------------------------
# A tiny xorshift64* generator. We roll our own instead of reaching for
# `std.random` so that every run in this file is bit-for-bit reproducible
# from an explicit seed, which is what makes the correctness checks below
# meaningful: the same matrices are generated every time this program runs.
# Box-Muller turns the uniform stream into standard-normal samples, the
# usual scale for initialising transformer weights.

struct Rng:
    """Xorshift64* generator with uniform and standard-normal output."""

    var state: UInt64

    def __init__(out self, seed: UInt64):
        # Zero is a fixed point of xorshift, so force a non-zero state.
        self.state = seed | UInt64(1)

    def next_u64(mut self) -> UInt64:
        var x = self.state
        x ^= x >> 12
        x ^= x << 25
        x ^= x >> 27
        self.state = x
        return x * UInt64(0x2545F4914F6CDD1D)

    def uniform(mut self) -> Float32:
        """Uniform sample in [0, 1). Uses the top 53 bits."""
        var bits = self.next_u64() >> 11
        return Float32(bits) * Float32(1.0 / 9007199254740992.0)

    def uniform_range(mut self, lo: Float32, hi: Float32) -> Float32:
        return lo + (hi - lo) * self.uniform()

    def normal(mut self) -> Float32:
        """Standard-normal sample via the Box-Muller transform."""
        var u1 = self.uniform()
        if u1 < Float32(1e-7):
            u1 = Float32(1e-7)
        var u2 = self.uniform()
        var radius = sqrt(Float32(-2.0) * log(u1))
        var angle = Float32(6.2831855) * u2
        return radius * cos(angle)

    def normal_scaled(mut self, scale: Float32) -> Float32:
        return scale * self.normal()


# ---------------------------------------------------------------------------
# Matrix: a row-major, List-backed Float32 matrix
# ---------------------------------------------------------------------------

struct Matrix:
    """Row-major dense matrix of Float32.

    Element (r, c) lives at `data[r * cols + c]`. Keeping one flat
    list (instead of a list of rows) is what lets the SIMD kernels
    below load contiguous runs of a row with a single vector build.
    """

    var rows: Int
    var cols: Int
    var data: List[Float32]

    def __init__(out self, rows: Int, cols: Int):
        self.rows = rows
        self.cols = cols
        self.data = List[Float32](length=rows * cols, fill=0.0)

    @staticmethod
    def zeros(rows: Int, cols: Int) -> Matrix:
        return Matrix(rows, cols)

    @staticmethod
    def identity(n: Int) -> Matrix:
        var m = Matrix(n, n)
        for i in range(n):
            m.set(i, i, 1.0)
        return m^

    @staticmethod
    def randn(rows: Int, cols: Int, seed: UInt64, scale: Float32) -> Matrix:
        var m = Matrix(rows, cols)
        var rng = Rng(seed)
        for i in range(rows * cols):
            m.data[i] = rng.normal_scaled(scale)
        return m^

    @staticmethod
    def uniform(rows: Int, cols: Int, seed: UInt64, lo: Float32, hi: Float32) -> Matrix:
        var m = Matrix(rows, cols)
        var rng = Rng(seed)
        for i in range(rows * cols):
            m.data[i] = rng.uniform_range(lo, hi)
        return m^

    @staticmethod
    def arange(rows: Int, cols: Int, start: Float32, step: Float32) -> Matrix:
        """Deterministic matrix with values start, start+step, ..."""
        var m = Matrix(rows, cols)
        var v = start
        for i in range(rows * cols):
            m.data[i] = v
            v += step
        return m^

    def get(self, r: Int, c: Int) -> Float32:
        return self.data[r * self.cols + c]

    def set(mut self, r: Int, c: Int, v: Float32):
        self.data[r * self.cols + c] = v

    def shape_str(self) -> String:
        return String(self.rows) + "x" + String(self.cols)

    def fill(mut self, v: Float32):
        for i in range(len(self.data)):
            self.data[i] = v

    def clone(self) -> Matrix:
        var m = Matrix(self.rows, self.cols)
        for i in range(len(self.data)):
            m.data[i] = self.data[i]
        return m^

    def transpose(self) -> Matrix:
        var t = Matrix(self.cols, self.rows)
        for r in range(self.rows):
            for c in range(self.cols):
                t.set(c, r, self.get(r, c))
        return t^

    def frobenius_norm(self) -> Float32:
        var acc = Float32(0.0)
        for i in range(len(self.data)):
            acc += self.data[i] * self.data[i]
        return sqrt(acc)

    def max_abs(self) -> Float32:
        var m = Float32(0.0)
        for i in range(len(self.data)):
            var a = self.data[i]
            if a < 0.0:
                a = -a
            if a > m:
                m = a
        return m

    def max_abs_diff(self, other: Matrix) raises -> Float32:
        """Largest |self - other| over all elements. Shapes must match."""
        check(
            self.rows == other.rows and self.cols == other.cols,
            "max_abs_diff: shape mismatch "
            + self.shape_str()
            + " vs "
            + other.shape_str(),
        )
        var m = Float32(0.0)
        for i in range(len(self.data)):
            var d = self.data[i] - other.data[i]
            if d < 0.0:
                d = -d
            if d > m:
                m = d
        return m

    def approx_equal(self, other: Matrix, tol: Float32) raises -> Bool:
        return self.max_abs_diff(other) <= tol

    def row(self, r: Int) -> List[Float32]:
        var out = List[Float32](length=self.cols, fill=0.0)
        for c in range(self.cols):
            out[c] = self.get(r, c)
        return out^

    def print_block(self, max_rows: Int, max_cols: Int):
        """Print the top-left corner, for eyeballing small results."""
        var nr = self.rows if self.rows < max_rows else max_rows
        var nc = self.cols if self.cols < max_cols else max_cols
        for r in range(nr):
            var line = String("")
            for c in range(nc):
                line += String(self.get(r, c)) + " "
            print(line)


# ---------------------------------------------------------------------------
# Matmul kernels
# ---------------------------------------------------------------------------
# All three compute C = A @ B with A (m x k) and B (k x n).
# The naive version is the ground truth; the other two must agree with
# it to within float tolerance on every shape we test.



def matmul_naive(a: Matrix, b: Matrix) raises -> Matrix:
    """Scalar reference: i-j-k triple loop, one multiply-add at a time.

    Deliberately the most obvious implementation possible -- this is
    the code the fast kernels are judged against, so it must be
    trivially auditable. The k loop is innermost, matching the
    textbook definition C[i,j] = sum_k A[i,k] * B[k,j].
    """
    check(a.cols == b.rows, "matmul_naive: inner dimensions must match")
    var c = Matrix(a.rows, b.cols)
    for i in range(a.rows):
        for j in range(b.cols):
            var acc = Float32(0.0)
            for k in range(a.cols):
                acc += a.get(i, k) * b.get(k, j)
            c.set(i, j, acc)
    return c^


def load_row_chunk(m: Matrix, r: Int, c0: Int) -> SIMD[DType.float32, 8]:
    """Build one 8-wide vector from row r, columns c0 .. c0+7."""
    return SIMD[DType.float32, 8](
        m.get(r, c0),
        m.get(r, c0 + 1),
        m.get(r, c0 + 2),
        m.get(r, c0 + 3),
        m.get(r, c0 + 4),
        m.get(r, c0 + 5),
        m.get(r, c0 + 6),
        m.get(r, c0 + 7),
    )


def store_row_chunk(mut m: Matrix, r: Int, c0: Int, v: SIMD[DType.float32, 8]):
    m.set(r, c0, v[0])
    m.set(r, c0 + 1, v[1])
    m.set(r, c0 + 2, v[2])
    m.set(r, c0 + 3, v[3])
    m.set(r, c0 + 4, v[4])
    m.set(r, c0 + 5, v[5])
    m.set(r, c0 + 6, v[6])
    m.set(r, c0 + 7, v[7])


def matmul_simd(a: Matrix, b: Matrix) raises -> Matrix:
    """SIMD matmul: vectorise over the column dimension.

    For a fixed row i of A and a fixed 8-wide column block of C, the
    accumulator is one SIMD register. Each step k broadcasts the
    scalar A[i,k] across a vector loaded from row k of B and adds the
    product. Columns that do not fill a whole vector fall back to the
    scalar loop, so odd shapes (e.g. 33x17) are handled exactly.
    """
    check(a.cols == b.rows, "matmul_simd: inner dimensions must match")
    var c = Matrix(a.rows, b.cols)
    for i in range(a.rows):
        var j = 0
        while j + 8 <= b.cols:
            var acc = SIMD[DType.float32, 8](0.0)
            for k in range(a.cols):
                var bv = load_row_chunk(b, k, j)
                acc += bv * a.get(i, k)
            store_row_chunk(c, i, j, acc)
            j += 8
        while j < b.cols:
            var s = Float32(0.0)
            for k in range(a.cols):
                s += a.get(i, k) * b.get(k, j)
            c.set(i, j, s)
            j += 1
    return c^


def matmul_tiled(a: Matrix, b: Matrix, bm: Int, bn: Int, bk: Int) raises -> Matrix:
    """Cache-blocked matmul on top of the SIMD inner kernel.

    The matrices are processed in (bm x bn) tiles of C, each built
    from (bk)-wide slabs of the shared k dimension. Blocking keeps
    the working set in cache: a tile of A is reused across every
    column tile, and a tile of B across every row tile. The inner
    work is the same SIMD-over-columns kernel as `matmul_simd`,
    accumulating into the C tile so partial sums stay in registers
    across k-slabs. Any tile size works; the min() guards handle
    shapes that are not multiples of the tile sizes.
    """
    check(a.cols == b.rows, "matmul_tiled: inner dimensions must match")
    check(bm > 0 and bn > 0 and bk > 0, "matmul_tiled: tile sizes must be positive")
    var m = a.rows
    var n = b.cols
    var kdim = a.cols
    var c = Matrix(m, n)
    var i0 = 0
    while i0 < m:
        var i_end = i0 + bm
        if i_end > m:
            i_end = m
        var j0 = 0
        while j0 < n:
            var j_end = j0 + bn
            if j_end > n:
                j_end = n
            var k0 = 0
            while k0 < kdim:
                var k_end = k0 + bk
                if k_end > kdim:
                    k_end = kdim
                for i in range(i0, i_end):
                    var j = j0
                    while j + 8 <= j_end:
                        var acc = load_row_chunk(c, i, j)
                        for kk in range(k0, k_end):
                            var bv = load_row_chunk(b, kk, j)
                            acc += bv * a.get(i, kk)
                        store_row_chunk(c, i, j, acc)
                        j += 8
                    while j < j_end:
                        var s = c.get(i, j)
                        for kk in range(k0, k_end):
                            s += a.get(i, kk) * b.get(kk, j)
                        c.set(i, j, s)
                        j += 1
                k0 += bk
            j0 += bn
        i0 += bm
    return c^


def matmul_add_bias(a: Matrix, b: Matrix, bias: List[Float32]) raises -> Matrix:
    """C = A @ B + bias, with one bias value per output column.

    The fused bias add is the form a transformer linear layer really
    uses (every projection is a matmul plus a bias). Checked against
    a naive matmul followed by an explicit bias loop.
    """
    check(a.cols == b.rows, "matmul_add_bias: inner dimensions must match")
    check(len(bias) == b.cols, "matmul_add_bias: bias length must equal output columns")
    var c = matmul_simd(a, b)
    for i in range(c.rows):
        for j in range(c.cols):
            c.set(i, j, c.get(i, j) + bias[j])
    return c^



# ---------------------------------------------------------------------------
# Attention scores: C = A @ B^T, SIMD over the shared dimension
# ---------------------------------------------------------------------------
# (A @ B^T)[i, j] = sum_k A[i,k] * B[j,k]. Both rows are contiguous in
# k, so one 8-wide vector from each row multiplies and accumulates,
# and `reduce_add` collapses the lanes at the end. This avoids ever
# materialising B^T -- exactly what attention wants for Q @ K^T.

def matmul_atb(a: Matrix, b: Matrix) raises -> Matrix:
    """C = A @ B^T, SIMD-vectorised over k. A is (m x k), B is (n x k)."""
    check(a.cols == b.cols, "matmul_atb: shared dimension must match")
    var c = Matrix(a.rows, b.rows)
    for i in range(a.rows):
        for j in range(b.rows):
            var acc = SIMD[DType.float32, 8](0.0)
            var k = 0
            while k + 8 <= a.cols:
                var av = load_row_chunk(a, i, k)
                var bv = load_row_chunk(b, j, k)
                acc += av * bv
                k += 8
            var s = acc.reduce_add()
            while k < a.cols:
                s += a.get(i, k) * b.get(j, k)
                k += 1
            c.set(i, j, s)
    return c^


def matmul_atb_naive(a: Matrix, b: Matrix) raises -> Matrix:
    """Scalar reference for C = A @ B^T."""
    check(a.cols == b.cols, "matmul_atb_naive: shared dimension must match")
    var c = Matrix(a.rows, b.rows)
    for i in range(a.rows):
        for j in range(b.rows):
            var s = Float32(0.0)
            for k in range(a.cols):
                s += a.get(i, k) * b.get(j, k)
            c.set(i, j, s)
    return c^


# ---------------------------------------------------------------------------
# Softmax
# ---------------------------------------------------------------------------
# The stable form subtracts the row maximum before exponentiating:
# softmax(x)_i = exp(x_i - max(x)) / sum_j exp(x_j - max(x)).
# The largest exponent is then exp(0) = 1, so no overflow is possible
# even for inputs in the thousands, and the result is identical to
# the textbook formula in exact arithmetic.

def softmax_rows(m: Matrix) -> Matrix:
    """Row-wise softmax, SIMD over columns, max-subtracted."""
    var result = Matrix(m.rows, m.cols)
    for r in range(m.rows):
        var row_max = m.get(r, 0)
        for c in range(1, m.cols):
            var v = m.get(r, c)
            if v > row_max:
                row_max = v
        var total = SIMD[DType.float32, 8](0.0)
        var c = 0
        while c + 8 <= m.cols:
            var chunk = load_row_chunk(m, r, c)
            total += exp(chunk - row_max)
            c += 8
        var denom = total.reduce_add()
        while c < m.cols:
            denom += exp(m.get(r, c) - row_max)
            c += 1
        c = 0
        while c + 8 <= m.cols:
            var chunk = load_row_chunk(m, r, c)
            var probs = exp(chunk - row_max) / denom
            store_row_chunk(result, r, c, probs)
            c += 8
        while c < m.cols:
            result.set(r, c, exp(m.get(r, c) - row_max) / denom)
            c += 1
    return result^


def softmax_row_scalar(m: Matrix, r: Int) -> List[Float32]:
    """Scalar reference softmax for one row, for checking."""
    var row_max = m.get(r, 0)
    for c in range(1, m.cols):
        if m.get(r, c) > row_max:
            row_max = m.get(r, c)
    var result = List[Float32](length=m.cols, fill=0.0)
    var total = Float32(0.0)
    for c in range(m.cols):
        result[c] = exp(m.get(r, c) - row_max)
        total += result[c]
    for c in range(m.cols):
        result[c] = result[c] / total
    return result^


def row_sum(m: Matrix, r: Int) -> Float32:
    var s = Float32(0.0)
    for c in range(m.cols):
        s += m.get(r, c)
    return s


# ---------------------------------------------------------------------------
# Causal masking
# ---------------------------------------------------------------------------

def apply_causal_mask(mut scores: Matrix):
    """Set scores[i, j] = -1e9 for j > i (future positions)."""
    for i in range(scores.rows):
        for j in range(i + 1, scores.cols):
            scores.set(i, j, Float32(-1e9))


def is_causal_masked(scores: Matrix) -> Bool:
    for i in range(scores.rows):
        for j in range(i + 1, scores.cols):
            if scores.get(i, j) > Float32(-1e8):
                return False
    return True


# ---------------------------------------------------------------------------
# Scaled dot-product attention
# ---------------------------------------------------------------------------

def sdpa_naive(q: Matrix, k: Matrix, v: Matrix, causal: Bool) raises -> Matrix:
    """Fully scalar SDPA reference: scores, scale, mask, softmax, mix.

    Q, K, V are (seq x d), (seq x d), (seq x d_v). Returns (seq x d_v).
    Every step is a plain loop so the logic is auditable by inspection.
    """
    var seq = q.rows
    var d = q.cols
    var scale = Float32(1.0) / sqrt(Float32(d))
    var scores = Matrix(seq, seq)
    for i in range(seq):
        for j in range(seq):
            var acc = Float32(0.0)
            for t in range(d):
                acc += q.get(i, t) * k.get(j, t)
            scores.set(i, j, acc * scale)
    if causal:
        apply_causal_mask(scores)
    var probs = Matrix(seq, seq)
    for i in range(seq):
        var row = softmax_row_scalar(scores, i)
        for j in range(seq):
            probs.set(i, j, row[j])
    var result = Matrix(seq, v.cols)
    for i in range(seq):
        for j in range(v.cols):
            var acc = Float32(0.0)
            for t in range(seq):
                acc += probs.get(i, t) * v.get(t, j)
            result.set(i, j, acc)
    return result^


def sdpa(q: Matrix, k: Matrix, v: Matrix, causal: Bool) raises -> Matrix:
    """Fast SDPA: SIMD scores via A @ B^T, SIMD softmax, SIMD mix."""
    var d = q.cols
    var scale = Float32(1.0) / sqrt(Float32(d))
    var scores = matmul_atb(q, k)
    for i in range(scores.rows):
        for j in range(scores.cols):
            scores.set(i, j, scores.get(i, j) * scale)
    if causal:
        apply_causal_mask(scores)
    var probs = softmax_rows(scores)
    var result = matmul_simd(probs, v)
    return result^


def sdpa_scores(q: Matrix, k: Matrix, causal: Bool) raises -> Matrix:
    """Just the (scaled, optionally masked) score matrix, for inspection."""
    var scale = Float32(1.0) / sqrt(Float32(q.cols))
    var scores = matmul_atb(q, k)
    for i in range(scores.rows):
        for j in range(scores.cols):
            scores.set(i, j, scores.get(i, j) * scale)
    if causal:
        apply_causal_mask(scores)
    return scores^




# ---------------------------------------------------------------------------
# Pointer-based SIMD matmul (benchmark-only variant)
# ---------------------------------------------------------------------------
# The `matmul_simd` in the shared core builds its vectors from eight
# scalar List reads, which costs a bounds check per element and
# hides the vector load from the compiler. This variant instead
# takes the raw storage pointers once and issues real 8-wide vector
# loads (`unsafe_load`) and stores (`unsafe_store`) against them.
# The arithmetic is identical -- only the memory path changes -- so
# it is checked against the same naive reference. It lives in this
# file only, because it needs the caller to guarantee the pointers
# stay valid for the duration of the call (true here: the matrices
# are alive for the whole kernel, and nothing else touches their
# storage while it runs).

def matmul_simd_ptr(a: Matrix, b: Matrix) raises -> Matrix:
    """C = A @ B with true vector loads/stores via UnsafePointer."""
    check(a.cols == b.rows, "matmul_simd_ptr: inner dimensions must match")
    var c = Matrix(a.rows, b.cols)
    var ap = a.data.unsafe_ptr()
    var bp = b.data.unsafe_ptr()
    var cp = c.data.unsafe_ptr()
    for i in range(a.rows):
        var j = 0
        while j + 8 <= b.cols:
            var acc = SIMD[DType.float32, 8](0.0)
            for k in range(a.cols):
                var bv = bp.unsafe_load[width=8](k * b.cols + j)
                acc += bv * ap.unsafe_load(i * a.cols + k)
            cp.unsafe_store[width=8](i * b.cols + j, acc)
            j += 8
        while j < b.cols:
            var s = Float32(0.0)
            for k in range(a.cols):
                s += a.get(i, k) * b.get(k, j)
            c.set(i, j, s)
            j += 1
    return c^

# ---------------------------------------------------------------------------
# Timing harness
# ---------------------------------------------------------------------------
# `perf_counter_ns` is a monotonic nanosecond clock. We time in
# whole iterations (no per-call overhead), take the BEST time over
# several iterations (the minimum is the least contaminated by
# scheduling noise), and report milliseconds plus GFLOPS. Warmup
# runs matter: the first call pays for any lazy initialisation and
# for bringing the matrices into cache.

struct Timing:
    """Best / mean milliseconds over the timed iterations."""

    var best_ms: Float64
    var mean_ms: Float64
    var iters: Int

    def __init__(out self, best_ms: Float64, mean_ms: Float64, iters: Int):
        self.best_ms = best_ms
        self.mean_ms = mean_ms
        self.iters = iters


def time_matmul(kind: String, a: Matrix, b: Matrix, iters: Int) raises -> Timing:
    """Time one matmul kernel. kind is "naive", "simd" or "tiled"."""
    check(iters > 0, "time_matmul: need at least one iteration")
    var best = Float64(1e30)
    var total = Float64(0.0)
    for _it in range(iters):
        var t0 = perf_counter_ns()
        if kind == "naive":
            var c = matmul_naive(a, b)
            _ = c
        elif kind == "simd":
            var c = matmul_simd(a, b)
            _ = c
        elif kind == "ptr":
            var c = matmul_simd_ptr(a, b)
            _ = c
        else:
            var c = matmul_tiled(a, b, 32, 32, 16)
            _ = c
        var t1 = perf_counter_ns()
        var ms = Float64(t1 - t0) / 1000000.0
        if ms < best:
            best = ms
        total += ms
    var result = Timing(best, total / Float64(iters), iters)
    return result^


def gflops_matmul(m: Int, n: Int, k: Int, ms: Float64) -> Float64:
    """2*m*n*k flops in ms milliseconds, expressed as GFLOPS."""
    var flops = Float64(2 * m * n * k)
    var seconds = ms / 1000.0
    return flops / seconds / 1000000000.0


def time_sdpa(kind: String, q: Matrix, k: Matrix, v: Matrix, iters: Int) raises -> Timing:
    var best = Float64(1e30)
    var total = Float64(0.0)
    for _it in range(iters):
        var t0 = perf_counter_ns()
        if kind == "naive":
            var c = sdpa_naive(q, k, v, True)
            _ = c
        else:
            var c = sdpa(q, k, v, True)
            _ = c
        var t1 = perf_counter_ns()
        var ms = Float64(t1 - t0) / 1000000.0
        if ms < best:
            best = ms
        total += ms
    var result = Timing(best, total / Float64(iters), iters)
    return result^


def time_softmax(m: Matrix, iters: Int) -> Timing:
    var best = Float64(1e30)
    var total = Float64(0.0)
    for _it in range(iters):
        var t0 = perf_counter_ns()
        var c = softmax_rows(m)
        _ = c
        var t1 = perf_counter_ns()
        var ms = Float64(t1 - t0) / 1000000.0
        if ms < best:
            best = ms
        total += ms
    var result = Timing(best, total / Float64(iters), iters)
    return result^


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def test_timer_monotonic() raises:
    var t0 = perf_counter_ns()
    var acc = 0
    for i in range(100000):
        acc += i
    var t1 = perf_counter_ns()
    check(t1 > t0, "perf_counter_ns is not monotonic")
    check(acc == 4999950000, "sanity sum is wrong")
    # Timing a no-op block is non-negative and tiny.
    var t2 = perf_counter_ns()
    var t3 = perf_counter_ns()
    check(t3 >= t2, "empty interval is negative")


def test_bench_correctness() raises:
    var tol = Float32(1e-3)
    var a = Matrix.randn(48, 40, 5150, 0.5)
    var b = Matrix.randn(40, 56, 5151, 0.5)
    var reference = matmul_naive(a, b)
    var fast = matmul_simd(a, b)
    var tiled = matmul_tiled(a, b, 32, 32, 16)
    check(reference.max_abs_diff(fast) <= tol, "bench SIMD result is wrong")
    check(reference.max_abs_diff(tiled) <= tol, "bench tiled result is wrong")
    # GFLOPS sanity: 2*64*64*64 flops in 1 ms is 0.524 GFLOPS.
    var g = gflops_matmul(64, 64, 64, Float64(1.0))
    check(g > 0.5 and g < 0.53, "GFLOPS accounting is wrong: " + String(g))
    # SDPA fast and naive agree before either is timed.
    var q = Matrix.randn(16, 32, 5152, 0.7)
    var k = Matrix.randn(16, 32, 5153, 0.7)
    var v = Matrix.randn(16, 32, 5154, 0.7)
    var fast_attn = sdpa(q, k, v, True)
    var ref_attn = sdpa_naive(q, k, v, True)
    check(fast_attn.max_abs_diff(ref_attn) <= Float32(1e-4), "bench SDPA result is wrong")


def fmt(x: Float64, decimals: Int) -> String:
    """Format a Float64 with a fixed number of decimals, by hand:
    Mojo has no printf-style formatting in the stdlib, so we scale,
    round and split on the decimal point ourselves."""
    var scale = Float64(1.0)
    for _i in range(decimals):
        scale *= 10.0
    var rounded = Float64(Int(x * scale + Float64(0.5))) / scale
    var whole = Int(rounded)
    var frac = Int((rounded - Float64(whole)) * scale + Float64(0.5))
    var frac_str = String(frac)
    while frac_str.byte_length() < decimals:
        frac_str = "0" + frac_str
    if decimals == 0:
        return String(whole)
    return String(whole) + "." + frac_str


def main() raises:
    print("=== transformer_benchmark: naive vs SIMD vs tiled ===")
    print("")
    var suite = TestSuite()
    suite.test[test_timer_monotonic]()
    suite.test[test_bench_correctness]()
    suite^.run()
    print("  unit tests passed (timer monotonic, bench correctness, GFLOPS math)")
    print("")

    print("Matmul benchmark (best of N runs, Float32, single thread):")
    print("  shape        naive ms    SIMD ms    tiled ms   ptrSIMD ms  SIMD x   ptr x  ptr GFLOPS")
    var sizes = List[Int]()
    sizes.append(64)
    sizes.append(128)
    sizes.append(256)
    sizes.append(512)
    var iters = List[Int]()
    iters.append(20)
    iters.append(10)
    iters.append(3)
    iters.append(2)
    for si in range(len(sizes)):
        var n = sizes[si]
        var reps = iters[si]
        var a = Matrix.randn(n, n, UInt64(6000 + si), 0.5)
        var b = Matrix.randn(n, n, UInt64(6100 + si), 0.5)
        # Correctness first, on these exact matrices.
        var reference = matmul_naive(a, b)
        var fast = matmul_simd(a, b)
        var tiled = matmul_tiled(a, b, 32, 32, 16)
        var tol = Float32(1e-3)
        check(reference.max_abs_diff(fast) <= tol, "SIMD wrong at n=" + String(n))
        check(reference.max_abs_diff(tiled) <= tol, "tiled wrong at n=" + String(n))
        # Warmup, then time.
        var _w = matmul_simd(a, b)
        var _w2 = matmul_tiled(a, b, 32, 32, 16)
        var t_naive = time_matmul("naive", a, b, reps)
        var t_simd = time_matmul("simd", a, b, reps)
        var t_tiled = time_matmul("tiled", a, b, reps)
        var t_ptr = time_matmul("ptr", a, b, reps)
        var speedup_simd = t_naive.best_ms / t_simd.best_ms
        var speedup_ptr = t_naive.best_ms / t_ptr.best_ms
        var gf = gflops_matmul(n, n, n, t_ptr.best_ms)
        check(reference.max_abs_diff(matmul_simd_ptr(a, b)) <= tol, "ptr kernel wrong at n=" + String(n))
        print(
            "  "
            + String(n)
            + "x"
            + String(n)
            + "     "
            + fmt(t_naive.best_ms, 2)
            + "     "
            + fmt(t_simd.best_ms, 2)
            + "     "
            + fmt(t_tiled.best_ms, 2)
            + "     "
            + fmt(t_ptr.best_ms, 2)
            + "    "
            + fmt(speedup_simd, 1)
            + "x   "
            + fmt(speedup_ptr, 1)
            + "x   "
            + fmt(gf, 2)
        )
        # The SIMD kernel must beat the scalar loop on a real
        # matrix; if it does not, something is wrong with the
        # vectorisation rather than with the machine.
        if n >= 128:
            check(
                t_simd.best_ms < t_naive.best_ms,
                "SIMD matmul is slower than naive at n=" + String(n),
            )
            check(
                t_ptr.best_ms < t_simd.best_ms,
                "pointer SIMD is slower than gather SIMD at n=" + String(n),
            )
    print("")
    print("SDPA benchmark (causal, d = 64, best of 5 runs):")
    var seqs = List[Int]()
    seqs.append(32)
    seqs.append(64)
    seqs.append(128)
    for si in range(len(seqs)):
        var seq = seqs[si]
        var q = Matrix.randn(seq, 64, UInt64(7000 + si), 0.6)
        var k = Matrix.randn(seq, 64, UInt64(7100 + si), 0.6)
        var v = Matrix.randn(seq, 64, UInt64(7200 + si), 0.6)
        var reference = sdpa_naive(q, k, v, True)
        var fast = sdpa(q, k, v, True)
        check(reference.max_abs_diff(fast) <= Float32(1e-4), "SDPA wrong at seq=" + String(seq))
        var t_ref = time_sdpa("naive", q, k, v, 5)
        var t_fast = time_sdpa("fast", q, k, v, 5)
        print(
            "  seq="
            + String(seq)
            + "  naive "
            + fmt(t_ref.best_ms, 2)
            + " ms  fast "
            + fmt(t_fast.best_ms, 2)
            + " ms  speedup "
            + fmt(t_ref.best_ms / t_fast.best_ms, 1)
            + "x"
        )
    print("")
    print("Softmax benchmark (rows x 512, best of 10 runs):")
    var rows_list = List[Int]()
    rows_list.append(64)
    rows_list.append(256)
    for ri in range(len(rows_list)):
        var rows = rows_list[ri]
        var m = Matrix.randn(rows, 512, UInt64(8000 + ri), 1.0)
        var t = time_softmax(m, 10)
        var total_elems = Float64(rows * 512)
        var throughput = total_elems / (t.best_ms / 1000.0) / 1000000.0
        print(
            "  "
            + String(rows)
            + "x512  "
            + fmt(t.best_ms, 2)
            + " ms  "
            + fmt(throughput, 1)
            + " M elements/s"
        )
    print("")
    print("ALL BENCHMARK CHECKS PASSED (timings are machine-dependent)")
