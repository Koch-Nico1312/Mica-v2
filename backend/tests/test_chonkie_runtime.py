"""Fresh-container compatibility proof for MICA's code-aware chunker.

Run from the repository root after building the Python image:

    docker run --rm -v "$PWD/backend:/source:ro" --entrypoint python \
      mica-mica-api /source/tests/test_chonkie_runtime.py
"""
from __future__ import annotations

import importlib.metadata
import unittest

from chonkie import CodeChunker, TokenChunker


class ChonkieRuntimeTests(unittest.TestCase):
    def test_locked_versions_and_markdown_token_chunking(self) -> None:
        self.assertEqual(importlib.metadata.version("chonkie"), "1.7.0")
        self.assertEqual(importlib.metadata.version("tree-sitter-language-pack"), "1.8.1")

        source = ("Markdown-Wissen bleibt die einzige Wahrheit. " * 100).strip()
        chunks = TokenChunker(tokenizer="character", chunk_size=700)(source)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].start_index, 0)
        self.assertEqual(chunks[-1].end_index, len(source))

    def test_python_code_is_split_on_syntax_aware_boundaries(self) -> None:
        source = "".join(
            f"def health_check_{index}(value):\n"
            f"    return value == {index}\n\n"
            for index in range(90)
        )
        chunks = CodeChunker(
            tokenizer="character", chunk_size=900, language="python"
        )(source)

        self.assertGreaterEqual(len(chunks), 3)
        self.assertEqual(chunks[0].start_index, 0)
        self.assertEqual(chunks[-1].end_index, len(source))
        self.assertTrue(all(chunk.text.lstrip().startswith("def ") for chunk in chunks))
        self.assertEqual("".join(chunk.text for chunk in chunks), source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
