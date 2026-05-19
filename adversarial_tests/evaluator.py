"""Evaluator: compare actual CLI output against expected results."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


def normalize_citation(text: str) -> str:
    """Normalize a citation string for comparison.

    Handles variants of:
    - "6 Del. C. § 17-407"
    - "6 Del.C. §17-407"
    - "6 Del C § 17-407"
    - "Title 6, Section 17-407"
    - "Section 17-407 of Title 6"
    - "6 Del. C. ch. 17"
    - "Title 6, Chapter 17"
    """
    if not text:
        return ""

    # Unicode normalize
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()

    # Remove trailing punctuation (periods, commas, semicolons, colons)
    text = re.sub(r"[,;:.]+$", "", text.strip())

    # Normalize "Section X of the Delaware Code/Act" → "§ X" (keep general)
    m = re.match(
        r"Section\s+([\dA-Za-z]+(?:\([^)]*\))?(?:[.\-][\dA-Za-z]+)*)\s+of\s+the\s+Delaware\s+(?:Code|Act|DRULPA|General Corporation Law|LLC Act)",
        text,
        re.IGNORECASE,
    )
    if m:
        text = f"§ {m.group(1)}"

    # Normalize "§ X of the Delaware Code/Act" (keep as § X)
    m = re.match(
        r"§+\s*([\dA-Za-z]+(?:\([^)]*\))?(?:[.\-][\dA-Za-z]+)*)\s+of\s+the\s+Delaware\s+(?:Code|Act|DRULPA|General Corporation Law|LLC Act)",
        text,
        re.IGNORECASE,
    )
    if m:
        text = f"§ {m.group(1)}"

    # Normalize "Section X of Title Y" → "Y Del. C. § X"
    m = re.match(
        r"Section\s+([\dA-Za-z]+(?:\([^)]*\))?(?:[.\-][\dA-Za-z]+)*)\s+of\s+Title\s+(\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        text = f"{m.group(2)} Del. C. § {m.group(1)}"

    # Normalize "Chapter X of Title Y" → "Y Del. C. ch. X"
    m = re.match(
        r"Chapter\s+(\d+[A-Za-z]?)\s+of\s+Title\s+(\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        text = f"{m.group(2)} Del. C. ch. {m.group(1)}"

    # Normalize "Title X, Section Y" → "X Del. C. § Y"
    m = re.match(
        r"Title\s+(\d+),?\s*Section\s+([\dA-Za-z]+(?:\([^)]*\))?(?:[.\-][\dA-Za-z]+)*)",
        text,
        re.IGNORECASE,
    )
    if m:
        text = f"{m.group(1)} Del. C. § {m.group(2)}"

    # Normalize "Title X, Chapter Y" → "X Del. C. ch. Y"
    m = re.match(
        r"Title\s+(\d+),?\s*Chapter\s+(\d+[A-Za-z]?)",
        text,
        re.IGNORECASE,
    )
    if m:
        text = f"{m.group(1)} Del. C. ch. {m.group(2)}"

    # Normalize bare "Section" / "§" to canonical form
    text = re.sub(r"\bSection\b", "§", text, flags=re.IGNORECASE)
    # Normalize spacing in "X Del. C. § Y"
    text = re.sub(r"Del\.?\s*C\.?", "Del. C.", text, flags=re.IGNORECASE)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Normalize § spacing
    text = re.sub(r"§\s*", "§ ", text)
    text = re.sub(r"\s+§", " §", text)
    # Normalize "ch." vs "Chapter"
    text = re.sub(r"\bchapter\b", "ch.", text, flags=re.IGNORECASE)
    text = re.sub(r"\bch\.\s*", "ch. ", text, flags=re.IGNORECASE)
    # Collapse whitespace again after substitutions
    text = re.sub(r"\s+", " ", text).strip()

    return text


# Error-indicating words/phrases in the output
ERROR_KEYWORDS = [
    "error", "invalid", "mismatch", "wrong", "incorrect",
    "not found", "nonexistent", "does not exist", "should be",
    "instead", "主题不匹配", "错误", "不存在", "应改为", "建议",
    "not_found", "invalid_format", "明显错误",
]

# Warning-indicating words/phrases
WARNING_KEYWORDS = [
    "warning", "warn", "caution", "review", "coverage",
    "not covered", "outside scope", "federal", "case law",
    "session law", "administrative code", "超出覆盖", "不覆盖",
    "联邦", "判例", "提示", "uncovered", "outside",
    "beyond", "超出",
]

# Pass-indicating words/phrases
PASS_KEYWORDS = [
    "valid", "found", "ok", "pass", "exists", "verified",
    "通过", "存在", "已确认正确",
]


def _contains_any_keywords(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _context_around(text: str, citation: str, window: int = 300) -> str:
    """Get text context window around a citation occurrence."""
    idx = text.lower().find(citation.lower())
    if idx < 0:
        return text
    start = max(0, idx - window)
    end = min(len(text), idx + len(citation) + window)
    return text[start:end]


def _find_citation_occurrence(text: str, citation: str) -> int:
    """Find the start index of a citation in text (case-insensitive, fuzzy)."""
    lowered_text = text.lower()
    lowered_cit = citation.lower().strip()

    # Direct match
    idx = lowered_text.find(lowered_cit)
    if idx >= 0:
        return idx

    # Try normalized match
    norm_cit = normalize_citation(citation).lower()
    # Search for the normalized citation in the text
    idx = lowered_text.find(norm_cit)
    if idx >= 0:
        return idx

    # Try matching just the section number
    m = re.search(r"§\s*([\dA-Za-z]+(?:\([^)]*\))?(?:[.\-][\dA-Za-z]+)*)", citation)
    if m:
        section = m.group(1)
        pattern = re.compile(
            r"§\s*" + re.escape(section) + r"(?:\b|[)\-])",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            return match.start()

    return -1


def _citation_in_output(citation: str, combined_output: str) -> bool:
    """Check if citation appears in output (with normalization and fuzzy search)."""
    lowered_output = combined_output.lower()
    lowered_cit = citation.lower().strip()
    # Direct check
    if lowered_cit in lowered_output:
        return True
    # Normalized check
    norm = normalize_citation(citation)
    if norm.lower() in lowered_output:
        return True
    # Also check if the normalized output contains the citation
    norm_output = normalize_citation(combined_output)
    if norm.lower() in norm_output.lower():
        return True
    # Fuzzy: check if key numbers appear near each other
    parts = re.findall(r'[\d]+[A-Za-z.]*', citation)
    if len(parts) >= 2:
        all_found = all(p.lower() in lowered_output for p in parts)
        if all_found:
            return True
    return False


def _parse_validator_json(stdout: str) -> dict | None:
    """Try to parse validator JSON output. Returns None on failure."""
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _find_citation_in_json(
    citation: str, parsed: dict
) -> dict | None:
    """Find a citation entry in parsed validator JSON output.

    Searches citations[], chapter_references[], court_rule_references[],
    and broad_references[] for a matching input field.
    """
    norm_cit = normalize_citation(citation).lower().rstrip(".")
    citation_arrays = [
        parsed.get("citations", []),
        parsed.get("chapter_references", []),
        parsed.get("court_rule_references", []),
        parsed.get("broad_references", []),
    ]
    for arr in citation_arrays:
        for entry in arr:
            entry_input = normalize_citation(entry.get("input", "")).lower().rstrip(".")
            if norm_cit in entry_input or entry_input in norm_cit:
                return entry
            # Also check if the entry input contains the citation (fuzzy)
            if citation.lower().strip().rstrip(".") in entry.get("input", "").lower():
                return entry

    # Also check outside_delaware_signals, admin_code_signals, bill_signals, uncovered_material_signals
    signal_status_map = {
        "outside_delaware_signals": "federal",
        "admin_code_signals": "admin_code",
        "bill_signals": "bill",
        "uncovered_material_signals": "uncovered",
    }
    for key, signal_status in signal_status_map.items():
        signals = parsed.get(key, [])
        for sig in (signals if isinstance(signals, list) else []):
            sig_str = str(sig)
            sig_norm = normalize_citation(sig_str).lower().rstrip(".")
            if norm_cit in sig_norm or sig_norm in norm_cit:
                return {"input": sig_str, "status": signal_status}
            if citation.lower().strip().rstrip(".") in sig_str.lower():
                return {"input": sig_str, "status": signal_status}

    # Check in topic_reviews for suggested citations
    for tr in parsed.get("topic_reviews", []):
        for s in tr.get("suggestions", []):
            sug_cit = str(s.get("citation", ""))
            sug_norm = normalize_citation(sug_cit).lower().rstrip(".")
            if norm_cit in sug_norm or sug_norm in norm_cit:
                return {"input": sug_cit, "status": "suggestion"}

    # Check in implicit_references
    for ir in parsed.get("implicit_references", []):
        ir_cit = str(ir.get("citation", ""))
        ir_norm = normalize_citation(ir_cit).lower().rstrip(".")
        if norm_cit in ir_norm or ir_norm in norm_cit:
            return {"input": ir_cit, "status": "implicit"}

    return None


def _citation_has_error_signals(entry: dict) -> bool:
    """Check if a citation entry has error/warning signals."""
    status = entry.get("status", "")
    if status in ("not_found", "invalid_format", "federal", "other_state", "uncovered", "bill", "admin_code"):
        return True
    warnings = entry.get("warnings", [])
    if warnings:
        for w in warnings:
            w_lower = str(w).lower()
            if _contains_any_keywords(w_lower, ERROR_KEYWORDS):
                return True
    return False


def _citation_has_warning_signals(entry: dict) -> bool:
    """Check if a citation entry has warning signals."""
    warnings = entry.get("warnings", [])
    return len(warnings) > 0


def check_citations_detected(
    expected_citations: list[str],
    combined_output: str,
    parsed: dict | None = None,
) -> dict:
    """Check that each expected citation appears in output."""
    results: dict[str, bool] = {}
    if parsed is None:
        parsed = _parse_validator_json(combined_output)
    for citation in expected_citations:
        if parsed and _find_citation_in_json(citation, parsed):
            results[citation] = True
        else:
            results[citation] = _citation_in_output(citation, combined_output)
    return results


def check_should_pass(
    should_pass_items: list[dict],
    combined_output: str,
    parsed: dict | None = None,
) -> dict:
    """Check that citations expected to pass do not have error signals."""
    if parsed is None:
        parsed = _parse_validator_json(combined_output)
    results = {}
    for item in should_pass_items:
        citation = item.get("citation", "")
        reason = item.get("reason", "")

        if parsed:
            entry = _find_citation_in_json(citation, parsed)
            if entry is None:
                # Citation not found in structured output — try text search
                if _citation_in_output(citation, combined_output):
                    results[citation] = {
                        "passed": True,
                        "reason": f"Citation found in output (text). {reason}",
                        "failure_type": None,
                    }
                else:
                    results[citation] = {
                        "passed": False,
                        "reason": f"Citation not found in output. Expected: {reason}",
                        "failure_type": "missed_citation",
                    }
                continue

            has_error = _citation_has_error_signals(entry)
            has_suggestion = len(entry.get("suggestions", [])) > 0
            results[citation] = {
                "passed": not has_error and not has_suggestion,
                "reason": reason,
                "failure_type": "false_positive" if (has_error or has_suggestion) else None,
                "entry_status": entry.get("status"),
                "entry_warnings": [str(w) for w in entry.get("warnings", [])],
            }
        else:
            # Fallback to text search
            idx = _find_citation_occurrence(combined_output, citation)
            if idx < 0:
                results[citation] = {
                    "passed": False,
                    "reason": f"Citation not found. Expected: {reason}",
                    "failure_type": "missed_citation",
                }
                continue
            window_text = combined_output[max(0, idx - 300): min(len(combined_output), idx + 300)]
            has_error = _contains_any_keywords(window_text, ERROR_KEYWORDS)
            results[citation] = {
                "passed": not has_error,
                "reason": reason,
                "failure_type": "false_positive" if has_error else None,
            }
    return results


def check_should_error(
    should_error_items: list[dict],
    combined_output: str,
    parsed: dict | None = None,
) -> dict:
    """Check that citations expected to error have error/warning signals."""
    if parsed is None:
        parsed = _parse_validator_json(combined_output)
    results = {}
    for item in should_error_items:
        citation = item.get("citation", "")
        reason = item.get("reason", "")
        reason_lowered = reason.lower()

        if parsed:
            entry = _find_citation_in_json(citation, parsed)
            if entry is None:
                # Citation not found in structured output
                if _citation_in_output(citation, combined_output):
                    results[citation] = {
                        "passed": False,
                        "reason": f"Citation found in text but not in structured output. {reason}",
                        "failure_type": "parse_failure",
                    }
                else:
                    results[citation] = {
                        "passed": False,
                        "reason": f"Citation not found in output. Expected: {reason}",
                        "failure_type": "missed_citation",
                    }
                continue

            has_error = _citation_has_error_signals(entry)
            has_warning = _citation_has_warning_signals(entry)
            entry_warnings = [str(w) for w in entry.get("warnings", [])]
            entry_suggestions = entry.get("suggestions", [])

            if has_error or has_warning or entry_suggestions:
                # The validator flagged something — good
                results[citation] = {
                    "passed": True,
                    "reason": reason,
                    "failure_type": None,
                    "entry_status": entry.get("status"),
                    "entry_warnings": entry_warnings,
                    "entry_suggestions": entry_suggestions,
                }
            else:
                # Validator found the citation but didn't flag it
                failure_type = "false_negative"
                if any(kw in reason_lowered for kw in ["llc", "lp", "ucc", "foia", "admin", "federal", "coverage", "topic", "主题"]):
                    failure_type = "topic_mismatch_missing"
                results[citation] = {
                    "passed": False,
                    "reason": reason,
                    "failure_type": failure_type,
                    "entry_status": entry.get("status"),
                    "entry_warnings": entry_warnings,
                }
        else:
            # Fallback to text search
            idx = _find_citation_occurrence(combined_output, citation)
            if idx < 0:
                results[citation] = {
                    "passed": False,
                    "reason": f"Citation not found. Expected: {reason}",
                    "failure_type": "missed_citation",
                }
                continue
            window_text = combined_output[max(0, idx - 300): min(len(combined_output), idx + 300)]
            has_error = _contains_any_keywords(window_text, ERROR_KEYWORDS)
            if has_error:
                results[citation] = {"passed": True, "reason": reason, "failure_type": None}
            else:
                ftype = "topic_mismatch_missing" if any(kw in reason_lowered for kw in ["llc", "lp", "ucc", "foia", "admin", "federal", "coverage", "topic", "主题"]) else "false_negative"
                results[citation] = {"passed": False, "reason": reason, "failure_type": ftype}
    return results


def check_should_warn(
    should_warn_items: list[dict],
    combined_output: str,
    parsed: dict | None = None,
) -> dict:
    """Check that expected warnings appear in output (JSON-aware)."""
    if parsed is None:
        parsed = _parse_validator_json(combined_output)
    results = {}
    for item in should_warn_items:
        contains_any = item.get("contains_any", [])
        reason = item.get("reason", "")

        found_keywords: list[str] = []
        missing_keywords: list[str] = []

        # Search both raw text and JSON structured fields
        search_text = combined_output.lower()
        if parsed:
            # Also include topic_reviews messages and citations warnings
            for tr in parsed.get("topic_reviews", []):
                search_text += " " + str(tr.get("message", "")).lower()
                search_text += " " + str(tr.get("code", "")).lower()
                for s in tr.get("suggestions", []):
                    search_text += " " + str(s.get("citation", "")).lower()
            for c in parsed.get("citations", []):
                for w in c.get("warnings", []):
                    search_text += " " + str(w).lower()
                for s in c.get("suggestions", []):
                    search_text += " " + str(s.get("citation", "")).lower()
                    search_text += " " + str(s.get("reason", "")).lower()

        for keyword in contains_any:
            if keyword.lower() in search_text:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)

        passed = len(found_keywords) > 0
        results[reason] = {
            "passed": passed,
            "found_keywords": found_keywords,
            "missing_keywords": missing_keywords,
            "failure_type": "topic_mismatch_missing" if not passed else None,
        }
    return results


def check_coverage_warnings(
    coverage_warnings: list[dict],
    combined_output: str,
    parsed: dict | None = None,
) -> dict:
    """Check that coverage warnings appear in output (JSON-aware)."""
    if parsed is None:
        parsed = _parse_validator_json(combined_output)
    results = {}
    for item in coverage_warnings:
        citation = item.get("citation", "")
        contains_any = item.get("contains_any", [])

        found_keywords: list[str] = []
        missing_keywords: list[str] = []

        # Search coverage-related fields in JSON + full text
        search_text = combined_output.lower()
        if parsed:
            for cw in parsed.get("coverage_warnings", []):
                search_text += " " + str(cw).lower()
            for sig in parsed.get("outside_delaware_signals", []):
                search_text += " " + str(sig).lower()
            for sig in parsed.get("uncovered_material_signals", []):
                search_text += " " + str(sig).lower()
            for sig in parsed.get("admin_code_signals", []):
                search_text += " " + str(sig).lower()
            for sig in parsed.get("bill_signals", []):
                search_text += " " + str(sig).lower()

        for keyword in contains_any:
            if keyword.lower() in search_text:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)

        passed = len(found_keywords) > 0
        results[citation] = {
            "passed": passed,
            "found_keywords": found_keywords,
            "missing_keywords": missing_keywords,
            "failure_type": "coverage_warning_missing" if not passed else None,
        }
    return results


def check_must_not_contain(
    forbidden_patterns: list[str],
    combined_output: str,
) -> dict:
    """Check that forbidden patterns do not appear in output."""
    results = {}
    for pattern in forbidden_patterns:
        present = pattern.lower() in combined_output.lower()
        results[pattern] = {
            "passed": not present,
            "present": present,
            "failure_type": "unexpected_cli_error" if present else None,
        }
    return results


def evaluate_case(
    case: dict,
    actual: dict | None,
) -> dict:
    """Evaluate a single test case against its actual output.

    Returns an evaluation dict with status and detailed checks.
    """
    case_id = case.get("id", "unknown")
    expected = case.get("expected", {})
    combined_output = ""

    if actual:
        combined_output = (
            actual.get("stdout", "")
            + "\n"
            + actual.get("stderr", "")
        )

    # Handle missing actual result
    if actual is None:
        return {
            "case_id": case_id,
            "title": case.get("title", ""),
            "category": case.get("category", ""),
            "status": "FAIL",
            "failures": [
                {
                    "type": "unexpected_cli_error",
                    "citation": "",
                    "detail": "No actual result file found — runner may have failed to execute this case.",
                }
            ],
            "checks": {},
        }

    if actual.get("timed_out"):
        return {
            "case_id": case_id,
            "title": case.get("title", ""),
            "category": case.get("category", ""),
            "status": "FAIL",
            "failures": [
                {
                    "type": "unexpected_cli_error",
                    "citation": "",
                    "detail": f"Command timed out after {actual.get('duration_ms', 0)}ms.",
                }
            ],
            "checks": {},
        }

    if actual.get("exit_code", -1) < 0 and "Command not found" in actual.get("stderr", ""):
        return {
            "case_id": case_id,
            "title": case.get("title", ""),
            "category": case.get("category", ""),
            "status": "FAIL",
            "failures": [
                {
                    "type": "unexpected_cli_error",
                    "citation": "",
                    "detail": actual.get("stderr", "").strip(),
                }
            ],
            "checks": {},
        }

    checks: dict[str, Any] = {}
    failures: list[dict] = []

    # Parse JSON output once
    parsed = _parse_validator_json(actual.get("stdout", "")) if actual else None

    # 1. Citations detected check
    if "citations_detected" in expected:
        cd_results = check_citations_detected(
            expected["citations_detected"], combined_output, parsed
        )
        checks["citations_detected"] = cd_results
        for citation, found in cd_results.items():
            if not found:
                failures.append({
                    "type": "missed_citation",
                    "citation": citation,
                    "detail": f"Expected citation '{citation}' not found in output.",
                })

    # 2. Should pass check
    if "should_pass" in expected:
        sp_results = check_should_pass(
            expected["should_pass"], combined_output, parsed
        )
        checks["should_pass"] = sp_results
        for citation, result in sp_results.items():
            if not result["passed"]:
                failures.append({
                    "type": result.get("failure_type", "false_positive"),
                    "citation": citation,
                    "detail": result["reason"],
                })

    # 3. Should error check
    if "should_error" in expected:
        se_results = check_should_error(
            expected["should_error"], combined_output, parsed
        )
        checks["should_error"] = se_results
        for citation, result in se_results.items():
            if not result["passed"]:
                failures.append({
                    "type": result.get("failure_type", "false_negative"),
                    "citation": citation,
                    "detail": result["reason"],
                })

    # 4. Should warn check
    if "should_warn" in expected:
        sw_results = check_should_warn(
            expected["should_warn"], combined_output, parsed
        )
        checks["should_warn"] = sw_results
        for reason, result in sw_results.items():
            if not result["passed"]:
                failures.append({
                    "type": result.get("failure_type", "topic_mismatch_missing"),
                    "citation": "",
                    "detail": f"Expected warning containing any of {result['missing_keywords']}. Reason: {reason}",
                })

    # 5. Coverage warnings check
    if "coverage_warnings" in expected:
        cw_results = check_coverage_warnings(
            expected["coverage_warnings"], combined_output, parsed
        )
        checks["coverage_warnings"] = cw_results
        for citation, result in cw_results.items():
            if not result["passed"]:
                failures.append({
                    "type": "coverage_warning_missing",
                    "citation": citation,
                    "detail": f"Expected coverage warning containing any of {result['missing_keywords']}.",
                })

    # 6. Must not contain check
    if "must_not_contain" in expected:
        mnc_results = check_must_not_contain(
            expected["must_not_contain"], combined_output
        )
        checks["must_not_contain"] = mnc_results
        for pattern, result in mnc_results.items():
            if not result["passed"]:
                failures.append({
                    "type": "unexpected_cli_error",
                    "citation": pattern,
                    "detail": f"Forbidden pattern '{pattern}' found in output.",
                })

    status = "PASS" if not failures else "FAIL"

    return {
        "case_id": case_id,
        "title": case.get("title", ""),
        "category": case.get("category", ""),
        "status": status,
        "failures": failures,
        "checks": checks,
    }


def load_actual_results(results_dir: Path) -> dict[str, dict | None]:
    """Load all .actual.json files from results directory, keyed by case_id."""
    actual_map: dict[str, dict | None] = {}
    if not results_dir.exists():
        return actual_map
    for result_file in sorted(results_dir.glob("*.actual.json")):
        try:
            data = json.loads(result_file.read_text(encoding="utf-8"))
            case_id = data.get("case_id", result_file.stem.replace(".actual", ""))
            actual_map[case_id] = data
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: failed to read {result_file}: {exc}")
    return actual_map


def evaluate_all(
    cases: list[dict],
    results_dir: Path,
    output_path: Path,
) -> dict:
    """Evaluate all test cases against their actual results.

    Returns the combined evaluation result.
    """
    actual_map = load_actual_results(results_dir)
    evaluations: list[dict] = []

    for case in cases:
        case_id = case.get("id", "")
        actual = actual_map.get(case_id)
        evaluation = evaluate_case(case, actual)
        evaluations.append(evaluation)

        # Also write per-case evaluation
        case_eval_path = results_dir / f"{case_id}.evaluation.json"
        case_eval_path.write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    total = len(evaluations)
    passed = sum(1 for e in evaluations if e["status"] == "PASS")
    failed = total - passed

    result = {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total * 100, 1) if total > 0 else 0.0,
        },
        "evaluations": evaluations,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return result


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    config = json.loads((base_dir / "config.json").read_text(encoding="utf-8"))

    case_glob = config.get("case_glob", "cases/*.json")
    generated_case_glob = config.get("generated_case_glob", "generated/*.json")
    results_dir = base_dir / config.get("results_dir", "results")
    run_generated = config.get("run_generated_cases", True)

    cases: list[dict] = []
    for case_file in sorted(base_dir.glob(case_glob)):
        try:
            data = json.loads(case_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                cases.extend(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: failed to read {case_file}: {exc}")

    if run_generated:
        for case_file in sorted(base_dir.glob(generated_case_glob)):
            try:
                data = json.loads(case_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    cases.extend(data)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Warning: failed to read {case_file}: {exc}")

    output_path = results_dir / "evaluation_latest.json"
    result = evaluate_all(cases, results_dir, output_path)

    print(f"Evaluated {result['summary']['total']} cases.")
    print(f"Passed: {result['summary']['passed']}")
    print(f"Failed: {result['summary']['failed']}")
    print(f"Pass rate: {result['summary']['pass_rate']}%")
    print(f"Evaluation saved to {output_path}")

    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
