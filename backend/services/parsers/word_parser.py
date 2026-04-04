"""
LAKO — Word Document Parser
Extracts paragraphs, headings, and tables from .docx files.
Uses python-docx. Returns a single ParsedPage (no page concept in python-docx).
Session 6:  Fully implemented.
Session 15: Walk doc.element.body in document order so tables appear inline with prose.
            Tables emitted as markdown — chunker detects them for contextual chunking.
"""

from pathlib import Path
from typing import List

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.table import Table as DocxTable

from services.parsers.pdf_parser import ParsedDocument, ParsedPage

# Map python-docx style names to markdown heading prefixes
_HEADING_PREFIX = {
    "Heading 1": "#",
    "Heading 2": "##",
    "Heading 3": "###",
    "Title":     "#",
    "Subtitle":  "##",
}


class WordParser:
    """
    Parses .docx files using python-docx.

    Walks doc.element.body in document order so that tables appear immediately
    after the prose that introduces them. Each table is converted to a markdown
    table string (| col | col |) and inserted inline — the chunker then keeps
    the surrounding paragraph and the table together in one chunk.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract text and tables from a Word document in document order.
        Returns ParsedDocument with a single ParsedPage containing unified inline text.
        """
        file_path = Path(file_path)
        doc = Document(str(file_path))

        parts: List[str] = []

        for child in doc.element.body:
            tag = child.tag

            if tag == qn("w:p"):
                para = DocxParagraph(child, doc)
                text = para.text.strip()
                if not text:
                    continue
                prefix = _HEADING_PREFIX.get(para.style.name, "")
                parts.append(f"{prefix} {text}" if prefix else text)

            elif tag == qn("w:tbl"):
                table = DocxTable(child, doc)
                md = self._table_to_markdown(table)
                if md.strip():
                    parts.append(md)

            # w:sectPr (section properties) and other tags are skipped

        page = ParsedPage(
            page_number=1,
            text="\n\n".join(parts),
            tables=[],   # tables now inline in text — tables list intentionally empty
        )

        return ParsedDocument(
            filename=file_path.name,
            pages=[page],
            total_pages=1,
        )

    def _table_to_markdown(self, table: DocxTable) -> str:
        """
        Convert a python-docx Table to a markdown table string.
        First row is treated as the header row.
        Newlines within cells are collapsed to spaces.
        """
        rows: List[List[str]] = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(cells)

        if not rows:
            return ""

        headers = rows[0]
        col_count = len(headers)
        separator = ["---"] * col_count

        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("| " + " | ".join(separator) + " |")

        for row in rows[1:]:
            # Pad short rows, truncate over-long rows to match header width
            padded = (row + [""] * col_count)[:col_count]
            lines.append("| " + " | ".join(padded) + " |")

        return "\n".join(lines)


# Singleton instance
word_parser = WordParser()
