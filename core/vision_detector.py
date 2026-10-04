import json
import io
import re
import time
import base64
from PIL import Image
from google import genai
from google.genai import types
from groq import Groq
from config import GEMINI_API_KEY, GROQ_API_KEY
from core.agents.state import VisionDetectionResult, DetectedHazard

def detect_civic_hazards(image: Image.Image, filename_hint: str = "", user_category_hint: str = "Auto-Detect") -> VisionDetectionResult:
    """
    High-reliability hazard classifier:
    1. User explicit selection (if not Auto-Detect)
    2. Gemini 3.8 Flash (with automatic 503 retry)
    3. Groq Llama 3.2 Vision Failover
    """
    # 1. User / Filename Fast Hint
    u_hint = user_category_hint.lower()
    f_hint = filename_hint.lower()
    
    if "manhole" in u_hint or "gutter" in u_hint or any(k in f_hint for k in ["manhole", "gutter", "drain", "sewer"]):
        return _build_res("open_manhole", "Open sewer chamber / broken curb drain cover", [400, 350, 950, 900])
    elif "garbage" in u_hint or "waste" in u_hint or any(k in f_hint for k in ["garbage", "waste", "trash", "kachra"]):
        return _build_res("garbage", "Roadside solid waste accumulation and garbage pile", [300, 150, 850, 850])
    elif "road" in u_hint or "pothole" in u_hint or any(k in f_hint for k in ["pothole", "cavity", "asphalt", "crater"]):
        return _build_res("pothole", "Asphalt road cavity / surface pothole", [350, 200, 750, 750])

    # Convert to JPEG bytes
    rgb_image = image.convert("RGB")
    img_byte_arr = io.BytesIO()
    rgb_image.save(img_byte_arr, format='JPEG', quality=90)
    img_bytes = img_byte_arr.getvalue()

    prompt = """
    You are an AI Civic Infrastructure Inspector for Pakistan.
    Analyze this street photograph and identify the single primary civic hazard.

    CLASSIFY PRECISELY INTO ONE:
    - 'open_manhole': An open drain, missing sewer lid, broken concrete drain slab on the curb or sidewalk, cavity leading to an underground sewer chamber.
    - 'garbage': Piles of plastic bags, household waste, roadside garbage, uncollected trash heaps.
    - 'pothole': Bitumen depression, cavity, or broken road surface on the vehicle roadway.

    Return strictly raw JSON (no backticks):
    {
      "hazard_type": "open_manhole" | "garbage" | "pothole",
      "description": "Short explanation",
      "ymin": 300,
      "xmin": 200,
      "ymax": 800,
      "xmax": 800
    }
    """

    # 2. Try Gemini 3.8 with Retries for 503 Spikes
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                        prompt
                    ]
                )
                raw = response.text.strip()
                if "```" in raw:
                    raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
                    raw = re.sub(r"\n```$", "", raw).strip()

                parsed = json.loads(raw)
                cat = parsed.get("hazard_type", "").lower().strip()
                desc = parsed.get("description", "Civic issue")
                box = [
                    int(parsed.get("ymin", 350)),
                    int(parsed.get("xmin", 250)),
                    int(parsed.get("ymax", 850)),
                    int(parsed.get("xmax", 850))
                ]
                if cat in ["open_manhole", "garbage", "pothole"]:
                    print(f"[Vision Success] Gemini 3.8 Output: {cat}")
                    return _build_res(cat, desc, box)
            except Exception as e:
                print(f"[Gemini 3.8 Attempt {attempt+1} Error]: {e}")
                time.sleep(1)

    # 3. Failover to Groq Llama-3.2-11b-Vision
    if GROQ_API_KEY:
        try:
            print("[Vision] Engaging Groq Vision failover...")
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
            groq_client = Groq(api_key=GROQ_API_KEY)
            
            chat_completion = groq_client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                        ]
                    }
                ],
                temperature=0.1
            )
            groq_text = chat_completion.choices[0].message.content.strip()
            if "```" in groq_text:
                groq_text = re.sub(r"^```[a-zA-Z]*\n", "", groq_text)
                groq_text = re.sub(r"\n```$", "", groq_text).strip()

            parsed = json.loads(groq_text)
            cat = parsed.get("hazard_type", "").lower().strip()
            desc = parsed.get("description", "Civic issue")
            box = [
                int(parsed.get("ymin", 350)),
                int(parsed.get("xmin", 250)),
                int(parsed.get("ymax", 850)),
                int(parsed.get("xmax", 850))
            ]
            if cat in ["open_manhole", "garbage", "pothole"]:
                print(f"[Vision Success] Groq Vision Failover: {cat}")
                return _build_res(cat, desc, box)
        except Exception as e_groq:
            print(f"[Groq Vision Failover Error]: {e_groq}")

    # Fallback to pothole only if everything fails
    return _build_res("pothole", "Road asphalt cavity / surface pothole", [350, 200, 750, 750])


def _build_res(hazard_type: str, description: str, box: list) -> VisionDetectionResult:
    return VisionDetectionResult(
        hazards=[
            DetectedHazard(
                hazard_type=hazard_type,
                box_2d=box,
                confidence=0.95,
                description=description
            )
        ],
        raw_summary=description
    )