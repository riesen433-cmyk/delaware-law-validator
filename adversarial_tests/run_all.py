"""run_all.py: orchestrate the full adversarial testing pipeline.

Steps:
1. mutator.py — generate format variants
2. runner.py  — invoke CLI and capture output
3. evaluator.py — compare actual vs expected
4. reporter.py  — generate reports
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_module(module_path: Path) -> int:
    """Run a Python module and return its exit code."""
    result = subprocess.run(
        [sys.executable, str(module_path)],
        capture_output=False,
        cwd=str(module_path.parent),
    )
    return result.returncode


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    config_path = base_dir / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    validator_cmd = config.get("validator_cmd", "delaware-law")
    results_dir = base_dir / config.get("results_dir", "results")
    reports_dir = base_dir / config.get("reports_dir", "reports")
    evaluation_path = results_dir / "evaluation_latest.json"
    report_path = reports_dir / "latest.md"

    print("=" * 60)
    print("Delaware Law Validator — Adversarial Testing Pipeline")
    print("=" * 60)
    print()

    # Step 1: Mutator
    print("[1/4] Generating mutation cases...")
    mutator_path = base_dir / "mutator.py"
    rc = run_module(mutator_path)
    if rc != 0:
        print(f"  Mutator exited with code {rc} (non-fatal)")
    print()

    # Step 2: Runner
    print("[2/4] Running test cases through CLI...")
    runner_path = base_dir / "runner.py"
    rc = run_module(runner_path)
    if rc != 0:
        print(f"  Runner exited with code {rc} (non-fatal)")
    print()

    # Step 3: Evaluator
    print("[3/4] Evaluating results...")
    evaluator_path = base_dir / "evaluator.py"
    rc = run_module(evaluator_path)
    if rc != 0:
        print(f"  Evaluator exited with code {rc}")
    print()

    # Step 4: Reporter
    print("[4/4] Generating reports...")
    reporter_path = base_dir / "reporter.py"
    rc = run_module(reporter_path)
    if rc != 0:
        print(f"  Reporter exited with code {rc}")
    print()

    # Print final summary
    print("=" * 60)
    print("Final Summary")
    print("=" * 60)

    if evaluation_path.exists():
        eval_data = json.loads(evaluation_path.read_text(encoding="utf-8"))
        summary = eval_data.get("summary", {})
        print(f"Total:   {summary.get('total', 'N/A')}")
        print(f"Passed:  {summary.get('passed', 'N/A')}")
        print(f"Failed:  {summary.get('failed', 'N/A')}")
        print(f"Rate:    {summary.get('pass_rate', 'N/A')}%")
    else:
        print("No evaluation results found.")
        print("If the validator command was not found, set validator_cmd in config.json.")
        print(f"Current validator_cmd: '{validator_cmd}'")
        print()
        print("Example commands to try:")
        print("  which delaware-law")
        print("  python -m delaware_law_skill.cli --help")

    print()
    print(f"Evaluation JSON: {evaluation_path}")
    print(f"Markdown Report: {report_path}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
