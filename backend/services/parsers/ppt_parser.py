"""
LAKO — PowerPoint Parser
Extracts slide text and speaker notes from .pptx files.
Uses python-pptx. Each slide becomes a separate ParsedPage.
Session 6: Fully implemented.
"""

from pathlib import Path

from pptx import Presentation

from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class PPTParser:
    """
    Parses .pptx files using python-pptx.
    Each slide becomes a separate 'page' in ParsedDocument.
    Extracts: slide title (prefixed with #), all text boxes, speaker notes.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract slide text and notes from a PowerPoint file.
        Returns ParsedDocument where each page = one slide.
        """
        file_path = Path(file_path)
        prs = Presentation(str(file_path))
        pages = []

        for slide_index, slide in enumerate(prs.slides):
            text = self._slide_to_text(slide)
            pages.append(ParsedPage(
                page_number=slide_index + 1,
                text=text,
            ))

        return ParsedDocument(
            filename=file_path.name,
            pages=pages,
            total_pages=len(prs.slides),
        )

    def _slide_to_text(self, slide) -> str:
        """
        Extract all text from a single slide.
        Order: title (with # prefix) → remaining text boxes → speaker notes.
        """
        parts = []

        # Title — identified via slide.shapes.title
        title_shape = slide.shapes.title
        title_id = title_shape.shape_id if title_shape else None
        if title_shape and title_shape.has_text_frame:
            title = title_shape.text_frame.text.strip()
            if title:
                parts.append(f"# {title}")

        # All other text-bearing shapes (text boxes, content placeholders)
        for shape in slide.shapes:
            if shape.shape_id == title_id:
                continue
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(text)

        # Speaker notes
        if slide.has_notes_slide:
            notes_tf = slide.notes_slide.notes_text_frame
            if notes_tf:
                notes = notes_tf.text.strip()
                if notes:
                    parts.append(f"[Notes: {notes}]")

        return "\n\n".join(parts)


# Singleton instance
ppt_parser = PPTParser()
