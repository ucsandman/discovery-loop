"""Apply the edit blocks a generation returns instead of a whole rewritten file.

A cvrp generation rewrites a 48 KB solver to change one neighbourhood, and the slot hits its $40 cap after
about ten of those (2026-09-16: $38.51 for 10 candidates). An edit block carries only the lines that change,
so the same allowance buys more attempts. The format is deliberately the widely used SEARCH/REPLACE shape:

    <<<<<<< SEARCH
    the exact lines to find
    =======
    the lines that replace them
    >>>>>>> REPLACE

Every SEARCH must match the current file exactly once. A block that matches nothing, or matches in more than
one place, fails the whole edit rather than guessing: a silently misapplied edit would be evaluated as if the
model had proposed it.
"""

from __future__ import annotations

import re


_BLOCK = re.compile(
    r"^<{5,9} SEARCH[^\n]*\n(?P<search>.*?)^={5,9}[^\n]*\n(?P<replace>.*?)^>{5,9} REPLACE[^\n]*$",
    re.MULTILINE | re.DOTALL,
)
MAX_BLOCKS = 40


def parse_blocks(text):
    """Every SEARCH/REPLACE pair in the response, in the order the model wrote them."""
    if not isinstance(text, str):
        return []
    return [(match.group("search"), match.group("replace")) for match in _BLOCK.finditer(text)]


def apply_blocks(source, text):
    """Return (patched_source, error). ``error`` is None only when every block applied exactly once."""
    if not isinstance(source, str) or not source:
        return None, "no incumbent source to edit"
    blocks = parse_blocks(text)
    if not blocks:
        return None, "response contained no SEARCH/REPLACE block"
    if len(blocks) > MAX_BLOCKS:
        return None, f"response contained {len(blocks)} edit blocks; the limit is {MAX_BLOCKS}"
    patched = source.replace("\r\n", "\n")
    for index, (search, replace) in enumerate(blocks, start=1):
        search = search.replace("\r\n", "\n")
        replace = replace.replace("\r\n", "\n")
        if not search.strip():
            return None, f"edit block {index} has an empty SEARCH section"
        occurrences = patched.count(search)
        if occurrences == 0:
            head = search.strip().splitlines()[0][:120] if search.strip() else ""
            return None, f"edit block {index} did not match the file (looked for: {head})"
        if occurrences > 1:
            head = search.strip().splitlines()[0][:120]
            return None, f"edit block {index} matched {occurrences} places; it must match exactly one (at: {head})"
        patched = patched.replace(search, replace, 1)
    if patched == source.replace("\r\n", "\n"):
        return None, "edit blocks left the file unchanged"
    return patched, None


DIFF_OUTPUT_FORMAT = """OUTPUT FORMAT: the tagged IDEA line, then one or more edit blocks against the file above.
Each block must be exactly:

<<<<<<< SEARCH
(lines copied verbatim from the file above)
=======
(the lines that replace them)
>>>>>>> REPLACE

Copy the SEARCH lines character for character from the file above, including indentation, and include enough
surrounding lines that they appear exactly once in the file. Do not output the whole file, a unified diff, or
any prose after the last block. To add a new function, SEARCH for an existing neighbouring line and repeat it
in the REPLACE section along with the new code."""
