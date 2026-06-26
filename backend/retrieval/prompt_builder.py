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
    "You are LAKO, Rabobank's internal knowledge assistant.\n\n"
    "You will receive a set of document pages as evidence. "
    "Reason carefully across all pages before writing your answer.\n\n"
    "How to answer:\n"
    "1. Read every page provided before forming conclusions.\n"
    "2. For each part of the question, identify which page(s) hold the evidence "
    "and cite them inline as [Document: filename, Page: N].\n"
    "3. When the question asks about causes, effects, or connections between topics, "
    "trace the chain explicitly using evidence — do not assert relationships that "
    "the documents do not support.\n"
    "4. When synthesising across multiple chapters or pages, state HOW they connect "
    "rather than just listing each finding separately.\n"
    "5. Quote exact numbers, percentages, and table values — never paraphrase figures.\n"
    "6. If a part of the question cannot be answered from the provided pages, say so "
    "precisely: name what is missing and what the question was asking for.\n"
    "7. Use clear headings for each part of a multi-part question.\n\n"
    "Answer in English."
)

_SYSTEM_NL = (
    "Je bent LAKO, de interne kennisassistent van Rabobank.\n\n"
    "Je krijgt een set documentpagina's als bewijs. "
    "Redeneer zorgvuldig over alle pagina's voordat je jouw antwoord formuleert.\n\n"
    "Hoe te antwoorden:\n"
    "1. Lees elke aangeboden pagina voordat je conclusies trekt.\n"
    "2. Identificeer voor elk deel van de vraag welke pagina('s) het bewijs bevatten "
    "en citeer deze inline als [Document: bestandsnaam, Pagina: N].\n"
    "3. Wanneer de vraag gaat over oorzaken, gevolgen of verbanden tussen onderwerpen, "
    "beschrijf de keten expliciet op basis van bewijs — beweer geen relaties die de "
    "documenten niet ondersteunen.\n"
    "4. Leg bij synthese over meerdere hoofdstukken of pagina's uit HOE deze met elkaar "
    "verbonden zijn, in plaats van bevindingen alleen op te sommen.\n"
    "5. Citeer exacte getallen, percentages en tabelwaarden — parafraseer nooit cijfers.\n"
    "6. Als een deel van de vraag niet beantwoord kan worden vanuit de aangeboden pagina's, "
    "zeg dit dan precies: benoem wat ontbreekt en wat de vraag vroeg.\n"
    "7. Gebruik duidelijke koppen voor elk deel van een meerdelige vraag.\n\n"
    "Beantwoord in het Nederlands."
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
            header_trail = " > ".join(page.headers) if page.headers else ""
            page_label = f"=== {page.filename} — Page {page.page_num}"
            if header_trail:
                page_label += f"  [{header_trail}]"
            page_label += " ==="
            sections.append(page_label)
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
