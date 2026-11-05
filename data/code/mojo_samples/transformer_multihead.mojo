# transformer_multihead.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# Multi-head attention (MHA): split, attend per head, concat, project.
#
# What this file demonstrates:
#   * `MHAWeights`: the four projections of one attention layer
#     (Wq, Wk, Wv, Wo plus biases), initialised at the usual
#     1/sqrt(d_model) scale.
#   * `split_heads` / `concat_heads`: reshaping (seq x d_model) into
#     per-head (seq x d_head) views and back. The split is a pure
#     column partition -- no data is ever copied twice.
#   * `mha`: project, attend independently in each head with the
#     fast SDPA from transformer_attention, concat, output-project.
#   * `mha_naive`: the same computation with scalar matmuls and
#     scalar SDPA, used as the correctness reference.
#   * Two structural checks that catch real bugs:
#       - one head must reduce exactly to single-head attention;
#       - permuting the heads (and the matching blocks of Wo) must
#         leave the output bit-identical, because heads are
#         independent and their order is arbitrary.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` /
# matmul / SDPA core is the same self-contained core used across
# this sample series, repeated in each file so every file runs on
# its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_multihead.mojo
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
# Linear projections
# ---------------------------------------------------------------------------
# A transformer linear layer is y = x @ W + b. The bias is a plain
# List[Float32] with one entry per output column; the fused add keeps
# the hot path as one SIMD matmul plus one pass over the output.

def linear(x: Matrix, w: Matrix, bias: List[Float32]) raises -> Matrix:
    var y = matmul_simd(x, w)
    check(len(bias) == w.cols, "linear: bias length must equal output columns")
    for i in range(y.rows):
        for j in range(y.cols):
            y.set(i, j, y.get(i, j) + bias[j])
    return y^


def linear_naive(x: Matrix, w: Matrix, bias: List[Float32]) raises -> Matrix:
    var y = matmul_naive(x, w)
    check(len(bias) == w.cols, "linear_naive: bias length must equal output columns")
    for i in range(y.rows):
        for j in range(y.cols):
            y.set(i, j, y.get(i, j) + bias[j])
    return y^


def zero_bias(cols: Int) -> List[Float32]:
    return List[Float32](length=cols, fill=0.0)


# ---------------------------------------------------------------------------
# Head splitting
# ---------------------------------------------------------------------------

def split_heads(x: Matrix, n_heads: Int) raises -> List[Matrix]:
    """Split (seq x d_model) into n_heads matrices of (seq x d_head).

    Head h owns columns [h*d_head, (h+1)*d_head) of every row. This
    is the "split" half of split/concat; it is a pure partition, so
    concatenating the pieces reproduces the input exactly.
    """
    check(x.cols % n_heads == 0, "split_heads: d_model must divide evenly into heads")
    var d_head = x.cols // n_heads
    var heads = List[Matrix]()
    for h in range(n_heads):
        var part = Matrix(x.rows, d_head)
        for r in range(x.rows):
            for c in range(d_head):
                part.set(r, c, x.get(r, h * d_head + c))
        heads.append(part^)
    return heads^


def concat_heads(heads: List[Matrix]) raises -> Matrix:
    """Inverse of split_heads: column-concatenate the per-head pieces."""
    check(len(heads) > 0, "concat_heads: need at least one head")
    var seq = heads[0].rows
    var d_head = heads[0].cols
    var result = Matrix(seq, d_head * len(heads))
    for h in range(len(heads)):
        check(heads[h].rows == seq, "concat_heads: head row counts differ")
        check(heads[h].cols == d_head, "concat_heads: head widths differ")
        for r in range(seq):
            for c in range(d_head):
                result.set(r, c + h * d_head, heads[h].get(r, c))
    return result^


# ---------------------------------------------------------------------------
# MHA weights
# ---------------------------------------------------------------------------

struct MHAWeights:
    """The four projections of one attention layer, with biases.

    Wq, Wk, Wv are (d_model x d_model); Wo is (d_model x d_model).
    In the per-head view, head h owns columns [h*d_head,
    (h+1)*d_head) of Wq/Wk/Wv and rows [h*d_head, (h+1)*d_head) of Wo.
    """

    var d_model: Int
    var n_heads: Int
    var d_head: Int
    var wq: Matrix
    var wk: Matrix
    var wv: Matrix
    var wo: Matrix
    var bq: List[Float32]
    var bk: List[Float32]
    var bv: List[Float32]
    var bo: List[Float32]

    def __init__(out self, d_model: Int, n_heads: Int, seed: UInt64) raises:
        check(d_model % n_heads == 0, "MHAWeights: d_model must divide evenly into heads")
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        var scale = Float32(1.0) / sqrt(Float32(d_model))
        self.wq = Matrix.randn(d_model, d_model, seed, scale)
        self.wk = Matrix.randn(d_model, d_model, seed + 1, scale)
        self.wv = Matrix.randn(d_model, d_model, seed + 2, scale)
        self.wo = Matrix.randn(d_model, d_model, seed + 3, scale)
        self.bq = zero_bias(d_model)
        self.bk = zero_bias(d_model)
        self.bv = zero_bias(d_model)
        self.bo = zero_bias(d_model)

    def clone(self) raises -> MHAWeights:
        var w = MHAWeights(self.d_model, self.n_heads, 1)
        w.wq = self.wq.clone()
        w.wk = self.wk.clone()
        w.wv = self.wv.clone()
        w.wo = self.wo.clone()
        w.bq = self.bq.copy()
        w.bk = self.bk.copy()
        w.bv = self.bv.copy()
        w.bo = self.bo.copy()
        return w^


def permute_heads(w: MHAWeights, perm: List[Int]) raises -> MHAWeights:
    """Reorder the heads of a weight set.

    `perm` maps new head index -> old head index. The column blocks
    of Wq/Wk/Wv (and their biases) and the row blocks of Wo are all
    permuted the same way. Because heads are independent, MHA with
    the permuted weights must give bit-identical output -- a strong
    check that the split/concat bookkeeping is right.
    """
    check(len(perm) == w.n_heads, "permute_heads: permutation length must equal head count")
    var result = w.clone()
    var d_head = w.d_head
    for new_h in range(w.n_heads):
        var old_h = perm[new_h]
        for c in range(d_head):
            var src_col = old_h * d_head + c
            var dst_col = new_h * d_head + c
            for r in range(w.d_model):
                result.wq.set(r, dst_col, w.wq.get(r, src_col))
                result.wk.set(r, dst_col, w.wk.get(r, src_col))
                result.wv.set(r, dst_col, w.wv.get(r, src_col))
            result.bq[dst_col] = w.bq[src_col]
            result.bk[dst_col] = w.bk[src_col]
            result.bv[dst_col] = w.bv[src_col]
            # Wo is permuted along its ROWS: head h contributes rows
            # [h*d_head, (h+1)*d_head).
            for cc in range(w.d_model):
                result.wo.set(dst_col, cc, w.wo.get(src_col, cc))
    return result^


# ---------------------------------------------------------------------------
# Multi-head attention
# ---------------------------------------------------------------------------

def mha(x: Matrix, w: MHAWeights, causal: Bool) raises -> Matrix:
    """Fast MHA: project, per-head SDPA, concat, output project."""
    var q = linear(x, w.wq, w.bq)
    var k = linear(x, w.wk, w.bk)
    var v = linear(x, w.wv, w.bv)
    var q_heads = split_heads(q, w.n_heads)
    var k_heads = split_heads(k, w.n_heads)
    var v_heads = split_heads(v, w.n_heads)
    var out_heads = List[Matrix]()
    for h in range(w.n_heads):
        var head_out = sdpa(q_heads[h], k_heads[h], v_heads[h], causal)
        out_heads.append(head_out^)
    var joined = concat_heads(out_heads)
    var result = linear(joined, w.wo, w.bo)
    return result^


def mha_naive(x: Matrix, w: MHAWeights, causal: Bool) raises -> Matrix:
    """Scalar reference MHA: naive linears and naive per-head SDPA."""
    var q = linear_naive(x, w.wq, w.bq)
    var k = linear_naive(x, w.wk, w.bk)
    var v = linear_naive(x, w.wv, w.bv)
    var q_heads = split_heads(q, w.n_heads)
    var k_heads = split_heads(k, w.n_heads)
    var v_heads = split_heads(v, w.n_heads)
    var out_heads = List[Matrix]()
    for h in range(w.n_heads):
        var head_out = sdpa_naive(q_heads[h], k_heads[h], v_heads[h], causal)
        out_heads.append(head_out^)
    var joined = concat_heads(out_heads)
    var result = linear_naive(joined, w.wo, w.bo)
    return result^


def mha_probs(x: Matrix, w: MHAWeights, causal: Bool) raises -> List[Matrix]:
    """Per-head attention probability matrices, for inspection.

    Returns one (seq x seq) matrix per head. Every row must sum to
    1, and with a causal mask every entry above the diagonal must
    be (numerically) zero.
    """
    var q = linear(x, w.wq, w.bq)
    var k = linear(x, w.wk, w.bk)
    var q_heads = split_heads(q, w.n_heads)
    var k_heads = split_heads(k, w.n_heads)
    var probs = List[Matrix]()
    for h in range(w.n_heads):
        var scores = sdpa_scores(q_heads[h], k_heads[h], causal)
        var probs_h = softmax_rows(scores)
        probs.append(probs_h^)
    return probs^


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_probs_valid(probs: List[Matrix], causal: Bool) raises:
    for h in range(len(probs)):
        for i in range(probs[h].rows):
            var s = Float32(0.0)
            for j in range(probs[h].cols):
                var v = probs[h].get(i, j)
                check(v >= 0.0 and v <= 1.0, "attention probability outside [0, 1]")
                if causal and j > i:
                    check(v < Float32(1e-6), "causal mask leaked probability to a future position")
                s += v
            check(s > Float32(1.0) - Float32(1e-5) and s < Float32(1.0) + Float32(1e-5),
                  "attention row does not sum to 1")


def test_split_concat_roundtrip() raises:
    var x = Matrix.randn(9, 24, 77, 1.0)
    for n_heads in range(1, 9):
        if 24 % n_heads != 0:
            continue
        var heads = split_heads(x, n_heads)
        check(len(heads) == n_heads, "split_heads returned wrong head count")
        var back = concat_heads(heads)
        check(back.max_abs_diff(x) == Float32(0.0), "split/concat round-trip is not exact")
    # Odd sequence length and a single column per head.
    var thin = Matrix.randn(5, 8, 78, 1.0)
    var heads8 = split_heads(thin, 8)
    check(heads8[0].cols == 1, "8 heads over d_model 8 should give d_head 1")
    var back8 = concat_heads(heads8)
    check(back8.max_abs_diff(thin) == Float32(0.0), "thin split/concat round-trip failed")


def test_mha_matches_naive() raises:
    var tol = Float32(1e-4)
    var seq = 13
    var d_model = 32
    var x = Matrix.randn(seq, d_model, 55, 0.7)
    for n_heads in range(1, 5):
        if d_model % n_heads != 0:
            continue
        var w = MHAWeights(d_model, n_heads, UInt64(60 + n_heads))
        var fast = mha(x, w, True)
        var reference = mha_naive(x, w, True)
        check(fast.max_abs_diff(reference) <= tol,
              "MHA fast vs naive mismatch, heads=" + String(n_heads))
        var fast_full = mha(x, w, False)
        var ref_full = mha_naive(x, w, False)
        check(fast_full.max_abs_diff(ref_full) <= tol,
              "MHA (non-causal) fast vs naive mismatch, heads=" + String(n_heads))
        var probs = mha_probs(x, w, True)
        check_probs_valid(probs, True)
        var probs_full = mha_probs(x, w, False)
        check_probs_valid(probs_full, False)


def test_mha_single_head_reduction() raises:
    """With one head, MHA must equal single-head attention by hand."""
    var seq = 6
    var d_model = 16
    var x = Matrix.randn(seq, d_model, 88, 0.7)
    var w = MHAWeights(d_model, 1, 99)
    var got = mha(x, w, True)
    var q = linear(x, w.wq, w.bq)
    var k = linear(x, w.wk, w.bk)
    var v = linear(x, w.wv, w.bv)
    var attended = sdpa(q, k, v, True)
    var manual = linear(attended, w.wo, w.bo)
    check(got.max_abs_diff(manual) <= Float32(1e-5),
          "single-head MHA does not reduce to plain SDPA")


def test_head_permutation_invariance() raises:
    """Reordering heads (and the matching Wo rows) must not change
    the output at all. This is the check that would catch a head
    being wired to the wrong output block."""
    var seq = 8
    var d_model = 24
    var x = Matrix.randn(seq, d_model, 111, 0.7)
    var w = MHAWeights(d_model, 4, 222)
    var base = mha(x, w, True)
    # Reverse the head order.
    var perm = List[Int]()
    perm.append(3)
    perm.append(2)
    perm.append(1)
    perm.append(0)
    var w_perm = permute_heads(w, perm)
    var permuted = mha(x, w_perm, True)
    check(base.max_abs_diff(permuted) <= Float32(1e-5),
          "head permutation changed the MHA output")
    # A rotation by one head.
    var perm2 = List[Int]()
    perm2.append(1)
    perm2.append(2)
    perm2.append(3)
    perm2.append(0)
    var w_perm2 = permute_heads(w, perm2)
    var permuted2 = mha(x, w_perm2, True)
    check(base.max_abs_diff(permuted2) <= Float32(1e-5),
          "head rotation changed the MHA output")


def main() raises:
    print("=== transformer_multihead: multi-head attention ===")
    print("")
    var suite = TestSuite()
    suite.test[test_split_concat_roundtrip]()
    suite.test[test_mha_matches_naive]()
    suite.test[test_mha_single_head_reduction]()
    suite.test[test_head_permutation_invariance]()
    suite^.run()
    print("  unit tests passed (split/concat, MHA vs naive, 1-head")
    print("  reduction, head-permutation invariance)")
    print("")

    print("Fast vs naive MHA on several shapes (tolerance 1e-4):")
    var tol = Float32(1e-4)
    var seqs = List[Int]()
    seqs.append(1)
    seqs.append(7)
    seqs.append(16)
    seqs.append(25)
    var models = List[Int]()
    models.append(16)
    models.append(32)
    models.append(64)
    for si in range(len(seqs)):
        for mi in range(len(models)):
            var seq = seqs[si]
            var d_model = models[mi]
            var x = Matrix.randn(seq, d_model, UInt64(400 + si * 13 + mi), 0.6)
            for n_heads in range(1, 5):
                if d_model % n_heads != 0:
                    continue
                var w = MHAWeights(d_model, n_heads, UInt64(500 + si * 17 + mi * 3 + n_heads))
                var fast = mha(x, w, True)
                var reference = mha_naive(x, w, True)
                var diff = fast.max_abs_diff(reference)
                check(diff <= tol, "MHA mismatch seq=" + String(seq) + " d=" + String(d_model))
                print(
                    "  OK seq="
                    + String(seq)
                    + " d_model="
                    + String(d_model)
                    + " heads="
                    + String(n_heads)
                    + " d_head="
                    + String(d_model // n_heads)
                    + " max diff="
                    + String(diff)
                )
    print("")

    print("Inspecting one small run (seq=4, d_model=8, heads=2):")
    var x = Matrix.arange(4, 8, 0.1, 0.05)
    var w = MHAWeights(8, 2, 777)
    var result = mha(x, w, True)
    print("  input row 0:")
    x.print_block(1, 8)
    print("  MHA output (causal):")
    result.print_block(4, 8)
    var result2 = mha(x, w, True)
    check(result.max_abs_diff(result2) == Float32(0.0), "MHA is not deterministic")
    var probs = mha_probs(x, w, True)
    print("  head 0 attention rows (row i sums to 1, future is 0):")
    probs[0].print_block(4, 4)
    check_probs_valid(probs, True)
    print("  determinism: second run is bit-identical")
    print("")
    print("ALL MULTI-HEAD CHECKS PASSED")
