# transformer_kv_cache.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# A KV-cache for autoregressive decoding, with a step-by-step
# generation loop.
#
# What this file demonstrates:
#   * `KVCache`: preallocated K and V buffers (max_len x d_model)
#     with a length counter. Appending one token's K/V row is O(1);
#     attention over the cache only ever reads the filled prefix,
#     so decoding one new token costs O(len) instead of O(len^2).
#   * `CachedBlock`: one pre-norm decoder block (RMSNorm, causal
#     MHA with RoPE, SwiGLU) that can run in two modes:
#       - `prefill`: run a whole prompt at once, filling the cache;
#       - `decode_step`: run a single new token against the cache.
#   * The equivalence that makes the cache trustworthy, checked
#     directly: prefill outputs and one-token-at-a-time decode
#     outputs agree to 1e-5, and both agree with a full
#     recompute-from-scratch forward pass.
#   * A greedy generation loop: embed a prompt, prefill, then
#     decode token after token, each step's argmax feeding the next
#     step's input -- and the token stream is checked identical to
#     generation by full recomputation at every step.
#   * RoPE with absolute positions: a decode step at position p
#     rotates Q/K by p, which is why the cache can store already-
#     rotated keys and reuse them verbatim.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` /
# matmul / SDPA / RMSNorm / RoPE core is the same self-contained
# core used across this sample series, repeated in each file so
# every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_kv_cache.mojo
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


def single_row(m: Matrix, r: Int) -> Matrix:
    var result = Matrix(1, m.cols)
    for c in range(m.cols):
        result.set(0, c, m.get(r, c))
    return result^


# ---------------------------------------------------------------------------
# The KV cache
# ---------------------------------------------------------------------------
# Two preallocated buffers, (max_len x d_model) each, plus a length.
# Rows [0, len) hold the keys/values of the tokens seen so far, in
# order; rows [len, max_len) are unwritten. Because RoPE is applied
# BEFORE the keys are stored, a cached key already carries its
# absolute position and can be reused verbatim at every later step.

struct KVCache:
    var max_len: Int
    var d_model: Int
    var len: Int
    var keys: Matrix
    var values: Matrix

    def __init__(out self, max_len: Int, d_model: Int):
        self.max_len = max_len
        self.d_model = d_model
        self.len = 0
        self.keys = Matrix(max_len, d_model)
        self.values = Matrix(max_len, d_model)

    def append(mut self, k_row: Matrix, v_row: Matrix) raises:
        """Store one token's K and V rows (each 1 x d_model)."""
        check(k_row.rows == 1 and k_row.cols == self.d_model, "KVCache.append: bad K row shape")
        check(v_row.rows == 1 and v_row.cols == self.d_model, "KVCache.append: bad V row shape")
        check(self.len < self.max_len, "KVCache.append: cache is full")
        for c in range(self.d_model):
            self.keys.set(self.len, c, k_row.get(0, c))
            self.values.set(self.len, c, v_row.get(0, c))
        self.len += 1

    def clear(mut self):
        self.len = 0

    def is_empty(self) -> Bool:
        return self.len == 0

    def is_full(self) -> Bool:
        return self.len >= self.max_len


# ---------------------------------------------------------------------------
# Cached attention for one query row
# ---------------------------------------------------------------------------
# Scores of one query against every cached key, per head. The query
# is a single row, so each score is a plain dot product; the softmax
# runs over the cached prefix only, which is exactly the causal
# mask -- no explicit mask is needed, because future keys simply
# are not in the cache yet.

def cached_attention(
    q_row: Matrix,
    cache: KVCache,
    n_heads: Int,
    tables: RopeTables,
    pos: Int,
) raises -> Matrix:
    """Attend one rotated query row against the cache.

    q_row is (1 x d_model) AFTER its Q projection but BEFORE RoPE;
    RoPE is applied here at absolute position `pos`, and the result
    is (1 x d_model). The cache must already contain the keys for
    positions 0..pos-1 (and the current key, if appended first).
    """
    check(q_row.rows == 1, "cached_attention: query must be a single row")
    var d_model = q_row.cols
    var d_head = d_model // n_heads
    var scale = Float32(1.0) / sqrt(Float32(d_head))
    var q_heads = split_heads(q_row, n_heads)
    var out_heads = List[Matrix]()
    for h in range(n_heads):
        var qh = apply_rope_simd(q_heads[h], tables, pos)
        # Scores against every cached key of this head.
        var scores = List[Float32](length=cache.len, fill=0.0)
        var best = Float32(-3.4028235e38)
        for t in range(cache.len):
            var dot = Float32(0.0)
            for c in range(d_head):
                dot += qh.get(0, c) * cache.keys.get(t, h * d_head + c)
            scores[t] = dot * scale
            if scores[t] > best:
                best = scores[t]
        # Stable softmax over the cached prefix.
        var denom = Float32(0.0)
        for t in range(cache.len):
            scores[t] = exp(scores[t] - best)
            denom += scores[t]
        var out_h = Matrix(1, d_head)
        for c in range(d_head):
            var acc = Float32(0.0)
            for t in range(cache.len):
                var p = scores[t] / denom
                acc += p * cache.values.get(t, h * d_head + c)
            out_h.set(0, c, acc)
        out_heads.append(out_h^)
    var joined = concat_heads(out_heads)
    return joined^


# ---------------------------------------------------------------------------
# One cached decoder block
# ---------------------------------------------------------------------------

struct CachedBlock:
    """One pre-norm decoder block with a KV cache.

    Weights mirror TransformerBlock in transformer_block.mojo:
    attention projections, SwiGLU projections, RMSNorm gains.
    """

    var d_model: Int
    var n_heads: Int
    var d_ff: Int
    var max_len: Int
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
    var cache: KVCache
    var tables: RopeTables

    def __init__(
        out self, d_model: Int, n_heads: Int, d_ff: Int, max_len: Int, seed: UInt64
    ) raises:
        check(d_model % n_heads == 0, "CachedBlock: d_model must divide into heads")
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_ff = d_ff
        self.max_len = max_len
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
        self.cache = KVCache(max_len, d_model)
        self.tables = RopeTables(max_len, d_model // n_heads, Float32(10000.0))

    def clear_cache(mut self):
        self.cache.clear()

    def swiglu_forward(self, x: Matrix) raises -> Matrix:
        var gate = matmul_add_bias(x, self.w_gate, self.b_gate)
        var activated = silu_matrix(gate)
        var up = matmul_add_bias(x, self.w_up, self.b_up)
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
        var result = matmul_add_bias(hidden, self.w_down, self.b_down)
        return result^

    def decode_step(mut self, h_row: Matrix) raises -> Matrix:
        """Run one token (1 x d_model) through the block, using and
        extending the cache. Returns the block output row.

        The order matters: the K/V rows are projected, rotated at
        the CURRENT absolute position (the cache length), appended,
        and only then attended -- so the token attends to itself and
        everything before it, and nothing after.
        """
        check(h_row.rows == 1, "decode_step: input must be a single row")
        var pos = self.cache.len
        var normed = rmsnorm_rows(h_row, self.norm1_w, Float32(1e-6))
        var q = linear(normed, self.wq, self.bq)
        var k = linear(normed, self.wk, self.bk)
        var v = linear(normed, self.wv, self.bv)
        # Rotate K at this absolute position, then store it.
        var k_heads = split_heads(k, self.n_heads)
        var k_rot_heads = List[Matrix]()
        for hh in range(self.n_heads):
            var kr = apply_rope_simd(k_heads[hh], self.tables, pos)
            k_rot_heads.append(kr^)
        var k_rot = concat_heads(k_rot_heads)
        self.cache.append(k_rot, v)
        var attended = cached_attention(q, self.cache, self.n_heads, self.tables, pos)
        var attn_out = linear(attended, self.wo, self.bo)
        var x1 = add_matrices(h_row, attn_out)
        var h2 = rmsnorm_rows(x1, self.norm2_w, Float32(1e-6))
        var mlp = self.swiglu_forward(h2)
        var result = add_matrices(x1, mlp)
        return result^

    def prefill(mut self, x: Matrix) raises -> Matrix:
        """Run a whole prompt (seq x d_model) through the block,
        one decode_step per row, filling the cache. Returns the
        block outputs for every prompt row."""
        self.clear_cache()
        var result = Matrix(x.rows, x.cols)
        for r in range(x.rows):
            var row = single_row(x, r)
            var out_row = self.decode_step(row)
            for c in range(x.cols):
                result.set(r, c, out_row.get(0, c))
        return result^

    def forward_full(self, x: Matrix) raises -> Matrix:
        """The same block with NO cache: full causal SDPA over the
        whole sequence. This is the reference the cached modes are
        checked against."""
        var h1 = rmsnorm_rows(x, self.norm1_w, Float32(1e-6))
        var q = linear(h1, self.wq, self.bq)
        var k = linear(h1, self.wk, self.bk)
        var v = linear(h1, self.wv, self.bv)
        var q_heads = split_heads(q, self.n_heads)
        var k_heads = split_heads(k, self.n_heads)
        var v_heads = split_heads(v, self.n_heads)
        var out_heads = List[Matrix]()
        for hh in range(self.n_heads):
            var q_rot = apply_rope_simd(q_heads[hh], self.tables, 0)
            var k_rot = apply_rope_simd(k_heads[hh], self.tables, 0)
            var head_out = sdpa(q_rot, k_rot, v_heads[hh], True)
            out_heads.append(head_out^)
        var joined = concat_heads(out_heads)
        var attn_out = linear(joined, self.wo, self.bo)
        var x1 = add_matrices(x, attn_out)
        var h2 = rmsnorm_rows(x1, self.norm2_w, Float32(1e-6))
        var mlp = self.swiglu_forward(h2)
        var result = add_matrices(x1, mlp)
        return result^


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def test_cache_append_and_clear() raises:
    var cache = KVCache(8, 4)
    check(cache.is_empty(), "fresh cache is not empty")
    check(cache.len == 0, "fresh cache length is not 0")
    var k = Matrix(1, 4)
    var v = Matrix(1, 4)
    for i in range(4):
        k.set(0, i, Float32(i + 1))
        v.set(0, i, Float32(10 - i))
    cache.append(k, v)
    check(cache.len == 1, "cache length is not 1 after one append")
    check(cache.keys.get(0, 2) == Float32(3.0), "cached key row is wrong")
    check(cache.values.get(0, 1) == Float32(9.0), "cached value row is wrong")
    for _i in range(7):
        cache.append(k, v)
    check(cache.is_full(), "cache is not full at max_len")
    check(cache.len == 8, "cache length is not max_len when full")
    cache.clear()
    check(cache.is_empty(), "cache is not empty after clear")
    cache.append(k, v)
    check(cache.len == 1, "cache does not accept appends after clear")


def test_prefill_vs_incremental() raises:
    """Prefill and one-token-at-a-time decode must agree, and both
    must agree with the full recompute. Three ways of running the
    same block, one answer."""
    var tol = Float32(1e-5)
    var blk = CachedBlock(32, 4, 64, 32, 9876)
    var x = Matrix.randn(10, 32, 9877, 0.8)
    var full = blk.forward_full(x)
    check(all_finite(full), "full forward is not finite")
    var prefilled = blk.prefill(x)
    check(blk.cache.len == 10, "prefill did not fill the cache")
    check(prefilled.max_abs_diff(full) <= tol, "prefill disagrees with full forward")
    # Incremental: fresh cache, one decode_step per row.
    blk.clear_cache()
    var incremental = Matrix(10, 32)
    for r in range(10):
        var row = single_row(x, r)
        var out_row = blk.decode_step(row)
        for c in range(32):
            incremental.set(r, c, out_row.get(0, c))
    check(blk.cache.len == 10, "incremental decode did not fill the cache")
    check(incremental.max_abs_diff(full) <= tol, "incremental decode disagrees with full forward")
    check(incremental.max_abs_diff(prefilled) <= tol, "incremental decode disagrees with prefill")
    # Determinism: run the whole thing again from a clear cache.
    var prefilled2 = blk.prefill(x)
    check(prefilled.max_abs_diff(prefilled2) == Float32(0.0), "prefill is not deterministic")


def test_cached_generation() raises:
    """Greedy generation with the cache must produce exactly the
    same tokens as generation by full recomputation at every step,
    and the stream must be deterministic."""
    var d_model = 32
    var vocab = 48
    var blk = CachedBlock(d_model, 4, 64, 64, 13579)
    var emb = Matrix.randn(vocab, d_model, 13580, 0.3)
    var vocab_w = Matrix.randn(d_model, vocab, 13581, Float32(1.0) / sqrt(Float32(d_model)))
    var vocab_b = zero_bias(vocab)

    var prompt = List[Int]()
    prompt.append(4)
    prompt.append(11)
    prompt.append(25)
    prompt.append(2)

    # --- Cached generation: prefill the prompt, then decode. ---
    var prompt_x = Matrix(len(prompt), d_model)
    for t in range(len(prompt)):
        for c in range(d_model):
            prompt_x.set(t, c, emb.get(prompt[t], c))
    var hidden = blk.prefill(prompt_x)
    var prefill_out = hidden.clone()
    var final_w = ones_weight(d_model)
    var cached_tokens = List[Int]()
    for t in range(len(prompt)):
        cached_tokens.append(prompt[t])
    for _step in range(8):
        var last = single_row(hidden, len(cached_tokens) - 1)
        var normed = rmsnorm_rows(last, final_w, Float32(1e-6))
        var logits = matmul_add_bias(normed, vocab_w, vocab_b)
        var nxt = argmax_row(logits, 0)
        cached_tokens.append(nxt)
        var tok_x = Matrix(1, d_model)
        for c in range(d_model):
            tok_x.set(0, c, emb.get(nxt, c))
        var out_row = blk.decode_step(tok_x)
        # Track the new hidden row for the next step's logits.
        var new_hidden = Matrix(len(cached_tokens), d_model)
        for r in range(len(cached_tokens) - 1):
            for c in range(d_model):
                new_hidden.set(r, c, hidden.get(r, c))
        for c in range(d_model):
            new_hidden.set(len(cached_tokens) - 1, c, out_row.get(0, c))
        hidden = new_hidden^
    check(blk.cache.len == len(cached_tokens), "cache length does not match generated length")

    # --- Full-recompute generation: no cache at all. ---
    var full_tokens = List[Int]()
    for t in range(len(prompt)):
        full_tokens.append(prompt[t])
    for _step2 in range(8):
        var seq_x = Matrix(len(full_tokens), d_model)
        for t in range(len(full_tokens)):
            for c in range(d_model):
                seq_x.set(t, c, emb.get(full_tokens[t], c))
        var h_full = blk.forward_full(seq_x)
        var last = single_row(h_full, len(full_tokens) - 1)
        var normed = rmsnorm_rows(last, final_w, Float32(1e-6))
        var logits = matmul_add_bias(normed, vocab_w, vocab_b)
        full_tokens.append(argmax_row(logits, 0))
    check(len(cached_tokens) == len(full_tokens), "generation lengths differ")
    for t in range(len(cached_tokens)):
        check(cached_tokens[t] == full_tokens[t],
              "cached generation diverged at step " + String(t))
    # Determinism of the cached path: a fresh block with the same
    # seed must reproduce the prefill outputs exactly.
    var blk2 = CachedBlock(d_model, 4, 64, 64, 13579)
    var hidden2 = blk2.prefill(prompt_x)
    check(prefill_out.max_abs_diff(hidden2) == Float32(0.0), "cached prefill is not deterministic")


def main() raises:
    print("=== transformer_kv_cache: KV-cache + generation ===")
    print("")
    var suite = TestSuite()
    suite.test[test_cache_append_and_clear]()
    suite.test[test_prefill_vs_incremental]()
    suite.test[test_cached_generation]()
    suite^.run()
    print("  unit tests passed (cache ops, prefill vs incremental,")
    print("  cached vs full generation)")
    print("")

    print("Demonstrating cached generation (prompt 4 11 25 2, 8 steps):")
    var d_model = 32
    var vocab = 48
    var blk = CachedBlock(d_model, 4, 64, 64, 24680)
    var emb = Matrix.randn(vocab, d_model, 24681, 0.3)
    var vocab_w = Matrix.randn(d_model, vocab, 24682, Float32(1.0) / sqrt(Float32(d_model)))
    var vocab_b = zero_bias(vocab)
    var final_w = ones_weight(d_model)
    var prompt = List[Int]()
    prompt.append(4)
    prompt.append(11)
    prompt.append(25)
    prompt.append(2)
    var prompt_x = Matrix(len(prompt), d_model)
    for t in range(len(prompt)):
        for c in range(d_model):
            prompt_x.set(t, c, emb.get(prompt[t], c))
    var hidden = blk.prefill(prompt_x)
    print("  after prefill: cache length = " + String(blk.cache.len))
    var tokens = List[Int]()
    for t in range(len(prompt)):
        tokens.append(prompt[t])
    for _step in range(8):
        var last = single_row(hidden, len(tokens) - 1)
        var normed = rmsnorm_rows(last, final_w, Float32(1e-6))
        var logits = matmul_add_bias(normed, vocab_w, vocab_b)
        var nxt = argmax_row(logits, 0)
        tokens.append(nxt)
        var tok_x = Matrix(1, d_model)
        for c in range(d_model):
            tok_x.set(0, c, emb.get(nxt, c))
        var out_row = blk.decode_step(tok_x)
        var new_hidden = Matrix(len(tokens), d_model)
        for r in range(len(tokens) - 1):
            for c in range(d_model):
                new_hidden.set(r, c, hidden.get(r, c))
        for c in range(d_model):
            new_hidden.set(len(tokens) - 1, c, out_row.get(0, c))
        hidden = new_hidden^
        print(
            "  step "
            + String(_step)
            + ": token "
            + String(nxt)
            + " (cache length "
            + String(blk.cache.len)
            + ")"
        )
    var line = String("  full stream: ")
    for t in range(len(tokens)):
        line += String(tokens[t]) + " "
    print(line)
    check(blk.cache.len == 12, "final cache length is not 12")
    print("")
    print("ALL KV-CACHE CHECKS PASSED")
