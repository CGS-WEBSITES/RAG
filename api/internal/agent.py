"""Laço de conversa com ferramentas, comum ao chat interno e ao público."""

import json
import logging
import re
from typing import Callable, Iterator

from api.internal.llm import openai_client

logger = logging.getLogger(__name__)


def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required}}}


def _model_options(model: str) -> dict:
    if model.startswith(("gpt-5", "gpt-6")):
        # A partir do 5.4 o chat/completions só aceita ferramentas sem raciocínio.
        effort = "low" if re.fullmatch(r"gpt-5(-mini|-nano)?", model) else "none"
        return {"model": model, "max_completion_tokens": 6000, "extra_body": {"reasoning_effort": effort}}
    return {"model": model, "max_tokens": 2500, "temperature": 0.2}


def _gpt_round(model: str, messages: list, tools: list | None) -> Iterator[str]:
    """Mesmo contrato de claude.run_round: emite texto e devolve o resumo da rodada."""
    calls: dict[int, dict] = {}
    out = {"calls": [], "finish": "stop", "tokens_in": 0, "tokens_out": 0, "native": None}
    clean = [{k: v for k, v in m.items() if k != "claude_content"} for m in messages]
    stream = openai_client().chat.completions.create(
        messages=clean, stream=True, stream_options={"include_usage": True},
        **_model_options(model), **({"tools": tools} if tools else {}))
    for chunk in stream:
        if chunk.usage:
            out["tokens_in"] = chunk.usage.prompt_tokens
            out["tokens_out"] = chunk.usage.completion_tokens
        if not chunk.choices:
            continue
        out["finish"] = chunk.choices[0].finish_reason or out["finish"]
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
        for tc in delta.tool_calls or []:
            call = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            call["id"] = tc.id or call["id"]
            if tc.function:
                call["name"] += tc.function.name or ""
                call["arguments"] += tc.function.arguments or ""
    out["calls"] = list(calls.values())
    return out


def _round(models: list[str], messages: list, tools: list | None, effort: str) -> Iterator[str]:
    """Roda no primeiro modelo da lista; se falhar sem ter escrito nada, passa ao próximo (e o descarta)."""
    while True:
        model, wrote = models[0], False
        try:
            if model.startswith("claude"):
                from api.internal import claude
                run = claude.run_round(model, messages, tools, effort)
            else:
                run = _gpt_round(model, messages, tools)
            while True:
                try:
                    text = next(run)
                except StopIteration as end:
                    if end.value["finish"] == "refusal" and not wrote and len(models) > 1:
                        raise RuntimeError("recusa do modelo") from None
                    return end.value
                wrote = True
                yield text
        except Exception as e:
            if wrote or len(models) == 1:
                raise
            logger.warning("Modelo %s falhou, usando %s: %s", model, models[1], e)
            models.pop(0)


def loop(messages: list[dict], models: list[str], tools: list[dict], run_tool: Callable, status: dict[str, str],
         effort: str, rounds: int = 5, sources: dict | None = None, steps: list | None = None) -> Iterator[dict]:
    """Emite eventos token/status e devolve {answer, sources, steps, model, tokens_in, tokens_out}."""
    sources = {} if sources is None else sources
    steps = [] if steps is None else steps
    answer, tokens_in, tokens_out = "", 0, 0
    allowed = {t["function"]["name"] for t in tools}
    for round_no in range(rounds + 1):
        text = ""
        run = _round(models, messages, tools if round_no < rounds else None, effort)
        while True:
            try:
                piece = next(run)
            except StopIteration as end:
                result_round = end.value
                break
            text += piece
            yield {"type": "token", "content": piece}
        tokens_in += result_round["tokens_in"]
        tokens_out += result_round["tokens_out"]
        answer += text
        if not result_round["calls"]:
            if result_round["finish"] == "length":
                answer += " […]"
                yield {"type": "token", "content": " […]"}
            break
        if text:
            answer += "\n\n"
            yield {"type": "token", "content": "\n\n"}
        messages.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in result_round["calls"]], "claude_content": result_round["native"]})
        for c in result_round["calls"]:
            try:
                if c["name"] not in allowed:
                    raise ValueError(f"ferramenta não permitida: {c['name']}")
                args = json.loads(c["arguments"] or "{}")
                label, detail = status.get(c["name"], "…"), args.get("query")
                steps.append(f"{label}: {detail}" if detail else label)
                yield {"type": "status", "text": label, "step": steps[-1]}
                result, found = run_tool(c["name"], args)
            except Exception:
                logger.exception("Falha na ferramenta %s", c["name"])
                result, found = "The lookup failed; say this source is unavailable right now.", []
            sources.update({s["id"]: s for s in found})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False, default=str)})
    if not answer.strip():
        raise RuntimeError("O modelo devolveu uma resposta vazia")
    return {"answer": answer, "sources": sources, "steps": steps, "model": models[0],
            "tokens_in": tokens_in, "tokens_out": tokens_out}
