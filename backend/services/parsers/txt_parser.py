"""
LAKO — Plain Text Parser
Reads .txt files directly into ParsedDocument format.
Session 5: Fully implemented.
"""

from pathlib import Path
from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class TxtParser:
    """
    Reads plain text files.
    Treats the entire file as a single page (page_number = 1).
    No chunking happens here — the chunker handles that downstream.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Read a .txt file and wrap its content in a ParsedDocument.
        Tries UTF-8 first, falls back to latin-1 for files with non-UTF-8 bytes.
        Returns a ParsedDocument with one ParsedPage containing the full text.
        """
        file_path = Path(file_path)

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="latin-1")

        page = ParsedPage(page_number=1, text=text)

        return ParsedDocument(
            filename=file_path.name,
            pages=[page],
            total_pages=1,
            used_ocr=False,
        )


# Singleton instance
txt_parser = TxtParser()
