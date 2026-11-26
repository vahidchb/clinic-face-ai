"""clinic-face-ai — FastAPI backend for face diagnosis (step 1).

Serves the GlowAI-pink UI from static/ and exposes the analysis API.
POST /api/analyze calls the vision model through the gateway when it is
configured, else it returns DEMO data. POST /api/simulate builds the real
after-photo with the image model — enabled since the face-preservation
test passed 3/3 (2 on Gisoo, 1 on Hormouz, 2026-11-26).

Gateway: Hormouz (primary, 2026-11-26) — Iranian gateway, rial payment,
OpenAI-compatible chat API at https://api.hormouz.net/v1. Both the vision
model and the image model run through /chat/completions there: the edited
image comes back as a data URI on choices[0].message.images[0].image_url.url.
The /v1/predictions route does NOT accept a data-URL input image, so it is
not used for edits. Gisoo still works for /api/analyze (same chat API) but
its image models need /images/generations, which this code does not call.

Red line: the API returns visual intensity only (mild / moderate /
noticeable). It never returns a dosage in units or a medical diagnosis.
The doctor sets the exact amount.
"""

import base64
import json
import os

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="clinic-face-ai")

# Real gateway config — all from environment, never hard-code a key here.
# Hormouz (primary): AI_GATEWAY_BASE_URL=https://api.hormouz.net/v1
#   AI_VISION_MODEL=google/gemini-3.1-flash-lite  (vision, $0.25 in / $1.50 out per 1M)
#   AI_IMAGE_MODEL=google/gemini-3.1-flash-lite-image  (Nano Banana 2 Lite, $0.034/image)
# One analysis on Hormouz costs ~$0.001; one after-photo ~$0.034.
# Gisoo (backup for analysis only): AI_GATEWAY_BASE_URL=https://ir.gisoo.pro/api/v1
#   with AI_VISION_MODEL=gemini-3.1-flash-lite (no google/ prefix there).
GATEWAY_BASE_URL = os.environ.get("AI_GATEWAY_BASE_URL", "https://api.hormouz.net/v1")
GATEWAY_API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")
VISION_MODEL = os.environ.get("AI_VISION_MODEL", "google/gemini-3.1-flash-lite")
IMAGE_MODEL = os.environ.get("AI_IMAGE_MODEL", "google/gemini-3.1-flash-lite-image")

ANALYZE_SYSTEM_PROMPT = (
    "You are a skin-analysis assistant for an aesthetic clinic. "
    "Analyze the face photo and return ONLY valid JSON with this shape: "
    '{"glow_score": 0-100, "metrics": [{"key": "hydration"|"wrinkles"|"spots"|"pores"|"redness", '
    '"label": "<Persian label>", "value": 0-100}], '
    '"zones": [{"id": 1-5, "name": "<Persian zone>", "note": "<one short Persian sentence>"}], '
    '"treatments": [{"id": "forehead-botox"|"frown-botox"|"eyes-botox"|"lip-filler"|"cheek-filler", '
    '"name": "<Persian name>", "zone": "<Persian zone>"}]} '
    "Zones are: 1 forehead, 2 frown lines, 3 around eyes, 4 lips, 5 cheeks. "
    "Always list all 5 zones and all 5 treatments, even when a treatment is "
    "not needed for this face — the doctor decides what to use. "
    "Give visual intensity only — never a dosage in units, never a medical diagnosis."
)

# Per-treatment edit instructions for the after-photo. Intensity words are
# the same three levels the UI offers (mild / moderate / noticeable).
TREATMENT_EDITS = {
    "forehead-botox": "smooth the horizontal forehead lines",
    "frown-botox": "smooth the vertical frown line between the eyebrows",
    "eyes-botox": "smooth the fine lines at the outer corners of the eyes (crow's feet)",
    "lip-filler": "add a natural, subtle volume to the lips",
    "cheek-filler": "add a natural, subtle volume to the cheeks, lifting them slightly",
}
INTENSITY_WORDS = {
    "خفیف": "subtly",
    "متعادل": "visibly",
    "محسوس": "strongly",
}
DISCLAIMER = (
    "پیش‌نمایش تصویری است، نه تضمین نتیجه؛ تصمیم نهایی با پزشک است."
)


def _client():
    from openai import OpenAI

    return OpenAI(base_url=GATEWAY_BASE_URL, api_key=GATEWAY_API_KEY)


def _data_url(image_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()


async def gateway_analysis(image_bytes: bytes):
    """Call the vision model through the gateway. Raises on failure."""
    client = _client()
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this face photo. Return only the JSON."},
                    {"type": "image_url", "image_url": {"url": _data_url(image_bytes)}},
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


async def gateway_simulate(image_bytes: bytes, treatments: list):
    """Build the real after-photo with the image model. Raises on failure.

    `treatments` is a list of {"id": ..., "intensity": "خفیف"|"متعادل"|"محسوس"}.
    On Hormouz the image model is a chat model: the edited photo comes back
    as a data URI on message.images, so the raw response dict is read
    (the OpenAI SDK does not expose the non-standard `images` field).
    """
    edits = []
    for t in treatments:
        base = TREATMENT_EDITS.get(t.get("id", ""))
        if not base:
            continue
        edits.append(f"{INTENSITY_WORDS.get(t.get('intensity', 'متعادل'), 'visibly')} {base}")
    if not edits:
        raise ValueError("no treatment selected")
    prompt = (
        "Edit this photo: " + "; ".join(edits) + ", natural result. "
        "Keep the person's face, eyes, nose, lips, skin tone, hairstyle, pose, "
        "lighting and background EXACTLY the same. Change ONLY the treated areas. "
        "Do not beautify anything else. Photorealistic, no cartoon look."
    )
    client = _client()
    resp = client.chat.completions.create(
        model=IMAGE_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _data_url(image_bytes)}},
                ],
            }
        ],
    )
    raw = resp.model_dump()
    images = raw["choices"][0]["message"].get("images") or []
    if not images:
        raise RuntimeError("image model returned no image")
    return {
        "image": images[0]["image_url"]["url"],
        "demo": False,
        "disclaimer": DISCLAIMER,
    }


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
    return {"ok": True, "gateway": bool(GATEWAY_BASE_URL and GATEWAY_API_KEY)}


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
async def simulate(
    file: UploadFile = File(...),
    treatments: str = Form(default="[]"),
):
    """Real after-photo via the image model (Hormouz chat route).

    `treatments` is a JSON string: [{"id": "forehead-botox", "intensity": "متعادل"}].
    Without a gateway key the endpoint refuses — it never fakes the photo.
    """
    image_bytes = await file.read()
    if not (GATEWAY_BASE_URL and GATEWAY_API_KEY):
        return {
            "error": "not_ready",
            "message": (
                "عکس واقعی «بعد» نیاز به کلید درگاه دارد — AI_GATEWAY_API_KEY را در .env بگذارید. "
                f"مدل تصویری: {IMAGE_MODEL}."
            ),
        }
    try:
        selected = json.loads(treatments)
    except json.JSONDecodeError:
        return {"error": "bad_treatments", "message": "treatments باید JSON معتبر باشد."}
    try:
        return await gateway_simulate(image_bytes, selected)
    except Exception as exc:
        return {"error": f"gateway failed: {exc}"}


app.mount("/static", StaticFiles(directory="static"), name="static")
