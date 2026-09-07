"""Detect degenerated / repetitive-garbage model output.

Small or under-trained models (e.g. 7B Qwen) sometimes collapse into a
repetition loop after context compaction + truncation-continuation prompts,
emitting hundreds of copies of a short fragment like ``(c#\\b ( (c#\\c ...``
or ``\\n\\n\\n\\n\\n``.  This module provides a fast heuristic that flags
such output so the conversation loop can retry on a fallback model instead
of shipping the garbage to the user.

Heuristics (any one triggers detection):

1. **Short-fragment repetition** — the most common 8-32 char substring
   accounts for >60% of the total length, with >8 repetitions.
2. **Token-level repetition** — after splitting on whitespace, the
   unique-token ratio is <0.15 over >200 tokens.
3. **Backslash-fragment flood** — >40% of non-whitespace characters are
   part of ``\\X`` (backslash + single char) tokens, indicating LaTeX /
   escape-sequence degeneration.
4. **Parenthesis-token flood** — >40% of tokens match ``\\(?[A-Za-z0-9#]?``
   parenthesis fragments like ``(c#\\b``, ``( 4\\c``.

The detector is deliberately conservative — it only fires on long output
(>300 chars) with extreme repetition, so valid repetitive content (code
with repeated patterns, tabular data) is not falsely flagged.
"""

from __future__ import annotations

import re
from collections import Counter

# Minimum length to even check — short responses can't degenerate meaningfully.
_MIN_LENGTH = 400

# Fragment repetition thresholds — real degeneration shows 100+ repeats
# covering >70% of output.  Conservative thresholds avoid false positives
# on legitimate repetitive content (lists, poetry, tabular data).
_FRAGMENT_MIN_LEN = 8
_FRAGMENT_MAX_LEN = 32
_FRAGMENT_REPEAT_MIN = 20
_FRAGMENT_DOMINANCE = 0.70  # most common fragment covers >70% of text

# Token repetition thresholds — garbled output measured 7-8% unique.
# Normal repetitive text stays above 12% unique even with heavy reuse.
_TOKEN_UNIQUE_RATIO_MAX = 0.10
_TOKEN_COUNT_MIN = 300

# Flood thresholds (fraction of tokens matching a degenerate pattern)
_FLOOD_FRACTION = 0.40

# Backslash-fragment: \X where X is a single non-space char (LaTeX / escape degeneration)
_BACKSLASH_FRAGMENT_RE = re.compile(r'\\[^\s\\]')

# Parenthesis-fragment: ( optionally followed by one alnum/# then \X or bare letter
_PAREN_FRAGMENT_RE = re.compile(r'\(\s?[A-Za-z0-9#]?\\?[A-Za-z0-9]?')

# Collapsed whitespace run (3+ newlines or 3+ spaces repeated)
_WS_RUN_RE = re.compile(r'(?:\n{3,}|\t{3,}| {5,})')


def detect_degeneration(text: str) -> tuple[bool, str | None]:
    """Return ``(is_degenerated, reason)``.

    ``reason`` is a short human-readable string when degeneration is detected,
    ``None`` otherwise.  The check is O(n) and safe to run on every final
    response.
    """
    if not text or len(text) < _MIN_LENGTH:
        return False, None

    # Strip code blocks before analysis — repeated code patterns inside
    # fenced blocks are legitimate and should not trigger the detector.
    stripped = re.sub(r'```[\s\S]*?```', '', text)
    stripped = re.sub(r'`[^`\n]*`', '', stripped)
    # Also strip think/reasoning blocks
    stripped = re.sub(r'<(?:REASONING_SCRATCHPAD|think|reasoning)>[\s\S]*?</(?:REASONING_SCRATCHPAD|think|reasoning)>', '', stripped, flags=re.IGNORECASE)

    if len(stripped) < _MIN_LENGTH:
        return False, None

    # Heuristic 1: short-fragment repetition
    reason = _check_fragment_repetition(stripped)
    if reason:
        return True, reason

    # Heuristic 2: token-level repetition
    reason = _check_token_repetition(stripped)
    if reason:
        return True, reason

    # Heuristic 3: backslash-fragment flood
    reason = _check_backslash_flood(stripped)
    if reason:
        return True, reason

    # Heuristic 4: parenthesis-fragment flood
    reason = _check_paren_flood(stripped)
    if reason:
        return True, reason

    return False, None


def _check_fragment_repetition(text: str) -> str | None:
    """Detect a single short fragment dominating the output."""
    # Sample candidate fragments by taking sliding windows at a few offsets.
    # Checking every offset is O(n^2); sampling keeps it near-linear.
    n = len(text)
    candidates: set[str] = set()
    for start in (0, n // 4, n // 2, 3 * n // 4):
        for length in (_FRAGMENT_MIN_LEN, 16, 24, _FRAGMENT_MAX_LEN):
            if start + length <= n:
                candidates.add(text[start:start + length])
    # Also add the first 8-32 chars — degeneration often starts at the top.
    for length in (_FRAGMENT_MIN_LEN, 16, _FRAGMENT_MAX_LEN):
        if length <= n:
            candidates.add(text[:length])

    for frag in candidates:
        if not frag.strip():
            continue
        count = text.count(frag)
        if count >= _FRAGMENT_REPEAT_MIN:
            dominance = (count * len(frag)) / n
            if dominance >= _FRAGMENT_DOMINANCE:
                preview = frag.replace('\n', '\\n')[:40]
                return f"fragment_repetition: '{preview}' x{count} ({dominance:.0%} of output)"
    return None


def _check_token_repetition(text: str) -> str | None:
    """Detect very low unique-token ratio (token-level degeneration)."""
    tokens = text.split()
    if len(tokens) < _TOKEN_COUNT_MIN:
        return None
    unique = len(set(tokens))
    ratio = unique / len(tokens)
    if ratio < _TOKEN_UNIQUE_RATIO_MAX:
        return f"token_repetition: {unique}/{len(tokens)} unique ({ratio:.0%})"
    return None


def _check_backslash_flood(text: str) -> str | None:
    """Detect a flood of \\X backslash-fragments (LaTeX/escape degeneration)."""
    matches = _BACKSLASH_FRAGMENT_RE.findall(text)
    if not matches:
        return None
    # Count non-whitespace characters
    non_ws = len(re.sub(r'\s', '', text))
    if non_ws == 0:
        return None
    backslash_chars = sum(len(m) for m in matches)
    fraction = backslash_chars / non_ws
    if fraction >= _FLOOD_FRACTION and len(matches) >= 20:
        return f"backslash_flood: {len(matches)} \\X fragments ({fraction:.0%} of non-ws chars)"
    return None


def _check_paren_flood(text: str) -> str | None:
    """Detect a flood of parenthesis-fragment tokens like (c#\\b, ( 4\\c."""
    tokens = text.split()
    if len(tokens) < 50:
        return None
    paren_tokens = [t for t in tokens if _PAREN_FRAGMENT_RE.match(t)]
    if not paren_tokens:
        return None
    fraction = len(paren_tokens) / len(tokens)
    if fraction >= _FLOOD_FRACTION:
        return f"paren_flood: {len(paren_tokens)}/{len(tokens)} paren-frag tokens ({fraction:.0%})"
    return None
