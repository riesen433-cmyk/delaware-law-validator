from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_VERSION = "delaware-law-data-v0.1.0"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "delaware_law_data_v0.1.0.sqlite"
DEFAULT_RAW_MD_DIR = PROJECT_ROOT / "data" / "raw_md"
DEFAULT_RAW_COURT_RULES_DIR = PROJECT_ROOT / "data" / "raw_court_rules"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.json"
DEFAULT_COVERAGE_PATH = PROJECT_ROOT / "data" / "coverage-report.json"
DEFAULT_SEMANTIC_INDEX_DIR = PROJECT_ROOT / "data" / "semantic"
DEFAULT_ADMIN_CODE_DIR = PROJECT_ROOT / "data" / "admin_code"
DEFAULT_ADMIN_CODE_DB_PATH = DEFAULT_ADMIN_CODE_DIR / "admin_code.sqlite"
DEFAULT_ADMIN_CODE_PDF_DIR = DEFAULT_ADMIN_CODE_DIR / "pdf"

DELCODE_HOME_URL = "https://delcode.delaware.gov/"
DELAWARE_REGULATIONS_HOME_URL = "https://regulations.delaware.gov"
DELAWARE_REGULATIONS_API_URL = "https://regulations.delaware.gov/api/"

BGE_EMBEDDING_MODEL = "BAAI/bge-m3"
BGE_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
