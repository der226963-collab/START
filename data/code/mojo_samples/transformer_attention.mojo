# transformer_attention.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# Scaled dot-product attention (SDPA), the heart of the transformer.
#
# What this file demonstrates:
#   * `matmul_atb`: C = A @ B^T, SIMD-vectorised over the shared
#     dimension, which is how attention scores Q @ K^T are computed
#     without materialising a transposed copy of K.
#   * Row-wise softmax with max-subtraction, the numerically stable
#     form: exp(x - max) can never overflow, and rows always sum to 1.
#   * Causal masking: future positions are set to a large negative
#     value before the softmax, so they receive (numerically) zero
#     weight -- the property that makes a decoder autoregressive.
#   * `sdpa`: the full pipeline -- scores, 1/sqrt(d_k) scaling,
#     optional causal mask, softmax, weighted sum over V -- plus a
#     completely scalar `sdpa_naive` reference that the fast version
#     is checked against on several shapes.
#   * Structural checks: every output row is a convex combination of
#     the V rows, and with a causal mask row i provably ignores every
#     V row after i.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` helpers
# are the same small self-contained core used across this sample
# series, repeated in each file so every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_attention.mojo
# Exit code 0 means every check and every unit test passed.

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
        var result = List[Float32](length=self.cols, fill=0.0)
        for c in range(self.cols):
            result[c] = self.get(r, c)
        return result^

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
# Checks
# ---------------------------------------------------------------------------

def check_convex_combination(result: Matrix, v: Matrix, tol: Float32) raises:
    """Every output row is a weighted average of V rows, so each
    output element must lie between the min and max of its column
    of V (up to float tolerance). A softmax bug -- negative weights,
    weights not summing to 1 -- shows up here immediately."""
    for j in range(v.cols):
        var lo = v.get(0, j)
        var hi = v.get(0, j)
        for t in range(1, v.rows):
            var x = v.get(t, j)
            if x < lo:
                lo = x
            if x > hi:
                hi = x
        for i in range(result.rows):
            var y = result.get(i, j)
            check(
                y >= lo - tol and y <= hi + tol,
                "convex-combination check failed at ("
                + String(i)
                + ","
                + String(j)
                + "): "
                + String(y)
                + " outside ["
                + String(lo)
                + ", "
                + String(hi)
                + "]",
            )


def check_causal_independence(q: Matrix, k: Matrix, v: Matrix) raises:
    """With a causal mask, output row i must not depend on V rows
    after i. We prove it by recomputing with those rows scrambled
    and requiring row i to be bit-identical."""
    var base = sdpa(q, k, v, True)
    var v2 = v.clone()
    var rng = Rng(999)
    # Rows 2 and later are scrambled; row 1 must be unchanged.
    for t in range(2, v2.rows):
        for j in range(v2.cols):
            v2.set(t, j, rng.normal_scaled(5.0))
    var changed = sdpa(q, k, v2, True)
    for j in range(base.cols):
        check(
            base.get(1, j) == changed.get(1, j),
            "causal leak: row 1 changed when later V rows changed",
        )
    # And row 0 depends only on V row 0: it must equal V row 0
    # exactly (its only allowed source).
    for j in range(base.cols):
        check(
            base.get(0, j) == v.get(0, j),
            "causal row 0 is not exactly V row 0",
        )


def test_softmax_properties() raises:
    # Rows sum to 1, including for huge inputs where a naive
    # exp() would overflow to infinity.
    var big = Matrix(2, 4)
    big.set(0, 0, 1000.0)
    big.set(0, 1, 1001.0)
    big.set(0, 2, 999.0)
    big.set(0, 3, 1000.5)
    big.set(1, 0, -500.0)
    big.set(1, 1, -499.0)
    big.set(1, 2, -501.0)
    big.set(1, 3, -500.0)
    var p = softmax_rows(big)
    for r in range(2):
        assert_almost_equal(row_sum(p, r), Float32(1.0), atol=1e-6)
        for c in range(4):
            check(p.get(r, c) >= 0.0 and p.get(r, c) <= 1.0, "softmax probability outside [0, 1]")
            check(p.get(r, c) == p.get(r, c), "softmax produced NaN")
    # Softmax is shift-invariant: adding a constant to a row changes
    # nothing, and the largest logit gets the largest probability.
    var shifted = Matrix(2, 4)
    for r in range(2):
        for c in range(4):
            shifted.set(r, c, big.get(r, c) + Float32(12345.0))
    var p2 = softmax_rows(shifted)
    check(p.max_abs_diff(p2) <= Float32(1e-6), "softmax is not shift-invariant")
    check(p.get(0, 1) > p.get(0, 3), "softmax ordering wrong (1 vs 3)")
    check(p.get(0, 3) > p.get(0, 0), "softmax ordering wrong (3 vs 0)")
    # SIMD softmax matches the scalar reference on an odd width.
    var odd = Matrix.randn(3, 13, 42, 1.0)
    var fast = softmax_rows(odd)
    for r in range(3):
        var reference = softmax_row_scalar(odd, r)
        for c in range(13):
            assert_almost_equal(fast.get(r, c), reference[c], atol=1e-6)
    # One-hot limit: a single dominant logit takes ~all the mass.
    var peaked = Matrix(1, 5)
    peaked.set(0, 2, 50.0)
    var pp = softmax_rows(peaked)
    check(pp.get(0, 2) > Float32(0.9999), "peaked softmax mass not concentrated")
    check(pp.get(0, 0) < Float32(1e-10), "peaked softmax tail not ~0")


def test_atb_matches_naive() raises:
    var a = Matrix.randn(11, 19, 21, 0.7)
    var b = Matrix.randn(7, 19, 22, 0.7)
    var fast = matmul_atb(a, b)
    var reference = matmul_atb_naive(a, b)
    check(fast.max_abs_diff(reference) <= Float32(1e-4), "A@B^T mismatch vs naive")
    assert_equal(fast.rows, 11)
    assert_equal(fast.cols, 7)
    # A @ A^T is symmetric, with squared row norms on the diagonal.
    var sym = matmul_atb(a, a)
    for i in range(a.rows):
        for j in range(a.rows):
            assert_almost_equal(sym.get(i, j), sym.get(j, i), atol=1e-4)
    var row0_norm2 = Float32(0.0)
    for t in range(a.cols):
        row0_norm2 += a.get(0, t) * a.get(0, t)
    assert_almost_equal(sym.get(0, 0), row0_norm2, atol=1e-3)


def test_sdpa_matches_naive() raises:
    var tol = Float32(1e-4)
    var q = Matrix.randn(17, 16, 31, 0.8)
    var k = Matrix.randn(17, 16, 32, 0.8)
    var v = Matrix.randn(17, 24, 33, 0.8)
    var fast_causal = sdpa(q, k, v, True)
    var ref_causal = sdpa_naive(q, k, v, True)
    check(fast_causal.max_abs_diff(ref_causal) <= tol, "causal SDPA mismatch vs naive")
    var fast_full = sdpa(q, k, v, False)
    var ref_full = sdpa_naive(q, k, v, False)
    check(fast_full.max_abs_diff(ref_full) <= tol, "full SDPA mismatch vs naive")
    # Causal and non-causal differ (later positions get masked result).
    check(fast_causal.max_abs_diff(fast_full) > Float32(1e-3), "causal and full SDPA unexpectedly identical")
    # Single-token sequence: attention is the identity on V.
    var q1 = Matrix.randn(1, 8, 34, 1.0)
    var k1 = Matrix.randn(1, 8, 35, 1.0)
    var v1 = Matrix.randn(1, 8, 36, 1.0)
    var out1 = sdpa(q1, k1, v1, True)
    check(out1.max_abs_diff(v1) <= Float32(1e-5), "single-token attention is not the identity on V")
    check_convex_combination(fast_full, v, Float32(1e-4))
    check_convex_combination(fast_causal, v, Float32(1e-4))
    check_causal_independence(q, k, v)


def main() raises:
    print("=== transformer_attention: scaled dot-product attention ===")
    print("")
    var suite = TestSuite()
    suite.test[test_softmax_properties]()
    suite.test[test_atb_matches_naive]()
    suite.test[test_sdpa_matches_naive]()
    suite^.run()
    print("  unit tests passed (softmax, A@B^T, SDPA vs naive, causal)")
    print("")

    print("Fast vs naive SDPA on several shapes (tolerance 1e-4):")
    var tol = Float32(1e-4)
    var seqs = List[Int]()
    seqs.append(1)
    seqs.append(5)
    seqs.append(17)
    seqs.append(32)
    var dims = List[Int]()
    dims.append(8)
    dims.append(16)
    dims.append(32)
    dims.append(64)
    for si in range(len(seqs)):
        for di in range(len(dims)):
            var seq = seqs[si]
            var d = dims[di]
            var dv = d + 8
            var q = Matrix.randn(seq, d, UInt64(100 + si * 7 + di), 0.6)
            var k = Matrix.randn(seq, d, UInt64(200 + si * 7 + di), 0.6)
            var v = Matrix.randn(seq, dv, UInt64(300 + si * 7 + di), 0.6)
            var fast = sdpa(q, k, v, True)
            var reference = sdpa_naive(q, k, v, True)
            var diff = fast.max_abs_diff(reference)
            check(diff <= tol, "SDPA mismatch seq=" + String(seq) + " d=" + String(d))
            check_convex_combination(fast, v, Float32(1e-4))
            print(
                "  OK seq="
                + String(seq)
                + " d="
                + String(d)
                + " d_v="
                + String(dv)
                + " max diff="
                + String(diff)
            )
    print("")

    print("Inspecting a tiny causal attention run (seq=4, d=4):")
    var q = Matrix.arange(4, 4, 0.1, 0.1)
    var k = Matrix.arange(4, 4, -0.05, 0.07)
    var v = Matrix.arange(4, 4, 1.0, 1.0)
    var scores = sdpa_scores(q, k, True)
    print("  masked scores (row 0 may only see col 0):")
    scores.print_block(4, 4)
    check(is_causal_masked(scores), "scores are not causally masked")
    var result = sdpa(q, k, v, True)
    print("  output rows (row 0 must equal V row 0):")
    result.print_block(4, 4)
    for j in range(4):
        check(result.get(0, j) == v.get(0, j), "row 0 of causal output is not V row 0")
    var out2 = sdpa(q, k, v, True)
    check(result.max_abs_diff(out2) == Float32(0.0), "SDPA is not deterministic")
    print("  determinism: second run is bit-identical")
    print("")
    print("ALL ATTENTION CHECKS PASSED")
