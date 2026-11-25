r"""Comparing two readings of the same handwriting, character by character.

Two examiners reading one script must see the same signs.  A second reading is
only worth its request if the comparison can tell ``+`` from ``-``: the defect
this module exists for is a marking pass that read
``(4x^2 + 12x + 9) - (4x^2 - 12x + 9)`` as ``4x^2 + 12x + 9 - 4x^2 - 12x + 9``,
concluded both expansions were wrong and took a confident zero for correct work.

Mathematical equivalence is **not** the question here.  ``3/4`` and ``0.75`` are
the same number and different working; a scheme can award a fraction and withhold
a decimal.  ``(x + 1)^2`` and ``x^2 + 2x + 1`` are equal and show different
method.  So this module compares the *written* form: it normalises only what
cannot change the reading, then compares token by token.  A sign, an exponent, a
bracket, a numerator, a decimal point or a relation that differs is a material
difference, and a question with one goes to a person.

LaTeX is normalised the same way: only typography and wrapper characters are
removed.  A command that names a mathematics symbol is mapped to a stable token
(``\theta`` → ``theta``, ``\sin`` → ``sin``) and a command this module does not
know is left in the stream as its own token.  Nothing deletes a symbol: an
unknown macro can never turn ``2\theta`` into ``2`` and so make two different
answers agree.

Brackets are compared structurally rather than textually, because that is where
the defects live.  ``-(a - b)`` and ``-a - b`` contain the same characters and
mean different things, so a minus in front of a bracket is distributed into it
before comparison — a deterministic rewrite, not algebra: no expansion of
products, no simplification, no reordering.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

STATUS_AGREES = "AGREES"
STATUS_DIFFERS = "DIFFERS"
STATUS_ABSENT = "ABSENT"
STATUS_UNVERIFIABLE = "UNVERIFIABLE"

#: What kind of detail the two readings disagree on.  These are reported so a
#: reviewer knows what to look at, not to score severity: every one is material.
KIND_SIGN = "SIGN"
KIND_EXPONENT = "EXPONENT"
KIND_BRACKET = "BRACKET"
KIND_FRACTION = "FRACTION"
KIND_DECIMAL = "DECIMAL"
KIND_RELATION = "RELATION"
KIND_TERM = "TERM"
KIND_MISSING_EXPRESSION = "MISSING_EXPRESSION"
KIND_WORKING_NOT_RECORDED = "WORKING_NOT_RECORDED"
KIND_INDEPENDENT_ABSENT = "INDEPENDENT_ABSENT"

_SUPERSCRIPTS = {
    "⁰": "^0",
    "¹": "^1",
    "²": "^2",
    "³": "^3",
    "⁴": "^4",
    "⁵": "^5",
    "⁶": "^6",
    "⁷": "^7",
    "⁸": "^8",
    "⁹": "^9",
    "⁻": "^-",
    "⁺": "^+",
}

_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    # Dashes a reader may copy for a minus sign.  An en dash inside a range is
    # not a minus, but no marking transcript writes ranges.
    ("\u2212", "-"),  # minus sign
    ("\u2013", "-"),  # en dash
    ("\u2014", "-"),  # em dash
    ("\u00d7", "*"),  # multiplication sign
    ("\u00b7", "*"),  # middle dot
    ("\u00f7", "/"),  # division sign
    ("\u2264", "<="),
    ("\u2265", ">="),
    ("\u2260", "!="),
    ("**", "^"),
)

#: LaTeX that has a fixed, non-deleting rewrite: a fraction becomes a division,
#: a root a function call, an escaped punctuation mark the character it escapes.
_LATEX_STRUCTURE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\\[(),;:!]"), ""),
    (re.compile(r"\\cdot|\\times"), "*"),
    (re.compile(r"\\div"), "/"),
    (re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}"), r"((\1)/(\2))"),
    (re.compile(r"\\sqrt\s*\{([^{}]*)\}"), r"sqrt(\1)"),
    (re.compile(r"\^\s*\{([^{}]*)\}"), r"^(\1)"),
    # A braced subscript is the same subscript: ``a_{1}`` reads as ``a_1``.
    (re.compile(r"_\s*\{([^{}]*)\}"), r"_\1"),
)

#: Commands that only set typography or spacing.  Deleting one cannot change
#: what was read, so they are the *only* commands this module removes.  The
#: negative lookahead keeps ``\leftarrow`` from being read as ``\left`` + arrow.
_LATEX_TYPOGRAPHY = re.compile(
    r"\\(?:left|right|big|Big|bigg|Bigg|bigl|bigr|Bigl|Bigr|biggl|biggr|"
    r"Biggl|Biggr|displaystyle|textstyle|limits|nolimits|quad|qquad)(?![A-Za-z])\s*"
)

#: A wrapper command around content: the content is the reading, so it stays and
#: the wrapper goes.  ``\mathrm{d}x`` reads as ``dx`` and ``\text{hence}`` as
#: ``hence``; a difference inside the braces is still a difference.
_LATEX_WRAPPER_COMMANDS = re.compile(
    r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|text|textrm|textnormal|"
    r"operatorname|mbox)\s*\{([^{}]*)\}"
)

#: Mathematical commands, mapped to a stable word token.  These are never
#: deleted: ``2\theta`` must not compare equal to ``2``.
_SYMBOL_NAMES: tuple[tuple[str, str], ...] = (
    ("theta", "theta"),
    ("vartheta", "theta"),
    ("varphi", "phi"),
    ("phi", "phi"),
    ("psi", "psi"),
    ("alpha", "alpha"),
    ("beta", "beta"),
    ("gamma", "gamma"),
    ("delta", "delta"),
    ("varepsilon", "epsilon"),
    ("epsilon", "epsilon"),
    ("lambda", "lambda"),
    ("mu", "mu"),
    ("nu", "nu"),
    ("rho", "rho"),
    ("sigma", "sigma"),
    ("tau", "tau"),
    ("omega", "omega"),
    ("pi", "pi"),
    ("infty", "infinity"),
    ("sin", "sin"),
    ("cos", "cos"),
    ("tan", "tan"),
    ("cot", "cot"),
    ("sec", "sec"),
    ("csc", "csc"),
    ("arcsin", "arcsin"),
    ("arccos", "arccos"),
    ("arctan", "arctan"),
    ("log", "log"),
    ("ln", "ln"),
    ("exp", "exp"),
    ("lim", "lim"),
    ("sum", "sum"),
    ("prod", "prod"),
    ("int", "int"),
    ("pm", "pm"),
    ("mp", "mp"),
    # A named relation is compared with the symbol it names, so ``\le`` and
    # ``<=`` are the same reading and ``\le`` and ``<`` are not.
    ("le", "<="),
    ("ge", ">="),
    ("ne", "!="),
    ("approx", "approx"),
    ("equiv", "equiv"),
    ("propto", "propto"),
    ("angle", "angle"),
    ("triangle", "triangle"),
    ("degree", "degree"),
    ("circ", "circ"),
    ("sim", "sim"),
    ("cong", "cong"),
)

_LATEX_SYMBOLS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\\{name}(?![A-Za-z])"), f" {token} ")
    for name, token in _SYMBOL_NAMES
)

_WRAPPERS = re.compile(r"\$+")

#: Numbers, names, two-character relations, then single symbols.  Anything else
#: becomes its own token so a difference can never cancel out.
_TOKEN = re.compile(
    r"\d+(?:\.\d+)?|[A-Za-z]+|<=|>=|!=|[+\-*/^()_=<>,;|]|\S"
)

_RELATIONS = frozenset({"<=", ">=", "!=", "=", "<", ">"})
#: Tokens a term can start after.  A closing bracket is deliberately absent:
#: ``(a+b)(a-b)`` is a product, and the second group is not free to drop.
_TERM_START = frozenset(
    {"+", "-", "*", "/", "^", "=", "<", ">", "<=", ">=", "!=", ",", "(", "|", ";"}
)

#: Tokens that make a following bracket a factor or a power rather than a pure
#: grouping: ``(a + b)c``, ``(a + b)^2``, ``2(a + b)``.  A bracket followed by
#: anything else is grouping and can be dropped without changing the reading.
#: Tokens after which a bracket is only grouping: the expression continues with
#: an operator, ends, or another group follows.
_GROUPING_AFTER = frozenset({"+", "-", "=", "<", ">", "<=", ">=", "!=", ",", ")", "|", ";"})


@dataclass(frozen=True, slots=True)
class Difference:
    """One material disagreement, kept verbatim for the reviewer."""

    kind: str
    marking: str
    independent: str
    position: int

    def describe(self) -> str:
        return (
            f"{self.kind}: this run read {self.marking!r} where the independent "
            f"reading has {self.independent!r}"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "marking": self.marking,
            "independent": self.independent,
            "position": self.position,
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    """The outcome of comparing one recorded reading with one blind reading."""

    status: str
    differences: tuple[Difference, ...] = ()

    @property
    def material(self) -> bool:
        return bool(self.differences)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted({difference.kind for difference in self.differences}))

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "material": self.material,
            "kinds": list(self.kinds),
            "differences": [difference.as_dict() for difference in self.differences],
        }


def normalise_math(text: str | None) -> str:
    """Strip what cannot change a reading: wrappers, typography, spacing.

    Nothing that names a mathematics symbol is removed.  A known command becomes
    a stable word token and an unknown one is left exactly as written (its
    backslash tokenises as its own symbol), so a macro the author of this module
    did not anticipate can never cancel a material difference.
    """

    value = (text or "").strip()
    if not value:
        return ""
    for symbol, replacement in _SUBSTITUTIONS:
        value = value.replace(symbol, replacement)
    for symbol, replacement in _SUPERSCRIPTS.items():
        value = value.replace(symbol, replacement)
    value = _WRAPPERS.sub("", value)
    for pattern, replacement in _LATEX_STRUCTURE:
        value = pattern.sub(replacement, value)
    value = _LATEX_TYPOGRAPHY.sub(" ", value)
    value = _LATEX_WRAPPER_COMMANDS.sub(r"\1", value)
    for pattern, replacement in _LATEX_SYMBOLS:
        value = pattern.sub(replacement, value)
    return re.sub(r"\s+", " ", value).strip()


#: A line break is a wrap when the expression clearly continues across it: the
#: previous line ends with an operator or an unclosed bracket, or the next line
#: begins with one.  A break between two values is a *boundary* — a separate
#: answer or a new line of working — and is never joined.
_WRAP_AFTER = frozenset({"+", "-", "*", "/", "^", "=", "<", ">", ",", "(", "[", "{", "|", "_"})
_WRAP_BEFORE = frozenset({"+", "-", "*", "/", "^", "=", "<", ">", ",", ")", "]", "}", "|", "_"})
#: The longest run of lines one written expression may be wrapped across.  A
#: window is only built from consecutive wraps, so this bounds noise, not truth.
_MAX_WRAP_LINES = 4

#: A number that ends a line: something a reader may write on the same line as
#: the working it follows.  Only the end of the line is considered, because a
#: number in the middle is part of the expression.
_TERMINAL_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_TERMINAL_PUNCTUATION = (".",)


def _strip_terminal_stop(line: str) -> str:
    """Drop a full stop a reader copied from the page, but never a decimal point.

        ``24x.`` and ``24x`` are the same reading; ``2.`` and ``2`` are too.  A
    decimal point is never trailing — ``0.75`` ends in a digit — so this
    cannot erase one.  A comma or semicolon is *not* stripped: it can continue
    a list of answers (``x = 3, y = 7``), and removing it would join two
    readings.
    """

    stripped = line.rstrip()
    while len(stripped) > 1 and stripped[-1] in _TERMINAL_PUNCTUATION:
        stripped = stripped[:-1].rstrip()
    return stripped


def _split_appended_answer(line: str) -> list[str]:
    """Split a final answer written on the same line as its working.

    An independent reader frequently merges the answer line onto the working it
    follows: ``(4x^2+12x+9)-(4x^2-12x+9)18``.  The written mathematics is not
    changed — both parts are compared as written — but a number appended after a
    closed top-level group is its own line, so a final answer the marking pass
    quoted separately is not reported as missing.  Only a number that ends the
    line is split off.
    """

    depth = 0
    for index, char in enumerate(line):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth != 0 or index + 1 >= len(line):
                continue
            tail = line[index + 1 :].strip()
            if _TERMINAL_NUMBER.match(tail):
                head = line[: index + 1].strip()
                if head:
                    return [head, tail]
    return [line]


def _continues(left: str, right: str) -> bool:
    """Whether a line break inside a transcript is a wrap, not a boundary.

    A break is a wrap when the writing itself says the expression goes on: an
    operator or an unclosed bracket at the end of the line, or an operator or a
    closing bracket at the start of the next.  Two values facing each other
    across a break are a boundary — a separate final answer, or a new line of
    working — and are never joined.
    """

    head = left.rstrip()
    tail = right.lstrip()
    if not head or not tail:
        return False
    if head.count("(") > head.count(")"):
        return True
    # ``)`` then ``(`` is an implicit product: the same expression continues.
    if head[-1] == ")" and tail[0] == "(":
        return True
    if head[-1] in _WRAP_AFTER:
        return True
    return tail[0] in _WRAP_BEFORE


def _wrapped_windows(lines: Sequence[str]) -> list[list[str]]:
    """Token windows of each line, and of each run of genuinely wrapped lines.

    A written expression can be wrapped across line breaks without changing what
    it says, and a reader may wrap it two or three times.  Every line is a
    window, and so is every run of two to four lines joined only across breaks
    the writing explains.  Because a run is built from consecutive wraps, two
    unrelated lines of working cannot be glued into a match, and a final answer
    written on its own line stays its own line.
    """

    windows: list[list[str]] = [tokens(line) for line in lines]
    for start in range(len(lines)):
        parts = [lines[start]]
        for end in range(start + 1, min(start + _MAX_WRAP_LINES, len(lines))):
            if not _continues(lines[end - 1], lines[end]):
                break
            parts.append(lines[end])
            windows.append(tokens(" ".join(parts)))
    return windows


def expressions(text: str | None) -> list[str]:
    """The lines of a transcript, normalised and without empty ones."""

    value = (text or "").strip()
    if not value:
        return []
    # Split before normalising: normalisation collapses whitespace, which would
    # join separate lines of working into one expression.
    lines: list[str] = []
    for part in re.split(r"[\n\r]+", value):
        normalised = _strip_terminal_stop(normalise_math(part))
        if normalised:
            lines.extend(_split_appended_answer(normalised))
    return [line for line in lines if line]


def tokens(text: str | None) -> list[str]:
    """The token stream of one expression, brackets distributed for comparison."""

    return flatten(_TOKEN.findall(_strip_terminal_stop(normalise_math(text))))


def _matching(stream: Sequence[str], start: int) -> int | None:
    """Index of the bracket closing ``stream[start]``, if it closes."""

    depth = 0
    for index in range(start, len(stream)):
        token = stream[index]
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _distribute(inner: Sequence[str], sign: int) -> list[str]:
    """Apply a leading sign to the terms of a bracketed group.

    Only the group's own top-level signs change.  This is sign distribution, not
    expansion: nothing is multiplied out and no term is reordered.
    """

    if sign > 0:
        return list(inner)
    result: list[str] = []
    depth = 0
    for token in inner:
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        if depth == 0 and token in {"+", "-"}:
            result.append("+" if token == "-" else "-")
        else:
            result.append(token)
    if not result:
        return ["0"]
    if result[0] not in {"+", "-"}:
        result.insert(0, "-")
    return result


def flatten(stream: Sequence[str]) -> list[str]:
    """Remove brackets whose only remaining role is a sign the reader wrote.

    ``-(a - b + c)`` becomes ``- a + b - c``; ``+(a - b)`` becomes ``a - b``; a
    bracket wrapping the whole expression is dropped.  Brackets that carry
    meaning — a product, a power, a function call — are left exactly as written.
    """

    result = list(stream)
    for _ in range(4):  # a handful of nested groups; bounded to keep it total
        changed = False
        index = 0
        while index < len(result):
            token = result[index]
            previous = result[index - 1] if index else None
            opens_group = index + 1 < len(result) and result[index + 1] == "("
            begins_term = previous is None or previous in _TERM_START
            if token in {"+", "-"} and opens_group:
                close = _matching(result, index + 1)
                if close is None:
                    index += 1
                    continue
                inner = flatten(result[index + 2 : close])
                result = (
                    result[:index]
                    + _distribute(inner, 1 if token == "+" else -1)
                    + result[close + 1 :]
                )
                changed = True
                continue
            if token == "(" and begins_term:
                close = _matching(result, index)
                after = result[close + 1] if close is not None and close + 1 < len(result) else None
                # A bracket that only groups terms is droppable: it is not a
                # factor (nothing multiplies it), not a power base, and the
                # expression continues with an operator or ends.
                inner = result[index + 1 : close] if close is not None else []
                # Anything else after the group — a power, a product, a value —
                # makes the bracket structural and it stays.
                grouping = after is None or after in _GROUPING_AFTER or (
                    after == "/" and _is_atom(inner)
                )
                if close is not None and grouping:
                    result = result[:index] + flatten(inner) + result[close + 1 :]
                    changed = True
                    continue
            index += 1
        if not changed:
            break
    return _trim(result)


def _is_atom(inner: Sequence[str]) -> bool:
    """Whether a bracket holds one value rather than an expression.

    ``(3)`` and ``(2x)`` are the same value with or without the bracket; ``(a +
b)`` is not, and its bracket carries the fraction or product boundary.
    """

    if not inner or len(inner) > 4:
        return False
    operators = {"+", "-", "*", "/", "=", "<", ">", "<=", ">=", "!="}
    return not any(token in operators for token in inner)


def _trim(stream: Sequence[str]) -> list[str]:
    """Drop a leading unary plus and any empty token left by a rewrite."""

    result = [token for token in stream if token != ""]
    while result and result[0] == "+":
        result = result[1:]
    return result


def _is_value(token: str | None) -> bool:
    """A number or a name: a token that can continue a term."""

    if not token:
        return False
    return token[0].isdigit() or token[0].isalpha()


def _contains(stream: Sequence[str], target: Sequence[str]) -> bool:
    """Whether ``target`` appears in ``stream`` as a whole term sequence.

    A match that starts or ends inside a term does not count: ``- 60x`` must not
    be found inside ``- 60x^2``, whose exponent the other reader did see.
    """

    if not target:
        return True
    span = len(target)
    for start in range(0, len(stream) - span + 1):
        if list(stream[start : start + span]) != list(target):
            continue
        before = stream[start - 1] if start else None
        after = stream[start + span] if start + span < len(stream) else None
        if before in {"^", "_"} or after in {"^", "_"}:
            continue
        if _is_value(before) or _is_value(after):
            continue
        return True
    return False


def _overlap(left: Sequence[str], right: Sequence[str]) -> float:
    """Share of the shorter stream that appears in the longer one."""

    if not left or not right:
        return 0.0
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    hits = sum(1 for token in shorter if token in longer)
    return hits / len(shorter)


def _kind_for_unmatched(target: Sequence[str], candidate: Sequence[str]) -> str:
    """Name the kind of difference when the two lines share little.

    ``3/4`` against ``0.75`` is the case this exists for: no token is shared, yet
    the difference is exactly the written form of a fraction.
    """

    if "/" in target or "/" in candidate:
        return KIND_FRACTION
    if any("." in token for token in target) or any("." in token for token in candidate):
        return KIND_DECIMAL
    return KIND_MISSING_EXPRESSION


def _kind_of_token(token: str, stream: Sequence[str], position: int) -> str:
    """Name a difference from the one token a reader has and the other lacks."""

    before = stream[position - 1] if position else None
    if token in {"+", "-"}:
        return KIND_SIGN
    if token in _RELATIONS:
        return KIND_RELATION
    if token == "^" or before == "^":
        return KIND_EXPONENT
    if token in {"(", ")"}:
        return KIND_BRACKET
    if token == "/" or before == "/":
        return KIND_FRACTION
    if "." in token:
        return KIND_DECIMAL
    return KIND_TERM


def _classify(marking: Sequence[str], independent: Sequence[str], position: int) -> str:
    """Name the kind of detail two aligned streams disagree on."""

    left = marking[position] if position < len(marking) else None
    right = independent[position] if position < len(independent) else None
    if left is None and right is not None:
        return _kind_of_token(right, independent, position)
    if right is None and left is not None:
        return _kind_of_token(left, marking, position)
    if left is None or right is None:
        return KIND_MISSING_EXPRESSION
    if {left, right} == {"+", "-"}:
        return KIND_SIGN
    if left in _RELATIONS or right in _RELATIONS:
        return KIND_RELATION
    before = marking[position - 1] if position else None
    if left == "^" or right == "^" or before == "^":
        return KIND_EXPONENT
    if left in {"(", ")"} or right in {"(", ")"}:
        return KIND_BRACKET
    if left == "/" or right == "/" or before == "/":
        return KIND_FRACTION
    if left.replace(".", "") == right.replace(".", "") and (
        "." in left or "." in right
    ):
        return KIND_DECIMAL
    return KIND_TERM


def _differences(
    marking: Sequence[str],
    independent: Sequence[str],
    *,
    marking_text: str,
    independent_text: str,
) -> list[Difference]:
    """Every independent material difference between two token streams.

    The streams are aligned once, so one underlying mismatch produces one block
    rather than a cascade: a replaced token is one difference, and a shifted
    stream is one insertion, not one difference per following token.  Distinct
    mismatches stay distinct — two wrong signs are two findings, which is what a
    reviewer needs in order to check both.
    """

    matcher = difflib.SequenceMatcher(
        a=list(marking), b=list(independent), autojunk=False
    )
    found: list[Difference] = []
    seen: set[tuple[str, int]] = set()
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        position = left_start if left_start < len(marking) else right_start
        kind = _classify_block(
            marking, independent, left_start, left_end, right_start, right_end
        )
        if (kind, position) in seen:
            continue
        seen.add((kind, position))
        found.append(
            Difference(
                kind=kind,
                marking=marking_text,
                independent=independent_text,
                position=position,
            )
        )
    if not found:  # the streams are equal; the caller never reaches here
        found.append(
            Difference(
                kind=KIND_TERM,
                marking=marking_text,
                independent=independent_text,
                position=0,
            )
        )
    return found


def _classify_block(
    marking: Sequence[str],
    independent: Sequence[str],
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> str:
    """Classify one aligned mismatch block.

    The first token that actually differs decides the kind.  For an insertion or
    a deletion the present token decides, so a lost bracket is still reported as
    a bracket rather than as a missing expression.
    """

    if left_start < left_end and right_start < right_end:
        offset = 0
        while (
            left_start + offset < left_end
            and right_start + offset < right_end
            and marking[left_start + offset] == independent[right_start + offset]
        ):
            offset += 1
        return _classify(marking, independent, left_start + offset)
    if right_start < right_end:
        return _kind_of_token(independent[right_start], independent, right_start)
    return _kind_of_token(marking[left_start], marking, left_start)


def compare_readings(
    marking: Iterable[str | None], independent: str | None
) -> Comparison:
    """Compare what the marking pass recorded with what a blind reader saw.

    ``marking`` is everything the marking pass claims to have read for one
    question: its recorded answer and each quotation it awarded.  The blind
    reading is a full transcript of the question, so it may contain more lines
    than the marking pass quoted — that is not a difference.  What must appear
    is what the marking pass said it read.
    """

    recorded = [
        expression
        for text in marking
        for expression in expressions(text)
    ]
    blind_lines = expressions(independent)
    if not recorded and not blind_lines:
        return Comparison(STATUS_ABSENT)
    if not recorded:
        return Comparison(
            STATUS_DIFFERS,
            (
                Difference(
                    kind=KIND_WORKING_NOT_RECORDED,
                    marking="",
                    independent=(blind_lines[0] if blind_lines else ""),
                    position=0,
                ),
            ),
        )
    if not blind_lines:
        return Comparison(
            STATUS_DIFFERS,
            (
                Difference(
                    kind=KIND_INDEPENDENT_ABSENT,
                    marking=recorded[0],
                    independent="",
                    position=0,
                ),
            ),
        )

    # A recorded expression may be found in one line of the blind reading or in
    # a run of lines the writing itself joins (see ``_wrapped_windows``).
    windows = _wrapped_windows(blind_lines)

    differences: list[Difference] = []
    for expression in recorded:
        target = tokens(expression)
        if not target or any(_contains(window, target) for window in windows):
            continue
        best = max(blind_lines, key=lambda line: _overlap(target, tokens(line)))
        candidate = tokens(best)
        if _overlap(target, candidate) < 0.5:
            differences.append(
                Difference(
                    kind=_kind_for_unmatched(target, candidate),
                    marking=expression,
                    independent=best,
                    position=0,
                )
            )
            continue
        differences.extend(
            _differences(
                target,
                candidate,
                marking_text=expression,
                independent_text=best,
            )
        )

    if differences:
        return Comparison(STATUS_DIFFERS, tuple(differences))
    return Comparison(STATUS_AGREES)


__all__ = [
    "STATUS_ABSENT",
    "STATUS_AGREES",
    "STATUS_DIFFERS",
    "STATUS_UNVERIFIABLE",
    "Comparison",
    "Difference",
    "compare_readings",
    "expressions",
    "flatten",
    "normalise_math",
    "tokens",
]
