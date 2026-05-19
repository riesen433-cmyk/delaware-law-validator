"""Mutation generator: reads hand-written cases, produces format-variant copies."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

CITATION_PATTERNS = [
    # (regex, list of variant strings)
    (
        re.compile(r"\b(\d+)\s+Del\.\s*C\.\s*§\s*([\dA-Za-z]+(?:\([^)]*\))?(?:[\dA-Za-z.\-]*)*)\b", re.IGNORECASE),
        [
            "{title} Del. C. § {section}",
            "{title} Del.C. §{section}",
            "{title} Del C § {section}",
            "Title {title}, Section {section}",
            "Section {section} of Title {title}",
            "Section {section} of the Delaware Code",
        ],
    ),
    (
        re.compile(r"\b(\d+)\s+Del\.\s*C\.\s*(?:ch\.?|chapter)\s*(\d+[A-Za-z]?)\b", re.IGNORECASE),
        [
            "{title} Del. C. ch. {chapter}",
            "{title} Del.C. Chapter {chapter}",
            "Title {title}, Chapter {chapter}",
            "Chapter {chapter} of Title {title}",
        ],
    ),
    (
        re.compile(r"\b(Del\.\s*Ch\.\s*Ct\.\s*R\.\s*[\d]+(?:\([^)]*\))?)\b", re.IGNORECASE),
        [
            "Del. Ch. Ct. R. {rule}",
            "Court of Chancery Rule {rule}",
            "Chancery Rule {rule}",
        ],
    ),
    (
        re.compile(r"\b(D\.R\.E\.\s*\d+)\b", re.IGNORECASE),
        [
            "D.R.E. {rule_num}",
            "Delaware Rule of Evidence {rule_num}",
            "Delaware Uniform Rule of Evidence {rule_num}",
        ],
    ),
]

MAX_VARIANTS_PER_CASE = 5


def _apply_code_variants(text: str) -> list[tuple[str, str | None, str | None]]:
    """Generate format variants of code citations in text.

    Returns list of (variant_text, original_citation, new_citation).
    """
    variants: list[tuple[str, str | None, str | None]] = []
    seen: set[str] = set()

    for pattern_index, (pattern, templates) in enumerate(CITATION_PATTERNS):
        for match in pattern.finditer(text):
            original = match.group(0).strip()
            groups = match.groups()

            # pattern_index 0: Code section (title, section)
            # pattern_index 1: Chapter (title, chapter)
            # pattern_index 2: Court rule (rule)
            # pattern_index 3: DRE (rule_num)
            if pattern_index == 0 and len(groups) >= 2:
                title, section = groups[0], groups[1]
                format_kwargs = {"title": title, "section": section}
            elif pattern_index == 1 and len(groups) >= 2:
                title, chapter = groups[0], groups[1]
                format_kwargs = {"title": title, "chapter": chapter}
            elif pattern_index == 2 and len(groups) >= 1:
                rule = groups[0]
                format_kwargs = {"rule": rule}
            elif pattern_index == 3 and len(groups) >= 1:
                rule_num = groups[0]
                format_kwargs = {"rule_num": rule_num}
            else:
                continue

            for template in templates:
                try:
                    variant = template.format(**format_kwargs)
                except KeyError:
                    continue
                if variant != original and variant not in seen:
                    seen.add(variant)
                    new_text = text[: match.start()] + variant + text[match.end() :]
                    variants.append((new_text, original, variant))
                    if len(variants) >= MAX_VARIANTS_PER_CASE:
                        return variants

    return variants


def _replace_citation_in_text(text: str, old_citation: str, new_citation: str) -> str:
    """Replace citation in text, handling surrounding context."""
    idx = text.find(old_citation)
    if idx < 0:
        return text.replace(old_citation, new_citation)
    return text[:idx] + new_citation + text[idx + len(old_citation) :]


def generate_mutations(cases: list[dict], output_path: Path) -> int:
    """Generate mutation cases from hand-written cases.

    Returns number of mutations generated.
    """
    mutations: list[dict] = []
    seen_ids: set[str] = set()

    for case in cases:
        text = case.get("text", "")
        variants = _apply_code_variants(text)

        for i, (variant_text, orig_citation, new_citation) in enumerate(variants):
            mut_id = f"{case['id']}__mut_{i + 1:03d}"
            if mut_id in seen_ids:
                continue
            seen_ids.add(mut_id)

            mut_case = copy.deepcopy(case)
            mut_case["id"] = mut_id
            mut_case["title"] = f"{case['title']} [format variant: {orig_citation} → {new_citation}]"
            mut_case["text"] = variant_text
            mut_case["category"] = case.get("category", "mutation_format_variant")

            # Update expected citations_detected to include the variant
            expected = mut_case.get("expected", {})
            if "citations_detected" in expected:
                new_detected = list(expected["citations_detected"])
                if new_citation and new_citation not in new_detected:
                    new_detected.append(new_citation)
                if orig_citation and orig_citation not in new_detected:
                    new_detected.append(orig_citation)
                expected["citations_detected"] = new_detected
                mut_case["expected"] = expected

            mutations.append(mut_case)

    if mutations:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(mutations, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return len(mutations)


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    cases_dir = base_dir / "cases"
    generated_dir = base_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    output_path = generated_dir / "mutations_round_latest.json"

    all_cases: list[dict] = []
    for case_file in sorted(cases_dir.glob("*.json")):
        try:
            data = json.loads(case_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                all_cases.extend(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: failed to read {case_file}: {exc}")

    count = generate_mutations(all_cases, output_path)
    print(f"Generated {count} mutation cases → {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
