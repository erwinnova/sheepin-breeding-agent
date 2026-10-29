"""
Transcribe a farmer's voice note with Muse Spark Open (Baseten) using the
audio_url content type with a base64 data URL, so no file hosting is needed.

Docs: https://docs.baseten.co/inference/model-apis/audio.md
Accepted: WAV, MP3, FLAC, OGG, M4A; 8-48 kHz; <= 5 minutes, <= 25 MB.
"""

import base64
import os

from openai import OpenAI

BASE_URL = "https://inference.baseten.co/v1"
MODEL = os.environ.get("BASETEN_MODEL", "meta-models/muse-spark-open-1026")

PROMPT = (
    "Transcribe this recording word for word in the language spoken (Bahasa Indonesia or English). "
    "Write ear tag numbers as digits (for example 0266, not 'nol dua enam enam'). "
    "Return only the transcript, with no introduction, quotes or commentary."
)


def transcribe(audio_bytes: bytes, mime: str = "audio/wav") -> dict:
    client = OpenAI(base_url=BASE_URL, api_key=os.environ["BASETEN_API_KEY"])
    data_url = f"data:{mime};base64," + base64.b64encode(audio_bytes).decode("ascii")
    r = client.chat.completions.create(
        model=MODEL,
        temperature=0.0,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "audio_url", "audio_url": {"url": data_url}},
        ]}],
    )
    text = (r.choices[0].message.content or "").strip().strip('"')
    u = r.usage
    return {"text": text, "usage": {"prompt": u.prompt_tokens, "completion": u.completion_tokens} if u else None}


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    ext = path.rsplit(".", 1)[-1].lower()
    mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "m4a": "audio/mp4", "flac": "audio/flac"}.get(ext, "audio/wav")
    with open(path, "rb") as f:
        print(transcribe(f.read(), mime))
