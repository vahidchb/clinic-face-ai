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
#   AI_IMAGE_MODEL=google/gemini-3-pro-image  (Nano Banana Pro, ~$0.13-0.25/image)
# One analysis on Hormouz costs ~$0.0028 (two runs averaged, see _merge_analyses);
# one after-photo ~$0.13-0.25 (Pro). Pro replaced Lite as default 2026-11-28:
# one Pro test (photo1, 6 treatments محسوس) showed clearly visible changes
# (lips clearly fuller) with no color drift, where Lite did almost nothing.
# Gisoo (backup for analysis only): AI_GATEWAY_BASE_URL=https://ir.gisoo.pro/api/v1
#   with AI_VISION_MODEL=gemini-3.1-flash-lite (no google/ prefix there).
GATEWAY_BASE_URL = os.environ.get("AI_GATEWAY_BASE_URL", "https://api.hormouz.net/v1")
GATEWAY_API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")
VISION_MODEL = os.environ.get("AI_VISION_MODEL", "google/gemini-3.1-flash-lite")
IMAGE_MODEL = os.environ.get("AI_IMAGE_MODEL", "google/gemini-3-pro-image")

ANALYZE_SYSTEM_PROMPT = (
    "You are an experienced aesthetic dermatologist with 15 years of clinical "
    "practice in facial aesthetics. You are examining a patient's front-facing "
    "photo exactly as you would at the start of a consultation: first an overall "
    "clinical impression, then a systematic zone-by-zone examination of the WHOLE "
    "face, then a prioritized treatment plan. "
    "Examine every zone below. Do not skip any. For each zone report only what "
    "you can actually see on this photo: exact location, depth/severity (mild / "
    "moderate / severe), symmetry (symmetric, or which side is worse), and what "
    "it means for treatment. Be specific and clinical — never vague. If a zone "
    "shows no visible problem, say so plainly (score near 100) instead of "
    "inventing one. "
    "ZONES — always list all 10, in this order: "
    "1 forehead — horizontal lines; "
    "2 frown lines — vertical lines between the eyebrows; "
    "3 around eyes — crow's feet and fine lines at the outer corners; "
    "4 under eyes — darkness, puffiness, hollowing (tear trough); "
    "5 nasolabial folds — smile lines from the nose to the mouth corners; "
    "6 marionette lines — lines running down from the mouth corners; "
    "7 lips — volume, shape, symmetry, definition; "
    "8 cheeks — volume, lift, sagging; "
    "9 jawline — definition, jowls, contour; "
    "10 chin — shape, projection, dimpling. "
    "OVERALL — also assess: facial symmetry, skin texture, pigmentation and "
    "spots, pores, redness, and hydration (appearance estimate only — hydration "
    "cannot be measured from a photo). "
    "TREATMENT PLAN — prioritized, in the order a doctor would do them: what "
    "first (biggest visible improvement), what next, what can wait. For each "
    "treatment give: zone, treatment type (Botox / filler / skin treatment such "
    "as mesotherapy, microneedling or laser — the TYPE only), and visual "
    "intensity: mild / moderate / noticeable. Default intensity is noticeable "
    "(محسوس) — the patient must see a clear difference. Also list what NOT to "
    "touch: areas to leave alone to preserve natural symmetry and expression. "
    "RULES — Visual intensity only. NEVER give a dosage in units, a volume in "
    "cc or ml, or a medical diagnosis. The final amount and decision are always "
    "the treating doctor's. Score only what you can actually see; do not guess "
    "what the camera cannot show. Scales are anchored: 0 = problem severe and "
    "clearly visible, 50 = moderate and visible at normal distance, 100 = not "
    "visible at all. Use the exact Persian label 'آبرسانی (تخمین ظاهری)' for "
    "hydration. Give one short Persian evidence sentence per metric and per "
    "zone: what is visible, where, how severe, and which side if asymmetric. "
    "Return ONLY valid JSON with this exact shape: "
    '{"glow_score": 0-100, '
    '"overall_impression": "<one Persian sentence: overall clinical impression>", '
    '"metrics": [{"key": "hydration"|"wrinkles"|"spots"|"pores"|"redness"|"undereye"|"symmetry", '
    '"label": "<Persian label>", "value": 0-100, '
    '"evidence": "<one short Persian sentence>"}], '
    '"zones": [{"id": 1-10, "name": "<Persian zone>", "value": 0-100, '
    '"note": "<one short Persian sentence>"}], '
    '"treatments": [{"id": "forehead-botox"|"frown-botox"|"eyes-botox"|"undereye-filler"|'
    '"nasolabial-filler"|"marionette-filler"|"lip-filler"|"cheek-filler"|"jawline-filler"|'
    '"chin-filler"|"skin-treatment", "name": "<Persian name>", "zone": "<Persian zone>", '
    '"priority": 1-3, "intensity": "خفیف"|"ملایم"|"محسوس"}], '
    '"do_not_touch": ["<Persian: area to leave alone and why>"], '
    '"photo_quality": {"ok": true/false, '
    '"note": "<one short Persian sentence: front-facing, lighting, makeup/filter>"}} '
    "Always list all 10 zones and all 7 metrics. List the treatments this face "
    "needs, in priority order. Do not list treatments for zones with no visible problem."
)

HYDRATION_NOTE = (
    "آبرسانی از روی عکس فقط تخمین ظاهری است؛ عدد دقیق را دستگاه کلینیک می‌دهد."
)

# Per-treatment edit instructions for the after-photo. Intensity words are
# the same three levels the UI offers (mild / moderate / noticeable); the
# base wording carries no "subtle" so a محسوس edit reads as a clear change.
TREATMENT_EDITS = {
    # Result-state wording (experiment 2026-11-28): describe the face AFTER
    # the treatment has fully taken effect, explicitly and visibly — the old
    # gentle wording ("smooth the lines") made Lite do almost nothing.
    "forehead-botox": "the forehead is completely smooth with NO visible horizontal lines, and the eyebrows are visibly lifted and arched higher than before",
    "frown-botox": "the vertical frown lines between the eyebrows are completely gone",
    "eyes-botox": "the eyebrows are visibly lifted and arched higher, and the fine lines at the outer corners of the eyes are completely gone",
    "undereye-filler": "the under-eye hollows are clearly filled and the dark circles are gone, only under the eyes",
    "nasolabial-filler": "the nasolabial folds (smile lines) are clearly filled and softened",
    "marionette-filler": "the marionette lines at the mouth corners are clearly filled and softened",
    "lip-filler": "the lips are clearly fuller and more defined, like a 0.5 to 1cc filler result, keeping their natural shape",
    "cheek-filler": "the cheeks are visibly lifted and fuller, with a clear youthful contour",
    "jawline-filler": "the jawline is sharply defined and contoured, clearly stronger than before",
    "chin-filler": "the chin shape is clearly improved with better projection, any dimpling smoothed",
    "skin-treatment": "skin texture is clearly improved only in the treated skin — smoother, more even texture, without changing skin color, brightness or tone",
}
INTENSITY_WORDS = {
    # Calibrated 2026-11-28 (Vahid's 0.5cc rule): خفیف = just perceptible in
    # that feature, like a small 0.5cc adjustment; ملایم = clearly visible;
    # محسوس = obvious from a distance.
    "خفیف": "slightly but perceptibly, like a small 0.5cc adjustment",
    "ملایم": "clearly visibly",
    "محسوس": "dramatically and obviously, clearly visible from a distance",
    # Old label kept as a silent alias so a stale page can still send it.
    "متعادل": "clearly visibly",
}
DISCLAIMER = (
    "پیش‌نمایش تصویری است، نه تضمین نتیجه؛ تصمیم نهایی با پزشک است."
)


def _client():
    from openai import OpenAI

    return OpenAI(base_url=GATEWAY_BASE_URL, api_key=GATEWAY_API_KEY)


def _data_url(image_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()


def _image_dimensions(image_bytes: bytes):
    """Width/height from JPEG/PNG headers with stdlib only; None if unknown."""
    if image_bytes[:3] == b"\xff\xd8\xff":  # JPEG: scan markers for SOF0/1/2
        i = 2
        while i + 9 < len(image_bytes):
            if image_bytes[i] != 0xFF:
                i += 1
                continue
            marker = image_bytes[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h = int.from_bytes(image_bytes[i + 5 : i + 7], "big")
                w = int.from_bytes(image_bytes[i + 7 : i + 9], "big")
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(image_bytes[i + 2 : i + 4], "big")
            i += 2 + seg_len
        return None
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n" and len(image_bytes) >= 24:
        w = int.from_bytes(image_bytes[16:20], "big")
        h = int.from_bytes(image_bytes[20:24], "big")
        return w, h
    return None


def _photo_gate_error(image_bytes: bytes):
    """Persian error when a real photo is too small/low-quality; None if OK.

    Returns 'not_an_image' for bytes that are not JPEG/PNG at all (the demo
    blob) so demo mode keeps working. The gate is the single biggest accuracy
    lever: a tiny, dark or filtered photo makes every score unreliable.
    """
    dims = _image_dimensions(image_bytes)
    if dims is None:
        return "not_an_image"
    w, h = dims
    if len(image_bytes) < 12_000:
        return "عکس خیلی کم‌حجم است — لطفاً عکس بزرگ‌تر و بدون فشرده‌سازی زیاد بفرستید."
    if min(w, h) < 240 or max(w, h) < 480:
        return "عکس خیلی کوچک است — لطفاً عکس بزرگ‌تر و واضح‌تر بفرستید (حداقل ۴۸۰ پیکسل)."
    return None


def _clamp(v):
    return max(0, min(100, round(v)))


ZONE_NAMES = {
    1: "پیشانی", 2: "خط اخم", 3: "دور چشم", 4: "زیر چشم", 5: "خط خنده",
    6: "خط غم", 7: "لب", 8: "گونه", 9: "خط فک", 10: "چانه",
}


def _normalize_analysis(d: dict) -> dict:
    """Guarantee every model field the frontend interpolates is a string.

    The model sometimes omits a zone `note` — the frontend then rendered the
    literal word "undefined" ("پیشانی: 85٪ — undefined"). Fill every missing
    text field with "" so that can never happen again.
    """
    for z in d.get("zones") or []:
        z["name"] = z.get("name") or ZONE_NAMES.get(z.get("id"), "")
        z["note"] = z.get("note") or ""
        if not isinstance(z.get("value"), (int, float)):
            z["value"] = 0
    for m in d.get("metrics") or []:
        m["label"] = m.get("label") or ""
        m["evidence"] = m.get("evidence") or ""
        if not isinstance(m.get("value"), (int, float)):
            m["value"] = 0
    for t in d.get("treatments") or []:
        t["name"] = t.get("name") or ""
        t["zone"] = t.get("zone") or ""
        if t.get("intensity") not in ("خفیف", "ملایم", "محسوس", "متعادل"):
            t["intensity"] = "ملایم"
    d["overall_impression"] = d.get("overall_impression") or ""
    d["do_not_touch"] = [x for x in (d.get("do_not_touch") or []) if x]
    q = d.get("photo_quality") or {}
    q["note"] = q.get("note") or ""
    d["photo_quality"] = q
    return d


def _merge_analyses(first: dict, second: dict) -> dict:
    """Average two runs of the same photo; flag disagreement.

    Gemini is non-deterministic — the same photo can score differently twice.
    Averaging two runs (still ~$0.0028, ~3x cheaper than the cheapest dedicated
    scan) makes the score repeatable enough for a clinic, and a spread over 15
    points tells the doctor not to trust that number yet.
    """
    merged = dict(first)
    spread = abs((first.get("glow_score") or 0) - (second.get("glow_score") or 0))
    merged["glow_score"] = _clamp(
        ((first.get("glow_score") or 0) + (second.get("glow_score") or 0)) / 2
    )
    for key in ("metrics", "zones"):
        by_id = {}
        for item in second.get(key) or []:
            by_id[item.get("key", item.get("id"))] = item
        out = []
        for item in first.get(key) or []:
            other = by_id.get(item.get("key", item.get("id")))
            if other is None:
                out.append(item)
                continue
            spread = max(spread, abs((item.get("value") or 0) - (other.get("value") or 0)))
            merged_item = dict(item)
            merged_item["value"] = _clamp(((item.get("value") or 0) + (other.get("value") or 0)) / 2)
            if key == "zones":
                # A note the first run omitted but the second wrote still counts.
                merged_item["note"] = item.get("note") or other.get("note") or ""
            else:
                merged_item["evidence"] = item.get("evidence") or other.get("evidence") or ""
            out.append(merged_item)
        # A zone/metric the first run skipped but the second found still counts.
        seen_keys = {i.get("key", i.get("id")) for i in out}
        for item in second.get(key) or []:
            if item.get("key", item.get("id")) not in seen_keys:
                out.append(item)
        if key == "zones":
            out.sort(key=lambda z: z.get("id") or 0)
        merged[key] = out
    seen = {t.get("id") for t in first.get("treatments") or []}
    merged["treatments"] = list(first.get("treatments") or []) + [
        t for t in (second.get("treatments") or []) if t.get("id") not in seen
    ]
    merged["treatments"].sort(key=lambda t: t.get("priority") or 9)
    merged["overall_impression"] = (
        first.get("overall_impression") or second.get("overall_impression") or ""
    )
    merged["do_not_touch"] = list(
        dict.fromkeys(
            (first.get("do_not_touch") or []) + (second.get("do_not_touch") or [])
        )
    )
    q1, q2 = first.get("photo_quality") or {}, second.get("photo_quality") or {}
    merged["photo_quality"] = {
        "ok": bool(q1.get("ok", True) and q2.get("ok", True)),
        "note": q1.get("note") or q2.get("note") or "",
    }
    merged["agreement"] = "low" if spread > 15 else "high"
    merged["runs"] = 2
    if spread > 15:
        merged["agreement_note"] = (
            "دو بار تحلیل نتیجه‌های متفاوتی داد (اختلاف بیش از ۱۵) — "
            "به این عددها با احتیاط نگاه کنید و عکس بهتری بگیرید."
        )
    return _normalize_analysis(merged)


async def gateway_analysis(image_bytes: bytes):
    """Call the vision model through the gateway. Raises on failure.

    temperature=0: the clinic needs the same photo to score the same twice.
    """
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
        temperature=0,
    )
    result = json.loads(resp.choices[0].message.content)
    result["demo"] = False
    result["disclaimer"] = (
        "نتیجه پیش‌نمایش است، نه تضمین نتیجه؛ مقدار دقیق (واحد / حجم) را فقط پزشک تعیین می‌کند."
    )
    result["hydration_note"] = HYDRATION_NOTE
    return _normalize_analysis(result)


async def gateway_analysis_twice(image_bytes: bytes):
    """Two runs, averaged — see _merge_analyses. If one run fails, use the
    other alone and say so instead of failing the whole analysis."""
    first = await gateway_analysis(image_bytes)
    try:
        second = await gateway_analysis(image_bytes)
    except Exception:
        first["runs"] = 1
        first["agreement"] = "single"
        first["agreement_note"] = "تحلیل دوم انجام نشد — فقط یک بار تحلیل شد."
        return first
    return _merge_analyses(first, second)


# One step gentler: the "ملایم" preview level downgrades every chosen intensity,
# so the patient sees the subtle end of the range first — a preview is a
# direction, not a promise, and the doctor can step it up from there.
PREVIEW_DOWNGRADE = {"محسوس": "ملایم", "ملایم": "خفیف", "خفیف": "خفیف", "متعادل": "خفیف"}


async def gateway_simulate(image_bytes: bytes, treatments: list, preview: str = "استاندارد"):
    """Build the real after-photo with the image model. Raises on failure.

    `treatments` is a list of {"id": ..., "intensity": "خفیف"|"ملایم"|"محسوس"}.
    `preview` "ملایم" downgrades each intensity one step (see PREVIEW_DOWNGRADE).
    On Hormouz the image model is a chat model: the edited photo comes back
    as a data URI on message.images, so the raw response dict is read
    (the OpenAI SDK does not expose the non-standard `images` field).

    Color discipline: the prompt below forbids ANY change outside the treated
    zones — no hair color/style, eye color, skin tone, background, lighting
    or clothing change. The old wording asked for a "brighter" overall skin
    refresh and the model shifted the whole photo's color (even hair color).
    """
    edits = []
    for t in treatments:
        base = TREATMENT_EDITS.get(t.get("id", ""))
        if not base:
            continue
        intensity = t.get("intensity", "ملایم")
        if preview == "ملایم":
            intensity = PREVIEW_DOWNGRADE.get(intensity, intensity)
        edits.append(f"{INTENSITY_WORDS.get(intensity, 'visibly')} {base}")
    if not edits:
        raise ValueError("no treatment selected")
    prompt = (
        "Edit this photo to show the face AFTER these aesthetic treatments "
        "have fully taken effect: " + "; ".join(edits) + ". "
        "The treated areas must look clearly different from the original — "
        "a person looking at the photo must be able to tell the treatments "
        "were done. "
        "Change ONLY the treated areas listed above — nothing else in the photo. "
        "NEVER change the hair color or hairstyle, eye color, skin tone or skin "
        "color, background, lighting, or clothing. Keep the person's face, eyes, "
        "nose, lips, identity, features, expression, pose, and framing EXACTLY "
        "the same. Photorealistic, no cartoon look."
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
        "preview_level": preview,
        "disclaimer": DISCLAIMER
        + " پیش‌نمایش جهت تغییر را نشان می‌دهد، نه نتیجه‌ی دقیق بعد از تزریق.",
    }


def demo_analysis():
    """Demo result — same shape the real gateway will return later."""
    return {
        "glow_score": 76,
        "overall_impression": "چهره‌ی کلی سالم با خطوط متوسط پیشانی و خط اخم؛ اولویت با پیشانی و خط اخم است.",
        "metrics": [
            {"key": "hydration", "label": "آبرسانی (تخمین ظاهری)", "value": 72,
             "evidence": "پوست کمی خشک به نظر می‌رسد."},
            {"key": "wrinkles", "label": "چروک ریز", "value": 64,
             "evidence": "خطوط ریز روی پیشانی دیده می‌شود."},
            {"key": "spots", "label": "لک و یکنواختی", "value": 68,
             "evidence": "لک‌های پراکنده‌ی خفیف روی گونه."},
            {"key": "pores", "label": "منافذ", "value": 71,
             "evidence": "منافذ روی بینی و گونه قابل مشاهده است."},
            {"key": "redness", "label": "قرمزی", "value": 82,
             "evidence": "قرمزی محسوسی دیده نمی‌شود."},
            {"key": "undereye", "label": "تیرگی/پف زیر چشم", "value": 70,
             "evidence": "تیرگی خفیف زیر چشم دیده می‌شود."},
            {"key": "symmetry", "label": "تقارن", "value": 85,
             "evidence": "تقارن صورت در مجموع خوب است."},
        ],
        "zones": [
            {"id": 1, "name": "پیشانی", "value": 70, "note": "خطوط افقی خفیف تا متوسط"},
            {"id": 2, "name": "خط اخم", "value": 62, "note": "خط عمودی بین ابروها"},
            {"id": 3, "name": "دور چشم", "value": 68, "note": "خطوط ریز گوشه‌ی چشم"},
            {"id": 4, "name": "زیر چشم", "value": 70, "note": "تیرگی خفیف، گودی محسوس نیست"},
            {"id": 5, "name": "خط خنده", "value": 72, "note": "خط خنده‌ی خفیف تا متوسط"},
            {"id": 6, "name": "خط غم", "value": 78, "note": "خط غم خفیف"},
            {"id": 7, "name": "لب", "value": 80, "note": "حجم طبیعی، تقارن خوب"},
            {"id": 8, "name": "گونه", "value": 74, "note": "حجم متوسط، افت خفیف"},
            {"id": 9, "name": "خط فک", "value": 76, "note": "خط فک نسبتاً مشخص"},
            {"id": 10, "name": "چانه", "value": 82, "note": "فرم چانه مناسب"},
        ],
        "treatments": [
            {"id": "forehead-botox", "name": "بوتاکس پیشانی", "zone": "پیشانی", "priority": 1, "intensity": "محسوس"},
            {"id": "frown-botox", "name": "بوتاکس خط اخم", "zone": "خط اخم", "priority": 1, "intensity": "محسوس"},
            {"id": "eyes-botox", "name": "بوتاکس دور چشم", "zone": "دور چشم", "priority": 2, "intensity": "ملایم"},
            {"id": "undereye-filler", "name": "فیلر زیر چشم", "zone": "زیر چشم", "priority": 2, "intensity": "ملایم"},
            {"id": "nasolabial-filler", "name": "فیلر خط خنده", "zone": "خط خنده", "priority": 2, "intensity": "ملایم"},
            {"id": "lip-filler", "name": "فیلر لب", "zone": "لب", "priority": 3, "intensity": "خفیف"},
            {"id": "cheek-filler", "name": "فیلر گونه", "zone": "گونه", "priority": 3, "intensity": "ملایم"},
        ],
        "do_not_touch": [
            "لب را بیش‌ازحد پر نکنید — حجم طبیعی آن خوب است و تقارن را خراب می‌کند.",
            "تقارن طبیعی ابروها را حفظ کنید.",
        ],
        "demo": True,
        "photo_quality": {"ok": True, "note": "عکس نمایشی — کیفیت واقعی بررسی نشده است."},
        "agreement": "high",
        "runs": 2,
        "hydration_note": HYDRATION_NOTE,
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
    gate = _photo_gate_error(image_bytes)
    if gate not in (None, "not_an_image"):
        return {"error": gate}
    if GATEWAY_BASE_URL and GATEWAY_API_KEY:
        if gate == "not_an_image":
            return {"error": "لطفاً یک عکس واقعی (JPG یا PNG) انتخاب کنید."}
        try:
            return await gateway_analysis_twice(image_bytes)
        except Exception as exc:  # gateway down / bad key: fail loudly, no fake data
            return {"error": f"gateway failed: {exc}"}
    return demo_analysis()


@app.post("/api/simulate")
async def simulate(
    file: UploadFile = File(...),
    treatments: str = Form(default="[]"),
    preview: str = Form(default="استاندارد"),
):
    """Real after-photo via the image model (Hormouz chat route).

    `treatments` is a JSON string: [{"id": "forehead-botox", "intensity": "ملایم"}].
    `preview` "ملایم" shows the subtle end of the range (each intensity one
    step gentler); "استاندارد" uses the chosen intensities as-is.
    Without a gateway key the endpoint refuses — it never fakes the photo.
    """
    image_bytes = await file.read()
    gate = _photo_gate_error(image_bytes)
    if gate not in (None, "not_an_image"):
        return {"error": gate}
    if gate == "not_an_image":
        return {"error": "لطفاً یک عکس واقعی (JPG یا PNG) انتخاب کنید."}
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
        return await gateway_simulate(image_bytes, selected, preview)
    except Exception as exc:
        return {"error": f"gateway failed: {exc}"}


app.mount("/static", StaticFiles(directory="static"), name="static")
