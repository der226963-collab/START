#!/usr/bin/env python3
"""
reversing_disasm.py -- A disassembly reporter built on the dis module.

Given a function, method, class, module, or code object, this module
produces a readable per-instruction listing (offset, opcode, argument,
argument value, source line), plus the analysis a reverse engineer
actually wants on top of the raw listing:

  * opcode histograms and per-function bytecode statistics,
  * a source-line interleaved listing (source line, then its instructions),
  * a stack-depth simulation that tracks the deepest evaluation stack,
  * jump-target resolution (which instructions are jump targets, and
    which instructions jump where),
  * a search API: find every instruction matching an opcode, a name, or
    a constant, with its source line,
  * a side-by-side diff of two functions' instruction streams.

Only the standard library is used.  The file is self-contained; its
__main__ demo disassembles real functions from this file and from the
START repo (mini_ai modules) and asserts concrete facts about them.

Usage:
    python3 reversing_disasm.py                     # run the demo
    python3 reversing_disasm.py path/to/file.py     # disassemble a module
    python3 reversing_disasm.py path/to/file.py -f name
"""

from __future__ import annotations

import dis
import inspect
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# Sentinel for "no constant filter" in find_instructions.
_MISSING: Any = object()

# ---------------------------------------------------------------------------
# Core: one instruction, fully described
# ---------------------------------------------------------------------------


class Instr:
    """One bytecode instruction, enriched with source-line context."""

    __slots__ = ("offset", "opname", "opcode", "arg", "argval", "argrepr",
                 "starts_line", "is_jump_target", "positions")

    def __init__(self, raw: dis.Instruction) -> None:
        self.offset = raw.offset
        self.opname = raw.opname
        self.opcode = raw.opcode
        self.arg = raw.arg
        self.argval = raw.argval
        self.argrepr = raw.argrepr
        self.starts_line = raw.starts_line
        self.is_jump_target = raw.is_jump_target
        self.positions = raw.positions

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Instr(%d %s %s)" % (self.offset, self.opname, self.argrepr)

    def short(self) -> str:
        """One-line rendering, in the style of dis.dis output."""
        target = ">> " if self.is_jump_target else "   "
        line = "%4d " % self.starts_line if self.starts_line is not None else "     "
        return "%s%s %4d %-22s %s" % (
            target, line, self.offset, self.opname,
            self.argrepr if self.arg is not None else "")


def get_instructions(obj: Any) -> List[Instr]:
    """Return the enriched instruction list for a function/code object."""
    if isinstance(obj, types.CodeType):
        code = obj
    elif isinstance(obj, (types.FunctionType, types.MethodType)):
        code = obj.__code__
    elif isinstance(obj, type):
        # A class: disassemble its methods one at a time via walk below.
        raise TypeError("pass a function or code object, not a class; "
                        "use disassemble_module for classes")
    else:
        raise TypeError("cannot disassemble %r" % type(obj).__name__)
    return [Instr(raw) for raw in dis.get_instructions(code)]


# ---------------------------------------------------------------------------
# Statistics and analysis over an instruction list
# ---------------------------------------------------------------------------

def opcode_histogram(instructions: Iterable[Instr]) -> Counter:
    return Counter(ins.opname for ins in instructions)


def jump_map(instructions: List[Instr]) -> Dict[int, List[int]]:
    """Map each jump-target offset to the offsets of instructions that
    jump to it."""
    targets: Dict[int, List[int]] = {}
    for ins in instructions:
        if "JUMP" in ins.opname or ins.opname in (
                "POP_JUMP_IF_TRUE", "POP_JUMP_IF_FALSE",
                "JUMP_IF_TRUE_OR_POP", "JUMP_IF_FALSE_OR_POP",
                "FOR_ITER", "SETUP_FINALLY"):
            if isinstance(ins.argval, int):
                targets.setdefault(ins.argval, []).append(ins.offset)
    return targets


def jump_targets(instructions: List[Instr]) -> List[int]:
    return sorted({ins.offset for ins in instructions if ins.is_jump_target})


def max_stack_depth(instructions: List[Instr]) -> int:
    """Simulate the evaluation stack linearly and report the deepest
    point reached.  This is an approximation: it follows the instruction
    order, not the control-flow graph, so it is an upper bound only when
    a loop body pushes more than it pops.  For straight-line code it is
    exact; see reversing_flow.py for the CFG-based version."""
    depth = 0
    deepest = 0
    for ins in instructions:
        try:
            effect = dis.stack_effect(ins.opcode, ins.arg)
        except (ValueError, TypeError):
            effect = 0
        depth += effect
        deepest = max(deepest, depth)
        # A jump target may reset the stack in real execution; the linear
        # simulation keeps going, which is why this is an upper bound.
        if depth < 0:
            depth = 0
    return deepest


def line_spans(instructions: List[Instr]) -> Dict[int, List[Instr]]:
    """Group instructions by the source line that starts them."""
    spans: Dict[int, List[Instr]] = {}
    current: Optional[int] = None
    for ins in instructions:
        if ins.starts_line is not None:
            current = ins.starts_line
        if current is not None:
            spans.setdefault(current, []).append(ins)
    return spans


def _call_sites(instructions: List[Instr]
                ) -> List[Tuple[int, str, Optional[int]]]:
    """Origin-tracking stack simulation: for every CALL instruction,
    return (index, dotted callee name, source line).

    The stack holds the *origin* of each value: LOAD_GLOBAL os pushes
    "os", LOAD_ATTR system turns the top origin into "os.system".
    A CALL with n arguments finds its callable at stack position
    -(n+1), because CPython 3.12 lays the call out as
    [NULL, callable, arg1, ..., argn] (the NULL comes from LOAD_GLOBAL
    with its null-bit set, from PUSH_NULL, or from LOAD_ATTR with its
    null-bit set).  The simulation is linear: at any jump target the
    stack is reset, so calls that span a branch are missed rather than
    misattributed.
    """
    stack: List[str] = []
    out: List[Tuple[int, str, Optional[int]]] = []
    current_line: Optional[int] = None
    for i, ins in enumerate(instructions):
        if getattr(ins, "starts_line", None) is not None:
            # CALL itself often carries no line; remember the line of
            # the statement it belongs to.
            current_line = ins.starts_line
        if ins.is_jump_target and i != 0:
            stack = []
        op = ins.opname
        arg = ins.arg if ins.arg is not None else 0
        if op == "PUSH_NULL":
            stack.append("<null>")
            continue
        if op == "LOAD_GLOBAL":
            if arg & 1:
                stack.append("<null>")
            stack.append(str(ins.argval))
            continue
        if op in ("LOAD_FAST", "LOAD_DEREF", "LOAD_NAME", "LOAD_CLOSURE"):
            stack.append(str(ins.argval))
            continue
        if op == "LOAD_CONST":
            stack.append("<const>")
            continue
        if op in ("LOAD_ATTR", "LOAD_METHOD"):
            base = stack.pop() if stack else "<obj>"
            if arg & 1:
                stack.append("<null>")
            stack.append("%s.%s" % (base, ins.argval))
            continue
        if op == "LOAD_SUPER_ATTR":
            base = "<super>"
            if stack:
                stack.pop()
            if stack:
                base = stack.pop()
            if arg & 1:
                stack.append("<null>")
            stack.append("%s.%s" % (base, ins.argval))
            continue
        if op == "COPY":
            if stack and 1 <= arg <= len(stack):
                stack.append(stack[-arg])
            else:
                stack.append("<expr>")
            continue
        if op == "SWAP":
            if len(stack) >= arg and arg >= 2:
                stack[-1], stack[-arg] = stack[-arg], stack[-1]
            continue
        if op.startswith("CALL"):
            if op == "CALL_FUNCTION_EX":
                popped = 4 if (arg & 1) else 3
                callee = stack[-3] if len(stack) >= 3 else None
                if callee is not None:
                    out.append((i, callee, current_line))
                stack = stack[:-popped] if popped <= len(stack) else []
                stack.append("<call>")
                continue
            argc = arg
            callee = None
            if len(stack) >= argc + 1:
                callee = stack[-argc - 1]
            if callee is not None and callee not in ("<null>", "<const>",
                                                     "<expr>", "<call>"):
                out.append((i, callee, current_line))
            popped = argc + 2
            stack = stack[:-popped] if popped <= len(stack) else []
            stack.append("<call>")
            continue
        try:
            effect = dis.stack_effect(ins.opcode, ins.arg)
        except (ValueError, TypeError):
            stack = []
            continue
        if effect < 0:
            pops = -effect
            stack = stack[:-pops] if pops <= len(stack) else []
        elif effect > 0:
            stack.extend("<expr>" for _ in range(effect))
    return out


def find_instructions(instructions: List[Instr], *,
                      opname: Optional[str] = None,
                      name: Optional[str] = None,
                      constant: Any = _MISSING) -> List[Instr]:
    """Find instructions matching an opcode name, a LOAD name, or a
    constant value.  Pass constant=_MISSING to skip the constant test;
    any other value (including None) is matched exactly."""
    out = []
    for ins in instructions:
        if opname is not None and ins.opname != opname:
            continue
        if name is not None and ins.argval != name:
            continue
        if constant is not _MISSING and ins.argval != constant:
            continue
        out.append(ins)
    return out


class FunctionReport:
    """Everything the reporter knows about one function."""

    def __init__(self, obj: Any, label: Optional[str] = None) -> None:
        if isinstance(obj, types.CodeType):
            self.code = obj
            self.name = obj.co_qualname
        else:
            self.code = obj.__code__
            self.name = label or getattr(obj, "__qualname__", str(obj))
        self.instructions = get_instructions(self.code)
        self.histogram = opcode_histogram(self.instructions)
        self.jumps = jump_map(self.instructions)
        self.targets = jump_targets(self.instructions)
        self.spans = line_spans(self.instructions)
        self.max_depth = max_stack_depth(self.instructions)

    @property
    def instruction_count(self) -> int:
        return len(self.instructions)

    @property
    def byte_size(self) -> int:
        return len(self.code.co_code)

    @property
    def distinct_opcodes(self) -> int:
        return len(self.histogram)

    @property
    def first_line(self) -> int:
        return self.code.co_firstlineno

    @property
    def source_lines_covered(self) -> int:
        return len(self.spans)

    def most_common_opcodes(self, n: int = 5) -> List[Tuple[str, int]]:
        return self.histogram.most_common(n)

    def loads_of(self, name: str) -> List[Instr]:
        return find_instructions(self.instructions, name=name)

    def calls(self) -> List[Instr]:
        """Every CALL / CALL_FUNCTION_EX instruction."""
        return [ins for ins in self.instructions
                if ins.opname.startswith("CALL")]

    def called_names(self) -> List[str]:
        """Names of the callables this function calls, via an
        origin-tracking stack simulation (see _call_sites): the stack
        holds the origin of each value, so a CALL finds its callable
        at stack position -(argc+1), below its arguments.  This is
        exact for direct calls like os.system(x) or math.sqrt(16);
        calls through computed values are skipped, not guessed."""
        return [name for _, name, _ in _call_sites(self.instructions)]

    def listing(self) -> str:
        lines = ["%s  (%d instructions, %d bytes, first line %d)"
                 % (self.name, self.instruction_count, self.byte_size,
                    self.first_line)]
        for ins in self.instructions:
            lines.append(ins.short())
        return "\n".join(lines)

    def interleaved_listing(self, source_lines: List[str]) -> str:
        """Source lines with the instructions that implement them."""
        out = ["%s  (source-interleaved)" % self.name]
        for lineno in sorted(self.spans):
            text = ""
            if 1 <= lineno <= len(source_lines):
                text = source_lines[lineno - 1].rstrip()
            out.append("  %4d  %s" % (lineno, text))
            for ins in self.spans[lineno]:
                out.append("        " + ins.short())
        return "\n".join(out)

    def summary(self) -> str:
        top = ", ".join("%s x%d" % (op, n)
                        for op, n in self.most_common_opcodes())
        return (
            "%s: %d instructions, %d distinct opcodes, %d jump targets, "
            "max stack depth %d, %d source lines covered\n"
            "  most common: %s\n"
            "  calls: %s"
            % (self.name, self.instruction_count, self.distinct_opcodes,
               len(self.targets), self.max_depth,
               self.source_lines_covered, top,
               ", ".join(self.called_names()) or "none"))


# ---------------------------------------------------------------------------
# Module-level disassembly
# ---------------------------------------------------------------------------

def walk_code_objects(code: types.CodeType):
    """Yield a code object and every nested code object, depth-first."""
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from walk_code_objects(const)


def disassemble_module(path: str | Path) -> Dict[str, FunctionReport]:
    """Disassemble every code object in a .py source file."""
    path = Path(path)
    code = compile(path.read_text(), str(path), "exec")
    reports: Dict[str, FunctionReport] = {}
    for obj in walk_code_objects(code):
        reports[obj.co_qualname] = FunctionReport(obj)
    return reports


def module_summary(path: str | Path) -> str:
    reports = disassemble_module(path)
    total = sum(r.instruction_count for r in reports.values())
    all_hist: Counter = Counter()
    for r in reports.values():
        all_hist.update(r.histogram)
    lines = ["== %s ==" % Path(path).name,
             "code objects: %d, total instructions: %d"
             % (len(reports), total),
             "module opcode histogram (top 10):"]
    for op, n in all_hist.most_common(10):
        lines.append("  %-24s %d" % (op, n))
    lines.append("")
    for name in sorted(reports):
        lines.append("  " + reports[name].summary().replace("\n", "\n  "))
    return "\n".join(lines)


def opcode_bigrams(instructions: List[Instr]) -> Counter:
    """Counts of adjacent opcode pairs: the idioms a function uses,
    e.g. LOAD_FAST -> BINARY_OP, or COMPARE_OP -> POP_JUMP_IF_FALSE."""
    return Counter(
        (a.opname, b.opname)
        for a, b in zip(instructions, instructions[1:]))


def detect_constructs(report: "FunctionReport") -> Set[str]:
    """Name the source-level constructs a function's bytecode shows:
    comprehensions, with-statements, f-strings, exception handling,
    async/await, decorators (via MAKE_FUNCTION with a closure), and
    attribute assignment.  Useful for a quick read of what a function
    does without reading its source."""
    ops = set(report.histogram)
    found: Set[str] = set()
    if ops & {"LIST_APPEND", "SET_ADD", "MAP_ADD"}:
        found.add("comprehension")
    if ops & {"SETUP_WITH", "BEFORE_WITH"}:
        found.add("with-statement")
    if "FORMAT_VALUE" in ops or "FORMAT" in ops:
        found.add("f-string")
    if ops & {"SETUP_FINALLY", "SETUP_CLEANUP", "PUSH_EXC_INFO",
              "CHECK_EXC_MATCH", "RERAISE"}:
        found.add("exception-handling")
    if ops & {"GET_AWAITABLE", "GET_AITER", "GET_ANEXT", "SEND"}:
        found.add("async")
    if "MAKE_FUNCTION" in ops:
        found.add("nested-function-or-decorator")
    if "LOAD_ASSERTION_ERROR" in ops:
        found.add("assert")
    if ops & {"BUILD_LIST", "BUILD_MAP", "BUILD_SET", "BUILD_TUPLE",
              "BUILD_SLICE", "BUILD_STRING"}:
        found.add("literal-construction")
    if ops & {"IMPORT_NAME", "IMPORT_FROM"}:
        found.add("import")
    if "YIELD_VALUE" in ops:
        found.add("generator")
    return found


def line_density(report: "FunctionReport") -> List[Tuple[int, int]]:
    """Source lines ranked by how many instructions implement them:
    the densest lines are usually the most complex expressions."""
    rows = [(lineno, len(insns))
            for lineno, insns in report.spans.items()]
    rows.sort(key=lambda row: -row[1])
    return rows


def diff_functions(func_a: Any, func_b: Any) -> Dict[str, Any]:
    """Compare two functions' instruction streams opcode by opcode.
    Instructions are compared as (opname, argrepr) pairs, because in
    CPython 3.11+ the operator of BINARY_OP lives in the argument, not
    in a distinct opcode."""
    a = get_instructions(func_a)
    b = get_instructions(func_b)
    ops_a = [(i.opname, i.argrepr) for i in a]
    ops_b = [(i.opname, i.argrepr) for i in b]
    common_prefix = 0
    for x, y in zip(ops_a, ops_b):
        if x != y:
            break
        common_prefix += 1
    first_diff: Optional[Tuple[int, Optional[str], Optional[str]]] = None
    if common_prefix < min(len(ops_a), len(ops_b)):
        first_diff = (common_prefix, ops_a[common_prefix],
                      ops_b[common_prefix])
    return {
        "len_a": len(ops_a),
        "len_b": len(ops_b),
        "common_prefix": common_prefix,
        "first_diff": first_diff,
        "only_in_a": sorted(set(ops_a) - set(ops_b)),
        "only_in_b": sorted(set(ops_b) - set(ops_a)),
        "identical": ops_a == ops_b,
    }


# ---------------------------------------------------------------------------
# Demo targets (real code, analysed by the demo below)
# ---------------------------------------------------------------------------

def sample_add(a, b):
    """Add two numbers."""
    return a + b


def sample_loop(n):
    """Sum squares with a loop and a conditional."""
    total = 0
    for i in range(n):
        if i % 2 == 0:
            total += i * i
        else:
            total += 1
    return total


def sample_conditional(x):
    if x < 0:
        return "negative"
    elif x == 0:
        return "zero"
    return "positive"


def sample_try(x):
    try:
        return 10 // x
    except ZeroDivisionError:
        return None
    finally:
        pass


def sample_callers():
    import math
    return math.sqrt(16) + len("abcd")


def sample_comprehension(items):
    """A list comprehension, a dict comprehension, and an f-string."""
    squares = [x * x for x in items if x > 0]
    lookup = {x: x * x for x in items}
    return "%s -> %s" % (squares, lookup) + f" ({len(squares)} items)"


def sample_with(path):
    """A with-statement plus an assert."""
    with open(path) as handle:
        text = handle.read()
    assert text, "file was empty"
    return text


async def sample_async(items):
    """An async function, so GET_AWAITABLE appears in its bytecode."""
    total = 0
    for item in items:
        total += await item
    return total


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------

def _run_demo() -> int:
    failures: List[str] = []

    def check(condition: bool, message: str) -> None:
        print(("  ok  " if condition else " FAIL ") + message)
        if not condition:
            failures.append(message)

    print("== reversing_disasm demo ==")

    # --- basic listing of a tiny function --------------------------------
    rep = FunctionReport(sample_add)
    print(rep.listing())
    check(rep.instruction_count == 5,
          "sample_add has exactly 5 instructions (got %d)" % rep.instruction_count)
    check([i.opname for i in rep.instructions]
          == ["RESUME", "LOAD_FAST", "LOAD_FAST", "BINARY_OP", "RETURN_VALUE"],
          "sample_add opcode stream is RESUME, LOAD_FAST, LOAD_FAST, "
          "BINARY_OP, RETURN_VALUE")
    check(rep.called_names() == [], "sample_add calls nothing")
    check(rep.max_depth == 2, "sample_add max stack depth is 2")

    # --- constants and names are recoverable from the listing ------------
    loads = find_instructions(rep.instructions, opname="LOAD_FAST")
    check([i.argval for i in loads] == ["a", "b"],
          "LOAD_FAST args are a, b")

    # --- loop function: jumps, targets, histogram ------------------------
    loop = FunctionReport(sample_loop)
    print()
    print(loop.summary())
    check(len(loop.targets) >= 2,
          "sample_loop has >= 2 jump targets (got %d: %s)"
          % (len(loop.targets), loop.targets))
    check("FOR_ITER" in loop.histogram,
          "sample_loop uses FOR_ITER")
    check("POP_JUMP_IF_FALSE" in loop.histogram or
          "POP_JUMP_IF_TRUE" in loop.histogram,
          "sample_loop has a conditional jump")
    check(loop.source_lines_covered >= 5,
          "sample_loop covers >= 5 source lines (got %d)"
          % loop.source_lines_covered)
    check(loop.max_depth >= 2, "sample_loop stack depth >= 2")

    # --- conditional: three return paths, jump map is non-empty ----------
    cond = FunctionReport(sample_conditional)
    check(len(cond.jumps) >= 2,
          "sample_conditional has >= 2 jump sites (got %d)"
          % len(cond.jumps))
    rets = [i for i in cond.instructions
            if i.opname in ("RETURN_VALUE", "RETURN_CONST")]
    check(len(rets) == 3,
          "sample_conditional has 3 returns (RETURN_VALUE/RETURN_CONST)")
    check(find_instructions(cond.instructions, constant="negative"),
          "constant 'negative' found in sample_conditional")

    # --- try/except: SETUP_FINALLY / exception handling opcodes ----------
    tr = FunctionReport(sample_try)
    check(any(op in tr.histogram for op in
              ("SETUP_FINALLY", "SETUP_CLEANUP", "PUSH_EXC_INFO",
               "CHECK_EXC_MATCH")),
          "sample_try has exception-handling opcodes: %s"
          % [op for op in tr.histogram if "EXC" in op or "SETUP" in op])

    # --- calls: the callee-name heuristic --------------------------------
    callers = FunctionReport(sample_callers)
    check("math.sqrt" in callers.called_names(),
          "sample_callers calls math.sqrt (found %s)" % callers.called_names())
    check("len" in callers.called_names(),
          "sample_callers calls len")

    # --- diff: identical functions, and a changed one --------------------
    def twin_add(a, b):
        return a + b

    def other_add(a, b):
        return a - b

    d_same = diff_functions(sample_add, twin_add)
    check(d_same["identical"], "identical functions diff as identical")
    d_diff = diff_functions(sample_add, other_add)
    check(not d_diff["identical"],
          "a + b vs a - b diff as different")
    check(d_diff["common_prefix"] == 3,
          "a + b vs a - b share a 3-instruction prefix (RESUME + two LOAD_FASTs)")

    # --- interleaved source listing --------------------------------------
    # Pass the whole file's lines: spans are keyed by absolute line number.
    src_lines = Path(__file__).read_text().splitlines()
    inter = loop.interleaved_listing(src_lines)
    check("for i in range(n):" in inter,
          "interleaved listing contains the for line")
    check("total += i * i" in inter,
          "interleaved listing contains the total += i * i line")

    # --- real repo code: disassemble this file's own module --------------
    here = Path(__file__)
    reports = disassemble_module(here)
    check(len(reports) >= 10,
          "this file disassembles into >= 10 code objects (got %d)"
          % len(reports))
    check("sample_loop" in reports, "sample_loop found in module walk")
    check("FunctionReport.listing" in reports,
          "method FunctionReport.listing found in module walk")
    total = sum(r.instruction_count for r in reports.values())
    check(total > 500,
          "this file totals > 500 instructions (got %d)" % total)

    # --- real repo code: a mini_ai module --------------------------------
    repo = Path(__file__).resolve().parents[2]
    planning = repo / "mini_ai" / "planning" / "core.py"
    if planning.exists():
        preports = disassemble_module(planning)
        check(len(preports) > 0, "mini_ai/planning/core.py disassembles")
        names = sorted(preports)
        print("  mini_ai/planning/core.py code objects: %s" % names)
        check(any("plan" in n.lower() for n in names),
              "core.py contains a plan-related code object")
        ptotal = sum(r.instruction_count for r in preports.values())
        print("  mini_ai/planning/core.py total instructions: %d" % ptotal)
        check(ptotal > 50, "core.py has > 50 instructions")
        # Every instruction offset must be even and strictly increasing.
        for name, r in preports.items():
            offs = [i.offset for i in r.instructions]
            check(offs == sorted(offs) and all(o % 2 == 0 for o in offs),
                  "offsets in %s are increasing and even" % name)
    else:
        print("  (mini_ai/planning/core.py not found; repo check skipped)")

    # --- construct detection ------------------------------------------------
    comp = FunctionReport(sample_comprehension)
    constructs = detect_constructs(comp)
    check("comprehension" in constructs,
          "comprehension detected in sample_comprehension")
    check("f-string" in constructs,
          "f-string detected in sample_comprehension")
    with_rep = FunctionReport(sample_with)
    check("with-statement" in detect_constructs(with_rep),
          "with-statement detected in sample_with")
    check("assert" in detect_constructs(with_rep),
          "assert detected in sample_with")
    check("import" not in detect_constructs(with_rep),
          "sample_with has no import (open is a builtin, not an import)")
    async_rep = FunctionReport(sample_async)
    check("async" in detect_constructs(async_rep),
          "async detected in sample_async")
    check("generator" not in detect_constructs(FunctionReport(sample_loop)),
          "sample_loop is not a generator")

    # --- bigrams and line density -------------------------------------------
    bigrams = opcode_bigrams(loop.instructions)
    check(("LOAD_FAST", "LOAD_FAST") in bigrams
          or ("LOAD_FAST", "BINARY_OP") in bigrams,
          "sample_loop has LOAD_FAST bigrams")
    check(sum(bigrams.values()) == loop.instruction_count - 1,
          "bigram count is instruction count - 1")
    density = line_density(loop)
    check(density[0][1] >= 2,
          "densest line of sample_loop has >= 2 instructions")
    check(all(n >= 1 for _, n in density),
          "every covered line has >= 1 instruction")

    # --- error paths ------------------------------------------------------
    try:
        get_instructions(42)
        check(False, "get_instructions(42) raises TypeError")
    except TypeError:
        check(True, "get_instructions(42) raises TypeError")
    try:
        get_instructions(dict)
        check(False, "get_instructions(class) raises TypeError")
    except TypeError:
        check(True, "get_instructions(class) raises TypeError")

    if failures:
        print("DEMO FAILED: %d check(s)" % len(failures))
        return 1
    print("DEMO PASSED: all checks green")
    return 0


def main(argv: List[str]) -> int:
    if len(argv) == 1:
        return _run_demo()
    path = Path(argv[1])
    if len(argv) >= 4 and argv[2] == "-f":
        reports = disassemble_module(path)
        name = argv[3]
        if name not in reports:
            print("no code object named %r; available: %s"
                  % (name, sorted(reports)))
            return 2
        print(reports[name].listing())
        return 0
    print(module_summary(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
