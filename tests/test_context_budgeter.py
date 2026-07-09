from agent.context_budgeter import (
    ContextBudgetConfig,
    apply_context_budget,
    resolve_target_input_tokens,
)
from agent.model_metadata import estimate_request_tokens_rough


def _msg(role: str, content: str, **extra):
    data = {"role": role, "content": content}
    data.update(extra)
    return data


def test_resolve_target_prefers_explicit_operator_cap():
    cfg = ContextBudgetConfig(enabled=True, max_input_tokens=120_000)
    assert resolve_target_input_tokens(config=cfg, context_length=1_000_000, max_tokens=32_000) == 120_000


def test_budgeter_is_noop_when_disabled():
    messages = [_msg("system", "s"), _msg("user", "u" * 10_000)]
    out, metrics = apply_context_budget(
        messages,
        config=ContextBudgetConfig(enabled=False, max_input_tokens=100),
    )
    assert out == messages
    assert metrics.reason == "disabled"
    assert metrics.removed_messages == 0


def test_budgeter_trims_middle_context_to_target():
    messages = [_msg("system", "stable system prompt")]
    messages.append(_msg("user", "first user turn"))
    messages.append(_msg("assistant", "first assistant turn"))
    for i in range(20):
        messages.append(_msg("user", f"middle user {i} " + ("x" * 2_000)))
        messages.append(_msg("assistant", f"middle assistant {i} " + ("y" * 2_000)))
    messages.append(_msg("user", "latest question must remain"))

    before = estimate_request_tokens_rough(messages)
    out, metrics = apply_context_budget(
        messages,
        config=ContextBudgetConfig(
            enabled=True,
            max_input_tokens=4_500,
            protect_first_n=2,
            protect_last_n=4,
            min_trim_tokens=1,
        ),
    )
    after = estimate_request_tokens_rough(out)

    assert before > 4_500
    assert after <= 4_500
    assert metrics.reason == "trimmed"
    assert metrics.removed_messages > 0
    assert metrics.removed_tokens > 0
    assert metrics.reduction_ratio > 0
    assert out[0]["role"] == "system"
    assert "latest question must remain" in str(out[-1]["content"])
    assert "Hermes context budgeter" in str(out[-1]["content"])


def test_budgeter_keeps_tail_tool_group_together():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "terminal", "arguments": "{}"},
    }
    messages = [
        _msg("system", "s"),
        _msg("user", "first"),
        _msg("assistant", "a"),
        _msg("user", "old " + ("x" * 10_000)),
        _msg("assistant", "tool", tool_calls=[tool_call]),
        {"role": "tool", "tool_call_id": "call_1", "name": "terminal", "content": "result"},
        _msg("user", "latest"),
    ]
    out, metrics = apply_context_budget(
        messages,
        config=ContextBudgetConfig(
            enabled=True,
            max_input_tokens=1_500,
            protect_first_n=1,
            protect_last_n=2,
            min_trim_tokens=1,
        ),
    )

    roles = [m.get("role") for m in out]
    assert "tool" in roles
    tool_index = roles.index("tool")
    assert out[tool_index - 1].get("role") == "assistant"
    assert out[tool_index - 1].get("tool_calls")
    assert metrics.removed_messages > 0


def test_budgeter_removes_tool_result_when_parent_call_is_trimmed():
    tool_call = {
        "id": "call_parent",
        "type": "function",
        "function": {"name": "terminal", "arguments": "{}"},
    }
    messages = [
        _msg("system", "s"),
        _msg("user", "first"),
        _msg("assistant", "keep head"),
        _msg("assistant", "large tool request " + ("x" * 10_000), tool_calls=[tool_call]),
        {"role": "tool", "tool_call_id": "call_parent", "name": "terminal", "content": "result"},
        _msg("user", "latest question must remain"),
    ]

    out, metrics = apply_context_budget(
        messages,
        config=ContextBudgetConfig(
            enabled=True,
            max_input_tokens=1_500,
            protect_first_n=1,
            protect_last_n=1,
            min_trim_tokens=1,
        ),
    )

    assert metrics.reason == "trimmed"
    assert all(m.get("tool_call_id") != "call_parent" for m in out)
    assert all(
        "call_parent" not in {tc.get("id") for tc in (m.get("tool_calls") or [])}
        for m in out
    )
    assert "latest question must remain" in str(out[-1]["content"])
