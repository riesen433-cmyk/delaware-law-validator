from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from delaware_law_skill.admin_code import (
    AdminCodeError,
    HttpResponse,
    check_admin_regulation_freshness,
    fetch_admin_regulation,
    refresh_admin_code_title,
    search_admin_code,
)


class FakeAdminCodeClient:
    def __init__(self, *, title_payload=None, pdf_bodies=None, fail_pdf: AdminCodeError | None = None) -> None:
        self.title_payload = title_payload or _title_payload(api_link=None)
        self.pdf_bodies = list(pdf_bodies or [b"%PDF-1.7\nfake pdf v1\n"])
        self.fail_pdf = fail_pdf
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, *, json_body=None, expected=None) -> HttpResponse:
        self.calls.append((method.upper(), url))
        if url.endswith("/api/AdminCode/title"):
            return _json_response(url, self.title_payload)
        if url.endswith("/api/AdminCode/regulation"):
            return _json_response(
                url,
                {
                    "titleId": 1272,
                    "titleName": "Title 24 Regulated Professions and Occupations",
                    "regulationName": "3900 Board of Social Work Examiners",
                    "pdfId": "11111111-2222-3333-4444-555555555555",
                    "titleUrl": "/AdminCode/title24",
                    "htmlBody": "<html><body>official body metadata</body></html>",
                },
            )
        if "/api/AdminCode/title24/3900/" in url:
            if self.fail_pdf:
                raise self.fail_pdf
            body = self.pdf_bodies.pop(0) if len(self.pdf_bodies) > 1 else self.pdf_bodies[0]
            return HttpResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/pdf"},
                body=body,
            )
        raise AssertionError(f"Unexpected request: {method} {url}")


class DelawareAdminCodeTests(unittest.TestCase):
    def test_title_refresh_parses_api_pdf_links_from_official_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            client = FakeAdminCodeClient(
                title_payload=_title_payload(api_link="/api/AdminCode/title24/3900/from-title-page")
            )

            result = refresh_admin_code_title("24", db_path=db_path, http_client=client)

            self.assertEqual(result["status"], "ok")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT * FROM regulation_index WHERE regulation_number = '3900'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[8], "https://regulations.delaware.gov/api/AdminCode/title24/3900/from-title-page")

    def test_lazy_fetch_pdf_content_type_and_extracts_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            pdf_dir = Path(temp_dir) / "pdf"
            client = FakeAdminCodeClient()
            refresh_admin_code_title("24", db_path=db_path, http_client=client)

            with patch("delaware_law_skill.admin_code._extract_pdf_text", return_value="Board of Social Work text"):
                result = fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)

            self.assertEqual(result["fetch_status"], "fetched")
            self.assertIn("/api/AdminCode/title24/3900/11111111-2222-3333-4444-555555555555", result["api_pdf_url"])
            self.assertEqual(result["cache"]["extracted_text"], "Board of Social Work text")
            self.assertTrue(Path(result["cache"]["pdf_storage_path"]).exists())
            self.assertIn(("POST", "https://regulations.delaware.gov/api/AdminCode/regulation"), client.calls)

    def test_cache_hit_does_not_redownload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            pdf_dir = Path(temp_dir) / "pdf"
            client = FakeAdminCodeClient()
            refresh_admin_code_title("24", db_path=db_path, http_client=client)
            with patch("delaware_law_skill.admin_code._extract_pdf_text", return_value="cached text"):
                fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)
            client.calls.clear()

            result = fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)

            self.assertEqual(result["fetch_status"], "cache_hit")
            self.assertEqual(client.calls, [])

    def test_expired_cache_refreshes_and_keeps_old_version_on_hash_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            pdf_dir = Path(temp_dir) / "pdf"
            client = FakeAdminCodeClient(pdf_bodies=[b"%PDF-1.7\nv1\n", b"%PDF-1.7\nv2\n"])
            refresh_admin_code_title("24", db_path=db_path, http_client=client)
            with patch("delaware_law_skill.admin_code._extract_pdf_text", side_effect=["text v1", "text v2"]):
                first = fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)
                _expire_current_cache(db_path)
                second = fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)

            self.assertNotEqual(first["cache"]["content_hash"], second["cache"]["content_hash"])
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT fetch_status, is_current, content_hash FROM regulation_cache ORDER BY id"
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][1], 0)
            self.assertEqual(rows[1][1], 1)

    def test_failed_refresh_keeps_old_cache_and_marks_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            pdf_dir = Path(temp_dir) / "pdf"
            client = FakeAdminCodeClient()
            refresh_admin_code_title("24", db_path=db_path, http_client=client)
            with patch("delaware_law_skill.admin_code._extract_pdf_text", return_value="old official text"):
                fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)
            _expire_current_cache(db_path)
            client.fail_pdf = AdminCodeError("not_found: HTTP 404", kind="not_found", status_code=404)

            result = fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)
            freshness = check_admin_regulation_freshness(1, db_path=db_path)

            self.assertEqual(result["fetch_status"], "not_found")
            self.assertIsNotNone(result["cached_entry"])
            self.assertFalse(freshness["fresh"])
            self.assertTrue(freshness["refresh_failed"])
            with sqlite3.connect(db_path) as conn:
                current_success = conn.execute(
                    "SELECT COUNT(*) FROM regulation_cache WHERE fetch_status = 'success' AND is_current = 1"
                ).fetchone()[0]
                failures = conn.execute(
                    "SELECT COUNT(*) FROM regulation_cache WHERE fetch_status = 'not_found' AND is_current = 0"
                ).fetchone()[0]
            self.assertEqual(current_success, 1)
            self.assertEqual(failures, 1)

    def test_search_fetches_index_hit_and_returns_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            client = FakeAdminCodeClient()
            refresh_admin_code_title("24", db_path=db_path, http_client=client)

            with patch("delaware_law_skill.admin_code._extract_pdf_text", return_value="Social Work continuing education"):
                results = search_admin_code(
                    "Social Work",
                    title_number=24,
                    db_path=db_path,
                    pdf_dir=Path(temp_dir) / "pdf",
                    http_client=client,
                )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["citation"], "24 DE Admin. Code 3900")
            self.assertEqual(results[0]["body_status"], "available")
            self.assertIn("official_url", results[0])
            self.assertIn("/api/AdminCode/title24/3900/", results[0]["api_pdf_url"])
            self.assertEqual(results[0]["cache"]["source_format"], "pdf")

    def test_search_refreshes_expired_cache_before_returning_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            pdf_dir = Path(temp_dir) / "pdf"
            client = FakeAdminCodeClient(pdf_bodies=[b"%PDF-1.7\nold\n", b"%PDF-1.7\nnew\n"])
            refresh_admin_code_title("24", db_path=db_path, http_client=client)
            with patch("delaware_law_skill.admin_code._extract_pdf_text", side_effect=["old text", "new text"]):
                old = fetch_admin_regulation(1, db_path=db_path, pdf_dir=pdf_dir, http_client=client)
                _expire_current_cache(db_path)
                rows = search_admin_code(
                    "24 DE Admin. Code 3900",
                    db_path=db_path,
                    pdf_dir=pdf_dir,
                    http_client=client,
                )

            self.assertEqual(rows[0]["body_status"], "available")
            self.assertTrue(rows[0]["cache_fresh"])
            self.assertNotEqual(old["cache"]["content_hash"], rows[0]["cache"]["content_hash"])

    @unittest.skipUnless(
        os.environ.get("DELAWARE_ADMIN_CODE_LIVE_TESTS") == "1",
        "Set DELAWARE_ADMIN_CODE_LIVE_TESTS=1 to run the official-site integration test.",
    )
    def test_live_title24_lazy_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite"
            pdf_dir = Path(temp_dir) / "pdf"
            result = refresh_admin_code_title("24", db_path=db_path)
            self.assertGreater(result["indexed_count"], 20)
            rows = search_admin_code(
                "24 DE Admin. Code 3900",
                title_number=24,
                db_path=db_path,
                pdf_dir=pdf_dir,
                limit=1,
            )
            self.assertEqual(len(rows), 1)
            self.assertIn("/api/AdminCode/title24/3900/", rows[0]["api_pdf_url"])
            self.assertEqual(rows[0]["cache"]["source_format"], "pdf")
            self.assertIn("Board of Social Work", rows[0]["cache"]["extracted_text"])


def _title_payload(api_link: str | None) -> dict[str, object]:
    unit = {
        "regulationId": 1296,
        "treeComponentTypeId": 3,
        "hierarchy": "/18/49/1/38/",
        "regulationNumber": "3900",
        "regulationName": "Board of Social Work Examiners",
        "regulationDisplay": "3900 Board of Social Work Examiners",
        "isRepealed": False,
        "isLinkUnit": False,
        "publicSiteRegulationUniqueUrl": "/AdminCode/title24/3900",
        "units": [],
        "expanded": False,
        "hasHtml": True,
    }
    if api_link:
        unit["officialPdfLink"] = api_link
    return {
        "regulationId": 1272,
        "regulationName": "Title 24 Regulated Professions and Occupations",
        "titleNumber": None,
        "publicSiteRegulationUniqueUrl": None,
        "regulatoryUnits": [
            {
                "regulationId": 376095,
                "treeComponentTypeId": 2,
                "regulationName": "Department of State",
                "publicSiteRegulationUniqueUrl": None,
                "units": [unit],
            }
        ],
    }


def _json_response(url: str, payload: object) -> HttpResponse:
    return HttpResponse(
        url=url,
        status_code=200,
        headers={"content-type": "application/json; charset=utf-8"},
        body=json.dumps(payload).encode("utf-8"),
    )


def _expire_current_cache(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE regulation_cache
            SET expires_at = '2000-01-01T00:00:00+00:00'
            WHERE is_current = 1
            """
        )


if __name__ == "__main__":
    unittest.main()
