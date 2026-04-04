"""
LAKO — Excel Parser
Extracts cell data and sheet names from .xlsx files.
Uses openpyxl + pandas. Each sheet becomes a separate ParsedPage.
Session 6:  Fully implemented.
Session 15: Tables emitted as markdown (| col | col |) for consistent chunking.
            Rule-based sheet summary stored in page.text so it becomes a lightweight
            searchable chunk alongside the full table chunk.
"""

from pathlib import Path
from typing import List

import pandas as pd

from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class ExcelParser:
    """
    Parses .xlsx files using openpyxl / pandas.
    Each sheet becomes a separate 'page' in ParsedDocument.

    page.text   = One-line rule-based summary: sheet name + column names + row count.
                  Stored as an inline_block → becomes a lightweight searchable chunk.

    page.tables = Full sheet as a markdown table string (| col | col |).
                  Stored as a standalone_table → chunk_table() applies header-prepend
                  splitting if the sheet is too large for one chunk.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract all sheet data from an Excel file.
        Returns ParsedDocument where each page = one sheet.
        """
        file_path = Path(file_path)
        xl = pd.ExcelFile(str(file_path), engine="openpyxl")
        pages = []

        for sheet_index, sheet_name in enumerate(xl.sheet_names):
            df = xl.parse(sheet_name, dtype=str)
            df = df.fillna("")

            table_text = f"Sheet: {sheet_name}\n{self._sheet_to_markdown(df)}"
            summary = self._sheet_summary(sheet_name, df, file_path.name)

            pages.append(ParsedPage(
                page_number=sheet_index + 1,
                text=summary,           # lightweight summary → inline_block
                tables=[table_text],    # full table  → standalone table chunk
            ))

        return ParsedDocument(
            filename=file_path.name,
            pages=pages,
            total_pages=len(pages),
        )

    def _sheet_to_markdown(self, df: "pd.DataFrame") -> str:
        """
        Convert a pandas DataFrame to a markdown table string.
        Header row + separator row + data rows.
        Empty cells become blank strings.
        """
        columns = [str(col) for col in df.columns]
        col_count = len(columns)
        separator = ["---"] * col_count

        lines = ["| " + " | ".join(columns) + " |"]
        lines.append("| " + " | ".join(separator) + " |")

        for _, row in df.iterrows():
            cells = [str(val).strip().replace("\n", " ") for val in row]
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    def _sheet_summary(self, sheet_name: str, df: "pd.DataFrame", filename: str) -> str:
        """
        Generate a one-line rule-based summary for the sheet.
        Used as a lightweight anchor chunk for semantic search.
        Example: "Sheet 'Rates' from report.xlsx: columns Product, Q1, Q2, Type. 42 rows."
        """
        col_preview = ", ".join(str(c) for c in df.columns[:8])
        if len(df.columns) > 8:
            col_preview += f" (+{len(df.columns) - 8} more)"
        return (
            f"Sheet '{sheet_name}' from {filename}: "
            f"columns {col_preview}. "
            f"{len(df)} row(s) of data."
        )


# Singleton instance
excel_parser = ExcelParser()
