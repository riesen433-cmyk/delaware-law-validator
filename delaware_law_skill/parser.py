from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable


SECTION_RE = re.compile(r"^§\s+(?P<section>[A-Za-z0-9][A-Za-z0-9.\-]*)(?:\.)?\s*(?P<title>.*)$")
TITLE_RE = re.compile(r"^Title\s+(?P<number>\d+)(?:\s*-\s*(?P<name>.+))?$")
RULE_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?Rule\s+(?P<rule>[0-9][0-9A-Za-z.-]*)(?:[.:])?\s*(?P<title>.*)$",
    re.IGNORECASE,
)
GUIDELINE_HEADING_RE = re.compile(r"^(?:#{1,6}\s*)?(?P<rule>[0-9]+)\.\s+(?P<title>[A-Z].+)$")
CURRENT_THROUGH_RE = re.compile(
    r"includes all acts enacted as of "
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4}), "
    r"up to and including (?P<chapter>.+?)\. DISCLAIMER:",
    re.IGNORECASE,
)
CONSTITUTION_THROUGH_RE = re.compile(r"Through\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})")


COURT_RULE_SOURCES = {
    "amended spec rule 2017-1.complete.clean.final.prw.02.01.2020.md": {
        "doc_id": "court-rule-superior-special-2017-1",
        "title_name": "Superior Court Special Rule of Procedure 2017-1",
        "citation_prefix": "Del. Super. Ct. Spec. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=133058",
        "current_through": "Effective February 1, 2020",
        "single_rule": "2017-1",
    },
    "court-on-the-judiciary-rules-2018mar6.md": {
        "doc_id": "court-rule-court-on-judiciary",
        "title_name": "Court on the Judiciary Rules",
        "citation_prefix": "Del. Ct. Jud. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=160518",
        "current_through": "Current as of March 6, 2018",
    },
    "del_civ_r_govg_cp.md": {
        "doc_id": "court-rule-common-pleas-civil",
        "title_name": "Court of Common Pleas Civil Rules",
        "citation_prefix": "Del. Ct. Com. Pl. Civ. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=176248",
        "current_through": "Current as of January 10, 2023",
    },
    "del_family_ct_civ_r.effective 01 05 2026.md": {
        "doc_id": "court-rule-family-civil",
        "title_name": "Family Court Civil Rules",
        "citation_prefix": "Del. Fam. Ct. Civ. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=39308",
        "current_through": "Current as of January 2026",
    },
    "del_super_ct_civ_02052026.md": {
        "doc_id": "court-rule-superior-civil",
        "title_name": "Superior Court Civil Rules",
        "citation_prefix": "Del. Super. Ct. Civ. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=304488",
        "current_through": "2026 Edition / local file dated February 5, 2026",
    },
    "rapid arbitration rule.md": {
        "doc_id": "court-rule-rapid-arbitration",
        "title_name": "Delaware Rapid Arbitration Rules",
        "citation_prefix": "Del. Rapid Arb. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=160508",
        "current_through": None,
    },
    "rules of evidence.md": {
        "doc_id": "court-rule-evidence",
        "title_name": "Delaware Uniform Rules of Evidence",
        "citation_prefix": "D.R.E.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=39388",
        "current_through": None,
    },
    "sc rules_as amended through 2-2-26.md": {
        "doc_id": "court-rule-supreme",
        "title_name": "Supreme Court Rules",
        "citation_prefix": "Del. Supr. Ct. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=174928",
        "current_through": "Current through February 2, 2026",
    },
    "self-represented.md": {
        "doc_id": "court-guideline-self-represented",
        "title_name": "Delaware Judicial Guidelines for Civil Hearings Involving Self-Represented Litigants",
        "citation_prefix": "Del. Judicial Guidelines for Self-Represented Litigants",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=101568",
        "current_through": "Effective May 11, 2011",
        "guidelines": True,
    },
    "updated full set of chancery rules 11.6.2025.md": {
        "doc_id": "court-rule-chancery",
        "title_name": "Court of Chancery Rules",
        "citation_prefix": "Del. Ch. Ct. R.",
        "source_url": "https://courts.delaware.gov/forms/download.aspx?id=160908",
        "current_through": "Current as of November 6, 2025",
    },
}


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    material_type: str
    title_number: int | None
    title_name: str
    source_url: str
    file_name: str
    file_path: str
    sha256: str
    byte_count: int
    line_count: int
    current_through: str | None


@dataclass(frozen=True)
class LegalMaterial:
    material_id: str
    material_type: str
    jurisdiction: str
    citation: str
    normalized_citation: str
    title_number: int | None
    section_number: str
    heading: str
    text: str
    source_doc_id: str
    source_file: str
    source_url: str
    source_hash: str
    data_version: str
    is_current: int
    article: str | None = None
    chapter: str | None = None
    subchapter: str | None = None
    start_line: int | None = None


@dataclass(frozen=True)
class LegalChapter:
    chapter_id: str
    material_type: str
    jurisdiction: str
    citation: str
    normalized_citation: str
    title_number: int
    chapter_number: str
    heading: str
    source_doc_id: str
    source_file: str
    source_url: str
    source_hash: str
    data_version: str
    start_line: int


def normalize_citation(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.replace("section", "§")
    lowered = lowered.replace("del. c.", "delc")
    lowered = lowered.replace("del.c.", "delc")
    return re.sub(r"[^a-z0-9§().-]+", "", lowered)


def discover_markdown_files(source_dir: Path) -> list[Path]:
    files = sorted(source_dir.glob("*.md"))
    return sorted(files, key=_source_sort_key)


def parse_source_file(path: Path, data_version: str) -> tuple[SourceDocument, list[LegalMaterial], list[LegalChapter]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    file_hash = sha256(raw).hexdigest()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    if path.name == "constitution.md":
        source = _constitution_source(path, text, raw, file_hash, lines)
    else:
        source = _title_source(path, text, raw, file_hash, lines)

    materials = _parse_sections(lines, source, data_version)
    chapters = _parse_chapters(lines, source, data_version)
    return source, materials, chapters


def parse_court_rule_file(path: Path, data_version: str) -> tuple[SourceDocument, list[LegalMaterial], list[LegalChapter]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    file_hash = sha256(raw).hexdigest()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    metadata = COURT_RULE_SOURCES.get(path.name, _court_rule_fallback_metadata(path, lines))
    source = SourceDocument(
        doc_id=str(metadata["doc_id"]),
        material_type="court_rule",
        title_number=None,
        title_name=str(metadata["title_name"]),
        source_url=str(metadata["source_url"]),
        file_name=path.name,
        file_path=str(path),
        sha256=file_hash,
        byte_count=len(raw),
        line_count=len(lines),
        current_through=metadata.get("current_through"),  # type: ignore[arg-type]
    )
    return source, _parse_court_rule_materials(lines, source, data_version, metadata), []


def _source_sort_key(path: Path) -> tuple[int, int, str]:
    if path.name == "constitution.md":
        return (0, 0, path.name)
    match = re.match(r"title(\d+)\.md$", path.name)
    if match:
        return (1, int(match.group(1)), path.name)
    return (2, 999, path.name)


def _constitution_source(
    path: Path,
    text: str,
    raw: bytes,
    file_hash: str,
    lines: list[str],
) -> SourceDocument:
    match = CONSTITUTION_THROUGH_RE.search(text[:1200])
    return SourceDocument(
        doc_id="constitution",
        material_type="constitution",
        title_number=None,
        title_name="Delaware Constitution",
        source_url="https://delcode.delaware.gov/constitution/constitution.pdf",
        file_name=path.name,
        file_path=str(path),
        sha256=file_hash,
        byte_count=len(raw),
        line_count=len(lines),
        current_through=match.group("date") if match else None,
    )


def _title_source(
    path: Path,
    text: str,
    raw: bytes,
    file_hash: str,
    lines: list[str],
) -> SourceDocument:
    file_match = re.match(r"title(?P<number>\d+)\.md$", path.name)
    title_number = int(file_match.group("number")) if file_match else None
    title_name = f"Title {title_number}" if title_number is not None else path.stem

    for index, line in enumerate(lines[:80]):
        stripped = line.strip()
        if stripped == f"Title {title_number}" and index + 1 < len(lines):
            title_name = lines[index + 1].strip() or title_name
            break
        title_match = TITLE_RE.match(stripped)
        if title_match and title_match.group("name"):
            title_name = title_match.group("name").strip()
            break

    current_through = _extract_current_through(text)

    source_url = f"https://delcode.delaware.gov/title{title_number}/Title{title_number}.pdf"
    return SourceDocument(
        doc_id=f"title{title_number}",
        material_type="statute",
        title_number=title_number,
        title_name=title_name,
        source_url=source_url,
        file_name=path.name,
        file_path=str(path),
        sha256=file_hash,
        byte_count=len(raw),
        line_count=len(lines),
        current_through=current_through,
    )


def _extract_current_through(text: str) -> str | None:
    header = re.sub(r"\s+", " ", text[:2400]).strip()
    current = CURRENT_THROUGH_RE.search(header)
    if not current:
        return None
    chapter = re.sub(r"\s+", " ", current.group("chapter")).strip()
    return f"{current.group('date')} / {chapter}"


def _parse_sections(
    lines: list[str],
    source: SourceDocument,
    data_version: str,
) -> list[LegalMaterial]:
    starts: list[tuple[int, re.Match[str], str | None, str | None, str | None]] = []
    article = None
    chapter = None
    subchapter = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^ARTICLE\s+[IVXLCDM]+\.?", stripped):
            article = stripped
        elif re.match(r"^Chapter\s+[A-Za-z0-9.-]+$", stripped):
            chapter_name = _next_context_name(lines, index)
            chapter = f"{stripped}: {chapter_name}" if chapter_name else stripped
        elif re.match(r"^Subchapter\s+[A-Za-z0-9.-]+$", stripped):
            subchapter_name = _next_context_name(lines, index)
            subchapter = f"{stripped}: {subchapter_name}" if subchapter_name else stripped

        match = SECTION_RE.match(stripped)
        if match and _looks_like_section_heading(match, lines, index):
            starts.append((index, match, article, chapter, subchapter))

    materials: list[LegalMaterial] = []
    for pos, (start_index, match, article, chapter, subchapter) in enumerate(starts):
        end_index = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        section_number = _clean_section_number(match.group("section"))
        block_lines = lines[start_index:end_index]
        heading = _extract_heading(block_lines, match)
        body = _clean_section_text(block_lines)

        if source.material_type == "constitution":
            article_part = article or "Delaware Constitution"
            citation = f"Del. Const. {article_part}, § {section_number}"
            material_id = f"constitution-{_slug(article_part)}-sec-{_slug(section_number)}-line-{start_index + 1}"
            title_number = None
        else:
            citation = f"{source.title_number} Del. C. § {section_number}"
            material_id = f"title{source.title_number}-sec-{_slug(section_number)}-line-{start_index + 1}"
            title_number = source.title_number

        materials.append(
            LegalMaterial(
                material_id=material_id,
                material_type=source.material_type,
                jurisdiction="Delaware",
                citation=citation,
                normalized_citation=normalize_citation(citation),
                title_number=title_number,
                section_number=section_number,
                heading=heading,
                text=body,
                source_doc_id=source.doc_id,
                source_file=source.file_name,
                source_url=source.source_url,
                source_hash=source.sha256,
                data_version=data_version,
                is_current=1,
                article=article,
                chapter=chapter,
                subchapter=subchapter,
                start_line=start_index + 1,
            )
        )

    return materials


def _parse_chapters(
    lines: list[str],
    source: SourceDocument,
    data_version: str,
) -> list[LegalChapter]:
    if source.material_type != "statute" or source.title_number is None:
        return []

    chapters: list[LegalChapter] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = re.match(r"^Chapter\s+(?P<chapter>[A-Za-z0-9.-]+)$", stripped)
        if not match:
            continue
        chapter_number = match.group("chapter").rstrip(".")
        heading = _next_context_name(lines, index) or "(untitled chapter)"
        citation = f"{source.title_number} Del. C. ch. {chapter_number}"
        chapters.append(
            LegalChapter(
                chapter_id=f"title{source.title_number}-chapter-{_slug(chapter_number)}-line-{index + 1}",
                material_type=source.material_type,
                jurisdiction="Delaware",
                citation=citation,
                normalized_citation=normalize_citation(citation),
                title_number=source.title_number,
                chapter_number=chapter_number,
                heading=heading,
                source_doc_id=source.doc_id,
                source_file=source.file_name,
                source_url=source.source_url,
                source_hash=source.sha256,
                data_version=data_version,
                start_line=index + 1,
            )
        )
    return chapters


def _parse_court_rule_materials(
    lines: list[str],
    source: SourceDocument,
    data_version: str,
    metadata: dict[str, object],
) -> list[LegalMaterial]:
    starts = _court_rule_starts(lines, metadata)
    if not starts:
        starts = [(0, str(metadata.get("single_rule") or "document"), source.title_name)]

    materials: list[LegalMaterial] = []
    citation_prefix = str(metadata.get("citation_prefix") or source.title_name)
    for pos, (start_index, rule_number, heading) in enumerate(starts):
        end_index = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        block_lines = lines[start_index:end_index]
        body = _clean_section_text(block_lines)
        citation = _court_rule_citation(citation_prefix, rule_number)
        materials.append(
            LegalMaterial(
                material_id=f"{source.doc_id}-rule-{_slug(rule_number)}-line-{start_index + 1}",
                material_type=source.material_type,
                jurisdiction="Delaware",
                citation=citation,
                normalized_citation=normalize_citation(citation),
                title_number=None,
                section_number=rule_number,
                heading=heading,
                text=body,
                source_doc_id=source.doc_id,
                source_file=source.file_name,
                source_url=source.source_url,
                source_hash=source.sha256,
                data_version=data_version,
                is_current=1,
                article=source.title_name,
                chapter=None,
                subchapter=None,
                start_line=start_index + 1,
            )
        )
    return materials


def _court_rule_starts(lines: list[str], metadata: dict[str, object]) -> list[tuple[int, str, str]]:
    if metadata.get("single_rule"):
        heading = _first_nonempty_heading(lines) or str(metadata["title_name"])
        return [(0, str(metadata["single_rule"]), heading)]

    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if metadata.get("guidelines"):
            match = GUIDELINE_HEADING_RE.match(stripped)
            if match:
                starts.append((index, match.group("rule"), _clean_rule_heading(match.group("title"))))
            continue

        match = RULE_HEADING_RE.match(stripped)
        if not match or _is_court_rule_cross_reference(lines, index):
            continue
        rule_number = _clean_rule_number(match.group("rule"))
        heading = _clean_rule_heading(match.group("title")) or f"Rule {rule_number}"
        starts.append((index, rule_number, heading))
    return starts


def _is_court_rule_cross_reference(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    is_markdown_heading = stripped.startswith("#")
    if is_markdown_heading:
        return False
    previous = lines[index - 1].strip() if index > 0 else ""
    next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
    if not previous or previous.startswith("#") or next_line.startswith("#"):
        return False
    return not bool(re.match(r"^Rule\s+[0-9][0-9A-Za-z.-]*(?:[.:])?\s+[A-Z\[]", stripped))


def _court_rule_citation(prefix: str, rule_number: str) -> str:
    if prefix == "D.R.E.":
        return f"D.R.E. {rule_number}"
    if prefix.endswith("Litigants"):
        return f"{prefix} § {rule_number}"
    return f"{prefix} {rule_number}"


def _clean_rule_number(value: str) -> str:
    return value.strip().rstrip(".:")


def _clean_rule_heading(value: str) -> str:
    heading = re.sub(r"\s+", " ", value).strip()
    return heading.rstrip(".")


def _first_nonempty_heading(lines: list[str]) -> str | None:
    headings: list[str] = []
    for line in lines[:12]:
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            headings.append(stripped)
    return " — ".join(headings[:3]) if headings else None


def _court_rule_fallback_metadata(path: Path, lines: list[str]) -> dict[str, object]:
    title_name = _first_nonempty_heading(lines) or path.stem
    return {
        "doc_id": f"court-rule-{_slug(path.stem)}",
        "title_name": title_name,
        "citation_prefix": title_name,
        "source_url": path.as_uri(),
        "current_through": None,
    }


def _clean_section_number(value: str) -> str:
    return value.strip().rstrip(".")


def _looks_like_section_heading(match: re.Match[str], lines: list[str], index: int) -> bool:
    title = match.group("title").strip()
    if not title and index + 1 < len(lines):
        title = lines[index + 1].strip()
    if not title:
        return False

    first = title[0]
    if first not in "[ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return False
    if title.startswith(("[", "Repealed", "Reserved")):
        return True
    if re.match(r"^(and|or|of|to|for|from|under|by|with|in)\b", title, re.IGNORECASE):
        return False
    if re.match(r"^[A-Z][A-Za-z0-9'’(),;:/&\-\s\[\].§]+$", title):
        return True
    return False


def _extract_heading(block_lines: list[str], first_match: re.Match[str]) -> str:
    heading_parts: list[str] = []
    first_title = first_match.group("title").strip()
    if first_title:
        heading_parts.append(first_title)
        if first_title.endswith("."):
            heading = re.sub(r"\s+", " ", first_title).strip()
            return heading.rstrip(".")

    for line in block_lines[1:5]:
        stripped = line.strip()
        if not stripped or _is_body_line(stripped) or _is_noise_line(stripped):
            break
        heading_parts.append(stripped)
        if stripped.endswith("."):
            break

    heading = " ".join(part.strip() for part in heading_parts if part.strip())
    heading = re.sub(r"\s+", " ", heading).strip()
    return heading.rstrip(".") if heading else "(untitled section)"


def _clean_section_text(block_lines: Iterable[str]) -> str:
    cleaned: list[str] = []
    for line in block_lines:
        stripped = line.replace("\f", "").rstrip()
        if _is_noise_line(stripped.strip()):
            continue
        cleaned.append(stripped)
    text = "\n".join(cleaned).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _is_body_line(value: str) -> bool:
    return bool(
        re.match(r"^\([a-zA-Z0-9]+\)", value)
        or value.startswith("---(")
        or re.match(r"^\d+\)", value)
        or value.startswith("[")
    )


def _is_noise_line(value: str) -> bool:
    return bool(
        re.match(r"^Page\s+\d+$", value)
        or re.match(r"^Title\s+\d+\s+-\s+.+$", value)
        or re.match(r"^(Subtitle|Article|Part|Chapter|Subchapter)\s+[A-Za-z0-9IVXLCDM.-]+$", value)
        or value == "Cover Page"
    )


def _next_context_name(lines: list[str], index: int) -> str | None:
    if index + 1 >= len(lines):
        return None
    candidate = lines[index + 1].strip()
    if not candidate or SECTION_RE.match(candidate):
        return None
    if re.match(r"^(Chapter|Subchapter|Article|Part|Subtitle)\s+", candidate):
        return None
    return candidate


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "x"
