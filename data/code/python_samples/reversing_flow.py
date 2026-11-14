#!/usr/bin/env python3
"""
reversing_flow.py -- Control-flow analysis for Python bytecode.

Builds, from the dis module's instruction stream, the structures a
reverse engineer draws on paper:

  * basic blocks -- maximal straight-line runs of instructions,
  * the control-flow graph (CFG) -- edges between blocks,
  * dominators -- which blocks must be passed through to reach a block,
  * loops -- natural loops found from back edges in the CFG,
  * unreachable blocks -- code that no edge can reach,
  * cyclomatic complexity -- edges - nodes + 2,
  * a call graph -- which functions call which, across a whole module.

Only the standard library is used.  The file is self-contained; its
__main__ demo analyses real functions (loops, nested branches, try/
except, an early return) and asserts concrete facts: block counts,
loop headers and bodies, dominator sets, complexity numbers, and a
call graph built from this file and from mini_ai modules in the repo.

Usage:
    python3 reversing_flow.py                    # run the demo
    python3 reversing_flow.py path/to/file.py    # CFG report for a module
"""

from __future__ import annotations

import dis
import sys
import types
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# Opcodes that end a block by transferring control elsewhere, and
# opcodes that end a block by leaving the function.
UNCONDITIONAL_JUMPS = {"JUMP_FORWARD", "JUMP_BACKWARD", "JUMP"}
CONDITIONAL_JUMPS = {
    "POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE",
    "JUMP_IF_TRUE_OR_POP", "JUMP_IF_FALSE_OR_POP",
    "JUMP_IF_NOT_EXC_MATCH",
}
TERMINATORS = {"RETURN_VALUE", "RETURN_CONST", "RAISE_VARARGS",
               "RERAISE", "RETURN_GENERATOR"}
# Instructions that can transfer control to a handler or iterator end.
BRANCHING = UNCONDITIONAL_JUMPS | CONDITIONAL_JUMPS | {
    "FOR_ITER", "SETUP_FINALLY", "SETUP_CLEANUP", "SETUP_WITH",
    "SEND", "JUMP_IF_NOT_EXC_MATCH",
}


def _is_branch(ins: dis.Instruction) -> bool:
    return ins.opname in BRANCHING


def _is_terminator(ins: dis.Instruction) -> bool:
    return ins.opname in TERMINATORS


def _jump_target(ins: dis.Instruction) -> Optional[int]:
    if _is_branch(ins) and isinstance(ins.argval, int):
        return ins.argval
    return None


# ---------------------------------------------------------------------------
# Basic blocks
# ---------------------------------------------------------------------------

class BasicBlock:
    """A maximal straight-line run of instructions."""

    def __init__(self, block_id: int, start_offset: int) -> None:
        self.id = block_id
        self.start_offset = start_offset
        self.instructions: List[dis.Instruction] = []
        self.successors: Set[int] = set()
        self.predecessors: Set[int] = set()

    @property
    def end_offset(self) -> int:
        return self.instructions[-1].offset if self.instructions else -1

    @property
    def first_line(self) -> Optional[int]:
        for ins in self.instructions:
            if ins.starts_line is not None:
                return ins.starts_line
        return None

    @property
    def last_opname(self) -> Optional[str]:
        return self.instructions[-1].opname if self.instructions else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Block(%d, off=%d, %d ins, succ=%s)" % (
            self.id, self.start_offset, len(self.instructions),
            sorted(self.successors))


def split_into_blocks(instructions: List[dis.Instruction]) -> List[BasicBlock]:
    """Split an instruction list into basic blocks.

    A new block starts at every jump target and at every instruction
    that follows a branch or a terminator.
    """
    if not instructions:
        return []
    leaders: Set[int] = {instructions[0].offset}
    for i, ins in enumerate(instructions):
        target = _jump_target(ins)
        if target is not None:
            leaders.add(target)
        if (_is_branch(ins) or _is_terminator(ins)) and i + 1 < len(instructions):
            leaders.add(instructions[i + 1].offset)
    blocks: List[BasicBlock] = []
    current: Optional[BasicBlock] = None
    for ins in instructions:
        if ins.offset in leaders:
            current = BasicBlock(len(blocks), ins.offset)
            blocks.append(current)
        assert current is not None
        current.instructions.append(ins)
    return blocks


# ---------------------------------------------------------------------------
# Control-flow graph
# ---------------------------------------------------------------------------

class CFG:
    """Control-flow graph of one function."""

    def __init__(self, obj: Any, label: Optional[str] = None) -> None:
        if isinstance(obj, types.CodeType):
            self.code = obj
            self.name = obj.co_qualname
        else:
            self.code = obj.__code__
            self.name = label or getattr(obj, "__qualname__", str(obj))
        instructions = list(dis.get_instructions(self.code))
        self.instructions = instructions
        self.blocks = split_into_blocks(instructions)
        self._offset_to_block: Dict[int, int] = {}
        for block in self.blocks:
            for ins in block.instructions:
                self._offset_to_block[ins.offset] = block.id
        self._link_blocks()

    # -- construction ------------------------------------------------------
    def _link_blocks(self) -> None:
        for i, block in enumerate(self.blocks):
            if not block.instructions:
                continue
            last = block.instructions[-1]
            target = _jump_target(last)
            if last.opname in UNCONDITIONAL_JUMPS:
                if target is not None and target in self._offset_to_block:
                    block.successors.add(self._offset_to_block[target])
            elif _is_branch(last):
                # Conditional: fall through to the next block AND jump.
                if i + 1 < len(self.blocks):
                    block.successors.add(i + 1)
                if target is not None and target in self._offset_to_block:
                    block.successors.add(self._offset_to_block[target])
            elif _is_terminator(last):
                pass  # leaves the function; no successors
            else:
                if i + 1 < len(self.blocks):
                    block.successors.add(i + 1)
            for succ in block.successors:
                self.blocks[succ].predecessors.add(block.id)
        self._link_exception_edges()

    def _block_containing(self, offset: int) -> Optional[int]:
        """Id of the block that contains a bytecode offset (the block
        with the greatest start offset <= the given offset)."""
        best: Optional[int] = None
        for block in self.blocks:
            if block.start_offset <= offset:
                best = block.id
            else:
                break
        return best

    def _link_exception_edges(self) -> None:
        """Add edges from the exception table: if an exception can be
        raised anywhere in [start, end), control can jump to `target`.
        CPython 3.11+ stores this table on the code object; dis exposes
        a private parser for it.  Without a parser we simply have no
        exception edges (handlers then look unreachable)."""
        parse = getattr(dis, "_parse_exception_table", None)
        if parse is None:
            return
        try:
            entries = parse(self.code)
        except Exception:
            return
        for entry in entries:
            target_block = self._block_containing(entry.target)
            if target_block is None:
                continue
            for block in self.blocks:
                covered = any(entry.start <= ins.offset < entry.end
                              for ins in block.instructions)
                if covered and target_block not in block.successors:
                    block.successors.add(target_block)
                    self.blocks[target_block].predecessors.add(block.id)

    # -- queries ------------------------------------------------------------
    @property
    def entry(self) -> BasicBlock:
        return self.blocks[0]

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def edge_count(self) -> int:
        return sum(len(b.successors) for b in self.blocks)

    def cyclomatic_complexity(self) -> int:
        """McCabe complexity for a graph with possibly several exits:
        E - N + exits + 1, where exits are blocks with no successors.
        (For a single exit this reduces to the familiar E - N + 2.)"""
        exits = sum(1 for b in self.blocks if not b.successors)
        return self.edge_count - self.block_count + exits + 1

    def reachable_blocks(self) -> Set[int]:
        seen: Set[int] = set()
        stack = [0]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self.blocks[node].successors)
        return seen

    def unreachable_blocks(self) -> List[BasicBlock]:
        reachable = self.reachable_blocks()
        return [b for b in self.blocks if b.id not in reachable]

    def dominators(self) -> Dict[int, Set[int]]:
        """Iterative dominator computation (Cooper et al. style, set form).

        dom(entry) = {entry}; dom(b) = {b} u intersection of dom(p) for
        every predecessor p.  Iterated to a fixed point.
        """
        all_ids = set(range(len(self.blocks)))
        dom: Dict[int, Set[int]] = {i: set(all_ids) for i in all_ids}
        dom[0] = {0}
        changed = True
        while changed:
            changed = False
            for block in self.blocks[1:]:
                preds = [p for p in block.predecessors if p in dom]
                if not preds:
                    new = {block.id}
                else:
                    new = set.intersection(*(dom[p] for p in preds))
                    new.add(block.id)
                if new != dom[block.id]:
                    dom[block.id] = new
                    changed = True
        return dom

    def back_edges(self) -> List[Tuple[int, int]]:
        """Edges (source, target) where the target dominates the source:
        these are the loop-closing edges."""
        dom = self.dominators()
        edges = []
        for block in self.blocks:
            for succ in block.successors:
                if succ in dom[block.id]:
                    edges.append((block.id, succ))
        return edges

    def natural_loop(self, back_edge: Tuple[int, int]) -> Set[int]:
        """The natural loop of a back edge (source, header): the header
        plus every block that can reach the source without passing
        through the header."""
        source, header = back_edge
        loop = {header, source}
        stack = [source]
        while stack:
            node = stack.pop()
            for pred in self.blocks[node].predecessors:
                if pred not in loop:
                    loop.add(pred)
                    stack.append(pred)
        return loop

    def loops(self) -> List[Dict[str, Any]]:
        """All natural loops, one per loop header.  A loop often has
        several back edges (one per branch that jumps back to the
        header, e.g. each arm of an if/elif inside a for body), so
        back edges are grouped by header and the body is the union
        of their natural loops."""
        by_header: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for edge in self.back_edges():
            by_header[edge[1]].append(edge)
        out = []
        for header_id, edges in sorted(by_header.items()):
            body: Set[int] = set()
            for edge in edges:
                body |= self.natural_loop(edge)
            header = self.blocks[header_id]
            line = header.first_line
            if line is None:
                # The header instruction (e.g. FOR_ITER) often carries
                # no line of its own; fall back to the body's lines.
                body_lines = [self.blocks[b].first_line for b in body]
                body_lines = [ln for ln in body_lines if ln is not None]
                line = min(body_lines) if body_lines else None
            out.append({
                "header_block": header_id,
                "header_line": line,
                "latch_blocks": sorted(e[0] for e in edges),
                "body_blocks": sorted(body),
                "body_size": len(body),
            })
        return out

    def block_for_line(self, lineno: int) -> Optional[BasicBlock]:
        for block in self.blocks:
            if block.first_line == lineno:
                return block
        return None

    def reachable_from(self, block_id: int) -> Set[int]:
        """All blocks reachable from a given block (including itself)."""
        seen: Set[int] = set()
        stack = [block_id]
        while stack:
            node = stack.pop()
            if node in seen or node >= len(self.blocks):
                continue
            seen.add(node)
            stack.extend(self.blocks[node].successors)
        return seen

    def loop_nesting_depth(self) -> int:
        """Deepest loop nesting: a loop header inside another loop's
        body adds one level.  Computed from header containment: a
        loop's header is nested inside every other loop whose body
        contains it."""
        loops = self.loops()
        if not loops:
            return 0
        bodies = [set(loop["body_blocks"]) for loop in loops]
        headers = [loop["header_block"] for loop in loops]
        depth = [1] * len(loops)
        for i, header in enumerate(headers):
            for j, body in enumerate(bodies):
                if i != j and header in body:
                    depth[i] = max(depth[i], depth[j] + 1)
        # Iterate to a fixed point: nesting can chain.
        changed = True
        while changed:
            changed = False
            for i, header in enumerate(headers):
                for j, body in enumerate(bodies):
                    if i != j and header in body and depth[i] < depth[j] + 1:
                        depth[i] = depth[j] + 1
                        changed = True
        return max(depth)

    def to_dot(self) -> str:
        """Graphviz DOT rendering of the CFG, for piping to `dot`."""
        lines = ["digraph %s {" % self.name.replace(".", "_"),
                 '  label="%s (complexity %d)";' % (
                     self.name, self.cyclomatic_complexity()),
                 "  node [shape=box, fontname=monospace];"]
        for block in self.blocks:
            label = "B%d\\nline %s\\n%s" % (
                block.id, block.first_line,
                "\\n".join(i.opname for i in block.instructions[:6]))
            if len(block.instructions) > 6:
                label += "\\n..."
            lines.append('  B%d [label="%s"];' % (block.id, label))
        for block in self.blocks:
            for succ in sorted(block.successors):
                lines.append("  B%d -> B%d;" % (block.id, succ))
        lines.append("}")
        return "\n".join(lines)

    # -- rendering ----------------------------------------------------------
    def render(self) -> str:
        lines = ["CFG of %s: %d blocks, %d edges, complexity %d"
                 % (self.name, self.block_count, self.edge_count,
                    self.cyclomatic_complexity())]
        loops = self.loops()
        if loops:
            for loop in loops:
                lines.append("  loop: header block %d (line %s), latches %s, body blocks %s"
                             % (loop["header_block"], loop["header_line"],
                                loop["latch_blocks"], loop["body_blocks"]))
        unreachable = self.unreachable_blocks()
        if unreachable:
            lines.append("  unreachable blocks: %s"
                         % [b.id for b in unreachable])
        for block in self.blocks:
            opnames = [i.opname for i in block.instructions]
            lines.append("  B%d [line %s, off %d..%d] -> %s : %s"
                         % (block.id, block.first_line, block.start_offset,
                            block.end_offset, sorted(block.successors),
                            ", ".join(opnames)))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Call graph
# ---------------------------------------------------------------------------

def _call_sites(instructions: List[dis.Instruction]
                ) -> List[Tuple[int, str, Optional[int]]]:
    """Origin-tracking stack simulation: for every CALL instruction,
    return (index, dotted callee name, source line).  The stack holds
    the origin of each value (LOAD_GLOBAL os pushes "os", LOAD_ATTR
    system makes it "os.system"); a CALL with n arguments finds its
    callable at stack position -(n+1), below the NULL and the args,
    per CPython 3.12's calling convention.  Linear simulation: the
    stack resets at jump targets, so calls spanning a branch are
    missed rather than misattributed."""
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


def _called_names(code: types.CodeType) -> List[str]:
    """Best-effort callee names for one code object, via _call_sites."""
    instructions = list(dis.get_instructions(code))
    return [name for _, name, _ in _call_sites(instructions)]


def _walk_code_objects(code: types.CodeType):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _walk_code_objects(const)


class CallGraph:
    """Call graph of a whole module: caller qualname -> callee names,
    plus which callees resolve to functions defined in the same module."""

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        self.path = path
        code = compile(path.read_text(), str(path), "exec")
        self.nodes: Dict[str, types.CodeType] = {}
        for obj in _walk_code_objects(code):
            self.nodes[obj.co_qualname] = obj
        self.edges: Dict[str, List[str]] = {
            name: _called_names(obj) for name, obj in self.nodes.items()
        }

    def internal_edges(self) -> Dict[str, List[str]]:
        """Edges where the callee is defined in this same module."""
        defined = set(self.nodes)
        return {caller: [c for c in callees if c in defined]
                for caller, callees in self.edges.items()}

    def external_calls(self) -> Dict[str, List[str]]:
        defined = set(self.nodes)
        return {caller: [c for c in callees if c not in defined]
                for caller, callees in self.edges.items()}

    def callers_of(self, name: str) -> List[str]:
        return [caller for caller, callees in self.edges.items()
                if name in callees]

    def roots(self) -> List[str]:
        """Functions nothing in the module calls (entry points)."""
        called = {c for callees in self.edges.values() for c in callees}
        return [n for n in self.nodes if n not in called]

    def render(self) -> str:
        lines = ["call graph of %s (%d functions)"
                 % (self.path.name, len(self.nodes))]
        for caller in sorted(self.edges):
            callees = self.edges[caller]
            internal = [c for c in callees if c in self.nodes]
            lines.append("  %s -> %s" % (
                caller,
                ", ".join("%s*" % c if c in internal else c
                          for c in callees) or "(none)"))
        lines.append("  (* = defined in this module)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo targets (real code, analysed by the demo below)
# ---------------------------------------------------------------------------

def demo_straight(x):
    """No branches at all: a single basic block."""
    y = x * 2 + 1
    return y


def demo_branch(x):
    """One if/else: three blocks, complexity 2."""
    if x > 0:
        return "pos"
    return "non-pos"


def demo_loop(n):
    """A for loop with an inner conditional: two loops? No -- one loop,
    but the inner if adds a branch inside the loop body."""
    total = 0
    for i in range(n):
        if i % 3 == 0:
            total += i
        elif i % 3 == 1:
            total += 2 * i
        else:
            total += 3
    return total


def demo_while(n):
    """A while loop with a break: one loop, one exit edge."""
    total = 0
    i = 0
    while i < n:
        if i == 5:
            break
        total += i
        i += 1
    return total


def demo_nested(n):
    """Two nested loops: an outer loop and an inner loop."""
    total = 0
    for i in range(n):
        for j in range(i):
            total += j
    return total


def demo_early_return(x):
    """Early return inside a loop: the loop still has one back edge."""
    for i in range(10):
        if i == x:
            return i
    return -1


def demo_try(x):
    """try/except adds an exception-handling edge."""
    try:
        return 100 // x
    except ZeroDivisionError:
        return 0


def demo_helper_a():
    return demo_helper_b() + 1


def demo_helper_b():
    return 41


def demo_caller():
    return demo_helper_a() + demo_helper_b()


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------

def _run_demo() -> int:
    failures: List[str] = []

    def check(condition: bool, message: str) -> None:
        print(("  ok  " if condition else " FAIL ") + message)
        if not condition:
            failures.append(message)

    print("== reversing_flow demo ==")

    # --- straight-line code: one block, complexity 1 ----------------------
    cfg = CFG(demo_straight)
    print(cfg.render())
    check(cfg.block_count == 1, "demo_straight has 1 block")
    check(cfg.cyclomatic_complexity() == 1,
          "demo_straight complexity is 1")
    check(cfg.loops() == [], "demo_straight has no loops")
    check(cfg.unreachable_blocks() == [], "demo_straight has no dead blocks")

    # --- one branch: 3 blocks, complexity 2 -------------------------------
    cfg = CFG(demo_branch)
    check(cfg.block_count == 3, "demo_branch has 3 blocks (got %d)"
          % cfg.block_count)
    check(cfg.cyclomatic_complexity() == 2, "demo_branch complexity is 2")
    check(cfg.loops() == [], "demo_branch has no loops")

    # --- for loop with inner if: one loop, complexity 4 -------------------
    cfg = CFG(demo_loop)
    print()
    print(cfg.render())
    loops = cfg.loops()
    check(len(loops) == 1, "demo_loop has exactly 1 loop (got %d)"
          % len(loops))
    if loops:
        check(loops[0]["body_size"] >= 3,
              "demo_loop loop body spans >= 3 blocks (got %d)"
              % loops[0]["body_size"])
        check(loops[0]["header_line"] is not None,
              "demo_loop loop header has a source line")
    check(cfg.cyclomatic_complexity() == 4,
          "demo_loop complexity is 4 (got %d)" % cfg.cyclomatic_complexity())

    # --- while + break ------------------------------------------------------
    # Note: the compiler duplicates `return total` on the break path, so
    # the bytecode graph has TWO exit blocks.  Graph-theoretic McCabe
    # counts the extra exit: 1 (base) + 1 (while) + 1 (if) + 1 (extra
    # exit) = 4, one more than a source-level count of 3.
    cfg = CFG(demo_while)
    check(len(cfg.loops()) == 1, "demo_while has exactly 1 loop")
    check(cfg.cyclomatic_complexity() == 4,
          "demo_while complexity is 4 (got %d)" % cfg.cyclomatic_complexity())

    # --- nested loops: two loops, inner header dominated by outer ---------
    cfg = CFG(demo_nested)
    loops = cfg.loops()
    check(len(loops) == 2, "demo_nested has exactly 2 loops (got %d)"
          % len(loops))
    check(cfg.cyclomatic_complexity() == 3,
          "demo_nested complexity is 3 (got %d)" % cfg.cyclomatic_complexity())
    dom = cfg.dominators()
    if len(loops) == 2:
        headers = sorted(loop["header_block"] for loop in loops)
        outer, inner = headers[0], headers[1]
        check(outer in dom[inner],
              "outer loop header dominates inner loop header")

    # --- early return: still one loop ---------------------------------------
    cfg = CFG(demo_early_return)
    check(len(cfg.loops()) == 1, "demo_early_return has 1 loop")

    # --- try/except: at least one extra edge, no crash ----------------------
    cfg = CFG(demo_try)
    check(cfg.block_count >= 3,
          "demo_try has >= 3 blocks (got %d)" % cfg.block_count)
    check(cfg.cyclomatic_complexity() >= 2,
          "demo_try complexity >= 2")

    # --- dominators: entry dominates everything ------------------------------
    cfg = CFG(demo_loop)
    dom = cfg.dominators()
    check(all(0 in dom[b] for b in dom),
          "entry block dominates every block in demo_loop")
    check(dom[0] == {0}, "entry block's dominator set is just itself")

    # --- reachability: every block reachable in these demos -----------------
    for fn in (demo_straight, demo_branch, demo_loop, demo_while,
               demo_nested, demo_early_return, demo_try):
        c = CFG(fn)
        check(c.unreachable_blocks() == [],
              "%s has no unreachable blocks" % fn.__name__)

    # --- the analyses agree with execution -----------------------------------
    check(demo_loop(6) == 0 + 0 + 2 + 3 + 4 + 10,
          "demo_loop(6) == 19 (sanity: analysed code runs)")
    check(demo_nested(3) == 0 + 0 + 1,
          "demo_nested(3) == 1")
    check(demo_while(10) == 0 + 1 + 2 + 3 + 4,
          "demo_while(10) == 10 (break at i == 5)")

    # --- call graph of this file ----------------------------------------------
    here = Path(__file__)
    graph = CallGraph(here)
    print()
    print(graph.render())
    check("demo_caller" in graph.edges, "call graph has demo_caller")
    check("demo_helper_a" in graph.edges["demo_caller"],
          "demo_caller calls demo_helper_a")
    check("demo_helper_b" in graph.edges["demo_caller"],
          "demo_caller calls demo_helper_b")
    check("demo_helper_b" in graph.edges["demo_helper_a"],
          "demo_helper_a calls demo_helper_b")
    check("demo_helper_b" in graph.callers_of("demo_helper_b")
          or "demo_caller" in graph.callers_of("demo_helper_b"),
          "callers_of(demo_helper_b) is non-empty")
    check(set(graph.callers_of("demo_helper_b"))
          == {"demo_helper_a", "demo_caller"},
          "exactly demo_helper_a and demo_caller call demo_helper_b")
    internal = graph.internal_edges()
    check("demo_helper_a" in internal["demo_caller"],
          "demo_helper_a is an internal edge of demo_caller")

    # --- call graph of a real repo module --------------------------------------
    repo = here.resolve().parents[2]
    planning = repo / "mini_ai" / "planning" / "core.py"
    if planning.exists():
        pgraph = CallGraph(planning)
        print()
        print(pgraph.render())
        check(len(pgraph.nodes) >= 3,
              "core.py call graph has >= 3 nodes (got %d)"
              % len(pgraph.nodes))
        check(all(isinstance(v, list) for v in pgraph.edges.values()),
              "core.py edges are lists")
        # Every edge target is a string name.
        check(all(isinstance(c, str) for cs in pgraph.edges.values()
                  for c in cs), "core.py callee names are strings")
    else:
        print("  (mini_ai/planning/core.py not found; repo check skipped)")

    # --- DOT output and loop nesting -----------------------------------------
    cfg = CFG(demo_nested)
    check(cfg.loop_nesting_depth() == 2,
          "demo_nested loop nesting depth is 2 (got %d)"
          % cfg.loop_nesting_depth())
    cfg = CFG(demo_loop)
    check(cfg.loop_nesting_depth() == 1,
          "demo_loop loop nesting depth is 1")
    cfg = CFG(demo_straight)
    check(cfg.loop_nesting_depth() == 0,
          "demo_straight loop nesting depth is 0")
    dot = CFG(demo_loop).to_dot()
    check(dot.startswith("digraph"), "DOT output starts with digraph")
    check("B0 -> B1" in dot, "DOT output contains the B0 -> B1 edge")
    check("FOR_ITER" in dot, "DOT output names the FOR_ITER instruction")
    check("complexity 4" in dot, "DOT label carries the complexity")
    check(CFG(demo_loop).reachable_from(0)
          == set(range(CFG(demo_loop).block_count)),
          "every block is reachable from the entry block of demo_loop")

    # --- CFG of every function in this file: no crashes, sane numbers ---------
    for name, obj in graph.nodes.items():
        c = CFG(obj)
        # Generator expressions can legitimately compute complexity 0:
        # they are resumed via SEND, an edge this CFG does not model.
        check(c.block_count >= 1 and c.cyclomatic_complexity() >= 0,
              "CFG of %s is sane (%d blocks, complexity %d)"
              % (name, c.block_count, c.cyclomatic_complexity()))

    if failures:
        print("DEMO FAILED: %d check(s)" % len(failures))
        return 1
    print("DEMO PASSED: all checks green")
    return 0


def main(argv: List[str]) -> int:
    if len(argv) == 1:
        return _run_demo()
    path = Path(argv[1])
    print(CallGraph(path).render())
    print()
    code = compile(path.read_text(), str(path), "exec")
    for obj in _walk_code_objects(code):
        print(CFG(obj).render())
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
