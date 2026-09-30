"""Markdown report of an agent evaluation run (the JSON next to it has every detail)."""

import math
from collections.abc import Sequence
from typing import Any

from evals.metrics.agent import PASS_CHECKS, RunRecord


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return round(ordered[rank - 1], 2)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _usd(value: float | None) -> str:
    return "n/a (no price)" if value is None else f"${value:.4f}"


def render_markdown(
    config: dict[str, Any],
    summary: dict[str, Any],
    gate_reasons: list[str],
    usage: dict[str, Any],
    records: Sequence[RunRecord],
) -> str:
    k = summary["repeats"]
    lines = [
        f"# Agent evaluation ({config['split']})",
        "",
        f"- Commit `{config['commit']}` · dataset `{config['dataset_sha256']}` · "
        f"started {config['started_at']}",
        f"- Agent: `{config['agent_model']}` with `{config['agent_prompt']}`, retrieval "
        f"`{config['retrieval_mode']}` (top {config['top_k']})",
        f"- Judge: `{config['judge_model']}` with `{config['judge_prompt']}`",
        f"- {summary['cases']} case(s) x {k} repeat(s) = {summary['runs']} run(s)"
        + (" · **partial run** (`--limit` / `--cases`)" if config["partial"] else ""),
        "",
        "## Quality gate: " + ("PASS" if not gate_reasons else "FAIL"),
        "",
    ]
    lines += [f"- {reason}" for reason in gate_reasons] or ["- All conditions met."]
    lines += [
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Pass rate (runs) | {_fmt(summary['pass_rate'])} |",
        f"| pass^{k} (cases passing every repeat) | {_fmt(summary['pass_hat_k'])} |",
        f"| Critical cases failed | {len(summary['critical_failed'])} of "
        f"{summary['critical_cases']} |",
        f"| Safety violations | {summary['safety_violations']} |",
        f"| Runs with errors | {summary['errors']} |",
    ]
    lines += [f"| Check `{name}` | {_fmt(summary['checks'][name])} |" for name in PASS_CHECKS]
    lines += [
        f"| Key-fact recall (judge) | {_fmt(summary['key_fact_recall'])} |",
        f"| Evidence recall (agent retrieval) | {_fmt(summary['evidence_recall'])} |",
        f"| Structured answers (`responder`) | {_fmt(summary['structured_answers'])} |",
        "",
        "Checks are rates over the runs where they apply (`n/a`: no run applies).",
        "",
        "## By category",
        "",
        "| Category | Cases | Pass rate |",
        "|---|---|---|",
    ]
    lines += [
        f"| {category} | {row['cases']} | {_fmt(row['pass_rate'])} |"
        for category, row in summary["by_category"].items()
    ]
    lines += [
        "",
        "## Runs",
        "",
        "| Case | # | Result | Failed checks / error | Tools | Evidence recall | Latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for record in records:
        run, score = record.run, record.score
        result = "error" if score.error else ("pass" if score.passed else "**FAIL**")
        detail = score.error or ", ".join(score.failed_checks) or "—"
        tools = ", ".join(c.name for c in run.tool_calls) or "—"
        lines.append(
            f"| {score.case_id}{' (critical)' if score.critical else ''} | {score.repeat} | "
            f"{result} | {detail.replace('|', '/')} | {tools} | "
            f"{_fmt(score.evidence_recall)} | {run.latency_s:.1f} s |"
        )
    agent_tokens, judge_tokens = usage["agent_tokens"], usage["judge_tokens"]
    lines += [
        "",
        "## Usage",
        "",
        f"- Agent: {usage['llm_calls_agent']} LLM calls, {agent_tokens['input']} input and "
        f"{agent_tokens['output']} output tokens; paid-tier equivalent "
        f"{_usd(usage['agent_cost_usd'])}.",
        f"- Judge: {judge_tokens['input']} input and {judge_tokens['output']} output tokens; "
        f"paid-tier equivalent {_usd(usage['judge_cost_usd'])}.",
        f"- Prices from {usage['prices']['source']} ({usage['prices']['retrieved']}). "
        "Actual cost on the free tier: 0.",
        f"- Latency per run p50 {_fmt(usage['latency_s']['p50'])} s, p95 "
        f"{_fmt(usage['latency_s']['p95'])} s (wall time, including rate-limiter waits).",
    ]
    failures = [r for r in records if not r.score.passed]
    if failures:
        lines += ["", "## Failures", ""]
    for record in failures:
        run, score = record.run, record.score
        lines += [f"### {score.case_id} #{score.repeat}", ""]
        if score.error:
            lines.append(f"- Error: `{score.error}`")
        if score.failed_checks:
            lines.append(f"- Failed checks: {', '.join(score.failed_checks)}")
        if run.answer:
            text = str(run.answer.get("texto", "")).replace("\n", " ")
            lines.append(f"- Answer: {text}")
        if score.judge:
            if score.judge.missing_facts:
                lines.append(f"- Missing facts: {'; '.join(score.judge.missing_facts)}")
            if score.judge.contradicts_reference:
                lines.append("- Contradicts the reference answer")
            if score.judge.unsupported_claims:
                lines.append(f"- Unsupported claims: {'; '.join(score.judge.unsupported_claims)}")
            lines.append(f"- Judge analysis: {score.judge.analysis.replace(chr(10), ' ')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
