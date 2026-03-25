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


CONTEXT_ANALYSIS_PROMPT = """You are a context analyzer for a customer support system of Creative Games Studio (CGS), a board game company.

CGS has multiple board game projects shipped to different regions worldwide.

Analyze the user's question AND the conversation history to determine if you have enough context to give a precise answer.

You MUST respond in valid JSON only, no markdown, no backticks:

If context is SUFFICIENT:
{"status": "ready", "project": "detected project or null", "region": "detected region or null", "language": "detected language code (pt or en)", "enhanced_query": "the question enriched with context from history"}

If context is MISSING:
{"status": "need_info", "missing": ["list of what's missing"], "language": "detected language code (pt or en)", "follow_up": "a friendly question in the SAME LANGUAGE as the FIRST user message asking for the missing info"}

CRITICAL RULES FOR CLASSIFICATION:

PERSONAL questions (status: "need_info" if project/region unknown):
These contain possessive pronouns or refer to a specific person's situation:
- "meu pedido", "minha entrega", "meu reembolso", "meu rastreamento"
- "my order", "my delivery", "my refund", "my tracking"
- "como está minha entrega?", "meu pedido está atrasado"
- "where is my order?", "what's the status of my delivery?"
- "quero trocar meu endereço", "quero cancelar meu pedido"
- Any question with "meu/minha/my" + order/delivery/shipment/pedido/entrega
- Any question asking about a SPECIFIC order status, tracking, or shipment
These ALWAYS need project AND region. If EITHER is missing, set status to "need_info".

GENERIC questions (status: "ready", no project/region needed):
These ask about policies, processes, or how to handle situations in general:
- "como funciona o reembolso?", "qual a política de troca?"
- "how does refund work?", "what's the return policy?"
- "como responder reclamações de atraso?"
- "o que fazer quando um cliente reclama de defeito?"
- Any question about CGS policies, processes, or general guidance

OTHER RULES:
- If the conversation history already contains project/region info, extract it and set status to "ready".
- The follow_up question must be concise, friendly, and list available options.
- Always respond in the same language as the user's question.
- Available projects: Drunagor, Dante, ForFun, Oathfall, Magnus, Frosthaven.
- Available regions: Brasil, Europa, EUA, Ásia, Oceania.
- When in doubt between personal and generic, choose "need_info" — it's better to ask than to guess wrong."""


def analyze_context(question: str, chat_history: list[dict] | None = None) -> dict:
    history_text = ""
    if chat_history:
        history_parts = []
        for msg in chat_history[-6:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            history_parts.append(f"{role}: {msg.get('content', '')}")
        history_text = "\n".join(history_parts)

    user_content = (
        f"CONVERSATION HISTORY:\n{history_text}\n\nCURRENT QUESTION: {question}"
        if history_text
        else f"CURRENT QUESTION: {question}"
    )

    try:
        if Config.is_openai_llm():
            client = _get_openai_client()
            response = client.chat.completions.create(
                model=Config.get_llm_model(),
                messages=[
                    {"role": "system", "content": CONTEXT_ANALYSIS_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            result_text = response.choices[0].message.content.strip()
        else:
            resp = requests.post(
                f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": Config.get_llm_model(),
                    "messages": [
                        {"role": "system", "content": CONTEXT_ANALYSIS_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0, "num_predict": 200},
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            result_text = data.get("message", {}).get("content", "{}").strip()

        result = json.loads(result_text)
        logger.info(
            "Context analysis: status=%s, question='%s'",
            result.get("status"),
            question[:50],
        )
        return result

    except Exception as e:
        logger.warning("Context analysis failed: %s — proceeding with ready", e)
        return {
            "status": "ready",
            "project": None,
            "region": None,
            "enhanced_query": question,
        }


def _sanitize_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"#yiv\d+[^\n]*", "", text)
    text = re.sub(
        r"\{[^}]*(?:margin|padding|border|display|height|width|font)[^}]*\}", "", text
    )
    text = re.sub(r"https?://[^\s\)]+", "", text)
    text = re.sub(
        r"(?:www\.)?[a-zA-Z0-9-]+\.(?:com|com\.br|org|net|io|app)(?:\.[a-z]{2,3})?(?:/[^\s]*)?",
        "",
        text,
    )
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "", text)
    text = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "", text)
    text = re.sub(r"(?:Crowdox\s*)?Order\s*ID\s*#?\s*\d+", "", text)
    text = re.sub(r"Pledge\s*(?:id|ID)\s*\w+", "", text)
    text = re.sub(
        r"(?:backer\s*(?:number|#|num)\s*(?:is\s*)?)?#\d{3,6}\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"#\d{5,}", "", text)
    text = re.sub(r"\b\d{3}\.\d{3}\.\d{3}[-]\d{2}\b", "", text)
    text = re.sub(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}[-]\d{2}\b", "", text)
    text = re.sub(r"\b[A-Z]{1,2}\d{1,2}\s?\d[A-Z]{2}\b", "", text)
    text = re.sub(r"\b\d{5}[-]?\d{3}\b", "", text)
    text = re.sub(r"[\+]?\d[\d\s\-\(\)]{8,}\d", "", text)
    text = re.sub(r"\$\d+[\d,.]*\s*(?:usd|USD)?", "", text)
    text = re.sub(r"@[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}", "", text)
    text = re.sub(
        r"(?:Hi|Hello|Dear|Thanks|Thank you|Regards|Best regards|Kind regards|Warm regards|"
        r"Many thanks|Obrigado|Olá|Prezado|Caro|Att|Atenciosamente|Oi|OI|oi|At\.te|Ei)\s*[,;.:!]?\s*"
        r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3}",
        "",
        text,
    )
    text = re.sub(
        r"(?:^---\s*\n\s*)[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,3}",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"raised by\s+[A-Za-zÀ-ü\s]+\s*\([^)]*\)", "", text)
    text = re.sub(r"raised by\s+[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+)*", "", text)
    text = re.sub(
        r"^[A-ZÀ-Ü][a-zà-üA-Z]{1,20}(?:\s+[A-ZÀ-Ü][a-zà-üA-Z]{1,20}){0,3}\s*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}\s+"
        r"(?:SALES|Sales|EXECUTIVE|Executive|MANAGER|Manager|SUPPORT|Support|"
        r"CUSTOMER SERVICE|Customer Service|ATENDIMENTO|Atendimento)",
        "",
        text,
    )
    text = re.sub(
        r"(?:Att|ATT|At\.te)\s*[;.,:]?\s*[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}",
        "",
        text,
    )
    text = re.sub(
        r"(?:Meu nome é|My name is|Me chamo|I am|I\'m)\s+[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:conversei com|falei com|com a|com o|sou a|sou o)\s+[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"[A-ZÀ-Ü][a-zà-ü]+\s+(?:referred|encaminhou|me passaram|passaram)",
        "",
        text,
    )
    text = re.sub(r"[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}\s+says:", "", text)
    text = re.sub(
        r"(?:De|From|To|Para|Enviado|Sent|Date|Subject|Assunto):.*?\n",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^--\s*\n\s*[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü][a-zà-ü]+){0,2}\s*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"Name:\*?\s*[A-ZÀ-Ü].*?\n", "", text)
    text = re.sub(
        r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*\s+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Park|Blvd|Way|Rua|Avenida|Av|"
        r"Flatts|Crescent|Close|Court|Place|Terrace)\b",
        "",
        text,
    )
    text = re.sub(
        r"(?:Avenida|Rua|Alameda|Travessa|Estrada|Rodovia)\s+(?:Dr\.?\s+)?[A-ZÀ-Ü][a-zà-ü]+(?:\s+[A-ZÀ-Ü]?[a-zà-ü]+)*(?:\s*,\s*(?:Number|Número|N[ºo°]?)?\s*\d+)?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?:my address is|meu endereço é|address to|endereço para)\s*:?\s*[^\n]+(?:\n[^\n]+)*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"[A-ZÀ-Ü][a-zà-ü]+,\s*[A-ZÀ-Ü][a-zà-ü\s]+/[A-Z]{2}\s*-?\s*(?:Brazil|Brasil)",
        "",
        text,
    )
    text = re.sub(r"Zip\s*Code\s*\d*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Number\s+\d+", "", text)
    text = re.sub(
        r"(?:United Kingdom|United States|UK|USA|Brazil|Brasil|Canada|Australia|Germany|France)\b",
        "",
        text,
    )
    text = re.sub(r"(?:Em|On)\s+\d{4}-\d{2}-\d{2}.*?escreveu:", "", text)
    text = re.sub(
        r"On\s+\w+,\s+\w+\s+\d+,\s+\d{4}\s+at\s+\d+:\d+\s*(?:AM|PM).*?wrote:", "", text
    )
    text = re.sub(
        r"-{5,}\s*Forwarded message\s*-{5,}.*?(?:\n\n|\Z)", "", text, flags=re.DOTALL
    )
    text = re.sub(
        r"Sent from (?:Yahoo Mail|my iPhone|my iPad|Mail for Windows|Samsung|Outlook).*",
        "",
        text,
    )
    text = re.sub(
        r"(?:Observa[çc][õo]es?|Notes?|Obs|Nota|Observation|Remark|Observação)\s*:\s*[^\n]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"-{5,}.*?(?:Due to high volume|contents of this email|confidential).*?(?:\n|$)",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"CREATIVE GAMES STUDIO", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(?:PayPal|Paypal)\s+(?:you|me|us|the)\b", "", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\b\d{10,}\b", "", text)
    text = re.sub(
        r"This is intended only.*?(?:prohibited|$)",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"\b(?:PSC|BGG)\b", "", text)
    text = re.sub(r"Continued in\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^.{1,2}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s\-\*=_\.,:;]{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\xa0]", " ", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def _prepare_rag_context(
    question: str,
    max_chunks: int = 5,
    project: str | None = None,
    region: str | None = None,
    category: str | None = None,
    language: str | None = None,
) -> dict:
    model = Config.get_llm_model()

    ticket_chunks = semantic_search(question, limit=max_chunks, source="tickets")
    ticket_chunks = _filter_chunks(ticket_chunks)

    has_context = bool(project or region)
    LOGISTICS_CATEGORIES = {"atraso_entrega", "rastreamento", "status_pedido"}
    include_logistics = has_context or (
        category in LOGISTICS_CATEGORIES if category else False
    )

    logistics_chunks = []
    if include_logistics:
        logistics_limit = 3 if project or region else 1
        logistics_chunks = semantic_search(
            question, limit=logistics_limit, source="logistics"
        )
        logistics_chunks = _filter_chunks(logistics_chunks)

        if project and logistics_chunks:
            filtered = [
                c
                for c in logistics_chunks
                if project.lower() in c.get("title", "").lower()
                or project.lower() in c.get("chunk", "").lower()
            ]
            if filtered:
                logistics_chunks = filtered

        if region and logistics_chunks:
            region_aliases = {
                "brazil": "brasil",
                "eua": "eua",
                "usa": "eua",
                "us": "eua",
                "europe": "europa",
                "asia": "ásia",
                "oceania": "oceania",
            }
            region_normalized = region_aliases.get(region.lower(), region.lower())
            filtered = [
                c
                for c in logistics_chunks
                if region_normalized in c.get("title", "").lower()
                or region_normalized in c.get("chunk", "").lower()
            ]
            if filtered:
                logistics_chunks = filtered

        if len(logistics_chunks) > 1:
            logistics_chunks = logistics_chunks[:1]

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

    context_hint = ""
    if project:
        context_hint += f"\nThe user is asking about project: {project}."
    if region:
        context_hint += f"\nThe user is in region: {region}."
    if language:
        lang_name = "Portuguese" if language == "pt" else "English"
        context_hint += f"\nYou MUST respond in {lang_name}. This is mandatory."

    system_prompt = (
        "You are a customer support assistant for Creative Games Studio (CGS), "
        "a board game company. Follow these rules strictly:\n\n"
        "VOICE TONE GUIDELINES (always follow this tone):\n"
        f"{voice_tone_text}\n\n"
        "RULES:\n"
        "1. The tickets provided are EXAMPLES of past support conversations. "
        "Use them as reference to craft a helpful response.\n"
        "2. Use the voice tone guidelines to shape HOW you respond.\n"
        "3. The logistics data shows current shipping status. Reference it ONLY if it matches "
        "the user's project and region. Do NOT mix data from different projects or regions.\n"
        "4. Be concise, direct and helpful. Go straight to the answer.\n"
        "5. NEVER include personal data in your response: no names (real or fictional), "
        "no emails, no addresses, no order IDs, no phone numbers. "
        "Do NOT sign with any name or title.\n"
        "6. NEVER add observations, notes, disclaimers or meta-commentary about "
        "the tickets or your process. Do NOT say which ticket you based your answer on. "
        "Do NOT add sections like 'Observação:', 'O que fazer em seguida?', or similar.\n"
        "7. ALWAYS respond in the SAME LANGUAGE as the user's FIRST message in the conversation. "
        "If the user started in English, respond in English even if later messages are in another language.\n"
        "8. If no relevant info is found, just say you couldn't find the information "
        "and suggest contacting support at customerservice@wearecgs.com."
        f"{context_hint}"
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


def generate_rag_stream(
    question: str,
    max_chunks: int = 5,
    session_id: str = "",
    chat_history: list[dict] | None = None,
) -> Generator[str, None, None]:
    model = Config.get_llm_model()

    analysis = analyze_context(question, chat_history)

    if analysis.get("status") == "need_info":
        follow_up = analysis.get("follow_up", "Poderia me dar mais detalhes?")
        category = classify_question(question)

        yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': {'tickets': [], 'logistics': []}, 'model': model, 'need_info': True})}\n\n"
        for word in follow_up.split(" "):
            yield f"data: {json.dumps({'type': 'token', 'content': word + ' '})}\n\n"

        chat_id = 0
        if session_id:
            try:
                chat_id = save_chat(
                    session_id=session_id,
                    question=question,
                    answer=follow_up,
                    category=category,
                    model=model,
                    provider=Config.LLM_PROVIDER,
                    tokens_in=0,
                    tokens_out=0,
                    sources_count=0,
                )
            except Exception as e:
                logger.warning("Failed to save chat history: %s", e)

        yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"
        return

    project = analysis.get("project")
    region = analysis.get("region")
    language = analysis.get("language")
    enhanced_query = analysis.get("enhanced_query", question)

    category = classify_question(question)
    ctx = _prepare_rag_context(
        enhanced_query,
        max_chunks,
        project=project,
        region=region,
        category=category,
        language=language,
    )

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
        "project=%s, region=%s, tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        category,
        project,
        region,
        tokens_in,
        tokens_out,
    )

    yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    session_id: str = "",
    chat_history: list[dict] | None = None,
) -> dict[str, Any]:
    analysis = analyze_context(question, chat_history)

    if analysis.get("status") == "need_info":
        follow_up = analysis.get("follow_up", "Poderia me dar mais detalhes?")
        category = classify_question(question)
        return {
            "question": question,
            "answer": follow_up,
            "sources": {"tickets": [], "logistics": []},
            "model": Config.get_llm_model(),
            "category": category,
            "chat_id": 0,
            "need_info": True,
        }

    project = analysis.get("project")
    region = analysis.get("region")
    language = analysis.get("language")
    enhanced_query = analysis.get("enhanced_query", question)

    ctx = _prepare_rag_context(
        enhanced_query,
        max_chunks,
        project=project,
        region=region,
        category=classify_question(question),
        language=language,
    )

    if ctx.get("empty"):
        return {
            "question": question,
            "answer": "Não encontrei documentos relevantes na base de conhecimento.",
            "sources": {"tickets": [], "logistics": []},
            "model": ctx["model"],
            "category": "outro",
            "chat_id": 0,
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

    return {
        "question": question,
        "answer": answer,
        "sources": ctx["sources"],
        "model": model,
        "category": category,
        "chat_id": chat_id,
    }
