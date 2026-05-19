"""Reporter: generate machine-readable JSON and human-readable Markdown reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _truncate(text: str, max_length: int = 500) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def _failure_type_counts(evaluations: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for evaluation in evaluations:
        for failure in evaluation.get("failures", []):
            ftype = failure.get("type", "unknown")
            counts[ftype] = counts.get(ftype, 0) + 1
    return counts


def _collect_failures_by_type(
    evaluations: list[dict], failure_type: str
) -> list[dict]:
    results: list[dict] = []
    for evaluation in evaluations:
        for failure in evaluation.get("failures", []):
            if failure.get("type") == failure_type:
                results.append({
                    "case_id": evaluation["case_id"],
                    "title": evaluation.get("title", ""),
                    "category": evaluation.get("category", ""),
                    "citation": failure.get("citation", ""),
                    "detail": failure.get("detail", ""),
                })
    return results


def _generate_recommendations(counts: dict[str, int]) -> list[str]:
    recommendations: list[str] = []

    if counts.get("missed_citation", 0) > 2:
        recommendations.append(
            "**Citation Parser 加强**：missed_citation 较多，"
            "建议检查 parser 的正则表达式对 `Section X of Title Y`、"
            "`Chapter` 变体、无 Title 前缀的 § 引用等格式的识别覆盖。"
        )
    if counts.get("topic_mismatch_missing", 0) > 2:
        recommendations.append(
            "**Context Window / Topic Rules 加强**：topic_mismatch_missing 较多，"
            "建议扩大主题规则覆盖的条文编号陷阱（如 cross-title section number traps），"
            "或在 registry 中增加更多 entity-type / UCC article / profession chapter 映射。"
        )
    if counts.get("coverage_warning_missing", 0) > 2:
        recommendations.append(
            "**Coverage Detector 加强**：coverage_warning_missing 较多，"
            "建议增强 federal / case law / admin / session law 覆盖边界检测，"
            "确保 NON_DELAWARE_RE / UNCOVERED_RE / BILLS_RE 等正则被正确触发。"
        )
    if counts.get("false_positive", 0) > 2:
        recommendations.append(
            "**降低 Topic Rules 过度触发**：false_positive 较多，"
            "建议审查主题规则的触发条件，增加更多语境词匹配或缩小窗口范围，"
            "避免在正确引用场景下产生误报。"
        )
    if counts.get("false_negative", 0) > 2:
        recommendations.append(
            "**加强 Error 信号检测**：false_negative 较多，"
            "建议检查 validator 对错误引用的标记逻辑，"
            "确保 topic mismatch 场景能被正确识别并输出 error/warning。"
        )
    if counts.get("unexpected_cli_error", 0) > 0:
        recommendations.append(
            "**CLI 稳定性修复**：unexpected_cli_error 存在，"
            "建议检查 CLI 命令对异常输入（特殊字符、超长文本、空输入等）的处理，"
            "增加 try/except 和适当的错误消息。"
        )

    if not recommendations:
        recommendations.append(
            "整体表现良好。可继续增加更多边界条件和格式变体测试用例。"
        )

    return recommendations


def generate_markdown_report(
    evaluation_result: dict,
    output_path: Path,
) -> str:
    """Generate a human-readable Markdown report."""
    summary = evaluation_result.get("summary", {})
    evaluations = evaluation_result.get("evaluations", [])
    counts = _failure_type_counts(evaluations)

    # Group failures by category for the report
    missed_citations = _collect_failures_by_type(evaluations, "missed_citation")
    topic_mismatches = _collect_failures_by_type(evaluations, "topic_mismatch_missing")
    coverage_missing = _collect_failures_by_type(evaluations, "coverage_warning_missing")
    false_positives = _collect_failures_by_type(evaluations, "false_positive")
    false_negatives = _collect_failures_by_type(evaluations, "false_negative")
    cli_errors = _collect_failures_by_type(evaluations, "unexpected_cli_error")

    failed_cases = [e for e in evaluations if e["status"] == "FAIL"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines: list[str] = []
    lines.append("# Delaware Law Validator Adversarial Test Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total cases: {summary.get('total', 0)}")
    lines.append(f"- Passed: {summary.get('passed', 0)}")
    lines.append(f"- Failed: {summary.get('failed', 0)}")
    lines.append(f"- Pass rate: {summary.get('pass_rate', 0)}%")
    lines.append(f"- Generated at: {now}")
    lines.append("")

    lines.append("## Failure Breakdown")
    lines.append("")
    if counts:
        lines.append("| Failure Type | Count |")
        lines.append("|---|---|")
        for ftype, count in sorted(counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {ftype} | {count} |")
    else:
        lines.append("No failures detected.")
    lines.append("")

    if failed_cases:
        lines.append("## Failed Cases")
        lines.append("")
        for case in failed_cases:
            lines.append(f"### {case['case_id']} — {case.get('title', 'Untitled')}")
            lines.append("")
            lines.append(f"- **Category**: {case.get('category', 'N/A')}")
            failure_types = {f.get("type", "unknown") for f in case.get("failures", [])}
            lines.append(f"- **Failure Types**: {', '.join(sorted(failure_types))}")
            lines.append("")
            for failure in case.get("failures", []):
                lines.append(f"- ❌ **{failure['type']}**: {failure.get('detail', '')}")
                if failure.get("citation"):
                    lines.append(f"  - Citation: `{failure['citation']}`")
            lines.append("")
    else:
        lines.append("## Failed Cases")
        lines.append("")
        lines.append("All cases passed.")
        lines.append("")

    if missed_citations:
        lines.append("## Missed Citations")
        lines.append("")
        lines.append("| Case ID | Title | Citation |")
        lines.append("|---|---|---|")
        for item in missed_citations[:20]:
            lines.append(
                f"| {item['case_id']} | {item['title']} | `{item['citation']}` |"
            )
        if len(missed_citations) > 20:
            lines.append(f"| ... | ... | (+ {len(missed_citations) - 20} more) |")
        lines.append("")

    if topic_mismatches:
        lines.append("## Topic Mismatch Failures")
        lines.append("")
        lines.append("| Case ID | Title | Citation | Detail |")
        lines.append("|---|---|---|---|")
        for item in topic_mismatches:
            lines.append(
                f"| {item['case_id']} | {item['title']} | `{item['citation']}` | {_truncate(item['detail'], 200)} |"
            )
        lines.append("")

    if coverage_missing:
        lines.append("## Coverage Warning Failures")
        lines.append("")
        lines.append("| Case ID | Title | Citation | Detail |")
        lines.append("|---|---|---|---|")
        for item in coverage_missing:
            lines.append(
                f"| {item['case_id']} | {item['title']} | `{item['citation']}` | {_truncate(item['detail'], 200)} |"
            )
        lines.append("")

    if false_positives or false_negatives or cli_errors:
        lines.append("## Other Failures")
        lines.append("")
        if false_positives:
            lines.append("### False Positives")
            for item in false_positives:
                lines.append(f"- {item['case_id']}: `{item['citation']}` — {_truncate(item['detail'], 200)}")
            lines.append("")
        if false_negatives:
            lines.append("### False Negatives")
            for item in false_negatives:
                lines.append(f"- {item['case_id']}: `{item['citation']}` — {_truncate(item['detail'], 200)}")
            lines.append("")
        if cli_errors:
            lines.append("### CLI Errors")
            for item in cli_errors:
                lines.append(f"- {item['case_id']}: {_truncate(item['detail'], 200)}")
            lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    for rec in _generate_recommendations(counts):
        lines.append(f"- {rec}")
    lines.append("")

    content = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    return content


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    config = json.loads((base_dir / "config.json").read_text(encoding="utf-8"))
    results_dir = base_dir / config.get("results_dir", "results")
    reports_dir = base_dir / config.get("reports_dir", "reports")

    evaluation_path = results_dir / "evaluation_latest.json"
    if not evaluation_path.exists():
        print(f"Error: evaluation file not found at {evaluation_path}")
        print("Run evaluator.py first.")
        return 1

    evaluation_result = json.loads(evaluation_path.read_text(encoding="utf-8"))

    # Generate markdown report
    md_path = reports_dir / "latest.md"
    generate_markdown_report(evaluation_result, md_path)
    print(f"Markdown report saved to {md_path}")

    # Print summary to terminal
    summary = evaluation_result.get("summary", {})
    print()
    print("=" * 50)
    print("Adversarial Test Report")
    print("=" * 50)
    print(f"Total:   {summary.get('total', 0)}")
    print(f"Passed:  {summary.get('passed', 0)}")
    print(f"Failed:  {summary.get('failed', 0)}")
    print(f"Rate:    {summary.get('pass_rate', 0)}%")
    print(f"Report:  {md_path}")
    print(f"Eval:    {evaluation_path}")
    print("=" * 50)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
