"""Private voice-to-text for Telegram Mini App, backed by Yandex SpeechKit.

Only the transcription is returned. No audio is saved in PostgreSQL or GitHub.
iOS WebViews often record MP4, so ffmpeg normalizes every supported input to
30-second mono OggOpus before the provider request.
"""
import os
import subprocess

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from dishes import limited_body

MAX_AUDIO_BYTES = 2_500_000
STT_URL = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"


def normalize_audio(data, mime):
    mime = (mime or "").partition(";")[0].strip().lower()
    valid = (
        (mime in ("audio/mp4", "audio/x-m4a") and data[4:8] == b"ftyp")
        or (mime in ("audio/webm", "video/webm") and data.startswith(b"\x1a\x45\xdf\xa3"))
        or (mime in ("audio/ogg", "application/ogg") and data.startswith(b"OggS"))
    )
    if not valid or len(data) < 1000 or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(422, "Нужна запись голоса длительностью до 30 секунд")
    try:
        process = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
             "-i", "pipe:0", "-map", "0:a:0", "-t", "30", "-vn", "-ac", "1",
             "-ar", "48000", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503, "Не удалось обработать запись, введи ответ текстом")
    if process.returncode or not process.stdout.startswith(b"OggS") or len(process.stdout) > 1_000_000:
        raise HTTPException(422, "Не удалось распознать формат записи. Введи ответ текстом.")
    return process.stdout


def yandex_recognize(ogg):
    key = os.getenv("YANDEX_STT_API_KEY") or os.getenv("YANDEX_API_KEY")
    if not key:
        raise HTTPException(503, "Голосовой ввод ожидает подключения Yandex SpeechKit")
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                STT_URL, params={"format": "oggopus", "lang": "ru-RU", "topic": "general"},
                content=ogg,
                headers={"Authorization": "Api-Key " + key,
                         "Content-Type": "application/octet-stream"},
            )
            response.raise_for_status()
            value = response.json().get("result")
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, "SpeechKit не распознал ответ. Проверь роль ai.speechkit-stt.user или введи текст.")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, "Речь не распознана. Повтори запись или введи текст.")
    return value.strip()[:1600]


def make_voice_router(db, require):
    router = APIRouter(prefix="/api/voice")

    @router.post("/transcribe")
    async def transcribe(request: Request):
        # Authentication and quota checks happen before media decoding/provider cost.
        with db() as c:
            u = require(c, request)
            c.execute("SELECT id FROM staff WHERE id=%s FOR UPDATE", (u["id"],))
            used = c.execute(
                "SELECT count(*) AS n FROM voice_transcriptions "
                "WHERE staff_id=%s AND created_at>now()-interval '24 hours'",
                (u["id"],),
            ).fetchone()["n"]
            if used >= 12:
                raise HTTPException(429, "Лимит голосовых ответов: 12 записей за сутки")
            c.execute("INSERT INTO voice_transcriptions(staff_id) VALUES(%s)", (u["id"],))
        blob = await limited_body(request, MAX_AUDIO_BYTES)
        ogg = await run_in_threadpool(normalize_audio, blob, request.headers.get("content-type", ""))
        transcript = await run_in_threadpool(yandex_recognize, ogg)
        return {"text": transcript, "audio_saved": False}

    return router
