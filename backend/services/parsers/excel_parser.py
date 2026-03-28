"""
LAKO — Excel Parser
Extracts cell data and sheet names from .xlsx files.
Uses openpyxl + pandas.
Session 1: Stub — wired in Session 6.
"""

from pathlib import Path
from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class ExcelParser:
    """
    Parses .xlsx files using openpyxl/pandas.
    Each sheet becomes a separate 'page' in ParsedDocument.
    Cell data is formatted as readable text (CSV-style).
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract all sheet data from an Excel file.
        Returns ParsedDocument where each page = one sheet.
        TODO (Session 6): implement with openpyxl + pandas.
        """
        raise NotImplementedError("ExcelParser.parse() — Session 6")

    def _sheet_to_text(self, df) -> str:
        """
        Convert a pandas DataFrame to a readable text table.
        TODO (Session 6): implement.
        """
        raise NotImplementedError("ExcelParser._sheet_to_text() — Session 6")


# Singleton instance
excel_parser = ExcelParser()
