# transformer_rope.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# Rotary positional embeddings (RoPE): position as rotation.
#
# What this file demonstrates:
#   * `rope_tables`: precomputed cos/sin tables for positions
#     0..max_seq and pair frequencies theta_i = base^(-2i/d),
#     the standard RoPE frequency schedule (base 10000).
#   * `apply_rope`: rotate every consecutive pair of features
#     (x_2i, x_2i+1) of a row by the angle for that row's position,
#     the scalar reference implementation.
#   * `apply_rope_simd`: the same rotation, eight pairs at a time,
#     gathering the even and odd features into SIMD vectors.
#   * The three properties that make RoPE work, checked directly:
#       - rotation preserves each row's norm exactly;
#       - position 0 is the identity (angle zero);
#       - the dot product of a rotated query and a rotated key
#         depends only on their RELATIVE offset, which is why
#         attention with RoPE generalises to unseen lengths;
#       - rotations compose: rope_p(rope_q(x)) == rope_{p+q}(x).
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`); no
# Python interop, no external packages. The `Matrix` / `Rng` core
# is the same self-contained core used across this sample series,
# repeated in each file so every file runs on its own.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_rope.mojo
# Exit code 0 means every check and every unit test passed.

from std.math import sqrt, log, cos, sin, exp
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
# Checks
# ---------------------------------------------------------------------------

def test_rope_matches_simd() raises:
    var tol = Float32(1e-5)
    var dims = List[Int]()
    dims.append(2)
    dims.append(8)
    dims.append(16)
    dims.append(30)
    dims.append(32)
    dims.append(64)
    for di in range(len(dims)):
        var d = dims[di]
        var tables = RopeTables(64, d, Float32(10000.0))
        var x = Matrix.randn(9, d, UInt64(600 + di), 1.0)
        var scalar = apply_rope(x, tables, 0)
        var fast = apply_rope_simd(x, tables, 0)
        check(scalar.max_abs_diff(fast) <= tol,
              "RoPE SIMD mismatch at d=" + String(d))
        # A non-zero start offset exercises the table indexing.
        var scalar_off = apply_rope(x, tables, 11)
        var fast_off = apply_rope_simd(x, tables, 11)
        check(scalar_off.max_abs_diff(fast_off) <= tol,
              "RoPE SIMD mismatch at d=" + String(d) + " offset 11")
        check(scalar.max_abs_diff(scalar_off) > Float32(1e-3),
              "RoPE offset had no effect at d=" + String(d))


def test_rope_rotation_properties() raises:
    var tol = Float32(1e-5)
    # 2-D case: head_dim 2 has a single pair with theta_0 = 1, so
    # rotating (1, 0) by position p must give (cos p, sin p).
    var tables2 = RopeTables(32, 2, Float32(10000.0))
    var one = Matrix(1, 2)
    one.set(0, 0, 1.0)
    one.set(0, 1, 0.0)
    for p in range(0, 10):
        var rotated = apply_rope(one, tables2, p)
        var expected_c = cos(Float32(p))
        var expected_s = sin(Float32(p))
        assert_almost_equal(rotated.get(0, 0), expected_c, atol=1e-6)
        assert_almost_equal(rotated.get(0, 1), expected_s, atol=1e-6)
    # Position 0 is the identity, for any width: a single row at
    # position 0 must come back unchanged.
    var tables = RopeTables(64, 32, Float32(10000.0))
    var x = Matrix.randn(4, 32, 700, 1.0)
    var x_one = Matrix(1, 32)
    for c in range(32):
        x_one.set(0, c, x.get(0, c))
    var at_zero = apply_rope(x_one, tables, 0)
    check(at_zero.max_abs_diff(x_one) <= Float32(1e-6), "RoPE at position 0 is not the identity")
    # Rotation preserves every row's norm.
    var rotated = apply_rope_simd(x, tables, 5)
    for r in range(4):
        assert_almost_equal(row_norm(rotated, r), row_norm(x, r), atol=1e-5)
    # Composition: rope_p(rope_q(x)) == rope_{p+q}(x), checked on a
    # single row so every application uses one position.
    var step1 = apply_rope(x_one, tables, 3)
    var step2 = apply_rope(step1, tables, 4)
    var direct = apply_rope(x_one, tables, 7)
    check(step2.max_abs_diff(direct) <= tol, "RoPE rotations do not compose")
    # Frequency schedule: theta_0 is 1, later thetas shrink.
    var freqs = rope_freqs(32, Float32(10000.0))
    assert_almost_equal(freqs[0], Float32(1.0), atol=1e-6)
    check(freqs[1] < freqs[0], "RoPE frequencies are not decreasing")
    check(freqs[15] < Float32(0.01), "RoPE slowest frequency is not small")
    # Tables are unit-norm: cos^2 + sin^2 == 1 everywhere.
    for pos in range(0, 64, 7):
        for i in range(16):
            var c = tables.cos_table.get(pos, i)
            var s = tables.sin_table.get(pos, i)
            assert_almost_equal(c * c + s * s, Float32(1.0), atol=1e-6)


def test_rope_relative_property() raises:
    """The dot product of a rotated query and a rotated key depends
    only on their relative offset. This is the property that lets
    RoPE attention generalise to positions never seen in training:
    shift both positions by the same amount and the score is the
    same. We check it for several offsets and shifts."""
    var tol = Float32(1e-4)
    var tables = RopeTables(128, 32, Float32(10000.0))
    var q = Matrix.randn(1, 32, 800, 1.0)
    var k = Matrix.randn(1, 32, 801, 1.0)
    var offsets = List[Int]()
    offsets.append(0)
    offsets.append(1)
    offsets.append(3)
    offsets.append(9)
    offsets.append(17)
    var shifts = List[Int]()
    shifts.append(0)
    shifts.append(2)
    shifts.append(5)
    shifts.append(11)
    for oi in range(len(offsets)):
        var off = offsets[oi]
        var q0 = apply_rope(q, tables, 4)
        var k0 = apply_rope(k, tables, 4 + off)
        var base_dot = row_dot(q0, 0, k0, 0)
        for si in range(len(shifts)):
            var shift = shifts[si]
            var qs = apply_rope(q, tables, 4 + shift)
            var ks = apply_rope(k, tables, 4 + off + shift)
            var shifted_dot = row_dot(qs, 0, ks, 0)
            check(
                shifted_dot > base_dot - tol and shifted_dot < base_dot + tol,
                "RoPE dot product depends on absolute position, not just offset",
            )
    # ...while the ABSOLUTE score does change with offset, so the
    # check above is not vacuous: different offsets give different
    # dots for the same query.
    var q0 = apply_rope(q, tables, 4)
    var k_same = apply_rope(k, tables, 4)
    var k_far = apply_rope(k, tables, 20)
    var d_same = row_dot(q0, 0, k_same, 0)
    var d_far = row_dot(q0, 0, k_far, 0)
    check(d_same != d_far, "RoPE scores do not vary with offset at all")


def main() raises:
    print("=== transformer_rope: rotary positional embeddings ===")
    print("")
    var suite = TestSuite()
    suite.test[test_rope_matches_simd]()
    suite.test[test_rope_rotation_properties]()
    suite.test[test_rope_relative_property]()
    suite^.run()
    print("  unit tests passed (SIMD match, rotation properties, relative dot)")
    print("")

    print("Inspecting one small run (head_dim=8, positions 0..3):")
    var tables = RopeTables(16, 8, Float32(10000.0))
    var x = Matrix(4, 8)
    for r in range(4):
        for c in range(8):
            x.set(r, c, Float32(1.0) if c == 0 else Float32(0.0))
    print("  input rows are all (1, 0, 0, ...):")
    x.print_block(4, 8)
    var rotated = apply_rope_simd(x, tables, 0)
    print("  after RoPE, pair 0 rotates by pos * 1.0, pair 1 by pos * 0.1:")
    rotated.print_block(4, 8)
    print("  pair-0 angles: row p should be (cos p, sin p):")
    for r in range(4):
        print(
            "    pos "
            + String(r)
            + ": ("
            + String(rotated.get(r, 0))
            + ", "
            + String(rotated.get(r, 1))
            + ")  expected ("
            + String(cos(Float32(r)))
            + ", "
            + String(sin(Float32(r)))
            + ")"
        )
    var rotated2 = apply_rope_simd(x, tables, 0)
    check(rotated.max_abs_diff(rotated2) == Float32(0.0), "RoPE is not deterministic")
    print("  determinism: second run is bit-identical")
    print("")
    print("ALL ROPE CHECKS PASSED")
