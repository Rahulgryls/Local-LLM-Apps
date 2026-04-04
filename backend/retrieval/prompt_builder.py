"""
LAKO V2 — Prompt Builder

Assembles the final LLM prompt from a trimmed AssembledContext.
Returns (user_prompt, system_prompt) as a tuple so the caller can
pass them to Ollama's separate prompt / system fields.

Also builds the web-search prompt used when RAG is disabled.
"""

from retrieval.models import AssembledContext, WebResult

# ── System prompts ─────────────────────────────────────────────────────────────

_SYSTEM_EN = (
    "You are LAKO, Rabobank's internal knowledge assistant. "
    "Answer based ONLY on the provided document pages below. "
    "If information is not found in these pages, state clearly what is missing.\n\n"
    "Rules:\n"
    "- Cite your sources using [Document: filename, Page: N] format\n"
    "- If multiple documents provide relevant information, synthesize across them\n"
    "- For tables or numerical data, preserve the exact figures\n"
    "- Respond in English"
)

_SYSTEM_NL = (
    "Je bent LAKO, de interne kennisassistent van Rabobank. "
    "Beantwoord uitsluitend op basis van de onderstaande documentpagina's. "
    "Als informatie niet in deze pagina's staat, geef dan duidelijk aan wat ontbreekt.\n\n"
    "Regels:\n"
    "- Vermeld je bronnen als [Document: bestandsnaam, Pagina: N]\n"
    "- Als meerdere documenten relevante informatie bevatten, synthetiseer deze\n"
    "- Bewaar exacte cijfers uit tabellen of numerieke gegevens\n"
    "- Beantwoord in het Nederlands"
)

_WEB_SYSTEM_EN = (
    "You are LAKO, Rabobank's knowledge assistant. "
    "The user has asked a question that requires internet information. "
    "Answer concisely based on the search results below.\n\n"
    "Rules:\n"
    "- Cite sources as [Source: title](url)\n"
    "- Do not speculate beyond what the sources say\n"
    "- Respond in English"
)

_WEB_SYSTEM_NL = (
    "Je bent LAKO, de kennisassistent van Rabobank. "
    "De gebruiker stelt een vraag die actuele internetinformatie vereist. "
    "Beantwoord beknopt op basis van de onderstaande zoekresultaten.\n\n"
    "Regels:\n"
    "- Vermeld bronnen als [Bron: titel](url)\n"
    "- Speculeer niet buiten wat de bronnen vermelden\n"
    "- Beantwoord in het Nederlands"
)


def _system_prompt(language: str) -> str:
    return _SYSTEM_NL if language.lower().startswith("nl") else _SYSTEM_EN


def _web_system_prompt(language: str) -> str:
    return _WEB_SYSTEM_NL if language.lower().startswith("nl") else _WEB_SYSTEM_EN


# ── RAG prompt builder ─────────────────────────────────────────────────────────

def build_query_prompt(
    query:    str,
    context:  AssembledContext,
    language: str = "en",
) -> tuple[str, str]:
    """
    Build the (user_prompt, system_prompt) pair for a RAG query.

    The user_prompt contains all document pages grouped by document,
    followed by the question.  The system_prompt carries the LAKO
    identity and citation rules.

    Returns:
        (user_prompt, system_prompt)
    """
    # Group pages by document, preserving (doc_id, page_num) order
    by_doc: dict[str, list] = {}
    for page in context.pages:
        by_doc.setdefault(page.doc_id, []).append(page)

    sections: list[str] = ["--- DOCUMENT PAGES ---\n"]
    for doc_id, pages in by_doc.items():
        for page in pages:
            sections.append(f"=== {page.filename} — Page {page.page_num} ===")
            sections.append(page.raw_text)
            sections.append("=== END PAGE ===\n")

    sections.append("--- END DOCUMENT PAGES ---\n")
    sections.append(f"Question: {query}")

    user_prompt   = "\n".join(sections)
    system_prompt = _system_prompt(language)
    return user_prompt, system_prompt


# ── Web-search prompt builder ──────────────────────────────────────────────────

def build_web_prompt(
    query:       str,
    web_results: list[WebResult],
    language:    str = "en",
) -> tuple[str, str]:
    """
    Build the (user_prompt, system_prompt) pair for a web-search query.

    Returns:
        (user_prompt, system_prompt)
    """
    sections: list[str] = ["--- WEB RESULTS ---\n"]
    for i, r in enumerate(web_results, start=1):
        sections.append(f"[{i}] {r.title}")
        sections.append(f"URL: {r.url}")
        sections.append(r.snippet)
        sections.append("")

    sections.append("--- END WEB RESULTS ---\n")
    sections.append(f"Question: {query}")

    user_prompt   = "\n".join(sections)
    system_prompt = _web_system_prompt(language)
    return user_prompt, system_prompt
