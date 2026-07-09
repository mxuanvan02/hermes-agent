"""Per-request context budgeting for API-bound message payloads.

The compressor owns durable session compaction.  This module is a lighter
preflight guard that trims the API copy only when a single request is about to
exceed an operator-defined budget.  It keeps the persisted transcript intact.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agent.model_metadata import (
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextBudgetConfig:
    enabled: bool = False
    max_input_tokens: int = 0
    target_context_ratio: float = 0.35
    reserve_output_tokens: int = 16_384
    safety_margin_tokens: int = 8_192
    protect_first_n: int = 2
    protect_last_n: int = 16
    min_trim_tokens: int = 4_096
    marker_enabled: bool = True


@dataclass(frozen=True)
class ContextBudgetMetrics:
    enabled: bool
    target_input_tokens: int
    before_tokens: int
    after_tokens: int
    tool_tokens: int
    message_tokens_before: int
    message_tokens_after: int
    removed_messages: int
    removed_tokens: int
    reduction_ratio: float
    budget_hit: bool
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "target_input_tokens": self.target_input_tokens,
            "before_tokens": self.before_tokens,
            "after_tokens": self.after_tokens,
            "tool_tokens": self.tool_tokens,
            "message_tokens_before": self.message_tokens_before,
            "message_tokens_after": self.message_tokens_after,
            "removed_messages": self.removed_messages,
            "removed_tokens": self.removed_tokens,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "budget_hit": self.budget_hit,
            "reason": self.reason,
        }


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def context_budget_config_from_mapping(raw: Any) -> ContextBudgetConfig:
    """Build config from YAML mapping plus env overrides."""
    cfg = raw if isinstance(raw, dict) else {}
    enabled = str(cfg.get("enabled", False)).strip().lower() in {"1", "true", "yes", "on"}
    return ContextBudgetConfig(
        enabled=_env_bool("HERMES_CONTEXT_BUDGET_ENABLED", enabled),
        max_input_tokens=_env_int("HERMES_CONTEXT_BUDGET_MAX_INPUT_TOKENS", int(cfg.get("max_input_tokens", 0) or 0)),
        target_context_ratio=_env_float("HERMES_CONTEXT_BUDGET_TARGET_RATIO", float(cfg.get("target_context_ratio", 0.35) or 0.35)),
        reserve_output_tokens=_env_int("HERMES_CONTEXT_BUDGET_RESERVE_OUTPUT_TOKENS", int(cfg.get("reserve_output_tokens", 16_384) or 16_384)),
        safety_margin_tokens=_env_int("HERMES_CONTEXT_BUDGET_SAFETY_MARGIN_TOKENS", int(cfg.get("safety_margin_tokens", 8_192) or 8_192)),
        protect_first_n=max(0, _env_int("HERMES_CONTEXT_BUDGET_PROTECT_FIRST_N", int(cfg.get("protect_first_n", 2) or 2))),
        protect_last_n=max(1, _env_int("HERMES_CONTEXT_BUDGET_PROTECT_LAST_N", int(cfg.get("protect_last_n", 16) or 16))),
        min_trim_tokens=max(0, _env_int("HERMES_CONTEXT_BUDGET_MIN_TRIM_TOKENS", int(cfg.get("min_trim_tokens", 4_096) or 4_096))),
        marker_enabled=_env_bool("HERMES_CONTEXT_BUDGET_MARKER_ENABLED", str(cfg.get("marker_enabled", True)).lower() in {"1", "true", "yes", "on"}),
    )


def resolve_target_input_tokens(
    *,
    config: ContextBudgetConfig,
    context_length: Optional[int],
    max_tokens: Optional[int],
) -> int:
    """Resolve the request input budget in tokens.

    ``max_input_tokens`` is a hard operator cap.  Otherwise derive a budget from
    the model context length while reserving room for output and provider drift.
    """
    explicit = int(config.max_input_tokens or 0)
    if explicit > 0:
        return explicit

    ctx = int(context_length or 0)
    if ctx <= 0:
        return 0
    ratio_target = int(ctx * max(0.05, min(config.target_context_ratio, 0.95)))
    output_reserve = int(max_tokens or config.reserve_output_tokens or 0)
    window_target = max(ctx - output_reserve - int(config.safety_margin_tokens or 0), 0)
    if window_target <= 0:
        return ratio_target
    return max(1, min(ratio_target, window_target))


def _message_token_counts(messages: Sequence[Dict[str, Any]]) -> List[int]:
    return [max(1, estimate_messages_tokens_rough([m])) for m in messages]


def _tool_token_count(tools: Any) -> int:
    if not tools:
        return 0
    return max(0, estimate_request_tokens_rough([], tools=tools))


def _append_marker_to_latest_user(messages: List[Dict[str, Any]], marker: str) -> List[Dict[str, Any]]:
    if not marker:
        return messages
    out = [m.copy() for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") != "user":
            continue
        content = out[i].get("content", "")
        if isinstance(content, str):
            out[i]["content"] = content + "\n\n" + marker
        elif isinstance(content, list):
            out[i]["content"] = [*content, {"type": "text", "text": marker}]
        else:
            out[i]["content"] = str(content) + "\n\n" + marker
        return out
    return out


def _tool_call_ids(message: Dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for tc in message.get("tool_calls") or []:
        if isinstance(tc, dict):
            cid = tc.get("id") or tc.get("tool_call_id")
        else:
            cid = getattr(tc, "id", None) or getattr(tc, "tool_call_id", None)
        if cid:
            ids.add(str(cid))
    return ids


def _expand_tool_group_removals(
    messages: Sequence[Dict[str, Any]],
    removed_indices: set[int],
) -> set[int]:
    """Expand removals so tool-call requests and results stay paired.

    OpenAI-compatible providers reject a request if a ``role=tool`` result is
    present without its parent assistant ``tool_calls`` message.  The budgeter
    removes an API-only middle slice, so it must avoid cutting those pairs in
    half even when removing one large message would already satisfy the budget.
    """
    expanded = set(removed_indices)
    changed = True
    while changed:
        changed = False
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant" and msg.get("tool_calls"):
                call_ids = _tool_call_ids(msg)
                if not call_ids:
                    continue
                group = {i}
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    if str(messages[j].get("tool_call_id") or "") in call_ids:
                        group.add(j)
                    j += 1
                if expanded.intersection(group) and not group.issubset(expanded):
                    expanded.update(group)
                    changed = True
            elif role == "tool" and i in expanded:
                cid = str(msg.get("tool_call_id") or "")
                if not cid:
                    continue
                for j in range(i - 1, -1, -1):
                    prev = messages[j]
                    if prev.get("role") == "assistant" and cid in _tool_call_ids(prev):
                        if j not in expanded:
                            expanded.add(j)
                            changed = True
                        break
                    if prev.get("role") not in {"tool", "assistant"}:
                        break
    return expanded


def apply_context_budget(
    messages: Sequence[Dict[str, Any]],
    *,
    tools: Any = None,
    config: Optional[ContextBudgetConfig] = None,
    context_length: Optional[int] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], ContextBudgetMetrics]:
    """Return an API-only message list that fits the configured budget.

    The policy is conservative: protect the system prompt, a small head window,
    and the recent tail, then remove the largest removable middle messages until
    the request is under budget or no removable messages remain.
    """
    cfg = config or ContextBudgetConfig()
    original = [m.copy() for m in messages]
    tool_tokens = _tool_token_count(tools)
    before_tokens = estimate_request_tokens_rough(original, tools=tools)
    msg_tokens_before = max(0, before_tokens - tool_tokens)
    target = resolve_target_input_tokens(
        config=cfg,
        context_length=context_length,
        max_tokens=max_tokens,
    )

    def metrics(out: List[Dict[str, Any]], *, removed: int, removed_tokens: int, reason: str) -> ContextBudgetMetrics:
        after = estimate_request_tokens_rough(out, tools=tools)
        msg_after = max(0, after - tool_tokens)
        return ContextBudgetMetrics(
            enabled=cfg.enabled,
            target_input_tokens=target,
            before_tokens=before_tokens,
            after_tokens=after,
            tool_tokens=tool_tokens,
            message_tokens_before=msg_tokens_before,
            message_tokens_after=msg_after,
            removed_messages=removed,
            removed_tokens=removed_tokens,
            reduction_ratio=(removed_tokens / before_tokens) if before_tokens > 0 else 0.0,
            budget_hit=bool(target and after > target),
            reason=reason,
        )

    if not cfg.enabled:
        return original, metrics(original, removed=0, removed_tokens=0, reason="disabled")
    if target <= 0:
        return original, metrics(original, removed=0, removed_tokens=0, reason="no_target")
    if before_tokens <= target:
        return original, metrics(original, removed=0, removed_tokens=0, reason="under_budget")

    counts = _message_token_counts(original)
    n = len(original)
    system_indices = {i for i, m in enumerate(original) if m.get("role") == "system"}
    first_user = next((i for i, m in enumerate(original) if m.get("role") == "user"), 0)
    protect_until = min(n, first_user + 1 + cfg.protect_first_n)
    protect_from = max(0, n - cfg.protect_last_n)

    # Keep tool-call groups intact at the tail boundary.  If the tail would
    # start on a tool result, include the preceding assistant call as part of
    # the protected tail instead of leaving an orphan tool message.
    while protect_from > protect_until and original[protect_from].get("role") == "tool":
        protect_from -= 1
    if protect_from > protect_until and original[protect_from - 1].get("role") == "assistant" and original[protect_from - 1].get("tool_calls"):
        protect_from -= 1

    # Avoid leaving a protected head assistant that expects tool results which
    # are then removed from the middle.
    while protect_until > 0 and protect_until < protect_from:
        prev = original[protect_until - 1]
        if prev.get("role") == "assistant" and prev.get("tool_calls"):
            protect_until -= 1
            continue
        break

    removable = list(range(protect_until, protect_from))
    removable = [i for i in removable if i not in system_indices]
    if not removable:
        return original, metrics(original, removed=0, removed_tokens=0, reason="no_removable_messages")

    removed_indices = set()
    removed_tokens = 0
    current = before_tokens
    # Remove a contiguous middle window from oldest to newest.  This may discard
    # more than an arbitrary largest-message strategy, but it preserves the
    # structural integrity of the remaining conversation far better.
    for i in removable:
        if current <= target:
            break
        removed_indices.add(i)
        removed_tokens += counts[i]
        current -= counts[i]

    expanded_removed_indices = _expand_tool_group_removals(original, removed_indices)
    if expanded_removed_indices != removed_indices:
        removed_indices = expanded_removed_indices
        removed_tokens = sum(counts[i] for i in removed_indices)

    if removed_tokens < cfg.min_trim_tokens:
        return original, metrics(original, removed=0, removed_tokens=0, reason="trim_too_small")

    trimmed = [m.copy() for i, m in enumerate(original) if i not in removed_indices]
    if cfg.marker_enabled and removed_indices:
        marker = (
            "[Hermes context budgeter: omitted "
            f"{len(removed_indices)} older middle message(s), roughly "
            f"{removed_tokens:,} tokens, from this API request only. "
            "Use session/file/search tools if those details are needed.]"
        )
        trimmed = _append_marker_to_latest_user(trimmed, marker)

    return trimmed, metrics(trimmed, removed=len(removed_indices), removed_tokens=removed_tokens, reason="trimmed")
