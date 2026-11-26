"""One-day face-preservation test — run BEFORE building the after-photo module.

Usage (copy, do not retype):
    python -m pip install -r requirements.txt
    set AI_GATEWAY_BASE_URL=https://api.hormouz.net/v1   (Windows cmd)
    set AI_GATEWAY_API_KEY=...
    set AI_IMAGE_MODEL=google/gemini-3.1-flash-lite-image
    python scripts/face_preservation_test.py

Gateway routes differ: on Hormouz the image model is a CHAT model
(/chat/completions, edited image back on message.images); on Gisoo
image models need POST /images/generations. The script picks the route
from the base URL. Never use Hormouz /v1/predictions for edits — it
ignores a data-URL input image and generates a fresh picture instead.

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
# Cheapest Nano Banana (2026-11-26): Lite is $0.034 per image on Hormouz
# (9 test images = ~$0.31) and ~$0.06 on Gisoo. Nano Banana 2.1 costs
# almost the same as Lite on Hormouz — try it second if Lite moves the
# face. Always test at 1K, never 2K/4K, and one treatment at a time —
# 5 treatments at once is 5x the images.
MODEL = os.environ.get("AI_IMAGE_MODEL", "google/gemini-3.1-flash-lite-image")

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

    is_hormouz = "hormouz" in BASE_URL
    for photo in photos:
        image_b64 = base64.b64encode(photo.read_bytes()).decode()
        for level, instruction in INTENSITIES.items():
            prompt = PROMPT_TEMPLATE.format(instruction=instruction)
            out_path = out_dir / f"{photo.stem}_{level}.jpg"
            if is_hormouz:
                # VERIFIED 2026-11-26: on Hormouz the image model is a chat
                # model. POST {BASE_URL}/chat/completions with the photo as
                # image_url data URL; the edited image comes back as a data
                # URI on message.images (read the raw dict — the SDK does
                # not expose the non-standard `images` field).
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}"
                                    },
                                },
                            ],
                        }
                    ],
                )
                raw = resp.model_dump()
                images = raw["choices"][0]["message"].get("images") or []
                assert images, "image model returned no image"
                uri = images[0]["image_url"]["url"]
                out_path.write_bytes(base64.b64decode(uri.split(",", 1)[1]))
            else:
                # VERIFIED 2026-11-26 on Gisoo: image models do NOT work on
                # /chat/completions (400 model_endpoint_mismatch) and the
                # OpenAI client's images.generate() takes no `image` argument.
                # Working call: POST {BASE_URL}/images/generations, JSON body
                # {model, prompt, image: "data:image/jpeg;base64,...",
                #  size: "1024x1024", n: 1}; response data[0] holds b64_json.
                # Actual cost on Gisoo: min $0.0706 per image request
                # (not the $0.047 estimate from per-token math).
                import json as _json
                import urllib.request as _url

                body = _json.dumps(
                    {
                        "model": MODEL,
                        "prompt": prompt,
                        "image": f"data:image/jpeg;base64,{image_b64}",
                        "size": "1024x1024",
                        "n": 1,
                    }
                ).encode()
                req = _url.Request(
                    f"{BASE_URL}/images/generations",
                    data=body,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {API_KEY}",
                    },
                )
                with _url.urlopen(req, timeout=120) as resp:
                    result = _json.loads(resp.read())
                out_b64 = result["data"][0]["b64_json"]
                out_path.write_bytes(base64.b64decode(out_b64))
            print(f"{photo.name} x {level}: saved {out_path}")

    print("Done. Check test_output/ against the pass rule in this file's docstring.")


if __name__ == "__main__":
    main()
