"""
LAKO — Plain Text Parser
Reads .txt files directly into ParsedDocument format.
Session 1: Stub — wired in Session 5.
"""

from pathlib import Path
from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class TxtParser:
    """Reads plain text files. Treats whole file as single page."""

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Read a .txt file and wrap it in ParsedDocument.
        TODO (Session 5): implement.
        """
        raise NotImplementedError("TxtParser.parse() — Session 5")


# Singleton instance
txt_parser = TxtParser()
