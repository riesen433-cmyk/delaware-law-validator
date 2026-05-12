from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from .config import DEFAULT_DB_PATH
from .parser import normalize_citation


@dataclass(frozen=True)
class CitationQuery:
    raw: str
    title_number: int | None
    section_number: str | None
    subsection: str | None
    material_type: str | None = None


@dataclass(frozen=True)
class ChapterQuery:
    raw: str
    title_number: int | None
    chapter_number: str | None


@dataclass(frozen=True)
class CourtRuleQuery:
    raw: str
    source_doc_id: str | None
    rule_number: str | None
    subsection: str | None


class DelawareLawDatabase:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def metadata(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def lookup(self, citation: str) -> tuple[CitationQuery, list[sqlite3.Row]]:
        query = parse_citation(citation)
        if query.material_type == "constitution" and query.section_number:
            rows = self.conn.execute(
                """
                SELECT * FROM materials
                WHERE material_type = 'constitution' AND section_number = ?
                ORDER BY citation
                """,
                (query.section_number,),
            ).fetchall()
            return query, rows

        if query.title_number is not None and query.section_number:
            rows = self.conn.execute(
                """
                SELECT * FROM materials
                WHERE title_number = ? AND section_number = ?
                ORDER BY citation
                """,
                (query.title_number, query.section_number),
            ).fetchall()
            return query, rows

        if query.section_number:
            rows = self.conn.execute(
                """
                SELECT * FROM materials
                WHERE section_number = ?
                ORDER BY citation
                """,
                (query.section_number,),
            ).fetchall()
            return query, rows

        normalized = normalize_citation(citation)
        rows = self.conn.execute(
            """
            SELECT * FROM materials
            WHERE normalized_citation = ?
            ORDER BY citation
            """,
            (normalized,),
        ).fetchall()
        return query, rows

    def lookup_chapter(self, value: str) -> tuple[ChapterQuery, list[sqlite3.Row]]:
        query = parse_chapter_reference(value)
        if query.title_number is not None and query.chapter_number:
            rows = self.conn.execute(
                """
                SELECT * FROM chapters
                WHERE title_number = ? AND chapter_number = ?
                ORDER BY title_number, chapter_number
                """,
                (query.title_number, query.chapter_number),
            ).fetchall()
            return query, rows

        if query.chapter_number:
            rows = self.conn.execute(
                """
                SELECT * FROM chapters
                WHERE chapter_number = ?
                ORDER BY title_number, chapter_number
                """,
                (query.chapter_number,),
            ).fetchall()
            return query, rows

        return query, []

    def lookup_rule(self, value: str) -> tuple[CourtRuleQuery, list[sqlite3.Row]]:
        query = parse_court_rule_reference(value)
        if query.rule_number and query.source_doc_id:
            rows = self.conn.execute(
                """
                SELECT * FROM materials
                WHERE material_type = 'court_rule'
                  AND source_doc_id = ?
                  AND LOWER(section_number) = LOWER(?)
                ORDER BY citation
                """,
                (query.source_doc_id, query.rule_number),
            ).fetchall()
            return query, rows

        if query.rule_number:
            rows = self.conn.execute(
                """
                SELECT * FROM materials
                WHERE material_type = 'court_rule'
                  AND LOWER(section_number) = LOWER(?)
                ORDER BY citation
                """,
                (query.rule_number,),
            ).fetchall()
            return query, rows

        normalized = normalize_citation(value)
        rows = self.conn.execute(
            """
            SELECT * FROM materials
            WHERE material_type = 'court_rule'
              AND normalized_citation = ?
            ORDER BY citation
            """,
            (normalized,),
        ).fetchall()
        return query, rows

    def search(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        chapter_query, chapter_rows = self.lookup_chapter(query)
        if chapter_query.chapter_number and len(chapter_rows) == 1:
            chapter = chapter_rows[0]
            rows = self.conn.execute(
                """
                SELECT * FROM materials
                WHERE source_doc_id = ? AND chapter LIKE ?
                ORDER BY start_line
                LIMIT ?
                """,
                (chapter["source_doc_id"], f"Chapter {chapter['chapter_number']}:%", limit),
            ).fetchall()
            if rows:
                return rows

        mapped_rows = self._mapped_search(query, limit)
        if len(mapped_rows) >= limit:
            return mapped_rows[:limit]

        terms = _search_terms(query)
        if not terms:
            return mapped_rows
        fts_query = " ".join(terms)
        remaining = max(limit - len(mapped_rows), 1)
        try:
            rows = self.conn.execute(
                """
                SELECT m.*, bm25(materials_fts) AS rank
                FROM materials_fts
                JOIN materials m ON materials_fts.rowid = m.rowid
                WHERE materials_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, remaining),
            ).fetchall()
            if rows:
                return _dedupe_rows([*mapped_rows, *rows])[:limit]
        except sqlite3.Error:
            pass
        return _dedupe_rows([*mapped_rows, *self._like_search(terms, remaining)])[:limit]

    def _mapped_search(self, query: str, limit: int) -> list[sqlite3.Row]:
        citations = _concept_citations_for_search(query)
        rows: list[sqlite3.Row] = []
        for citation in citations:
            _, matches = self.lookup(citation)
            if not matches:
                _, matches = self.lookup_rule(citation)
            rows.extend(matches[:1])
            if len(rows) >= limit:
                break
        return _dedupe_rows(rows)

    def _like_search(self, terms: list[str], limit: int) -> list[sqlite3.Row]:
        where = " AND ".join(["(LOWER(heading) LIKE ? OR LOWER(text) LIKE ?)"] * len(terms))
        params: list[str] = []
        for term in terms:
            like = f"%{term.lower()}%"
            params.extend([like, like])
        return self.conn.execute(
            f"""
            SELECT * FROM materials
            WHERE {where}
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

    def get_title(self, title_number: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM source_documents
            WHERE title_number = ?
            """,
            (title_number,),
        ).fetchone()

    def materials_for_semantic_index(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT rowid, citation, heading, text, material_type, source_file, source_url,
                   data_version, title_number, section_number, start_line
            FROM materials
            WHERE is_current = 1
            ORDER BY title_number, citation, rowid
        """
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return self.conn.execute(sql, params).fetchall()

    def materials_by_rowids(self, rowids: list[int]) -> dict[int, sqlite3.Row]:
        if not rowids:
            return {}
        placeholders = ",".join(["?"] * len(rowids))
        rows = self.conn.execute(
            f"""
            SELECT rowid, citation, heading, text, material_type, source_file, source_url,
                   data_version, title_number, section_number, start_line
            FROM materials
            WHERE rowid IN ({placeholders})
            """,
            tuple(rowids),
        ).fetchall()
        return {int(row["rowid"]): row for row in rows}


def parse_citation(value: str) -> CitationQuery:
    raw = value.strip()
    title_number: int | None = None
    section_number: str | None = None
    subsection: str | None = None
    material_type: str | None = None

    code_match = re.search(
        r"\b(?P<title>\d+)\s+Del\.?\s*C\.?\s*§+\s*(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*)(?P<subsection>(?:\([A-Za-z0-9]+\))*)",
        raw,
        re.IGNORECASE,
    )
    if code_match:
        title_number = int(code_match.group("title"))
        section_number = _clean_section_number(code_match.group("section"))
        subsection = code_match.group("subsection") or None
        return CitationQuery(raw, title_number, section_number, subsection, "statute")

    const_match = re.search(
        r"Del\.?\s*Const\.?.*?§+\s*(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*)(?P<subsection>(?:\([A-Za-z0-9]+\))*)",
        raw,
        re.IGNORECASE,
    )
    if const_match:
        section_number = _clean_section_number(const_match.group("section"))
        subsection = const_match.group("subsection") or None
        return CitationQuery(raw, None, section_number, subsection, "constitution")

    section_match = re.search(
        r"(?:§+\s*|Section\s+)(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*)(?P<subsection>(?:\([A-Za-z0-9]+\))*)",
        raw,
        re.IGNORECASE,
    )
    if section_match:
        section_number = _clean_section_number(section_match.group("section"))
        subsection = section_match.group("subsection") or None
        return CitationQuery(raw, None, section_number, subsection, None)

    return CitationQuery(raw, None, None, None, None)


def parse_chapter_reference(value: str) -> ChapterQuery:
    raw = value.strip()

    title_chapter = re.search(
        r"\bTitle\s+(?P<title>\d+)\s*,?\s*(?:Chapter|Ch\.?)\s*(?P<chapter>[0-9][A-Za-z0-9.-]*)\b",
        raw,
        re.IGNORECASE,
    )
    if title_chapter:
        return ChapterQuery(
            raw,
            int(title_chapter.group("title")),
            _clean_chapter_number(title_chapter.group("chapter")),
        )

    chapter_of_title = re.search(
        r"\b(?:Chapter|Ch\.?)\s*(?P<chapter>[0-9][A-Za-z0-9.-]*)\s+of\s+Title\s+(?P<title>\d+)\b",
        raw,
        re.IGNORECASE,
    )
    if chapter_of_title:
        return ChapterQuery(
            raw,
            int(chapter_of_title.group("title")),
            _clean_chapter_number(chapter_of_title.group("chapter")),
        )

    code_chapter = re.search(
        r"\b(?P<title>\d+)\s+Del\.?\s*C\.?\s*(?:ch\.?|chapter)\s+(?P<chapter>[0-9][A-Za-z0-9.-]*)\b",
        raw,
        re.IGNORECASE,
    )
    if code_chapter:
        return ChapterQuery(
            raw,
            int(code_chapter.group("title")),
            _clean_chapter_number(code_chapter.group("chapter")),
        )

    chapter_only = re.search(r"\b(?:Chapter|Ch\.?)\s*(?P<chapter>[0-9][A-Za-z0-9.-]*)\b", raw, re.IGNORECASE)
    if chapter_only:
        return ChapterQuery(raw, None, _clean_chapter_number(chapter_only.group("chapter")))

    return ChapterQuery(raw, None, None)


def parse_court_rule_reference(value: str) -> CourtRuleQuery:
    raw = value.strip()
    compact = re.sub(r"\s+", " ", raw)
    patterns: list[tuple[str, str]] = [
        ("court-rule-chancery", r"(?:Del\.?\s*Ch\.?\s*Ct\.?\s*R\.?|Court\s+of\s+Chancery\s+Rule|Chancery\s+Rule)"),
        ("court-rule-superior-civil", r"(?:Del\.?\s*Super\.?\s*Ct\.?\s*Civ\.?\s*R\.?|Superior\s+Court\s+Civil\s+Rule)"),
        ("court-rule-superior-special-2017-1", r"(?:Del\.?\s*Super\.?\s*Ct\.?\s*Spec\.?\s*R\.?|Special\s+Rule(?:\s+of\s+Procedure)?)"),
        ("court-rule-supreme", r"(?:Del\.?\s*Supr\.?\s*Ct\.?\s*R\.?|Supreme\s+Court\s+Rule)"),
        ("court-rule-family-civil", r"(?:Del\.?\s*Fam\.?\s*Ct\.?\s*Civ\.?\s*R\.?|Family\s+Court\s+Civil\s+Rule)"),
        ("court-rule-common-pleas-civil", r"(?:Del\.?\s*Ct\.?\s*Com\.?\s*Pl\.?\s*Civ\.?\s*R\.?|Court\s+of\s+Common\s+Pleas\s+Civil\s+Rule)"),
        ("court-rule-evidence", r"(?:D\.?\s*R\.?\s*E\.?|Delaware\s+(?:Uniform\s+)?Rules?\s+of\s+Evidence|Delaware\s+Rule\s+of\s+Evidence|Rule\s+of\s+Evidence)"),
        ("court-rule-rapid-arbitration", r"(?:Del\.?\s*Rapid\s+Arb\.?\s*R\.?|Delaware\s+Rapid\s+Arbitration\s+Rule|Rapid\s+Arbitration\s+Rule)"),
        ("court-rule-court-on-judiciary", r"(?:Del\.?\s*Ct\.?\s*Jud\.?\s*R\.?|Court\s+on\s+the\s+Judiciary\s+Rule)"),
    ]
    for source_doc_id, prefix in patterns:
        match = re.search(
            prefix + r"\s*(?:No\.?\s*)?(?P<rule>[0-9][0-9A-Za-z.-]*)(?P<subsection>(?:\([A-Za-z0-9]+\))*)",
            compact,
            re.IGNORECASE,
        )
        if match:
            return CourtRuleQuery(
                raw,
                source_doc_id,
                _clean_rule_number(match.group("rule")),
                match.group("subsection") or None,
            )

    guideline = re.search(
        r"(?:Self-Represented\s+Litigants?\s+Guideline|Judicial\s+Guideline)\s*(?P<rule>[0-9]+(?:\.[0-9]+)?)",
        compact,
        re.IGNORECASE,
    )
    if guideline:
        return CourtRuleQuery(raw, "court-guideline-self-represented", _clean_rule_number(guideline.group("rule")), None)

    return CourtRuleQuery(raw, None, None, None)


def _clean_section_number(value: str) -> str:
    return value.strip().rstrip(".")


def _clean_chapter_number(value: str) -> str:
    return value.strip().rstrip(".")


def _clean_rule_number(value: str) -> str:
    return value.strip().rstrip(".:")


def _search_terms(value: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{1,}", value.lower())
    stop = {"the", "and", "for", "with", "from", "this", "that", "delaware"}
    return [term for term in terms if term not in stop][:8]


def _concept_citations_for_search(query: str) -> list[str]:
    lowered = query.lower()
    citations: list[str] = []

    if _contains_any(lowered, {"warranty disclaimer", "disclaimer", "merchantability", "implied warranty"}):
        citations.extend(["6 Del. C. § 2-316", "6 Del. C. § 2-314", "6 Del. C. § 2-315"])

    if _contains_any(lowered, {"perfection", "perfected", "security interest", "financing statement", "collateral"}):
        citations.extend(
            [
                "6 Del. C. § 9-308",
                "6 Del. C. § 9-301",
                "6 Del. C. § 9-310",
                "6 Del. C. § 9-314",
                "6 Del. C. § 9-501",
                "6 Del. C. § 9-102",
            ]
        )

    if _contains_any(lowered, {"filing office", "file financing statement", "financing statement filing"}):
        citations.extend(["6 Del. C. § 9-501", "6 Del. C. § 9-515"])

    if _contains_any(lowered, {"deposit account control", "control of deposit account"}):
        citations.extend(["6 Del. C. § 9-104", "6 Del. C. § 9-327"])

    if _contains_any(lowered, {"investment property control", "control of investment property"}):
        citations.extend(["6 Del. C. § 9-106", "6 Del. C. § 9-328"])

    if _contains_any(lowered, {"good samaritan", "emergency care immunity", "volunteer medical immunity", "overdose immunity"}):
        citations.extend(["10 Del. C. § 8135", "16 Del. C. § 4769", "16 Del. C. § 908", "16 Del. C. § 2515A"])

    if _contains_any(lowered, {"telehealth", "telemedicine", "remote health", "virtual care"}):
        citations.extend(["24 Del. C. § 6002", "24 Del. C. § 6004", "24 Del. C. § 6001"])

    if _contains_any(lowered, {"social work", "social worker"}):
        citations.extend(["24 Del. C. § 3903", "24 Del. C. § 3920"])

    if _contains_any(lowered, {"failure to state a claim", "12(b)(6)", "motion to dismiss"}):
        if "chancery" in lowered:
            citations.append("Del. Ch. Ct. R. 12")
        if "superior" in lowered:
            citations.append("Del. Super. Ct. Civ. R. 12")
        if "family" in lowered:
            citations.append("Del. Fam. Ct. Civ. R. 12")
        if "common pleas" in lowered:
            citations.append("Del. Ct. Com. Pl. Civ. R. 12")

    if _contains_any(lowered, {"unfair prejudice", "probative value", "relevant evidence"}):
        citations.append("D.R.E. 403")

    return _dedupe_strings(citations)


def _contains_any(value: str, terms: set[str]) -> bool:
    return any(term in value for term in terms)


def _dedupe_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    seen: set[int] = set()
    unique: list[sqlite3.Row] = []
    for row in rows:
        rowid = int(row["rowid"])
        if rowid in seen:
            continue
        seen.add(rowid)
        unique.append(row)
    return unique


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique
