# transformer_block.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# A full transformer block and a small stacked decoder.
#
# What this file demonstrates:
#   * `TransformerBlock`: pre-norm decoder block -- RMSNorm, causal
#     multi-head attention with RoPE on Q/K, residual, RMSNorm,
#     SwiGLU feed-forward, residual. This is the LLaMA-style block
#     layout used by most modern decoders.
#   * `block_forward_pre` and `block_forward_post`: the two
#     normalisation placements, so their behaviour can be compared
#     directly (pre-norm is what trains stably at depth).
#   * `Decoder`: a stack of blocks plus a final RMSNorm and a
#     vocabulary projection, with token embedding lookup and a
#     greedy next-token readout -- a complete, runnable miniature
#     language model forward pass.
#   * The checks that matter for a block:
#       - with every weight zeroed the block is exactly the identity
#         (residuals carry the input through untouched);
#       - outputs are finite for inputs scaled 0.1x, 1x and 10x;
#       - the output is deterministic across runs;
#       - with causal attention, changing the LAST token cannot
#         change any earlier output row (autoregressive locality);
#       - pre-norm and post-norm genuinely differ.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` /
# matmul / SDPA / RMSNorm / RoPE / MHA / SwiGLU core is the same
# self-contained core used across this sample series, repeated in
# each file so every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_block.mojo
# Exit code 0 means every check and every unit test passed.

from std.math import sqrt, log, cos, exp, sin, erf, tanh
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
# RoPE tables
# ---------------------------------------------------------------------------
# RoPE (Su et al., 2021) encodes position by rotating pairs of
# features. For head dimension d there are d/2 pairs, pair i rotates
# by angle pos * theta_i with theta_i = base^(-2i/d). Low indices
# rotate fast (fine position detail), high indices rotate slowly
# (coarse position). The cos/sin tables are precomputed once per
# maximum sequence length and reused for every forward pass.

def rope_freqs(head_dim: Int, base: Float32) raises -> List[Float32]:
    """Theta_i = base^(-2i / head_dim) for i in 0 .. head_dim/2."""
    check(head_dim % 2 == 0, "rope_freqs: head_dim must be even")
    var half = head_dim // 2
    var freqs = List[Float32](length=half, fill=0.0)
    for i in range(half):
        var exponent = Float32(-2.0) * Float32(i) / Float32(head_dim)
        freqs[i] = exp(exponent * log(base))
    return freqs^


struct RopeTables:
    """Precomputed cos/sin tables, shape (max_seq x head_dim/2)."""

    var cos_table: Matrix
    var sin_table: Matrix
    var head_dim: Int
    var max_seq: Int

    def __init__(out self, max_seq: Int, head_dim: Int, base: Float32) raises:
        check(head_dim % 2 == 0, "RopeTables: head_dim must be even")
        check(max_seq > 0, "RopeTables: max_seq must be positive")
        self.head_dim = head_dim
        self.max_seq = max_seq
        var half = head_dim // 2
        var freqs = rope_freqs(head_dim, base)
        self.cos_table = Matrix(max_seq, half)
        self.sin_table = Matrix(max_seq, half)
        for pos in range(max_seq):
            for i in range(half):
                var angle = Float32(pos) * freqs[i]
                self.cos_table.set(pos, i, cos(angle))
                self.sin_table.set(pos, i, sin(angle))

    def clone(self) raises -> RopeTables:
        var t = RopeTables(self.max_seq, self.head_dim, Float32(10000.0))
        t.cos_table = self.cos_table.clone()
        t.sin_table = self.sin_table.clone()
        return t^


# ---------------------------------------------------------------------------
# Applying RoPE
# ---------------------------------------------------------------------------
# For a row at absolute position p and pair i:
#   x'[2i]   = x[2i] * cos(p*theta_i) - x[2i+1] * sin(p*theta_i)
#   x'[2i+1] = x[2i] * sin(p*theta_i) + x[2i+1] * cos(p*theta_i)
# `start_pos` is the absolute position of row 0, which is what lets
# a KV-cache decode step apply RoPE at the right offset.

def apply_rope(
    x: Matrix, tables: RopeTables, start_pos: Int
) raises -> Matrix:
    """Scalar reference RoPE."""
    check(x.cols == tables.head_dim, "apply_rope: width must equal head_dim")
    check(start_pos >= 0, "apply_rope: start_pos must be non-negative")
    check(
        start_pos + x.rows <= tables.max_seq,
        "apply_rope: positions exceed the precomputed table",
    )
    var result = Matrix(x.rows, x.cols)
    var half = x.cols // 2
    for r in range(x.rows):
        var pos = start_pos + r
        for i in range(half):
            var c = tables.cos_table.get(pos, i)
            var s = tables.sin_table.get(pos, i)
            var x0 = x.get(r, 2 * i)
            var x1 = x.get(r, 2 * i + 1)
            result.set(r, 2 * i, x0 * c - x1 * s)
            result.set(r, 2 * i + 1, x0 * s + x1 * c)
    return result^


def apply_rope_simd(
    x: Matrix, tables: RopeTables, start_pos: Int
) raises -> Matrix:
    """SIMD RoPE: eight pairs at a time.

    The even features x[2i], x[2i+2], ... are gathered into one
    vector and the odd features into another; the cos/sin table
    rows are contiguous in i, so they load as plain chunks. The
    tail (fewer than 8 pairs left) falls back to the scalar code.
    """
    check(x.cols == tables.head_dim, "apply_rope_simd: width must equal head_dim")
    check(start_pos >= 0, "apply_rope_simd: start_pos must be non-negative")
    check(
        start_pos + x.rows <= tables.max_seq,
        "apply_rope_simd: positions exceed the precomputed table",
    )
    var result = Matrix(x.rows, x.cols)
    var half = x.cols // 2
    for r in range(x.rows):
        var pos = start_pos + r
        var i = 0
        while i + 8 <= half:
            var evens = SIMD[DType.float32, 8](
                x.get(r, 2 * i),
                x.get(r, 2 * i + 2),
                x.get(r, 2 * i + 4),
                x.get(r, 2 * i + 6),
                x.get(r, 2 * i + 8),
                x.get(r, 2 * i + 10),
                x.get(r, 2 * i + 12),
                x.get(r, 2 * i + 14),
            )
            var odds = SIMD[DType.float32, 8](
                x.get(r, 2 * i + 1),
                x.get(r, 2 * i + 3),
                x.get(r, 2 * i + 5),
                x.get(r, 2 * i + 7),
                x.get(r, 2 * i + 9),
                x.get(r, 2 * i + 11),
                x.get(r, 2 * i + 13),
                x.get(r, 2 * i + 15),
            )
            var c = load_row_chunk(tables.cos_table, pos, i)
            var s = load_row_chunk(tables.sin_table, pos, i)
            var new_evens = evens * c - odds * s
            var new_odds = evens * s + odds * c
            for t in range(8):
                result.set(r, 2 * (i + t), new_evens[t])
                result.set(r, 2 * (i + t) + 1, new_odds[t])
            i += 8
        while i < half:
            var c = tables.cos_table.get(pos, i)
            var s = tables.sin_table.get(pos, i)
            var x0 = x.get(r, 2 * i)
            var x1 = x.get(r, 2 * i + 1)
            result.set(r, 2 * i, x0 * c - x1 * s)
            result.set(r, 2 * i + 1, x0 * s + x1 * c)
            i += 1
    return result^


def row_norm(m: Matrix, r: Int) -> Float32:
    var total = Float32(0.0)
    for c in range(m.cols):
        var v = m.get(r, c)
        total += v * v
    return sqrt(total)


def row_dot(a: Matrix, ra: Int, b: Matrix, rb: Int) -> Float32:
    var total = Float32(0.0)
    for c in range(a.cols):
        total += a.get(ra, c) * b.get(rb, c)
    return total



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




# ---------------------------------------------------------------------------
# Elementwise helpers
# ---------------------------------------------------------------------------

def add_matrices(a: Matrix, b: Matrix) raises -> Matrix:
    check(a.rows == b.rows and a.cols == b.cols, "add_matrices: shape mismatch")
    var result = Matrix(a.rows, a.cols)
    for i in range(len(a.data)):
        result.data[i] = a.data[i] + b.data[i]
    return result^


def all_finite(m: Matrix) -> Bool:
    for i in range(len(m.data)):
        var v = m.data[i]
        if v != v:
            return False
        if v > Float32(3.4028235e38) or v < Float32(-3.4028235e38):
            return False
    return True


def argmax_row(m: Matrix, r: Int) -> Int:
    var best = 0
    var best_v = m.get(r, 0)
    for c in range(1, m.cols):
        var v = m.get(r, c)
        if v > best_v:
            best_v = v
            best = c
    return best


# ---------------------------------------------------------------------------
# Attention with RoPE
# ---------------------------------------------------------------------------
# The block's attention is MHA plus RoPE: Q and K are projected,
# split into heads, rotated at their absolute positions, and then
# attended with causal SDPA. RoPE is applied per head, so each head
# gets the same position tables at its own head dimension.

def mha_rope(
    x: Matrix,
    wq: Matrix,
    wk: Matrix,
    wv: Matrix,
    wo: Matrix,
    bq: List[Float32],
    bk: List[Float32],
    bv: List[Float32],
    bo: List[Float32],
    n_heads: Int,
    tables: RopeTables,
) raises -> Matrix:
    var q = linear(x, wq, bq)
    var k = linear(x, wk, bk)
    var v = linear(x, wv, bv)
    var q_heads = split_heads(q, n_heads)
    var k_heads = split_heads(k, n_heads)
    var v_heads = split_heads(v, n_heads)
    var out_heads = List[Matrix]()
    for h in range(n_heads):
        var q_rot = apply_rope_simd(q_heads[h], tables, 0)
        var k_rot = apply_rope_simd(k_heads[h], tables, 0)
        var head_out = sdpa(q_rot, k_rot, v_heads[h], True)
        out_heads.append(head_out^)
    var joined = concat_heads(out_heads)
    var result = linear(joined, wo, bo)
    return result^


def swiglu_block(
    x: Matrix,
    w_gate: Matrix,
    w_up: Matrix,
    w_down: Matrix,
    b_gate: List[Float32],
    b_up: List[Float32],
    b_down: List[Float32],
) raises -> Matrix:
    var gate = matmul_add_bias(x, w_gate, b_gate)
    var activated = silu_matrix(gate)
    var up = matmul_add_bias(x, w_up, b_up)
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
    var result = matmul_add_bias(hidden, w_down, b_down)
    return result^


# ---------------------------------------------------------------------------
# The transformer block
# ---------------------------------------------------------------------------

struct TransformerBlock:
    """One pre-norm decoder block (LLaMA-style layout).

    Attention weights are (d_model x d_model); the feed-forward
    uses d_ff, usually 4x d_model in the classic layout or ~8/3x
    with SwiGLU. Norm weights are plain per-column gain lists.
    """

    var d_model: Int
    var n_heads: Int
    var d_ff: Int
    var wq: Matrix
    var wk: Matrix
    var wv: Matrix
    var wo: Matrix
    var w_gate: Matrix
    var w_up: Matrix
    var w_down: Matrix
    var bq: List[Float32]
    var bk: List[Float32]
    var bv: List[Float32]
    var bo: List[Float32]
    var b_gate: List[Float32]
    var b_up: List[Float32]
    var b_down: List[Float32]
    var norm1_w: List[Float32]
    var norm2_w: List[Float32]

    def __init__(out self, d_model: Int, n_heads: Int, d_ff: Int, seed: UInt64) raises:
        check(d_model % n_heads == 0, "TransformerBlock: d_model must divide into heads")
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_ff = d_ff
        var scale_attn = Float32(1.0) / sqrt(Float32(d_model))
        var scale_ff = Float32(1.0) / sqrt(Float32(d_ff))
        self.wq = Matrix.randn(d_model, d_model, seed, scale_attn)
        self.wk = Matrix.randn(d_model, d_model, seed + 1, scale_attn)
        self.wv = Matrix.randn(d_model, d_model, seed + 2, scale_attn)
        self.wo = Matrix.randn(d_model, d_model, seed + 3, scale_attn)
        self.w_gate = Matrix.randn(d_model, d_ff, seed + 4, scale_attn)
        self.w_up = Matrix.randn(d_model, d_ff, seed + 5, scale_attn)
        self.w_down = Matrix.randn(d_ff, d_model, seed + 6, scale_ff)
        self.bq = zero_bias(d_model)
        self.bk = zero_bias(d_model)
        self.bv = zero_bias(d_model)
        self.bo = zero_bias(d_model)
        self.b_gate = zero_bias(d_ff)
        self.b_up = zero_bias(d_ff)
        self.b_down = zero_bias(d_model)
        self.norm1_w = ones_weight(d_model)
        self.norm2_w = ones_weight(d_model)

    def zero_all_weights(mut self):
        """Zero every projection (not the norms): the block must
        then behave as the exact identity, which tests the residual
        wiring with no other moving parts."""
        self.wq.fill(0.0)
        self.wk.fill(0.0)
        self.wv.fill(0.0)
        self.wo.fill(0.0)
        self.w_gate.fill(0.0)
        self.w_up.fill(0.0)
        self.w_down.fill(0.0)


def block_forward_pre(
    x: Matrix, blk: TransformerBlock, tables: RopeTables
) raises -> Matrix:
    """Pre-norm block: x + attn(norm(x)), then + mlp(norm(.)).

    Normalising BEFORE each sub-layer keeps the residual stream
    unscaled, which is why deep pre-norm stacks train stably: the
    gradient has a clean path through the additions.
    """
    var h1 = rmsnorm_rows(x, blk.norm1_w, Float32(1e-6))
    var attn = mha_rope(
        h1, blk.wq, blk.wk, blk.wv, blk.wo,
        blk.bq, blk.bk, blk.bv, blk.bo, blk.n_heads, tables,
    )
    var x1 = add_matrices(x, attn)
    var h2 = rmsnorm_rows(x1, blk.norm2_w, Float32(1e-6))
    var mlp = swiglu_block(
        h2, blk.w_gate, blk.w_up, blk.w_down,
        blk.b_gate, blk.b_up, blk.b_down,
    )
    var result = add_matrices(x1, mlp)
    return result^


def block_forward_post(
    x: Matrix, blk: TransformerBlock, tables: RopeTables
) raises -> Matrix:
    """Post-norm block: norm(x + attn(x)), then norm(. + mlp(.)).

    The original 2017 layout. The norms sit on the residual stream
    itself, so the stream is rescaled at every layer -- workable
    for shallow stacks, less stable as depth grows.
    """
    var attn = mha_rope(
        x, blk.wq, blk.wk, blk.wv, blk.wo,
        blk.bq, blk.bk, blk.bv, blk.bo, blk.n_heads, tables,
    )
    var x1 = add_matrices(x, attn)
    var n1 = rmsnorm_rows(x1, blk.norm1_w, Float32(1e-6))
    var mlp = swiglu_block(
        n1, blk.w_gate, blk.w_up, blk.w_down,
        blk.b_gate, blk.b_up, blk.b_down,
    )
    var x2 = add_matrices(n1, mlp)
    var result = rmsnorm_rows(x2, blk.norm2_w, Float32(1e-6))
    return result^


# ---------------------------------------------------------------------------
# The stacked decoder
# ---------------------------------------------------------------------------

struct Decoder:
    """A stack of blocks + final norm + vocab projection.

    `embed` looks up token rows of the embedding matrix, the blocks
    run the forward pass, the final norm stabilises the last hidden
    states, and the vocab projection turns them into logits.
    """

    var n_layers: Int
    var d_model: Int
    var vocab: Int
    var blocks: List[TransformerBlock]
    var final_norm_w: List[Float32]
    var vocab_w: Matrix
    var vocab_b: List[Float32]
    var tables: RopeTables
    var emb: Matrix

    def __init__(
        out self,
        n_layers: Int,
        d_model: Int,
        n_heads: Int,
        d_ff: Int,
        vocab: Int,
        max_seq: Int,
        seed: UInt64,
    ) raises:
        self.n_layers = n_layers
        self.d_model = d_model
        self.vocab = vocab
        self.blocks = List[TransformerBlock]()
        for l in range(n_layers):
            var blk = TransformerBlock(d_model, n_heads, d_ff, seed + UInt64(l * 100))
            self.blocks.append(blk^)
        self.final_norm_w = ones_weight(d_model)
        self.vocab_w = Matrix.randn(d_model, vocab, seed + 999, Float32(1.0) / sqrt(Float32(d_model)))
        self.vocab_b = zero_bias(vocab)
        self.tables = RopeTables(max_seq, d_model // n_heads, Float32(10000.0))
        self.emb = Matrix.randn(vocab, d_model, seed + 555, Float32(0.1))

    def embed_tokens(self, tokens: List[Int]) raises -> Matrix:
        var result = Matrix(len(tokens), self.d_model)
        for t in range(len(tokens)):
            var tok = tokens[t]
            check(tok >= 0 and tok < self.vocab, "embed_tokens: token id out of range")
            for c in range(self.d_model):
                result.set(t, c, self.emb.get(tok, c))
        return result^

    def forward(self, x: Matrix) raises -> Matrix:
        """Hidden states -> logits. x is (seq x d_model)."""
        var h = x.clone()
        for l in range(self.n_layers):
            var nxt = block_forward_pre(h, self.blocks[l], self.tables)
            h = nxt^
        var normed = rmsnorm_rows(h, self.final_norm_w, Float32(1e-6))
        var logits = matmul_add_bias(normed, self.vocab_w, self.vocab_b)
        return logits^

    def forward_tokens(self, tokens: List[Int]) raises -> Matrix:
        var x = self.embed_tokens(tokens)
        var logits = self.forward(x)
        return logits^


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def test_block_identity_zero_weights() raises:
    """Zero every projection: attention and MLP both output zero,
    so the two residuals must carry the input through exactly."""
    var tables = RopeTables(32, 8, Float32(10000.0))
    var blk = TransformerBlock(32, 4, 64, 1234)
    blk.zero_all_weights()
    var x = Matrix.randn(6, 32, 1235, 1.0)
    var y_pre = block_forward_pre(x, blk, tables)
    check(y_pre.max_abs_diff(x) == Float32(0.0),
          "zero-weight pre-norm block is not the identity")
    var y_post = block_forward_post(x, blk, tables)
    # Post-norm still normalises the stream, so it is NOT the
    # identity -- but it must be finite and shape-correct.
    check(y_post.rows == 6 and y_post.cols == 32, "post-norm block changed shape")
    check(all_finite(y_post), "zero-weight post-norm block is not finite")


def test_block_shapes_finite() raises:
    var tables = RopeTables(64, 8, Float32(10000.0))
    var blk = TransformerBlock(32, 4, 128, 2345)
    var scales = List[Float32]()
    scales.append(0.1)
    scales.append(1.0)
    scales.append(10.0)
    for si in range(len(scales)):
        var x = Matrix.randn(12, 32, UInt64(3000 + si), scales[si])
        var y = block_forward_pre(x, blk, tables)
        check(y.rows == 12 and y.cols == 32, "block changed shape")
        check(all_finite(y), "block output is not finite at scale " + String(scales[si]))
        var moved = y.max_abs_diff(x)
        check(moved > Float32(1e-6), "block output equals its input (dead block?)")
        check(moved < Float32(100.0), "block output exploded: moved " + String(moved))
    # Pre-norm and post-norm genuinely differ on the same weights.
    var x = Matrix.randn(8, 32, 3456, 1.0)
    var y_pre = block_forward_pre(x, blk, tables)
    var y_post = block_forward_post(x, blk, tables)
    check(y_pre.max_abs_diff(y_post) > Float32(1e-3),
          "pre-norm and post-norm blocks unexpectedly agree")
    # Determinism.
    var y2 = block_forward_pre(x, blk, tables)
    check(y_pre.max_abs_diff(y2) == Float32(0.0), "block forward is not deterministic")


def test_causal_locality() raises:
    """Changing the last token must not change any earlier output
    row. This is the block-level form of autoregressiveness, and it
    only holds if the causal mask, the residuals and the RoPE
    positions are all wired correctly."""
    var tables = RopeTables(64, 8, Float32(10000.0))
    var blk = TransformerBlock(32, 4, 64, 4567)
    var x = Matrix.randn(8, 32, 4568, 1.0)
    var base = block_forward_pre(x, blk, tables)
    var x2 = x.clone()
    var rng = Rng(4569)
    for c in range(32):
        x2.set(7, c, rng.normal_scaled(3.0))
    var changed = block_forward_pre(x2, blk, tables)
    for r in range(7):
        for c in range(32):
            check(base.get(r, c) == changed.get(r, c),
                  "causal locality violated at row " + String(r))
    var moved_last = Float32(0.0)
    for c in range(32):
        var d = base.get(7, c) - changed.get(7, c)
        if d < 0.0:
            d = -d
        if d > moved_last:
            moved_last = d
    check(moved_last > Float32(1e-3), "changing the last token did not change its output")


def test_decoder_logits() raises:
    var dec = Decoder(2, 32, 4, 64, 64, 32, 7777)
    var tokens = List[Int]()
    tokens.append(3)
    tokens.append(17)
    tokens.append(42)
    tokens.append(9)
    var logits = dec.forward_tokens(tokens)
    check(logits.rows == 4 and logits.cols == 64, "decoder logits have the wrong shape")
    check(all_finite(logits), "decoder logits are not finite")
    var logits2 = dec.forward_tokens(tokens)
    check(logits.max_abs_diff(logits2) == Float32(0.0), "decoder is not deterministic")
    # A different prompt gives different logits at the last row.
    var tokens2 = List[Int]()
    tokens2.append(3)
    tokens2.append(17)
    tokens2.append(42)
    tokens2.append(10)
    var logits_b = dec.forward_tokens(tokens2)
    var same = True
    for c in range(64):
        if logits.get(0, c) != logits_b.get(0, c):
            same = False
    check(same, "changing the last token changed an earlier row's logits")
    var last_diff = Float32(0.0)
    for c in range(64):
        var d = logits.get(3, c) - logits_b.get(3, c)
        if d < 0.0:
            d = -d
        if d > last_diff:
            last_diff = d
    check(last_diff > Float32(1e-4), "changing the last token did not change its logits")


def main() raises:
    print("=== transformer_block: full block + stacked decoder ===")
    print("")
    var suite = TestSuite()
    suite.test[test_block_identity_zero_weights]()
    suite.test[test_block_shapes_finite]()
    suite.test[test_causal_locality]()
    suite.test[test_decoder_logits]()
    suite^.run()
    print("  unit tests passed (identity, shapes/finite, causal locality,")
    print("  decoder logits)")
    print("")

    print("Running a tiny decoder (2 layers, d_model 32, vocab 64):")
    var dec = Decoder(2, 32, 4, 64, 64, 32, 20240)
    var prompt = List[Int]()
    prompt.append(5)
    prompt.append(23)
    prompt.append(41)
    prompt.append(7)
    prompt.append(19)
    var logits = dec.forward_tokens(prompt)
    print("  prompt tokens: 5 23 41 7 19")
    print("  logits shape: " + logits.shape_str())
    print("  last-row top token (greedy next token): " + String(argmax_row(logits, 4)))
    print("  first-row top token: " + String(argmax_row(logits, 0)))
    print("  last-row logits (first 8 of 64):")
    logits.print_block(1, 8)
    # Greedy continuation: feed the model's own prediction back in.
    var generated = List[Int]()
    for t in range(len(prompt)):
        generated.append(prompt[t])
    for _step in range(6):
        var lg = dec.forward_tokens(generated)
        var nxt = argmax_row(lg, len(generated) - 1)
        generated.append(nxt)
    print("  greedy continuation (6 steps):")
    var line = String("   ")
    for t in range(len(generated)):
        line += String(generated[t]) + " "
    print(line)
    var logits_again = dec.forward_tokens(prompt)
    check(logits.max_abs_diff(logits_again) == Float32(0.0), "decoder is not deterministic")
    print("  determinism: second forward pass is bit-identical")
    print("")
    print("ALL BLOCK CHECKS PASSED")
