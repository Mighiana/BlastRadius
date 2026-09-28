"""Bounded evaluator for python-hcl2's serialized expression format.

python-hcl2 v8 does not hand us an AST for function calls: it re-serializes
expressions such as ``jsonencode({...})`` back into a single string
``"${jsonencode({Version = \\"v\\", ...})}"``. This module parses that text
with a tiny allowlisted recursive-descent reader — objects, lists, strings,
numbers, booleans, null, Terraform resource traversals, and interpolated
strings — and nothing else. Anything unrecognized (other function calls,
var./local./data./module. traversals, operators, conditionals) is reported as
unresolved so callers can fail closed instead of guessing.

There is no eval(), no exec(), and no Terraform execution anywhere in this
file. Evaluation is bounded by node and depth budgets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_EXPR_NODES = 2_000
MAX_EXPR_DEPTH = 64
MAX_REASON_LENGTH = 120


class ExpressionError(ValueError):
    """The serialized expression is malformed or exceeds its budget."""


@dataclass
class Unresolved:
    """A short, safe description of one unresolvable sub-expression."""

    reason: str

    def __post_init__(self) -> None:
        if len(self.reason) > MAX_REASON_LENGTH:
            self.reason = self.reason[:MAX_REASON_LENGTH]


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TRAVERSAL_TAIL = re.compile(r"\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\]")
_AWS_TRAVERSAL = re.compile(r"aws_[A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])+")
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass
class _Reader:
    text: str
    problems: list[Unresolved] = field(default_factory=list)
    nodes: int = 0

    def _node(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_EXPR_NODES:
            raise ExpressionError("expression exceeds node budget")

    def _skip_ws(self) -> None:
        self.text = self.text.lstrip()

    def _peek(self) -> str:
        return self.text[:1]

    def _expect(self, token: str) -> None:
        self._skip_ws()
        if not self.text.startswith(token):
            raise ExpressionError(f"expected {token!r}")
        self.text = self.text[len(token):]

    def read_value(self, depth: int = 0) -> object:
        self._node()
        if depth > MAX_EXPR_DEPTH:
            raise ExpressionError("expression exceeds nesting budget")
        self._skip_ws()
        ch = self._peek()
        if not ch:
            raise ExpressionError("unexpected end of expression")
        if ch == "{":
            return self._read_object(depth)
        if ch == "[":
            return self._read_list(depth)
        if ch == '"':
            return self._read_string()
        if ch.isdigit() or ch == "-":
            return self._read_number()
        ident = _IDENTIFIER.match(self.text)
        if ident:
            name = ident.group(0)
            self.text = self.text[ident.end():]
            if name in ("true", "false"):
                return name == "true"
            if name == "null":
                return None
            self._skip_ws()
            if self._peek() == "(":
                self._skip_call()
                self.problems.append(Unresolved(f"unsupported function '{name}'"))
                return None
            traversal = self._read_traversal(name)
            if traversal.startswith("aws_"):
                return "${" + traversal + "}"
            self.problems.append(Unresolved(f"unresolved reference '{traversal}'"))
            return None
        raise ExpressionError(f"unexpected token {ch!r}")

    def _read_traversal(self, head: str) -> str:
        parts = [head]
        while True:
            match = _TRAVERSAL_TAIL.match(self.text)
            if not match:
                break
            parts.append(match.group(0))
            self.text = self.text[match.end():]
        return "".join(parts)

    def _read_object(self, depth: int) -> dict:
        result: dict[str, object] = {}
        self._expect("{")
        while True:
            self._skip_ws()
            if self._peek() == "}":
                self.text = self.text[1:]
                return result
            if self._peek() == '"':
                key = self._read_string()
            else:
                match = _IDENTIFIER.match(self.text)
                if not match:
                    raise ExpressionError("object key is not an identifier")
                key = match.group(0)
                self.text = self.text[match.end():]
            self._skip_ws()
            self._expect("=")
            result[str(key)] = self.read_value(depth + 1)
            self._skip_ws()
            if self._peek() == ",":
                self.text = self.text[1:]

    def _read_list(self, depth: int) -> list:
        result: list[object] = []
        self._expect("[")
        while True:
            self._skip_ws()
            if self._peek() == "]":
                self.text = self.text[1:]
                return result
            result.append(self.read_value(depth + 1))
            self._skip_ws()
            if self._peek() == ",":
                self.text = self.text[1:]

    def _read_string(self) -> str:
        self._expect('"')
        out: list[str] = []
        while self.text:
            ch = self.text[0]
            self.text = self.text[1:]
            if ch == '"':
                return "".join(out)
            if ch == "\\":
                out.append(self._read_escape())
            elif ch in "$%" and self.text.startswith(ch + "{"):
                out.append(ch + "{")
                self.text = self.text[2:]
            elif ch in "$%" and self.text.startswith("{"):
                self.text = self.text[1:]
                out.append(self._read_template(ch))
            else:
                out.append(ch)
        raise ExpressionError("unterminated string")

    def _read_escape(self) -> str:
        esc = self.text[:1]
        self.text = self.text[1:]
        if esc in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[esc]
        width = {"u": 4, "U": 8}.get(esc)
        if width is None:
            raise ExpressionError("invalid string escape")
        digits = self.text[:width]
        if len(digits) != width or not all(c in "0123456789abcdefABCDEF" for c in digits):
            raise ExpressionError("invalid unicode escape")
        self.text = self.text[width:]
        code = int(digits, 16)
        if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
            raise ExpressionError("invalid unicode code point")
        return chr(code)

    def _read_template(self, marker: str) -> str:
        """Read one ``${...}``/``%{...}`` sequence after its opening brace."""
        end = self.text.find("}")
        if end < 0:
            raise ExpressionError("unterminated template sequence")
        body = self.text[:end].strip()
        self.text = self.text[end + 1:]
        if marker == "$" and _AWS_TRAVERSAL.fullmatch(body):
            return "${" + body + "}"
        label = "template directive" if marker == "%" else f"interpolation '{body[:60]}'"
        self.problems.append(Unresolved(f"unresolved {label}"))
        return ""

    def _read_number(self) -> object:
        match = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", self.text)
        if not match:
            raise ExpressionError("invalid number")
        token = match.group(0)
        self.text = self.text[match.end():]
        return float(token) if any(c in token for c in ".eE") else int(token)

    def _skip_call(self) -> None:
        """Consume `(...)` including nested parentheses and strings."""
        self._expect("(")
        depth = 1
        while self.text:
            ch = self.text[0]
            if ch == '"':
                self._read_string()
                continue
            self.text = self.text[1:]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return
        raise ExpressionError("unterminated function call")


def evaluate_expression(text: str) -> tuple[object, list[Unresolved]]:
    """Evaluate one serialized hcl2 expression.

    Returns ``(value, problems)``. ``problems`` is empty only when every
    sub-expression was understood; any entry means the value is partial and
    callers must fail closed. Raises ExpressionError on malformed input or
    budget exhaustion.
    """
    if len(text) > 1_000_000:
        raise ExpressionError("expression exceeds size budget")
    reader = _Reader(text)
    value = reader.read_value()
    reader._skip_ws()
    if reader.text:
        raise ExpressionError("trailing content after expression")
    return value, reader.problems


def jsonencode_argument(text: str) -> str | None:
    """Extract the argument of ``jsonencode(...)`` from a serialized value.

    Accepts both ``jsonencode({...})`` and its ``${jsonencode({...})}``
    interpolation-wrapped form (the shape python-hcl2 emits).
    """
    text = text.strip()
    if text.startswith("${") and text.endswith("}"):
        text = text[2:-1].strip()
    if text.startswith("jsonencode(") and text.endswith(")"):
        return text[len("jsonencode("):-1]
    return None
