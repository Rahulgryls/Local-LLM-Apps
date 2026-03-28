"""
LAKO — Excel Parser
Extracts cell data and sheet names from .xlsx files.
Uses openpyxl + pandas. Each sheet becomes a separate ParsedPage.
Session 6: Fully implemented.
"""

from pathlib import Path

import pandas as pd

from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class ExcelParser:
    """
    Parses .xlsx files using openpyxl/pandas.
    Each sheet becomes a separate 'page' in ParsedDocument.
    Sheet data is formatted as a pipe-separated text table and stored in
    page.tables so the chunker preserves each sheet as an intact table chunk.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract all sheet data from an Excel file.
        Returns ParsedDocument where each page = one sheet.
        """
        file_path = Path(file_path)

        # Read all sheet names without loading data yet
        xl = pd.ExcelFile(str(file_path), engine="openpyxl")
        pages = []

        for sheet_index, sheet_name in enumerate(xl.sheet_names):
            df = xl.parse(sheet_name, dtype=str)
            table_text = f"Sheet: {sheet_name}\n{self._sheet_to_text(df)}"

            pages.append(ParsedPage(
                page_number=sheet_index + 1,
                text="",             # text blocks not used for Excel
                tables=[table_text], # each sheet stored as one table chunk
            ))

        return ParsedDocument(
            filename=file_path.name,
            pages=pages,
            total_pages=len(pages),
        )

    def _sheet_to_text(self, df: "pd.DataFrame") -> str:
        """
        Convert a pandas DataFrame to a pipe-separated text table.
        Empty cells become blank strings. Column headers are included as first row.
        """
        df = df.fillna("")

        # Header row
        lines = [" | ".join(str(col) for col in df.columns)]

        # Data rows
        for _, row in df.iterrows():
            lines.append(" | ".join(str(val) for val in row))

        return "\n".join(lines)


# Singleton instance
excel_parser = ExcelParser()
