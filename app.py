"""clinic-face-ai — FastAPI backend for face diagnosis (step 1).

Serves the GlowAI-pink UI from static/ and exposes a demo analysis API.
POST /api/analyze currently returns DEMO data. Replace `demo_analysis()`
with a real vision-model call (Gisoo / Sepand gateway) — same JSON shape,
no frontend change needed.

Red line: the API returns visual intensity only (mild / moderate /
noticeable). It never returns a dosage in units or a medical diagnosis.
The doctor sets the exact amount.
"""

import base64
import json
import os

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="clinic-face-ai")

# Real gateway config — all from environment, never hard-code a key here.
# Gisoo (first choice): AI_GATEWAY_BASE_URL=https://ir.gisoo.pro/api/v1
# Sepand (backup):      AI_GATEWAY_BASE_URL=https://api.sepandsoftware.ir/v1
# Vision model for analysis — cheapest capable Gemini on Gisoo (2026-11-26).
# gemini-3.1-flash-lite: $0.35 in / $2.10 out per 1M tokens, vision + JSON.
# One analysis (1120 input image tokens + ~500 output) costs ~$0.0014.
# gemini-3.6-flash costs ~$0.0038 for the same call — 2.6x more, no gain here.
# gpt-5-nano is even cheaper (~$0.0003) but weaker on detailed skin JSON,
# so Lite is the test default; compare nano on the same photo if curious.
GATEWAY_BASE_URL = os.environ.get("AI_GATEWAY_BASE_URL", "")
GATEWAY_API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")
VISION_MODEL = os.environ.get("AI_VISION_MODEL", "gemini-3.1-flash-lite")
# Image model for the real after-photo, e.g. gemini-3.1-flash-lite-image
# (Nano Banana 2 Lite) — check GET {base_url}/models on the gateway first.
IMAGE_MODEL = os.environ.get("AI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")

ANALYZE_SYSTEM_PROMPT = (
    "You are a skin-analysis assistant for an aesthetic clinic. "
    "Analyze the face photo and return ONLY valid JSON with this shape: "
    '{"glow_score": 0-100, "metrics": [{"key": "hydration"|"wrinkles"|"spots"|"pores"|"redness", '
    '"label": "<Persian label>", "value": 0-100}], '
    '"zones": [{"id": 1-5, "name": "<Persian zone>", "note": "<one short Persian sentence>"}], '
    '"treatments": [{"id": "forehead-botox"|"frown-botox"|"eyes-botox"|"lip-filler"|"cheek-filler", '
    '"name": "<Persian name>", "zone": "<Persian zone>"}]} '
    "Zones are: 1 forehead, 2 frown lines, 3 around eyes, 4 lips, 5 cheeks. "
    "Give visual intensity only — never a dosage in units, never a medical diagnosis."
)


async def gateway_analysis(image_bytes: bytes):
    """Call the vision model through the Iranian gateway. Raises on failure."""
    from openai import OpenAI

    client = OpenAI(base_url=GATEWAY_BASE_URL, api_key=GATEWAY_API_KEY)
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this face photo. Return only the JSON."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        response_format={"type": "json_object"},
    )
    result = json.loads(resp.choices[0].message.content)
    result["demo"] = False
    result["disclaimer"] = (
        "نتیجه پیش‌نمایش است، نه تضمین نتیجه؛ مقدار دقیق (واحد / حجم) را فقط پزشک تعیین می‌کند."
    )
    return result


def demo_analysis():
    """Demo result — same shape the real gateway will return later."""
    return {
        "glow_score": 76,
        "metrics": [
            {"key": "hydration", "label": "آبرسانی", "value": 72},
            {"key": "wrinkles", "label": "چروک ریز", "value": 64},
            {"key": "spots", "label": "لک و یکنواختی", "value": 68},
            {"key": "pores", "label": "منافذ", "value": 71},
            {"key": "redness", "label": "قرمزی", "value": 82},
        ],
        "zones": [
            {"id": 1, "name": "پیشانی", "note": "خطوط افقی خفیف تا متوسط"},
            {"id": 2, "name": "خط اخم", "note": "خط عمودی بین ابروها"},
            {"id": 3, "name": "دور چشم", "note": "خطوط ریز گوشه‌ی چشم"},
            {"id": 4, "name": "لب", "note": "حجم طبیعی، تقارن خوب"},
            {"id": 5, "name": "گونه", "note": "حجم متوسط، افت خفیف"},
        ],
        "treatments": [
            {"id": "forehead-botox", "name": "بوتاکس پیشانی", "zone": "پیشانی"},
            {"id": "frown-botox", "name": "بوتاکس خط اخم", "zone": "خط اخم"},
            {"id": "eyes-botox", "name": "بوتاکس دور چشم", "zone": "دور چشم"},
            {"id": "lip-filler", "name": "فیلر لب", "zone": "لب"},
            {"id": "cheek-filler", "name": "فیلر گونه", "zone": "گونه"},
        ],
        "demo": True,
        "disclaimer": "نتیجه نمایشی است، نه تضمین نتیجه؛ مقدار دقیق (واحد / حجم) را فقط پزشک تعیین می‌کند.",
    }


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    image_bytes = await file.read()
    if GATEWAY_BASE_URL and GATEWAY_API_KEY:
        try:
            return await gateway_analysis(image_bytes)
        except Exception as exc:  # gateway down / bad key: fail loudly, no fake data
            return {"error": f"gateway failed: {exc}", "demo": demo_analysis()}
    return demo_analysis()


@app.post("/api/simulate")
async def simulate(file: UploadFile = File(...)):
    """Real after-photo — NOT implemented until the face-preservation test passes.

    The test (scripts/face_preservation_test.py) decides which image model
    keeps the face identical. Until then this endpoint refuses to fake it.
    """
    _ = await file.read()
    return {
        "error": "not_ready",
        "message": (
            "عکس واقعی «بعد» هنوز آماده نیست — اول تست حفظ چهره باید پاس شود. "
            f"مدل تصویری پیش‌بینی‌شده: {IMAGE_MODEL} از طریق درگاه."
        ),
    }


app.mount("/static", StaticFiles(directory="static"), name="static")
