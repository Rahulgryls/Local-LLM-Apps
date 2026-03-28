"""
LAKO — Word Document Parser
Extracts paragraphs, headings, and tables from .docx files.
Uses python-docx. Returns a single ParsedPage (no page concept in python-docx).
Session 6: Fully implemented.
"""

from pathlib import Path

from docx import Document

from services.parsers.pdf_parser import ParsedDocument, ParsedPage

# Map python-docx style names to markdown heading prefixes
_HEADING_PREFIX = {
    "Heading 1": "#",
    "Heading 2": "##",
    "Heading 3": "###",
    "Title": "#",
    "Subtitle": "##",
}


class WordParser:
    """
    Parses .docx files using python-docx.
    Paragraphs (with heading markers) go into page.text.
    Tables go into page.tables as pipe-separated strings — the chunker
    keeps each table intact as a single chunk.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract paragraphs, headings, and tables from a Word document.
        Returns ParsedDocument with a single ParsedPage.
        """
        file_path = Path(file_path)
        doc = Document(str(file_path))

        para_lines = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            prefix = _HEADING_PREFIX.get(para.style.name, "")
            if prefix:
                para_lines.append(f"{prefix} {text}")
            else:
                para_lines.append(text)

        table_texts = []
        for table in doc.tables:
            table_text = self._table_to_text(table)
            if table_text.strip():
                table_texts.append(table_text)

        page = ParsedPage(
            page_number=1,
            text="\n".join(para_lines),
            tables=table_texts,
        )

        return ParsedDocument(
            filename=file_path.name,
            pages=[page],
            total_pages=1,
        )

    def _table_to_text(self, table) -> str:
        """
        Convert a python-docx Table object to pipe-separated plain text.
        Each row becomes one line. Newlines within cells are collapsed to spaces.
        """
        rows = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(" | ".join(cells))
        return "\n".join(rows)


# Singleton instance
word_parser = WordParser()
