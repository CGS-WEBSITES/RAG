"""Tetos de uso da parte pública. Ficam em memória: zeram se a API reiniciar."""

import threading
import time
from collections import defaultdict, deque

from flask import request

from api.config import Config

_lock = threading.Lock()
_hour: dict[str, deque] = defaultdict(deque)
_day: dict[str, float] = defaultdict(float)
_day_start = time.time()


def client_ip() -> str:
    # O CloudFront acrescenta o IP real no fim; o começo é forjável pelo cliente.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[-1].strip() or request.remote_addr or "?"


def _roll_day(now: float) -> None:
    global _day_start
    if now - _day_start > 86400:
        _day.clear()
        _hour.clear()
        _day_start = now


def allow_question(session: str = "") -> bool:
    """Teto por navegador (uma casa ou escritório divide o mesmo IP) e um teto maior por IP,
    porque o identificador do navegador pode ser trocado."""
    ip, now = client_ip(), time.time()
    with _lock:
        _roll_day(now)
        limits = {f"ip:{ip}": Config.PUBLIC_HOURLY_PER_IP * 5}
        if session:
            limits[f"nav:{ip}:{session}"] = Config.PUBLIC_HOURLY_PER_IP
        for key in limits:
            while _hour[key] and now - _hour[key][0] > 3600:
                _hour[key].popleft()
        if any(len(_hour[k]) >= n for k, n in limits.items()) or _day["perguntas"] >= Config.PUBLIC_DAILY_QUESTIONS:
            return False
        for key in limits:
            _hour[key].append(now)
        _day["perguntas"] += 1
        return True


def allow_voice(chars: int) -> bool:
    ip, now = client_ip(), time.time()
    with _lock:
        _roll_day(now)
        if (_day["voz"] + chars > Config.VOICE_DAILY_CHARS
                or _day[f"voz:{ip}"] + chars > Config.VOICE_DAILY_CHARS / 4):
            return False
        _day["voz"] += chars
        _day[f"voz:{ip}"] += chars
        return True
