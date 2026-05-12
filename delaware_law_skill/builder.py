from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3

from .config import (
    DATA_VERSION,
    DELCODE_HOME_URL,
    DEFAULT_COVERAGE_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_RAW_COURT_RULES_DIR,
    DEFAULT_RAW_MD_DIR,
)
from .parser import (
    LegalChapter,
    LegalMaterial,
    SourceDocument,
    discover_markdown_files,
    parse_court_rule_file,
    parse_source_file,
)


SCHEMA = """
PRAGMA journal_mode = WAL;

DROP TABLE IF EXISTS metadata;
DROP TABLE IF EXISTS source_documents;
DROP TABLE IF EXISTS chapters;
DROP TABLE IF EXISTS materials;
DROP TABLE IF EXISTS materials_fts;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE source_documents (
    doc_id TEXT PRIMARY KEY,
    material_type TEXT NOT NULL,
    title_number INTEGER,
    title_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_count INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    current_through TEXT
);

CREATE TABLE materials (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT UNIQUE NOT NULL,
    material_type TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    citation TEXT NOT NULL,
    normalized_citation TEXT NOT NULL,
    title_number INTEGER,
    section_number TEXT NOT NULL,
    heading TEXT NOT NULL,
    text TEXT NOT NULL,
    source_doc_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    data_version TEXT NOT NULL,
    is_current INTEGER NOT NULL,
    article TEXT,
    chapter TEXT,
    subchapter TEXT,
    start_line INTEGER,
    FOREIGN KEY (source_doc_id) REFERENCES source_documents(doc_id)
);

CREATE TABLE chapters (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id TEXT UNIQUE NOT NULL,
    material_type TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    citation TEXT NOT NULL,
    normalized_citation TEXT NOT NULL,
    title_number INTEGER NOT NULL,
    chapter_number TEXT NOT NULL,
    heading TEXT NOT NULL,
    source_doc_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    data_version TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    FOREIGN KEY (source_doc_id) REFERENCES source_documents(doc_id)
);

CREATE INDEX idx_materials_citation ON materials(citation);
CREATE INDEX idx_materials_section ON materials(section_number);
CREATE INDEX idx_materials_title_section ON materials(title_number, section_number);
CREATE INDEX idx_materials_type ON materials(material_type);
CREATE INDEX idx_chapters_title_chapter ON chapters(title_number, chapter_number);
CREATE INDEX idx_chapters_chapter ON chapters(chapter_number);

CREATE VIRTUAL TABLE materials_fts USING fts5(
    citation,
    heading,
    text,
    content='materials',
    content_rowid='rowid'
);
"""


def build_database(
    source_dir: Path,
    court_rules_source_dir: Path | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    raw_md_dir: Path = DEFAULT_RAW_MD_DIR,
    raw_court_rules_dir: Path = DEFAULT_RAW_COURT_RULES_DIR,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    coverage_path: Path = DEFAULT_COVERAGE_PATH,
    copy_raw: bool = True,
) -> dict[str, object]:
    source_dir = source_dir.resolve()
    court_rules_source_dir = court_rules_source_dir.resolve() if court_rules_source_dir else None
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_md_dir.mkdir(parents=True, exist_ok=True)
    raw_court_rules_dir.mkdir(parents=True, exist_ok=True)

    files = discover_markdown_files(source_dir)
    if not files:
        raise FileNotFoundError(f"No markdown files found in {source_dir}")
    court_rule_files = discover_markdown_files(court_rules_source_dir) if court_rules_source_dir else []

    sources: list[SourceDocument] = []
    materials: list[LegalMaterial] = []
    chapters: list[LegalChapter] = []
    for path in files:
        source, parsed, parsed_chapters = parse_source_file(path, DATA_VERSION)
        sources.append(source)
        materials.extend(parsed)
        chapters.extend(parsed_chapters)
        if copy_raw:
            shutil.copy2(path, raw_md_dir / path.name)
    for path in court_rule_files:
        source, parsed, parsed_chapters = parse_court_rule_file(path, DATA_VERSION)
        sources.append(source)
        materials.extend(parsed)
        chapters.extend(parsed_chapters)
        if copy_raw:
            shutil.copy2(path, raw_court_rules_dir / path.name)

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _insert_metadata(conn, sources, materials, chapters)
        _insert_sources(conn, sources)
        _insert_chapters(conn, chapters)
        _insert_materials(conn, materials)
        conn.execute(
            """
            INSERT INTO materials_fts(rowid, citation, heading, text)
            SELECT rowid, citation, heading, COALESCE(article || char(10), '') || text FROM materials
            """
        )
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()

    db_hash = _file_sha256(db_path)
    (db_path.with_suffix(db_path.suffix + ".sha256")).write_text(
        f"{db_hash}  {db_path.name}\n",
        encoding="utf-8",
    )

    manifest = _build_manifest(source_dir, court_rules_source_dir, db_path, db_hash, sources, materials, chapters)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    coverage = _build_coverage(sources, materials, chapters)
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "db_path": str(db_path),
        "db_sha256": db_hash,
        "source_count": len(sources),
        "material_count": len(materials),
        "chapter_count": len(chapters),
        "manifest_path": str(manifest_path),
        "coverage_path": str(coverage_path),
    }


def _insert_metadata(
    conn: sqlite3.Connection,
    sources: list[SourceDocument],
    materials: list[LegalMaterial],
    chapters: list[LegalChapter],
) -> None:
    coverage_included = _coverage_included(sources)
    coverage_excluded = _coverage_excluded(sources)
    values = {
        "data_version": DATA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "jurisdiction": "Delaware",
        "coverage": "; ".join(coverage_included),
        "excluded": "; ".join(coverage_excluded),
        "source_count": str(len(sources)),
        "material_count": str(len(materials)),
        "chapter_count": str(len(chapters)),
        "official_source_home": DELCODE_HOME_URL,
    }
    conn.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", values.items())


def _insert_sources(conn: sqlite3.Connection, sources: list[SourceDocument]) -> None:
    conn.executemany(
        """
        INSERT INTO source_documents(
            doc_id, material_type, title_number, title_name, source_url, file_name,
            file_path, sha256, byte_count, line_count, current_through
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                source.doc_id,
                source.material_type,
                source.title_number,
                source.title_name,
                source.source_url,
                source.file_name,
                source.file_path,
                source.sha256,
                source.byte_count,
                source.line_count,
                source.current_through,
            )
            for source in sources
        ],
    )


def _insert_chapters(conn: sqlite3.Connection, chapters: list[LegalChapter]) -> None:
    conn.executemany(
        """
        INSERT INTO chapters(
            chapter_id, material_type, jurisdiction, citation, normalized_citation,
            title_number, chapter_number, heading, source_doc_id, source_file,
            source_url, source_hash, data_version, start_line
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                chapter.chapter_id,
                chapter.material_type,
                chapter.jurisdiction,
                chapter.citation,
                chapter.normalized_citation,
                chapter.title_number,
                chapter.chapter_number,
                chapter.heading,
                chapter.source_doc_id,
                chapter.source_file,
                chapter.source_url,
                chapter.source_hash,
                chapter.data_version,
                chapter.start_line,
            )
            for chapter in chapters
        ],
    )


def _insert_materials(conn: sqlite3.Connection, materials: list[LegalMaterial]) -> None:
    conn.executemany(
        """
        INSERT INTO materials(
            material_id, material_type, jurisdiction, citation, normalized_citation,
            title_number, section_number, heading, text, source_doc_id, source_file,
            source_url, source_hash, data_version, is_current, article, chapter,
            subchapter, start_line
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                material.material_id,
                material.material_type,
                material.jurisdiction,
                material.citation,
                material.normalized_citation,
                material.title_number,
                material.section_number,
                material.heading,
                material.text,
                material.source_doc_id,
                material.source_file,
                material.source_url,
                material.source_hash,
                material.data_version,
                material.is_current,
                material.article,
                material.chapter,
                material.subchapter,
                material.start_line,
            )
            for material in materials
        ],
    )


def _build_manifest(
    source_dir: Path,
    court_rules_source_dir: Path | None,
    db_path: Path,
    db_hash: str,
    sources: list[SourceDocument],
    materials: list[LegalMaterial],
    chapters: list[LegalChapter],
) -> dict[str, object]:
    return {
        "data_version": DATA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source_dir),
        "court_rules_source_directory": str(court_rules_source_dir) if court_rules_source_dir else None,
        "database_file": db_path.name,
        "database_sha256": db_hash,
        "jurisdiction": "Delaware",
        "coverage": {
            "included": _coverage_included(sources),
            "excluded": _coverage_excluded(sources),
        },
        "no_paid_sources": True,
        "official_source_home": DELCODE_HOME_URL,
        "disclaimer": (
            "This data pack supports retrieval and citation checking only. It is not an official database "
            "and does not provide legal advice."
        ),
        "source_files": [
            {
                "doc_id": source.doc_id,
                "file_name": source.file_name,
                "material_type": source.material_type,
                "title_number": source.title_number,
                "title_name": source.title_name,
                "source_url": source.source_url,
                "sha256": source.sha256,
                "byte_count": source.byte_count,
                "line_count": source.line_count,
                "current_through": source.current_through,
            }
            for source in sources
        ],
        "counts": {
            "source_files": len(sources),
            "materials": len(materials),
            "chapters": len(chapters),
        },
    }


def _build_coverage(
    sources: list[SourceDocument],
    materials: list[LegalMaterial],
    chapters: list[LegalChapter],
) -> dict[str, object]:
    by_source = Counter(material.source_doc_id for material in materials)
    chapters_by_source = Counter(chapter.source_doc_id for chapter in chapters)
    return {
        "data_version": DATA_VERSION,
        "summary": "; ".join(_coverage_included(sources)),
        "not_covered": _coverage_excluded(sources),
        "source_count": len(sources),
        "material_count": len(materials),
        "chapter_count": len(chapters),
        "sources": [
            {
                "doc_id": source.doc_id,
                "title_name": source.title_name,
                "material_type": source.material_type,
                "material_count": by_source[source.doc_id],
                "chapter_count": chapters_by_source[source.doc_id],
                "current_through": source.current_through,
                "source_url": source.source_url,
            }
            for source in sources
        ],
    }


def _coverage_included(sources: list[SourceDocument]) -> list[str]:
    included = ["Delaware Constitution", "Delaware Code Title 1-31"]
    if any(source.material_type == "court_rule" for source in sources):
        included.append("Selected Delaware Court Rules")
    return included


def _coverage_excluded(sources: list[SourceDocument]) -> list[str]:
    excluded = ["Delaware regulations", "opinions/cases", "secondary sources", "paid legal databases"]
    if not any(source.material_type == "court_rule" for source in sources):
        excluded.insert(1, "court rules")
    return excluded


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
