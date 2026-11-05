# transformer_norms.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# RMSNorm and LayerNorm: the normalisation layers that keep a
# transformer's activations on a stable scale.
#
# What this file demonstrates:
#   * `rmsnorm_rows`: per-row RMS normalisation, x / sqrt(mean(x^2)
#     + eps) * weight, SIMD-vectorised over the row. This is the
#     normalisation used by modern decoder-only transformers
#     (LLaMA-style), and it is the only norm a pre-norm block needs.
#   * `layernorm_rows`: per-row mean/variance normalisation,
#     (x - mean) / sqrt(var + eps) * weight + bias, the classic
#     transformer normalisation, also SIMD-vectorised.
#   * A fully scalar reference for each norm, which the fast
#     versions are checked against on many shapes, including odd
#     row widths that stress the SIMD tail loop.
#   * The defining properties, checked directly:
#       - RMSNorm output rows have RMS exactly 1 (weight 1);
#       - LayerNorm output rows have mean 0 and variance 1;
#       - RMSNorm is invariant to positive rescaling of the input;
#       - LayerNorm is invariant to shifting the input;
#       - a zero row normalises to zero, and a row of 1e6-magnitude
#         values stays finite with RMS 1.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` /
# matmul core is the same self-contained core used across this
# sample series, repeated in each file so every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_norms.mojo
# Exit code 0 means every check and every unit test passed.

from std.math import sqrt, log, cos
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
# RMSNorm
# ---------------------------------------------------------------------------
# RMSNorm (Zhang & Sennrich, 2019) drops the mean-centering of
# LayerNorm and keeps only the scale: y_i = x_i / RMS(x) * w_i,
# with RMS(x) = sqrt(mean(x^2) + eps). It is cheaper (one reduction
# instead of two), has no bias term, and is invariant to multiplying
# the whole row by a positive constant -- which is why it pairs so
# well with residual streams whose scale drifts during training.

def rmsnorm_rows(x: Matrix, weight: List[Float32], eps: Float32) raises -> Matrix:
    """Per-row RMSNorm, SIMD over columns. weight has one entry per column."""
    check(len(weight) == x.cols, "rmsnorm_rows: weight length must equal columns")
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        var sq = SIMD[DType.float32, 8](0.0)
        var c = 0
        while c + 8 <= x.cols:
            var chunk = load_row_chunk(x, r, c)
            sq += chunk * chunk
            c += 8
        var total = sq.reduce_add()
        while c < x.cols:
            var v = x.get(r, c)
            total += v * v
            c += 1
        var inv = Float32(1.0) / sqrt(total / Float32(x.cols) + eps)
        c = 0
        while c + 8 <= x.cols:
            var chunk = load_row_chunk(x, r, c)
            var wchunk = SIMD[DType.float32, 8](
                weight[c], weight[c + 1], weight[c + 2], weight[c + 3],
                weight[c + 4], weight[c + 5], weight[c + 6], weight[c + 7],
            )
            store_row_chunk(result, r, c, chunk * inv * wchunk)
            c += 8
        while c < x.cols:
            result.set(r, c, x.get(r, c) * inv * weight[c])
            c += 1
    return result^


def rmsnorm_naive(x: Matrix, weight: List[Float32], eps: Float32) raises -> Matrix:
    """Scalar reference RMSNorm."""
    check(len(weight) == x.cols, "rmsnorm_naive: weight length must equal columns")
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        var total = Float32(0.0)
        for c in range(x.cols):
            var v = x.get(r, c)
            total += v * v
        var inv = Float32(1.0) / sqrt(total / Float32(x.cols) + eps)
        for c in range(x.cols):
            result.set(r, c, x.get(r, c) * inv * weight[c])
    return result^


def row_rms(m: Matrix, r: Int) -> Float32:
    var total = Float32(0.0)
    for c in range(m.cols):
        var v = m.get(r, c)
        total += v * v
    return sqrt(total / Float32(m.cols))


def ones_weight(cols: Int) -> List[Float32]:
    return List[Float32](length=cols, fill=1.0)


# ---------------------------------------------------------------------------
# LayerNorm
# ---------------------------------------------------------------------------
# LayerNorm (Ba et al., 2016) centres each row first, then scales:
# y_i = (x_i - mean(x)) / sqrt(var(x) + eps) * w_i + b_i, with the
# biased (population) variance. Two reductions are needed -- one for
# the mean, one for the variance -- so the fast version makes two
# SIMD passes and a third pass to write the normalised row.

def layernorm_rows(
    x: Matrix, weight: List[Float32], bias: List[Float32], eps: Float32
) raises -> Matrix:
    """Per-row LayerNorm, SIMD over columns."""
    check(len(weight) == x.cols, "layernorm_rows: weight length must equal columns")
    check(len(bias) == x.cols, "layernorm_rows: bias length must equal columns")
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        var sum_vec = SIMD[DType.float32, 8](0.0)
        var c = 0
        while c + 8 <= x.cols:
            sum_vec += load_row_chunk(x, r, c)
            c += 8
        var total = sum_vec.reduce_add()
        while c < x.cols:
            total += x.get(r, c)
            c += 1
        var mean = total / Float32(x.cols)
        var var_vec = SIMD[DType.float32, 8](0.0)
        c = 0
        while c + 8 <= x.cols:
            var chunk = load_row_chunk(x, r, c)
            var d = chunk - mean
            var_vec += d * d
            c += 8
        var var_total = var_vec.reduce_add()
        while c < x.cols:
            var d = x.get(r, c) - mean
            var_total += d * d
            c += 1
        var inv = Float32(1.0) / sqrt(var_total / Float32(x.cols) + eps)
        c = 0
        while c + 8 <= x.cols:
            var chunk = load_row_chunk(x, r, c)
            var wchunk = SIMD[DType.float32, 8](
                weight[c], weight[c + 1], weight[c + 2], weight[c + 3],
                weight[c + 4], weight[c + 5], weight[c + 6], weight[c + 7],
            )
            var bchunk = SIMD[DType.float32, 8](
                bias[c], bias[c + 1], bias[c + 2], bias[c + 3],
                bias[c + 4], bias[c + 5], bias[c + 6], bias[c + 7],
            )
            store_row_chunk(result, r, c, (chunk - mean) * inv * wchunk + bchunk)
            c += 8
        while c < x.cols:
            result.set(r, c, (x.get(r, c) - mean) * inv * weight[c] + bias[c])
            c += 1
    return result^


def layernorm_naive(
    x: Matrix, weight: List[Float32], bias: List[Float32], eps: Float32
) raises -> Matrix:
    """Scalar reference LayerNorm."""
    check(len(weight) == x.cols, "layernorm_naive: weight length must equal columns")
    check(len(bias) == x.cols, "layernorm_naive: bias length must equal columns")
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        var mean = Float32(0.0)
        for c in range(x.cols):
            mean += x.get(r, c)
        mean /= Float32(x.cols)
        var var_total = Float32(0.0)
        for c in range(x.cols):
            var d = x.get(r, c) - mean
            var_total += d * d
        var inv = Float32(1.0) / sqrt(var_total / Float32(x.cols) + eps)
        for c in range(x.cols):
            result.set(r, c, (x.get(r, c) - mean) * inv * weight[c] + bias[c])
    return result^


def row_mean(m: Matrix, r: Int) -> Float32:
    var s = Float32(0.0)
    for c in range(m.cols):
        s += m.get(r, c)
    return s / Float32(m.cols)


def row_var(m: Matrix, r: Int) -> Float32:
    var mean = row_mean(m, r)
    var s = Float32(0.0)
    for c in range(m.cols):
        var d = m.get(r, c) - mean
        s += d * d
    return s / Float32(m.cols)


def all_finite(m: Matrix) -> Bool:
    for i in range(len(m.data)):
        var v = m.data[i]
        if v != v:
            return False
        if v > Float32(3.4028235e38) or v < Float32(-3.4028235e38):
            return False
    return True


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def test_rmsnorm_properties() raises:
    var eps = Float32(1e-6)
    var w = ones_weight(16)
    # With unit weights, every output row has RMS exactly 1.
    var x = Matrix.randn(5, 16, 301, 2.0)
    var y = rmsnorm_rows(x, w, eps)
    for r in range(5):
        assert_almost_equal(row_rms(y, r), Float32(1.0), atol=1e-5)
    # Scale invariance: rmsnorm(3x) == rmsnorm(x) for positive 3.
    var x3 = Matrix(5, 16)
    for i in range(len(x.data)):
        x3.data[i] = x.data[i] * Float32(3.0)
    var y3 = rmsnorm_rows(x3, w, eps)
    check(y.max_abs_diff(y3) <= Float32(1e-5), "RMSNorm is not scale-invariant")
    # A zero row normalises to zero (eps guards the division).
    var z = Matrix.zeros(2, 16)
    var yz = rmsnorm_rows(z, w, eps)
    check(yz.max_abs() == Float32(0.0), "RMSNorm of a zero row is not zero")
    # Huge magnitudes stay finite and still have RMS 1.
    var big = Matrix.randn(3, 16, 302, 1.0)
    for i in range(len(big.data)):
        big.data[i] = big.data[i] * Float32(1e6)
    var ybig = rmsnorm_rows(big, w, eps)
    check(all_finite(ybig), "RMSNorm of huge inputs is not finite")
    for r in range(3):
        assert_almost_equal(row_rms(ybig, r), Float32(1.0), atol=1e-4)
    # Weights scale the output: with weight 2 the RMS doubles.
    var w2 = List[Float32](length=16, fill=2.0)
    var y2 = rmsnorm_rows(x, w2, eps)
    for r in range(5):
        assert_almost_equal(row_rms(y2, r), Float32(2.0), atol=1e-5)
    # Negative rescaling flips the sign but keeps the magnitude.
    var xn = Matrix(5, 16)
    for i in range(len(x.data)):
        xn.data[i] = -x.data[i] * Float32(2.0)
    var yn = rmsnorm_rows(xn, w, eps)
    var yneg = Matrix(5, 16)
    for i in range(len(y.data)):
        yneg.data[i] = -y.data[i]
    check(yn.max_abs_diff(yneg) <= Float32(1e-5), "RMSNorm sign behaviour wrong")


def test_layernorm_properties() raises:
    var eps = Float32(1e-6)
    var w = ones_weight(24)
    var b = List[Float32](length=24, fill=0.0)
    var x = Matrix.randn(4, 24, 303, 3.0)
    var y = layernorm_rows(x, w, b, eps)
    # With unit weights and zero bias, each output row has mean 0
    # and variance 1.
    for r in range(4):
        assert_almost_equal(row_mean(y, r), Float32(0.0), atol=1e-5)
        assert_almost_equal(row_var(y, r), Float32(1.0), atol=1e-5)
    # Shift invariance: layernorm(x + 7) == layernorm(x).
    var xs = Matrix(4, 24)
    for i in range(len(x.data)):
        xs.data[i] = x.data[i] + Float32(7.0)
    var ys = layernorm_rows(xs, w, b, eps)
    check(y.max_abs_diff(ys) <= Float32(1e-5), "LayerNorm is not shift-invariant")
    # Scale invariance also holds (mean and var both rescale).
    var x2 = Matrix(4, 24)
    for i in range(len(x.data)):
        x2.data[i] = x.data[i] * Float32(0.25)
    var y2 = layernorm_rows(x2, w, b, eps)
    check(y.max_abs_diff(y2) <= Float32(1e-5), "LayerNorm is not scale-invariant")
    # A constant row has zero variance: the output is just the bias.
    var c = Matrix(2, 24)
    c.fill(5.0)
    var yc = layernorm_rows(c, w, b, eps)
    check(yc.max_abs() <= Float32(1e-4), "LayerNorm of a constant row is not ~0")
    # Bias shifts the output by exactly the bias.
    var b2 = List[Float32](length=24, fill=0.0)
    for i in range(24):
        b2[i] = Float32(i) * Float32(0.1)
    var yb = layernorm_rows(x, w, b2, eps)
    for r in range(4):
        for cc in range(24):
            check(
                yb.get(r, cc) == y.get(r, cc) + b2[cc],
                "LayerNorm bias did not shift the output exactly",
            )


def test_norms_match_naive() raises:
    var tol = Float32(1e-5)
    var widths = List[Int]()
    widths.append(1)
    widths.append(7)
    widths.append(8)
    widths.append(13)
    widths.append(31)
    widths.append(33)
    widths.append(64)
    for wi in range(len(widths)):
        var cols = widths[wi]
        var x = Matrix.randn(6, cols, UInt64(400 + wi), 1.5)
        var w = List[Float32](length=cols, fill=0.0)
        var b = List[Float32](length=cols, fill=0.0)
        var rng = Rng(UInt64(500 + wi))
        for i in range(cols):
            w[i] = rng.uniform_range(Float32(0.5), Float32(1.5))
            b[i] = rng.uniform_range(Float32(-1.0), Float32(1.0))
        var fast_rms = rmsnorm_rows(x, w, Float32(1e-6))
        var ref_rms = rmsnorm_naive(x, w, Float32(1e-6))
        check(fast_rms.max_abs_diff(ref_rms) <= tol,
              "RMSNorm mismatch at width " + String(cols))
        var fast_ln = layernorm_rows(x, w, b, Float32(1e-6))
        var ref_ln = layernorm_naive(x, w, b, Float32(1e-6))
        check(fast_ln.max_abs_diff(ref_ln) <= tol,
              "LayerNorm mismatch at width " + String(cols))


def main() raises:
    print("=== transformer_norms: RMSNorm and LayerNorm ===")
    print("")
    var suite = TestSuite()
    suite.test[test_rmsnorm_properties]()
    suite.test[test_layernorm_properties]()
    suite.test[test_norms_match_naive]()
    suite^.run()
    print("  unit tests passed (RMSNorm/LayerNorm properties, fast vs naive)")
    print("")

    print("Inspecting one small run (rows of 8):")
    var x = Matrix(3, 8)
    var vals = List[Float32]()
    vals.append(1.0)
    vals.append(2.0)
    vals.append(3.0)
    vals.append(4.0)
    vals.append(-1.0)
    vals.append(-2.0)
    vals.append(0.5)
    vals.append(-0.5)
    for r in range(3):
        for c in range(8):
            x.set(r, c, vals[c] * Float32(r + 1))
    print("  input:")
    x.print_block(3, 8)
    var w = ones_weight(8)
    var y_rms = rmsnorm_rows(x, w, Float32(1e-6))
    print("  RMSNorm output (each row RMS = 1):")
    y_rms.print_block(3, 8)
    for r in range(3):
        print("    row " + String(r) + " RMS = " + String(row_rms(y_rms, r)))
    var b = List[Float32](length=8, fill=0.0)
    var y_ln = layernorm_rows(x, w, b, Float32(1e-6))
    print("  LayerNorm output (each row mean = 0, var = 1):")
    y_ln.print_block(3, 8)
    for r in range(3):
        print(
            "    row "
            + String(r)
            + " mean = "
            + String(row_mean(y_ln, r))
            + " var = "
            + String(row_var(y_ln, r))
        )
    var y_rms2 = rmsnorm_rows(x, w, Float32(1e-6))
    check(y_rms.max_abs_diff(y_rms2) == Float32(0.0), "RMSNorm is not deterministic")
    print("  determinism: second RMSNorm run is bit-identical")
    print("")
    print("ALL NORM CHECKS PASSED")
