"""clinic-face-ai — FastAPI backend for face diagnosis (step 1).

Serves the GlowAI-pink UI from static/ and exposes a demo analysis API.
POST /api/analyze currently returns DEMO data. Replace `demo_analysis()`
with a real vision-model call (Gisoo / Sepand gateway) — same JSON shape,
no frontend change needed.

Red line: the API returns visual intensity only (mild / moderate /
noticeable). It never returns a dosage in units or a medical diagnosis.
The doctor sets the exact amount.
"""

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="clinic-face-ai")


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
    # TODO: send `await file.read()` to the AI gateway and return its JSON.
    # For now the file is accepted and ignored; demo data is returned.
    _ = file.filename
    return demo_analysis()


app.mount("/static", StaticFiles(directory="static"), name="static")
