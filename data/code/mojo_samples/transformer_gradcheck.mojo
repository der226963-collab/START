# transformer_gradcheck.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# Gradient checking: analytic backpropagation verified against
# finite differences, the standard way to prove a backward pass is
# correct before trusting it to train anything.
#
# What this file demonstrates:
#   * `linear_forward` / `linear_backward`: y = x @ W + b and its
#     three gradients, dX = dY @ W^T, dW = X^T @ dY, db = column
#     sums of dY -- the backward pass every transformer projection
#     needs, built from the verified matmul kernels.
#   * `softmax_cross_entropy` and its gradient: loss = -log p[target]
#     with a max-subtracted softmax, and dlogits = p - one_hot(target),
#     the gradient that starts every classifier's backward pass.
#   * `mlp_backward`: a full two-layer SiLU MLP backward pass,
#     including the SiLU derivative, sigmoid(z) * (1 + z * (1 -
#     sigmoid(z))), chained through both layers.
#   * Finite-difference gradient checks (central differences) for
#     every parameter of the linear layer, the loss, and the MLP,
#     plus the property that one SGD step on the tiny MLP actually
#     reduces the loss -- the minimal end-to-end proof that the
#     gradients point downhill.
#
# Why finite differences: an analytic gradient can be wrong in
# ways that still produce finite, plausible-looking numbers. The
# central difference (f(w+e) - f(w-e)) / 2e uses only the forward
# pass, so agreement between the two independent computations (to
# ~1e-3 in Float32) is strong evidence the backward pass is right.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` /
# matmul core is the same self-contained core used across this
# sample series, repeated in each file so every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_gradcheck.mojo
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
# Linear layer forward and backward
# ---------------------------------------------------------------------------
# Forward: Y = X @ W + b, with X (n x in), W (in x out), b (out).
# Backward, given upstream dY (n x out):
#   dX = dY @ W^T          (n x in)    -- via matmul_atb
#   dW = X^T @ dY          (in x out)  -- transpose, then matmul
#   db = sum over rows of dY           (out)
# Each of these is a shape fact as much as a calculus fact: the
# gradient of a matrix has the matrix's own shape, which the checks
# below verify first.

def linear_forward(x: Matrix, w: Matrix, b: List[Float32]) raises -> Matrix:
    return matmul_add_bias(x, w, b)


def column_sums(m: Matrix) -> List[Float32]:
    var result = List[Float32](length=m.cols, fill=0.0)
    for r in range(m.rows):
        for c in range(m.cols):
            result[c] += m.get(r, c)
    return result^


struct LinearGrads:
    var dx: Matrix
    var dw: Matrix
    var db: List[Float32]

    def __init__(out self, dx: Matrix, dw: Matrix, db: List[Float32]):
        self.dx = dx.clone()
        self.dw = dw.clone()
        self.db = db.copy()


def linear_backward(x: Matrix, w: Matrix, dy: Matrix) raises -> LinearGrads:
    var dx = matmul_atb(dy, w)
    var xt = x.transpose()
    var dw = matmul_simd(xt, dy)
    var db = column_sums(dy)
    var grads = LinearGrads(dx^, dw^, db^)
    return grads^


# ---------------------------------------------------------------------------
# Softmax cross-entropy loss and gradient
# ---------------------------------------------------------------------------

def softmax_cross_entropy(logits: Matrix, row: Int, target: Int) raises -> Float32:
    """-log p[target] for one row, with a max-subtracted softmax."""
    check(row >= 0 and row < logits.rows, "softmax_cross_entropy: row out of range")
    check(target >= 0 and target < logits.cols, "softmax_cross_entropy: target out of range")
    var row_max = logits.get(row, 0)
    for c in range(1, logits.cols):
        if logits.get(row, c) > row_max:
            row_max = logits.get(row, c)
    var total = Float32(0.0)
    for c in range(logits.cols):
        total += exp(logits.get(row, c) - row_max)
    var log_prob = (logits.get(row, target) - row_max) - log(total)
    return -log_prob


def sce_grad(logits: Matrix, row: Int, target: Int) raises -> Matrix:
    """Gradient of the loss wrt the logits for one row: softmax - one_hot(target).

    This is a (1 x vocab) matrix, zero everywhere except the
    softmax probabilities, with -1 added at the target: the gradient
    pushes the target logit up and every other logit down, in
    proportion to how much probability each currently holds.
    """
    var probs = softmax_row_scalar(logits, row)
    var grad = Matrix(1, logits.cols)
    for c in range(logits.cols):
        var g = probs[c]
        if c == target:
            g -= Float32(1.0)
        grad.set(0, c, g)
    return grad^


# ---------------------------------------------------------------------------
# Two-layer SiLU MLP forward and backward
# ---------------------------------------------------------------------------

def silu_scalar(x: Float32) -> Float32:
    var s = Float32(1.0) / (Float32(1.0) + exp(-x))
    return x * s


def silu_deriv_scalar(x: Float32) -> Float32:
    """Derivative of SiLU(x): sigmoid(x) * (1 + x * (1 - sigmoid(x)))."""
    var s = Float32(1.0) / (Float32(1.0) + exp(-x))
    return s * (Float32(1.0) + x * (Float32(1.0) - s))


def silu_matrix(x: Matrix) -> Matrix:
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


struct MLPParams:
    var w1: Matrix
    var b1: List[Float32]
    var w2: Matrix
    var b2: List[Float32]

    def __init__(out self, w1: Matrix, b1: List[Float32], w2: Matrix, b2: List[Float32]):
        self.w1 = w1.clone()
        self.b1 = b1.copy()
        self.w2 = w2.clone()
        self.b2 = b2.copy()

    def clone(self) -> MLPParams:
        var p = MLPParams(self.w1.clone(), self.b1.copy(), self.w2.clone(), self.b2.copy())
        return p^


struct MLPGrads:
    var dw1: Matrix
    var db1: List[Float32]
    var dw2: Matrix
    var db2: List[Float32]
    var dx: Matrix

    def __init__(
        out self,
        dw1: Matrix,
        db1: List[Float32],
        dw2: Matrix,
        db2: List[Float32],
        dx: Matrix,
    ):
        self.dw1 = dw1.clone()
        self.db1 = db1.copy()
        self.dw2 = dw2.clone()
        self.db2 = db2.copy()
        self.dx = dx.clone()


def mlp_forward(x: Matrix, p: MLPParams) raises -> Matrix:
    var hidden_pre = matmul_add_bias(x, p.w1, p.b1)
    var hidden = silu_matrix(hidden_pre)
    var logits = matmul_add_bias(hidden, p.w2, p.b2)
    return logits^


def mlp_loss(x: Matrix, p: MLPParams, target: Int) raises -> Float32:
    var logits = mlp_forward(x, p)
    return softmax_cross_entropy(logits, 0, target)


def mlp_backward(x: Matrix, p: MLPParams, target: Int) raises -> MLPGrads:
    var hidden_pre = matmul_add_bias(x, p.w1, p.b1)
    var hidden = silu_matrix(hidden_pre)
    var logits = matmul_add_bias(hidden, p.w2, p.b2)
    var dlogits = sce_grad(logits, 0, target)
    # Layer 2: dW2 = hidden^T @ dlogits, db2 = colsum, dhidden = dlogits @ W2^T.
    var hidden_t = hidden.transpose()
    var dw2 = matmul_simd(hidden_t, dlogits)
    var db2 = column_sums(dlogits)
    var dhidden = matmul_atb(dlogits, p.w2)
    # SiLU derivative, elementwise on the pre-activations.
    var dpre = Matrix(dhidden.rows, dhidden.cols)
    for r in range(dhidden.rows):
        for c in range(dhidden.cols):
            dpre.set(r, c, dhidden.get(r, c) * silu_deriv_scalar(hidden_pre.get(r, c)))
    # Layer 1: dW1 = x^T @ dpre, db1 = colsum, dx = dpre @ W1^T.
    var xt = x.transpose()
    var dw1 = matmul_simd(xt, dpre)
    var db1 = column_sums(dpre)
    var dx = matmul_atb(dpre, p.w1)
    var grads = MLPGrads(dw1^, db1^, dw2^, db2^, dx^)
    return grads^


def sgd_step(mut p: MLPParams, g: MLPGrads, lr: Float32):
    """One SGD step, in place: w -= lr * dw for every parameter."""
    for i in range(len(p.w1.data)):
        p.w1.data[i] -= lr * g.dw1.data[i]
    for i in range(len(p.w2.data)):
        p.w2.data[i] -= lr * g.dw2.data[i]
    for i in range(len(p.b1)):
        p.b1[i] -= lr * g.db1[i]
    for i in range(len(p.b2)):
        p.b2[i] -= lr * g.db2[i]


# ---------------------------------------------------------------------------
# Finite-difference machinery
# ---------------------------------------------------------------------------
# Central differences: (f(w+e) - f(w-e)) / 2e. The error is O(e^2)
# in exact arithmetic; in Float32 the rounding floor is about
# 1e-7 / e, so e = 1e-3 balances the two at roughly 1e-4 -- the
# tolerance used below (2e-3) has an order of magnitude of slack.

def max_grad_error(
    analytic: Matrix, numeric: Matrix
) raises -> Float32:
    check(
        analytic.rows == numeric.rows and analytic.cols == numeric.cols,
        "max_grad_error: shape mismatch",
    )
    return analytic.max_abs_diff(numeric)


def test_linear_gradients() raises:
    var tol = Float32(2e-3)
    var eps = Float32(1e-3)
    # One training example: x is (1 x 4), W is (4 x 3).
    var x = Matrix(1, 4)
    x.set(0, 0, 0.5)
    x.set(0, 1, -1.0)
    x.set(0, 2, 2.0)
    x.set(0, 3, 0.25)
    var w = Matrix.randn(4, 3, 4242, 0.5)
    var b = List[Float32](length=3, fill=0.0)
    b[0] = 0.1
    b[1] = -0.2
    b[2] = 0.3
    var target = 1
    var logits = linear_forward(x, w, b)
    var loss = softmax_cross_entropy(logits, 0, target)
    check(loss > Float32(0.0), "cross-entropy loss is not positive")
    var dlogits = sce_grad(logits, 0, target)
    var grads = linear_backward(x, w, dlogits)
    check(grads.dx.rows == 1 and grads.dx.cols == 4, "dX has the wrong shape")
    check(grads.dw.rows == 4 and grads.dw.cols == 3, "dW has the wrong shape")
    check(len(grads.db) == 3, "db has the wrong length")
    # Numeric dW and db by central differences on each parameter.
    var num_dw = Matrix(4, 3)
    for i in range(4):
        for j in range(3):
            var orig = w.get(i, j)
            w.set(i, j, orig + eps)
            var lp = softmax_cross_entropy(linear_forward(x, w, b), 0, target)
            w.set(i, j, orig - eps)
            var lm = softmax_cross_entropy(linear_forward(x, w, b), 0, target)
            w.set(i, j, orig)
            num_dw.set(i, j, (lp - lm) / (Float32(2.0) * eps))
    var err_w = max_grad_error(grads.dw, num_dw)
    print("  linear dW max grad error: " + String(err_w))
    check(err_w <= tol, "linear dW failed the gradient check")
    var num_db = List[Float32](length=3, fill=0.0)
    for j in range(3):
        var orig = b[j]
        b[j] = orig + eps
        var lp = softmax_cross_entropy(linear_forward(x, w, b), 0, target)
        b[j] = orig - eps
        var lm = softmax_cross_entropy(linear_forward(x, w, b), 0, target)
        b[j] = orig
        num_db[j] = (lp - lm) / (Float32(2.0) * eps)
    for j in range(3):
        var d = grads.db[j] - num_db[j]
        if d < 0.0:
            d = -d
        check(d <= tol, "linear db failed the gradient check")
    # Numeric dX the same way, perturbing the input.
    var num_dx = Matrix(1, 4)
    for j in range(4):
        var orig = x.get(0, j)
        x.set(0, j, orig + eps)
        var lp = softmax_cross_entropy(linear_forward(x, w, b), 0, target)
        x.set(0, j, orig - eps)
        var lm = softmax_cross_entropy(linear_forward(x, w, b), 0, target)
        x.set(0, j, orig)
        num_dx.set(0, j, (lp - lm) / (Float32(2.0) * eps))
    var err_x = max_grad_error(grads.dx, num_dx)
    print("  linear dX max grad error: " + String(err_x))
    check(err_x <= tol, "linear dX failed the gradient check")


def test_softmax_ce_gradients() raises:
    var tol = Float32(2e-3)
    var eps = Float32(1e-3)
    var logits = Matrix(1, 5)
    logits.set(0, 0, 1.0)
    logits.set(0, 1, -2.0)
    logits.set(0, 2, 0.5)
    logits.set(0, 3, 3.0)
    logits.set(0, 4, -0.5)
    var target = 3
    var loss = softmax_cross_entropy(logits, 0, target)
    # The loss must equal -log(softmax[target]) computed directly.
    var probs = softmax_row_scalar(logits, 0)
    var expected = -log(probs[target])
    assert_almost_equal(loss, expected, atol=1e-6)
    # The gradient sums to zero (probabilities sum to 1, and the
    # one-hot removes exactly 1), and the target entry is negative.
    var grad = sce_grad(logits, 0, target)
    var total = Float32(0.0)
    for c in range(5):
        total += grad.get(0, c)
    assert_almost_equal(total, Float32(0.0), atol=1e-6)
    check(grad.get(0, target) < 0.0, "SCE gradient at the target is not negative")
    # Numeric check on every logit.
    for j in range(5):
        var orig = logits.get(0, j)
        logits.set(0, j, orig + eps)
        var lp = softmax_cross_entropy(logits, 0, target)
        logits.set(0, j, orig - eps)
        var lm = softmax_cross_entropy(logits, 0, target)
        logits.set(0, j, orig)
        var num = (lp - lm) / (Float32(2.0) * eps)
        var d = grad.get(0, j) - num
        if d < 0.0:
            d = -d
        check(d <= tol, "SCE gradient failed at logit " + String(j))


def test_mlp_gradients() raises:
    var tol = Float32(2e-3)
    var eps = Float32(1e-3)
    # Tiny MLP: x (1 x 3) -> hidden 4 -> logits 3.
    var x = Matrix(1, 3)
    x.set(0, 0, 0.8)
    x.set(0, 1, -0.5)
    x.set(0, 2, 1.2)
    var w1 = Matrix.randn(3, 4, 5150, 0.5)
    var b1 = List[Float32](length=4, fill=0.0)
    b1[0] = 0.1
    b1[2] = -0.3
    var w2 = Matrix.randn(4, 3, 5151, 0.5)
    var b2 = List[Float32](length=3, fill=0.0)
    b2[1] = 0.2
    var params = MLPParams(w1, b1, w2, b2)
    var target = 2
    var grads = mlp_backward(x, params, target)
    # Numeric gradients for every parameter, one at a time.
    var num_dw1 = Matrix(3, 4)
    for i in range(3):
        for j in range(4):
            var orig = params.w1.get(i, j)
            params.w1.set(i, j, orig + eps)
            var lp = mlp_loss(x, params, target)
            params.w1.set(i, j, orig - eps)
            var lm = mlp_loss(x, params, target)
            params.w1.set(i, j, orig)
            num_dw1.set(i, j, (lp - lm) / (Float32(2.0) * eps))
    var err_w1 = max_grad_error(grads.dw1, num_dw1)
    print("  mlp dW1 max grad error: " + String(err_w1))
    check(err_w1 <= tol, "MLP dW1 failed the gradient check")
    var num_dw2 = Matrix(4, 3)
    for i in range(4):
        for j in range(3):
            var orig = params.w2.get(i, j)
            params.w2.set(i, j, orig + eps)
            var lp = mlp_loss(x, params, target)
            params.w2.set(i, j, orig - eps)
            var lm = mlp_loss(x, params, target)
            params.w2.set(i, j, orig)
            num_dw2.set(i, j, (lp - lm) / (Float32(2.0) * eps))
    var err_w2 = max_grad_error(grads.dw2, num_dw2)
    print("  mlp dW2 max grad error: " + String(err_w2))
    check(err_w2 <= tol, "MLP dW2 failed the gradient check")
    # Biases: numeric check on b1 and b2.
    for j in range(4):
        var orig = params.b1[j]
        params.b1[j] = orig + eps
        var lp = mlp_loss(x, params, target)
        params.b1[j] = orig - eps
        var lm = mlp_loss(x, params, target)
        params.b1[j] = orig
        var num = (lp - lm) / (Float32(2.0) * eps)
        var d = grads.db1[j] - num
        if d < 0.0:
            d = -d
        check(d <= tol, "MLP db1 failed at " + String(j))
    for j in range(3):
        var orig = params.b2[j]
        params.b2[j] = orig + eps
        var lp = mlp_loss(x, params, target)
        params.b2[j] = orig - eps
        var lm = mlp_loss(x, params, target)
        params.b2[j] = orig
        var num = (lp - lm) / (Float32(2.0) * eps)
        var d = grads.db2[j] - num
        if d < 0.0:
            d = -d
        check(d <= tol, "MLP db2 failed at " + String(j))


def test_sgd_step_reduces_loss() raises:
    """The point of a gradient: one step downhill must reduce the
    loss. If the gradients were wrong (or sign-flipped), the loss
    would rise instead."""
    var x = Matrix(1, 3)
    x.set(0, 0, 0.8)
    x.set(0, 1, -0.5)
    x.set(0, 2, 1.2)
    var w1 = Matrix.randn(3, 4, 5150, 0.5)
    var b1 = List[Float32](length=4, fill=0.0)
    var w2 = Matrix.randn(4, 3, 5151, 0.5)
    var b2 = List[Float32](length=3, fill=0.0)
    var params = MLPParams(w1, b1, w2, b2)
    var target = 2
    var loss0 = mlp_loss(x, params, target)
    var grads = mlp_backward(x, params, target)
    sgd_step(params, grads, Float32(0.5))
    var loss1 = mlp_loss(x, params, target)
    print("  loss before step: " + String(loss0) + "  after step: " + String(loss1))
    check(loss1 < loss0, "one SGD step did not reduce the loss")
    # Ten more steps keep reducing it.
    for _i in range(10):
        var g = mlp_backward(x, params, target)
        sgd_step(params, g, Float32(0.5))
    var loss11 = mlp_loss(x, params, target)
    print("  loss after 11 steps: " + String(loss11))
    check(loss11 < loss1, "loss did not keep falling over 11 SGD steps")
    check(loss11 < Float32(0.1), "loss did not get small after 11 steps on one example")


def main() raises:
    print("=== transformer_gradcheck: analytic vs finite-difference gradients ===")
    print("")
    var suite = TestSuite()
    suite.test[test_linear_gradients]()
    suite.test[test_softmax_ce_gradients]()
    suite.test[test_mlp_gradients]()
    suite.test[test_sgd_step_reduces_loss]()
    suite^.run()
    print("  unit tests passed (linear grads, SCE grads, MLP grads, SGD step)")
    print("")

    print("Gradient-check summary (central differences, eps=1e-3, tol=2e-3):")
    print("  linear layer dW / db / dX: checked above")
    print("  softmax cross-entropy dlogits: checked above")
    print("  two-layer SiLU MLP dW1 / db1 / dW2 / db2: checked above")
    print("  one SGD step reduces the loss; 11 steps drive it below 0.1")
    print("")
    print("ALL GRADIENT CHECKS PASSED")
