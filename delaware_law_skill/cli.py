from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

from .builder import build_database
from .config import (
    BGE_EMBEDDING_MODEL,
    BGE_RERANKER_MODEL,
    DATA_VERSION,
    DEFAULT_ADMIN_CODE_DB_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_SEMANTIC_INDEX_DIR,
)
from .admin_code import (
    check_admin_regulation_freshness,
    fetch_admin_regulation,
    get_admin_regulation_by_citation,
    refresh_admin_code_index,
    refresh_admin_code_title,
    search_admin_code,
)
from .database import DelawareLawDatabase
from .semantic import SemanticError, build_semantic_index, semantic_index_status, semantic_search
from .validator import validate_text


REVIEW_SECTIONS = [
    "明显错误",
    "引用太宽泛",
    "需要查外部材料",
    "本地数据库没查到",
    "可能影响结论的相关法律",
    "已确认正确的引用",
    "本工具未覆盖的内容",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="delaware-law",
        description="Local Delaware legal materials lookup, search, and citation validation.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the local SQLite data pack.")
    parser.add_argument(
        "--admin-db",
        default=str(DEFAULT_ADMIN_CODE_DB_PATH),
        help="Path to the Delaware Administrative Code index/cache database.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build the local data pack from markdown files.")
    build_parser.add_argument("--source", required=True, help="Directory containing Delaware markdown files.")
    build_parser.add_argument("--court-rules-source", help="Directory containing Delaware court rules markdown files.")
    build_parser.add_argument("--no-copy-raw", action="store_true", help="Do not copy source markdown into data/raw_md.")

    lookup_parser = subparsers.add_parser("lookup", help="Look up an exact citation.")
    lookup_parser.add_argument("citation", help='Example: "6 Del. C. § 17-407"')
    lookup_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    search_parser = subparsers.add_parser("search", help="Search legal materials by keywords.")
    search_parser.add_argument("query", help='Example: "limited partnership distribution"')
    search_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum results.")
    search_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    admin_refresh_parser = subparsers.add_parser(
        "admin-refresh-index",
        help="Refresh the Delaware Administrative Code index without downloading all PDFs.",
    )
    admin_refresh_parser.add_argument("--title", help="Refresh only one Administrative Code title, e.g. 24.")
    admin_refresh_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    admin_search_parser = subparsers.add_parser(
        "admin-search",
        help="Search the Delaware Administrative Code index and lazy cache.",
    )
    admin_search_parser.add_argument("query", help='Example: "24 DE Admin. Code 3900"')
    admin_search_parser.add_argument("--title", help="Limit search to one title.")
    admin_search_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum results.")
    admin_search_parser.add_argument(
        "--no-cached-text",
        action="store_true",
        help="Search index only; do not lazy-fetch missing regulation PDFs.",
    )
    admin_search_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    admin_fetch_parser = subparsers.add_parser(
        "admin-fetch",
        help="Fetch one Delaware Administrative Code regulation PDF by index id.",
    )
    admin_fetch_parser.add_argument("regulation_index_id", type=int)
    admin_fetch_parser.add_argument("--force-refresh", action="store_true", help="Refresh even if cache is fresh.")
    admin_fetch_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    admin_lookup_parser = subparsers.add_parser(
        "admin-lookup",
        help="Look up one Delaware Administrative Code citation and lazy-fetch its official PDF text.",
    )
    admin_lookup_parser.add_argument("citation", help='Example: "24 DE Admin. Code 3900"')
    admin_lookup_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    admin_freshness_parser = subparsers.add_parser(
        "admin-freshness",
        help="Check whether one cached Administrative Code regulation is still fresh.",
    )
    admin_freshness_parser.add_argument("regulation_index_id", type=int)
    admin_freshness_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    semantic_build_parser = subparsers.add_parser(
        "semantic-build",
        help="Build the optional semantic index for broad topic retrieval.",
    )
    semantic_build_parser.add_argument("--index-dir", default=str(DEFAULT_SEMANTIC_INDEX_DIR))
    semantic_build_parser.add_argument(
        "--model",
        default=BGE_EMBEDDING_MODEL,
        help=f"Embedding model name. Default: {BGE_EMBEDDING_MODEL}",
    )
    semantic_build_parser.add_argument(
        "--reranker-model",
        default=BGE_RERANKER_MODEL,
        help=f"Reranker model name recorded in the index. Default: {BGE_RERANKER_MODEL}",
    )
    semantic_build_parser.add_argument("--batch-size", type=int, default=16)
    semantic_build_parser.add_argument("--limit", type=int, help="Index only the first N materials for testing.")
    semantic_build_parser.add_argument("--quiet", action="store_true", help="Hide model progress bars.")
    semantic_build_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    rag_build_parser = subparsers.add_parser(
        "rag-build",
        help="Build the RAG index used by rag-search.",
    )
    rag_build_parser.add_argument("--index-dir", default=str(DEFAULT_SEMANTIC_INDEX_DIR))
    rag_build_parser.add_argument(
        "--model",
        default=BGE_EMBEDDING_MODEL,
        help=f"Embedding model name. Default: {BGE_EMBEDDING_MODEL}",
    )
    rag_build_parser.add_argument(
        "--reranker-model",
        default=BGE_RERANKER_MODEL,
        help=f"Reranker model name recorded in the index. Default: {BGE_RERANKER_MODEL}",
    )
    rag_build_parser.add_argument("--batch-size", type=int, default=16)
    rag_build_parser.add_argument("--limit", type=int, help="Index only the first N materials for testing.")
    rag_build_parser.add_argument("--quiet", action="store_true", help="Hide model progress bars.")
    rag_build_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    _add_rag_search_parser(
        subparsers,
        "semantic-search",
        "Find likely relevant sections with BGE, then retrieve exact database materials.",
    )
    _add_rag_search_parser(
        subparsers,
        "rag-search",
        "RAG-style locator: first find likely sections, then retrieve exact database materials.",
    )

    validate_parser = subparsers.add_parser("validate", help="Validate citations in text or a file.")
    validate_parser.add_argument("text", nargs="?", help="Text to validate. Omit when using --file.")
    validate_parser.add_argument("--file", help="Path to a text/markdown file to validate.")
    validate_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    review_parser = subparsers.add_parser("review", help="Review a document and print a six-category citation report.")
    review_parser.add_argument("text", nargs="?", help="Text to review. Omit when using --file.")
    review_parser.add_argument("--file", help="Path to a text/markdown/docx file to review.")
    review_parser.add_argument("--rag", action="store_true", help="Run RAG locator on recognized conceptual references.")
    review_parser.add_argument("--rag-limit", type=int, default=3, help="Maximum RAG candidates per conceptual query.")
    review_parser.add_argument("--rag-candidates", type=int, default=30, help="Rough candidates to pull before reranking.")
    review_parser.add_argument("--index-dir", default=str(DEFAULT_SEMANTIC_INDEX_DIR), help="Path to the RAG index.")
    review_parser.add_argument("--no-rerank", action="store_true", help="Skip reranking for review --rag.")
    review_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    rag_status_parser = subparsers.add_parser("rag-status", help="Check whether the local RAG index is ready.")
    rag_status_parser.add_argument("--index-dir", default=str(DEFAULT_SEMANTIC_INDEX_DIR), help="Path to the RAG index.")
    rag_status_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    info_parser = subparsers.add_parser("info", help="Show data pack metadata.")
    info_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    args = parser.parse_args(argv)

    if args.command == "build":
        result = build_database(
            source_dir=Path(args.source),
            court_rules_source_dir=Path(args.court_rules_source) if args.court_rules_source else None,
            db_path=Path(args.db),
            copy_raw=not args.no_copy_raw,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "admin-refresh-index":
        return _admin_refresh_index(Path(args.admin_db), args.title, args.json)
    if args.command == "admin-search":
        return _admin_search(
            Path(args.admin_db),
            args.query,
            args.title,
            args.limit,
            not args.no_cached_text,
            args.json,
        )
    if args.command == "admin-fetch":
        return _admin_fetch(Path(args.admin_db), args.regulation_index_id, args.force_refresh, args.json)
    if args.command == "admin-lookup":
        return _admin_lookup(Path(args.admin_db), args.citation, args.json)
    if args.command == "admin-freshness":
        return _admin_freshness(Path(args.admin_db), args.regulation_index_id, args.json)

    db = DelawareLawDatabase(Path(args.db))
    try:
        if args.command == "lookup":
            return _lookup(db, args.citation, args.json)
        if args.command == "search":
            return _search(db, args.query, args.limit, args.json)
        if args.command in {"semantic-build", "rag-build"}:
            return _semantic_build(
                db,
                Path(args.index_dir),
                args.model,
                args.reranker_model,
                args.batch_size,
                args.limit,
                args.quiet,
                args.json,
            )
        if args.command in {"semantic-search", "rag-search"}:
            return _semantic_search(
                db,
                args.query,
                args.limit,
                args.candidates,
                Path(args.index_dir),
                args.model,
                args.reranker_model,
                not args.no_rerank,
                args.json,
            )
        if args.command == "validate":
            text = _load_validation_text(args.text, args.file)
            return _validate(db, text, args.json)
        if args.command == "review":
            text = _load_validation_text(args.text, args.file)
            return _review(
                db,
                text,
                args.json,
                args.rag,
                args.rag_limit,
                args.rag_candidates,
                Path(args.index_dir),
                not args.no_rerank,
            )
        if args.command == "rag-status":
            return _rag_status(db, Path(args.index_dir), args.json)
        if args.command == "info":
            return _info(db, args.json)
    finally:
        db.close()

    return 1


def _add_rag_search_parser(subparsers: argparse._SubParsersAction, command: str, help_text: str) -> None:
    rag_parser = subparsers.add_parser(command, help=help_text)
    rag_parser.add_argument("query", help='Example: "Delaware LP distribution solvency test"')
    rag_parser.add_argument("-n", "--limit", type=int, default=10, help="Maximum final results.")
    rag_parser.add_argument(
        "--candidates",
        type=int,
        default=50,
        help="Number of rough candidates to pull before exact retrieval and reranking.",
    )
    rag_parser.add_argument("--index-dir", default=str(DEFAULT_SEMANTIC_INDEX_DIR))
    rag_parser.add_argument(
        "--model",
        default=None,
        help=f"Embedding model name. Default: index setting or {BGE_EMBEDDING_MODEL}",
    )
    rag_parser.add_argument(
        "--reranker-model",
        default=BGE_RERANKER_MODEL,
        help=f"Reranker model name. Default: {BGE_RERANKER_MODEL}",
    )
    rag_parser.add_argument("--no-rerank", action="store_true", help="Skip BGE reranker.")
    rag_parser.add_argument("--json", action="store_true", help="Print JSON output.")


def _lookup(db: DelawareLawDatabase, citation: str, as_json: bool) -> int:
    query, rows = db.lookup(citation)
    chapter_query = None
    chapter_rows = []
    rule_query = None
    rule_rows = []
    if not rows and query.section_number is None:
        chapter_query, chapter_rows = db.lookup_chapter(citation)
    if not rows and not chapter_rows:
        rule_query, rule_rows = db.lookup_rule(citation)
    metadata = db.metadata()
    if as_json:
        print(
            json.dumps(
                {
                    "input": citation,
                    "parsed": query.__dict__,
                    "parsed_chapter": chapter_query.__dict__ if chapter_query else None,
                    "parsed_rule": rule_query.__dict__ if rule_query else None,
                    "found": bool(rows or chapter_rows or rule_rows),
                    "data_version": metadata.get("data_version"),
                    "coverage": metadata.get("coverage"),
                    "results": [_row_to_material(row, include_text=True) for row in rows],
                    "chapter_results": [_row_to_chapter(row) for row in chapter_rows],
                    "court_rule_results": [_row_to_material(row, include_text=True) for row in rule_rows],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if rows or chapter_rows or rule_rows else 2

    print(f"查询：{citation}")
    print(f"数据包：{metadata.get('data_version', DATA_VERSION)}")
    print(f"覆盖范围：{metadata.get('coverage', 'Delaware Constitution; Delaware Code Title 1-31')}")
    if not rows and not chapter_rows and not rule_rows:
        print("结果：本地数据库未检出。不得据此认定该材料不存在；请回查官方来源或更新数据库。")
        return 2

    if chapter_rows:
        if len(chapter_rows) > 1:
            print(f"结果：找到 {len(chapter_rows)} 个可能匹配的 Chapter，引用需要更精确。")
        else:
            print("结果：找到 Chapter。")
        for index, row in enumerate(chapter_rows, start=1):
            print()
            print(f"[{index}] {row['citation']} — {row['heading']}")
            print(f"来源文件：{row['source_file']}")
            print(f"官方来源：{row['source_url']}")
            print("提醒：这是章级引用；用于具体法律结论时，建议进一步定位到具体 Section。")
        _print_disclaimer()
        return 0

    if rule_rows:
        if len(rule_rows) > 1:
            print(f"结果：找到 {len(rule_rows)} 条可能匹配的 court rule，引用建议更精确。")
        else:
            print("结果：找到 court rule。")
        for index, row in enumerate(rule_rows, start=1):
            print()
            print(f"[{index}] {row['citation']} — {row['heading']}")
            print(f"来源文件：{row['source_file']}")
            print(f"官方来源：{row['source_url']}")
            print()
            print(row["text"])
        _print_disclaimer()
        return 0

    if len(rows) > 1:
        print(f"结果：找到 {len(rows)} 条可能匹配，引用可能需要更精确。")
    else:
        print("结果：找到。")

    for index, row in enumerate(rows, start=1):
        print()
        print(f"[{index}] {row['citation']} — {row['heading']}")
        print(f"来源文件：{row['source_file']}")
        print(f"官方来源：{row['source_url']}")
        print()
        print(row["text"])
    _print_disclaimer()
    return 0


def _search(db: DelawareLawDatabase, query: str, limit: int, as_json: bool) -> int:
    rows = db.search(query, limit)
    metadata = db.metadata()
    if as_json:
        print(
            json.dumps(
                {
                    "query": query,
                    "data_version": metadata.get("data_version"),
                    "coverage": metadata.get("coverage"),
                    "results": [_row_to_material(row, include_text=False) for row in rows],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"搜索：{query}")
    print(f"数据包：{metadata.get('data_version', DATA_VERSION)}")
    print(f"覆盖范围：{metadata.get('coverage', 'Delaware Constitution; Delaware Code Title 1-31')}")
    if not rows:
        print("结果：未找到。可尝试 rag-search 做主题定位；不得据此认定相关法律材料不存在。")
        return 2

    for index, row in enumerate(rows, start=1):
        preview = " ".join(row["text"].split())[:320]
        print()
        print(f"[{index}] {row['citation']} — {row['heading']}")
        print(f"来源文件：{row['source_file']}")
        print(f"官方来源：{row['source_url']}")
        print(f"摘录：{preview}...")
    _print_disclaimer()
    return 0


def _semantic_build(
    db: DelawareLawDatabase,
    index_dir: Path,
    embedding_model: str,
    reranker_model: str,
    batch_size: int,
    limit: int | None,
    quiet: bool,
    as_json: bool,
) -> int:
    try:
        result = build_semantic_index(
            db,
            index_dir=index_dir,
            embedding_model=embedding_model,
            reranker_model=reranker_model,
            batch_size=batch_size,
            limit=limit,
            show_progress=not quiet,
        )
    except SemanticError as exc:
        print(f"语义索引未生成：{exc}", file=sys.stderr)
        return 2

    payload = result.__dict__
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("语义索引已生成。")
    print(f"索引目录：{result.index_dir}")
    print(f"粗找模型：{result.embedding_model}")
    print(f"复排模型：{result.reranker_model}")
    print(f"材料数量：{result.material_count}")
    print(f"向量维度：{result.embedding_dimension}")
    print("流程：语义粗找 → 本地数据库精确取回 → 复排。")
    return 0


def _semantic_search(
    db: DelawareLawDatabase,
    query: str,
    limit: int,
    candidate_limit: int,
    index_dir: Path,
    embedding_model: str | None,
    reranker_model: str,
    rerank: bool,
    as_json: bool,
) -> int:
    metadata = db.metadata()
    try:
        rows = semantic_search(
            db,
            query,
            index_dir=index_dir,
            embedding_model=embedding_model,
            reranker_model=reranker_model,
            limit=limit,
            candidate_limit=candidate_limit,
            rerank=rerank,
        )
    except SemanticError as exc:
        print(f"语义检索不可用：{exc}", file=sys.stderr)
        return 2

    if as_json:
        print(
            json.dumps(
                {
                    "query": query,
                    "pipeline": "semantic candidate retrieval -> exact SQLite material retrieval -> reranking",
                    "data_version": metadata.get("data_version"),
                    "coverage": metadata.get("coverage"),
                    "rerank": rerank,
                    "results": [row.to_dict() for row in rows],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if rows else 2

    print(f"语义检索：{query}")
    print(f"数据包：{metadata.get('data_version', DATA_VERSION)}")
    print(f"覆盖范围：{metadata.get('coverage', 'Delaware Constitution; Delaware Code Title 1-31')}")
    print("流程：先用 BGE 模型找大概位置，再从本地数据库精确取回原文。")
    print(f"复排：{'开启' if rerank else '关闭'}")
    if not rows:
        print("结果：未找到。")
        return 2

    for index, row in enumerate(rows, start=1):
        score_label = "复排分" if row.rerank_score is not None else "语义分"
        print()
        print(f"[{index}] {row.citation} — {row.heading}")
        print(f"精确取回：{'是' if row.exact_retrieved else '否'} | {score_label}：{row.final_score:.4f}")
        print(f"来源文件：{row.source_file}")
        print(f"官方来源：{row.source_url}")
        print(f"摘录：{row.preview}...")
    _print_disclaimer()
    return 0


def _rag_status(db: DelawareLawDatabase, index_dir: Path, as_json: bool) -> int:
    status = semantic_index_status(db, index_dir)
    payload = status.to_dict()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"RAG索引：{'可用' if status.ready else '不可用'}")
    print(f"索引目录：{status.index_dir}")
    print(f"数据包版本：{status.db_data_version}")
    if status.data_version:
        print(f"索引版本：{status.data_version}")
    if status.embedding_model:
        print(f"粗找模型：{status.embedding_model}")
    if status.reranker_model:
        print(f"复排模型：{status.reranker_model}")
    if status.material_count is not None:
        print(f"索引材料数：{status.material_count}")
    for filename, exists in status.files.items():
        print(f"{filename}: {'存在' if exists else '缺失'}")
    for warning in status.warnings:
        print(f"提醒：{warning}")
    return 0


def _validate(db: DelawareLawDatabase, text: str, as_json: bool) -> int:
    report = validate_text(db, text)
    metadata = db.metadata()
    report["data_version"] = metadata.get("data_version")
    report["coverage"] = metadata.get("coverage")

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"数据包：{report['data_version']}")
    print(f"覆盖范围：{report['coverage']}")
    print(f"识别到引用数量：{report['citation_count']}")
    if report.get("chapter_reference_count"):
        print(f"识别到 Chapter 引用数量：{report['chapter_reference_count']}")
    if report.get("court_rule_reference_count"):
        print(f"识别到 court rule 引用数量：{report['court_rule_reference_count']}")
    if report.get("broad_reference_count"):
        print(f"识别到过宽 Title 引用数量：{report['broad_reference_count']}")
    if report.get("topic_review_count"):
        print(f"识别到主题校验提醒数量：{report['topic_review_count']}")
    if report.get("implicit_reference_count"):
        print(f"识别到隐式引用数量：{report['implicit_reference_count']}")
    if report.get("database_misses"):
        print(f"本地数据库没查到数量：{len(report['database_misses'])}")

    for warning in report["coverage_warnings"]:
        print(f"覆盖提醒：{warning}")

    for index, item in enumerate(report["citations"], start=1):
        print()
        print(f"[{index}] {item['input']}")
        print(f"状态：{item['status']} — {item['message']}")
        for match in item["matches"]:
            print(f"匹配：{match['citation']} — {match['heading']}")
            print(f"来源：{match['source_file']} | {match['source_url']}")
        for warning in item["warnings"]:
            print(f"提醒：{warning}")
        for suggestion in item["suggestions"]:
            print(f"建议查看：{suggestion['citation']} — {suggestion['heading']}")
            print(f"原因：{suggestion['reason']}")

    for index, item in enumerate(report.get("chapter_references", []), start=1):
        print()
        print(f"[Chapter {index}] {item['input']}")
        print(f"状态：{item['status']} — {item['message']}")
        for match in item["matches"]:
            print(f"匹配：{match['citation']} — {match['heading']}")
            print(f"来源：{match['source_file']} | {match['source_url']}")
        for warning in item["warnings"]:
            print(f"提醒：{warning}")
        for suggestion in item["suggestions"]:
            print(f"建议查看：{suggestion['citation']} — {suggestion['heading']}")
            print(f"原因：{suggestion['reason']}")

    for index, item in enumerate(report.get("court_rule_references", []), start=1):
        print()
        print(f"[Court Rule {index}] {item['input']}")
        print(f"状态：{item['status']} — {item['message']}")
        for match in item["matches"]:
            print(f"匹配：{match['citation']} — {match['heading']}")
            print(f"来源：{match['source_file']} | {match['source_url']}")
        for warning in item["warnings"]:
            print(f"提醒：{warning}")

    for index, item in enumerate(report.get("broad_references", []), start=1):
        print()
        print(f"[Broad {index}] {item['input']}")
        print(f"状态：{item['status']} — {item['message']}")
        for match in item["matches"]:
            print(f"匹配：Title {match['title_number']} — {match['title_name']}")
            print(f"来源：{match['source_file']} | {match['source_url']}")
        for warning in item["warnings"]:
            print(f"提醒：{warning}")
        for suggestion in item.get("suggestions", []):
            print(f"建议查看：{suggestion['citation']} — {suggestion['heading']}")
            print(f"原因：{suggestion['reason']}")

    for index, item in enumerate(report.get("topic_reviews", []), start=1):
        print()
        print(f"[Topic {index}] {item['category']} — {item['code']}")
        print(f"提醒：{item['message']}")
        if item.get("coverage"):
            coverage = item["coverage"]
            if coverage.get("covered"):
                print(f"已覆盖：{coverage['covered']}")
            if coverage.get("not_covered"):
                print(f"未覆盖：{coverage['not_covered']}")
        for suggestion in item["suggestions"]:
            print(f"建议查看：{suggestion['citation']} — {suggestion['heading']}")
            print(f"原因：{suggestion['reason']}")
            if suggestion.get("source_url"):
                print(f"来源：{suggestion['source_url']}")

    for index, item in enumerate(report.get("implicit_references", []), start=1):
        print()
        print(f"[Implicit {index}] {item['input']}")
        print(f"状态：{item['status']} — {item['message']}")
        for warning in item.get("warnings", []):
            print(f"提醒：{warning}")
        for suggestion in item.get("suggestions", []):
            print(f"建议查看：{suggestion['citation']} — {suggestion['heading']}")
            print(f"原因：{suggestion['reason']}")
            if suggestion.get("source_url"):
                print(f"来源：{suggestion['source_url']}")

    for index, item in enumerate(report.get("database_misses", []), start=1):
        print()
        print(f"[Database Miss {index}] {item['input']}")
        print(f"状态：{item['kind']} — {item['message']}")
        for warning in item.get("warnings", []):
            print(f"提醒：{warning}")

    if report["outside_delaware_signals"]:
        print()
        print("疑似非 Delaware/联邦材料信号：")
        for signal in report["outside_delaware_signals"]:
            print(f"- {signal}")

    if report["uncovered_material_signals"]:
        print()
        print("当前数据包暂不覆盖的材料信号：")
        for signal in report["uncovered_material_signals"]:
            print(f"- {signal}")

    _print_disclaimer()
    return 0


def _review(
    db: DelawareLawDatabase,
    text: str,
    as_json: bool,
    use_rag: bool = False,
    rag_limit: int = 3,
    rag_candidates: int = 30,
    index_dir: Path = DEFAULT_SEMANTIC_INDEX_DIR,
    rerank: bool = True,
) -> int:
    report = validate_text(db, text)
    metadata = db.metadata()
    categorized = _categorize_review(report, metadata)
    if use_rag:
        categorized["rag_candidates"] = _rag_candidates_for_review(
            db,
            report,
            index_dir=index_dir,
            limit=rag_limit,
            candidate_limit=rag_candidates,
            rerank=rerank,
        )
    if as_json:
        print(json.dumps(categorized, ensure_ascii=False, indent=2))
        return 0

    print(f"数据包：{categorized['data_version']}")
    print(f"覆盖范围：{categorized['coverage']}")
    print()
    for section in REVIEW_SECTIONS:
        print(f"## {section}")
        items = categorized["sections"][section]
        if not items:
            print("- 未发现。")
            print()
            continue
        for item in items:
            print(f"- {item['summary']}")
            for detail in item.get("details", []):
                print(f"  {detail}")
        print()
    if use_rag:
        print("## RAG 候选定位")
        candidates = categorized.get("rag_candidates", [])
        if not candidates:
            print("- 未发现需要 RAG 定位的概念性引用。")
        for item in candidates:
            print(f"- {item['query']}：{item['status']}")
            if item.get("message"):
                print(f"  {item['message']}")
            for result in item.get("results", []):
                print(f"  {result['citation']} — {result['heading']} | {result['source_url']}")
        print()
    _print_disclaimer()
    return 0


def _categorize_review(report: dict[str, object], metadata: dict[str, str]) -> dict[str, object]:
    sections: dict[str, list[dict[str, object]]] = {section: [] for section in REVIEW_SECTIONS}

    for item in report.get("citations", []):
        warnings = item.get("warnings", [])
        matches = item.get("matches", [])
        has_topic_mismatch = any("主题可能不匹配" in warning for warning in warnings)
        if item.get("status") == "not_found":
            sections["本地数据库没查到"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _citation_details(item),
                }
            )
        elif item.get("status") == "invalid_format" or has_topic_mismatch:
            sections["明显错误"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _citation_details(item),
                }
            )
        if item.get("status") == "found" and not has_topic_mismatch:
            sections["已确认正确的引用"].append(
                {
                    "summary": f"{item['input']}：已验证存在。",
                    "details": _citation_details(item, include_warnings=False),
                }
            )

    for item in report.get("chapter_references", []):
        if item.get("status") == "found":
            sections["引用太宽泛"].append(
                {
                    "summary": f"{item['input']}：Chapter 级引用已找到，但用于具体结论时应定位到 Section。",
                    "details": _chapter_details(item),
                }
            )
        elif item.get("status") == "not_found":
            sections["本地数据库没查到"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _chapter_details(item),
                }
            )
        else:
            sections["明显错误"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _chapter_details(item),
                }
            )

    for item in report.get("court_rule_references", []):
        if item.get("status") == "found":
            sections["已确认正确的引用"].append(
                {
                    "summary": f"{item['input']}：已验证 court rule 存在。",
                    "details": _citation_details(item, include_warnings=True),
                }
            )
        elif item.get("status") == "not_found":
            sections["本地数据库没查到"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _citation_details(item),
                }
            )
        else:
            sections["明显错误"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _citation_details(item),
                }
            )

    for item in report.get("broad_references", []):
        if item.get("status") == "not_found":
            sections["本地数据库没查到"].append(
                {
                    "summary": f"{item['input']}：{item['message']}",
                    "details": _broad_details(item),
                }
            )
            continue
        sections["引用太宽泛"].append(
            {
                "summary": f"{item['input']}：{item['message']}",
                "details": _broad_details(item),
            }
        )

    for item in report.get("implicit_references", []):
        target = "明显错误" if item.get("warnings") else "可能影响结论的相关法律"
        sections[target].append(
            {
                "summary": str(item.get("message")),
                "details": _implicit_details(item),
            }
        )

    for item in report.get("topic_reviews", []):
        category = item.get("category")
        target = _review_section_for_category(str(category))
        sections[target].append(
            {
                "summary": str(item.get("message")),
                "details": _topic_details(item),
            }
        )

    for warning in report.get("coverage_warnings", []):
        sections["需要查外部材料"].append({"summary": warning, "details": []})

    sections["本工具未覆盖的内容"].append(
        {
            "summary": f"当前数据包覆盖：{metadata.get('coverage')}",
            "details": [
                f"未覆盖：{metadata.get('excluded', 'regulations; opinions/cases; paid legal databases')}",
                f"source_count: {metadata.get('source_count')}",
                f"material_count: {metadata.get('material_count')}",
                f"chapter_count: {metadata.get('chapter_count', 'not available')}",
            ],
        }
    )

    return {
        "data_version": metadata.get("data_version"),
        "coverage": metadata.get("coverage"),
        "sections": sections,
        "database_misses": report.get("database_misses", []),
        "implicit_references": report.get("implicit_references", []),
        "rag_candidates": report.get("rag_candidates", []),
    }


def _citation_details(item: dict[str, object], include_warnings: bool = True) -> list[str]:
    details: list[str] = []
    for match in item.get("matches", []):
        details.append(f"匹配：{match['citation']} — {match['heading']} | {match['source_url']}")
    if include_warnings:
        for warning in item.get("warnings", []):
            details.append(f"提醒：{warning}")
    for suggestion in item.get("suggestions", []):
        details.append(f"建议：{suggestion['citation']} — {suggestion['heading']}；{suggestion['reason']}")
    return details


def _chapter_details(item: dict[str, object]) -> list[str]:
    details: list[str] = []
    for match in item.get("matches", []):
        details.append(f"匹配：{match['citation']} — {match['heading']} | {match['source_url']}")
    for warning in item.get("warnings", []):
        details.append(f"提醒：{warning}")
    for suggestion in item.get("suggestions", []):
        details.append(f"建议：{suggestion['citation']} — {suggestion['heading']}；{suggestion['reason']}")
    return details


def _broad_details(item: dict[str, object]) -> list[str]:
    details: list[str] = []
    for match in item.get("matches", []):
        details.append(f"匹配：Title {match['title_number']} — {match['title_name']} | {match['source_url']}")
    for warning in item.get("warnings", []):
        details.append(f"提醒：{warning}")
    for suggestion in item.get("suggestions", []):
        details.append(f"建议：{suggestion['citation']} — {suggestion['heading']}；{suggestion['reason']}")
    return details


def _topic_details(item: dict[str, object]) -> list[str]:
    details: list[str] = []
    coverage = item.get("coverage") or {}
    if coverage.get("covered"):
        details.append(f"已覆盖：{coverage['covered']}")
    if coverage.get("not_covered"):
        details.append(f"未覆盖：{coverage['not_covered']}")
    for suggestion in item.get("suggestions", []):
        source = f" | {suggestion['source_url']}" if suggestion.get("source_url") else ""
        details.append(f"建议：{suggestion['citation']} — {suggestion['heading']}；{suggestion['reason']}{source}")
    return details


def _implicit_details(item: dict[str, object]) -> list[str]:
    details: list[str] = []
    for warning in item.get("warnings", []):
        details.append(f"提醒：{warning}")
    for suggestion in item.get("suggestions", []):
        source = f" | {suggestion['source_url']}" if suggestion.get("source_url") else ""
        details.append(f"建议：{suggestion['citation']} — {suggestion['heading']}；{suggestion['reason']}{source}")
    return details


def _review_section_for_category(category: str) -> str:
    mapping = {
        "错误引用": "明显错误",
        "明显错误": "明显错误",
        "过宽引用": "引用太宽泛",
        "需外部材料": "需要查外部材料",
        "需要查外部材料": "需要查外部材料",
        "数据库疑似缺漏/解析异常": "本地数据库没查到",
        "本地数据库没查到": "本地数据库没查到",
        "已验证引用": "可能影响结论的相关法律",
        "可能影响结论的相关法律": "可能影响结论的相关法律",
        "已确认正确的引用": "已确认正确的引用",
        "覆盖限制": "本工具未覆盖的内容",
        "本工具未覆盖的内容": "本工具未覆盖的内容",
    }
    return mapping.get(category, "需要查外部材料")


def _rag_candidates_for_review(
    db: DelawareLawDatabase,
    report: dict[str, object],
    index_dir: Path,
    limit: int,
    candidate_limit: int,
    rerank: bool,
) -> list[dict[str, object]]:
    queries = _rag_queries_from_report(report)
    results: list[dict[str, object]] = []
    for query in queries:
        try:
            rows = semantic_search(
                db,
                query,
                index_dir=index_dir,
                limit=limit,
                candidate_limit=candidate_limit,
                rerank=rerank,
            )
        except SemanticError as exc:
            results.append({"query": query, "status": "unavailable", "message": str(exc), "results": []})
            break
        results.append(
            {
                "query": query,
                "status": "found" if rows else "not_found",
                "message": "",
                "results": [row.to_dict() for row in rows],
            }
        )
    return results


def _rag_queries_from_report(report: dict[str, object]) -> list[str]:
    queries: list[str] = []
    for item in report.get("implicit_references", []):
        query = item.get("query")
        if query:
            queries.append(str(query))
    for item in report.get("topic_reviews", []):
        code = str(item.get("code", ""))
        if code.startswith("ucc_"):
            queries.append(str(item.get("message", "")))
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(query)
    return unique[:5]


def _admin_refresh_index(admin_db_path: Path, title: str | None, as_json: bool) -> int:
    if title:
        result = refresh_admin_code_title(title, db_path=admin_db_path)
    else:
        result = refresh_admin_code_index(db_path=admin_db_path)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 2
    if result.get("status") != "ok":
        print("Administrative Code 索引刷新失败。")
        print(f"Title：{result.get('title_number', '全部')}")
        print(f"错误：{result.get('error_message', '未知错误')}")
        return 2
    if title:
        print(f"已刷新 Delaware Administrative Code Title {result['title_number']} 索引。")
        print(f"索引条目：{result['indexed_count']}")
    else:
        print("已刷新 Delaware Administrative Code 索引。")
        print(f"Title 数量：{result['refreshed_title_count']}")
        print(f"索引条目：{result['indexed_regulation_count']}")
    print(f"最后检查：{result['last_checked_at']}")
    print("说明：这里只建立目录，不全量下载 regulation PDF；正文会在具体命中时按需抓取。")
    return 0


def _admin_search(
    admin_db_path: Path,
    query: str,
    title: str | None,
    limit: int,
    include_cached_text: bool,
    as_json: bool,
) -> int:
    rows = search_admin_code(
        query,
        title_number=title,
        include_cached_text=include_cached_text,
        db_path=admin_db_path,
        pdf_dir=_admin_pdf_dir(admin_db_path),
        limit=limit,
    )
    if as_json:
        print(json.dumps({"query": query, "results": rows}, ensure_ascii=False, indent=2))
        return 0 if rows else 2
    print(f"Administrative Code 搜索：{query}")
    if not rows:
        print("结果：未找到。可先运行 admin-refresh-index 或指定 --title 刷新对应 Title。")
        return 2
    for index, row in enumerate(rows, start=1):
        print()
        print(f"[{index}] #{row['regulation_index_id']} {row['citation']} — {row['regulation_title']}")
        print(f"官方条目：{row['official_url']}")
        if row.get("api_pdf_url"):
            print(f"官方 PDF/API：{row['api_pdf_url']}")
        print(f"状态：{row['status']} | 正文：{row['body_status']}")
        print(f"最后检查：{row['last_checked_at']}")
        cache = row.get("cache")
        if cache:
            print(f"缓存抓取：{cache['fetched_at']} | 过期：{cache['expires_at']}")
            print(f"缓存有效：{'是' if row.get('cache_fresh') else '否'}")
            print(f"版本 hash：{cache['content_hash']}")
        if row.get("fetch_error"):
            print(f"抓取错误：{row['fetch_error']}")
        if row.get("text_preview"):
            print(f"摘录：{row['text_preview']}...")
    print()
    print("提醒：如果只有索引命中但正文未抓取成功，只能说找到可能相关的官方条目，不能引用正文。")
    return 0


def _admin_fetch(admin_db_path: Path, regulation_index_id: int, force_refresh: bool, as_json: bool) -> int:
    result = fetch_admin_regulation(
        regulation_index_id,
        force_refresh=force_refresh,
        db_path=admin_db_path,
        pdf_dir=_admin_pdf_dir(admin_db_path),
    )
    ok = result.get("fetch_status") in {"cache_hit", "fetched"}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if ok else 2
    print(f"Administrative Code 抓取：#{regulation_index_id}")
    print(f"状态：{result.get('fetch_status')}")
    print(f"引用：{result.get('citation')}")
    print(f"官方条目：{result.get('official_url')}")
    if result.get("api_pdf_url"):
        print(f"官方 PDF/API：{result.get('api_pdf_url')}")
    if not ok:
        print(f"错误：{result.get('error_message')}")
        if result.get("cached_entry"):
            cache = result["cached_entry"]
            print(f"保留旧缓存：{cache['fetched_at']} | hash：{cache['content_hash']}")
        return 2
    cache = result.get("cache") or {}
    print(f"缓存抓取：{cache.get('fetched_at')} | 过期：{cache.get('expires_at')}")
    print(f"版本 hash：{cache.get('content_hash')}")
    return 0


def _admin_lookup(admin_db_path: Path, citation: str, as_json: bool) -> int:
    result = get_admin_regulation_by_citation(
        citation,
        db_path=admin_db_path,
        pdf_dir=_admin_pdf_dir(admin_db_path),
    )
    if as_json:
        print(json.dumps({"input": citation, "found": bool(result), "result": result}, ensure_ascii=False, indent=2))
        return 0 if result else 2
    print(f"Administrative Code 查询：{citation}")
    if not result:
        print("结果：未找到。请确认 citation 格式，例如 24 DE Admin. Code 3900。")
        return 2
    print(f"结果：#{result['regulation_index_id']} {result['citation']} — {result['regulation_title']}")
    print(f"官方条目：{result['official_url']}")
    if result.get("api_pdf_url"):
        print(f"官方 PDF/API：{result['api_pdf_url']}")
    cache = result.get("cache")
    if cache:
        print(f"缓存抓取：{cache['fetched_at']} | 过期：{cache['expires_at']}")
        print(f"版本 hash：{cache['content_hash']}")
    print(f"正文状态：{result['body_status']}")
    return 0


def _admin_freshness(admin_db_path: Path, regulation_index_id: int, as_json: bool) -> int:
    result = check_admin_regulation_freshness(regulation_index_id, db_path=admin_db_path)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("fresh") else 2
    print(f"Administrative Code 新鲜度：#{regulation_index_id}")
    print(f"状态：{result.get('status')}")
    if result.get("citation"):
        print(f"引用：{result['citation']}")
    if result.get("fetched_at"):
        print(f"缓存抓取：{result['fetched_at']} | 过期：{result.get('expires_at')}")
    print(f"说明：{result.get('message')}")
    return 0 if result.get("fresh") else 2


def _admin_pdf_dir(admin_db_path: Path) -> Path:
    return admin_db_path.parent / "pdf"


def _info(db: DelawareLawDatabase, as_json: bool) -> int:
    metadata = db.metadata()
    if as_json:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0
    for key, value in metadata.items():
        print(f"{key}: {value}")
    return 0


def _load_validation_text(text: str | None, file_path: str | None) -> str:
    if file_path:
        path = Path(file_path)
        if path.suffix.lower() == ".docx":
            return _read_docx_text(path)
        return path.read_text(encoding="utf-8")
    if text is None:
        return sys.stdin.read()
    return text


def _row_to_material(row, include_text: bool) -> dict[str, object]:
    material = {
        "citation": row["citation"],
        "heading": row["heading"],
        "material_type": row["material_type"],
        "source_file": row["source_file"],
        "source_url": row["source_url"],
        "data_version": row["data_version"],
        "start_line": row["start_line"],
    }
    if include_text:
        material["text"] = row["text"]
    else:
        material["preview"] = " ".join(row["text"].split())[:500]
    return material


def _row_to_chapter(row) -> dict[str, object]:
    return {
        "citation": row["citation"],
        "heading": row["heading"],
        "material_type": row["material_type"],
        "source_file": row["source_file"],
        "source_url": row["source_url"],
        "data_version": row["data_version"],
        "start_line": row["start_line"],
    }


def _read_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as docx:
            part_names = _docx_text_part_names(docx)
            if "word/document.xml" not in part_names:
                raise KeyError("word/document.xml")
            paragraphs: list[str] = []
            for part_name in part_names:
                paragraphs.extend(_paragraphs_from_docx_xml(docx.read(part_name)))
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Cannot read DOCX text from {path}") from exc

    return "\n".join(paragraphs)


def _docx_text_part_names(docx: zipfile.ZipFile) -> list[str]:
    names = set(docx.namelist())
    ordered: list[str] = []
    for part_name in [
        "word/document.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    ]:
        if part_name in names:
            ordered.append(part_name)

    ordered.extend(sorted(name for name in names if re.match(r"word/header\d+\.xml$", name)))
    ordered.extend(sorted(name for name in names if re.match(r"word/footer\d+\.xml$", name)))
    return ordered


def _paragraphs_from_docx_xml(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{ns['w']}}}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{{{ns['w']}}}tab":
                parts.append("\t")
            elif node.tag == f"{{{ns['w']}}}br":
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return paragraphs


def _print_disclaimer() -> None:
    print()
    print("提醒：本工具只做法律材料检索和引用校验，不提供法律意见；正式交付前仍需核对官方来源或律师复核。")


if __name__ == "__main__":
    raise SystemExit(main())
