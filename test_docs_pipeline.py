"""Manual test script for the DOCX reader.

Usage:
    python test_docs_pipeline.py
    python test_docs_pipeline.py "data/uploads/my_notes.docx"
"""

import logging
import sys

from ai.ingestion.docs_reader import DocxReader

DEFAULT_DOCX_PATH = "data/uploads/test1word.docx"

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")


def main() -> None:
    docx_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX_PATH

    reader = DocxReader()
    doc = reader.read(docx_path)

    print("\n=== STATISTICS ===")
    print(doc.statistics)

    print("\n=== HEADINGS ===")
    for heading in doc.metadata.get("headings", []):
        print(f"{'  ' * heading['level']}[L{heading['level']}] {heading['text']}")

    print("\n=== IMAGES ===")
    for image in doc.metadata.get("images", []):
        print(image)

    page = doc.get_page(1)
    if page is not None:
        print("\n=== PAGE INFO ===")
        print(f"page_type  : {page.page_type.value}")
        print(f"confidence : {page.confidence}")
        print(f"warnings   : {page.warnings}")

    print("\n=== FULL TEXT ===")
    print(doc.full_text)


if __name__ == "__main__":
    main()
