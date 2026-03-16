import json
import logging
import re
from typing import Any, Generator

import requests
from openai import OpenAI

from api.config import Config
from api.services.search_service import semantic_search, get_all_by_source
from api.services.history_service import save_chat

logger = logging.getLogger(__name__)

MAX_CHUNK_LENGTH = 500
RELEVANCE_THRESHOLD = 1.5

CATEGORIES = [
    "atraso_entrega",
    "reembolso",
    "troca_endereco",
    "status_pedido",
    "duvida_produto",
    "dano_defeito",
    "pagamento",
    "cancelamento",
    "rastreamento",
    "outro",
]

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


def classify_question(question: str) -> str:
    categories_str = ", ".join(CATEGORIES)
    prompt = (
        f"Classify this customer support question into exactly ONE category.\n"
        f"Categories: {categories_str}\n"
        f"Question: {question}\n"
        f"Respond with ONLY the category name, nothing else."
    )

    try:
        if Config.is_openai_llm():
            client = _get_openai_client()
            response = client.chat.completions.create(
                model=Config.get_llm_model(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=20,
            )
            category = response.choices[0].message.content.strip().lower()
        else:
            resp = requests.post(
                f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": Config.get_llm_model(),
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 20},
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            category = data.get("message", {}).get("content", "outro").strip().lower()

        return category if category in CATEGORIES else "outro"
    except Exception as e:
        logger.warning("Classification failed: %s", e)
        return "outro"


def _sanitize_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"https?://[^\s\)]+", "[URL]", text)
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
    text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP]", text)
    text = re.sub(
        r"(?:Order\s*ID\s*#?\s*|Crowdox\s*Order\s*ID\s*#?\s*)\d+", "[ORDER_ID]", text
    )
    text = re.sub(r"#\d{5,}", "[TICKET_ID]", text)
    text = re.sub(r"\b\d{3}\.\d{3}\.\d{3}[-]\d{2}\b", "[CPF]", text)
    text = re.sub(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}[-]\d{2}\b", "[CNPJ]", text)
    text = re.sub(r"\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b", "[POSTAL_CODE]", text)
    text = re.sub(r"\b\d{5}[-]?\d{3}\b", "[CEP]", text)
    text = re.sub(r"\b\d{5}\b(?=\s*(?:USA|US|United States))", "[ZIP]", text)
    text = re.sub(r"[\+]?\d[\d\s\-\(\)]{8,}\d", "[PHONE]", text)

    text = re.sub(
        r"(?:Hi|Hello|Dear|Thanks|Thank you|Regards|Best regards|Kind regards|"
        r"Obrigado|Olá|Prezado|Caro|Att|Atenciosamente|Oi|OI|oi)\s*[,;.:!]?\s*"
        r"([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3})",
        lambda m: m.group(0).replace(m.group(1), "[NOME]"),
        text,
    )

    text = re.sub(
        r"(?:^---\s*\n\s*)([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3})",
        lambda m: m.group(0).replace(m.group(1), "[NOME]"),
        text,
        flags=re.MULTILINE,
    )

    text = re.sub(
        r"raised by\s+[A-Za-zÀ-ü\s]+\s*\([^)]*\)", "raised by [REMETENTE]", text
    )

    text = re.sub(
        r"raised by\s+[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)*",
        "raised by [REMETENTE]",
        text,
    )

    text = re.sub(
        r"^([A-ZÀ-Ü][a-zà-ü]{1,20}(?:\s+[A-ZÀ-Ü][a-zà-ü]{1,20}){0,3})\s*$",
        "[NOME]",
        text,
        flags=re.MULTILINE,
    )

    text = re.sub(
        r"([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2})\s+"
        r"(?:SALES|Sales|EXECUTIVE|Executive|MANAGER|Manager|SUPPORT|Support|"
        r"CUSTOMER SERVICE|Customer Service|ATENDIMENTO|Atendimento)",
        r"[NOME] ",
        text,
    )

    text = re.sub(
        r"(?:Att|ATT)\s*[;.,:]?\s*([A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2})",
        lambda m: m.group(0).replace(m.group(1), "[NOME]"),
        text,
    )

    text = re.sub(
        r"(?:Em|On)\s+\d{4}-\d{2}-\d{2}.*?escreveu:", "[EMAIL_ANTERIOR]", text
    )
    text = re.sub(
        r"On\s+\w+,\s+\w+\s+\d+,\s+\d{4}\s+at\s+\d+:\d+\s*(?:AM|PM).*?wrote:",
        "[EMAIL_ANTERIOR]",
        text,
    )

    text = re.sub(
        r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*\s+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Park|Blvd|Way|Rua|Avenida|Av)\b",
        "[ENDEREÇO]",
        text,
    )

    text = re.sub(
        r"(?:Observa[çc][õo]es?|Notes?|Obs|Nota|Observation|Remark|Observação)\s*:\s*[^\n]+",
        "[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"(?:PayPal|Paypal)\s+(?:you|me|us)\b",
        "enviar pagamento",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b\d{10,}\b", "[ID]", text)

    text = re.sub(
        r"-{5,}.*?(?:Due to high volume|contents of this email|confidential).*?(?:\n|$)",
        "[ASSINATURA_CORPORATIVA]",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return text


def _prepare_rag_context(question: str, max_chunks: int = 5) -> dict:
    if Config.is_openai_llm():
        model = Config.get_llm_model()
    else:
        model = Config.get_llm_model()

    ticket_chunks = semantic_search(question, limit=max_chunks, source="tickets")
    ticket_chunks = _filter_chunks(ticket_chunks)

    logistics_chunks = semantic_search(question, limit=1, source="logistics")
    logistics_chunks = _filter_chunks(logistics_chunks)

    voice_tone_docs = get_all_by_source("voice_tone")

    if not ticket_chunks and not logistics_chunks:
        return {"empty": True, "model": model}

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

    sanitized_tickets = [
        {
            "id": c["id"],
            "title": c["title"],
            "chunk": _sanitize_text(c["chunk"]),
            "distance": round(float(c["distance"]), 4),
        }
        for c in ticket_chunks
    ]

    return {
        "empty": False,
        "model": model,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "ticket_chunks": ticket_chunks,
        "logistics_chunks": logistics_chunks,
        "voice_tone_count": len(voice_tone_docs),
        "sources": {
            "tickets": sanitized_tickets,
            "logistics": _build_sources(logistics_chunks),
        },
    }


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    session_id: str = "",
) -> dict[str, Any]:
    ctx = _prepare_rag_context(question, max_chunks)

    if ctx.get("empty"):
        return {
            "question": question,
            "answer": "Não encontrei documentos relevantes na base de conhecimento.",
            "sources": {"tickets": [], "logistics": []},
            "model": ctx["model"],
            "category": "outro",
        }

    model = ctx["model"]

    try:
        if Config.is_openai_llm():
            client = _get_openai_client()
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ctx["system_prompt"]},
                    {"role": "user", "content": ctx["user_prompt"]},
                ],
                temperature=0.7,
                top_p=0.9,
                max_tokens=1024,
            )
            answer = response.choices[0].message.content.strip()
            tokens_in = response.usage.prompt_tokens
            tokens_out = response.usage.completion_tokens
        else:
            resp = requests.post(
                f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": ctx["system_prompt"]},
                        {"role": "user", "content": ctx["user_prompt"]},
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
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("message", {}).get("content", "").strip()
            tokens_in = data.get("prompt_eval_count", 0)
            tokens_out = data.get("eval_count", 0)
    except Exception as e:
        raise RuntimeError(f"Erro ao gerar resposta via {Config.LLM_PROVIDER}: {e}")

    category = classify_question(question)

    chat_id = 0
    if session_id:
        try:
            chat_id = save_chat(
                session_id=session_id,
                question=question,
                answer=answer,
                category=category,
                model=model,
                provider=Config.LLM_PROVIDER,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                sources_count=len(ctx["ticket_chunks"]) + len(ctx["logistics_chunks"]),
            )
        except Exception as e:
            logger.warning("Failed to save chat history: %s", e)

    logger.info(
        "RAG completed: provider=%s, question='%s', category=%s, tickets=%d, "
        "logistics=%d, model=%s, tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        category,
        len(ctx["ticket_chunks"]),
        len(ctx["logistics_chunks"]),
        model,
        tokens_in,
        tokens_out,
    )

    return {
        "question": question,
        "answer": answer,
        "sources": ctx["sources"],
        "model": model,
        "category": category,
        "chat_id": chat_id,
    }


def generate_rag_stream(
    question: str,
    max_chunks: int = 5,
    session_id: str = "",
) -> Generator[str, None, None]:
    ctx = _prepare_rag_context(question, max_chunks)
    model = ctx.get("model", Config.get_llm_model())
    category = classify_question(question)

    if ctx.get("empty"):
        yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': {'tickets': [], 'logistics': []}, 'model': model})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': 'Não encontrei documentos relevantes na base de conhecimento.'})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'chat_id': 0})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': ctx['sources'], 'model': model})}\n\n"

    full_answer = []
    tokens_in = 0
    tokens_out = 0

    try:
        if Config.is_openai_llm():
            client = _get_openai_client()
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ctx["system_prompt"]},
                    {"role": "user", "content": ctx["user_prompt"]},
                ],
                temperature=0.7,
                top_p=0.9,
                max_tokens=1024,
                stream=True,
                stream_options={"include_usage": True},
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_answer.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                if chunk.usage:
                    tokens_in = chunk.usage.prompt_tokens
                    tokens_out = chunk.usage.completion_tokens

        else:
            resp = requests.post(
                f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": ctx["system_prompt"]},
                        {"role": "user", "content": ctx["user_prompt"]},
                    ],
                    "stream": True,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 1024,
                        "num_ctx": 4096,
                    },
                },
                timeout=300,
                stream=True,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    if data.get("message", {}).get("content"):
                        token = data["message"]["content"]
                        full_answer.append(token)
                        yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                    if data.get("done"):
                        tokens_in = data.get("prompt_eval_count", 0)
                        tokens_out = data.get("eval_count", 0)

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return

    answer = "".join(full_answer)
    chat_id = 0
    if session_id:
        try:
            chat_id = save_chat(
                session_id=session_id,
                question=question,
                answer=answer,
                category=category,
                model=model,
                provider=Config.LLM_PROVIDER,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                sources_count=len(ctx["ticket_chunks"]) + len(ctx["logistics_chunks"]),
            )
        except Exception as e:
            logger.warning("Failed to save chat history: %s", e)

    logger.info(
        "RAG stream completed: provider=%s, question='%s', category=%s, "
        "tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        category,
        tokens_in,
        tokens_out,
    )

    yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"
