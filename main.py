import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

APP_DIR = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 250 * 1024 * 1024
MAX_VIDEO_SECONDS = 600
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

app = FastAPI(title="AI Prompt Generator Pro", version="1.0.0")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def get_client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY belum diatur di server. Ikuti langkah instalasi pada README.",
        )
    return genai.Client(api_key=key)


def extract_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise HTTPException(status_code=502, detail="Gemini tidak mengembalikan JSON yang valid.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail=f"JSON dari Gemini tidak valid: {exc}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Format respons Gemini bukan objek JSON.")
    return data


def clean_image_result(data: dict, ratio: str, style: str) -> dict:
    fields = [
        "main_subject", "secondary_elements", "environment", "lighting",
        "camera_angle", "depth_of_field", "texture_details", "mood",
        "color_grading", "style_reference", "full_prompt", "quality_tags",
    ]
    for field in fields:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            data[field] = (
                f"Not clearly distinguishable; use a restrained, realistic interpretation consistent with the visible image."
                if field != "full_prompt" else
                "Create a faithful, detailed image based on the supplied visual reference, preserving its clearly visible subject, composition, environment, lighting, textures, and overall mood."
            )
    if len(data["full_prompt"].split()) < 80:
        data["full_prompt"] += (
            f" Maintain visual coherence and realistic proportions, preserve the source image's strongest compositional features, "
            f"use {style.lower()} treatment, and compose for an output aspect ratio of {ratio}. "
            "Avoid invented text, distorted anatomy, inconsistent shadows, excessive sharpening, and unrelated objects."
        )
    data["quality_tags"] = data["quality_tags"] or "8K, ultra-detailed, hyperrealistic, professional lighting, sharp focus"
    return data


IMAGE_INSTRUCTIONS = """
You are a professional visual analyst and prompt engineer. Analyze the supplied image deeply.
Infer only plausible details; distinguish visible facts from reasonable visual interpretation. Never invent brand names, identities, readable text, or hidden objects.
Return ONLY valid JSON, with every value a non-empty string, using exactly these keys:
{
"main_subject":"detailed physical description of the primary subject",
"secondary_elements":"supporting objects, people, props and their placement",
"environment":"location, background, atmosphere and spatial context",
"lighting":"light source/type, direction, softness and intensity",
"camera_angle":"shot size, viewpoint, lens perspective and composition",
"depth_of_field":"focus plane, background separation and bokeh",
"texture_details":"specific material, surface, skin, fabric, weather and microtexture details",
"mood":"emotional tone and atmosphere",
"color_grading":"dominant palette, contrast, saturation and tonal treatment",
"style_reference":"visual genre and photographic/art direction; do not name a living artist",
"full_prompt":"One standalone professional English image-generation prompt of at least 100 words, usable without the reference image. Include subject, composition, setting, lighting, lens/camera feel, textures, mood, palette and requested aspect ratio.",
"quality_tags":"8K, ultra-detailed, hyperrealistic, professional lighting, sharp focus"
}
Requested output aspect ratio: {ratio}
Requested visual style: {style}
Keep all fields useful and specific. If something cannot be determined, say so briefly and give a conservative realistic inference. Do not include Markdown or commentary.
"""

VIDEO_INSTRUCTIONS = """
You are an expert film cinematographer, editor and prompt engineer. Analyze the supplied video as a sequence, not as one still image.
Split the timeline into consecutive segments of exactly 10 seconds; include the final shorter segment even if under 8 seconds.
For EACH segment provide: main_subject, action_progression, secondary_elements, environment, lighting, camera_movement_and_angle, shot_composition_and_depth_of_field, texture_details, mood, color_grading, cinematic_style, continuity_notes, and a standalone English text_to_video_prompt of at least 80 words.
Use exactly two representative keyframe moments per segment, with their timestamps in seconds (keyframe_1_seconds, keyframe_2_seconds). Choose moments that capture the visual state/action progression. Use the provided video and the supplied extracted keyframes; do not claim details not visible.
Maintain continuity of recurring subject appearance, wardrobe, props, geography, light direction, palette, and screen direction across segments. Do not force continuity if the scene clearly changes.
Return ONLY valid JSON with this shape:
{
"video_duration_seconds": number,
"segment_length_seconds": 10,
"overall_summary": "string",
"global_visual_style": "string",
"continuity_guide": "string",
"video_prompt": "A concise but useful overall English video prompt",
"segments": [
{
"segment": 1,
"start_seconds": 0,
"end_seconds": 10,
"keyframe_1_seconds": 2.5,
"keyframe_2_seconds": 7.5,
"main_subject": "string",
"action_progression": "string",
"secondary_elements": "string",
"environment": "string",
"lighting": "string",
"camera_movement_and_angle": "string",
"shot_composition_and_depth_of_field": "string",
"texture_details": "string",
"mood": "string",
"color_grading": "string",
"cinematic_style": "string",
"continuity_notes": "string",
"text_to_video_prompt": "At least 80 words, standalone English prompt"
}
]
}
Numbers must be JSON numbers, not strings. Include every segment including the final partial segment. No Markdown.
"""


@app.get("/")
def home():
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL, "api_key_configured": bool(os.getenv("GEMINI_API_KEY", "").strip())}


@app.post("/api/analyze/image")
async def analyze_image(
    file: UploadFile = File(...),
    aspect_ratio: str = Form("Otomatis (cocokkan sumber)"),
    style: str = Form("Cinematic photorealistic"),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File harus berupa gambar.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File gambar kosong.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran gambar maksimal 15 MB.")
    try:
        from PIL import Image
        import io
        image = Image.open(io.BytesIO(raw))
        image.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="File gambar tidak valid atau format tidak didukung.")

    client = get_client()
    prompt = IMAGE_INSTRUCTIONS.format(ratio=aspect_ratio, style=style)
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                prompt,
                types.Part.from_bytes(data=raw, mime_type=file.content_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.35,
            ),
        )
        data = extract_json(response.text)
        data = clean_image_result(data, aspect_ratio, style)
        english = data["full_prompt"]
        return {"english_prompt": english, "json_output": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini gagal menganalisis gambar: {str(exc)[:500]}")


@app.post("/api/analyze/video")
async def analyze_video(
    file: UploadFile = File(...),
    aspect_ratio: str = Form("Otomatis (cocokkan sumber)"),
    style: str = Form("Cinematic photorealistic"),
):
    if not file.content_type or not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File harus berupa video.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File video kosong.")
    if len(raw) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran video maksimal 250 MB.")

    suffix = Path(file.filename or "upload.mp4").suffix or ".mp4"
    temp_path = None
    uploaded = None
    client = get_client()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            temp_path = tmp.name

        try:
            import cv2
            cap = cv2.VideoCapture(temp_path)
            if not cap.isOpened():
                raise HTTPException(status_code=400, detail="Video tidak dapat dibaca. Coba MP4 H.264.")
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = frame_count / fps if fps > 0 else 0
            if duration <= 0:
                raise HTTPException(status_code=400, detail="Durasi video tidak dapat dideteksi.")
            if duration > MAX_VIDEO_SECONDS:
                raise HTTPException(status_code=413, detail="Durasi video maksimal 10 menit.")
            segment_count = int((duration + 9.999) // 10)
            if segment_count > 60:
                raise HTTPException(status_code=413, detail="Video terlalu panjang untuk batas 60 segmen.")
            keyframe_parts = []
            keyframe_metadata = []
            for seg_idx in range(segment_count):
                start = seg_idx * 10.0
                end = min((seg_idx + 1) * 10.0, duration)
                for fraction in (0.25, 0.75):
                    timestamp = start + (end - start) * fraction
                    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                    ok, frame = cap.read()
                    if not ok:
                        continue
                    h, w = frame.shape[:2]
                    scale = min(1.0, 960 / max(w, h))
                    if scale < 1:
                        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                    if ok:
                        keyframe_parts.append(types.Part.from_bytes(data=encoded.tobytes(), mime_type="image/jpeg"))
                        keyframe_metadata.append(
                            f"Segment {seg_idx + 1}, keyframe timestamp {timestamp:.2f} seconds."
                        )
            cap.release()
        except ImportError:
            raise HTTPException(status_code=500, detail="Dependensi OpenCV belum terpasang. Jalankan pip install -r requirements.txt.")

        uploaded = client.files.upload(file=temp_path)
        # Gemini Files API video processing is asynchronous; wait for ACTIVE.
        deadline = time.time() + 240
        while not uploaded.state or uploaded.state.name != "ACTIVE":
            if uploaded.state and uploaded.state.name == "FAILED":
                raise HTTPException(status_code=502, detail="Gemini gagal memproses file video.")
            if time.time() > deadline:
                raise HTTPException(status_code=504, detail="Pemrosesan video Gemini melewati batas waktu.")
            time.sleep(3)
            uploaded = client.files.get(name=uploaded.name)

        prompt = VIDEO_INSTRUCTIONS + f"""
Video duration detected by server: {duration:.3f} seconds.
Expected segment count: {segment_count}.
Aspect ratio requested for generated prompts: {aspect_ratio}.
Requested visual style: {style}.
There are exactly two extracted representative keyframes per segment when extraction succeeded. The following text maps them to their times:
""" + "\n".join(keyframe_metadata) + """
Use the original video for motion, timing, camera movement, and audio/context if relevant. Use keyframes as visual anchors. Return exactly the expected number of segments. The final segment end_seconds must equal the detected duration.
"""
        contents = [uploaded, prompt] + keyframe_parts
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.35,
            ),
        )
        data = extract_json(response.text)
        data["video_duration_seconds"] = round(duration, 3)
        data["segment_length_seconds"] = 10
        segments = data.get("segments")
        if not isinstance(segments, list):
            segments = []
        # Ensure all actual timeline segments are represented even if model omits one.
        normalized = []
        for i in range(segment_count):
            start = i * 10
            end = min((i + 1) * 10, duration)
            found = next((s for s in segments if isinstance(s, dict) and int(s.get("segment", -1)) == i + 1), {})
            item = {
                "segment": i + 1,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "keyframe_1_seconds": round(start + (end-start)*0.25, 3),
                "keyframe_2_seconds": round(start + (end-start)*0.75, 3),
            }
            for key in [
                "main_subject", "action_progression", "secondary_elements", "environment",
                "lighting", "camera_movement_and_angle", "shot_composition_and_depth_of_field",
                "texture_details", "mood", "color_grading", "cinematic_style",
                "continuity_notes", "text_to_video_prompt",
            ]:
                val = found.get(key, "")
                item[key] = val.strip() if isinstance(val, str) and val.strip() else (
                    "Not clearly discernible; preserve the visible video content and avoid unsupported assumptions."
                )
            if len(item["text_to_video_prompt"].split()) < 80:
                item["text_to_video_prompt"] += (
                    f" Reproduce the observed action with natural motion, coherent spatial relationships, "
                    f"believable lighting and textures, consistent subject design, {style.lower()} art direction, "
                    f"and a {aspect_ratio} composition. Avoid abrupt visual changes, warped objects, flicker, and invented details."
                )
            normalized.append(item)
        data["segments"] = normalized
        data.setdefault("overall_summary", "Video analyzed as consecutive cinematic segments.")
        data.setdefault("global_visual_style", style)
        data.setdefault("continuity_guide", "Maintain subject, wardrobe, props, lighting, palette and screen direction where the source supports continuity.")
        data.setdefault("video_prompt", "Create a faithful cinematic reconstruction of the supplied video, preserving its action, visual continuity, camera language, lighting and atmosphere.")
        return {"video_prompt": data["video_prompt"], "segments": normalized, **data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemini gagal menganalisis video: {str(exc)[:500]}")
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
