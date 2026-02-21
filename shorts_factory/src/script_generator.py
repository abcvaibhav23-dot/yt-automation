"""Generate short-form scripts with richer, region-aware narrative templates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from random import choice, sample
import re
import tempfile
import uuid
from typing import Optional

import requests
from .secrets_manager import get_secret


@dataclass
class ScriptResult:
    script_text: str
    script_path: Optional[Path] = None
    content_prompt: str = ""


TECH_IDEAS = [
    "फोन की एक सेटिंग बैटरी 20% तक बचा सकती है",
    "तीन शॉर्टकट से आपका काम दोगुना तेज हो सकता है",
    "एक छोटा ऑटोमेशन रोज़ का 30 मिनट बचा सकता है",
]

FUNNY_IDEAS = [
    "अलार्म बजता है और दिमाग कहता है पांच मिनट और",
    "वो दोस्त जो बोलता है बाहर हूँ, पर अभी घर पर होता है",
    "मीटिंग में वाई-फाई स्लो, ब्रेक में सुपरफास्ट",
]

BHAKTI_IDEAS = [
    "सुबह की शुरुआत कृतज्ञता और एक गहरी सांस से करें",
    "अनुशासन ही कर्म-भक्ति का सबसे सरल रूप है",
    "धैर्य और निरंतरता मिलकर जीवन बदल देते हैं",
]

REGIONAL_IDEAS = {
    "mirzapur": [
        "छोटे शहर की मेहनत ही सबसे बड़ी पहचान बनती है",
        "अपनी बोली, अपना स्वभाव और काम में ईमानदारी सबसे अलग बनाती है",
    ],
    "sonbhadra": [
        "सोनभद्र की मिट्टी जितनी सशक्त, उतना ही यहाँ के लोगों का जज़्बा",
        "लोकल हुनर को बस सही मंच चाहिए, फिर कहानी बदल जाती है",
    ],
    "bihar": [
        "बिहार का फोकस साफ़ है: मेहनत, अनुशासन और ठोस परिणाम",
        "यहाँ से निकले विचार देशभर में प्रभाव बनाते हैं",
    ],
    "default": [
        "छोटे शहरों से बड़े सपने हर दिन निकलते हैं",
        "अपनी जड़ों से जुड़कर आगे बढ़ना सबसे टिकाऊ रास्ता है",
    ],
}

PROMPT_BLUEPRINTS = {
    "tech": "Create a practical short in Hindi with one clear tech problem, one direct fix, and one actionable step.",
    "funny": "Create a relatable short in Hindi with one everyday comic setup, one punchline, and one audience CTA.",
    "bhakti": "Create a calm Hindi spiritual short with one reflective thought, one practical daily habit, and warm close.",
    "mirzapuri": "Create a confident regional Hindi short with local tone, grounded life lesson, and energetic close.",
    "regional": "Create a region-aware Hindi short with local pride, realistic value, and clean social-media cadence.",
}


PROMPT_TEMPLATE_PATHS = {
    "funny": "shorts_factory/templates/generic_prompt_templates.md#template-1",
    "mirzapuri": "shorts_factory/templates/generic_prompt_templates.md#template-2",
    "regional": "shorts_factory/templates/generic_prompt_templates.md#template-2",
}

PROMPT_ANGLES = {
    "tech": [
        "Angle: myth vs fact",
        "Angle: quick before/after",
        "Angle: one mistake + one fix",
        "Angle: student-friendly practical use",
    ],
    "funny": [
        "Angle: daily life exaggeration",
        "Angle: office/college relatability",
        "Angle: one-liner punch ending",
        "Angle: awkward social moment",
    ],
    "bhakti": [
        "Angle: calm reflection",
        "Angle: daily discipline reminder",
        "Angle: gratitude and patience",
        "Angle: stress-to-peace micro habit",
    ],
    "mirzapuri": [
        "Angle: local pride + humor",
        "Angle: grounded life lesson",
        "Angle: confidence with humility",
        "Angle: struggle to growth",
    ],
    "regional": [
        "Angle: local problem local solution",
        "Angle: youth and opportunity",
        "Angle: identity and progress",
        "Angle: culture with modern hustle",
    ],
}

SCRIPT_PARTS = {
    "tech": {
        "hooks": [
            "रुको, ये टेक ट्रिक आपका रोज़ का झंझट आधा कर सकती है।",
            "तीन सेकंड दो, ये सेटिंग काम सच में आसान कर देगी।",
            "अगर फोन स्लो लगता है, ये बात अभी काम आएगी।",
            "स्क्रॉल रोकिए, ये टिप आज ही टेस्ट करने लायक है।",
        ],
        "bridges": [
            "सीधा मुद्दा: बड़ा काम, छोटा बदलाव।",
            "नो फालतू बात, बस सीधा करने लायक स्टेप।",
            "इसको करके तुरंत फर्क समझ आएगा।",
            "ये वही शॉर्टकट है जो लोग मिस कर देते हैं।",
        ],
        "closes": [
            "अगर काम आए, इसे सेव करो और दोस्त को भेजो।",
            "ऐसी प्रैक्टिकल टेक शॉर्ट्स चाहिए तो फॉलो करो।",
            "टेस्ट करो, रिजल्ट कमेंट में लिखो।",
            "एक बार ट्राय करके बताओ, काम आया या नहीं।",
        ],
    },
    "funny": {
        "hooks": [
            "ये सीन देखा तो लगा, कैमरा मेरे घर में लगा है।",
            "हंसना मत... लेकिन ये हम सबने किया है।",
            "एकदम पर्सनल हमला टाइप रिलेटेबल मोमेंट शुरू।",
            "अगर ये आपके साथ नहीं हुआ, तो आप लेजेंडरी हो।",
        ],
        "bridges": [
            "पहले लगता है सब कंट्रोल में है... फिर कहानी पलटती है।",
            "नॉर्मल दिन था... फिर दिमाग ने कॉमेडी मोड ऑन कर दिया।",
            "एक छोटा डिसीजन... और पूरा ड्रामा शुरू।",
            "जो प्लान बनाया था, किस्मत ने उसका रीमिक्स कर दिया।",
        ],
        "closes": [
            "सच-सच बताओ, ये तुम हो या तुम्हारा दोस्त?",
            "टैग करो उस इंसान को जो बिल्कुल ऐसा ही करता है।",
            "अगर हंसी आई तो अगला पार्ट बनता है।",
            "कमेंट में लिखो: 'ये तो मेरी ही कहानी है'।",
        ],
    },
    "bhakti": {
        "hooks": [
            "आज की 30 सेकंड की बात, मन को हल्का कर देगी।",
            "थोड़ा रुकिए... ये एक विचार दिन बदल सकता है।",
            "शांति चाहिए तो ये छोटा अभ्यास याद रखिए।",
            "जल्दी में भी मन को स्थिर करने का एक सरल तरीका।",
        ],
        "bridges": [
            "बड़ी साधना से पहले छोटी निरंतरता काम करती है।",
            "दिन का रुख अक्सर एक विचार से बदलता है।",
            "जब मन भटके, सांस और कृतज्ञता पर लौट आइए।",
            "शांत मन से लिया निर्णय सबसे मजबूत होता है।",
        ],
        "closes": [
            "अगर यह बात उपयोगी लगी हो, किसी अपने तक पहुंचाइए।",
            "रोज़ एक मिनट, फिर फर्क खुद दिखेगा।",
            "मन शांत रहे, यही आज की शुभकामना है।",
            "ऐसी mindful shorts के लिए जुड़े रहिए।",
        ],
    },
    "regional": {
        "hooks": [
            "लोकल कहानी, लेकिन सीख पूरी दुनिया के लिए।",
            "छोटे शहर का अंदाज़, बड़ा असर वाली बात।",
            "जड़ों से जुड़ी ये लाइन सीधी दिल तक जाएगी।",
            "रियल लाइफ, रियल संघर्ष, रियल जीत की बात।",
        ],
        "bridges": [
            "यहाँ मेहनत धीरे दिखती है, लेकिन गहरी होती है।",
            "अपनी बोली और अपने तरीके में अलग ताकत होती है।",
            "लोकल समझ ही असली edge देती है।",
            "ज़मीन से जुड़ा नजरिया लंबे समय तक टिकता है।",
        ],
        "closes": [
            "अगर बात अपनी लगी, इसे शेयर जरूर करें।",
            "आपके शहर की कहानी भी कमेंट में लिखिए।",
            "ऐसी जमीन से जुड़ी शॉर्ट्स के लिए चैनल फॉलो कीजिए।",
            "लोकल गर्व को आगे बढ़ाइए, वीडियो सेव करें।",
        ],
    },
}

_FOCUS_STOPWORDS = {
    "create",
    "short",
    "hindi",
    "with",
    "one",
    "and",
    "for",
    "the",
    "this",
    "that",
    "channel",
    "context",
    "region",
    "focus",
    "angle",
    "user",
    "hint",
    "variation",
    "nonce",
    "shorts",
    "today",
    "generate",
    "high",
    "retention",
    "voice",
    "delivery",
}

_FOCUS_TOKEN_RENDER = {
    "tech": "टेक",
    "regional": "रीजनल",
    "funny": "फनी",
    "bhakti": "भक्ति",
    "comedy": "कॉमेडी",
    "office": "ऑफिस",
    "college": "कॉलेज",
    "daily": "डेली",
    "local": "लोकल",
    "story": "कहानी",
    "youth": "युवा",
    "jobs": "नौकरी",
    "discipline": "अनुशासन",
    "gratitude": "कृतज्ञता",
    "habit": "आदत",
    "focus": "फोकस",
}


def _normalize_style(style: str) -> str:
    normalized = style.strip().lower()
    if normalized == "motivation":
        return "bhakti"
    if normalized not in {"tech", "funny", "bhakti", "mirzapuri", "regional"}:
        raise ValueError("Unsupported style. Choose from: tech, funny, bhakti, motivation, mirzapuri, regional")
    return normalized


def _normalize_region(region: Optional[str]) -> str:
    return (region or "mirzapur").strip().lower()


def _extract_focus_terms(content_prompt: str, prompt_hint: Optional[str]) -> list[str]:
    combined = f"{content_prompt} {prompt_hint or ''}".strip()
    if not combined:
        return []
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}|[\u0900-\u097F]{3,}", combined.lower())
    keep: list[str] = []
    for tok in tokens:
        if tok in _FOCUS_STOPWORDS:
            continue
        if tok not in keep:
            keep.append(tok)
    return keep[:10]


def _pick_focus_line(content_prompt: str, prompt_hint: Optional[str]) -> str:
    terms = _extract_focus_terms(content_prompt=content_prompt, prompt_hint=prompt_hint)
    if not terms:
        return ""
    cleaned = [_FOCUS_TOKEN_RENDER.get(x, x) for x in terms]
    # keep only Hindi-like or mapped short terms for clean narration.
    filtered = [x for x in cleaned if re.search(r"[\u0900-\u097F]", x) or len(x) <= 10]
    chosen = sample(filtered or cleaned, k=min(2, len(filtered or cleaned)))
    return "आज का फोकस: " + " और ".join(chosen) + "।"


def _build_rich_script(
    style: str,
    channel_name: str,
    region: str,
    prompt_hint: Optional[str],
    content_prompt: str,
) -> str:
    style_key = "regional" if style in {"mirzapuri", "regional"} else style
    style_parts = SCRIPT_PARTS.get(style_key, SCRIPT_PARTS["regional"])

    if style == "tech":
        idea = choice(TECH_IDEAS)
    elif style == "funny":
        idea = choice(FUNNY_IDEAS)
    elif style == "bhakti":
        idea = choice(BHAKTI_IDEAS)
    else:
        pool = REGIONAL_IDEAS.get(region, REGIONAL_IDEAS["default"])
        idea = choice(pool)
    hook = choice(style_parts["hooks"])
    value = choice(style_parts["bridges"])
    close = choice(style_parts["closes"])

    prompt_line = _pick_focus_line(content_prompt=content_prompt, prompt_hint=prompt_hint)
    lines = [
        f"नमस्ते दोस्तों, {channel_name} में आपका स्वागत है।",
        hook,
        value,
        idea + ".",
    ]
    if prompt_line:
        lines.append(prompt_line)
    lines.append(close)
    return " ".join(lines)


def auto_content_prompt(style: str, region: Optional[str], channel_name: str, prompt_hint: Optional[str]) -> str:
    normalized_style = _normalize_style(style)
    normalized_region = _normalize_region(region)
    base = PROMPT_BLUEPRINTS.get(normalized_style, PROMPT_BLUEPRINTS["regional"])
    angle = choice(PROMPT_ANGLES.get(normalized_style, PROMPT_ANGLES["regional"]))
    region_bit = f"Region focus: {normalized_region.title()}."
    channel_bit = f"Channel context: {channel_name}."
    hint_bit = f"User hint: {prompt_hint.strip()}." if prompt_hint else ""
    variation_bit = f"Variation nonce: {datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}."
    local_prompt = " ".join([base, angle, region_bit, channel_bit, hint_bit, variation_bit]).strip()

    history_key = _prompt_history_key(normalized_style, normalized_region, channel_name)
    last_prompt = _load_last_prompt(history_key)

    # Try multiple times to avoid repeated prompt across runs.
    for _ in range(3):
        ai_prompt = _generate_prompt_via_chatgpt(
            style=normalized_style,
            region=normalized_region,
            channel_name=channel_name,
            prompt_hint=prompt_hint,
            local_fallback=local_prompt,
            avoid_text=last_prompt,
        )
        prompt = (ai_prompt or local_prompt).strip()
        if not _is_same_prompt(prompt, last_prompt):
            _save_last_prompt(history_key, prompt)
            return prompt
        # mutate fallback to force variation if equality still happens
        local_prompt = local_prompt + f" Variant token {uuid.uuid4().hex[:4]}."

    _save_last_prompt(history_key, local_prompt)
    return local_prompt


def _generate_prompt_via_chatgpt(
    *,
    style: str,
    region: str,
    channel_name: str,
    prompt_hint: Optional[str],
    local_fallback: str,
    avoid_text: Optional[str],
) -> Optional[str]:
    if os.getenv("OPENAI_PROMPTS_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
        return None

    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    nonce = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    template_ref = PROMPT_TEMPLATE_PATHS.get(style, "local-style-template")

    system_msg = (
        "You create high-retention YouTube Shorts content prompts. "
        "Return one concise prompt line only, no markdown."
    )
    user_msg = (
        f"Generate ONE unique Shorts content prompt for today.\n"
        f"Style: {style}\n"
        f"Region: {region}\n"
        f"Channel: {channel_name}\n"
        f"Template reference: {template_ref}\n"
        f"Hint: {prompt_hint or 'none'}\n"
        f"Quality goals: hook in first 3 seconds, strong retention, scene-friendly cues, smooth AI voice delivery.\n"
        f"Make it different from previous outputs. Variation nonce: {nonce}\n"
        f"Do NOT repeat or closely paraphrase this previous prompt:\n{avoid_text or 'N/A'}\n"
        f"Keep under 260 characters.\n"
    )

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_msg}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_msg}]},
        ],
        "max_output_tokens": 140,
        "temperature": 0.95,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post("https://api.openai.com/v1/responses", json=payload, headers=headers, timeout=30)
    except requests.RequestException:
        return None

    if resp.status_code != 200:
        return None

    try:
        body = resp.json()
    except ValueError:
        return None

    text = (body.get("output_text") or "").strip()
    if not text:
        # Fallback parse for older response shapes.
        output = body.get("output", [])
        for item in output:
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    text = content["text"].strip()
                    break
            if text:
                break

    if not text:
        return None

    text = " ".join(text.split())
    if len(text) > 260:
        text = text[:257].rstrip() + "..."
    return text or local_fallback


def _prompt_history_key(style: str, region: str, channel_name: str) -> str:
    slug = f"{style}_{region}_{channel_name}".lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    return re.sub(r"_+", "_", slug).strip("_")


def _history_path(key: str) -> Path:
    return Path(tempfile.gettempdir()) / f"shorts_last_prompt_{key}.txt"


def _load_last_prompt(key: str) -> Optional[str]:
    p = _history_path(key)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8").strip()
    return text or None


def _save_last_prompt(key: str, prompt: str) -> None:
    p = _history_path(key)
    p.write_text(prompt.strip(), encoding="utf-8")


def _script_history_path(key: str) -> Path:
    return Path(tempfile.gettempdir()) / f"shorts_last_script_{key}.txt"


def _load_last_script(key: str) -> Optional[str]:
    p = _script_history_path(key)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8").strip()
    return text or None


def _save_last_script(key: str, script_text: str) -> None:
    p = _script_history_path(key)
    p.write_text(script_text.strip(), encoding="utf-8")


def _normalize_prompt_for_compare(text: Optional[str]) -> str:
    if not text:
        return ""
    out = text.lower().strip()
    out = re.sub(r"variation nonce:\s*[a-z0-9\-_. ]+", "", out)
    out = re.sub(r"variant token\s*[a-z0-9]+", "", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _is_same_prompt(a: Optional[str], b: Optional[str]) -> bool:
    return _normalize_prompt_for_compare(a) == _normalize_prompt_for_compare(b)


def _normalize_script_for_compare(text: Optional[str]) -> str:
    if not text:
        return ""
    out = text.lower().strip()
    out = re.sub(r"variation nonce:\s*[a-z0-9\-_. ]+", "", out)
    out = re.sub(r"theme input:\s*", "theme input:", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _is_same_script(a: Optional[str], b: Optional[str]) -> bool:
    return _normalize_script_for_compare(a) == _normalize_script_for_compare(b)


def generate_script(
    style: str,
    channel_name: str,
    scripts_dir: Path,
    region: Optional[str] = None,
    persist: bool = False,
    prompt_hint: Optional[str] = None,
) -> ScriptResult:
    """Generate a richer script; optionally persist it."""
    normalized_style = _normalize_style(style)
    normalized_region = _normalize_region(region)
    history_key = _prompt_history_key(normalized_style, normalized_region, channel_name)
    last_script = _load_last_script(history_key)
    content_prompt = ""
    script_text = ""

    for attempt in range(4):
        retry_hint = prompt_hint
        if attempt > 0:
            token = uuid.uuid4().hex[:6]
            retry_hint = f"{(prompt_hint or '').strip()} retry-{token}".strip()
        content_prompt = auto_content_prompt(
            style=normalized_style,
            region=normalized_region,
            channel_name=channel_name,
            prompt_hint=retry_hint,
        )
        script_text = _build_rich_script(
            style=normalized_style,
            channel_name=channel_name,
            region=normalized_region,
            prompt_hint=prompt_hint,
            content_prompt=content_prompt,
        )
        if not _is_same_script(script_text, last_script):
            break

    _save_last_script(history_key, script_text)

    if persist:
        from datetime import datetime

        from .config import timestamp_slug

        filename = f"{datetime.now().strftime('%Y-%m-%d')}_{normalized_style}_{timestamp_slug()}.txt"
        script_path = scripts_dir / filename
        script_path.write_text(script_text, encoding="utf-8")
        return ScriptResult(script_text=script_text, script_path=script_path, content_prompt=content_prompt)

    return ScriptResult(script_text=script_text, script_path=None, content_prompt=content_prompt)
