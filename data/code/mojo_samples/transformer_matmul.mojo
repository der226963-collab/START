# transformer_matmul.mojo
#
# Component 1 of the START project's Mojo transformer samples.
#
# SIMD-vectorised, tiled and naive-scalar matrix multiplication.
#
# What this file demonstrates:
#   * A small row-major `Matrix` type (Float32, List-backed) with the
#     helpers a transformer implementation needs: fill, random normal
#     initialisation, identity, transpose, norms and comparison.
#   * Three matmul kernels for C = A @ B:
#       - `matmul_naive`  : plain scalar triple loop (the reference).
#       - `matmul_simd`   : SIMD over the column dimension, 8 floats
#                           at a time, with a scalar tail.
#       - `matmul_tiled`  : cache-blocked (i/j/k tiles) on top of the
#                           same SIMD inner kernel.
#   * Every fast kernel is checked against the naive reference on
#     several shapes, including odd (non-multiple-of-8) shapes, plus
#     hand-computed 2x2 and identity cases.
#
# All code here is original, written for this project. It uses only
# the Mojo 1.2.0 standard library (`std.math`, `std.testing`,
# `std.time`); no Python interop, no external packages.
#
# Mojo 1.2.0 notes (verified against this toolchain):
#   * `def` replaces the old `fn` keyword.
#   * stdlib imports carry the `std.` prefix, e.g.
#     `from std.math import sqrt, log, cos`.
#   * Structs holding a `List` are move-only: return them with `^`,
#     as in `return c^`.
#   * `SIMD[DType.float32, 8]` is the natural vector width on the
#     AVX2 CPUs this code targets; the tail loop handles the rest.
#
# Run with:
#   cd ~/workspace/mojo-work && pixi run mojo \
#       ~/workspace/ai-starter/data/code/mojo_samples/transformer_matmul.mojo
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
# Correctness checks
# ---------------------------------------------------------------------------

def check_kernel_pair(a: Matrix, b: Matrix, tol: Float32, label: String) raises:
    """Check SIMD and tiled kernels against the naive reference."""
    var reference = matmul_naive(a, b)
    var fast = matmul_simd(a, b)
    var d_simd = reference.max_abs_diff(fast)
    check(
        d_simd <= tol,
        "matmul_simd mismatch on " + label + ": max diff " + String(d_simd),
    )
    var tiled = matmul_tiled(a, b, 32, 32, 16)
    var d_tiled = reference.max_abs_diff(tiled)
    check(
        d_tiled <= tol,
        "matmul_tiled mismatch on " + label + ": max diff " + String(d_tiled),
    )
    var tiled_small = matmul_tiled(a, b, 7, 5, 3)
    var d_tiled_small = reference.max_abs_diff(tiled_small)
    check(
        d_tiled_small <= tol,
        "matmul_tiled (odd tiles) mismatch on "
        + label
        + ": max diff "
        + String(d_tiled_small),
    )
    print(
        "  OK "
        + label
        + "  simd diff="
        + String(d_simd)
        + "  tiled diff="
        + String(d_tiled)
        + "  tiled(7,5,3) diff="
        + String(d_tiled_small)
    )


def test_known_2x2() raises:
    var a = Matrix(2, 2)
    a.set(0, 0, 1.0)
    a.set(0, 1, 2.0)
    a.set(1, 0, 3.0)
    a.set(1, 1, 4.0)
    var b = Matrix(2, 2)
    b.set(0, 0, 5.0)
    b.set(0, 1, 6.0)
    b.set(1, 0, 7.0)
    b.set(1, 1, 8.0)
    # Hand-computed: [[1*5+2*7, 1*6+2*8], [3*5+4*7, 3*6+4*8]]
    #              = [[19, 22], [43, 50]]
    var expected = Matrix(2, 2)
    expected.set(0, 0, 19.0)
    expected.set(0, 1, 22.0)
    expected.set(1, 0, 43.0)
    expected.set(1, 1, 50.0)
    var r_naive = matmul_naive(a, b)
    var r_simd = matmul_simd(a, b)
    var r_tiled = matmul_tiled(a, b, 1, 1, 1)
    check(r_naive.approx_equal(expected, Float32(1e-6)), "naive 2x2 mismatch")
    check(r_simd.approx_equal(expected, Float32(1e-6)), "simd 2x2 mismatch")
    check(r_tiled.approx_equal(expected, Float32(1e-6)), "tiled 2x2 mismatch")
    # Transpose round-trip: (A^T)^T == A, and A @ I == A.
    var at = a.transpose()
    var att = at.transpose()
    check(att.approx_equal(a, Float32(1e-6)), "double transpose mismatch")
    var ident = Matrix.identity(2)
    var ai = matmul_simd(a, ident)
    check(ai.approx_equal(a, Float32(1e-6)), "A @ I mismatch")
    var ia = matmul_tiled(ident, a, 2, 2, 2)
    check(ia.approx_equal(a, Float32(1e-6)), "I @ A mismatch")
    # Zero matrix absorbs everything.
    var z = Matrix.zeros(2, 2)
    var az = matmul_naive(a, z)
    check(az.max_abs() == Float32(0.0), "A @ 0 is not zero")


def test_odd_shapes() raises:
    var tol = Float32(1e-3)
    var a = Matrix.randn(33, 17, 7, 0.5)
    var b = Matrix.randn(17, 29, 8, 0.5)
    var reference = matmul_naive(a, b)
    var fast = matmul_simd(a, b)
    check(reference.max_abs_diff(fast) <= tol, "simd odd-shape mismatch")
    var tiled = matmul_tiled(a, b, 16, 16, 8)
    check(reference.max_abs_diff(tiled) <= tol, "tiled odd-shape mismatch")
    # Vector shapes: 1xK times Kx1 is a dot product; Kx1 times 1xK
    # is an outer product. Both stress the tail loops.
    var row = Matrix.randn(1, 37, 9, 1.0)
    var col = Matrix.randn(37, 1, 10, 1.0)
    var dot = matmul_simd(row, col)
    var dot_ref = matmul_naive(row, col)
    check(dot.max_abs_diff(dot_ref) <= tol, "dot-product shape mismatch")
    assert_equal(dot.rows, 1)
    assert_equal(dot.cols, 1)
    var outer = matmul_tiled(col, row, 8, 8, 8)
    var outer_ref = matmul_naive(col, row)
    check(outer.max_abs_diff(outer_ref) <= tol, "outer-product shape mismatch")
    assert_equal(outer.rows, 37)
    assert_equal(outer.cols, 37)


def test_bias_and_norms() raises:
    var a = Matrix.randn(8, 12, 11, 0.5)
    var b = Matrix.randn(12, 5, 12, 0.5)
    var bias = List[Float32](length=5, fill=0.0)
    bias[0] = 0.5
    bias[1] = -1.25
    bias[2] = 2.0
    bias[3] = 0.0
    bias[4] = -0.75
    var fused = matmul_add_bias(a, b, bias)
    var plain = matmul_naive(a, b)
    for i in range(plain.rows):
        for j in range(plain.cols):
            plain.set(i, j, plain.get(i, j) + bias[j])
    check(fused.max_abs_diff(plain) <= Float32(1e-4), "fused bias mismatch")
    # Norms behave: ||A||_F of a 2x2 ones matrix is 2, max-abs is 1.
    var ones = Matrix(2, 2)
    ones.fill(1.0)
    assert_almost_equal(ones.frobenius_norm(), Float32(2.0), atol=1e-6)
    assert_almost_equal(ones.max_abs(), Float32(1.0), atol=1e-6)


def main() raises:
    print("=== transformer_matmul: naive vs SIMD vs tiled ===")
    print("")

    print("Known 2x2 hand-computed case, identity and zero checks:")
    var suite = TestSuite()
    suite.test[test_known_2x2]()
    suite.test[test_odd_shapes]()
    suite.test[test_bias_and_norms]()
    suite^.run()
    print("  unit tests passed (2x2, odd shapes, bias, norms)")
    print("")

    print("Kernel-vs-reference checks (tolerance 1e-3):")
    var tol = Float32(1e-3)
    # (m, k, n) triples, flattened.
    var spec = List[Int]()
    spec.append(1)
    spec.append(1)
    spec.append(1)
    spec.append(3)
    spec.append(5)
    spec.append(2)
    spec.append(16)
    spec.append(16)
    spec.append(16)
    spec.append(33)
    spec.append(17)
    spec.append(29)
    spec.append(64)
    spec.append(64)
    spec.append(64)
    spec.append(128)
    spec.append(96)
    spec.append(64)
    spec.append(96)
    spec.append(128)
    spec.append(96)
    spec.append(7)
    spec.append(13)
    spec.append(11)
    var s = 0
    var seed_base = UInt64(100)
    while s + 2 < len(spec):
        var m = spec[s]
        var k = spec[s + 1]
        var n = spec[s + 2]
        var a = Matrix.randn(m, k, seed_base + UInt64(s), 0.5)
        var b = Matrix.randn(k, n, seed_base + UInt64(s) + UInt64(50), 0.5)
        var label = String(m) + "x" + String(k) + " @ " + String(k) + "x" + String(n)
        check_kernel_pair(a, b, tol, label)
        s += 3
    print("")

    print("Spot-check of values (16x16, first 3x3 block of A @ B):")
    var a = Matrix.arange(16, 16, 0.01, 0.01)
    var b = Matrix.arange(16, 16, 0.02, -0.005)
    var c = matmul_simd(a, b)
    c.print_block(3, 3)
    var c_reference = matmul_naive(a, b)
    check(c.max_abs_diff(c_reference) <= tol, "spot-check mismatch")
    print("  spot-check matches naive reference")
    print("")
    print("ALL MATMUL CHECKS PASSED")
