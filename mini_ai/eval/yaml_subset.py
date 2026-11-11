"""A tiny, original YAML-subset parser.

This is NOT a general YAML parser and it is NOT PyYAML. It exists so
``mini_ai/eval`` can read YAML task definitions with zero new
dependencies (stdlib only): PyYAML is present in the dev environment
but is not declared in ``requirements.txt``, and adding a dependency
for a handful of small task files would be the wrong trade.

Supported subset (enough for task definitions, and deliberately small):

- ``#`` comments: full-line, or trailing after a space, outside quotes.
- Mappings by indentation (spaces only; tabs are rejected).
- Block sequences: ``- item`` for scalars, and ``- key: value`` for a
  mapping as a list item, with continuation keys indented to the key
  column of the first key.
- Inline flow lists: ``[a, b, "c d"]``.
- Scalars: ``null`` / ``~`` / ``None``, ``true`` / ``false``
  (any case), integers, floats, plain strings, single-quoted strings
  (``''`` escapes a quote) and double-quoted strings (``\\"``,
  ``\\\\``, ``\\n``, ``\\t`` escapes).
- Nested mappings and sequences to any depth.

NOT supported (a ``ValueError`` is raised, with the line number):
block scalars (``|`` / ``>``), anchors / aliases / tags, inline flow
mappings (``{a: b}``), multi-line plain scalars, tabs for indentation,
duplicate keys in one mapping.

Anything outside this subset should be written as plain JSON instead
and loaded with ``json.load`` — the task loader accepts a dict from
either source. Keep task files inside the subset; if a task file ever
needs full YAML, that is a deliberate decision to add PyYAML to
``requirements.txt``, not a silent drift.
"""

__all__ = ["parse_yaml_subset", "YamlSubsetError"]


class YamlSubsetError(ValueError):
    """Raised when a task file uses YAML outside the supported subset."""


def _strip_comment(line):
    """Remove a ``#`` comment that is outside any quoted string."""
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_single:
            if ch == "'":
                if i + 1 < len(line) and line[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
        elif in_double:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _split_flow_items(inner, line_no):
    """Split the inside of ``[...]`` on top-level commas."""
    items = []
    depth = 0
    in_single = False
    in_double = False
    current = []
    i = 0
    while i < len(inner):
        ch = inner[i]
        if in_single:
            current.append(ch)
            if ch == "'":
                if i + 1 < len(inner) and inner[i + 1] == "'":
                    current.append("'")
                    i += 2
                    continue
                in_single = False
        elif in_double:
            current.append(ch)
            if ch == "\\":
                if i + 1 < len(inner):
                    current.append(inner[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
                current.append(ch)
            elif ch == '"':
                in_double = True
                current.append(ch)
            elif ch in "[{":
                depth += 1
                current.append(ch)
            elif ch in "]}":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        i += 1
    if current or not items:
        items.append("".join(current).strip())
    if depth != 0 or in_single or in_double:
        raise YamlSubsetError(f"line {line_no}: unbalanced brackets or quotes")
    return [item for item in items if item != ""]


def _parse_scalar(text, line_no):
    """Parse one scalar token into a Python value."""
    text = text.strip()
    if text == "":
        return None
    if text.startswith("{") or text.startswith("}"):
        raise YamlSubsetError(
            f"line {line_no}: inline flow mappings are not supported: {text!r}"
        )
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if inner == "":
            return []
        return [_parse_scalar(item, line_no) for item in _split_flow_items(inner, line_no)]
    if text.startswith("[") or text.endswith("]"):
        raise YamlSubsetError(f"line {line_no}: unbalanced flow list: {text!r}")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        body = text[1:-1]
        out = []
        i = 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
                i += 2
            else:
                out.append(body[i])
                i += 1
        return "".join(out)
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if text[0] in "\"'":
        raise YamlSubsetError(f"line {line_no}: unbalanced quotes: {text!r}")
    lowered = text.lower()
    if lowered in ("null", "~", "none"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text[0] in "|>":
        raise YamlSubsetError(
            f"line {line_no}: block scalars (| / >) are not supported"
        )
    if text[0] in "&*!":
        raise YamlSubsetError(
            f"line {line_no}: anchors, aliases and tags are not supported: {text!r}"
        )
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _split_key_value(content, line_no):
    """Split ``key: value`` (or ``key:``) into (key, value-or-None).

    The colon must be followed by a space or end-of-line, so a plain
    scalar such as ``http://x`` or ``12:30`` is not split.
    """
    in_single = False
    in_double = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_single:
            if ch == "'":
                in_single = False
        elif in_double:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == ":" and (i + 1 == len(content) or content[i + 1] == " "):
                key = content[:i].strip()
                value = content[i + 1:].strip()
                if not key:
                    raise YamlSubsetError(f"line {line_no}: empty key")
                return _parse_scalar(key, line_no), (value if value else None)
        i += 1
    return None, None


def _prepare_lines(text):
    """Return [(indent, content, line_no)] for non-blank lines."""
    prepared = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlSubsetError(f"line {line_no}: tabs are not allowed for indentation")
        if raw.strip() == "":
            continue
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        prepared.append((indent, stripped.strip(), line_no))
    return prepared


def _parse_block(lines, pos, indent):
    """Parse one block (mapping, sequence, or scalar) at ``indent``.

    Returns (value, next_pos). ``lines`` is the prepared list from
    ``_prepare_lines``; ``pos`` is the index of the first line of the
    block, which must be indented exactly ``indent``.
    """
    if pos >= len(lines):
        return None, pos
    first_indent, first_content, first_no = lines[pos]
    if first_indent < indent:
        return None, pos
    if first_indent > indent:
        raise YamlSubsetError(
            f"line {first_no}: unexpected indentation (expected {indent}, got {first_indent})"
        )

    if first_content == "-" or first_content.startswith("- "):
        return _parse_sequence(lines, pos, indent)

    key, _ = _split_key_value(first_content, first_no)
    if key is not None:
        return _parse_mapping(lines, pos, indent)

    # A lone scalar on its own line.
    return _parse_scalar(first_content, first_no), pos + 1


def _parse_mapping(lines, pos, indent):
    result = {}
    while pos < len(lines):
        line_indent, content, line_no = lines[pos]
        if line_indent != indent:
            break
        if content == "-" or content.startswith("- "):
            break
        key, raw_value = _split_key_value(content, line_no)
        if key is None:
            raise YamlSubsetError(f"line {line_no}: expected 'key: value', got {content!r}")
        if key in result:
            raise YamlSubsetError(f"line {line_no}: duplicate key {key!r}")
        pos += 1
        if raw_value is not None:
            result[key] = _parse_scalar(raw_value, line_no)
        else:
            # Value is a nested block on the following lines, or null.
            if pos < len(lines) and lines[pos][0] > indent:
                value, pos = _parse_block(lines, pos, lines[pos][0])
                result[key] = value
            else:
                result[key] = None
    return result, pos


def _parse_sequence(lines, pos, indent):
    result = []
    while pos < len(lines):
        line_indent, content, line_no = lines[pos]
        if line_indent != indent:
            break
        if not (content == "-" or content.startswith("- ")):
            break
        rest = content[1:].strip()
        item_indent = indent + 2
        if rest == "":
            # Nested block on the following lines, or a null item.
            pos += 1
            if pos < len(lines) and lines[pos][0] > indent:
                value, pos = _parse_block(lines, pos, lines[pos][0])
                result.append(value)
            else:
                result.append(None)
            continue
        key, raw_value = _split_key_value(rest, line_no)
        if key is not None:
            # A mapping as a list item: first key on the dash line,
            # continuation keys indented to the key column.
            item = {}
            if key in item:
                raise YamlSubsetError(f"line {line_no}: duplicate key {key!r}")
            pos += 1
            if raw_value is not None:
                item[key] = _parse_scalar(raw_value, line_no)
            elif pos < len(lines) and lines[pos][0] > item_indent:
                value, pos = _parse_block(lines, pos, lines[pos][0])
                item[key] = value
            else:
                item[key] = None
            while pos < len(lines):
                cont_indent, cont_content, cont_no = lines[pos]
                if cont_indent != item_indent:
                    break
                if cont_content == "-" or cont_content.startswith("- "):
                    break
                cont_key, cont_raw = _split_key_value(cont_content, cont_no)
                if cont_key is None:
                    raise YamlSubsetError(
                        f"line {cont_no}: expected 'key: value', got {cont_content!r}"
                    )
                if cont_key in item:
                    raise YamlSubsetError(f"line {cont_no}: duplicate key {cont_key!r}")
                pos += 1
                if cont_raw is not None:
                    item[cont_key] = _parse_scalar(cont_raw, cont_no)
                elif pos < len(lines) and lines[pos][0] > item_indent:
                    value, pos = _parse_block(lines, pos, lines[pos][0])
                    item[cont_key] = value
                else:
                    item[cont_key] = None
            result.append(item)
            continue
        # A plain scalar item.
        result.append(_parse_scalar(rest, line_no))
        pos += 1
    return result, pos


def parse_yaml_subset(text):
    """Parse ``text`` under the supported YAML subset (see module docs).

    Returns plain Python values (dict / list / str / int / float /
    bool / None). Raises :class:`YamlSubsetError` on anything outside
    the subset, and on empty input.
    """
    if not isinstance(text, str):
        raise TypeError("parse_yaml_subset expects a string")
    lines = _prepare_lines(text)
    if not lines:
        raise YamlSubsetError("empty document")
    value, pos = _parse_block(lines, 0, lines[0][0])
    if pos != len(lines):
        raise YamlSubsetError(f"line {lines[pos][2]}: trailing content at wrong indent")
    return value
