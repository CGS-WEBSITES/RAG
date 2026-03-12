import logging
import re
from typing import Any

import requests
from openai import OpenAI

from api.config import Config
from api.services.search_service import semantic_search, get_all_by_source

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de otimização
# ---------------------------------------------------------------------------
MAX_CHUNK_LENGTH = 500
RELEVANCE_THRESHOLD = 1.5

_openai_client = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _openai_client


def _filter_chunks(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if c["distance"] < RELEVANCE_THRESHOLD]


def _build_sources(chunks: list[dict]) -> list[dict]:
    return [
        {
            "id": chunk["id"],
            "title": chunk["title"],
            "chunk": chunk["chunk"],
            "distance": round(float(chunk["distance"]), 4),
        }
        for chunk in chunks
    ]


# ---------------------------------------------------------------------------
# Filtro de dados sensíveis
# ---------------------------------------------------------------------------


def _sanitize_text(text: str) -> str:
    """Remove dados sensíveis do texto antes de enviar ao LLM e exibir ao usuário."""
    # HTML tags residuais
    text = re.sub(r"<[^>]+>", "", text)

    # URLs
    text = re.sub(r"https?://[^\s\)]+", "[URL]", text)

    # Emails
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)

    # IPs
    text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP]", text)

    # Order IDs / ticket IDs (Crowdox, Freshworks, etc)
    text = re.sub(
        r"(?:Order\s*ID\s*#?\s*|Crowdox\s*Order\s*ID\s*#?\s*)\d+", "[ORDER_ID]", text
    )
    text = re.sub(r"#\d{5,}", "[TICKET_ID]", text)

    # CPF / CNPJ
    text = re.sub(r"\b\d{3}\.\d{3}\.\d{3}[-]\d{2}\b", "[CPF]", text)
    text = re.sub(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}[-]\d{2}\b", "[CNPJ]", text)

    # Postal codes
    text = re.sub(r"\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b", "[POSTAL_CODE]", text)  # UK
    text = re.sub(r"\b\d{5}[-]?\d{3}\b", "[CEP]", text)  # Brasil
    text = re.sub(r"\b\d{5}\b(?=\s*(?:USA|US|United States))", "[ZIP]", text)  # USA

    # Telefones
    text = re.sub(r"[\+]?\d[\d\s\-\(\)]{8,}\d", "[PHONE]", text)

    # --- NOMES ---

    # Nomes após saudações (pt + en) — inclui variações com vírgula, ponto, dois pontos
    text = re.sub(
        r"(?:Hi|Hello|Dear|Thanks|Thank you|Regards|Best regards|Kind regards|"
        r"Obrigado|Olá|Prezado|Caro|Att|Atenciosamente|Oi|OI|oi)\s*[,;.:!]?\s*"
        r"([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3})",
        lambda m: m.group(0).replace(m.group(1), "[NOME]"),
        text,
    )

    # Nomes após "---" (separadores de thread de email) seguidos de nome
    text = re.sub(
        r"(?:^---\s*\n\s*)([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3})",
        lambda m: m.group(0).replace(m.group(1), "[NOME]"),
        text,
        flags=re.MULTILINE,
    )

    # "raised by Fulano (email)" ou "raised by Fulano"
    text = re.sub(
        r"raised by\s+[A-Za-zÀ-ü\s]+\s*\([^)]*\)", "raised by [REMETENTE]", text
    )
    text = re.sub(
        r"raised by\s+[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)*",
        "raised by [REMETENTE]",
        text,
    )

    # Nomes completos isolados em linhas (assinaturas) — 1 ou 2 nomes
    text = re.sub(
        r"^([A-ZÀ-Ü][a-zà-ü]{1,20}(?:\s+[A-ZÀ-Ü][a-zà-ü]{1,20}){0,3})\s*$",
        "[NOME]",
        text,
        flags=re.MULTILINE,
    )

    # Nomes antes de cargos (SALES EXECUTIVE, Customer Service, etc)
    text = re.sub(
        r"([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2})\s+"
        r"(?:SALES|Sales|EXECUTIVE|Executive|MANAGER|Manager|SUPPORT|Support|"
        r"CUSTOMER SERVICE|Customer Service|ATENDIMENTO|Atendimento)",
        r"[NOME] ",
        text,
    )

    # Att; / Att. / Att, seguido de nome
    text = re.sub(
        r"(?:Att|ATT)\s*[;.,:]?\s*([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2})",
        lambda m: m.group(0).replace(m.group(1), "[NOME]"),
        text,
    )

    # --- FIM NOMES ---

    # Citações de emails anteriores
    text = re.sub(
        r"(?:Em|On)\s+\d{4}-\d{2}-\d{2}.*?escreveu:", "[EMAIL_ANTERIOR]", text
    )
    text = re.sub(
        r"On\s+\w+,\s+\w+\s+\d+,\s+\d{4}\s+at\s+\d+:\d+\s*(?:AM|PM).*?wrote:",
        "[EMAIL_ANTERIOR]",
        text,
    )

    # Endereços (número + rua, pt + en)
    text = re.sub(
        r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*\s+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Park|Blvd|Way|Rua|Avenida|Av)\b",
        "[ENDEREÇO]",
        text,
    )

    # Campos de observação
    text = re.sub(
        r"(?:Observa[çc][õo]es?|Notes?|Obs|Nota|Observation|Remark|Observação)\s*:\s*[^\n]+",
        "[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )

    # PayPal references
    text = re.sub(
        r"(?:PayPal|Paypal)\s+(?:you|me|us)\b",
        "enviar pagamento",
        text,
        flags=re.IGNORECASE,
    )

    # Facebook IDs e identificadores numéricos longos
    text = re.sub(r"\b\d{10,}\b", "[ID]", text)

    # Blocos de assinatura corporativa (linhas com ---- seguidas de disclaimer)
    text = re.sub(
        r"-{5,}.*?(?:Due to high volume|contents of this email|confidential).*?(?:\n|$)",
        "[ASSINATURA_CORPORATIVA]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return text

    return text


# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------


def _openai_generate(model: str, system_prompt: str, user_prompt: str) -> dict:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        top_p=0.9,
        max_tokens=1024,
    )
    return {
        "answer": response.choices[0].message.content.strip(),
        "tokens_in": response.usage.prompt_tokens,
        "tokens_out": response.usage.completion_tokens,
    }


def _ollama_generate(model: str, system_prompt: str, user_prompt: str) -> dict:
    try:
        response = requests.post(
            f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "num_predict": 1024,
                    "num_ctx": 4096,
                },
            },
            timeout=300,
        )
        response.raise_for_status()
    except requests.ConnectionError:
        raise ConnectionError(
            f"Ollama indisponível em {Config.OLLAMA_HOST}. "
            "Verifique se o container está rodando com --profile ollama."
        )
    except requests.Timeout:
        raise RuntimeError("Timeout gerando resposta. Tente novamente.")

    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    message = data.get("message", {})
    return {
        "answer": message.get("content", "No response from model.").strip(),
        "tokens_in": data.get("prompt_eval_count", 0),
        "tokens_out": data.get("eval_count", 0),
    }


# ---------------------------------------------------------------------------
# RAG principal — endpoint unificado
# ---------------------------------------------------------------------------


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    model: str | None = None,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> dict[str, Any]:
    if Config.is_openai_llm():
        model = model or Config.get_llm_model()
    else:
        model = Config.get_llm_model()

    # 1. Tickets relevantes (base principal)
    ticket_chunks = semantic_search(question, limit=max_chunks, source="tickets")
    ticket_chunks = _filter_chunks(ticket_chunks)

    # 2. Logística relevante (1 resultado)
    logistics_chunks = semantic_search(question, limit=1, source="logistics")
    logistics_chunks = _filter_chunks(logistics_chunks)

    # 3. Tom de voz completo
    voice_tone_docs = get_all_by_source("voice_tone")

    if not ticket_chunks and not logistics_chunks:
        return {
            "question": question,
            "answer": "Não encontrei documentos relevantes na base de conhecimento.",
            "sources": {"tickets": [], "logistics": [], "voice_tone": []},
            "model": model,
        }

    # --- Montar contexto para o LLM ---

    voice_tone_text = "\n".join(
        f"- {doc['title']}: {doc['content']}" for doc in voice_tone_docs
    )

    context_parts = []
    for i, chunk in enumerate(ticket_chunks, 1):
        text = _sanitize_text(chunk["chunk"])
        if len(text) > MAX_CHUNK_LENGTH:
            text = text[:MAX_CHUNK_LENGTH] + "..."
        context_parts.append(f"[Ticket Exemplo {i} - {chunk['title']}]:\n{text}")

    for i, chunk in enumerate(logistics_chunks, 1):
        text = chunk["chunk"]
        if len(text) > MAX_CHUNK_LENGTH:
            text = text[:MAX_CHUNK_LENGTH] + "..."
        context_parts.append(f"[Logística {i} - {chunk['title']}]:\n{text}")

    context = "\n\n".join(context_parts)

    system_prompt = (
        "You are a customer support assistant for Creative Games Studio (CGS), "
        "a board game company. Follow these rules strictly:\n\n"
        "VOICE TONE GUIDELINES (always follow this tone):\n"
        f"{voice_tone_text}\n\n"
        "RULES:\n"
        "1. The tickets provided are EXAMPLES of past support conversations. "
        "Use them as reference to craft a helpful response.\n"
        "2. Use the voice tone guidelines to shape HOW you respond.\n"
        "3. The logistics data shows current shipping status. Reference it if relevant.\n"
        "4. Be concise, direct and helpful. Go straight to the answer.\n"
        "5. NEVER include personal data in your response: no names (real or fictional), "
        "no emails, no addresses, no order IDs, no phone numbers. "
        "Do NOT sign with any name or title.\n"
        "6. NEVER add observations, notes, disclaimers or meta-commentary about "
        "the tickets or your process. Do NOT say which ticket you based your answer on. "
        "Do NOT add sections like 'Observação:', 'O que fazer em seguida?', or similar.\n"
        "7. Always respond in the same language as the question.\n"
        "8. If no relevant info is found, just say you couldn't find the information "
        "and suggest contacting support at customerservice@wearecgs.com."
    )

    user_prompt = f"DOCUMENTS:\n{context}\n\nQUESTION: {question}"

    try:
        if Config.is_openai_llm():
            result = _openai_generate(model, system_prompt, user_prompt)
        else:
            result = _ollama_generate(model, system_prompt, user_prompt)
    except (ConnectionError, RuntimeError):
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error("LLM API error [%s]: %s", Config.LLM_PROVIDER, error_msg)
        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            raise ConnectionError(
                "OpenAI API key inválida. Verifique OPENAI_API_KEY no .env"
            )
        raise RuntimeError(
            f"Erro ao gerar resposta via {Config.LLM_PROVIDER}: {error_msg}"
        )

    # --- Montar resposta com sources separadas ---

    sanitized_tickets = [
        {
            "id": c["id"],
            "title": c["title"],
            "chunk": _sanitize_text(c["chunk"]),
            "distance": round(float(c["distance"]), 4),
        }
        for c in ticket_chunks
    ]

    logger.info(
        "RAG completed: provider=%s, question='%s', tickets=%d, logistics=%d, "
        "voice_tone=%d, model=%s, tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        len(ticket_chunks),
        len(logistics_chunks),
        len(voice_tone_docs),
        model,
        result["tokens_in"],
        result["tokens_out"],
    )

    return {
        "question": question,
        "answer": result["answer"],
        "sources": {
            "tickets": sanitized_tickets,
            "logistics": _build_sources(logistics_chunks),
        },
        "model": model,
    }
