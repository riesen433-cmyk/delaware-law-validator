from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from delaware_law_skill.parser import parse_source_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-m", "delaware_law_skill.cli"]


class DelawareLawCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> str:
        result = subprocess.run(
            [*CLI, *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    def run_cli_raw(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*CLI, *args],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_lookup_17_407(self) -> None:
        output = self.run_cli("lookup", "6 Del. C. § 17-407")
        self.assertIn("Reliance on reports and information", output)
        self.assertIn("delaware-law-data-v1.0.0", output)

    def test_parser_extracts_title_current_through(self) -> None:
        source, _, _ = parse_source_file(PROJECT_ROOT / "data" / "raw_md" / "title6.md", "test-version")
        self.assertEqual(source.current_through, "April 28, 2026 / 85 Del. Laws, c. 251")

    def test_lookup_17_607(self) -> None:
        output = self.run_cli("lookup", "6 Del. C. § 17-607")
        self.assertIn("Limitations on distribution", output)

    def test_lookup_8_262(self) -> None:
        output = self.run_cli("lookup", "8 Del. C. § 262")
        self.assertIn("Appraisal rights", output)

    def test_lookup_section_with_space_after_symbol(self) -> None:
        output = self.run_cli("lookup", "§ 17-407")
        self.assertIn("Reliance on reports and information", output)

    def test_lookup_chapter_12c(self) -> None:
        output = self.run_cli("lookup", "Title 6, Chapter 12C")
        self.assertIn("Online and Personal Privacy Protection", output)

    def test_lookup_court_of_chancery_rule(self) -> None:
        output = self.run_cli("lookup", "Court of Chancery Rule 12(b)(6)")
        self.assertIn("Del. Ch. Ct. R. 12", output)
        self.assertIn("failure to state a claim", output)

    def test_lookup_delaware_rule_of_evidence(self) -> None:
        output = self.run_cli("lookup", "D.R.E. 403")
        self.assertIn("D.R.E. 403", output)
        self.assertIn("Excluding Relevant Evidence", output)

    def test_lookup_chapter_abbreviation(self) -> None:
        output = self.run_cli("lookup", "Title 26, Ch. 8")
        self.assertIn("Underground Utility Damage Prevention and Safety", output)

    def test_validate_wrong_reliance_section(self) -> None:
        output = self.run_cli(
            "validate",
            "The GP may rely on professional opinions as permitted by Section 17-406 of the Delaware Act.",
        )
        self.assertIn("主题可能不匹配", output)
        self.assertIn("6 Del. C. § 17-407", output)

    def test_validate_17_607_b_asset_ratio(self) -> None:
        output = self.run_cli(
            "validate",
            "Asset-to-Liability Ratio — §17-607(b): assets exceed liabilities after the distribution.",
        )
        self.assertIn("不是资产负债比率测试", output)
        self.assertIn("6 Del. C. § 17-607(a)", output)

    def test_search_limited_partnership_distribution(self) -> None:
        output = self.run_cli("search", "limited partnership distribution", "-n", "5")
        self.assertIn("6 Del. C. § 17-", output)
        self.assertIn("distribution", output.lower())

    def test_search_warranty_disclaimer_maps_to_article_2(self) -> None:
        output = self.run_cli("search", "warranty disclaimer", "-n", "3")
        self.assertIn("6 Del. C. § 2-316", output)
        self.assertIn("Exclusion or modification of warranties", output)

    def test_search_court_rule_topic_maps_to_rule_set(self) -> None:
        output = self.run_cli("search", "chancery failure to state a claim", "-n", "3")
        self.assertIn("Del. Ch. Ct. R. 12", output)

    def test_search_evidence_topic_maps_to_dre_403(self) -> None:
        output = self.run_cli("search", "probative value unfair prejudice", "-n", "3")
        self.assertIn("D.R.E. 403", output)

    def test_search_chapter_12c(self) -> None:
        output = self.run_cli("search", "Title 6, Chapter 12C", "-n", "5")
        self.assertIn("6 Del. C. § 1205C", output)
        self.assertIn("privacy policy", output.lower())

    def test_validate_court_rules_are_covered(self) -> None:
        output = self.run_cli("validate", "Court of Chancery Rule 12(b)(6), D.R.E. 403, and Supreme Court Rule 26 apply.")
        self.assertIn("识别到 court rule 引用数量：3", output)
        self.assertIn("Del. Ch. Ct. R. 12", output)
        self.assertIn("D.R.E. 403", output)
        self.assertIn("Del. Supr. Ct. R. 26", output)
        self.assertNotIn("暂不覆盖", output)

    def test_validate_uncovered_opinions(self) -> None:
        output = self.run_cli("validate", "A Del. Ch. opinion and case law may apply.")
        self.assertIn("暂不覆盖", output)

    def test_validate_does_not_verify_us_code_as_delaware(self) -> None:
        output = self.run_cli("validate", "15 U.S.C. § 7001 is a federal citation.")
        self.assertIn("联邦法律", output)
        self.assertNotIn("10 Del. C. § 7001", output)

    def test_validate_chapter_reference(self) -> None:
        output = self.run_cli("validate", "Title 6, Chapter 12C or Title 6, Chapter 12D may apply.")
        self.assertIn("Online and Personal Privacy Protection", output)
        self.assertIn("Delaware Personal Data Privacy Act", output)
        self.assertNotIn("没有找到该 Chapter", output)

    def test_validate_broad_title_reference(self) -> None:
        output = self.run_cli("validate", "The parties shall evaluate Title 12 of the Delaware Code.")
        self.assertIn("整部 Title 引用过宽", output)

    def test_validate_not_found_is_database_miss(self) -> None:
        output = self.run_cli("validate", "The agreement cites 6 Del. C. § 99-999.")
        self.assertIn("本地数据库未检出", output)
        self.assertIn("不得据此认定该条文不存在", output)

    def test_validate_article_2_perfection_mismatch(self) -> None:
        output = self.run_cli("validate", "Article 2 governs perfection of a security interest under the UCC.")
        self.assertIn("主题可能不匹配", output)
        self.assertIn("UCC Article 9", output)
        self.assertIn("6 Del. C. § 9-308", output)

    def test_validate_ucc_article_9_perfection(self) -> None:
        output = self.run_cli("validate", "UCC Article 9 governs perfection of a security interest.")
        self.assertIn("识别到 UCC Article 9", output)
        self.assertIn("6 Del. C. § 9-501", output)

    def test_validate_section_9_501_infers_title_6(self) -> None:
        output = self.run_cli("validate", "The filing office is § 9-501 under Delaware UCC Article 9.")
        self.assertIn("6 Del. C. § 9-501", output)
        self.assertIn("Filing office", output)

    def test_validate_ignores_document_section_numbers(self) -> None:
        output = self.run_cli("validate", "Section 1. Corporate Authorization. Section 17-406 may apply.")
        self.assertIn("Section 17-406", output)
        self.assertNotIn("Del. Const. ARTICLE I", output)

    def test_validate_docx_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "sample.docx"
            _write_minimal_docx(
                docx_path,
                "Professional reliance is governed by 6 Del. C. § 17-406. Title 6, Chapter 12C may apply.",
            )
            output = self.run_cli("validate", "--file", str(docx_path))
        self.assertIn("6 Del. C. § 17-407", output)
        self.assertIn("Online and Personal Privacy Protection", output)

    def test_validate_docx_reads_notes_comments_headers_and_footers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "sample.docx"
            _write_minimal_docx(
                docx_path,
                "Body text without citations.",
                extra_parts={
                    "word/footnotes.xml": "Professional reliance is governed by 6 Del. C. § 17-406.",
                    "word/comments.xml": "Title 6, Chapter 12C may apply.",
                    "word/header1.xml": "Court of Chancery Rule 12(b)(6) applies.",
                    "word/footer1.xml": "Footer cites 6 Del. C. § 17-407. A Del. Ch. opinion may apply.",
                },
            )
            output = self.run_cli("validate", "--file", str(docx_path))
        self.assertIn("6 Del. C. § 17-407", output)
        self.assertIn("Del. Ch. Ct. R. 12", output)
        self.assertIn("Online and Personal Privacy Protection", output)
        self.assertIn("暂不覆盖", output)

    def test_validate_underground_utility_wrong_chapter(self) -> None:
        output = self.run_cli(
            "validate",
            "Underground Utility Damage Prevention and Safety Act is under Title 26, Ch. 12 (§801).",
        )
        self.assertIn("Title 26, Chapter 8", output)
        self.assertIn("26 Del. C. § 801", output)
        self.assertNotIn("1 Del. C. § 801", output)

    def test_validate_public_records_federal_foia_drift(self) -> None:
        output = self.run_cli(
            "validate",
            "A Delaware public body must answer public records requests under federal FOIA 5 U.S.C. § 552.",
        )
        self.assertIn("29 Del. C. ch. 100", output)
        self.assertIn("29 Del. C. § 10003", output)

    def test_validate_public_works_bond_not_title_18(self) -> None:
        output = self.run_cli(
            "validate",
            "Public works bid bond and performance bond requirements are governed by Title 18 insurance law.",
        )
        self.assertIn("29 Del. C. § 6927", output)
        self.assertIn("Bid and contract security", output)

    def test_validate_title_7_environment_needs_external_regulations(self) -> None:
        output = self.run_cli(
            "validate",
            "Environmental permit obligations under Title 7 of the Delaware Code may require DNREC regulations.",
        )
        self.assertIn("Delaware Code Title 7", output)
        self.assertIn("DNREC regulations", output)

    def test_validate_computer_crime_statutory_set(self) -> None:
        output = self.run_cli(
            "validate",
            "Any unauthorized access is a computer crime under 11 Del. C. § 932.",
        )
        self.assertIn("11 Del. C. § 939", output)
        self.assertIn("11 Del. C. § 940", output)

    def test_validate_bare_title_reference(self) -> None:
        output = self.run_cli(
            "validate",
            "Title 16 and Title 24 govern health services, pharmacy practice, social work and telehealth.",
        )
        self.assertIn("识别到过宽 Title 引用数量", output)
        self.assertIn("Title 16", output)
        self.assertIn("Title 24", output)

    def test_validate_professional_license_mapping(self) -> None:
        output = self.run_cli(
            "validate",
            "Professional licensing for pharmacy, nursing, social work and psychology under Title 24 must be checked.",
        )
        self.assertIn("24 Del. C. ch. 25", output)
        self.assertIn("24 Del. C. ch. 19", output)
        self.assertIn("24 Del. C. ch. 39", output)
        self.assertIn("24 Del. C. ch. 35", output)
        self.assertNotIn("social work maps to Chapter 30", output)

    def test_validate_telehealth_general_and_social_work_limits(self) -> None:
        output = self.run_cli(
            "validate",
            "Healthcare telehealth services are generally governed by 24 Del. C. § 3920.",
        )
        self.assertIn("不能泛化为所有医疗职业", output)
        self.assertIn("24 Del. C. § 6002", output)
        self.assertIn("24 Del. C. § 6004", output)

    def test_validate_social_work_not_chapter_30(self) -> None:
        output = self.run_cli(
            "validate",
            "Title 24 Chapter 30 governs social work licensing and telehealth under 24 Del. C. § 3920.",
        )
        self.assertIn("Social work 专业许可应定位到 Title 24 Chapter 39", output)
        self.assertIn("24 Del. C. ch. 39", output)
        self.assertIn("24 Del. C. § 3903", output)

    def test_validate_federal_health_education_boundary(self) -> None:
        output = self.run_cli(
            "validate",
            "HIPAA, FERPA, DEA, FDA, Medicare and Medicaid obligations apply.",
        )
        self.assertIn("联邦法律或项目", output)
        self.assertIn("当前数据包不能验证", output)

    def test_search_good_samaritan_maps_to_immunity(self) -> None:
        output = self.run_cli("search", "Good Samaritan", "-n", "4")
        self.assertIn("10 Del. C. § 8135", output)
        self.assertIn("16 Del. C. § 4769", output)

    def test_review_uses_plain_language_categories(self) -> None:
        output = self.run_cli(
            "review",
            "Professional reliance under 6 Del. C. § 17-406. 6 Del. C. § 99-999. Title 29 of the Delaware Code governs public procurement. A Del. Ch. opinion applies.",
        )
        for heading in [
            "## 明显错误",
            "## 引用太宽泛",
            "## 需要查外部材料",
            "## 本地数据库没查到",
            "## 可能影响结论的相关法律",
            "## 已确认正确的引用",
            "## 本工具未覆盖的内容",
        ]:
            self.assertIn(heading, output)
        self.assertIn("6 Del. C. § 17-407", output)
        self.assertIn("不得据此认定该条文不存在", output)
        self.assertIn("29 Del. C. ch. 69", output)

def _write_minimal_docx(path: Path, text: str, extra_parts: dict[str, str] | None = None) -> None:
    document_xml = _minimal_docx_xml(text)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
""")
        zf.writestr("word/document.xml", document_xml)
        for part_name, part_text in (extra_parts or {}).items():
            zf.writestr(part_name, _minimal_docx_xml(part_text))


def _minimal_docx_xml(text: str) -> str:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{escaped}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""


if __name__ == "__main__":
    unittest.main()
