import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Generator

import requests
from openai import OpenAI

from api.config import Config
from api.services.search_service import (
    semantic_search,
    get_all_by_source,
    get_logistics_by_project_region,
    search_manual_segments,
    search_keywords,
)
from api.services.history_service import save_chat
from api.services.character_prompts import get_character_prompt, get_character_name

import threading

logger = logging.getLogger(__name__)

# Smooth out peak CPU/RAM spikes by limiting concurrent heavy RAG pipelines to 2
_RAG_CONCURRENCY_SEMAPHORE = threading.Semaphore(2)

MAX_CHUNK_LENGTH = 500
RELEVANCE_THRESHOLD = 0.68
MAX_REFINEMENT_ROUNDS = 2
SUPPORT_URL = "https://newaccount1620866477944.freshdesk.com/support/tickets/new"
LOGISTICS_CONTEXT_CATEGORIES = {
    "atraso_entrega",
    "status_pedido",
    "rastreamento",
}

GLOBAL_RESPONSE_STYLE = """
RESPONSE STYLE (strict):
- DO NOT BE WORDY. Answer concisely and directly.
- STRICT KNOWLEDGE BASE ONLY (NO EXTERNAL RPG RULES): You MUST answer strictly and exclusively using the provided official rulebook excerpts, keyword definitions, support tickets, or logistics status data. NEVER use external or generic RPG knowledge (such as D&D, Pathfinder, standard d20 mechanics, general TTRPG rules, or external board game tropes). If the requested information is not explicitly present in the provided context, state clearly that you could not find it in the official documents.
- On technical, rule, or support questions, answer IMMEDIATELY without preambles, greetings, or filler sentences.
- Do NOT use dramatic preambles, ceremonial openings, greeting phrases ("Olá!", "Greetings traveler"), or restatements of the user's question.
- Do NOT add decorative closing lines after the practical answer.
- Do NOT translate shipping/support facts or game mechanics into fantasy metaphors. Use plain, accurate terms.
- Prefer 1 short paragraph or direct bullet points.
- If the user asks a simple question, answer it immediately without unrequested context.
- If the user is confused, answer with clear step-by-step instructions.
- For Discord, keep the answer easy to read on a phone.
"""

GAME_RULES_RESPONSE_STYLE = """
GAME RULES RESPONSE STYLE (STRICT - ZERO FLUFF, STRICT CLOSED WORLD, ERRATA PRIORITY):
- STRICT CLOSED-WORLD RULE: Answer strictly and exclusively using the provided manual excerpts and keyword definitions. NEVER use generic RPG rules (such as D&D, Pathfinder, generic d20 mechanics, spell slots, saving throws, advantage/disadvantage, or tabletop tropes) to answer.
- ABSOLUTE ZERO EXTRAPOLATION: If the provided excerpts do not explicitly contain or explain the rule for the queried scenario, state clearly: "I could not find this specific rule in the manual." Do NOT guess, assume, or extrapolate using generic RPG logic.
- ZERO FLUFF / ZERO PREAMBLE: Start IMMEDIATELY with the direct rule, definition, or mechanic.
- MANDATORY RESPONSE LANGUAGE RULE: You MUST write your entire response strictly in the requested language (e.g. English). NEVER respond in Portuguese if the request specifies English, even if the user asks their question in Portuguese.
- CHRONICLES OF DRUNAGOR TERMINOLOGY RULES (DO NOT CONFUSE CUBES VS DICE):
  - **Action Cubes (AC)**: Colored cubes (Red, Yellow, Green, Blue, Wild) spent by Heroes on Hero board slots to perform actions. They are NOT rolled like dice.
  - **Dice / D20**: Attacks and skill checks roll the 20-sided die (D20), NOT Action Cubes.
  - **Red Action Cubes**: Used for Ranged actions (up to 1 Area away).
  - **Yellow Action Cubes**: Used for Melee actions (adjacent square).
  - **Curse Cubes (CC)**: Black cubes that block Hero/Role skill slots. A Hero with 6 Curse Cubes becomes Corrupted (Adventure ends).
  - **Trauma Cubes (TC)**: Purple cubes that block Hero/Role skill slots. A Hero with 2 Trauma Cubes is killed (Adventure ends).
- If asked about a basic term or rule (e.g. "what is a trauma cube?", "como funciona o cubo de maldição?"), give a clear, direct, and complete explanation step-by-step using the manual excerpts and keyword definitions.
- If the question is simple (e.g. player count, session duration), give a direct 1-2 sentence response.
- ABSOLUTE ERRATA PRIORITY: If an ERRATA / OFFICIAL CLARIFICATION chunk is present in the provided context, it OVERRIDES base rulebook text.
- STRICT ZERO HALLUCINATION: Do NOT invent, speculate, or extrapolate rules. If the excerpts do not explicitly contain the rule, state clearly: "I could not find this specific rule in the manual."
- End with page references when page data is available (e.g. "Page 12 of the manual.").
"""

LOGISTICS_RESPONSE_STYLE = """
LOGISTICS RESPONSE STYLE (STRICT - ZERO FLUFF):
- Start with at most ONE single short character impact/intro phrase (e.g. "Greetings from the abyss! Here is your update:").
- Immediately give the exact logistics status, carrier, ETA, and backer notes in 2-3 direct lines or simple bullet points.
- Do NOT use fantasy metaphors for shipping or logistics terms (use plain terms: shipped, delayed, warehouse, carrier, tracking).
- Do NOT add decorative closing statements, dramatic lore, or fluff text after the facts.
- ZERO HALLUCINATION & CLOSED WORLD: State ONLY the exact facts present in the provided logistics status data. Never invent shipping updates or use external information.
- INDIVIDUAL ORDER / TRACKING / PLEDGE NUMBER RULE: Our AI assistant ONLY has access to regional/macro shipping status updates and CANNOT access personal pledge IDs, tracking numbers, or individual order details. If the user provides a tracking number, pledge number, order ID, or asks about their specific individual package status (e.g. "my order", "my tracking #", "my pledge", "meu pedido #"), explicitly explain that the AI only handles regional status, and direct them to open a support ticket to check individual pledge/tracking details.
"""

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
    "game_rules",
    "chitchat",
    "outro",
]

_openai_client = None

PROJECT_ALIASES = {
    "Drunagor": ("drunagor", "chronicles of drunagor", "cod", "aod"),
    "Dante": ("dante", "inferno"),
    "Battleforge": ("battleforge",),
    "Forfun": ("forfun", "for fun"),
}

GAME_RULE_TERMS = (
    "attack",
    "attacks",
    "attacking",
    "melee",
    "counter attack",
    "counterattack",
    "fumble",
    "damage",
    "defense",
    "defence",
    "dice",
    "die",
    "cube",
    "d20",
    "rule",
    "rules",
    "setup",
    "skill",
    "ability",
    "monster",
    "turn",
    "round",
    "combat",
    "how do i",
    "how to",
    "what is",
    "what does",
    "meaning",
    "definition",
    "keyword",
    "keywords",
    "ataque",
    "atacar",
    "corpo a corpo",
    "contra ataque",
    "contra-ataque",
    "dano",
    "defesa",
    "dado",
    "dados",
    "cubo",
    "cubos",
    "regra",
    "regras",
    "preparacao",
    "preparação",
    "habilidade",
    "monstro",
    "turno",
    "rodada",
    "combate",
    "como faco",
    "como faço",
    "o que e",
    "o que é",
    "o que significa",
    "significa",
    "significam",
    "significado",
    "termo",
    "termos",
    "palavra chave",
    "palavras chave",
    "palavra-chave",
    "palavras-chave",
)


def _detect_language(text: str) -> str:
    client = _get_openai_client()
    try:
        response = client.chat.completions.create(
            model=Config.get_llm_model(),
            messages=[
                {
                    "role": "user",
                    "content": f"Detect the language of this text and respond with ONLY the ISO 639-1 code (e.g. pt, en, es, de, fr). Text: {text[:100]}",
                }
            ],
            max_tokens=5,
            temperature=0,
        )
        lang = response.choices[0].message.content.strip().lower()[:2]
        return lang if lang else "en"
    except Exception:
        return "en"


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY não configurada no .env")
        _openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _openai_client


def _build_history_messages(
    chat_history: list[dict] | None,
    current_question: str,
    limit: int = 4,
) -> list[dict[str, str]]:
    if not chat_history:
        return []

    messages = []
    current = (current_question or "").strip()
    for msg in chat_history[-limit:]:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if not content or role not in ("user", "assistant"):
            continue
        if role == "user" and current and content == current:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _missing_logistics_context(
    project: str | None,
    region: str | None,
    product_language: str | None,
) -> list[str]:
    missing = []
    if not project:
        missing.append("project")
    if not region:
        missing.append("region")
    if not product_language:
        missing.append("product_language")
    return missing


def _build_logistics_follow_up(language: str | None, missing: list[str]) -> str:
    lang = (language or "en").lower()
    labels = {
        "pt": {
            "project": "projeto",
            "region": "região",
            "product_language": "idioma do produto/pacote",
            "prefix": "Para eu verificar logística sem chutar, me diga",
            "examples": "Exemplo: Drunagor, EUA, espanhol.",
        },
        "en": {
            "project": "project",
            "region": "region",
            "product_language": "product/package language",
            "prefix": "To check logistics without guessing, please tell me",
            "examples": "Example: Drunagor, USA, Spanish.",
        },
    }
    text = labels.get(lang, labels["en"])
    items = ", ".join(text[item] for item in missing)
    return f"{text['prefix']}: {items}. {text['examples']}"


def _logistics_mentions_product_language(chunk: dict, product_language: str | None) -> bool:
    if not product_language:
        return True
    aliases = {
        "en": ["english", "inglês", "ingles", "en"],
        "english": ["english", "inglês", "ingles", "en"],
        "es": ["spanish", "español", "espanhol", "es"],
        "spanish": ["spanish", "español", "espanhol", "es"],
        "pt": ["portuguese", "português", "portugues", "pt"],
        "portuguese": ["portuguese", "português", "portugues", "pt"],
        "de": ["german", "deutsch", "alemão", "alemao", "de"],
        "german": ["german", "deutsch", "alemão", "alemao", "de"],
        "fr": ["french", "français", "frances", "francês", "fr"],
        "french": ["french", "français", "frances", "francês", "fr"],
        "it": ["italian", "italiano", "it"],
        "italian": ["italian", "italiano", "it"],
        "pl": ["polish", "polski", "polonês", "polones", "pl"],
        "polish": ["polish", "polski", "polonês", "polones", "pl"],
    }
    requested = product_language.strip().lower()
    terms = aliases.get(requested, [requested])
    text = f"{chunk.get('title', '')}\n{chunk.get('chunk', '')}".lower()
    language_markers = ("idioma", "língua", "language", "version", "versão")
    return any(marker in text and term in text for marker in language_markers for term in terms)


def _is_specific_pledge_status_question(question: str) -> bool:
    text = (question or "").lower()
    personal_terms = (
        "my order",
        "my package",
        "my pledge",
        "my shipment",
        "my delivery",
        "my tracking",
        "where is my",
        "status of my",
        "meu pedido",
        "minha encomenda",
        "meu pacote",
        "minha pledge",
        "minha entrega",
        "meu rastreamento",
        "onde esta meu",
        "onde está meu",
        "cadê meu",
        "cade meu",
        "status do meu",
    )
    tracking_terms = ("tracking number", "codigo de rastreio", "código de rastreio")
    return any(term in text for term in personal_terms + tracking_terms)


def _with_support_fallback(message: str, language: str | None) -> str:
    lang = (language or "en").lower()
    suffixes = {
        "pt": f"Se precisar de ajuda com um caso específico, abra um chamado no suporte: {SUPPORT_URL}",
        "en": f"If you need help with a specific case, please open a support ticket: {SUPPORT_URL}",
        "es": f"Si necesitas ayuda con un caso específico, abre un ticket de soporte: {SUPPORT_URL}",
        "de": f"Wenn du Hilfe zu einem bestimmten Fall brauchst, eröffne bitte ein Support-Ticket: {SUPPORT_URL}",
        "fr": f"Si vous avez besoin d'aide pour un cas précis, ouvrez un ticket support : {SUPPORT_URL}",
        "it": f"Se hai bisogno di aiuto per un caso specifico, apri un ticket di supporto: {SUPPORT_URL}",
    }
    suffix = suffixes.get(lang, suffixes["en"])
    return f"{message}\n\n{suffix}"


def _detect_project_from_text(text: str) -> str | None:
    normalized = (text or "").lower()
    for project, aliases in PROJECT_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return project
    return None


def _looks_like_chitchat(text: str) -> bool:
    import unicodedata
    decomposed = unicodedata.normalize('NFKD', text or "")
    normalized = "".join(c for c in decomposed if not unicodedata.combining(c))
    clean = re.sub(r"[^\w\s]", "", normalized).strip().lower()
    greetings = {
        "ola", "oi", "bom dia", "boa tarde", "boa noite", "tudo bem", "como vai", 
        "opa", "e ai", "eae", "hello", "hi", "hey", "how are you", "good morning", 
        "good afternoon", "good evening", "obrigado", "obrigada", "thanks", 
        "thank you", "valeu", "tchau", "bye", "tudo bom", "como voce esta", 
        "quem e voce", "who are you", "o que voce e", "what are you", "salve", 
        "qual seu nome", "qual e o seu nome", "whats your name"
    }
    if clean in greetings:
        return True
    prefixes = {"ola", "oi", "hello", "hi", "hey", "salve", "opa", "eae"}
    suffixes = {"tudo bem", "tudo bom", "como vai", "como voce esta", "how are you", "bom dia", "boa tarde", "boa noite"}
    for pref in prefixes:
        if clean.startswith(pref + " "):
            suff = clean[len(pref):].strip()
            if suff in suffixes:
                return True
    return False


def _looks_like_game_rules_question(question: str) -> bool:
    text = (question or "").lower()
    if not text:
        return False

    # If the question contains logistics-related terms, we shouldn't force it to game rules
    logistics_terms = (
        "logistica", "logística", "logistics",
        "entrega", "entregas", "delivery", "deliveries", "entregar",
        "envio", "envios", "shipping", "shipment", "shipments", "shipped", "enviar", "enviado",
        "rastreamento", "rastreio", "tracking", "rastrear",
        "pledge", "pedido", "pedidos", "order", "orders",
        "atraso", "atrasos", "delay", "delays", "atrasado",
        "reembolso", "reembolsos", "refund", "refunds",
        "troca de endereco", "troca de endereço", "address change", "change address", "endereço", "endereco", "address",
        "pagamento", "pagamentos", "payment", "payments",
        "cancelamento", "cancelamentos", "cancel", "cancellation", "cancellations",
        "porto", "port", "hubs", "hub", "warehouse", "transportadora", "carrier"
    )
    if any(term in text for term in logistics_terms):
        return False

    if any(term in text for term in GAME_RULE_TERMS):
        return True
    if re.search(r"\b(d|dado|dice)\s*20\b", text):
        return True
    try:
        kw_matches = search_keywords(text, limit=1)
        if kw_matches and kw_matches[0]["distance"] <= 0.6:
            return True
    except Exception:
        pass
    return False


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
    if _looks_like_chitchat(question):
        return "chitchat"

    if _looks_like_game_rules_question(question):
        return "game_rules"

    categories_str = ", ".join(CATEGORIES)
    prompt = (
        f"Classify this customer support question into exactly ONE category.\n"
        f"Categories: {categories_str}\n\n"
        f"Category definitions:\n"
        f"- game_rules: questions about how to play the game, game mechanics, rules, components, setup, gameplay, abilities, skills, monsters, dungeons, campaigns, characters, cards, tokens, dice. Do NOT classify shipping, delivery, logistics, or fulfillment queries here. Examples: 'How does the Darkness work?', 'Como funciona a Escuridão?', 'What is a Berserker Spirit?', 'Quantos jogadores podem jogar?'\n"
        f"- atraso_entrega: delayed orders, deliveries, shipping rules, delivery rules, or general logistics rules (e.g., 'regras de envio', 'regras de entrega para o Brasil')\n"
        f"- reembolso: refund requests\n"
        f"- troca_endereco: address changes\n"
        f"- status_pedido: order status inquiries, general logistics/fulfillment updates, shipping status, carrier status, package tracking status (e.g. 'Qual a logística do Dante na Europa?', 'How is shipping status in USA?')\n"
        f"- duvida_produto: general product questions (NOT game rules)\n"
        f"- dano_defeito: damaged or defective items\n"
        f"- pagamento: payment issues\n"
        f"- cancelamento: order cancellations\n"
        f"- rastreamento: shipment tracking, tracking numbers\n"
        f"- chitchat: casual greetings, pleasantries, small talk, politeness, or simple conversational messages (e.g. 'Olá', 'Hello', 'Good morning', 'Tudo bem?', 'Como vai?', 'Obrigado', 'Who are you?', 'Quem é você?').\n"
        f"- outro: anything else\n\n"
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
{"status": "ready", "project": "detected project or null", "region": "detected region or null", "product_language": "detected product/package language or null", "language": "ISO 639-1 language code of the FIRST user message (e.g. pt, en, es, de, fr, it, ja, zh)", "enhanced_query": "the question enriched with context from history"}

If context is MISSING:
{"status": "need_info", "missing": ["list of what's missing"], "language": "ISO 639-1 language code of the FIRST user message", "follow_up": "a friendly question in the SAME LANGUAGE as the FIRST user message asking for the missing info"}

CRITICAL RULES FOR CLASSIFICATION:

PERSONAL questions (status: "need_info" if project, region, or product language is unknown):
These contain possessive pronouns or refer to a specific person's situation:
- "meu pedido", "minha entrega", "meu reembolso", "meu rastreamento"
- "my order", "my delivery", "my refund", "my tracking"
- "como está minha entrega?", "meu pedido está atrasado"
- "where is my order?", "what's the status of my delivery?"
- "quero trocar meu endereço", "quero cancelar meu pedido"
- Any question with "meu/minha/my" + order/delivery/shipment/pedido/entrega
- Any question asking about a SPECIFIC order status, tracking, or shipment
These ALWAYS need project, region, and product/package language confirmed. If ANY is missing, set status to "need_info".
Product/package language means the language/version of the pledged product (English, Spanish, German, French, Portuguese, etc.), NOT the language the user is writing in.
IMPORTANT: Even if the user mentions a project name in their message (e.g. "meu pedido Battleforge"), that does NOT count as complete context — you must still ask for the missing region and/or product language. Project, region, and product language must all be explicitly confirmed before answering personal questions.

GAME RULES questions (how to play, mechanics, setup, rules, components):
- If project is known (from payload or history): status = "ready"
- If project is UNKNOWN: status = "need_info", ask which game they want to know about
- Available game projects with rulebooks: Drunagor, Battleforge, Dante
- follow_up example: "Which game are you asking about? We have rulebooks for Drunagor and Battleforge."

GREETINGS / CHITCHAT / CASUAL CONVERSATION (status: "ready", no project/region/product language needed):
These are simple greetings, pleasantries, small talk, or questions about who you are:
- "olá", "oi", "hello", "hi", "bom dia", "tudo bem?", "como vai?"
- "who are you?", "quem é você?", "what is your name?", "qual seu nome?"
- "thanks", "obrigado", "valeu"
These are always "ready" because they do not require any project, region, or product language to be answered.

GENERIC questions (status: "ready", no project/region needed):
These ask about policies, processes, or how to handle situations in general:
- "como funciona o reembolso?", "qual a política de troca?"
- "how does refund work?", "what's the return policy?"
- "como responder reclamações de atraso?"
- "o que fazer quando um cliente reclama de defeito?"
- Any question about CGS policies, processes, or general guidance

OTHER RULES:
- If the conversation history already contains project, region, or product/package language, extract it and set status to "ready" only when the required fields for the question type are present.
- FOLLOW-UP QUESTIONS: If the user asks something short like "and in Europe?", "what about refunds?", "and for Dante?", look at the conversation history to understand the full context. Combine the follow-up with previous context in the enhanced_query. For example, if the user previously asked about Drunagor delivery in Brazil and now asks "and in Europe?", the enhanced_query should be something like "delivery status for Drunagor in Europe".
- If a follow-up changes the project or region, update those fields accordingly.
- The follow_up question must be concise, friendly, and list available options.
- Always respond in the same language as the user's FIRST question.
- Available projects: Drunagor, Dante, ForFun, Oathfall, Magnus, Frosthaven, Battleforge.
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
        r"[A-ZÀ-Ü][a-zà-ü]+\s+(?:referred|encaminhou|me passaram|passaram)", "", text
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
    product_language: str | None = None,
    category: str | None = None,
    language: str | None = None,
) -> dict:
    model = Config.get_llm_model()

    if category == "chitchat":
        character_prompt = get_character_prompt(project, region)
        LANG_NAMES = {
            "pt": "Portuguese",
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "fr": "French",
            "it": "Italian",
            "ja": "Japanese",
            "zh": "Chinese",
            "ko": "Korean",
            "ru": "Russian",
            "nl": "Dutch",
            "pl": "Polish",
        }
        response_language_rule = "- ALWAYS respond in the SAME LANGUAGE as the user's question."
        if language:
            lang_name = LANG_NAMES.get(language, language.upper())
            response_language_rule = f"- ALWAYS respond in {lang_name}. This is mandatory, even if the user writes in another language."

        if character_prompt:
            system_prompt = (
                f"{character_prompt}\n\n"
                "CHITCHAT RESPONSE STYLE (STRICT):\n"
                "- You are talking to a player/user who is greeting you or initiating a casual conversation.\n"
                "- Respond naturally and warmly, fully in character.\n"
                "- Keep the response brief (1-3 sentences) and ask how you can help them in character.\n"
                "- Do NOT retrieve rules or logistics. Do NOT mention any files or tickets.\n"
                f"{response_language_rule}"
            )
        else:
            system_prompt = (
                "You are a friendly customer support assistant for Creative Games Studio (CGS).\n\n"
                "CHITCHAT RESPONSE STYLE (STRICT):\n"
                "- Respond naturally, warmly, and politely to the user's greeting/pleasantry.\n"
                "- Keep it very brief (1-2 sentences) and ask how you can help them.\n"
                "- Do NOT mention rules or logistics. Do NOT mention any files or tickets.\n"
                f"{response_language_rule}"
            )

        return {
            "empty": False,
            "context": "",
            "sources": {"tickets": [], "logistics": []},
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": f"GREETING/CHITCHAT: {question}",
            "ticket_chunks": [],
            "logistics_chunks": [],
            "category": category,
        }

    # If game_rules category and project is set, search keywords first then manual segments
    if category == "game_rules" and project:
        keyword_chunks = search_keywords(question, project=project, limit=3)
        manual_chunks = search_manual_segments(
            question, project=project, limit=max_chunks
        )

        # Sort Errata / Official Clarification chunks to the very top so Erratas override base rules
        if manual_chunks:
            errata_chunks = [c for c in manual_chunks if "errata" in (str(c.get("section_title", "")) + str(c.get("chunk", ""))).lower()]
            non_errata_chunks = [c for c in manual_chunks if "errata" not in (str(c.get("section_title", "")) + str(c.get("chunk", ""))).lower()]
            manual_chunks = errata_chunks + non_errata_chunks

        if not keyword_chunks and not manual_chunks:
            not_found_messages = {
                "pt": "Não encontrei informações sobre isso no manual do jogo.",
                "en": "No relevant information found in the game manual.",
                "es": "No encontré información sobre esto en el manual del juego.",
                "de": "Keine relevanten Informationen im Spielhandbuch gefunden.",
                "fr": "Aucune information pertinente trouvée dans le manuel du jeu.",
                "it": "Nessuna informazione rilevante trovata nel manuale del gioco.",
                "ja": "ゲームマニュアルに関連情報が見つかりませんでした。",
                "zh": "游戏手册中未找到相关信息。",
                "ko": "게임 매뉴얼에서 관련 정보를 찾을 수 없습니다.",
                "ru": "В руководстве по игре не найдено соответствующей информации.",
                "nl": "Geen relevante informatie gevonden in de spelhandleiding.",
                "pl": "Nie znaleziono odpowiednich informacji w instrukcji gry.",
            }
            manual_not_found = not_found_messages.get(
                language or "en", not_found_messages["en"]
            )
            manual_not_found = _with_support_fallback(manual_not_found, language)
            return {"empty": True, "model": model, "not_found_msg": manual_not_found}
        
        context_parts = []
        for kw in keyword_chunks:
            kw_title = kw["keyword"]
            kw_desc = _sanitize_text(kw["description"])
            kw_icon = kw.get("icon")
            icon_str = f" [Icon Image: {kw_icon}]" if kw_icon else ""
            context_parts.append(f"EXACT KEYWORD DEFINITION: {kw_title}{icon_str}\n{kw_desc}")

        for c in manual_chunks:
            section = c.get("section_title", "")
            page = c.get("page_number", "")
            image_path = c.get("image_path", "")
            label = f"Manual {project}"
            if section:
                label += f" — {section}"
            if page:
                label += f" (page {page})"

            image_ref = ""
            if image_path:
                images = [img.strip() for img in image_path.split(",") if img.strip()]
                image_names = [img.split("/")[-1] for img in images]
                if image_names:
                    image_ref = f"\n[Images: {', '.join(image_names)}]"

            chunk_text = _sanitize_text(c["chunk"])
            if chunk_text:
                context_parts.append(f"{label}:{image_ref}\n{chunk_text}")
        context = "\n\n".join(context_parts)
        sources = {
            "tickets": [],
            "logistics": [],
            "manual": [
                {
                    "id": c["id"],
                    "title": f"{c.get('section_title', 'Manual')} (p.{c.get('page_number', '?')})",
                    "chunk": c["chunk"],
                    "distance": c["distance"],
                    "image_path": c.get("image_path", ""),
                    "page_number": c.get("page_number"),
                }
                for c in manual_chunks
            ],
            "keywords": [
                {
                    "id": kw["id"],
                    "title": kw["keyword"],
                    "description": kw["description"],
                    "icon": kw.get("icon"),
                    "distance": kw.get("distance", 0.0),
                }
                for kw in keyword_chunks
            ]
        }
        character_prompt = get_character_prompt(project, region)
        LANG_NAMES_MANUAL = {
            "pt": "Portuguese",
            "en": "English",
            "es": "Spanish",
            "de": "German",
            "fr": "French",
            "it": "Italian",
            "ja": "Japanese",
            "zh": "Chinese",
            "ko": "Korean",
            "ru": "Russian",
            "nl": "Dutch",
            "pl": "Polish",
        }
        response_language_rule = "- ALWAYS respond in the SAME LANGUAGE as the user's question."
        if language:
            lang_name = LANG_NAMES_MANUAL.get(language, language.upper())
            response_language_rule = f"- ALWAYS respond in {lang_name}. This is mandatory, even if the user writes in another language."

        if character_prompt:
            system_prompt = (
                f"{GAME_RULES_RESPONSE_STYLE}\n\n"
                f"{GLOBAL_RESPONSE_STYLE}\n\n"
                f"CHARACTER CONTEXT (Use ONLY for factual domain awareness, NOT for preambles or fluff):\n"
                f"{character_prompt}\n\n"
                "GAME RULES KNOWLEDGE:\n"
                "- You have access to the official game rulebook. Use it to answer the user's question accurately.\n"
                "- Use ONLY the provided rulebook excerpts as factual source. Do not invent rules from general board game knowledge.\n"
                f"- If the excerpts do not explicitly contain the rule for the exact scenario queried, state clearly that you could not find the rule in the manual and direct the user to support: {SUPPORT_URL}\n"
                "- ZERO FLUFF POLICY: Start directly with the answer. Do NOT add greetings, character flavor, lore preambles, or filler.\n"
                "\n"
                "ANSWER LENGTH & CLARITY (STRICTLY ENFORCED):\n"
                "- Simple questions (e.g. player count, session duration, page number): 1-2 direct lines.\n"
                "- Complex questions or explaining mechanics (e.g. how combat works, how to lose, how corruption works): explain the rules completely using clear steps or bullet points based strictly on the manual excerpts.\n"
                "- Do NOT add flavor text, dramatic preambles, or restate the question.\n"
                "- Lists: maximum 5 items, each one line.\n"
                "\n"
                "EXAMPLES (match this directness):\n"
                "- Q: 'How many players?' → A: 'Chronicles of Drunagor is played by 1 to 5 players. (Page 4 of Age of Darkness Rulebook)'\n"
                "- Q: 'When do I receive a Trauma Cube?' → A: 'A Hero receives 1 Trauma Cube when their Health Points reach 0 (Knocked Out) or from a Knock Out effect. (Page 15 of Age of Darkness Rulebook)'\n"
                "\n"
                "- PAGE CITATIONS RULE: Only cite page numbers explicitly provided in the retrieved excerpts (e.g. 'Page 15 of Age of Darkness Rulebook'). NEVER invent or guess a page number.\n\n"
                "STRICT RULES:\n"
                "- ZERO FLUFF: Start immediately with the answer.\n"
                f"{response_language_rule}"
            )
        else:
            system_prompt = (
                "You are a helpful game rules assistant for Creative Games Studio (CGS).\n"
                f"{GAME_RULES_RESPONSE_STYLE}\n"
                "Use the provided rulebook excerpts to answer the player's question accurately and clearly.\n"
                "Use ONLY the provided excerpts as factual source. Do not invent rules from general board game knowledge.\n"
                f"If the excerpts do not explicitly contain the rule for the exact scenario queried, you MUST state that you could not find the rule in the manual and direct the user to support: {SUPPORT_URL}\n"
                "\n"
                "ANSWER LENGTH (STRICTLY ENFORCED):\n"
                "- Simple questions (e.g. player count, session duration, page number): 1-2 direct lines.\n"
                "- Complex questions or explaining mechanics (e.g. how combat works, how to lose, how corruption works): explain the rules completely using the provided manual excerpts. Do not be short if being short would make the rule unclear or incomplete.\n"
                "- Do NOT restate the question or add unrequested context.\n"
                "- Lists: maximum 5 items, each one line.\n"
                "\n"
                "EXAMPLES:\n"
                "- Q: 'How many players?' → A: 'Drunagor is played by 1 to 5 heroes. You can find this on page 4 of the manual.'\n"
                "- Q: 'How long does a game last?' → A: 'A session takes about 60 to 90 minutes. See page 4 of the manual.'\n"
                "\n"
                "End with page number only when page data is available. Example: 'Page X.' If multiple pages are referenced, cite all of them.\n"
                f"{response_language_rule}"
            )

        user_prompt = f"RULEBOOK EXCERPTS:\n{context}\n\nQUESTION: {question}"

        return {
            "empty": False,
            "context": context,
            "sources": sources,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "ticket_chunks": [],
            "logistics_chunks": [],
            "category": category,
        }

    specific_pledge_status_question = (
        category in LOGISTICS_CONTEXT_CATEGORIES
        and _is_specific_pledge_status_question(question)
    )
    if specific_pledge_status_question:
        ticket_chunks = []
    else:
        ticket_chunks = semantic_search(question, limit=max_chunks, source="tickets")
        ticket_chunks = _filter_chunks(ticket_chunks)

    has_context = bool(project or region)
    include_logistics = has_context or (
        category in LOGISTICS_CONTEXT_CATEGORIES if category else False
    )

    logistics_chunks = []
    if include_logistics:
        if project and region:
            logistics_chunks = get_logistics_by_project_region(project, region)
        else:
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
                    "brazil": ["brasil", "brazil"],
                    "brasil": ["brasil", "brazil"],
                    "brasilien": ["brasil", "brazil"],
                    "canada": ["canada"],
                    "eua": ["eua", "usa", "united states"],
                    "usa": ["eua", "usa", "united states"],
                    "us": ["eua", "usa", "united states"],
                    "europe": ["europa", "europe"],
                    "europa": ["europa", "europe"],
                    "asia": ["asia"],
                    "australia": ["australia", "oceania"],
                    "uk": ["uk", "united kingdom"],
                    "united kingdom": ["uk", "united kingdom"],
                    "oceania": ["oceania", "australia"],
                    "rest of world": ["resto do mundo", "rest of world", "rest of the world"],
                    "rest of the world": ["resto do mundo", "rest of world", "rest of the world"],
                }
                region_terms = region_aliases.get(region.lower(), [region.lower()])
                filtered = [
                    c
                    for c in logistics_chunks
                    if any(
                        term in c.get("title", "").lower()
                        or term in c.get("chunk", "").lower()
                        for term in region_terms
                    )
                ]
                if filtered:
                    logistics_chunks = filtered

            if len(logistics_chunks) > 1:
                logistics_chunks = logistics_chunks[:1]

    if specific_pledge_status_question and product_language and logistics_chunks:
        language_matched = [
            chunk
            for chunk in logistics_chunks
            if _logistics_mentions_product_language(chunk, product_language)
        ]
        if language_matched:
            logistics_chunks = language_matched
        else:
            messages = {
                "pt": (
                    f"Encontrei dados de logística para {project or 'este projeto'}"
                    f" em {region or 'esta região'}, mas eles não especificam o idioma"
                    f" do produto ({product_language}). Não vou confirmar status sem"
                    " esse dado na base."
                ),
                "en": (
                    f"I found logistics data for {project or 'this project'}"
                    f" in {region or 'this region'}, but it does not specify the"
                    f" product language ({product_language}). I cannot confirm"
                    " that package status without language-specific logistics data."
                ),
            }
            return {
                "empty": True,
                "model": model,
                "not_found_msg": _with_support_fallback(
                    messages.get(language or "en", messages["en"]), language
                ),
            }

    voice_tone_docs = get_all_by_source("voice_tone")

    if not ticket_chunks and not logistics_chunks:
        NOT_FOUND_MESSAGES = {
            "pt": "Não encontrei informações relevantes sobre isso na base de conhecimento.",
            "en": "No relevant documents found in the knowledge base.",
            "es": "No encontré información relevante sobre esto en la base de conocimiento.",
            "de": "Ich habe keine relevanten Informationen dazu in der Wissensbasis gefunden.",
            "fr": "Aucune information pertinente trouvée dans la base de connaissances.",
            "it": "Non ho trovato informazioni rilevanti su questo nella base di conoscenza.",
            "ja": "ナレッジベースに関連情報が見つかりませんでした。",
            "zh": "知识库中未找到相关信息。",
            "ko": "지식 베이스에서 관련 정보를 찾을 수 없습니다。",
            "ru": "В базе знаний не найдено соответствующей информации.",
            "nl": "Geen relevante informatie gevonden in de kennisbank.",
            "pl": "Nie znaleziono odpowiednich informacji w bazie wiedzy.",
        }
        not_found_msg = NOT_FOUND_MESSAGES.get(
            language or "en", NOT_FOUND_MESSAGES["en"]
        )
        not_found_msg = _with_support_fallback(not_found_msg, language)
        return {"empty": True, "model": model, "not_found_msg": not_found_msg}

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

    LANG_NAMES = {
        "pt": "Portuguese",
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "fr": "French",
        "it": "Italian",
        "ja": "Japanese",
        "zh": "Chinese",
        "ko": "Korean",
        "ru": "Russian",
        "nl": "Dutch",
        "pl": "Polish",
    }

    NOT_FOUND_MESSAGES = {
        "pt": "Não encontrei informações relevantes sobre isso na base de conhecimento.",
        "en": "No relevant documents found in the knowledge base.",
        "es": "No encontré información relevante sobre esto en la base de conocimiento.",
        "de": "Ich habe keine relevanten Informationen dazu in der Wissensbasis gefunden.",
        "fr": "Aucune information pertinente trouvée dans la base de connaissances.",
        "it": "Non ho trovato informazioni rilevanti su questo nella base di conoscenza.",
        "ja": "ナレッジベースに関連情報が見つかりませんでした。",
        "zh": "知识库中未找到相关信息。",
        "ko": "지식 베이스에서 관련 정보를 찾을 수 없습니다。",
        "ru": "В базе знаний не найдено соответствующей информации.",
        "nl": "Geen relevante informatie gevonden in de kennisbank.",
        "pl": "Nie znaleziono odpowiednich informacji w bazie wiedzy.",
    }
    not_found_msg = NOT_FOUND_MESSAGES.get(language or "en", NOT_FOUND_MESSAGES["en"])
    not_found_msg = _with_support_fallback(not_found_msg, language)

    context_hint = ""
    if project:
        context_hint += f"\nThe user is asking about project: {project}."
    if region:
        context_hint += f"\nThe user is in region: {region}."
    if product_language:
        context_hint += f"\nThe product/package language is: {product_language}."
    response_language_rule = "- ALWAYS respond in the SAME LANGUAGE as the user's FIRST message."
    if language:
        lang_name = LANG_NAMES.get(language, language.upper())
        context_hint += f"\nYou MUST respond in {lang_name}. This is mandatory, even if documents are in other languages."
        response_language_rule = f"- ALWAYS respond in {lang_name}. This is mandatory, even if the user writes in another language."

    scope_rule = ""
    if project and region:
        scope_rule = (
            f"\n\nSCOPE RESTRICTION (strictly enforced):\n"
            f"- This conversation is exclusively about project '{project}' in region '{region}'.\n"
            f"- If the user asks about a DIFFERENT project or region, do NOT answer that question.\n"
            f"- Instead, politely explain that this chat is scoped to {project} / {region} and ask them "
            f"to go back to the previous page to select the correct project and region."
        )

    character_prompt = get_character_prompt(project, region)

    if character_prompt:
        system_prompt = (
            f"{character_prompt}\n\n"
            f"{GLOBAL_RESPONSE_STYLE}\n"
            f"{LOGISTICS_RESPONSE_STYLE}\n"
            "SUPPORT KNOWLEDGE:\n"
            "- You have access to past support ticket examples and logistics data. "
            "Use them as reference to answer the user's actual problem — but translate everything "
            "into your character's language and world with minimal flavor.\n"
            "- Never mention 'tickets', 'documents', 'database' or any technical term.\n\n"
            "LOGISTICS STATUS RULES:\n"
            "- For delivery status, tracking, and delays, use ONLY logistics data as factual status.\n"
            "- Never use past support examples to say a current package was delivered, delayed, refunded, or shipped.\n"
            "- If product/package language is requested but the logistics data does not explicitly mention that language, say that language-specific logistics are not available yet.\n\n"
            "STRICT RULES:\n"
            "- NEVER include personal data: no names, emails, addresses, order IDs, phone numbers.\n"
            "- Keep character voice subtle. One short character phrase is enough.\n"
            f"{response_language_rule}\n"
            f"- If no relevant info is found or you cannot answer safely, say so and direct the user to open a support ticket: {SUPPORT_URL}\n"
            "- If no relevant info is found, say so in character and suggest contacting "
            "customerservice@wearecgs.com — but phrase it as your character would.\n"
            "- If the user asks about a topic outside this project's scope, redirect them "
            "in character to go back and select the correct project."
            f"{context_hint}"
        )
    else:
        system_prompt = (
            "You are a friendly, knowledgeable customer support assistant for Creative Games Studio (CGS), "
            "a board game company. You have a warm, conversational tone — like a helpful colleague, not a robot.\n\n"
            f"{GLOBAL_RESPONSE_STYLE}\n"
            "VOICE TONE GUIDELINES (always follow this tone):\n"
            f"{voice_tone_text}\n\n"
            "HOW TO BEHAVE:\n"
            "- Be conversational and natural. Use the person's context from the conversation history.\n"
            "- If the user asks a follow-up like 'and in Europe?' or 'what about refunds?', "
            "use the conversation history to understand what they're referring to.\n"
            "- If you're unsure what the user means, ask a clarifying question naturally. "
            "For example: 'Just to make sure I help you correctly — are you asking about...?'\n"
            "- Keep answers concise but helpful. Don't over-explain.\n"
            "- The tickets provided are EXAMPLES of past support conversations. "
            "Use them as reference to craft your response, but never mention them.\n"
            "- The logistics data shows current shipping status. Reference it ONLY if it matches "
            "the user's project, region, and product/package language. If language-specific data is missing, say that clearly.\n"
            "- For delivery status, tracking, and delays, use ONLY logistics data as factual status. "
            "Never use past support examples to say a current package was delivered, delayed, refunded, or shipped.\n\n"
            "STRICT RULES:\n"
            "- NEVER include personal data: no names, emails, addresses, order IDs, phone numbers. "
            "Do NOT sign with any name or title.\n"
            "- NEVER add meta-commentary about tickets, your process, or sections like 'Observação:'.\n"
            f"{response_language_rule}\n"
            f"- If no relevant info is found or you cannot answer safely, say so naturally and direct the user to open a support ticket: {SUPPORT_URL}\n"
            "- If no relevant info is found, say so naturally and suggest contacting "
            "customerservice@wearecgs.com."
            f"{context_hint}"
            f"{scope_rule}"
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
        "category": category,
    }


def _build_refinement_system_prompt(
    original_question: str,
    original_answer: str,
    language: str | None,
    refinement_round: int = 1,
) -> str:
    LANG_NAMES = {
        "pt": "Portuguese",
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "fr": "French",
        "it": "Italian",
        "ja": "Japanese",
        "zh": "Chinese",
        "ko": "Korean",
        "ru": "Russian",
        "nl": "Dutch",
        "pl": "Polish",
    }
    lang_name = LANG_NAMES.get(language or "en", "English")

    is_last_attempt = refinement_round >= MAX_REFINEMENT_ROUNDS
    escalation_instruction = (
        f"\nIMPORTANT: This is the final refinement attempt. If you still cannot fully resolve "
        f"the issue, acknowledge it honestly and direct the user to open a support ticket at: {SUPPORT_URL}"
        if is_last_attempt
        else ""
    )

    return (
        "You are a friendly customer support assistant for Creative Games Studio (CGS), a board game company.\n\n"
        "The user was NOT satisfied with your previous answer. Your goal is to understand exactly "
        "what was missing or incorrect and provide a better, more complete response.\n\n"
        f"ORIGINAL QUESTION: {original_question}\n"
        f"PREVIOUS ANSWER: {original_answer}\n\n"
        "REFINEMENT RULES:\n"
        "- Acknowledge briefly that you want to help better — do NOT apologize excessively.\n"
        "- Ask targeted, specific questions to understand what was missing. Ask at most TWO at a time.\n"
        "- If the user has already explained what was missing, provide a clearly improved answer directly.\n"
        "- Never ask the user to repeat information they already provided.\n"
        "- Never mention tickets, documents, or internal processes."
        f"{escalation_instruction}\n\n"
        "STRICT RULES:\n"
        "- NEVER include personal data.\n"
        f"- ALWAYS respond in {lang_name}. This is mandatory."
    )


def generate_rag_stream(
    question: str,
    max_chunks: int = 5,
    session_id: str = "",
    chat_history: list[dict] | None = None,
    language: str | None = None,
    project: str | None = None,
    region: str | None = None,
    product_language: str | None = None,
    refinement_round: int = 0,
    parent_message_id: str | None = None,
    original_question: str | None = None,
    original_answer: str | None = None,
) -> Generator[str, None, None]:
    model = Config.get_llm_model()

    is_refinement = refinement_round > 0 and original_question and original_answer

    if is_refinement:
        detected_language = language
        category = classify_question(original_question)

        system_prompt = _build_refinement_system_prompt(
            original_question, original_answer, detected_language, refinement_round
        )

        llm_messages = [{"role": "system", "content": system_prompt}]
        llm_messages.extend(_build_history_messages(chat_history, question))
        llm_messages.append({"role": "user", "content": question})

        yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': {'tickets': [], 'logistics': []}, 'model': model, 'language': detected_language, 'refinement_round': refinement_round})}\n\n"

        full_answer = []
        tokens_in = 0
        tokens_out = 0

        try:
            if Config.is_openai_llm():
                client = _get_openai_client()
                stream = client.chat.completions.create(
                    model=model,
                    messages=llm_messages,
                    temperature=0.7,
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
                        "messages": llm_messages,
                        "stream": True,
                        "options": {
                            "temperature": 0.7,
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
        chat_id = ""
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
                    sources_count=0,
                    refinement_round=refinement_round,
                    parent_message_id=parent_message_id,
                    language=detected_language,
                )
            except Exception as e:
                logger.warning("Failed to save refinement chat: %s", e)

        yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"
        return

    # If enough context is already provided, skip context analysis entirely.
    # Game rules only need a project; support/order questions still need region.
    explicit_project = _detect_project_from_text(question)
    _project = explicit_project or project
    _region = region
    _product_language = product_language
    if _project:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_category = executor.submit(classify_question, question)
            future_lang = (
                executor.submit(_detect_language, question) if not language else None
            )
            category = future_category.result()
            detected_language = language if language else future_lang.result()
        missing_logistics = _missing_logistics_context(
            _project, _region, _product_language
        )
        if category == "game_rules" or category == "chitchat" or category in LOGISTICS_CONTEXT_CATEGORIES or (
            category not in LOGISTICS_CONTEXT_CATEGORIES and _region
        ):
            enhanced_query = question
            logger.info(
                "Fast path: category=%s, project=%s, region=%s, question=%s",
                category,
                _project,
                _region,
                question[:50],
            )
        else:
            _project = None
    else:
        category = None

    if not _project:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_analysis = executor.submit(analyze_context, question, chat_history)
            future_category = (
                executor.submit(classify_question, question) if category is None else None
            )
            analysis = future_analysis.result()
            category = category or future_category.result()

        detected_language = language or analysis.get("language")

        if analysis.get("status") == "need_info":
            follow_up = analysis.get("follow_up", "Could you provide more details?")

            yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': {'tickets': [], 'logistics': []}, 'model': model, 'need_info': True, 'language': detected_language})}\n\n"
            for word in follow_up.split(" "):
                yield f"data: {json.dumps({'type': 'token', 'content': word + ' '})}\n\n"

            chat_id = ""
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
                        language=detected_language,
                    )
                except Exception as e:
                    logger.warning("Failed to save chat history: %s", e)

            yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"
            return

        _project = explicit_project or analysis.get("project")
        _region = analysis.get("region")
        _product_language = product_language or analysis.get("product_language")
        enhanced_query = analysis.get("enhanced_query", question)

    if category in LOGISTICS_CONTEXT_CATEGORIES:
        missing_logistics = _missing_logistics_context(
            _project, _region, _product_language
        )
        if missing_logistics:
            follow_up = _build_logistics_follow_up(
                detected_language, missing_logistics
            )
            yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': {'tickets': [], 'logistics': []}, 'model': model, 'need_info': True, 'language': detected_language})}\n\n"
            for word in follow_up.split(" "):
                yield f"data: {json.dumps({'type': 'token', 'content': word + ' '})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'chat_id': ''})}\n\n"
            return

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_ctx = executor.submit(
            _prepare_rag_context,
            question=enhanced_query,
            max_chunks=max_chunks,
            project=_project,
            region=_region,
            product_language=_product_language,
            category=category,
            language=detected_language,
        )
        ctx = future_ctx.result()

    if ctx.get("empty"):
        nf_msg = ctx.get(
            "not_found_msg", "No relevant documents found in the knowledge base."
        )
        yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': {'tickets': [], 'logistics': []}, 'model': model, 'language': detected_language})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'content': nf_msg})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'chat_id': ''})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'meta', 'category': category, 'sources': ctx['sources'], 'model': model, 'language': detected_language, 'project': _project, 'region': _region, 'product_language': _product_language})}\n\n"

    llm_messages = [{"role": "system", "content": ctx["system_prompt"]}]
    llm_messages.extend(_build_history_messages(chat_history, question))
    llm_messages.append({"role": "user", "content": ctx["user_prompt"]})

    temperature = 0.3 if ctx.get("category") == "game_rules" else 0.7
    max_tokens = 800 if ctx.get("category") == "game_rules" else 520

    full_answer = []
    tokens_in = 0
    tokens_out = 0

    try:
        if Config.is_openai_llm():
            client = _get_openai_client()
            stream = client.chat.completions.create(
                model=model,
                messages=llm_messages,
                temperature=temperature,
                top_p=0.9,
                max_tokens=max_tokens,
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
                    "messages": llm_messages,
                    "stream": True,
                    "options": {
                            "temperature": temperature,
                            "top_p": 0.9,
                            "num_predict": max_tokens,
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
    chat_id = ""
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
                language=detected_language,
            )
        except Exception as e:
            logger.warning("Failed to save chat history: %s", e)

    logger.info(
        "RAG stream completed: provider=%s, question='%s', category=%s, "
        "project=%s, region=%s, language=%s, tokens_in=%d, tokens_out=%d",
        Config.LLM_PROVIDER,
        question[:50],
        category,
        project,
        region,
        detected_language,
        tokens_in,
        tokens_out,
    )

    yield f"data: {json.dumps({'type': 'done', 'chat_id': chat_id})}\n\n"


def generate_rag_response(
    question: str,
    max_chunks: int = 5,
    session_id: str = "",
    chat_history: list[dict] | None = None,
    language: str | None = None,
    project: str | None = None,
    region: str | None = None,
    product_language: str | None = None,
    refinement_round: int = 0,
    parent_message_id: str | None = None,
    original_question: str | None = None,
    original_answer: str | None = None,
) -> dict[str, Any]:
    is_refinement = refinement_round > 0 and original_question and original_answer

    if is_refinement:
        detected_language = language
        category = classify_question(original_question)
        model = Config.get_llm_model()

        system_prompt = _build_refinement_system_prompt(
            original_question, original_answer, detected_language, refinement_round
        )

        llm_messages = [{"role": "system", "content": system_prompt}]
        llm_messages.extend(_build_history_messages(chat_history, question))
        llm_messages.append({"role": "user", "content": question})

        try:
            if Config.is_openai_llm():
                client = _get_openai_client()
                response = client.chat.completions.create(
                    model=model,
                    messages=llm_messages,
                    temperature=0.7,
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
                        "messages": llm_messages,
                        "stream": False,
                        "options": {
                            "temperature": 0.7,
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
            raise RuntimeError(f"Error generating refinement response: {e}")

        chat_id = ""
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
                    sources_count=0,
                    refinement_round=refinement_round,
                    parent_message_id=parent_message_id,
                    language=detected_language,
                )
            except Exception as e:
                logger.warning("Failed to save refinement chat: %s", e)

        return {
            "question": question,
            "answer": answer,
            "sources": {"tickets": [], "logistics": []},
            "model": model,
            "category": category,
            "chat_id": chat_id,
            "language": detected_language,
            "refinement_round": refinement_round,
        }

    explicit_project = _detect_project_from_text(question)
    _project = explicit_project or project
    _region = region
    _product_language = product_language
    if _project:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_category = executor.submit(classify_question, question)
            future_lang = (
                executor.submit(_detect_language, question) if not language else None
            )
            category = future_category.result()
            detected_language = language if language else future_lang.result()
        missing_logistics = _missing_logistics_context(
            _project, _region, _product_language
        )
        if category == "game_rules" or category == "chitchat" or category in LOGISTICS_CONTEXT_CATEGORIES or (
            category not in LOGISTICS_CONTEXT_CATEGORIES and _region
        ):
            enhanced_query = question
        else:
            _project = None
    else:
        category = None

    if not _project:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_analysis = executor.submit(analyze_context, question, chat_history)
            future_category = (
                executor.submit(classify_question, question) if category is None else None
            )
            analysis = future_analysis.result()
            category = category or future_category.result()

        detected_language = language or analysis.get("language")

        if analysis.get("status") == "need_info":
            follow_up = analysis.get("follow_up", "Could you provide more details?")
            return {
                "question": question,
                "answer": follow_up,
                "sources": {"tickets": [], "logistics": []},
                "model": Config.get_llm_model(),
                "category": category,
                "chat_id": "",
                "need_info": True,
                "language": detected_language,
            }

        _project = explicit_project or analysis.get("project")
        _region = analysis.get("region")
        _product_language = product_language or analysis.get("product_language")
        enhanced_query = analysis.get("enhanced_query", question)

    if category in LOGISTICS_CONTEXT_CATEGORIES:
        missing_logistics = _missing_logistics_context(
            _project, _region, _product_language
        )
        if missing_logistics:
            follow_up = _build_logistics_follow_up(
                detected_language, missing_logistics
            )
            return {
                "question": question,
                "answer": follow_up,
                "sources": {"tickets": [], "logistics": []},
                "model": Config.get_llm_model(),
                "category": category,
                "chat_id": "",
                "need_info": True,
                "language": detected_language,
            }

    ctx = _prepare_rag_context(
        enhanced_query,
        max_chunks,
        project=_project,
        region=_region,
        product_language=_product_language,
        category=category,
        language=detected_language,
    )

    if ctx.get("empty"):
        return {
            "question": question,
            "answer": ctx.get(
                "not_found_msg", "No relevant documents found in the knowledge base."
            ),
            "sources": {"tickets": [], "logistics": []},
            "model": ctx["model"],
            "category": category,
            "chat_id": "",
            "language": detected_language,
        }

    model = ctx["model"]

    llm_messages = [{"role": "system", "content": ctx["system_prompt"]}]
    llm_messages.extend(_build_history_messages(chat_history, question))
    llm_messages.append({"role": "user", "content": ctx["user_prompt"]})

    temperature = 0.3 if ctx.get("category") == "game_rules" else 0.7
    max_tokens = 800 if ctx.get("category") == "game_rules" else 520

    try:
        if Config.is_openai_llm():
            client = _get_openai_client()
            response = client.chat.completions.create(
                model=model,
                messages=llm_messages,
                temperature=temperature,
                top_p=0.9,
                max_tokens=max_tokens,
            )
            answer = response.choices[0].message.content.strip()
            tokens_in = response.usage.prompt_tokens
            tokens_out = response.usage.completion_tokens
        else:
            resp = requests.post(
                f"{Config.OLLAMA_HOST.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": llm_messages,
                    "stream": False,
                        "options": {
                            "temperature": temperature,
                            "top_p": 0.9,
                            "num_predict": max_tokens,
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
        raise RuntimeError(f"Error generating response via {Config.LLM_PROVIDER}: {e}")

    chat_id = ""
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
        "language": detected_language,
    }
