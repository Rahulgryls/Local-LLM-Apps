"""
LAKO — PowerPoint Parser
Extracts slide text and speaker notes from .pptx files.
Uses python-pptx.
Session 1: Stub — wired in Session 6.
"""

from pathlib import Path
from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class PPTParser:
    """
    Parses .pptx files using python-pptx.
    Each slide becomes a separate 'page' in ParsedDocument.
    Extracts: slide title, text boxes, speaker notes.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract slide text and notes from a PowerPoint file.
        Returns ParsedDocument where each page = one slide.
        TODO (Session 6): implement with python-pptx.
        """
        raise NotImplementedError("PPTParser.parse() — Session 6")

    def _slide_to_text(self, slide) -> str:
        """
        Extract all text from a single slide (title + text boxes + notes).
        TODO (Session 6): implement.
        """
        raise NotImplementedError("PPTParser._slide_to_text() — Session 6")


# Singleton instance
ppt_parser = PPTParser()
