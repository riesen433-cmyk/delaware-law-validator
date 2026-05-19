from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .database import DelawareLawDatabase, parse_chapter_reference
from .registry import CROSS_TITLE_NUMBER_TRAPS


FULL_DELCODE_RE = re.compile(
    r"\b\d+\s+Del\.?\s*C\.?\s*§+\s*[A-Za-z0-9][A-Za-z0-9.\-]*(?:\([A-Za-z0-9]+\))*",
    re.IGNORECASE,
)
SECTION_ONLY_RE = re.compile(
    r"(?:§+\s*|Section\s+)[A-Za-z0-9][A-Za-z0-9.\-]*(?:\([A-Za-z0-9]+\))*"
    r"(?:\s+of\s+the\s+Delaware\s+(?:Act|Code|DRULPA|General Corporation Law|LLC Act))?",
    re.IGNORECASE,
)
TITLE_SECTION_RE = re.compile(
    r"\bTitle\s+(?P<title>\d+)\s*,?\s*Section\s+(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*(?:\([A-Za-z0-9]+\))*)\b",
    re.IGNORECASE,
)
SECTION_OF_TITLE_RE = re.compile(
    r"\bSection\s+(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*(?:\([A-Za-z0-9]+\))*)\s+of\s+Title\s+(?P<title>\d+)\b",
    re.IGNORECASE,
)
CHAPTER_REF_RE = re.compile(
    r"(?:Title\s+\d+\s*,?\s*)?(?:Chapter|Ch\.?)\s*[0-9][A-Za-z0-9.-]*"
    r"(?:\s+of\s+Title\s+\d+|\s+of\s+the\s+Delaware\s+Code|\s+of\s+the\s+Delaware\s+Code)?",
    re.IGNORECASE,
)
COURT_RULE_REF_RE = re.compile(
    r"\b(?:"
    r"Del\.?\s*Ch\.?\s*Ct\.?\s*R\.?|Court\s+of\s+Chancery\s+Rule|Chancery\s+Rule|"
    r"Del\.?\s*Super\.?\s*Ct\.?\s*Civ\.?\s*R\.?|Superior\s+Court\s+Civil\s+Rule|"
    r"Del\.?\s*Super\.?\s*Ct\.?\s*Spec\.?\s*R\.?|Special\s+Rule(?:\s+of\s+Procedure)?|"
    r"Del\.?\s*Supr\.?\s*Ct\.?\s*R\.?|Supreme\s+Court\s+Rule|"
    r"Del\.?\s*Fam\.?\s*Ct\.?\s*Civ\.?\s*R\.?|Family\s+Court\s+Civil\s+Rule|"
    r"Del\.?\s*Ct\.?\s*Com\.?\s*Pl\.?\s*Civ\.?\s*R\.?|Court\s+of\s+Common\s+Pleas\s+Civil\s+Rule|"
    r"D\.?\s*R\.?\s*E\.?|Delaware\s+(?:Uniform\s+)?Rules?\s+of\s+Evidence|Delaware\s+Rule\s+of\s+Evidence|Rule\s+of\s+Evidence|"
    r"Del\.?\s*Rapid\s+Arb\.?\s*R\.?|Delaware\s+Rapid\s+Arbitration\s+Rule|Rapid\s+Arbitration\s+Rule|"
    r"Del\.?\s*Ct\.?\s*Jud\.?\s*R\.?|Court\s+on\s+the\s+Judiciary\s+Rule"
    r")\s*(?:No\.?\s*)?[0-9][0-9A-Za-z.-]*(?:\([A-Za-z0-9]+\))*",
    re.IGNORECASE,
)
BROAD_TITLE_RE = re.compile(
    r"\bTitle\s+(?P<title>\d+)\b(?:\s+of\s+(?:the\s+)?Delaware\s+Code)?",
    re.IGNORECASE,
)
NON_DELAWARE_RE = re.compile(
    r"\b(?:\d+\s+U\.S\.C\.?\s*§+\s*[A-Za-z0-9.-]+|\d+\s+C\.F\.R\.?\s*(?:§+\s*|Part\s+)[A-Za-z0-9.-]+|New York|N\.Y\.|California|Cal\.|Nevada|Nev\.|HIPAA|FERPA|DEA|FDA|Medicare|Medicaid)\b",
    re.IGNORECASE,
)
UNCOVERED_RE = re.compile(
    r"\b(?:Del\. Ch\.|Del\. Supr\.|A\.\d+d|A\.3d|opinion|case law|判例)\b",
    re.IGNORECASE,
)
ADMIN_CODE_RE = re.compile(
    r"\b\d+\s+(?:DE|Del\.?)\s+Admin\.?\s*Code\s*§?\s*[A-Za-z0-9.-]+",
    re.IGNORECASE,
)
BILLS_RE = re.compile(
    r"\b(?:Senate\s+Bill|House\s+Bill|S\.\s*B\.|H\.\s*B\.)\s*\d+"
    r"|\b\d+(?:st|nd|rd|th)\s+General\s+Assembly\b",
    re.IGNORECASE,
)

RELIANCE_TERMS = {
    "rely",
    "reliance",
    "opinion",
    "opinions",
    "report",
    "reports",
    "information",
    "professional",
    "expert",
    "信赖",
    "依赖",
    "顾问",
    "意见",
    "报告",
    "专业",
}
SOLVENCY_TERMS = {
    "asset-to-liability",
    "asset",
    "liability",
    "liabilities",
    "solvency",
    "distribution",
    "ratio",
    "fair value",
    "资产",
    "负债",
    "偿付能力",
    "分配",
    "比率",
}
UNDERGROUND_UTILITY_TERMS = {
    "underground utility",
    "utility damage",
    "damage prevention",
    "excavat",
    "one-call",
    "one call",
    "utility line",
}
PUBLIC_RECORDS_TERMS = {
    "public record",
    "public records",
    "freedom of information",
    "foia",
    "open records",
}
PUBLIC_WORKS_BOND_TERMS = {
    "bid bond",
    "performance bond",
    "payment bond",
    "construction bond",
    "public works",
    "public work",
}
PROCUREMENT_TERMS = {
    "procurement",
    "public works",
    "public work",
    "bid",
    "bidding",
    "professional services",
    "nonprofessional services",
}
ENVIRONMENTAL_TERMS = {
    "environmental",
    "dnrec",
    "permit",
    "permits",
    "hazardous",
    "waste",
    "water",
    "air quality",
}
UTILITY_RATE_TERMS = {
    "utility rate",
    "public utility",
    "rate change",
    "tariff",
    "commission",
}
COMPUTER_CRIME_TERMS = {
    "unauthorized access",
    "computer crime",
    "computer crimes",
    "computer system",
    "criminal",
}
FEDERAL_BOUNDARY_TERMS = {
    "hipaa",
    "ferpa",
    "dea",
    "fda",
    "medicare",
    "medicaid",
}
FEDERAL_TAX_ERISA_TERMS = {
    "estate tax", "gift tax", "generation-skipping transfer tax", "gst tax",
    "income tax", "internal revenue code", "irc §", "26 u.s.c",
    "erisa", "employee retirement income security act",
    "ira", "401(k)", "retirement plan", "employee benefit plan",
}
GOOD_SAMARITAN_TERMS = {
    "good samaritan",
    "emergency care immunity",
    "volunteer medical immunity",
    "overdose immunity",
    "emergency care at the scene",
    "immune from civil liability",
    "renders emergency",
}
TRUST_ESTATES_TERMS = {
    "trust", "trustee", "fiduciary", "decedent", "estate", "probate",
    "will", "testament", "testamentary", "intestate", "settlor",
    "personal representative", "letters testamentary",
}
WRONG_TITLE_WILLS_TERMS = {
    "will", "probate", "executor", "testamentary", "decedents",
}
WRONG_TITLE_HEALTHCARE_TERMS = {
    "advance health-care", "health-care directive", "living will",
    "medical power of attorney", "health care agent",
}
WRONG_TITLE_GUARDIANSHIP_TERMS = {
    "minor guardian", "guardian of a minor", "minor child",
}
WRONG_TITLE_ANATOMICAL_TERMS = {
    "anatomical gift", "organ donation", "body", "tissues", "organs",
    "transplantation", "deceased donor",
}
TELEHEALTH_TERMS = {
    "telehealth",
    "telemedicine",
    "remote health",
    "remote care",
    "virtual care",
}
HEALTH_CARE_TERMS = {
    "health",
    "health-care",
    "healthcare",
    "medical",
    "medicine",
    "physician",
    "nursing",
    "nurse",
    "pharmacy",
    "pharmacist",
    "behavioral",
    "social work",
    "psychology",
    "counseling",
}
PROFESSION_TERMS = {
    "pharmacy",
    "pharmacist",
    "medicine",
    "medical practice",
    "physician",
    "nursing",
    "nurse",
    "mental health",
    "chemical dependency",
    "counseling",
    "professional counselor",
    "psychology",
    "psychologist",
    "social work",
    "social worker",
}
PROFESSION_CHAPTERS = [
    ({"pharmacy", "pharmacist"}, "24 Del. C. ch. 25", "pharmacy practice maps to the Board of Pharmacy chapter。"),
    ({"medicine", "medical practice", "physician"}, "24 Del. C. ch. 17", "medical practice maps to the Medical Practice Act。"),
    ({"nursing", "nurse"}, "24 Del. C. ch. 19", "nursing maps to the Nursing chapter。"),
    ({"mental health", "chemical dependency", "counseling", "professional counselor"}, "24 Del. C. ch. 30", "mental health / chemical dependency professionals map to Chapter 30。"),
    ({"psychology", "psychologist"}, "24 Del. C. ch. 35", "psychology maps to the Psychology chapter。"),
    ({"social work", "social worker"}, "24 Del. C. ch. 39", "social work maps to the Board of Social Work Examiners chapter。"),
]
UCC_ARTICLE_RE = re.compile(r"\b(?:Delaware\s+)?(?:UCC\s+)?Article\s+(?P<article>2A|[2789])\b", re.IGNORECASE)
UCC_CONTEXT_TERMS = {
    "ucc",
    "uniform commercial code",
    "security interest",
    "perfection",
    "perfected",
    "financing statement",
    "collateral",
    "priority",
    "control",
    "goods",
    "sale of goods",
    "leases",
    "investment securities",
    "documents of title",
    "warehouse receipt",
}
UCC_SECURED_TRANSACTION_TERMS = {
    "security interest",
    "perfection", "perfected", "perfect",
    "financing statement",
    "collateral",
    "priority",
    "control",
    "secured transaction",
}
WARRANTY_TERMS = {
    "warranty", "warranties",
    "disclaimer", "disclaim",
    "merchantability",
    "implied warranty",
    "warranty of fitness",
}
UCC_ARTICLE_LABELS = {
    "2": "Sales / Sale of Goods",
    "2A": "Leases",
    "7": "Documents of Title",
    "8": "Investment Securities",
    "9": "Secured Transactions",
}


@dataclass(frozen=True)
class ExtractedCitation:
    text: str
    start: int
    end: int
    context: str


def validate_text(db: DelawareLawDatabase, text: str) -> dict[str, Any]:
    citations = _extract_citations(text)
    court_rule_refs = _extract_court_rule_references(text, citations)
    chapter_refs = _extract_chapter_references(text, citations)
    broad_title_refs = _extract_broad_title_references(db, text, chapter_refs)
    topic_reviews = _build_topic_reviews(db, text)
    implicit_references = _build_implicit_references(db, text)
    results: list[dict[str, Any]] = []

    for citation in citations:
        query, rows = db.lookup(citation.text)
        inferred_title = _infer_title_from_context(citation)
        if inferred_title is not None and query.title_number is None and query.section_number:
            query, rows = db.lookup(f"{inferred_title} Del. C. § {query.section_number}{query.subsection or ''}")
        result: dict[str, Any] = {
            "input": citation.text,
            "status": "found" if rows else "not_found",
            "message": "",
            "matches": [],
            "warnings": [],
            "suggestions": [],
        }

        if not query.section_number:
            result["status"] = "invalid_format"
            result["message"] = "无法识别为当前工具支持的 Delaware 引用格式。"
            results.append(result)
            continue

        if not rows:
            result["message"] = "本地数据库未检出该引用。"
            result["warnings"].append("不得据此认定该条文不存在；请回查官方来源或更新数据库。")
            results.append(result)
            continue

        result["message"] = "当前数据包中找到该引用。"
        for row in rows[:5]:
            match = {
                "citation": row["citation"],
                "heading": row["heading"],
                "source_file": row["source_file"],
                "source_url": row["source_url"],
            }
            result["matches"].append(match)

        if query.subsection and not _subsection_exists(rows[0]["text"], query.subsection):
            result["warnings"].append(f"找到主条文，但没有明显找到分款 {query.subsection}。")

        _apply_topic_rules(db, query.section_number, query.subsection, citation.context, result, query.title_number)
        results.append(result)

    court_rule_results = [_validate_court_rule_reference(db, rule_ref) for rule_ref in court_rule_refs]
    outside = [match.group(0) for match in NON_DELAWARE_RE.finditer(text)]
    uncovered = sorted(set(match.group(0) for match in UNCOVERED_RE.finditer(text)))
    admin_code_signals_list = [match.group(0) for match in ADMIN_CODE_RE.finditer(text)]
    bill_signals_list = [match.group(0) for match in BILLS_RE.finditer(text)]
    coverage_warnings: list[str] = []
    if outside:
        coverage_warnings.append("文本中可能混入 Delaware 以外或联邦法律引用，当前数据库不能验证这些材料。")
    if uncovered:
        coverage_warnings.append("文本中提到判例或意见类材料；当前数据包暂不覆盖这些内容。")
    if admin_code_signals_list:
        coverage_warnings.append(
            "文本中包含 Delaware Administrative Code 引用，请通过 admin-refresh-index --title N 刷新索引"
            "并通过 admin-lookup / admin-search 按需抓取官方 PDF。"
        )
    if bill_signals_list:
        coverage_warnings.append(
            "文本中包含法案/议案引用（Bill / General Assembly）；"
            "当前数据包不包含 session laws 或 pending legislation，请勿将其作为现行法律引用。"
        )

    chapter_results = [_validate_chapter_reference(db, chapter) for chapter in chapter_refs]
    database_misses = _collect_database_misses(results, chapter_results, broad_title_refs, court_rule_results)

    return {
        "citation_count": len(citations),
        "citations": results,
        "court_rule_reference_count": len(court_rule_refs),
        "court_rule_references": court_rule_results,
        "chapter_reference_count": len(chapter_refs),
        "chapter_references": chapter_results,
        "broad_reference_count": len(broad_title_refs),
        "broad_references": broad_title_refs,
        "topic_review_count": len(topic_reviews),
        "topic_reviews": topic_reviews,
        "implicit_reference_count": len(implicit_references),
        "implicit_references": implicit_references,
        "database_misses": database_misses,
        "rag_candidates": [],
        "outside_delaware_signals": outside,
        "uncovered_material_signals": uncovered,
        "admin_code_signals": admin_code_signals_list,
        "bill_signals": bill_signals_list,
        "coverage_warnings": coverage_warnings,
    }


def _extract_citations(text: str) -> list[ExtractedCitation]:
    spans: list[tuple[int, int, str]] = []
    for match in FULL_DELCODE_RE.finditer(text):
        spans.append((match.start(), match.end(), match.group(0)))

    for match in SECTION_ONLY_RE.finditer(text):
        if any(_overlaps(match.start(), match.end(), start, end) for start, end, _ in spans):
            continue
        if _is_part_of_non_delaware_citation(text, match.start()):
            continue
        value = match.group(0)
        if _is_ordinary_document_section(value):
            continue
        spans.append((match.start(), match.end(), value))

    # "Title N, Section X" → normalize to "N Del. C. § X"
    for match in TITLE_SECTION_RE.finditer(text):
        if any(_overlaps(match.start(), match.end(), start, end) for start, end, _ in spans):
            continue
        title = match.group("title")
        section = match.group("section")
        normalized = f"{title} Del. C. § {section}"
        spans.append((match.start(), match.end(), normalized))

    # "Section X of Title N" → normalize to "N Del. C. § X"
    for match in SECTION_OF_TITLE_RE.finditer(text):
        if any(_overlaps(match.start(), match.end(), start, end) for start, end, _ in spans):
            continue
        title = match.group("title")
        section = match.group("section")
        normalized = f"{title} Del. C. § {section}"
        spans.append((match.start(), match.end(), normalized))

    spans.sort(key=lambda item: item[0])
    return [
        ExtractedCitation(value.strip(), start, end, _context_window(text, start, end))
        for start, end, value in spans
    ]


def _extract_chapter_references(
    text: str,
    section_citations: list[ExtractedCitation],
) -> list[ExtractedCitation]:
    spans: list[tuple[int, int, str]] = []
    citation_spans = [(citation.start, citation.end) for citation in section_citations]
    for match in CHAPTER_REF_RE.finditer(text):
        if any(_overlaps(match.start(), match.end(), start, end) for start, end in citation_spans):
            continue
        spans.append((match.start(), match.end(), match.group(0)))
    spans.sort(key=lambda item: item[0])
    return [
        ExtractedCitation(value.strip(), start, end, _context_window(text, start, end))
        for start, end, value in spans
    ]


def _extract_court_rule_references(
    text: str,
    section_citations: list[ExtractedCitation],
) -> list[ExtractedCitation]:
    spans: list[tuple[int, int, str]] = []
    citation_spans = [(citation.start, citation.end) for citation in section_citations]
    for match in COURT_RULE_REF_RE.finditer(text):
        if any(_overlaps(match.start(), match.end(), start, end) for start, end in citation_spans):
            continue
        spans.append((match.start(), match.end(), match.group(0)))
    spans.sort(key=lambda item: item[0])
    return [
        ExtractedCitation(value.strip(), start, end, _context_window(text, start, end))
        for start, end, value in spans
    ]


def _validate_court_rule_reference(db: DelawareLawDatabase, citation: ExtractedCitation) -> dict[str, Any]:
    query, rows = db.lookup_rule(citation.text)
    result: dict[str, Any] = {
        "input": citation.text,
        "status": "found" if rows else "not_found",
        "message": "",
        "matches": [],
        "warnings": [],
        "suggestions": [],
    }
    if not query.rule_number:
        result["status"] = "invalid_format"
        result["message"] = "无法识别为当前工具支持的 Delaware court rule 引用格式。"
        return result
    if not rows:
        result["message"] = "本地数据库未检出该 court rule 引用。"
        result["warnings"].append("不得据此认定该规则不存在；请回查 Delaware Courts 官方来源或更新数据库。")
        return result

    result["message"] = "当前数据包中找到该 court rule 引用。"
    for row in rows[:8]:
        result["matches"].append(
            {
                "citation": row["citation"],
                "heading": row["heading"],
                "source_file": row["source_file"],
                "source_url": row["source_url"],
            }
        )
    if len(rows) > 1:
        result["warnings"].append("该规则编号在多个规则集中出现；引用时建议写明具体法院或规则集。")
    if query.subsection and not _subsection_exists(rows[0]["text"], query.subsection):
        result["warnings"].append(f"找到主规则，但没有明显找到分款 {query.subsection}。")
    return result


def _extract_broad_title_references(
    db: DelawareLawDatabase,
    text: str,
    chapter_refs: list[ExtractedCitation],
) -> list[dict[str, Any]]:
    chapter_spans = [(chapter.start, chapter.end) for chapter in chapter_refs]
    results: list[dict[str, Any]] = []
    for match in BROAD_TITLE_RE.finditer(text):
        if any(_overlaps(match.start(), match.end(), start, end) for start, end in chapter_spans):
            continue
        if _is_part_of_chapter_reference(text, match.start(), match.end()):
            continue
        title_number = int(match.group("title"))
        row = db.get_title(title_number)
        result = {
            "input": match.group(0),
            "status": "overbroad" if row else "not_found",
            "message": "整部 Title 引用过宽；具体法律结论应落到具体 Chapter 或 Section。" if row else "本地数据库未检出该 Title。",
            "matches": [],
            "warnings": [] if row else ["不得据此认定该 Title 不存在；请回查官方来源或更新数据库。"],
            "suggestions": [],
        }
        if row:
            result["matches"].append(
                {
                    "title_number": row["title_number"],
                    "title_name": row["title_name"],
                    "source_file": row["file_name"],
                    "source_url": row["source_url"],
                }
            )
            result["warnings"].append("可以作为范围描述，但不宜作为具体法律依据。")
            context = _context_window(text, match.start(), match.end()).lower()
            result["suggestions"].extend(_title_context_suggestions(db, title_number, context))
            if title_number == 29 and _contains_any(context, PROCUREMENT_TERMS):
                result["suggestions"].extend(
                    _authority_suggestions(
                        db,
                        [
                            ("29 Del. C. ch. 69", "采购问题应先定位到 State Procurement 章。"),
                            ("29 Del. C. § 6960", "public works 项目可能涉及 prevailing wage requirements。"),
                            ("29 Del. C. § 6961", "small public works contract procedures。"),
                            ("29 Del. C. § 6962", "large public works contract procedures。"),
                        ],
                    )
                )
        results.append(result)
    return results


def _is_part_of_chapter_reference(text: str, start: int, end: int) -> bool:
    after = text[end : end + 40]
    return bool(re.match(r"\s*,?\s*(?:Chapter|Ch\.?)\s*[0-9]", after, re.IGNORECASE))


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


def _validate_chapter_reference(db: DelawareLawDatabase, citation: ExtractedCitation) -> dict[str, Any]:
    query, rows = db.lookup_chapter(citation.text)
    result: dict[str, Any] = {
        "input": citation.text,
        "status": "found" if rows else "not_found",
        "message": "",
        "matches": [],
        "warnings": [],
        "suggestions": [],
    }
    if not query.chapter_number:
        result["status"] = "invalid_format"
        result["message"] = "无法识别为当前工具支持的 Delaware Chapter 引用格式。"
        return result
    if not rows:
        # Smart fallback: check if sections exist for this title+chapter
        # (handles UCC Articles and other non-chapter organizational units)
        if _chapter_has_sections(db, query.title_number, query.chapter_number):
            result["status"] = "found"
            result["message"] = "当前数据包中找到对应条文（非标准 Chapter 结构）。"
            result["warnings"].append("该引用指向的可能是 Subtitle/Article 等非 Chapter 组织单位。")
            return result

        result["message"] = "本地数据库未检出该 Chapter 引用。"
        result["warnings"].append("不得据此认定该 Chapter 不存在；请回查官方来源或更新数据库。")
        if query.title_number == 6 and query.chapter_number.upper() == "12C":
            result["suggestions"].append(
                {
                    "citation": "6 Del. C. § 1205C",
                    "heading": "Posting of privacy policy by operators of commercial online sites and services",
                    "reason": "在线服务隐私政策常见具体条文在 § 1205C。",
                }
            )
        return result

    result["message"] = "当前数据包中找到该 Chapter。"
    for row in rows[:8]:
        result["matches"].append(
            {
                "citation": row["citation"],
                "heading": row["heading"],
                "source_file": row["source_file"],
                "source_url": row["source_url"],
            }
        )
    if len(rows) > 1:
        result["warnings"].append("该 Chapter 编号在多个 Title 中出现；请补充 Title 号。")
    else:
        result["warnings"].append("章级引用用于具体结论时，应定位到具体 Section。")
    return result


def _build_topic_reviews(db: DelawareLawDatabase, text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    reviews: list[dict[str, Any]] = []

    if _contains_any(lowered, UNDERGROUND_UTILITY_TERMS):
        wrong_chapter = re.search(
            r"(?:Title\s+26\s*,?\s*(?:Chapter|Ch\.?)\s*12|26\s+Del\.?\s*C\.?\s*(?:ch\.?|chapter)\s*12)",
            text,
            re.IGNORECASE,
        )
        title_21 = re.search(r"(?:Title\s+21|21\s+Del\.?\s*C\.?)", text, re.IGNORECASE)
        if wrong_chapter or title_21:
            reviews.append(
                _topic_review(
                    "错误引用",
                    "underground_utility_wrong_title_or_chapter",
                    "地下管线损害预防主题应定位到 Title 26, Chapter 8，而不是 Title 26 Chapter 12 或 Title 21。",
                    _authority_suggestions(
                        db,
                        [
                            ("26 Del. C. ch. 8", "Underground Utility Damage Prevention and Safety。"),
                            ("26 Del. C. § 801", "Purpose; citation; construction。"),
                        ],
                    ),
                )
            )

    if _contains_any(lowered, PUBLIC_RECORDS_TERMS) and re.search(r"\b5\s+U\.S\.C\.?\s*§?\s*552\b|federal\s+foia", text, re.IGNORECASE):
        reviews.append(
            _topic_review(
                "错误引用",
                "federal_foia_drift",
                "Delaware public body 的公共记录问题应先查 Delaware FOIA，不能直接套用联邦 FOIA。",
                _authority_suggestions(
                    db,
                    [
                        ("29 Del. C. ch. 100", "Freedom of Information Act。"),
                        ("29 Del. C. § 10003", "Examination and copying of public records。"),
                    ],
                ),
            )
        )

    if _contains_any(lowered, PUBLIC_WORKS_BOND_TERMS) and re.search(r"\bTitle\s+18\b|insurance", text, re.IGNORECASE):
        reviews.append(
            _topic_review(
                "错误引用",
                "public_works_bond_not_insurance_title",
                "公共工程 bid/performance/payment bond 问题不应只归入 Title 18 保险法，应先查采购和公共工程合同规则。",
                _authority_suggestions(
                    db,
                    [
                        ("29 Del. C. ch. 69", "State Procurement。"),
                        ("29 Del. C. § 6927", "Bid and contract security。"),
                        ("29 Del. C. § 6961", "Small public works contract procedures。"),
                        ("29 Del. C. § 6962", "Large public works contract procedures。"),
                    ],
                ),
            )
        )

    if re.search(r"\bTitle\s+7\b|7\s+Del\.?\s*C\.?", text, re.IGNORECASE) and _contains_any(lowered, ENVIRONMENTAL_TERMS):
        reviews.append(
            _topic_review(
                "需外部材料",
                "environmental_regulations_needed",
                "环境许可通常不只看 Delaware Code。当前数据包覆盖 Delaware Code Title 7，但不覆盖 DNREC regulations、Delaware Administrative Code、地方条例或行政政策。",
                [],
                coverage={
                    "covered": "Delaware Code Title 7",
                    "not_covered": "DNREC regulations / Delaware Administrative Code / local ordinances / administrative policy",
                },
            )
        )

    if _contains_any(lowered, UTILITY_RATE_TERMS) and ("rate" in lowered or "contract" in lowered):
        reviews.append(
            _topic_review(
                "需外部材料",
                "utility_rate_change_context",
                "公用事业费率或 tariff 变更通常不能只靠合同修改判断，需核对 Public Service Commission 相关规则和适用费率程序。",
                _authority_suggestions(
                    db,
                    [("26 Del. C. § 306", "Effective date of rate change; refund bond。")],
                ),
            )
        )

    if re.search(r"11\s+Del\.?\s*C\.?\s*§\s*932|§\s*932", text, re.IGNORECASE) or _contains_any(lowered, COMPUTER_CRIME_TERMS):
        reviews.append(
            _topic_review(
                "已验证引用",
                "computer_crime_requires_statutory_set",
                "§ 932 可作为 unauthorized access 起点，但不能单独证明所有未授权访问都自动构成犯罪；还要核对具体构成、损害金额、处罚和 venue。",
                _authority_suggestions(
                    db,
                    [
                        ("11 Del. C. § 932", "Unauthorized access。"),
                        ("11 Del. C. § 933", "Theft of computer services。"),
                        ("11 Del. C. § 934", "Interruption of computer services。"),
                        ("11 Del. C. § 935", "Misuse of computer system information。"),
                        ("11 Del. C. § 936", "Destruction of computer equipment。"),
                        ("11 Del. C. § 937", "Unrequested or unauthorized electronic mail or use of network or software to cause same。"),
                        ("11 Del. C. § 938", "Failure to promptly cease electronic communication upon request。"),
                        ("11 Del. C. § 939", "Penalties。"),
                        ("11 Del. C. § 940", "Venue。"),
                    ],
                ),
            )
        )

    reviews.extend(_build_trust_estates_topic_reviews(db, text))
    reviews.extend(_build_ucc_topic_reviews(db, text))
    reviews.extend(_build_health_topic_reviews(db, text))

    return reviews


def _build_health_topic_reviews(db: DelawareLawDatabase, text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    reviews: list[dict[str, Any]] = []

    if _contains_any(lowered, FEDERAL_BOUNDARY_TERMS):
        reviews.append(
            _topic_review(
                "需要查外部材料",
                "federal_health_education_boundary",
                "文本涉及 HIPAA / FERPA / DEA / FDA / Medicare / Medicaid 等联邦法律或项目；当前数据包不能验证这些外部材料。",
                [],
                coverage={
                    "covered": "Delaware Code Title 1-31",
                    "not_covered": "HIPAA / FERPA / DEA / FDA / Medicare / Medicaid and other federal materials",
                },
            )
        )

    if _contains_any(lowered, TELEHEALTH_TERMS):
        reviews.append(
            _topic_review(
                "可能影响结论的相关法律",
                "telehealth_profession_specific",
                "远程医疗/telehealth 不应只靠单一职业条文判断；一般 health-care telehealth 应先查 Title 24 Chapter 60，并按具体职业章节和行政规则复核。",
                _authority_suggestions(
                    db,
                    [
                        ("24 Del. C. ch. 60", "general telehealth and telemedicine framework。"),
                        ("24 Del. C. § 6002", "authorization to practice by telehealth and telemedicine。"),
                        ("24 Del. C. § 6004", "practice requirements。"),
                    ],
                ),
                coverage={"not_covered": "professional board regulations / Delaware Administrative Code"},
            )
        )
    if _contains_any(lowered, {"social work", "social worker"}) and re.search(
        r"(?:Title\s+24\s*,?\s*(?:Chapter|Ch\.?)\s*30|24\s+Del\.?\s*C\.?\s*(?:ch\.?|chapter)\s*30)",
        text,
        re.IGNORECASE,
    ):
        reviews.append(
            _topic_review(
                "明显错误",
                "social_work_not_chapter_30",
                "Social work 专业许可应定位到 Title 24 Chapter 39；Chapter 30 是 mental health and chemical dependency professionals，不是 social work 章节。",
                _authority_suggestions(
                    db,
                    [
                        ("24 Del. C. ch. 39", "Board of Social Work Examiners。"),
                        ("24 Del. C. § 3903", "License required for social work。"),
                        ("24 Del. C. ch. 30", "mental health and chemical dependency professionals, not social work。"),
                    ],
                ),
            )
        )

    if _contains_any(lowered, PROFESSION_TERMS):
        suggestions = _profession_suggestions(db, lowered)
        if suggestions:
            reviews.append(
                _topic_review(
                    "可能影响结论的相关法律",
                    "professional_license_chapter_mapping",
                    "专业许可不能只引用 Title 24；应按具体职业定位到对应 Chapter。",
                    suggestions,
                    coverage={"not_covered": "professional board regulations / Delaware Administrative Code"},
                )
            )

    if _contains_any(lowered, GOOD_SAMARITAN_TERMS):
        reviews.append(
            _topic_review(
                "可能影响结论的相关法律",
                "good_samaritan_immunity_mapping",
                "Good Samaritan / emergency immunity 不是单一固定关键词；应按具体场景核对志愿医疗、过量/紧急医疗、safe haven 等 Delaware immunity 条文。",
                _authority_suggestions(
                    db,
                    [
                        ("10 Del. C. § 8135", "civil liability limitation for certain volunteers。"),
                        ("16 Del. C. § 4769", "criminal immunity for overdose or life-threatening medical emergency reports。"),
                        ("16 Del. C. § 908", "safe haven related immunity。"),
                        ("16 Del. C. § 2515A", "health-care institution/practitioner/provider immunity in covered context。"),
                    ],
                ),
            )
        )

    return reviews


def _title_context_suggestions(db: DelawareLawDatabase, title_number: int, context: str) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    if title_number == 24 and _contains_any(context, PROFESSION_TERMS | TELEHEALTH_TERMS):
        suggestions.extend(_profession_suggestions(db, context))
        if _contains_any(context, TELEHEALTH_TERMS | HEALTH_CARE_TERMS):
            suggestions.extend(
                _authority_suggestions(
                    db,
                    [
                        ("24 Del. C. ch. 60", "general telehealth and telemedicine framework。"),
                        ("24 Del. C. § 6002", "authorization to practice by telehealth and telemedicine。"),
                        ("24 Del. C. § 6004", "practice requirements。"),
                    ],
                )
            )
    if title_number == 16 and _contains_any(context, {"health", "public health", "controlled substances", "food safety", "medical records"}):
        suggestions.extend(
            _authority_suggestions(
                db,
                [
                    ("16 Del. C. § 4769", "controlled substances / overdose emergency immunity may be relevant。"),
                    ("16 Del. C. § 2515A", "health-care immunity context may be relevant。"),
                ],
            )
        )
    if title_number == 4 and _contains_any(context, {"alcohol", "cannabis", "marijuana"}):
        suggestions.extend(
            _authority_suggestions(
                db,
                [
                    ("4 Del. C. ch. 1", "alcoholic liquors definitions and general provisions。"),
                    ("4 Del. C. ch. 13", "Delaware Marijuana Control Act。"),
                ],
            )
        )
    return _dedupe_suggestions(suggestions)


def _looks_like_general_telehealth_context(lowered_text: str) -> bool:
    if _contains_any(lowered_text, {"all health", "all medical", "all provider", "all providers", "generally", "universal", "healthcare", "health-care", "medical", "physician", "nursing", "pharmacy"}):
        return True
    return not _contains_any(lowered_text, {"social work", "social worker", "licensed clinical social work", "behavioral"})


def _profession_suggestions(db: DelawareLawDatabase, lowered_context: str) -> list[dict[str, Any]]:
    citations: list[tuple[str, str]] = []
    for terms, citation, reason in PROFESSION_CHAPTERS:
        if _contains_any(lowered_context, terms):
            citations.append((citation, reason))
    return _dedupe_suggestions(_authority_suggestions(db, citations))


def _build_trust_estates_topic_reviews(db: DelawareLawDatabase, text: str) -> list[dict[str, Any]]:
    """Topic reviews for Trust & Estates (Title 12), Guardianship (Title 13), Health (Title 16), and federal tax/ERISA boundaries."""
    lowered = text.lower()
    reviews: list[dict[str, Any]] = []

    # Wrong-title: Title 25 (Property) for wills/probate → should be Title 12
    if re.search(r"\bTitle\s+25\b|25\s+Del\.?\s*C\.?", text, re.IGNORECASE) and _contains_any(lowered, WRONG_TITLE_WILLS_TERMS):
        reviews.append(_topic_review(
            "错误引用", "wrong_title_25_not_12_for_wills",
            "遗嘱认证 (wills/probate) 应属于 Title 12 (Decedents' Estates and Fiduciary Relations)，而非 Title 25 (Property)。",
            _authority_suggestions(db, [
                ("12 Del. C. ch. 2", "Wills and probate provisions。"),
                ("12 Del. C. § 202", "Requisites and execution of will。"),
            ]),
        ))

    # Wrong-title: Title 12 (Decedents' Estates) for health-care directives → should be Title 16
    if re.search(r"\bTitle\s+12\b|12\s+Del\.?\s*C\.?", text, re.IGNORECASE) and _contains_any(lowered, WRONG_TITLE_HEALTHCARE_TERMS):
        reviews.append(_topic_review(
            "错误引用", "wrong_title_12_not_16_for_healthcare",
            "预先医疗指示 (advance health-care directives) 应属于 Title 16 (Health and Safety)，而非 Title 12 (Decedents' Estates)。",
            _authority_suggestions(db, [
                ("16 Del. C. ch. 25", "Advance Health-Care Directive Act。"),
                ("16 Del. C. § 2501", "Short title — Advance Health-Care Directives。"),
            ]),
        ))

    # Wrong-title: Title 12 for minor guardianship → should be Title 13
    if re.search(r"\bTitle\s+12\b|12\s+Del\.?\s*C\.?", text, re.IGNORECASE) and _contains_any(lowered, WRONG_TITLE_GUARDIANSHIP_TERMS):
        reviews.append(_topic_review(
            "错误引用", "wrong_title_12_not_13_for_minor_guardianship",
            "未成年人监护 (minor guardianship) 应属于 Title 13 (Domestic Relations)，而非 Title 12 (Decedents' Estates)。",
            _authority_suggestions(db, [
                ("13 Del. C. ch. 23", "Guardianship of minors。"),
            ]),
        ))

    # Wrong-title: Title 25 for anatomical gifts → should be Title 16
    if re.search(r"\bTitle\s+25\b|25\s+Del\.?\s*C\.?", text, re.IGNORECASE) and _contains_any(lowered, WRONG_TITLE_ANATOMICAL_TERMS):
        reviews.append(_topic_review(
            "错误引用", "wrong_title_25_not_16_for_anatomical_gifts",
            "遗体器官捐赠 (anatomical gifts) 应属于 Title 16 (Health and Safety) Chapter 27，而非 Title 25 (Property)。",
            _authority_suggestions(db, [
                ("16 Del. C. ch. 27", "Anatomical Gifts and Studies。"),
                ("16 Del. C. § 2712", "Making, amending, revoking, and refusing anatomical gift。"),
            ]),
        ))

    # Federal tax boundary
    if _contains_any(lowered, FEDERAL_TAX_ERISA_TERMS):
        reviews.append(_topic_review(
            "需要查外部材料", "federal_tax_erisa_boundary",
            "文本涉及联邦遗产税/赠与税/GST 税/所得税或 ERISA 事项；Delaware 信托法不能单独决定这些联邦法律问题，需查阅 federal tax law 或 ERISA 规则。",
            [],
            coverage={"not_covered": "federal estate/gift/GST/income tax; ERISA; Internal Revenue Code"},
        ))

    # Probate court rules / Register of Wills boundary
    probate_court_signals = {"register of wills", "probate form", "court rule", "chancery rule",
                             "court of chancery", "probate court", "orphans' court",
                             "fiduciary accounting", "letters testamentary"}
    if _contains_any(lowered, probate_court_signals) and _contains_any(lowered, TRUST_ESTATES_TERMS):
        reviews.append(_topic_review(
            "需要查外部材料", "probate_court_rules_boundary",
            "遗嘱认证程序 (probate) 通常涉及 Register of Wills、Chancery Court rules、probate forms 等非法典材料；当前数据包不覆盖这些内容。",
            [],
            coverage={"not_covered": "probate court rules; Register of Wills practice; probate forms"},
        ))

    return reviews


def _build_ucc_topic_reviews(db: DelawareLawDatabase, text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    reviews: list[dict[str, Any]] = []

    for match in UCC_ARTICLE_RE.finditer(text):
        article = match.group("article").upper()
        context = _context_window(text, match.start(), match.end()).lower()
        if article == "2" and _contains_any(context, UCC_SECURED_TRANSACTION_TERMS):
            reviews.append(
                _topic_review(
                    "错误引用",
                    "ucc_article_2_perfection_mismatch",
                    "主题可能不匹配：UCC Article 2 主要是货物买卖；security interest 的 perfection/priority/control 应先查 UCC Article 9。",
                    _ucc_article_suggestions(db, "9", context),
                )
            )
        elif article == "9" and _contains_any(context, UCC_SECURED_TRANSACTION_TERMS):
            reviews.append(
                _topic_review(
                    "已验证引用",
                    "ucc_article_9_security_interest_context",
                    "识别到 UCC Article 9 语境：security interest、perfection、priority、control 等问题通常应从 Article 9 定位具体条文。",
                    _ucc_article_suggestions(db, "9", context),
                )
            )

    if _contains_any(lowered, WARRANTY_TERMS):
        reviews.append(
            _topic_review(
                "已验证引用",
                "ucc_warranty_disclaimer_mapping",
                "识别到 warranty disclaimer / merchantability 语境；货物买卖中的 warranty 排除或修改应优先查 UCC Article 2 的具体条文。",
                _authority_suggestions(
                    db,
                    [
                        ("6 Del. C. § 2-316", "Exclusion or modification of warranties。"),
                        ("6 Del. C. § 2-314", "Implied warranty; merchantability; usage of trade。"),
                        ("6 Del. C. § 2-315", "Implied warranty; fitness for particular purpose。"),
                    ],
                ),
            )
        )

    return reviews


def _build_implicit_references(db: DelawareLawDatabase, text: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for match in UCC_ARTICLE_RE.finditer(text):
        article = match.group("article").upper()
        context = _context_window(text, match.start(), match.end())
        if not _looks_like_ucc_article_reference(context):
            continue
        label = UCC_ARTICLE_LABELS.get(article, "UCC Article")
        warnings: list[str] = []
        if article == "2" and _contains_any(context.lower(), UCC_SECURED_TRANSACTION_TERMS):
            warnings.append("主题可能不匹配：Article 2 是货物买卖；担保权益完善/优先权通常应查 Article 9。")
        references.append(
            {
                "input": match.group(0),
                "article": article,
                "status": "recognized",
                "message": f"识别到 UCC Article {article}：{label}。",
                "query": f"UCC Article {article} {label}",
                "warnings": warnings,
                "suggestions": _ucc_article_suggestions(db, article, context.lower()),
            }
        )
    return references


def _looks_like_ucc_article_reference(context: str) -> bool:
    return _contains_any(context.lower(), UCC_CONTEXT_TERMS)


def _ucc_article_suggestions(db: DelawareLawDatabase, article: str, context: str) -> list[dict[str, Any]]:
    if article == "2":
        citations = [("6 Del. C. § 2-102", "Article 2 scope and sales baseline。")]
        if _contains_any(context, WARRANTY_TERMS):
            citations.extend(
                [
                    ("6 Del. C. § 2-316", "warranty exclusion or modification。"),
                    ("6 Del. C. § 2-314", "implied warranty of merchantability。"),
                    ("6 Del. C. § 2-315", "implied warranty of fitness。"),
                ]
            )
        return _authority_suggestions(db, citations)
    if article == "2A":
        return _authority_suggestions(db, [("6 Del. C. § 2A-101", "Article 2A short title and lease baseline。")])
    if article == "7":
        return _authority_suggestions(db, [("6 Del. C. § 7-101", "Article 7 short title and documents of title baseline。")])
    if article == "8":
        return _authority_suggestions(db, [("6 Del. C. § 8-101", "Article 8 short title and investment securities baseline。")])
    if article == "9":
        return _authority_suggestions(
            db,
            [
                ("6 Del. C. § 9-102", "Article 9 definitions。"),
                ("6 Del. C. § 9-301", "law governing perfection and priority。"),
                ("6 Del. C. § 9-308", "when security interest is perfected。"),
                ("6 Del. C. § 9-310", "when filing is required to perfect。"),
                ("6 Del. C. § 9-314", "perfection by control。"),
                ("6 Del. C. § 9-501", "filing office。"),
            ],
        )
    return []


def _collect_database_misses(
    citation_results: list[dict[str, Any]],
    chapter_results: list[dict[str, Any]],
    broad_title_results: list[dict[str, Any]],
    court_rule_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    misses: list[dict[str, Any]] = []
    for item in citation_results:
        if item.get("status") == "not_found":
            misses.append(_database_miss("citation", item))
    for item in chapter_results:
        if item.get("status") == "not_found":
            misses.append(_database_miss("chapter", item))
    for item in broad_title_results:
        if item.get("status") == "not_found":
            misses.append(_database_miss("title", item))
    for item in court_rule_results:
        if item.get("status") == "not_found":
            misses.append(_database_miss("court_rule", item))
    return misses


def _database_miss(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "input": item.get("input"),
        "message": item.get("message"),
        "warnings": item.get("warnings", []),
        "suggestions": item.get("suggestions", []),
    }


def _topic_review(
    category: str,
    code: str,
    message: str,
    suggestions: list[dict[str, Any]],
    coverage: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "code": code,
        "message": message,
        "suggestions": suggestions,
        "coverage": coverage or {},
    }


def _authority_suggestions(
    db: DelawareLawDatabase,
    citations: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for citation, reason in citations:
        chapter_query, chapter_rows = db.lookup_chapter(citation)
        if chapter_rows:
            row = chapter_rows[0]
            suggestions.append(
                {
                    "citation": row["citation"],
                    "heading": row["heading"],
                    "reason": reason,
                    "source_url": row["source_url"],
                }
            )
            continue

        _, rows = db.lookup(citation)
        if rows:
            row = rows[0]
            suggestions.append(
                {
                    "citation": row["citation"],
                    "heading": row["heading"],
                    "reason": reason,
                    "source_url": row["source_url"],
                }
            )
        else:
            suggestions.append({"citation": citation, "heading": "", "reason": reason, "source_url": ""})
    return suggestions


def _dedupe_suggestions(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for suggestion in suggestions:
        key = str(suggestion.get("citation", "")).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(suggestion)
    return unique


def _context_window(text: str, start: int, end: int, radius: int = 220) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _infer_title_from_context(citation: ExtractedCitation) -> int | None:
    if re.search(r"\b\d+\s+Del\.?\s*C\.?", citation.text, re.IGNORECASE):
        return None
    before = citation.context[: max(0, citation.context.find(citation.text))]
    title_matches = list(re.finditer(r"\bTitle\s+(\d+)\b", before, re.IGNORECASE))
    if not title_matches:
        title_matches = list(re.finditer(r"\b(\d+)\s+Del\.?\s*C\.?", before, re.IGNORECASE))
    if not title_matches:
        return None
    return int(title_matches[-1].group(1))


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _is_part_of_non_delaware_citation(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24) : start]
    return bool(re.search(r"(U\.S\.C\.?|C\.F\.R\.?)\s*$", prefix, re.IGNORECASE))


def _is_ordinary_document_section(value: str) -> bool:
    if not value.lower().startswith("section "):
        return False
    if re.search(r"\b(?:Delaware|DRULPA|DGCL|LLC\s+Act|Code|Act)\b", value, re.IGNORECASE):
        return False
    match = re.search(r"Section\s+([A-Za-z0-9][A-Za-z0-9.\-]*)", value, re.IGNORECASE)
    if not match:
        return True
    section_number = match.group(1).rstrip(".")
    return "-" not in section_number and not re.search(r"[A-Za-z]$", section_number)


def _subsection_exists(section_text: str, subsection: str) -> bool:
    if subsection in section_text or subsection.replace("(", "").replace(")", "") in section_text:
        return True
    parts = re.findall(r"\([A-Za-z0-9]+\)", subsection)
    return bool(parts) and all(part in section_text for part in parts)


def _apply_topic_rules(
    db: DelawareLawDatabase,
    section_number: str,
    subsection: str | None,
    context: str,
    result: dict[str, Any],
    title_number: int | None = None,
) -> None:
    context_lower = context.lower()
    if section_number == "17-406" and _contains_any(context_lower, RELIANCE_TERMS):
        result["warnings"].append(
            "主题可能不匹配：§ 17-406 是 GP 违反合伙协议的救济条款，不是专业信赖条款。"
        )
        suggestion = _first_lookup(db, "6 Del. C. § 17-407")
        if suggestion:
            result["suggestions"].append(
                {
                    "citation": suggestion["citation"],
                    "heading": suggestion["heading"],
                    "reason": "§ 17-407 涉及对 records、information、opinions、reports 的 good-faith reliance。",
                }
            )

    if section_number == "17-607" and _contains_any(context_lower, SOLVENCY_TERMS):
        if subsection == "(b)":
            result["warnings"].append(
                "主题可能不匹配：§ 17-607(b) 是有限合伙人收到违法分配后的知情返还责任，不是资产负债比率测试。"
            )
            result["suggestions"].append(
                {
                    "citation": "6 Del. C. § 17-607(a)",
                    "heading": "Limitations on distribution",
                    "reason": "分配后的资产/负债限制在 § 17-607(a)。",
                }
            )
        else:
            result["warnings"].append(
                "主题可能不匹配：§ 17-607 在资产/负债测试语境中引用时，应明确 § 17-607(a)。§ 17-607(b) 是关于有限合伙人返还责任的不同条文。"
            )

    if section_number == "3920" and _contains_any(context_lower, TELEHEALTH_TERMS) and _looks_like_general_telehealth_context(context_lower):
        result["warnings"].append(
            "主题可能不匹配：§ 3920 是 Social Work 章节下的 telehealth 条文，不能泛化为所有医疗职业的统一 telehealth 规则。"
        )
        for suggestion in _authority_suggestions(
            db,
            [
                ("24 Del. C. § 6002", "general health-care provider telehealth authorization。"),
                ("24 Del. C. § 6004", "general telehealth practice requirements。"),
            ],
        ):
            result["suggestions"].append(suggestion)

    # § 17-1101 is LP (DRULPA), not LLC
    if section_number == "17-1101" and _contains_any(context_lower, {"llc", "limited liability company", "dllca", "member", "manager", "fiduciary waiver"}):
        result["warnings"].append(
            "主题可能不匹配：§ 17-1101 是 DRULPA（LP）条文，不适用于 LLC。LLC fiduciary waiver 应查 Title 6 Chapter 18（DLLCA）。"
        )
        suggestion = _first_lookup(db, "6 Del. C. § 18-1101")
        if suggestion:
            result["suggestions"].append({
                "citation": suggestion["citation"],
                "heading": suggestion["heading"],
                "reason": "LLC Act 的 construction and application 条文。",
            })

    # UCC Article 9 sections in warranty context
    if re.match(r"9-\d+", section_number) and _contains_any(context_lower, WARRANTY_TERMS):
        result["warnings"].append(
            "主题可能不匹配：Article 9 涉及 secured transactions，不涉及 warranty disclaimer。Warranty disclaimer 应查 Article 2（如 § 2-316）。"
        )
        result["suggestions"].append({
            "citation": "6 Del. C. § 2-316",
            "heading": "Exclusion or modification of warranties",
            "reason": "UCC Article 2 warranty disclaimer 条文。",
        })

    # UCC Article 2 sections in perfection/secured transaction context
    if re.match(r"2-\d+", section_number) and _contains_any(context_lower, UCC_SECURED_TRANSACTION_TERMS):
        result["warnings"].append(
            "主题可能不匹配：Article 2 涉及 sale of goods，不涉及 security interest/perfection。Perfection 应查 Article 9。"
        )
        result["suggestions"].append({
            "citation": "6 Del. C. § 9-310",
            "heading": "When filing required to perfect security interest",
            "reason": "UCC Article 9 perfection 条文。",
        })

    # § 2-714 is buyer's damages for accepted goods, not exclusion of consequential damages
    if section_number == "2-714" and _contains_any(context_lower, {"consequential", "exclusion", "exclude", "limitation of damages", "limitation of liability"}):
        result["warnings"].append(
            "主题可能不匹配：§ 2-714 是买方就已接受货物的损害赔偿计算条文，不是排除间接损害（consequential damages）的规定。排除间接损害应查 § 2-719(3)。"
        )
        result["suggestions"].append({
            "citation": "6 Del. C. § 2-719",
            "heading": "Contractual modification or limitation of remedy",
            "reason": "§ 2-719(3) 允许合同限制或排除间接损害赔偿。",
        })

    # ── Registry-backed cross-title traps ──────────────────────────────
    full_section = f"{section_number}"
    if subsection:
        full_section += subsection
    for trap in CROSS_TITLE_NUMBER_TRAPS:
        trap_section = trap.get("wrong_section")
        trap_subsection = trap.get("subsection")
        trap_title = trap.get("wrong_title")
        trap_terms = trap.get("context_terms", set())

        if trap_section is None:
            continue  # Chapter/title-level trap, not section-level

        # Match section number
        if trap_section != section_number:
            continue
        # Match subsection if specified
        if trap_subsection and trap_subsection != subsection:
            continue
        # Check title if specified in trap: only fire when the cited title matches the wrong title
        # If no title context available (Section X of the Delaware Code format), skip — ambiguous
        if trap_title is not None:
            if title_number is None:
                continue  # Title context lost (format variant); can't confirm wrong title
            if title_number != trap_title:
                continue  # Trap targets specific title; cited title is different → skip
        # Match context terms
        if not _contains_any(context_lower, trap_terms):
            continue

        result["warnings"].append(f"主题可能不匹配：{trap['reason']}")
        for cit, heading in trap.get("suggestions", []):
            suggestion = _first_lookup(db, cit)
            if suggestion:
                result["suggestions"].append({
                    "citation": suggestion["citation"],
                    "heading": suggestion["heading"],
                    "reason": heading.rstrip("。") + "。",
                })
            else:
                result["suggestions"].append({
                    "citation": cit,
                    "heading": heading,
                    "reason": trap["reason"],
                })


def _contains_any(value: str, terms: set[str]) -> bool:
    return any(term in value for term in terms)


def _first_lookup(db: DelawareLawDatabase, citation: str):
    _, rows = db.lookup(citation)
    return rows[0] if rows else None
