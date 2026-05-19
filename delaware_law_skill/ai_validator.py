"""AI-powered citation validator: use LLM to identify citations, then verify against local database.

The SYSTEM_PROMPT below is the citation-extraction guide for the agent. The agent (Claude)
does the extraction directly — no external API call. The local tooling only handles
database lookups, topic-rule application, and result formatting.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .database import DelawareLawDatabase
from .validator import (
    _apply_topic_rules,
    _context_window,
)


SYSTEM_PROMPT = """You are a Delaware legal citation extraction engine. Your job: identify ALL legal citations in text, and flag topic mismatches.

IMPORTANT: Topic mismatches are when a citation's section number is CORRECT (it exists in the database) but the TOPIC doesn't match the context. Flag these in topic_notes.

You MUST handle ALL citation formats, including variants with unusual spacing, punctuation, or phrasing:
- "6 Del. C. § 17-407" / "6 Del.C. §17-407" / "6 Del C § 17-407" — all the same
- "Title 6, Section 17-407" / "Section 17-407 of Title 6" / "Section 17-407 of the Delaware Code"
- "Chapter X of Title Y" / "Title Y, Chapter X" / "Y Del. C. ch. X"
- Citations with trailing periods, commas, or parentheticals

Known topic mismatch traps — ALWAYS flag these in topic_notes when detected:

**DRULPA / LP traps:**
- § 17-406 is REMEDIES FOR BREACH of partnership agreement, NOT professional reliance → correct is § 17-407
- § 17-607(b) is LP partner RETURN LIABILITY for unlawful distribution, NOT the asset/liability distribution test → correct is § 17-607(a)
- § 17-1101 is LP statute (DRULPA), NOT LLC Act → correct is § 18-1101 for LLC fiduciary waiver

**UCC Article traps:**
- Article 9 sections (like § 9-316) in WARRANTY/DISCLAIMER context are WRONG → correct is Article 2 (§ 2-316)
- Article 2 sections (like § 2-102) in SECURED TRANSACTION/PERFECTION context are WRONG → correct is Article 9
- § 2-714 is BUYER'S DAMAGES for accepted goods, NOT exclusion of consequential damages → correct is § 2-719(3)

**Health / Professional licensing traps:**
- § 3920 is SOCIAL WORK telehealth, NOT general healthcare telehealth → correct is § 6002
- Chapter 30 (Title 24) is MENTAL HEALTH/CHEMICAL DEPENDENCY, NOT social work → correct is Chapter 39
- Professional licensing must map by profession: pharmacy=ch.25, medicine=ch.17, nursing=ch.19, mental health=ch.30, psychology=ch.35, social work=ch.39

**Cross-jurisdiction traps:**
- Federal FOIA (5 U.S.C. § 552) for DELAWARE public records is WRONG → correct is 29 Del. C. ch. 100
- Title 18 (insurance) for PUBLIC WORKS BONDS is WRONG → correct is Title 29 procurement rules
- "Underground utility damage" references belong in Title 26 Chapter 8, NOT Chapter 12

**Title 12 Trust & Estates domain traps — ALWAYS flag these:**
- § 3528 is TRUSTEE AUTHORITY TO INVADE PRINCIPAL/INCOME, NOT decanting → correct is § 3525/§ 3526
- § 3549 is MARITAL DEDUCTION GIFT (tax compliance), NOT cy pres → correct is § 3541
- § 1130 is DEFINITIONS, NOT unclaimed property reporting → correct is Chapter 11
- § 1901 is PERSONAL PROPERTY CONSTITUTING ASSETS OF ESTATE, NOT spousal elective share → correct is § 901
- § 3313 is INVESTMENT ADVISERS for directed trusts, NOT trust modification/revocation by settlor
- § 3302 is DEGREE OF CARE for trustees, NOT power of attorney for agents → correct is Chapter 49A
- § 501 is INTESTATE SUCCESSION (no will), NOT guardianship or estate administration → correct is § 3901 or Ch. 15

**Title 13/16 Health & Domestic Relations traps:**
- § 2321 (Title 13) is CONSENT BY PARENT (adoption), NOT comprehensive minor guardianship → correct is Ch. 23
- § 2501 (Title 16) is ADVANCE HEALTH-CARE DIRECTIVE ACT short title, NOT anatomical gifts → correct is Ch. 27

**Wrong-Title traps — ALWAYS flag these:**
- Title 25 (Property) cited for WILLS/PROBATE → correct is Title 12 (Decedents' Estates)
- Title 12 (Decedents' Estates) cited for HEALTH-CARE DIRECTIVES → correct is Title 16 (Health and Safety)
- Title 12 (Decedents' Estates) cited for MINOR GUARDIANSHIP → correct is Title 13 (Domestic Relations)
- Title 25 (Property) cited for ANATOMICAL GIFTS → correct is Title 16 (Health and Safety)
- 6 Del. C. § 5001 (Title 6 Definitions) for DIGITAL ASSETS FIDUCIARY ACCESS → correct is 12 Del. C. § 5001
- 13 Del. C. § 3901 for ADULT DISABILITY GUARDIANSHIP → correct is 12 Del. C. § 3901

**Federal boundary traps:**
- Estate tax, gift tax, GST tax, income tax on trusts/estates → FEDERAL, outside Delaware Code
- ERISA fiduciary standards for employee benefit plan trusts → FEDERAL, may preempt state law
- HIPAA for trust beneficiary health information → FEDERAL, outside Delaware Code

Output a JSON object with this exact structure:
{
  "citations": [
    {
      "input": "the exact citation text as it appears in the source",
      "title": <title number or null>,
      "section": "<section number without trailing period>",
      "subsection": "<subsection in parens or null>",
      "citation_type": "statute|constitution|court_rule|admin_code|federal|other_state|bill|uncovered"
    }
  ],
  "chapter_references": [
    {
      "input": "the exact chapter reference text",
      "title": <title number or null>,
      "chapter": "<chapter number>"
    }
  ],
  "broad_title_references": ["Title N references that don't specify section or chapter"],
  "outside_signals": ["federal or non-Delaware citations found in text"],
  "topic_notes": [
    {
      "citation": "<the cited section, e.g. 6 Del. C. § 17-406>",
      "section": "<section number only, e.g. 17-406>",
      "title": <title number or null>,
      "note": "<brief note if the citation seems mismatched to its context>"
    }
  ]
}

Rules:
- Include EVERY citation you find, in ANY format
- For "Title N, Section X" format: title=N, section=X
- For "Section X of Title N" format: title=N, section=X
- For "§ X of the Delaware Code/Act" without a Title: title=null, section=X
- For chapter references like "Chapter X of Title N" or "Title N, Chapter X": put in chapter_references
- For Admin Code: citation_type="admin_code"
- For federal (U.S.C., C.F.R.): citation_type="federal"
- For other states (New York, California, etc.): citation_type="other_state"
- For bills/legislation: citation_type="bill"
- For case law/opinions: citation_type="uncovered"
- Clean section numbers: remove trailing periods, keep subsection in parens
- If a citation topic seems wrong (e.g., LP statute cited for LLC context, Article 9 cited for warranty, federal FOIA for Delaware records), ALWAYS add a topic_note with the "section" field set to the cited section number
- For chapter-level mismatches (e.g., social work → ch.30 instead of ch.39), add a topic_note with "section" set to the chapter number
- For federal citations in Delaware context, add a topic_note suggesting the Delaware equivalent
- Output ONLY valid JSON, no markdown, no explanation"""


def validate_text_ai(
    text: str,
    db: DelawareLawDatabase | None = None,
    extracted: dict | None = None,
) -> dict[str, Any]:
    """Validate Delaware legal citations. If *extracted* (AI-produced JSON) is
    provided, merge it with database lookups. Otherwise fall back to regex.

    The agent should produce *extracted* by following SYSTEM_PROMPT — no
    external API call is made by this function.
    """
    if db is None:
        db = DelawareLawDatabase()

    if extracted is None:
        return _fallback_validate(text, db)

    return _build_results(db, text, extracted)


def _apply_topic_note_to_result(
    note: dict,
    cit_input: str,
    section: str,
    result: dict,
) -> None:
    """Apply a single AI topic_note to a citation/chapter result if it matches."""
    note_section = note.get("section", "").strip()
    note_citation = note.get("citation", "").lower().strip()
    note_text = note.get("note", "")
    if not note_text:
        return

    warning_text = f"主题可能不匹配：{note_text}"

    # Match by section number (most reliable)
    if note_section and section and note_section == section:
        result.setdefault("warnings", []).append(warning_text)
        return

    # Match by citation text substring
    cit_lower = cit_input.lower().strip()
    if note_citation:
        if note_citation in cit_lower:
            result.setdefault("warnings", []).append(warning_text)
            return
        if cit_lower in note_citation:
            result.setdefault("warnings", []).append(warning_text)
            return

    # Match by section number appearing in note's citation field
    if section and note_citation:
        clean_section = section.rstrip(".")
        if clean_section in note_citation:
            result.setdefault("warnings", []).append(warning_text)
            return


def _apply_all_topic_notes(
    notes: list[dict],
    cit_input: str,
    section: str,
    result: dict,
) -> None:
    """Apply all matching AI topic_notes to a result entry."""
    for note in notes:
        _apply_topic_note_to_result(note, cit_input, section, result)


def _context_for(citation: str, text: str, radius: int = 220) -> str:
    """Find a citation in text and return its context window."""
    idx = text.lower().find(citation.lower())
    if idx < 0:
        return text
    return _context_window(text, idx, idx + len(citation), radius)


def _chapter_has_sections(db: DelawareLawDatabase, title_number: int | None, chapter_number: str) -> bool:
    """Check if any sections exist for a given title+chapter prefix, even if the chapter itself isn't in the chapters table."""
    if not title_number or not chapter_number:
        return False
    pattern = f"{title_number}delc%{chapter_number}-%"
    rows = db.conn.execute(
        "SELECT COUNT(*) as cnt FROM materials WHERE normalized_citation LIKE ?",
        (pattern,),
    ).fetchone()
    return rows["cnt"] > 0 if rows else False


def _build_results(db: DelawareLawDatabase, text: str, extracted: dict) -> dict[str, Any]:
    """Build structured results from AI-extracted citations + database lookups.

    After AI processing, supplements with:
    - Regex-based citation extraction (for format variants the AI misses)
    - Registry-based topic rules (deterministic mismatch detection)
    - Smart chapter fallback (checks if sections exist for non-chapter structures like UCC Articles)
    """
    from .validator import validate_text

    topic_notes = extracted.get("topic_notes", [])
    outside_signals: list[str] = []
    admin_code_signals: list[str] = []
    bill_signals: list[str] = []

    # ── Run regex validator as supplement ────────────────────────────────
    regex_report = validate_text(db, text)
    regex_citations_map: dict[str, dict] = {}
    for cit in regex_report.get("citations", []):
        key = cit.get("input", "").lower().strip().rstrip(".")
        regex_citations_map[key] = cit

    # ── Process AI citations ─────────────────────────────────────────────
    ai_results: list[dict] = []
    seen_inputs: set[str] = set()

    for cit in extracted.get("citations", []):
        cit_input = cit.get("input", "")
        cit_type = cit.get("citation_type", "statute")
        title = cit.get("title")
        section = cit.get("section", "")
        subsection = cit.get("subsection")

        seen_inputs.add(cit_input.lower().strip().rstrip("."))

        # ── Non-Delaware citations ──
        if cit_type in ("federal", "other_state", "uncovered", "bill"):
            result = {
                "input": cit_input,
                "status": cit_type,
                "message": f"Non-Delaware citation ({cit_type})",
                "matches": [],
                "warnings": [f"当前数据库不覆盖{_type_label(cit_type)}引用。"],
                "suggestions": [],
            }
            _apply_all_topic_notes(topic_notes, cit_input, section, result)
            ai_results.append(result)
            outside_signals.append(cit_input)
            if cit_type == "bill":
                bill_signals.append(cit_input)
            continue

        # ── Admin Code citations ──
        if cit_type == "admin_code":
            result = {
                "input": cit_input, "status": "admin_code",
                "message": "Delaware Administrative Code 引用",
                "matches": [], "warnings": [
                    "Administrative Code 需通过 admin-refresh-index 和 admin-lookup 按需验证。"],
                "suggestions": [],
            }
            _apply_all_topic_notes(topic_notes, cit_input, section, result)
            ai_results.append(result)
            admin_code_signals.append(cit_input)
            continue

        # ── Delaware statute citation ──
        lookup_cit = cit_input
        if title and section:
            lookup_cit = f"{title} Del. C. § {section}"
            if subsection:
                lookup_cit += subsection

        query, rows = db.lookup(lookup_cit)
        result = _build_citation_entry(cit_input, query, rows)

        if result["status"] == "found" and query.section_number:
            _apply_topic_rules(db, query.section_number, query.subsection,
                               _context_for(cit_input, text), result, query.title_number)

        _apply_all_topic_notes(topic_notes, cit_input, section, result)
        ai_results.append(result)

    # ── Supplement: add regex citations the AI missed ────────────────────
    for key, regex_cit in regex_citations_map.items():
        if key not in seen_inputs:
            seen_inputs.add(key)
            ai_results.append(regex_cit)

    # ── Process chapter references ───────────────────────────────────────
    chapter_results: list[dict] = []
    for ch in extracted.get("chapter_references", []):
        ch_input = ch.get("input", "")
        chapter_num = ch.get("chapter", "")
        title_num = ch.get("title")
        chapter_query, ch_rows = db.lookup_chapter(ch_input)

        ch_result = {
            "input": ch_input, "status": "found" if ch_rows else "not_found",
            "message": "", "matches": [], "warnings": [], "suggestions": [],
        }

        if not chapter_query.chapter_number:
            ch_result["status"] = "invalid_format"
            ch_result["message"] = "无法识别为当前工具支持的 Delaware Chapter 引用格式。"
        elif not ch_rows:
            # Smart fallback: check if sections exist for this title+chapter
            effective_title = title_num or chapter_query.title_number
            if _chapter_has_sections(db, effective_title, chapter_query.chapter_number):
                ch_result["status"] = "found"
                ch_result["message"] = "当前数据包中找到对应条文（非标准 Chapter 结构）。"
                ch_result["warnings"].append("该引用指向的可能是 Subtitle/Article 等非 Chapter 组织单位。")
            else:
                ch_result["message"] = "本地数据库未检出该 Chapter 引用。"
                ch_result["warnings"].append("请勿据此认定该 Chapter 不存在，应核查官方来源或更新数据库。")
        else:
            ch_result["message"] = "当前数据包中找到该 Chapter。"
            for row in ch_rows[:8]:
                ch_result["matches"].append({
                    "citation": row["citation"], "heading": row["heading"],
                    "source_file": row["source_file"], "source_url": row["source_url"],
                })
            if len(ch_rows) > 1:
                ch_result["warnings"].append("该 Chapter 编号在多个 Title 中出现；请补充 Title 号。")

        _apply_all_topic_notes(topic_notes, ch_input, chapter_num, ch_result)
        chapter_results.append(ch_result)

    # ── Supplement: add regex chapter references ─────────────────────────
    regex_chapter_inputs = {
        ch.get("input", "").lower().strip().rstrip(".")
        for ch in chapter_results
    }
    for ch in regex_report.get("chapter_references", []):
        if ch.get("input", "").lower().strip().rstrip(".") not in regex_chapter_inputs:
            chapter_results.append(ch)

    # ── Broad title references ───────────────────────────────────────────
    broad_refs = regex_report.get("broad_references", [])
    for bt in extracted.get("broad_title_references", []):
        existing = {str(b.get("input", "")).lower() for b in broad_refs}
        if str(bt).lower() not in existing:
            broad_refs.append({
                "input": bt, "status": "overbroad",
                "message": "仅引用 Title 过于宽泛，应定位到具体 Chapter 或 Section。",
                "matches": [], "warnings": ["请勿以宽泛引用作为具体法律依据。"], "suggestions": [],
            })

    # ── Coverage warnings ────────────────────────────────────────────────
    coverage_warnings = list(regex_report.get("coverage_warnings", []))
    if outside_signals and not any("混入 Delaware 以外" in w for w in coverage_warnings):
        coverage_warnings.append("文本中可能混入 Delaware 以外或联邦法律引用，当前数据库不能验证这些材料。")

    # ── Merge topic_reviews: AI + registry ───────────────────────────────
    ai_topic_reviews: list[dict] = []
    for n in topic_notes:
        note_text = n.get("note", "")
        if note_text:
            ai_topic_reviews.append({
                "category": "主题审查", "code": "ai_topic_check",
                "message": note_text, "suggestions": [], "coverage": {},
            })

    existing_codes = {r.get("code", "") for r in ai_topic_reviews}
    for review in regex_report.get("topic_reviews", []):
        if review.get("code", "") not in existing_codes:
            ai_topic_reviews.append(review)
            existing_codes.add(review.get("code", ""))

    # ── Merge implicit references ────────────────────────────────────────
    registry_implicit = list(regex_report.get("implicit_references", []))

    # ── Database misses ──────────────────────────────────────────────────
    database_misses: list[dict] = []
    for item in ai_results:
        if item.get("status") == "not_found":
            database_misses.append({
                "kind": "citation", "input": item.get("input"),
                "message": item.get("message"),
                "warnings": item.get("warnings", []),
                "suggestions": item.get("suggestions", []),
            })
    for item in chapter_results:
        if item.get("status") == "not_found":
            database_misses.append({
                "kind": "chapter", "input": item.get("input"),
                "message": item.get("message"),
                "warnings": item.get("warnings", []),
                "suggestions": item.get("suggestions", []),
            })

    return {
        "citation_count": len(ai_results),
        "citations": ai_results,
        "court_rule_reference_count": regex_report.get("court_rule_reference_count", 0),
        "court_rule_references": regex_report.get("court_rule_references", []),
        "chapter_reference_count": len(chapter_results),
        "chapter_references": chapter_results,
        "broad_reference_count": len(broad_refs),
        "broad_references": broad_refs,
        "topic_review_count": len(ai_topic_reviews),
        "topic_reviews": ai_topic_reviews,
        "implicit_reference_count": len(registry_implicit),
        "implicit_references": registry_implicit,
        "database_misses": database_misses,
        "rag_candidates": [],
        "outside_delaware_signals": list(set(
            list(outside_signals) + regex_report.get("outside_delaware_signals", [])
        )),
        "uncovered_material_signals": regex_report.get("uncovered_material_signals", []),
        "admin_code_signals": list(set(
            admin_code_signals + regex_report.get("admin_code_signals", [])
        )),
        "bill_signals": list(set(
            bill_signals + regex_report.get("bill_signals", [])
        )),
        "coverage_warnings": coverage_warnings,
    }


def _build_citation_entry(
    cit_input: str,
    query,
    rows: list,
) -> dict:
    """Build a single citation result entry from a database lookup."""
    result = {
        "input": cit_input,
        "status": "found" if rows else "not_found",
        "message": "",
        "matches": [],
        "warnings": [],
        "suggestions": [],
    }
    if not query.section_number:
        result["status"] = "invalid_format"
        result["message"] = "无法识别为当前工具支持的 Delaware 引用格式。"
    elif not rows:
        if query.title_number and query.title_number > 31:
            result["message"] = f"Title {query.title_number} 超出当前数据包覆盖范围（Title 1-31）。"
            result["warnings"].append("当前数据包仅覆盖 Delaware Code Title 1-31。")
        else:
            result["message"] = "本地数据库未检出该引用。"
            result["warnings"].append("请勿据此认定该条文不存在，应核查官方来源或更新数据库。")
    else:
        result["message"] = "当前数据包中找到该引用。"
        for row in rows[:5]:
            result["matches"].append({
                "citation": row["citation"], "heading": row["heading"],
                "source_file": row["source_file"], "source_url": row["source_url"],
            })
    return result


def _fallback_validate(text: str, db: DelawareLawDatabase) -> dict[str, Any]:
    """Fallback to regex-based validation when API is unavailable."""
    from .validator import validate_text
    return validate_text(db, text)


def _type_label(ct: str) -> str:
    labels = {
        "federal": "联邦",
        "other_state": "其他州",
        "uncovered": "判例/意见",
        "bill": "法案/议案",
    }
    return labels.get(ct, ct)
