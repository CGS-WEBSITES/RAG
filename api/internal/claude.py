"""Uma rodada de conversa com o Claude, no mesmo contrato usado para o GPT."""

import json
from typing import Iterator

import anthropic

from api.config import Config

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not Config.CLAUDE_API_KEY:
            raise RuntimeError("CLAUDE_API_KEY não configurada")
        _client = anthropic.Anthropic(api_key=Config.CLAUDE_API_KEY, timeout=90, max_retries=2)
    return _client


def _convert(messages: list[dict]) -> tuple[str, list[dict]]:
    """Do formato do GPT (o da conversa) para o da Anthropic."""
    system, out = "", []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            # Resultados da mesma rodada vão juntos numa única mensagem.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.get("claude_content"):
            out.append({"role": "assistant", "content": m["claude_content"]})
        elif m.get("tool_calls"):
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                        "input": json.loads(c["function"]["arguments"] or "{}")} for c in m["tool_calls"]]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return system, out


def run_round(model: str, messages: list[dict], tools: list[dict] | None, effort: str) -> Iterator[str]:
    """Emite texto e devolve {calls, finish, tokens_in, tokens_out, native}."""
    system, converted = _convert(messages)
    extra = {}
    if tools:
        extra["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                           "input_schema": t["function"]["parameters"]} for t in tools]
    with client().messages.stream(
        model=model, max_tokens=16000, system=system, messages=converted,
        output_config={"effort": effort}, cache_control={"type": "ephemeral"}, **extra,
    ) as stream:
        for text in stream.text_stream:
            yield text
        final = stream.get_final_message()
    usage = final.usage
    return {
        "calls": [{"id": b.id, "name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)}
                  for b in final.content if b.type == "tool_use"] if final.stop_reason == "tool_use" else [],
        "finish": {"max_tokens": "length", "refusal": "refusal"}.get(final.stop_reason, "stop"),
        "tokens_in": usage.input_tokens + (usage.cache_read_input_tokens or 0) + (usage.cache_creation_input_tokens or 0),
        "tokens_out": usage.output_tokens,
        # Devolvido intacto na rodada seguinte: os blocos de raciocínio são obrigatórios.
        "native": final.content,
    }
