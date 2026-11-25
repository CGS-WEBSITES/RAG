"""Voz dos personagens pelo Amazon Polly.

As credenciais temporárias vêm do Cognito aqui no servidor: o ID do pool não vai
para o navegador, porque o papel anônimo dele tem mais permissão do que deveria.
"""

import datetime
import hashlib
import hmac
import json
import threading
import time
import urllib.request
from collections import OrderedDict

from api.config import Config

REGION = "us-east-1"  # motor neural
MAX_CHARS = 1500
VOICES = {"en": "Joanna", "pt": "Vitoria", "es": "Lucia", "de": "Vicki"}  # voz da assistente CGS
_HOST = f"polly.{REGION}.amazonaws.com"
_lock = threading.Lock()
_credentials: dict | None = None
_cache: OrderedDict[str, bytes] = OrderedDict()


def voice_for(project: str, character: str, region: str) -> str:
    if region == "Brasil":
        return "Vitoria" if project == "Battleforge" and character == "Freya" else "Thiago"
    if project == "Dante":
        return "Brian"
    if project == "Battleforge":
        return "Joanna" if character == "Freya" else "Stephen"
    return "Joey" if project == "Forfun" else "Arthur"


def _cognito(action: str, body: dict) -> dict:
    region = Config.POLLY_IDENTITY_POOL_ID.split(":")[0]
    req = urllib.request.Request(
        f"https://cognito-identity.{region}.amazonaws.com/", json.dumps(body).encode(),
        {"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": f"AWSCognitoIdentityService.{action}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _get_credentials() -> dict:
    global _credentials
    with _lock:
        if not _credentials or _credentials["Expiration"] - time.time() < 120:
            identity = _cognito("GetId", {"IdentityPoolId": Config.POLLY_IDENTITY_POOL_ID})["IdentityId"]
            _credentials = _cognito("GetCredentialsForIdentity", {"IdentityId": identity})["Credentials"]
        return _credentials


def _sign(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def _signed_headers(body: bytes, creds: dict) -> dict:
    """Assinatura AWS v4 para POST /v1/speech."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    headers = {"content-type": "application/json", "host": _HOST, "x-amz-date": stamp,
               "x-amz-security-token": creds["SessionToken"]}
    names = ";".join(sorted(headers))
    canonical = "\n".join(["POST", "/v1/speech", "", *(f"{k}:{headers[k]}" for k in sorted(headers)), "", names,
                           hashlib.sha256(body).hexdigest()])
    scope = f"{day}/{REGION}/polly/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("AWS4" + creds["SecretKey"]).encode()
    for part in (day, REGION, "polly", "aws4_request"):
        key = _sign(key, part)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={creds['AccessKeyId']}/{scope}, "
                                f"SignedHeaders={names}, Signature={signature}")
    del headers["host"]
    return headers


def cached(text: str, voice: str) -> bytes | None:
    with _lock:
        return _cache.get(f"{voice}:{text}")


def synthesize(text: str, voice: str) -> bytes:
    body = json.dumps({"OutputFormat": "mp3", "Text": text, "TextType": "text", "VoiceId": voice,
                       "Engine": "neural"}).encode()
    req = urllib.request.Request(f"https://{_HOST}/v1/speech", body, _signed_headers(body, _get_credentials()))
    with urllib.request.urlopen(req, timeout=20) as r:
        audio = r.read()
    with _lock:
        _cache[f"{voice}:{text}"] = audio
        while len(_cache) > 60:
            _cache.popitem(last=False)
    return audio
