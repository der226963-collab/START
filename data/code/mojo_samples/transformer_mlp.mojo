# transformer_mlp.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# Feed-forward blocks: GELU MLP and SwiGLU, the two halves of a
# transformer block that do the per-position computation.
#
# What this file demonstrates:
#   * Activation functions, each with a scalar reference and a
#     checked fast path:
#       - GELU (exact, via erf, and the tanh approximation);
#       - SiLU / Swish, x * sigmoid(x), SIMD-vectorised;
#       - ReLU, as the simple baseline everything is compared to.
#   * `swiglu`: the gated feed-forward block of modern decoders,
#     hidden = SiLU(x @ W_gate) * (x @ W_up), out = hidden @ W_down.
#     The gate lets the network shut off (or amplify) each hidden
#     unit depending on the input -- the key difference from a
#     plain two-layer MLP.
#   * `mlp_gelu`: the classic two-layer GELU block, hidden = 4x
#     wider than the model by default.
#   * A fully scalar reference for each block, checked against the
#     SIMD-matmul fast path on several shapes, plus the defining
#     properties: GELU(0) = 0, GELU(x) -> x for large x, the exact
#     and tanh GELU agree to 5e-3, and a closed gate (SiLU -> 0)
#     makes the SwiGLU output exactly the down-projection bias.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` /
# matmul core is the same self-contained core used across this
# sample series, repeated in each file so every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_mlp.mojo
# Exit code 0 means every check and every unit test passed.

from std.math import sqrt, log, cos, exp, tanh, erf
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
# Activation functions
# ---------------------------------------------------------------------------
# GELU (Hendrycks & Gimpel, 2016) is x * Phi(x), the input weighted
# by the probability that a standard normal is below it: near zero
# it behaves like a smooth ReLU, for large |x| it is the identity
# (positive side) or zero (negative side). The exact form needs erf;
# the tanh form is a close, cheap approximation used in early GPTs.
# SiLU (also called Swish) is x * sigmoid(x): smooth, non-monotonic
# near zero, and the activation inside SwiGLU.

def sigmoid_scalar(x: Float32) -> Float32:
    return Float32(1.0) / (Float32(1.0) + exp(-x))


def silu_scalar(x: Float32) -> Float32:
    return x * sigmoid_scalar(x)


def gelu_exact_scalar(x: Float32) -> Float32:
    return Float32(0.5) * x * (Float32(1.0) + erf(x / sqrt(Float32(2.0))))


def gelu_tanh_scalar(x: Float32) -> Float32:
    var inner = sqrt(Float32(2.0 / 3.141592653589793)) * (
        x + Float32(0.044715) * x * x * x
    )
    return Float32(0.5) * x * (Float32(1.0) + tanh(inner))


def relu_scalar(x: Float32) -> Float32:
    if x > 0.0:
        return x
    return Float32(0.0)


def silu_matrix(x: Matrix) -> Matrix:
    """SiLU applied elementwise, SIMD over each row (exp is vectorised)."""
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        var c = 0
        while c + 8 <= x.cols:
            var chunk = load_row_chunk(x, r, c)
            var sig = Float32(1.0) / (Float32(1.0) + exp(-chunk))
            store_row_chunk(result, r, c, chunk * sig)
            c += 8
        while c < x.cols:
            result.set(r, c, silu_scalar(x.get(r, c)))
            c += 1
    return result^


def silu_matrix_scalar(x: Matrix) -> Matrix:
    """Scalar reference SiLU."""
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        for c in range(x.cols):
            result.set(r, c, silu_scalar(x.get(r, c)))
    return result^


def gelu_matrix(x: Matrix, exact: Bool) -> Matrix:
    """GELU applied elementwise (exact erf form, or tanh approx)."""
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        for c in range(x.cols):
            var v = x.get(r, c)
            if exact:
                result.set(r, c, gelu_exact_scalar(v))
            else:
                result.set(r, c, gelu_tanh_scalar(v))
    return result^


def relu_matrix(x: Matrix) -> Matrix:
    var result = Matrix(x.rows, x.cols)
    for r in range(x.rows):
        for c in range(x.cols):
            result.set(r, c, relu_scalar(x.get(r, c)))
    return result^


# ---------------------------------------------------------------------------
# Feed-forward blocks
# ---------------------------------------------------------------------------

def zero_bias(cols: Int) -> List[Float32]:
    return List[Float32](length=cols, fill=0.0)


struct MLPWeights:
    """Weights for both block styles in one struct.

    SwiGLU: W_gate, W_up are (d_model x d_ff), W_down is (d_ff x d_model).
    GELU MLP: W1 is (d_model x d_ff), W2 is (d_ff x d_model).
    """

    var d_model: Int
    var d_ff: Int
    var w_gate: Matrix
    var w_up: Matrix
    var w_down: Matrix
    var w1: Matrix
    var w2: Matrix
    var b_gate: List[Float32]
    var b_up: List[Float32]
    var b_down: List[Float32]
    var b1: List[Float32]
    var b2: List[Float32]

    def __init__(out self, d_model: Int, d_ff: Int, seed: UInt64) raises:
        self.d_model = d_model
        self.d_ff = d_ff
        var scale_in = Float32(1.0) / sqrt(Float32(d_model))
        var scale_hid = Float32(1.0) / sqrt(Float32(d_ff))
        self.w_gate = Matrix.randn(d_model, d_ff, seed, scale_in)
        self.w_up = Matrix.randn(d_model, d_ff, seed + 1, scale_in)
        self.w_down = Matrix.randn(d_ff, d_model, seed + 2, scale_hid)
        self.w1 = Matrix.randn(d_model, d_ff, seed + 3, scale_in)
        self.w2 = Matrix.randn(d_ff, d_model, seed + 4, scale_hid)
        self.b_gate = zero_bias(d_ff)
        self.b_up = zero_bias(d_ff)
        self.b_down = zero_bias(d_model)
        self.b1 = zero_bias(d_ff)
        self.b2 = zero_bias(d_model)


def swiglu(x: Matrix, w: MLPWeights) raises -> Matrix:
    """Fast SwiGLU: SiLU(x @ W_gate) * (x @ W_up), then @ W_down."""
    var gate = matmul_add_bias(x, w.w_gate, w.b_gate)
    var activated = silu_matrix(gate)
    var up = matmul_add_bias(x, w.w_up, w.b_up)
    var hidden = Matrix(activated.rows, activated.cols)
    for r in range(hidden.rows):
        var c = 0
        while c + 8 <= hidden.cols:
            var g = load_row_chunk(activated, r, c)
            var u = load_row_chunk(up, r, c)
            store_row_chunk(hidden, r, c, g * u)
            c += 8
        while c < hidden.cols:
            hidden.set(r, c, activated.get(r, c) * up.get(r, c))
            c += 1
    var result = matmul_add_bias(hidden, w.w_down, w.b_down)
    return result^


def swiglu_naive(x: Matrix, w: MLPWeights) raises -> Matrix:
    """Scalar reference SwiGLU (naive matmuls, scalar SiLU)."""
    var gate = matmul_naive(x, w.w_gate)
    for i in range(gate.rows):
        for j in range(gate.cols):
            gate.set(i, j, gate.get(i, j) + w.b_gate[j])
    var activated = silu_matrix_scalar(gate)
    var up = matmul_naive(x, w.w_up)
    for i in range(up.rows):
        for j in range(up.cols):
            up.set(i, j, up.get(i, j) + w.b_up[j])
    var hidden = Matrix(activated.rows, activated.cols)
    for i in range(hidden.rows):
        for j in range(hidden.cols):
            hidden.set(i, j, activated.get(i, j) * up.get(i, j))
    var result = matmul_naive(hidden, w.w_down)
    for i in range(result.rows):
        for j in range(result.cols):
            result.set(i, j, result.get(i, j) + w.b_down[j])
    return result^


def mlp_gelu(x: Matrix, w: MLPWeights, exact: Bool) raises -> Matrix:
    """Fast GELU MLP: GELU(x @ W1 + b1) @ W2 + b2."""
    var hidden_pre = matmul_add_bias(x, w.w1, w.b1)
    var hidden = gelu_matrix(hidden_pre, exact)
    var result = matmul_add_bias(hidden, w.w2, w.b2)
    return result^


def mlp_gelu_naive(x: Matrix, w: MLPWeights, exact: Bool) raises -> Matrix:
    """Scalar reference GELU MLP."""
    var hidden_pre = matmul_naive(x, w.w1)
    for i in range(hidden_pre.rows):
        for j in range(hidden_pre.cols):
            hidden_pre.set(i, j, hidden_pre.get(i, j) + w.b1[j])
    var hidden = gelu_matrix(hidden_pre, exact)
    var result = matmul_naive(hidden, w.w2)
    for i in range(result.rows):
        for j in range(result.cols):
            result.set(i, j, result.get(i, j) + w.b2[j])
    return result^


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

def test_activation_values() raises:
    # Known values, checked against the definitions:
    #   GELU(0) = 0, GELU(1) = 0.84119199, GELU(-1) = -0.15880801,
    #   SiLU(0) = 0, SiLU(1) = 0.73105858, sigmoid(0) = 0.5.
    assert_almost_equal(gelu_exact_scalar(0.0), Float32(0.0), atol=1e-7)
    assert_almost_equal(gelu_exact_scalar(1.0), Float32(0.84119199), atol=1e-3)
    assert_almost_equal(gelu_exact_scalar(-1.0), Float32(-0.15880801), atol=1e-3)
    assert_almost_equal(gelu_exact_scalar(5.0), Float32(5.0), atol=1e-4)
    check(gelu_exact_scalar(-5.0) > Float32(-1e-5) and gelu_exact_scalar(-5.0) < Float32(0.0),
          "GELU(-5) is not ~0")
    assert_almost_equal(silu_scalar(0.0), Float32(0.0), atol=1e-7)
    assert_almost_equal(silu_scalar(1.0), Float32(0.73105858), atol=1e-6)
    assert_almost_equal(silu_scalar(-1.0), Float32(-0.26894142), atol=1e-6)
    assert_almost_equal(sigmoid_scalar(0.0), Float32(0.5), atol=1e-7)
    check(relu_scalar(-3.0) == Float32(0.0), "ReLU(-3) is not 0")
    check(relu_scalar(2.5) == Float32(2.5), "ReLU(2.5) is not 2.5")
    # Exact and tanh GELU agree closely everywhere in [-5, 5].
    var worst = Float32(0.0)
    var v = Float32(-5.0)
    while v <= Float32(5.0):
        var d = gelu_exact_scalar(v) - gelu_tanh_scalar(v)
        if d < 0.0:
            d = -d
        if d > worst:
            worst = d
        v += Float32(0.05)
    check(worst <= Float32(5e-3),
          "exact vs tanh GELU differ by more than 5e-3: " + String(worst))
    print("  exact-vs-tanh GELU worst diff on [-5, 5]: " + String(worst))
    # GELU identity: GELU(-x) = GELU(x) - x.
    var xs = List[Float32]()
    xs.append(0.3)
    xs.append(1.7)
    xs.append(3.1)
    for i in range(len(xs)):
        var a = xs[i]
        assert_almost_equal(gelu_exact_scalar(-a), gelu_exact_scalar(a) - a, atol=1e-4)


def test_silu_simd() raises:
    var x = Matrix.randn(7, 37, 901, 1.5)
    var fast = silu_matrix(x)
    var reference = silu_matrix_scalar(x)
    check(fast.max_abs_diff(reference) <= Float32(1e-6), "SIMD SiLU mismatch vs scalar")
    # SiLU(x) -> x for large positive x, -> 0 for large negative x.
    var edge = Matrix(1, 4)
    edge.set(0, 0, 20.0)
    edge.set(0, 1, -20.0)
    edge.set(0, 2, 0.0)
    edge.set(0, 3, 1.0)
    var e = silu_matrix(edge)
    assert_almost_equal(e.get(0, 0), Float32(20.0), atol=1e-5)
    check(e.get(0, 1) > Float32(-1e-7) and e.get(0, 1) < Float32(0.0),
          "SiLU(-20) is not ~0")
    assert_almost_equal(e.get(0, 2), Float32(0.0), atol=1e-7)
    assert_almost_equal(e.get(0, 3), Float32(0.73105858), atol=1e-6)


def test_swiglu_matches_naive() raises:
    var tol = Float32(1e-4)
    var w = MLPWeights(24, 64, 1001)
    var x = Matrix.randn(11, 24, 1002, 0.8)
    var fast = swiglu(x, w)
    var reference = swiglu_naive(x, w)
    check(fast.max_abs_diff(reference) <= tol, "SwiGLU fast vs naive mismatch")
    check(all_finite(fast), "SwiGLU output is not finite")
    # A closed gate makes the output exactly the down bias: set the
    # gate weights to zero and the gate bias to a large negative
    # value, so SiLU(gate) is ~0 and the hidden layer vanishes.
    var w_closed = MLPWeights(24, 64, 1003)
    w_closed.w_gate.fill(0.0)
    for i in range(len(w_closed.b_gate)):
        w_closed.b_gate[i] = Float32(-30.0)
    var closed = swiglu(x, w_closed)
    for r in range(closed.rows):
        for c in range(closed.cols):
            check(
                closed.get(r, c) > w_closed.b_down[c] - Float32(1e-4)
                and closed.get(r, c) < w_closed.b_down[c] + Float32(1e-4),
                "closed-gate SwiGLU is not the down bias",
            )


def test_mlp_gelu_matches_naive() raises:
    var tol = Float32(1e-4)
    var w = MLPWeights(16, 64, 1101)
    var x = Matrix.randn(9, 16, 1102, 0.8)
    var fast_exact = mlp_gelu(x, w, True)
    var ref_exact = mlp_gelu_naive(x, w, True)
    check(fast_exact.max_abs_diff(ref_exact) <= tol, "GELU MLP (exact) fast vs naive mismatch")
    var fast_tanh = mlp_gelu(x, w, False)
    var ref_tanh = mlp_gelu_naive(x, w, False)
    check(fast_tanh.max_abs_diff(ref_tanh) <= tol, "GELU MLP (tanh) fast vs naive mismatch")
    check(all_finite(fast_exact) and all_finite(fast_tanh), "GELU MLP output is not finite")
    # ReLU MLP differs from GELU MLP (sanity: the activation matters).
    var hidden_pre = matmul_add_bias(x, w.w1, w.b1)
    var relu_hidden = relu_matrix(hidden_pre)
    var relu_out = matmul_add_bias(relu_hidden, w.w2, w.b2)
    check(fast_exact.max_abs_diff(relu_out) > Float32(1e-3),
          "GELU and ReLU MLPs unexpectedly agree")


def main() raises:
    print("=== transformer_mlp: GELU MLP and SwiGLU ===")
    print("")
    var suite = TestSuite()
    suite.test[test_activation_values]()
    suite.test[test_silu_simd]()
    suite.test[test_swiglu_matches_naive]()
    suite.test[test_mlp_gelu_matches_naive]()
    suite^.run()
    print("  unit tests passed (activations, SiLU SIMD, SwiGLU, GELU MLP)")
    print("")

    print("Fast vs naive feed-forward on several shapes (tolerance 1e-4):")
    var tol = Float32(1e-4)
    var seqs = List[Int]()
    seqs.append(1)
    seqs.append(8)
    seqs.append(17)
    var models = List[Int]()
    models.append(16)
    models.append(32)
    var mults = List[Int]()
    mults.append(2)
    mults.append(4)
    for si in range(len(seqs)):
        for mi in range(len(models)):
            for ui in range(len(mults)):
                var seq = seqs[si]
                var d_model = models[mi]
                var d_ff = d_model * mults[ui]
                var w = MLPWeights(d_model, d_ff, UInt64(2000 + si * 31 + mi * 7 + ui))
                var x = Matrix.randn(seq, d_model, UInt64(3000 + si * 31 + mi * 7 + ui), 0.7)
                var fast_sw = swiglu(x, w)
                var ref_sw = swiglu_naive(x, w)
                var d_sw = fast_sw.max_abs_diff(ref_sw)
                check(d_sw <= tol, "SwiGLU mismatch")
                var fast_gl = mlp_gelu(x, w, True)
                var ref_gl = mlp_gelu_naive(x, w, True)
                var d_gl = fast_gl.max_abs_diff(ref_gl)
                check(d_gl <= tol, "GELU MLP mismatch")
                print(
                    "  OK seq="
                    + String(seq)
                    + " d_model="
                    + String(d_model)
                    + " d_ff="
                    + String(d_ff)
                    + " swiglu diff="
                    + String(d_sw)
                    + " gelu diff="
                    + String(d_gl)
                )
    print("")

    print("Inspecting one small SwiGLU run (seq=2, d_model=8, d_ff=16):")
    var w = MLPWeights(8, 16, 4242)
    var x = Matrix.arange(2, 8, 0.1, 0.1)
    var result = swiglu(x, w)
    print("  input:")
    x.print_block(2, 8)
    print("  SwiGLU output:")
    result.print_block(2, 8)
    var result2 = swiglu(x, w)
    check(result.max_abs_diff(result2) == Float32(0.0), "SwiGLU is not deterministic")
    var gelu_result = mlp_gelu(x, w, True)
    print("  GELU MLP output (same weights, different block):")
    gelu_result.print_block(2, 8)
    print("  determinism: second SwiGLU run is bit-identical")
    print("")
    print("ALL MLP CHECKS PASSED")
