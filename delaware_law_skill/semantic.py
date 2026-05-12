from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .config import BGE_EMBEDDING_MODEL, BGE_RERANKER_MODEL, DEFAULT_SEMANTIC_INDEX_DIR
from .database import DelawareLawDatabase


EMBEDDINGS_FILE = "embeddings.npy"
MATERIALS_FILE = "materials.jsonl"
INDEX_META_FILE = "index.json"
MAX_TEXT_CHARS = 6000


class SemanticError(RuntimeError):
    pass


class SemanticDependencyError(SemanticError):
    pass


class SemanticIndexError(SemanticError):
    pass


@dataclass(frozen=True)
class SemanticBuildResult:
    index_dir: str
    embedding_model: str
    reranker_model: str
    material_count: int
    embedding_dimension: int
    data_version: str | None


@dataclass(frozen=True)
class SemanticIndexStatus:
    index_dir: str
    ready: bool
    embedding_model: str | None
    reranker_model: str | None
    data_version: str | None
    db_data_version: str | None
    material_count: int | None
    db_material_count: int | None
    embedding_dimension: int | None
    files: dict[str, bool]
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class SemanticSearchResult:
    citation: str
    heading: str
    source_file: str
    source_url: str
    data_version: str
    preview: str
    semantic_score: float
    rerank_score: float | None
    final_score: float
    exact_retrieved: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_semantic_index(
    db: DelawareLawDatabase,
    index_dir: Path = DEFAULT_SEMANTIC_INDEX_DIR,
    embedding_model: str = BGE_EMBEDDING_MODEL,
    reranker_model: str = BGE_RERANKER_MODEL,
    batch_size: int = 16,
    limit: int | None = None,
    show_progress: bool = True,
) -> SemanticBuildResult:
    np = _require_numpy()
    sentence_transformer = _require_sentence_transformer()

    rows = db.materials_for_semantic_index(limit=limit)
    if not rows:
        raise SemanticIndexError("No materials found in the local database.")
    db_metadata = db.metadata()

    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)

    texts = [_material_text(row) for row in rows]
    model = sentence_transformer(embedding_model)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=show_progress,
    )
    embeddings = np.asarray(embeddings, dtype="float32")
    np.save(index_dir / EMBEDDINGS_FILE, embeddings)

    with (index_dir / MATERIALS_FILE).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_row_metadata(row), ensure_ascii=False) + "\n")

    meta = {
        "embedding_model": embedding_model,
        "reranker_model": reranker_model,
        "material_count": len(rows),
        "embedding_dimension": int(embeddings.shape[1]),
        "data_version": db_metadata.get("data_version"),
        "coverage": db_metadata.get("coverage"),
        "pipeline": "semantic candidate retrieval -> exact SQLite material retrieval -> optional reranking",
    }
    (index_dir / INDEX_META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return SemanticBuildResult(
        index_dir=str(index_dir),
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        material_count=len(rows),
        embedding_dimension=int(embeddings.shape[1]),
        data_version=db_metadata.get("data_version"),
    )


def semantic_search(
    db: DelawareLawDatabase,
    query: str,
    index_dir: Path = DEFAULT_SEMANTIC_INDEX_DIR,
    embedding_model: str | None = None,
    reranker_model: str = BGE_RERANKER_MODEL,
    limit: int = 10,
    candidate_limit: int = 50,
    rerank: bool = True,
) -> list[SemanticSearchResult]:
    index_dir = Path(index_dir)
    index_meta = _load_index_meta(index_dir)
    materials = _load_index_materials(index_dir)
    embeddings_path = index_dir / EMBEDDINGS_FILE
    if not embeddings_path.exists():
        raise SemanticIndexError(
            f"Semantic index is missing: {embeddings_path}. Run rag-build first."
        )

    np = _require_numpy()
    sentence_transformer = _require_sentence_transformer()
    embeddings = np.load(embeddings_path)
    if len(materials) != embeddings.shape[0]:
        raise SemanticIndexError("Semantic index files are inconsistent. Rebuild the semantic index.")

    selected_embedding_model = embedding_model or str(index_meta.get("embedding_model") or BGE_EMBEDDING_MODEL)
    model = sentence_transformer(selected_embedding_model)
    query_embedding = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)
    scores = embeddings @ np.asarray(query_embedding[0], dtype="float32")

    candidate_count = min(max(candidate_limit, limit), len(materials))
    if candidate_count == 0:
        return []
    if candidate_count < len(materials):
        top_indices = np.argpartition(-scores, candidate_count - 1)[:candidate_count]
    else:
        top_indices = np.arange(len(materials))
    top_indices = top_indices[np.argsort(-scores[top_indices])]

    rowids = [int(materials[int(index)]["rowid"]) for index in top_indices]
    exact_rows = db.materials_by_rowids(rowids)
    results: list[SemanticSearchResult] = []
    rerank_texts: list[str] = []

    for index in top_indices:
        material = materials[int(index)]
        rowid = int(material["rowid"])
        row = exact_rows.get(rowid)
        exact_retrieved = row is not None
        if row is not None:
            citation = row["citation"]
            heading = row["heading"]
            source_file = row["source_file"]
            source_url = row["source_url"]
            data_version = row["data_version"]
            text = row["text"]
        else:
            citation = str(material["citation"])
            heading = str(material["heading"])
            source_file = str(material["source_file"])
            source_url = str(material["source_url"])
            data_version = str(material["data_version"])
            text = str(material.get("preview", ""))
        semantic_score = float(scores[int(index)])
        rerank_texts.append(_candidate_text(citation, heading, text))
        results.append(
            SemanticSearchResult(
                citation=citation,
                heading=heading,
                source_file=source_file,
                source_url=source_url,
                data_version=data_version,
                preview=" ".join(text.split())[:500],
                semantic_score=semantic_score,
                rerank_score=None,
                final_score=semantic_score,
                exact_retrieved=exact_retrieved,
            )
        )

    if rerank and results:
        selected_reranker = reranker_model or str(index_meta.get("reranker_model") or BGE_RERANKER_MODEL)
        rerank_scores = _rerank(query, rerank_texts, selected_reranker)
        for result, score in zip(results, rerank_scores):
            result.rerank_score = score
            result.final_score = score
        results.sort(key=lambda item: item.final_score, reverse=True)

    return results[:limit]


def _require_numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise SemanticDependencyError(
            "Semantic search requires optional dependencies. Install them with: "
            'python3 -m pip install -e ".[semantic]"'
        ) from exc
    return np


def _require_sentence_transformer() -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SemanticDependencyError(
            "Semantic search requires sentence-transformers. Install it with: "
            'python3 -m pip install -e ".[semantic]"'
        ) from exc
    return SentenceTransformer


def _require_cross_encoder() -> Any:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise SemanticDependencyError(
            "Reranking requires sentence-transformers. Install it with: "
            'python3 -m pip install -e ".[semantic]"'
        ) from exc
    return CrossEncoder


def semantic_index_status(
    db: DelawareLawDatabase,
    index_dir: Path = DEFAULT_SEMANTIC_INDEX_DIR,
) -> SemanticIndexStatus:
    index_dir = Path(index_dir)
    files = {
        INDEX_META_FILE: (index_dir / INDEX_META_FILE).exists(),
        MATERIALS_FILE: (index_dir / MATERIALS_FILE).exists(),
        EMBEDDINGS_FILE: (index_dir / EMBEDDINGS_FILE).exists(),
    }
    warnings: list[str] = []
    meta: dict[str, object] = {}
    if files[INDEX_META_FILE]:
        try:
            meta = json.loads((index_dir / INDEX_META_FILE).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warnings.append("index.json cannot be parsed; rebuild the RAG index.")
    else:
        warnings.append("RAG index metadata is missing; run rag-build.")

    material_line_count: int | None = None
    if files[MATERIALS_FILE]:
        with (index_dir / MATERIALS_FILE).open("r", encoding="utf-8") as handle:
            material_line_count = sum(1 for line in handle if line.strip())
    else:
        warnings.append("RAG materials map is missing; run rag-build.")

    if not files[EMBEDDINGS_FILE]:
        warnings.append("RAG embeddings file is missing; run rag-build.")

    db_metadata = db.metadata()
    db_data_version = db_metadata.get("data_version")
    data_version = _optional_str(meta.get("data_version"))
    if data_version and db_data_version and data_version != db_data_version:
        warnings.append("RAG index data version does not match the current database; rebuild the index.")

    db_material_count = _optional_int(db_metadata.get("material_count"))
    material_count = _optional_int(meta.get("material_count")) or material_line_count
    if material_count and db_material_count and material_count != db_material_count:
        warnings.append("RAG index material count does not match the current database; rebuild the index.")

    ready = all(files.values()) and not warnings
    return SemanticIndexStatus(
        index_dir=str(index_dir),
        ready=ready,
        embedding_model=_optional_str(meta.get("embedding_model")),
        reranker_model=_optional_str(meta.get("reranker_model")),
        data_version=data_version,
        db_data_version=db_data_version,
        material_count=material_count,
        db_material_count=db_material_count,
        embedding_dimension=_optional_int(meta.get("embedding_dimension")),
        files=files,
        warnings=warnings,
    )


def _rerank(query: str, candidate_texts: list[str], reranker_model: str) -> list[float]:
    flag_reranker = _require_flag_reranker()
    reranker = flag_reranker(reranker_model, use_fp16=False)
    scores = reranker.compute_score([(query, text) for text in candidate_texts], normalize=True)
    return [_to_float(score) for score in scores]


def _require_flag_reranker() -> Any:
    try:
        from FlagEmbedding import FlagReranker
    except ImportError as exc:
        raise SemanticDependencyError(
            "Reranking requires FlagEmbedding. Install semantic dependencies with: "
            'python3 -m pip install -e ".[semantic]"'
        ) from exc
    return FlagReranker


def _load_index_meta(index_dir: Path) -> dict[str, object]:
    meta_path = index_dir / INDEX_META_FILE
    if not meta_path.exists():
        raise SemanticIndexError(f"Semantic index is missing: {meta_path}. Run rag-build first.")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _load_index_materials(index_dir: Path) -> list[dict[str, object]]:
    materials_path = index_dir / MATERIALS_FILE
    if not materials_path.exists():
        raise SemanticIndexError(f"Semantic index is missing: {materials_path}. Run rag-build first.")
    materials: list[dict[str, object]] = []
    with materials_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                materials.append(json.loads(line))
    return materials


def _row_metadata(row: Any) -> dict[str, object]:
    return {
        "rowid": int(row["rowid"]),
        "citation": row["citation"],
        "heading": row["heading"],
        "material_type": row["material_type"],
        "source_file": row["source_file"],
        "source_url": row["source_url"],
        "data_version": row["data_version"],
        "title_number": row["title_number"],
        "section_number": row["section_number"],
        "start_line": row["start_line"],
        "preview": " ".join(row["text"].split())[:500],
    }


def _material_text(row: Any) -> str:
    return _candidate_text(row["citation"], row["heading"], row["text"])


def _candidate_text(citation: str, heading: str, text: str) -> str:
    trimmed_text = " ".join(text.split())[:MAX_TEXT_CHARS]
    return f"{citation}\n{heading}\n{trimmed_text}"


def _to_float(value: object) -> float:
    if hasattr(value, "item"):
        return float(value.item())  # type: ignore[no-any-return]
    if isinstance(value, (list, tuple)):
        return float(value[0])
    return float(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
