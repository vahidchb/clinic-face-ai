"""One-day face-preservation test — run BEFORE building the after-photo module.

Usage (copy, do not retype):
    python -m pip install -r requirements.txt
    set AI_GATEWAY_BASE_URL=https://ir.gisoo.pro/api/v1   (Windows cmd)
    set AI_GATEWAY_API_KEY=...
    set AI_IMAGE_MODEL=gemini-3.1-flash-lite-image
    python scripts/face_preservation_test.py

Put 3 front selfies (good light, no filter) in test_photos/ as photo1.jpg,
photo2.jpg, photo3.jpg. The script edits each one with ONE treatment
(forehead Botox) at 3 intensities and saves 9 outputs to test_output/.

Pass rule: in at least 2 of 3 photos, eyes / nose / lips / skin tone /
pose / background are unchanged and only the forehead changes, with a
believable (not cartoonish) result. If 2 of 3 fail, change the model —
do not build the product on it.
"""

import base64
import os
from pathlib import Path

from openai import OpenAI

BASE_URL = os.environ["AI_GATEWAY_BASE_URL"]
API_KEY = os.environ["AI_GATEWAY_API_KEY"]
# Cheapest Nano Banana on Gisoo (2026-11-26): Lite is ~$0.047 per 1K image,
# 9 test images = ~$0.43. Nano Banana 2 is 2x that (~$0.85 for 9);
# Nano Banana 2.1 costs almost the same as Lite (~$0.44 for 9) — try it
# second if Lite moves the face. Always test at 1K, never 2K/4K, and
# one treatment at a time — 5 treatments at once is 5x the images.
MODEL = os.environ.get("AI_IMAGE_MODEL", "gemini-3.1-flash-lite-image")

INTENSITIES = {
    "mild": "subtly soften the horizontal forehead lines, very natural, barely noticeable",
    "moderate": "visibly smooth the horizontal forehead lines, natural result",
    "noticeable": "strongly smooth the horizontal forehead lines, still realistic, not plastic",
}

PROMPT_TEMPLATE = (
    "Edit this photo: {instruction}. "
    "Keep the person's face, eyes, nose, lips, skin tone, hairstyle, pose, "
    "lighting and background EXACTLY the same. Change ONLY the forehead. "
    "Do not beautify anything else. Photorealistic, no cartoon look."
)


def main():
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    photos = sorted(Path("test_photos").glob("photo*.jpg"))
    assert len(photos) == 3, f"expected 3 photos in test_photos/, found {len(photos)}"
    out_dir = Path("test_output")
    out_dir.mkdir(exist_ok=True)

    for photo in photos:
        image_b64 = base64.b64encode(photo.read_bytes()).decode()
        for level, instruction in INTENSITIES.items():
            prompt = PROMPT_TEMPLATE.format(instruction=instruction)
            # NOTE: exact image-edit call depends on the gateway's model list.
            # Gisoo / Sepand expose OpenAI-compatible /images/generations;
            # if the gateway needs a different edit endpoint, adjust here
            # and record the working call in README.md — do not guess in prod.
            result = client.images.generate(
                model=MODEL,
                prompt=prompt,
                image=f"data:image/jpeg;base64,{image_b64}",
                size="1024x1024",
                n=1,
            )
            url = result.data[0].url
            print(f"{photo.name} x {level}: {url}")
            (out_dir / f"{photo.stem}_{level}.txt").write_text(url, encoding="utf-8")

    print("Done. Check test_output/ against the pass rule in this file's docstring.")


if __name__ == "__main__":
    main()
