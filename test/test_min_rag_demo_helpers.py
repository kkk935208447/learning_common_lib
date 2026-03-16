from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from learning_common_lib.案例.实现AgenticRAG数据库管理.最小可执行demo.errors import (  # noqa: E402
    FileTooLargeError,
    UnsupportedMediaTypeError,
)
from learning_common_lib.案例.实现AgenticRAG数据库管理.最小可执行demo.services.common import (  # noqa: E402
    build_storage_key,
    chunk_text,
    parse_bytes_to_text,
    validate_upload_request,
)


class MinRagDemoHelperTests(unittest.TestCase):
    def test_validate_upload_request_accepts_supported_text_file(self) -> None:
        external_doc_key, file_name, mime_type = validate_upload_request(
            external_doc_key=" employee-handbook ",
            file_name="../employee.md",
            mime_type="text/markdown",
            content=b"hello world",
        )
        self.assertEqual(external_doc_key, "employee-handbook")
        self.assertEqual(file_name, "employee.md")
        self.assertEqual(mime_type, "text/markdown")

    def test_validate_upload_request_rejects_unsupported_mime_type(self) -> None:
        with self.assertRaises(UnsupportedMediaTypeError):
            validate_upload_request(
                external_doc_key="doc-1",
                file_name="archive.zip",
                mime_type="application/zip",
                content=b"zip-bytes",
            )

    def test_validate_upload_request_rejects_too_large_file(self) -> None:
        with self.assertRaises(FileTooLargeError):
            validate_upload_request(
                external_doc_key="doc-2",
                file_name="large.txt",
                mime_type="text/plain",
                content=b"x" * (20 * 1024 * 1024 + 1),
            )

    def test_build_storage_key_uses_document_and_version_scope(self) -> None:
        storage_key = build_storage_key(12, 3, "../employee handbook.txt")
        self.assertEqual(storage_key, "raw/document_12/version_3/employee handbook.txt")

    def test_chunk_text_produces_stable_order(self) -> None:
        chunks = chunk_text("a" * 1200)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(chunks))

    def test_parse_bytes_to_text_supports_plain_text(self) -> None:
        text = parse_bytes_to_text("你好，RAG".encode("utf-8"), "text/plain")
        self.assertEqual(text, "你好，RAG")


if __name__ == "__main__":
    unittest.main()
