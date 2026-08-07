"""Everything that happens to a generated answer before the user sees it.

  1. shape check                 (0ms)
  2. PII leak scan -> redact     (0ms) — an answer may never emit PII even if the
                                  source chunk somehow carried it
  3. groundedness score          (1 model call) — the hallucination gate
  4. policy check                (1 model call, only when context is non-empty)

Steps 3 and 4 run in parallel; together they add one round-trip, not two.
"""

from __future__ import annotations

from ai.llm import chat_json, parallel_map
from ai.prompts import GROUNDEDNESS_PROMPT, POLICY_CHECK_PROMPT
from guardrails.pii import has_leak, redact_text
from guardrails.validators import check_response_shape, validate_json
from observability.telemetry import log
from rag.schemas import GroundednessVerdict, GuardrailResult, PolicyVerdict

# Below this the answer is not defensible as grounded. Tune during the demo dry-run —
# small local models score conservatively. [PLACEHOLDER: tune per domain risk appetite]
GROUNDEDNESS_FLOOR = 0.5

# Below this we refuse outright rather than caveat.
GROUNDEDNESS_REFUSE = 0.25

CAVEAT = "\n\n> ⚠️ Partially grounded — verify against the cited sources before acting."


def check_output(
    answer: str,
    context: str,
    trace=None,
    policy_prompt: str | None = None,
) -> tuple[GuardrailResult, float]:
    """Returns (result, groundedness). result.text is the answer to actually send.

    `policy_prompt` lets a caller supply a policy set appropriate to its output
    shape while sharing this one mechanism — same PII scan, same groundedness
    scorer, same audit path. The triage graph passes
    prompts.TRIAGE_POLICY_CHECK_PROMPT because the generic set treats stating a
    severity as an invented claim, which is exactly what a triage decision is
    supposed to do; see that prompt's comment. Defaults to the KB-chat set.
    """
    ok, reason = check_response_shape(answer)
    if not ok:
        return GuardrailResult(allowed=False, reason=reason, text=""), 0.0

    leaks = has_leak(answer)
    safe_answer = redact_text(answer) if leaks else answer
    findings = [{"type": f"pii_leak:{leak['type']}"} for leak in leaks]
    if leaks:
        log.warning("output contained %d PII leaks — redacted", len(leaks))

    if not context.strip():
        # Nothing was retrieved; there is nothing to be grounded against.
        return (
            GuardrailResult(allowed=True, reason="no context", text=safe_answer, findings=findings),
            0.0,
        )

    grounded_raw, policy_raw = parallel_map(
        lambda fn: fn(),
        [
            lambda: chat_json(
                GROUNDEDNESS_PROMPT.format(context=context, answer=safe_answer),
                fast=True,
                trace=trace,
            ),
            lambda: chat_json(
                (policy_prompt or POLICY_CHECK_PROMPT).format(context=context, answer=safe_answer),
                fast=True,
                trace=trace,
            ),
        ],
    )

    grounded = validate_json(grounded_raw, GroundednessVerdict)
    policy = validate_json(policy_raw, PolicyVerdict)

    if policy.violation:
        log.warning("output blocked by policy %s: %s", policy.policy, policy.reason)
        return (
            GuardrailResult(
                allowed=False,
                reason=f"Blocked by policy: {policy.policy or 'unspecified'}",
                text="",
                findings=findings + [{"type": "policy_violation", "policy": policy.policy}],
            ),
            grounded.groundedness,
        )

    if grounded.groundedness < GROUNDEDNESS_REFUSE:
        return (
            GuardrailResult(
                allowed=False,
                reason="The generated answer was not supported by the retrieved sources.",
                text="",
                findings=findings
                + [{"type": "hallucination", "claims": grounded.unsupported_claims[:3]}],
            ),
            grounded.groundedness,
        )

    if grounded.groundedness < GROUNDEDNESS_FLOOR:
        safe_answer += CAVEAT
        findings.append({"type": "low_groundedness", "score": grounded.groundedness})

    return (
        GuardrailResult(allowed=True, reason="", text=safe_answer, findings=findings),
        grounded.groundedness,
    )
