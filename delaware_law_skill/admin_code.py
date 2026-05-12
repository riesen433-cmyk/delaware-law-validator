from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .config import (
    DELAWARE_REGULATIONS_API_URL,
    DELAWARE_REGULATIONS_HOME_URL,
    DEFAULT_ADMIN_CODE_DB_PATH,
    DEFAULT_ADMIN_CODE_PDF_DIR,
)


ADMIN_CODE_SOURCE_TYPE = "regulation_current"
ADMIN_CODE_JURISDICTION = "Delaware"
DEFAULT_CACHE_DAYS = 30
HTTP_TIMEOUT_SECONDS = 20
HTTP_RETRIES = 2
HTTP_RATE_LIMIT_SECONDS = 0.4
USER_AGENT = "delaware-law-skill/0.1 (+https://regulations.delaware.gov/AdminCode)"


class AdminCodeError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "error",
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.url = url


@dataclass
class HttpResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes


class AdminCodeHttpClient:
    def __init__(
        self,
        *,
        timeout: int = HTTP_TIMEOUT_SECONDS,
        retries: int = HTTP_RETRIES,
        rate_limit_seconds: float = HTTP_RATE_LIMIT_SECONDS,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.rate_limit_seconds = rate_limit_seconds
        self.user_agent = user_agent
        self._last_request_at = 0.0

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        expected: str | None = None,
    ) -> HttpResponse:
        body = None
        headers = {"User-Agent": self.user_agent, "Accept": expected or "*/*"}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        last_error: AdminCodeError | None = None
        for attempt in range(self.retries + 1):
            self._sleep_for_rate_limit()
            request = Request(url, data=body, headers=headers, method=method.upper())
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw_headers = {k.lower(): v for k, v in response.headers.items()}
                    return HttpResponse(
                        url=response.geturl(),
                        status_code=response.status,
                        headers=raw_headers,
                        body=response.read(),
                    )
            except HTTPError as exc:
                kind = _http_status_kind(exc.code)
                last_error = AdminCodeError(
                    f"{kind}: HTTP {exc.code} while fetching {url}",
                    kind=kind,
                    status_code=exc.code,
                    url=url,
                )
                if exc.code in {403, 404}:
                    break
            except TimeoutError as exc:
                last_error = AdminCodeError(f"timeout: {url}", kind="timeout", url=url)
            except URLError as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(reason, TimeoutError):
                    last_error = AdminCodeError(f"timeout: {url}", kind="timeout", url=url)
                else:
                    last_error = AdminCodeError(f"network_error: {reason}", kind="error", url=url)
            if attempt < self.retries:
                time.sleep(0.8 * (attempt + 1))
        raise last_error or AdminCodeError(f"request failed: {url}", url=url)

    def _sleep_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_at = time.monotonic()


def refresh_admin_code_index(
    *,
    db_path: Path = DEFAULT_ADMIN_CODE_DB_PATH,
    http_client: AdminCodeHttpClient | None = None,
) -> dict[str, Any]:
    client = http_client or AdminCodeHttpClient()
    conn = _connect(db_path)
    try:
        titles = _get_all_titles(client)
        refreshed: list[dict[str, Any]] = []
        for title in titles:
            title_number = str(title.get("titleNumber") or "").strip()
            if not title_number:
                continue
            refreshed.append(
                refresh_admin_code_title(
                    title_number,
                    db_path=db_path,
                    http_client=client,
                    _connection=conn,
                )
            )
        return {
            "status": "ok",
            "title_count": len(titles),
            "refreshed_title_count": len(refreshed),
            "indexed_regulation_count": sum(item["indexed_count"] for item in refreshed),
            "last_checked_at": _utc_now(),
        }
    finally:
        conn.close()


def refresh_admin_code_title(
    title_number: str | int,
    *,
    db_path: Path = DEFAULT_ADMIN_CODE_DB_PATH,
    http_client: AdminCodeHttpClient | None = None,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    title_text = _normalize_title_number(title_number)
    client = http_client or AdminCodeHttpClient()
    owns_connection = _connection is None
    conn = _connection or _connect(db_path)
    now = _utc_now()
    try:
        title_payload = _get_title_payload(client, title_text)
        title_url = f"/AdminCode/title{title_text}"
        entries = list(_iter_title_regulations(title_payload, title_text))
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            seen.add((entry["title_number"], entry["regulation_number"]))
            _upsert_index_row(conn, entry, now)
        _mark_missing_rows(conn, title_text, seen, now)
        conn.commit()
        return {
            "status": "ok",
            "title_number": title_text,
            "title_url": _absolute_site_url(title_url),
            "indexed_count": len(entries),
            "last_checked_at": now,
        }
    except AdminCodeError as exc:
        _mark_title_error(conn, title_text, now, str(exc))
        conn.commit()
        return {
            "status": "error",
            "title_number": title_text,
            "indexed_count": 0,
            "last_checked_at": now,
            "error_message": str(exc),
        }
    finally:
        if owns_connection:
            conn.close()


def search_admin_code(
    query: str,
    title_number: str | int | None = None,
    include_cached_text: bool = True,
    *,
    db_path: Path = DEFAULT_ADMIN_CODE_DB_PATH,
    pdf_dir: Path = DEFAULT_ADMIN_CODE_PDF_DIR,
    http_client: AdminCodeHttpClient | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        index_rows = _search_index_rows(conn, query, title_number, limit)
        results: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        now = _utc_now()
        for row in index_rows:
            row_id = int(row["id"])
            seen_ids.add(row_id)
            fetch_result: dict[str, Any] | None = None
            cache = _current_cache_row(conn, row_id)
            if include_cached_text and (not cache or not _is_cache_fresh(cache, now)):
                fetch_result = fetch_admin_regulation(
                    row_id,
                    db_path=db_path,
                    pdf_dir=pdf_dir,
                    http_client=http_client,
                    _connection=conn,
                )
                row = _get_index_row(conn, row_id) or row
                cache = _current_cache_row(conn, row_id)
            results.append(
                _result_from_rows(
                    row,
                    cache,
                    matched_on="index",
                    fetch_result=fetch_result,
                    query=query,
                )
            )

        if include_cached_text:
            for row, cache in _search_cached_text_rows(conn, query, title_number, limit):
                row_id = int(row["id"])
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                fetch_result = None
                if not _is_cache_fresh(cache, now):
                    fetch_result = fetch_admin_regulation(
                        row_id,
                        db_path=db_path,
                        pdf_dir=pdf_dir,
                        http_client=http_client,
                        _connection=conn,
                    )
                    row = _get_index_row(conn, row_id) or row
                    cache = _current_cache_row(conn, row_id) or cache
                results.append(
                    _result_from_rows(
                        row,
                        cache,
                        matched_on="cached_text",
                        fetch_result=fetch_result,
                        query=query,
                    )
                )
                if len(results) >= limit:
                    break
        return results[:limit]
    finally:
        conn.close()


def fetch_admin_regulation(
    regulation_index_id: int,
    force_refresh: bool = False,
    *,
    db_path: Path = DEFAULT_ADMIN_CODE_DB_PATH,
    pdf_dir: Path = DEFAULT_ADMIN_CODE_PDF_DIR,
    http_client: AdminCodeHttpClient | None = None,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    client = http_client or AdminCodeHttpClient()
    owns_connection = _connection is None
    conn = _connection or _connect(db_path)
    now = _utc_now()
    try:
        row = _get_index_row(conn, regulation_index_id)
        if row is None:
            raise AdminCodeError(f"regulation_index_id not found: {regulation_index_id}", kind="not_found")

        current_cache = _current_cache_row(conn, regulation_index_id)
        if current_cache and not force_refresh and _is_cache_fresh(current_cache, now):
            return _fetch_payload(row, current_cache, "cache_hit")

        try:
            api_pdf_url = row["api_pdf_url"]
            if not api_pdf_url or force_refresh:
                api_pdf_url = _resolve_pdf_url(conn, row, client, now)
                row = _get_index_row(conn, regulation_index_id) or row
            pdf_response = client.request("GET", api_pdf_url, expected="application/pdf")
            content_type = (pdf_response.headers.get("content-type") or "").lower()
            if "application/pdf" not in content_type:
                raise AdminCodeError(
                    f"non_pdf_content_type: {content_type or 'missing'}",
                    kind="non_pdf_content_type",
                    url=api_pdf_url,
                )
            pdf_bytes = pdf_response.body
            if not pdf_bytes.startswith(b"%PDF"):
                raise AdminCodeError("non_pdf_content_type: response body is not a PDF", kind="non_pdf_content_type")
            content_hash = hashlib.sha256(pdf_bytes).hexdigest()
            pdf_path = _store_pdf(pdf_dir, row, content_hash, pdf_bytes)
            extracted_text = _extract_pdf_text(pdf_path)
            cache_row = _save_successful_cache(
                conn,
                regulation_index_id,
                pdf_path,
                extracted_text,
                content_hash,
                now,
            )
            _update_index_after_fetch(conn, regulation_index_id, now, "active", content_hash, None)
            conn.commit()
            row = _get_index_row(conn, regulation_index_id) or row
            return _fetch_payload(row, cache_row, "fetched")
        except AdminCodeError as exc:
            _record_fetch_failure(conn, regulation_index_id, now, exc.kind, str(exc))
            status = "missing" if exc.kind == "not_found" else "error"
            _update_index_after_fetch(conn, regulation_index_id, now, status, row["content_hash"], str(exc))
            conn.commit()
            latest_cache = _current_cache_row(conn, regulation_index_id)
            row = _get_index_row(conn, regulation_index_id) or row
            return {
                "regulation_index_id": regulation_index_id,
                "fetch_status": exc.kind,
                "error_message": str(exc),
                "citation": row["admin_code_citation"],
                "official_url": row["source_page_url"],
                "api_pdf_url": row["api_pdf_url"],
                "last_checked_at": row["last_checked_at"],
                "cached_entry": _cache_to_dict(latest_cache) if latest_cache else None,
            }
    finally:
        if owns_connection:
            conn.close()


def get_admin_regulation_by_citation(
    citation: str,
    *,
    db_path: Path = DEFAULT_ADMIN_CODE_DB_PATH,
    pdf_dir: Path = DEFAULT_ADMIN_CODE_PDF_DIR,
    http_client: AdminCodeHttpClient | None = None,
) -> dict[str, Any] | None:
    parsed = parse_admin_code_citation(citation)
    if parsed is None:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM regulation_index
            WHERE title_number = ? AND regulation_number = ?
            ORDER BY id
            LIMIT 1
            """,
            (parsed["title_number"], parsed["regulation_number"]),
        ).fetchone()
        if row is None:
            refresh_admin_code_title(parsed["title_number"], db_path=db_path, http_client=http_client, _connection=conn)
            row = conn.execute(
                """
                SELECT * FROM regulation_index
                WHERE title_number = ? AND regulation_number = ?
                ORDER BY id
                LIMIT 1
                """,
                (parsed["title_number"], parsed["regulation_number"]),
            ).fetchone()
        if row is None:
            return None
        fetch_result = fetch_admin_regulation(
            int(row["id"]),
            db_path=db_path,
            pdf_dir=pdf_dir,
            http_client=http_client,
            _connection=conn,
        )
        row = _get_index_row(conn, int(row["id"])) or row
        cache = _current_cache_row(conn, int(row["id"]))
        result = _result_from_rows(row, cache, matched_on="citation", fetch_result=fetch_result)
        return result
    finally:
        conn.close()


def check_admin_regulation_freshness(
    regulation_index_id: int,
    *,
    db_path: Path = DEFAULT_ADMIN_CODE_DB_PATH,
) -> dict[str, Any]:
    conn = _connect(db_path)
    now = _utc_now()
    try:
        row = _get_index_row(conn, regulation_index_id)
        if row is None:
            return {
                "regulation_index_id": regulation_index_id,
                "fresh": False,
                "status": "not_found",
                "message": "No regulation index row exists for this id.",
            }
        cache = _current_cache_row(conn, regulation_index_id)
        latest_event = _latest_cache_event(conn, regulation_index_id)
        if cache is None:
            return {
                "regulation_index_id": regulation_index_id,
                "citation": row["admin_code_citation"],
                "official_url": row["source_page_url"],
                "api_pdf_url": row["api_pdf_url"],
                "fresh": False,
                "status": "not_cached",
                "last_checked_at": row["last_checked_at"],
                "message": "Index exists, but no regulation text has been successfully fetched.",
            }
        fresh = _is_cache_fresh(cache, now)
        refresh_failed = (
            not fresh
            and latest_event is not None
            and latest_event["fetch_status"] != "success"
            and latest_event["fetched_at"] >= cache["fetched_at"]
        )
        return {
            "regulation_index_id": regulation_index_id,
            "citation": row["admin_code_citation"],
            "official_url": row["source_page_url"],
            "api_pdf_url": row["api_pdf_url"],
            "fresh": fresh,
            "status": "fresh" if fresh else "stale",
            "refresh_failed": refresh_failed,
            "last_checked_at": row["last_checked_at"],
            "fetched_at": cache["fetched_at"],
            "expires_at": cache["expires_at"],
            "content_hash": cache["content_hash"],
            "message": _freshness_message(fresh, refresh_failed),
        }
    finally:
        conn.close()


def parse_admin_code_citation(citation: str) -> dict[str, str] | None:
    pattern = re.compile(
        r"\b(?P<title>\d{1,2})\s+(?:DE|Del\.?)\s+Admin\.?\s+Code\s+(?P<regulation>[A-Za-z0-9][A-Za-z0-9.-]*)",
        re.IGNORECASE,
    )
    match = pattern.search(citation)
    if not match:
        return None
    return {
        "title_number": str(int(match.group("title"))),
        "regulation_number": match.group("regulation"),
    }


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS regulation_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jurisdiction TEXT NOT NULL,
            source_type TEXT NOT NULL,
            title_number TEXT NOT NULL,
            regulation_number TEXT NOT NULL,
            regulation_title TEXT NOT NULL,
            admin_code_citation TEXT NOT NULL,
            source_page_url TEXT NOT NULL,
            api_pdf_url TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_checked_at TEXT NOT NULL,
            status TEXT NOT NULL,
            content_hash TEXT,
            raw_link_text TEXT NOT NULL,
            error_message TEXT,
            UNIQUE(title_number, regulation_number)
        );

        CREATE INDEX IF NOT EXISTS idx_regulation_index_title
            ON regulation_index(title_number);
        CREATE INDEX IF NOT EXISTS idx_regulation_index_citation
            ON regulation_index(admin_code_citation);

        CREATE TABLE IF NOT EXISTS regulation_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regulation_index_id INTEGER NOT NULL,
            pdf_storage_path TEXT,
            extracted_text TEXT,
            fetched_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            content_hash TEXT,
            source_format TEXT NOT NULL,
            fetch_status TEXT NOT NULL,
            error_message TEXT,
            is_current INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(regulation_index_id) REFERENCES regulation_index(id)
        );

        CREATE INDEX IF NOT EXISTS idx_regulation_cache_current
            ON regulation_cache(regulation_index_id, is_current, fetched_at);
        CREATE INDEX IF NOT EXISTS idx_regulation_cache_hash
            ON regulation_cache(regulation_index_id, content_hash);
        """
    )
    conn.commit()


def _get_all_titles(client: AdminCodeHttpClient) -> list[dict[str, Any]]:
    url = urljoin(DELAWARE_REGULATIONS_API_URL, "AdminCode/titles")
    response = client.request("GET", url, expected="application/json")
    return _decode_json_response(response, list, url)


def _get_title_payload(client: AdminCodeHttpClient, title_number: str) -> dict[str, Any]:
    url = urljoin(DELAWARE_REGULATIONS_API_URL, "AdminCode/title")
    response = client.request(
        "POST",
        url,
        json_body={"regulationUrl": f"/AdminCode/title{title_number}"},
        expected="application/json",
    )
    return _decode_json_response(response, dict, url)


def _get_regulation_payload(client: AdminCodeHttpClient, source_page_url: str) -> dict[str, Any]:
    url = urljoin(DELAWARE_REGULATIONS_API_URL, "AdminCode/regulation")
    path = _site_path(source_page_url)
    response = client.request(
        "POST",
        url,
        json_body={"regulationUrl": path},
        expected="application/json",
    )
    return _decode_json_response(response, dict, url)


def _decode_json_response(response: HttpResponse, expected_type: type, url: str) -> Any:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/json" not in content_type:
        raise AdminCodeError(f"unexpected_content_type: {content_type}", kind="non_json_content_type", url=url)
    try:
        data = json.loads(response.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AdminCodeError(f"json_parse_failed: {exc}", kind="parse_error", url=url) from exc
    if not isinstance(data, expected_type):
        raise AdminCodeError(f"unexpected_json_shape: expected {expected_type.__name__}", kind="parse_error", url=url)
    return data


def _iter_title_regulations(payload: dict[str, Any], title_number: str) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []

    def walk(units: list[dict[str, Any]] | None) -> None:
        for unit in units or []:
            public_url = unit.get("publicSiteRegulationUniqueUrl")
            is_regulation = unit.get("treeComponentTypeId") == 3 or bool(public_url)
            if is_regulation and public_url:
                regulation_number = _regulation_identifier(unit, public_url)
                if regulation_number:
                    regulation_title = _clean_regulation_title(unit, regulation_number)
                    raw_text = str(
                        unit.get("regulationDisplay")
                        or unit.get("regulationName")
                        or f"{regulation_number} {regulation_title}"
                    ).strip()
                    api_pdf_url = _extract_first_admin_code_api_url(unit)
                    entries.append(
                        {
                            "jurisdiction": ADMIN_CODE_JURISDICTION,
                            "source_type": ADMIN_CODE_SOURCE_TYPE,
                            "title_number": title_number,
                            "regulation_number": regulation_number,
                            "regulation_title": regulation_title,
                            "admin_code_citation": f"{title_number} DE Admin. Code {regulation_number}",
                            "source_page_url": _absolute_site_url(public_url),
                            "api_pdf_url": api_pdf_url,
                            "status": "active",
                            "raw_link_text": raw_text,
                        }
                    )
            walk(unit.get("units"))

    walk(payload.get("regulatoryUnits"))
    if not entries:
        raise AdminCodeError("parse_error: no regulation entries found on title payload", kind="parse_error")
    return entries


def _regulation_identifier(unit: dict[str, Any], public_url: str) -> str:
    raw_number = str(unit.get("regulationNumber") or "").strip()
    if raw_number:
        return raw_number
    path_part = _site_path(public_url).rstrip("/").split("/")[-1]
    return path_part.strip()


def _clean_regulation_title(unit: dict[str, Any], regulation_number: str) -> str:
    title = str(unit.get("regulationName") or unit.get("regulationDisplay") or "").strip()
    title = re.sub(rf"^\s*{re.escape(regulation_number)}\s+", "", title).strip()
    return title or regulation_number


def _extract_first_admin_code_api_url(value: Any) -> str | None:
    text = json.dumps(value, ensure_ascii=False)
    match = re.search(r"https://regulations\.delaware\.gov/api/AdminCode/[A-Za-z0-9/_-]+", text)
    if match:
        return match.group(0)
    match = re.search(r"/api/AdminCode/[A-Za-z0-9/_-]+", text)
    if match:
        return _absolute_site_url(match.group(0))
    return None


def _upsert_index_row(conn: sqlite3.Connection, entry: dict[str, str | None], now: str) -> None:
    existing = conn.execute(
        """
        SELECT id, first_seen_at, api_pdf_url, content_hash
        FROM regulation_index
        WHERE title_number = ? AND regulation_number = ?
        """,
        (entry["title_number"], entry["regulation_number"]),
    ).fetchone()
    api_pdf_url = entry["api_pdf_url"] or (existing["api_pdf_url"] if existing else None)
    content_hash = existing["content_hash"] if existing else None
    first_seen_at = existing["first_seen_at"] if existing else now
    conn.execute(
        """
        INSERT INTO regulation_index (
            jurisdiction, source_type, title_number, regulation_number, regulation_title,
            admin_code_citation, source_page_url, api_pdf_url, first_seen_at, last_seen_at,
            last_checked_at, status, content_hash, raw_link_text, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(title_number, regulation_number) DO UPDATE SET
            jurisdiction = excluded.jurisdiction,
            source_type = excluded.source_type,
            regulation_title = excluded.regulation_title,
            admin_code_citation = excluded.admin_code_citation,
            source_page_url = excluded.source_page_url,
            api_pdf_url = COALESCE(excluded.api_pdf_url, regulation_index.api_pdf_url),
            last_seen_at = excluded.last_seen_at,
            last_checked_at = excluded.last_checked_at,
            status = excluded.status,
            raw_link_text = excluded.raw_link_text,
            error_message = NULL
        """,
        (
            entry["jurisdiction"],
            entry["source_type"],
            entry["title_number"],
            entry["regulation_number"],
            entry["regulation_title"],
            entry["admin_code_citation"],
            entry["source_page_url"],
            api_pdf_url,
            first_seen_at,
            now,
            now,
            entry["status"],
            content_hash,
            entry["raw_link_text"],
            None,
        ),
    )


def _mark_missing_rows(
    conn: sqlite3.Connection,
    title_number: str,
    seen: set[tuple[str, str]],
    now: str,
) -> None:
    existing = conn.execute(
        "SELECT title_number, regulation_number FROM regulation_index WHERE title_number = ?",
        (title_number,),
    ).fetchall()
    for row in existing:
        key = (row["title_number"], row["regulation_number"])
        if key not in seen:
            conn.execute(
                """
                UPDATE regulation_index
                SET status = 'missing', last_checked_at = ?, error_message = ?
                WHERE title_number = ? AND regulation_number = ?
                """,
                (now, "Entry was not present in the latest official title index response.", key[0], key[1]),
            )


def _mark_title_error(conn: sqlite3.Connection, title_number: str, now: str, error_message: str) -> None:
    conn.execute(
        """
        UPDATE regulation_index
        SET status = 'error', last_checked_at = ?, error_message = ?
        WHERE title_number = ?
        """,
        (now, error_message, title_number),
    )


def _search_index_rows(
    conn: sqlite3.Connection,
    query: str,
    title_number: str | int | None,
    limit: int,
) -> list[sqlite3.Row]:
    parsed = parse_admin_code_citation(query)
    title_clause = "AND title_number = ?" if title_number is not None else ""
    return conn.execute(
        f"""
        SELECT * FROM regulation_index
        WHERE (
            (title_number = ? AND regulation_number = ?)
            OR regulation_title LIKE ?
            OR regulation_number LIKE ?
            OR admin_code_citation LIKE ?
            OR raw_link_text LIKE ?
        )
        {title_clause}
        ORDER BY
            CASE WHEN admin_code_citation LIKE ? THEN 0 ELSE 1 END,
            CAST(title_number AS INTEGER),
            regulation_number
        LIMIT ?
        """,
        _search_index_params(parsed, query, title_number, limit),
    ).fetchall()


def _search_index_params(
    parsed: dict[str, str] | None,
    query: str,
    title_number: str | int | None,
    limit: int,
) -> list[Any]:
    like = f"%{query.strip()}%"
    params: list[Any] = []
    if parsed:
        params.extend([parsed["title_number"], parsed["regulation_number"]])
    else:
        params.extend(["__no_title__", "__no_regulation__"])
    params.extend([like, like, like, like])
    if title_number is not None:
        params.append(_normalize_title_number(title_number))
    params.extend([like, limit])
    return params


def _search_cached_text_rows(
    conn: sqlite3.Connection,
    query: str,
    title_number: str | int | None,
    limit: int,
) -> list[tuple[sqlite3.Row, sqlite3.Row]]:
    params: list[Any] = [f"%{query.strip()}%"]
    title_clause = ""
    if title_number is not None:
        title_clause = "AND i.title_number = ?"
        params.append(_normalize_title_number(title_number))
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT i.*, c.id AS cache_id
        FROM regulation_index i
        JOIN regulation_cache c ON c.regulation_index_id = i.id
        WHERE c.is_current = 1
          AND c.fetch_status = 'success'
          AND c.extracted_text LIKE ?
          {title_clause}
        ORDER BY c.fetched_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    output = []
    for row in rows:
        index_row = _get_index_row(conn, int(row["id"]))
        cache_row = _current_cache_row(conn, int(row["id"]))
        if index_row and cache_row:
            output.append((index_row, cache_row))
    return output


def _get_index_row(conn: sqlite3.Connection, regulation_index_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM regulation_index WHERE id = ?", (regulation_index_id,)).fetchone()


def _current_cache_row(conn: sqlite3.Connection, regulation_index_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM regulation_cache
        WHERE regulation_index_id = ?
          AND is_current = 1
          AND fetch_status = 'success'
        ORDER BY fetched_at DESC, id DESC
        LIMIT 1
        """,
        (regulation_index_id,),
    ).fetchone()


def _latest_cache_event(conn: sqlite3.Connection, regulation_index_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM regulation_cache
        WHERE regulation_index_id = ?
        ORDER BY fetched_at DESC, id DESC
        LIMIT 1
        """,
        (regulation_index_id,),
    ).fetchone()


def _resolve_pdf_url(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    client: AdminCodeHttpClient,
    now: str,
) -> str:
    payload = _get_regulation_payload(client, row["source_page_url"])
    pdf_id = str(payload.get("pdfId") or "").strip()
    if not pdf_id:
        raise AdminCodeError("metadata_missing_pdf_id: official regulation response did not include pdfId", kind="parse_error")
    title_identifier = f"title{row['title_number']}"
    regulation_identifier = row["regulation_number"] or _site_path(row["source_page_url"]).rstrip("/").split("/")[-1]
    api_pdf_url = urljoin(
        DELAWARE_REGULATIONS_API_URL,
        f"AdminCode/{title_identifier}/{regulation_identifier}/{pdf_id}",
    )
    regulation_name = str(payload.get("regulationName") or "").strip()
    if regulation_name:
        cleaned_title = re.sub(rf"^\s*{re.escape(row['regulation_number'])}\s+", "", regulation_name).strip()
        conn.execute(
            """
            UPDATE regulation_index
            SET api_pdf_url = ?,
                regulation_title = ?,
                last_checked_at = ?,
                status = 'active',
                error_message = NULL
            WHERE id = ?
            """,
            (api_pdf_url, cleaned_title or row["regulation_title"], now, row["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE regulation_index
            SET api_pdf_url = ?, last_checked_at = ?, status = 'active', error_message = NULL
            WHERE id = ?
            """,
            (api_pdf_url, now, row["id"]),
        )
    return api_pdf_url


def _store_pdf(pdf_dir: Path, row: sqlite3.Row, content_hash: str, pdf_bytes: bytes) -> Path:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    safe_regulation = re.sub(r"[^A-Za-z0-9.-]+", "_", row["regulation_number"])
    pdf_path = pdf_dir / f"title{row['title_number']}_{safe_regulation}_{content_hash[:16]}.pdf"
    if not pdf_path.exists():
        pdf_path.write_bytes(pdf_bytes)
    return pdf_path


def _extract_pdf_text(pdf_path: Path) -> str:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            result = subprocess.run(
                [pdftotext, "-layout", str(pdf_path), "-"],
                text=True,
                capture_output=True,
                check=True,
                timeout=60,
            )
            text = result.stdout.strip()
            if text:
                return text
        except (subprocess.SubprocessError, OSError) as exc:
            raise AdminCodeError(f"pdf_extract_failed: {exc}", kind="pdf_extract_failed") from exc
    try:
        import pypdf  # type: ignore[import-not-found]

        reader = pypdf.PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as exc:  # pragma: no cover - dependency-specific fallback
        raise AdminCodeError(f"pdf_extract_failed: {exc}", kind="pdf_extract_failed") from exc
    try:
        import PyPDF2  # type: ignore[import-not-found]

        reader = PyPDF2.PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if text:
            return text
    except ImportError as exc:
        raise AdminCodeError(
            "pdf_extract_failed: pdftotext, pypdf, and PyPDF2 are unavailable",
            kind="pdf_extract_failed",
        ) from exc
    except Exception as exc:  # pragma: no cover - dependency-specific fallback
        raise AdminCodeError(f"pdf_extract_failed: {exc}", kind="pdf_extract_failed") from exc
    raise AdminCodeError("pdf_extract_failed: no text extracted", kind="pdf_extract_failed")


def _save_successful_cache(
    conn: sqlite3.Connection,
    regulation_index_id: int,
    pdf_path: Path,
    extracted_text: str,
    content_hash: str,
    now: str,
) -> sqlite3.Row:
    expires_at = _add_days(now, DEFAULT_CACHE_DAYS)
    current = _current_cache_row(conn, regulation_index_id)
    if current and current["content_hash"] == content_hash:
        conn.execute(
            """
            UPDATE regulation_cache
            SET pdf_storage_path = ?,
                extracted_text = ?,
                fetched_at = ?,
                expires_at = ?,
                error_message = NULL,
                fetch_status = 'success'
            WHERE id = ?
            """,
            (str(pdf_path), extracted_text, now, expires_at, current["id"]),
        )
        return conn.execute("SELECT * FROM regulation_cache WHERE id = ?", (current["id"],)).fetchone()

    conn.execute(
        """
        UPDATE regulation_cache
        SET is_current = 0
        WHERE regulation_index_id = ? AND fetch_status = 'success'
        """,
        (regulation_index_id,),
    )
    cursor = conn.execute(
        """
        INSERT INTO regulation_cache (
            regulation_index_id, pdf_storage_path, extracted_text, fetched_at, expires_at,
            content_hash, source_format, fetch_status, error_message, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, 'pdf', 'success', NULL, 1)
        """,
        (regulation_index_id, str(pdf_path), extracted_text, now, expires_at, content_hash),
    )
    return conn.execute("SELECT * FROM regulation_cache WHERE id = ?", (cursor.lastrowid,)).fetchone()


def _record_fetch_failure(
    conn: sqlite3.Connection,
    regulation_index_id: int,
    now: str,
    fetch_status: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO regulation_cache (
            regulation_index_id, pdf_storage_path, extracted_text, fetched_at, expires_at,
            content_hash, source_format, fetch_status, error_message, is_current
        ) VALUES (?, NULL, NULL, ?, ?, NULL, 'pdf', ?, ?, 0)
        """,
        (regulation_index_id, now, now, fetch_status, error_message),
    )


def _update_index_after_fetch(
    conn: sqlite3.Connection,
    regulation_index_id: int,
    now: str,
    status: str,
    content_hash: str | None,
    error_message: str | None,
) -> None:
    conn.execute(
        """
        UPDATE regulation_index
        SET last_checked_at = ?,
            status = ?,
            content_hash = COALESCE(?, content_hash),
            error_message = ?
        WHERE id = ?
        """,
        (now, status, content_hash, error_message, regulation_index_id),
    )


def _result_from_rows(
    row: sqlite3.Row,
    cache: sqlite3.Row | None,
    *,
    matched_on: str,
    fetch_result: dict[str, Any] | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    result = _index_to_dict(row)
    result["matched_on"] = matched_on
    result["official_url"] = row["source_page_url"]
    result["cache"] = _cache_to_dict(cache) if cache else None
    result["body_status"] = "available" if cache else "index_only"
    result["cache_fresh"] = _is_cache_fresh(cache, _utc_now()) if cache else False
    if cache and query:
        result["text_preview"] = _text_preview(cache["extracted_text"], query)
    if fetch_result and fetch_result.get("fetch_status") not in {"cache_hit", "fetched"}:
        result["body_status"] = "fetch_failed"
        result["fetch_error"] = fetch_result.get("error_message")
    return result


def _fetch_payload(row: sqlite3.Row, cache: sqlite3.Row, status: str) -> dict[str, Any]:
    return {
        "regulation_index_id": row["id"],
        "fetch_status": status,
        "citation": row["admin_code_citation"],
        "official_url": row["source_page_url"],
        "api_pdf_url": row["api_pdf_url"],
        "last_checked_at": row["last_checked_at"],
        "cache": _cache_to_dict(cache),
    }


def _index_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "regulation_index_id": row["id"],
        "jurisdiction": row["jurisdiction"],
        "source_type": row["source_type"],
        "title_number": row["title_number"],
        "regulation_number": row["regulation_number"],
        "regulation_title": row["regulation_title"],
        "admin_code_citation": row["admin_code_citation"],
        "citation": row["admin_code_citation"],
        "source_page_url": row["source_page_url"],
        "official_url": row["source_page_url"],
        "api_pdf_url": row["api_pdf_url"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "last_checked_at": row["last_checked_at"],
        "status": row["status"],
        "content_hash": row["content_hash"],
        "raw_link_text": row["raw_link_text"],
        "error_message": row["error_message"],
    }


def _cache_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "regulation_index_id": row["regulation_index_id"],
        "pdf_storage_path": row["pdf_storage_path"],
        "extracted_text": row["extracted_text"],
        "fetched_at": row["fetched_at"],
        "expires_at": row["expires_at"],
        "content_hash": row["content_hash"],
        "source_format": row["source_format"],
        "fetch_status": row["fetch_status"],
        "error_message": row["error_message"],
        "is_current": bool(row["is_current"]),
    }


def _text_preview(text: str, query: str, width: int = 420) -> str:
    compact = " ".join((text or "").split())
    index = compact.lower().find(query.lower().strip())
    if index < 0:
        return compact[:width]
    start = max(0, index - width // 3)
    return compact[start : start + width]


def _is_cache_fresh(cache: sqlite3.Row, now: str) -> bool:
    return cache["expires_at"] > now


def _freshness_message(fresh: bool, refresh_failed: bool) -> str:
    if fresh:
        return "Cached regulation text is within the 30-day freshness window."
    if refresh_failed:
        return "Cached regulation text is stale and the latest refresh failed; cannot confirm it is the latest official version."
    return "Cached regulation text is stale and should be refreshed before relying on it as current."


def _http_status_kind(status_code: int) -> str:
    if status_code == 404:
        return "not_found"
    if status_code == 403:
        return "forbidden"
    return "http_error"


def _normalize_title_number(title_number: str | int) -> str:
    text = str(title_number).strip().lower().removeprefix("title").strip()
    if not text.isdigit():
        raise AdminCodeError(f"invalid_title_number: {title_number}", kind="input_error")
    return str(int(text))


def _absolute_site_url(url: str) -> str:
    return urljoin(DELAWARE_REGULATIONS_HOME_URL, url)


def _site_path(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme:
        return parsed.path
    return url


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _add_days(timestamp: str, days: int) -> str:
    value = datetime.fromisoformat(timestamp)
    return (value + timedelta(days=days)).replace(microsecond=0).isoformat()
