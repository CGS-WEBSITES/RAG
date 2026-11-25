"""Limpeza e anonimização de tickets antes de indexar ou enviar à OpenAI.

É a última barreira de privacidade: o que sai daqui vai para o banco e para a
API. Regex não pega 100% dos nomes e endereços, então prefira remover demais.
"""

import html
import re

_PERSON = r"[A-ZÀ-Ý][\w'’.-]+(?:[ \t]+[A-ZÀ-Ý][\w'’.-]*){0,3}"

_IDENTIFIERS = [
    (re.compile(r"[^\s<>()\[\],;:]+@[^\s<>()\[\],;:]+"), "[e-mail]"),
    (re.compile(r"\b\d{6,9}[A-Z]\b"), "[pledge]"),
    (re.compile(r"https?://\S+|\bwww\.\S+"), "[link]"),
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "[documento]"),
    (re.compile(r"\b(?:[A-Z]{2}\d{9}[A-Z]{2}|1Z[0-9A-Z]{16})\b"), "[rastreio]"),
    (re.compile(r"(?<![\w.])\+?\(?\d[\d ().-]{8,}\d(?!\w)"), "[número]"),
    (re.compile(r"\b(?:\d{5}-\d{3}|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b"), "[CEP]"),
]

_LABELLED = re.compile(
    r"^([ \t*]*(?:first name|last name|full name|name|nome|e-?mail|phone|telefone|address(?: line)? ?\d*|"
    r"endere[cç]o|street|rua|city|cidade|zip(?: ?code)?|post(?:al)? ?code|cep)\b[ \t*]*[:=]\s*)\S.*$",
    re.IGNORECASE | re.MULTILINE,
)
_FORM_NAME = re.compile(r"(Name:\*?\s+).{2,60}?(?=\s*Email\*?\s)", re.IGNORECASE)
_GREETING = re.compile(
    r"\b((?i:hi|hello|hey|dear|ol[áa]|oi|prezad[oa]|car[oa]|hola|hallo|bonjour))[ \t,]+"
    rf"(?!(?:There|Team|CGS|Creative|All|Everyone)\b){_PERSON}"
)
_SIGNOFF = re.compile(
    r"((?i:regards|thanks|thank you|cheers|sincerely|best|obrigad[oa]|atenciosamente|att|abra[çc]os|"
    r"gr[üu](?:ß|ss)e|cordialement|saludos))"
    rf"([ \t]*[,.!;-]*[ \t]*\n+[ \t]*){_PERSON}[ \t]*(?=\n|$)"
)
_I_AM = re.compile(rf"((?i:my name is|meu nome é|raised by|under the name(?: of)?))[ \t]+{_PERSON}")
_STREET = re.compile(
    r"\b\d+[A-Za-z]?[ \t]+(?:[A-Z][\w'.-]+[ \t]+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Blvd|Way|Court|Ct|Close|Crescent|Place|Terrace)\b\.?"
    r"|\b(?:Rua|Avenida|Av\.|Travessa|Alameda|Rue|Calle|Via)[ \t]+[A-ZÀ-Ý][^\n,]{2,50},?[ \t]*(?:n[ºo.]*[ \t]*)?\d+"
    r"|\b[A-ZÄÖÜ][\wäöüß.-]*(?:stra(?:ße|sse)|str\.|weg|platz|gasse)[ \t]+\d+[a-z]?\b"
)

_QUOTE_START = re.compile(
    r"^\s*(?:On\b.{5,200}\bwrote:|Em\b.{5,200}\bescreveu:|Am\b.{5,200}\bschrieb\b.{0,80}:|"
    r"Le\b.{5,200}\ba écrit\s*:|-{3,}\s*(?:Original Message|Mensagem original|Forwarded message)\s*-{3,}|"
    r"From:\s.+\n\s*(?:Date|Sent):)",
    re.IGNORECASE | re.MULTILINE,
)
_BOILERPLATE = re.compile(
    r"Due to high volume[^\n]*|The contents of this e-?mail[\s\S]*?in\s+the\s+future\.?|"
    r"Sent from (?:my|Yahoo|Mail|Outlook|Samsung)[^\n]*|Creative Games Studio powered by Freshdesk|"
    r"#yiv\d+[^\n]*|You've received a message from[^\n]*|"
    r"In case you have a question about a project[\s\S]*?Poland",
    re.IGNORECASE,
)

_AUTO_SUBJECT = re.compile(
    r"^new comment reply$|new pledge appeared|sending limits reached|custom mailbox error|undelivered mail|"
    r"delivery status notification|mail delivery (?:failed|subsystem)|^automatic reply|your freshdesk subscription|agent was added to your account|^creative games studio: .* was deleted|unable to send emails for custom mailbox|^out of office|newsletter",
    re.IGNORECASE,
)
_BULK_BODY = re.compile(
    r"unsubscribe|cancelar inscri|view (?:this email )?in (?:your )?browser|mail system at host|"
    r"your freshworks account",
    re.IGNORECASE,
)


def scrub_identifiers(text: str) -> str:
    """Remove identificadores diretos sem mexer na estrutura do texto."""
    for pattern, replacement in _IDENTIFIERS:
        text = pattern.sub(replacement, text)
    return text


def anonymize(text: str) -> str:
    text = _FORM_NAME.sub(r"\1[nome] ", text or "")
    text = _LABELLED.sub(r"\1[removido]", text)
    text = _STREET.sub("[endereço]", text)
    text = _GREETING.sub(r"\1 [nome]", text)
    text = _SIGNOFF.sub(r"\1\2[nome]", text)
    text = _I_AM.sub(r"\1 [nome]", text)
    return scrub_identifiers(text)


def clean_message(text: str | None) -> str:
    """Corta citações e assinaturas, e anonimiza."""
    text = re.sub(r"<[^<>\n]{1,200}>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"[​-‍﻿]", "", text).replace("\xa0", " ").replace("\r", "")
    quote = _QUOTE_START.search(text)
    # Citação logo no início é encaminhamento: o conteúdo útil vem depois dela.
    if quote and quote.start() > 20:
        text = text[: quote.start()]
    text = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith(">"))
    text = _BOILERPLATE.sub("", text)
    text = anonymize(text)
    text = re.sub(r"^[\s\-*=_.]{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*", "\n\n", text).strip()


def is_noise(subject: str, body: str, has_team_reply: bool) -> bool:
    """Notificação automática, propaganda ou vazio: não ensina nada."""
    if has_team_reply:
        return False
    if len(re.sub(r"\W", "", body or "")) < 15:
        return True
    return bool(_AUTO_SUBJECT.search(subject or "") or _BULK_BODY.search(body or ""))


_PROJECTS = [
    ("Battleforge", re.compile(r"battle\s?forge|ragnar saga", re.I)),
    ("Dante", re.compile(r"\bdante\b|\binferno\b", re.I)),
    ("Drunagor", re.compile(r"drunagor|\bcod\b|apocalypse|aftermath|awakening|undead dragon|luccanor", re.I)),
    ("Forfun", re.compile(r"for\s?fun\b", re.I)),
]


def detect_project(text: str, tags: list[str] | None = None) -> str | None:
    for haystack in (" ".join(tags or []), text or ""):
        scores = [(len(p.findall(haystack)), name) for name, p in _PROJECTS]
        best = max(scores, key=lambda s: s[0])
        if best[0]:
            return best[1]
    return None


_ADDRESS = r"address change|chang\w+ (?:of )?(?:my |the |our )?(?:shipping |delivery )?address|new address|mudança de endereço"
_TOPICS = [
    ("reembolso", r"refund|reembolso|estorno|chargeback|money back"),
    ("peças", r"missing|damaged|broken|replacement|faltando|quebrad|defeit|component"),
    ("entrega", r"deliver|shipping|shipped|tracking|shipment|entrega|envio|rastre|fulfil|customs|\bvat\b"),
    ("pagamento", r"payment|paid|credit card|charged|pagamento|invoice|paypal"),
    ("campanha", r"pledge|campaign|gamefound|kickstarter"),
    ("regras", r"\brules?\b|gameplay|rulebook|regras?\b"),
]
_TYPE_TO_TOPIC = {
    "01": "compra", "02": "entrega", "03": "peças", "04": "campanha", "05": "reembolso",
    "06": "regras", "07": "serviços", "08": "eventos",
}


def detect_topic(text: str, ticket_type: str | None = None) -> str:
    # "02- About delivery" engloba trocas de endereço: o texto refina o tipo.
    if re.search(_ADDRESS, text or "", re.I):
        return "endereço"
    if ticket_type and ticket_type[:2] in _TYPE_TO_TOPIC:
        return _TYPE_TO_TOPIC[ticket_type[:2]]
    for topic, pattern in _TOPICS:
        if re.search(pattern, text or "", re.I):
            return topic
    return "outros"
