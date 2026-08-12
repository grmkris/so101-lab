"""Gemini Robotics-ER 2: 2D pointing on an image.

Needs GEMINI_API_KEY (free key: https://aistudio.google.com/apikey — the
Gemini CLI OAuth path died with the Antigravity migration, 2026-08).

Usage: python er_client.py frame.jpg "the glass bowl" [overlay.jpg]
"""

import base64
import json
import os
import re
import sys
import time

import httpx

MODEL = "gemini-robotics-er-2-preview"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def _extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError(f"no JSON array in ER response: {text[:300]!r}")
    return json.loads(m.group(0))


def point_at(image_path: str, query: str, api_key: str | None = None, timeout: float = 90.0):
    """Ask ER 2 to point at `query`. Returns [{x, y, label}] in PIXELS of the image."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set — create a free key at https://aistudio.google.com/apikey")
    import cv2

    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(image_path)
    h, w = img.shape[:2]

    prompt = (
        f"Point to {query} in the image. Answer ONLY with a JSON array like "
        '[{"point": [y, x], "label": "..."}] where coordinates are normalized '
        "to 0-1000 in [y, x] order."
    )
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(open(image_path, "rb").read()).decode(),
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
    }
    t0 = time.perf_counter()
    r = httpx.post(URL, params={"key": api_key}, json=body, timeout=timeout)
    r.raise_for_status()
    latency = time.perf_counter() - t0
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    pts = _extract_json(text)
    out = [
        {
            "x": p["point"][1] / 1000.0 * w,
            "y": p["point"][0] / 1000.0 * h,
            "label": p.get("label", ""),
        }
        for p in pts
    ]
    print(f"[er] {latency:.1f}s, {len(out)} point(s): {out}")
    return out


def ask(image_path: str, question: str, api_key: str | None = None, timeout: float = 90.0) -> str:
    """Free-text question about an image (e.g. grasp verification). Returns the raw answer."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY not set — create a free key at https://aistudio.google.com/apikey")
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(open(image_path, "rb").read()).decode(),
                        }
                    },
                    {"text": question},
                ]
            }
        ],
    }
    t0 = time.perf_counter()
    r = httpx.post(URL, params={"key": api_key}, json=body, timeout=timeout)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    print(f"[er ask] {time.perf_counter()-t0:.1f}s: {text[:120]}")
    return text


def overlay(image_path: str, points, out_path: str):
    import cv2

    img = cv2.imread(image_path)
    for p in points:
        c = (int(round(p["x"])), int(round(p["y"])))
        cv2.circle(img, c, 8, (0, 0, 255), 2)
        cv2.drawMarker(img, c, (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        cv2.putText(img, p["label"], (c[0] + 10, c[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    cv2.imwrite(out_path, img)
    return out_path


if __name__ == "__main__":
    image, query = sys.argv[1], sys.argv[2]
    pts = point_at(image, query)
    if len(sys.argv) > 3:
        print(overlay(image, pts, sys.argv[3]))
