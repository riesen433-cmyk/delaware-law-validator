from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delaware_law_skill.config import DEFAULT_DB_PATH
from delaware_law_skill.database import DelawareLawDatabase
from delaware_law_skill.semantic import EMBEDDINGS_FILE, INDEX_META_FILE, MATERIALS_FILE, semantic_search


class SemanticPipelineTests(unittest.TestCase):
    def test_semantic_search_exact_retrieves_before_rerank(self) -> None:
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy is not installed")

        db = DelawareLawDatabase(DEFAULT_DB_PATH)
        try:
            _, first_rows = db.lookup("6 Del. C. § 17-406")
            _, second_rows = db.lookup("6 Del. C. § 17-407")
            first = first_rows[0]
            second = second_rows[0]

            with tempfile.TemporaryDirectory() as temp_dir:
                index_dir = Path(temp_dir)
                (index_dir / INDEX_META_FILE).write_text(
                    json.dumps(
                        {
                            "embedding_model": "fake-embedding",
                            "reranker_model": "fake-reranker",
                            "material_count": 2,
                            "embedding_dimension": 2,
                            "data_version": db.metadata().get("data_version"),
                        }
                    ),
                    encoding="utf-8",
                )
                with (index_dir / MATERIALS_FILE).open("w", encoding="utf-8") as handle:
                    for row in [first, second]:
                        handle.write(
                            json.dumps(
                                {
                                    "rowid": int(row["rowid"]),
                                    "citation": row["citation"],
                                    "heading": row["heading"],
                                    "source_file": row["source_file"],
                                    "source_url": row["source_url"],
                                    "data_version": row["data_version"],
                                    "preview": row["heading"],
                                }
                            )
                            + "\n"
                        )
                np.save(index_dir / EMBEDDINGS_FILE, np.asarray([[1.0, 0.0], [0.9, 0.1]], dtype="float32"))

                class FakeSentenceTransformer:
                    def __init__(self, model_name: str):
                        self.model_name = model_name

                    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
                        return np.asarray([[1.0, 0.0]], dtype="float32")

                captured_texts: list[str] = []

                def fake_rerank(query: str, candidate_texts: list[str], reranker_model: str) -> list[float]:
                    captured_texts.extend(candidate_texts)
                    return [0.1, 0.9]

                with patch("delaware_law_skill.semantic._require_sentence_transformer", return_value=FakeSentenceTransformer):
                    with patch("delaware_law_skill.semantic._rerank", side_effect=fake_rerank):
                        results = semantic_search(
                            db,
                            "professional reliance",
                            index_dir=index_dir,
                            limit=2,
                            candidate_limit=2,
                            rerank=True,
                        )

            self.assertEqual(results[0].citation, "6 Del. C. § 17-407")
            self.assertTrue(all(result.exact_retrieved for result in results))
            self.assertTrue(any("Reliance on reports and information" in text for text in captured_texts))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
