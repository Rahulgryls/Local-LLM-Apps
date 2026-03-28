"""
LAKO — Word Document Parser
Extracts paragraphs, headings, and tables from .docx files.
Uses python-docx.
Session 1: Stub — wired in Session 6.
"""

from pathlib import Path
from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class WordParser:
    """
    Parses .docx files using python-docx.
    Preserves heading hierarchy and table structure as text.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract paragraphs, headings, and tables from a Word document.
        Returns ParsedDocument (single page — Word has no page concept in python-docx).
        TODO (Session 6): implement with python-docx.
        """
        raise NotImplementedError("WordParser.parse() — Session 6")

    def _table_to_text(self, table) -> str:
        """
        Convert a python-docx Table object to plain text (pipe-separated rows).
        TODO (Session 6): implement.
        """
        raise NotImplementedError("WordParser._table_to_text() — Session 6")


# Singleton instance
word_parser = WordParser()
