"""Runner: invoke Delaware Law Validator CLI for each test case, capture output."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from tempfile import NamedTemporaryFile


def _truncate_text(text: str, max_length: int = 300) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _split_cmd(validator_cmd: str) -> list[str]:
    """Split a command string into a list, handling spaces."""
    return validator_cmd.strip().split()


def _project_root() -> Path:
    """Return the project root directory (parent of adversarial_tests/)."""
    return Path(__file__).resolve().parent.parent


def run_case(
    case: dict,
    validator_cmd: str,
    default_mode: str,
    timeout_seconds: int,
    normalize: bool = True,
) -> dict:
    mode = case.get("mode", default_mode)
    text = case.get("text", "")
    review_text = case.get("review_text")
    cmd_parts = _split_cmd(validator_cmd)

    if mode in ("review", "review_text"):
        # review command takes text or --file
        input_text = review_text or text
        if input_text:
            args = [*cmd_parts, "review", "--json", input_text]
        else:
            args = [*cmd_parts, "review", "--json"]
    elif mode == "validate":
        file_path = case.get("file")
        if file_path:
            args = [*cmd_parts, "validate", "--json", "--file", str(file_path)]
        elif text:
            args = [*cmd_parts, "validate", "--json", text]
        else:
            args = [*cmd_parts, "validate", "--json"]
    else:
        args = [*cmd_parts, mode, "--json", text]

    result = {
        "case_id": case["id"],
        "title": case.get("title", ""),
        "category": case.get("category", ""),
        "mode": mode,
        "command": [_truncate_text(a, 200) for a in args],
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "duration_ms": 0,
        "timed_out": False,
    }

    start = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout_seconds,
            text=False,
            cwd=str(_project_root()),
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        result["duration_ms"] = duration_ms
        result["exit_code"] = proc.returncode
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if normalize:
            stdout = normalize_unicode(stdout)
            stderr = normalize_unicode(stderr)
        result["stdout"] = stdout
        result["stderr"] = stderr
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        result["duration_ms"] = timeout_seconds * 1000
        result["stdout"] = ""
        result["stderr"] = f"Timeout after {timeout_seconds}s"
    except FileNotFoundError:
        result["exit_code"] = -1
        result["stderr"] = f"Command not found: {validator_cmd}"
    except Exception as exc:
        result["exit_code"] = -2
        result["stderr"] = f"Runner error: {exc}"

    return result


def run_all(
    cases: list[dict],
    validator_cmd: str,
    default_mode: str,
    timeout_seconds: int,
    results_dir: Path,
    normalize: bool = True,
) -> list[dict]:
    results_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict] = []

    total = len(cases)
    for i, case in enumerate(cases):
        case_id = case.get("id", f"unknown_{i}")
        print(f"[{i + 1}/{total}] Running {case_id} ...", end=" ", flush=True)
        result = run_case(
            case,
            validator_cmd=validator_cmd,
            default_mode=default_mode,
            timeout_seconds=timeout_seconds,
            normalize=normalize,
        )

        # Save individual result
        result_path = results_dir / f"{case_id}.actual.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        all_results.append(result)
        status = (
            "TIMEOUT" if result["timed_out"]
            else f"exit={result['exit_code']}"
        )
        print(status)

    # Save combined results
    combined_path = results_dir / "all_results.json"
    combined_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return all_results


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def load_cases(glob_pattern: str, base_dir: Path) -> list[dict]:
    cases: list[dict] = []
    for case_file in sorted(base_dir.glob(glob_pattern)):
        try:
            data = json.loads(case_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                cases.extend(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: failed to read {case_file}: {exc}")
    return cases


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    config = load_config(base_dir / "config.json")

    validator_cmd = config.get("validator_cmd", "delaware-law")
    default_mode = config.get("default_mode", "validate")
    timeout_seconds = config.get("timeout_seconds", 30)
    case_glob = config.get("case_glob", "cases/*.json")
    generated_case_glob = config.get("generated_case_glob", "generated/*.json")
    results_dir = base_dir / config.get("results_dir", "results")
    run_generated = config.get("run_generated_cases", True)
    normalize = config.get("normalize_unicode", True)

    # Check if validator exists
    try:
        subprocess.run(
            [*_split_cmd(validator_cmd), "--help"],
            capture_output=True,
            timeout=5,
            cwd=str(_project_root()),
        )
    except FileNotFoundError:
        print(f"Warning: '{validator_cmd}' command not found.")
        print("The runner will still attempt to run cases (they will all fail).")
        print(f"Set the correct validator_cmd in {base_dir / 'config.json'}.")

    cases = load_cases(case_glob, base_dir)
    print(f"Loaded {len(cases)} hand-written cases.")

    if run_generated:
        gen_cases = load_cases(generated_case_glob, base_dir)
        cases.extend(gen_cases)
        print(f"Loaded {len(gen_cases)} generated cases.")

    results = run_all(
        cases=cases,
        validator_cmd=validator_cmd,
        default_mode=default_mode,
        timeout_seconds=timeout_seconds,
        results_dir=results_dir,
        normalize=normalize,
    )

    print(f"Done. {len(results)} results saved to {results_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
