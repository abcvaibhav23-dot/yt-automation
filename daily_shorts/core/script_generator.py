"""Script generation via OpenAI with strict JSON output."""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import requests

from config.settings import DATA_DIR, MAX_WORDS, OPENAI_API_KEY, OPENAI_MODEL


@dataclass
class ScriptResult:
    payload: Dict
    topic: str
    api_calls: int


GENERIC_BANNED_SUBSTRINGS = [
    "2 minute rule",
    "speed se pehle clarity",
    "useful laga toh follow",
    "part-2",
    "part 2",
    "follow karke 'next'",
]


def _build_system_prompt(language_mode: str, max_scenes: int) -> str:
    return (
        "You are a YouTube Shorts script writer. Output strict JSON only. "
        f"Max words {MAX_WORDS}. Total duration 30-75 sec. Max scenes {max_scenes}. "
        f"Language mode: {language_mode}. Use easy spoken words and high retention pacing."
    )


def _topic_tokens(topic: str) -> List[str]:
    return [w.lower() for w in re.findall(r"[a-zA-Z]+", topic) if len(w) > 2]


def _norm_sig(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def _load_recent_hook_signatures(limit: int = 30) -> set[str]:
    path = DATA_DIR / "history.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        runs = list(data.get("runs", []))[-limit:]
        return {_norm_sig(r.get("hook_variant", "")) for r in runs if r.get("hook_variant")}
    except Exception:
        return set()


def _load_recent_scene_signatures(limit_runs: int = 20) -> set[str]:
    path = DATA_DIR / "history.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        runs = list(data.get("runs", []))[-limit_runs:]
        out: set[str] = set()
        for run in runs:
            for line in run.get("scene_texts", []) or []:
                sig = _norm_sig(line)
                if sig:
                    out.add(sig)
        return out
    except Exception:
        return set()


def _pick_first_unused(candidates: List[str], blocked: set[str], fallback: str) -> str:
    for c in _pick_unique(candidates, len(candidates)):
        if _norm_sig(c) not in blocked:
            return c
    return fallback


def _pick_unique(lines: List[str], count: int) -> List[str]:
    bag = [x for x in lines if x.strip()]
    random.shuffle(bag)
    out: List[str] = []
    seen = set()
    for x in bag:
        low = x.lower().strip()
        if low in seen:
            continue
        out.append(x.strip())
        seen.add(low)
        if len(out) >= count:
            break
    return out


def _channel_fallback_banks(channel: str, topic: str) -> Dict[str, List[str]]:
    t = topic.strip()
    ch = channel.strip().lower()
    if ch == "funny":
        return {
            "hooks": [
                f"Wait... {t} mein sabse funny fail point kya nikla?",
                f"Ruko... {t} ka asli comedy twist suno.",
                f"{t} mein log itni simple galti kyun repeat karte hain?",
            ],
            "setup": [
                f"Scene: {t} start hota hai full confidence se.",
                f"Real life mein {t} pe sab plan strong lagta hai.",
                f"{t} ka pehla step easy dikhta hai, wahi trap hota hai.",
                f"{t} ke start mein sab smooth lagta hai, phir timing fail hoti hai.",
                f"{t} mein sabko lagta hai problem bahar ki hai, par glitch andar ka hota hai.",
                f"{t} ka plan funny tab banta hai jab basic check skip ho jaata hai.",
            ],
            "build": [
                "Phir ek chhota miss hota hai... aur pura flow ulta padta hai.",
                "Sab haste hain, par andar se sabko same issue hota hai.",
                "Jitna fast karte ho, utna hi result funny tareeke se slip hota hai.",
                "Ek second ka shortcut, aur agle 10 minute damage control mein nikalte hain.",
                "Scene itna relatable hota hai ki har group mein ek banda ye karta hi karta hai.",
                "Sabko lagta hai kaam ho gaya... phir twist mein sab reset karna padta hai.",
            ],
            "fix": [
                "Fix: pehle 10-second check karo, phir next move lo.",
                "Fix: ek time pe ek hi step rakho, chaos half ho jayega.",
                "Fix: sequence simple rakho, over-smart mat bano.",
                "Fix: jo line repeat hoti hai usko pehle solve karo, baaki auto smooth ho jayega.",
                "Fix: start se pehle mini checklist bolo, galti half ho jayegi.",
                "Fix: pehla task easy rakho, confidence ke saath pace build karo.",
            ],
            "twist": [
                "Twist: problem skill ki nahi, timing ki hoti hai.",
                "Twist: smart log bhi isi basic point pe atak jaate hain.",
                "Twist: shortcut cute lagta hai, output ko hurt karta hai.",
                "Twist: jo loud lagta hai wo useful nahi hota, jo simple hai wahi bachata hai.",
                "Twist: asli hack naye tool mein nahi, first 20 seconds mein chhupa hota hai.",
                "Twist: galti chhoti hoti hai, par uski chain reaction badi hoti hai.",
            ],
            "cta": [
                "Relatable laga? Comment mein apna version drop karo.",
                "Ye scene apne us dost ko bhejo jo exactly aisa karta hai.",
                "Aisa aapke saath bhi hua ho toh comment mein 'same' likho.",
                "Is short ko save karo, kal test karke result batao.",
                "Next funny short ke liye follow karo aur topic suggest karo.",
            ],
        }
    if ch == "bhakti":
        return {
            "hooks": [
                f"Aaj {t} mein ek chhota sa satya suno.",
                f"{t} karte waqt ye bhav rakhenge toh shanti badhegi.",
                f"{t} ka ek simple niyam, jo mann ko halka karta hai.",
            ],
            "setup": [
                f"Subah ka samay, {t} ka arambh, aur mann thoda bhatakta hai.",
                f"{t} mein niyat sahi ho toh anubhav gehra hota hai.",
                f"{t} ka pehla pal hi poore din ka bhaav set karta hai.",
                f"{t} ke dauran chhote vichar aate hain, unhe prem se dekhna zaroori hai.",
            ],
            "build": [
                "Jab dhyan toot-ta hai, shraddha kam nahi hoti... bas saans sambhalni hoti hai.",
                "Chhoti vyastata aati hai, phir bhi man ko prem se wapas la sakte hain.",
                "Bahari shor rehta hai, andar ki shanti fir bhi jag sakti hai.",
            ],
            "fix": [
                "Upay: 3 gehri saans, phir ek line mantra ko dhire bolo.",
                "Upay: aankhen band karke 20 second gratitude par dhyan do.",
                "Upay: chhota sankalp lo, poora din halka lagega.",
                "Upay: ek hi prarthana line par 5 saans tak man ko tikaye rakho.",
            ],
            "twist": [
                "Satya: lamba samay nahi, sache bhaav se parivartan aata hai.",
                "Satya: tezi se nahi, sthirta se bhakti gehri hoti hai.",
                "Satya: jab mann komal hota hai, prarthana swayam sundar ho jaati hai.",
            ],
            "cta": [
                "Agar shanti mili ho toh comment mein 'Radhe Radhe' likhiye.",
                "Isko kisi apne ke saath share kijiye jise aaj santulan chahiye.",
                "Aise hi aur bhakti shorts ke liye follow zaroor kijiye.",
                "Aaj ka mantra kaunsa rakhen, comment mein batayiye.",
            ],
        }
    if ch == "tech":
        return {
            "hooks": [
                f"{t} mein log sabse costly mistake kya karte hain?",
                f"Stop scrolling: {t} ka ek high-impact fix abhi.",
                f"{t} slow kyun lagta hai jab sab tools same hain?",
            ],
            "setup": [
                f"{t} mein sab feature add karte rehte hain, result stable nahi hota.",
                f"Team {t} pe kaam karti hai, par bottleneck detect nahi hota.",
                f"{t} ka start fast hota hai, phir performance dip aata hai.",
                f"{t} mein logs clear na ho toh debugging blind ho jaati hai.",
            ],
            "build": [
                "Issue mostly tooling ka nahi, process order ka hota hai.",
                "Data clear na ho toh smart decisions bhi random lagte hain.",
                "Jaldi mein context skip hota hai, aur rework double ho jata hai.",
            ],
            "fix": [
                "Fix: ek metric lock karo, phir har step usi ke against check karo.",
                "Fix: pehle bottleneck isolate karo, tab optimization start karo.",
                "Fix: 15-minute review loop add karo, drift turant pakdega.",
                "Fix: baseline snapshot banao, phir change ko one-by-one test karo.",
            ],
            "twist": [
                "Twist: best tool nahi, best sequence output improve karta hai.",
                "Twist: speed badhane se pehle clarity badhao.",
                "Twist: chhota process tweak, bada performance jump deta hai.",
            ],
            "cta": [
                "Useful laga? Isko save karo aur team ke saath share karo.",
                "Aise practical tech shorts ke liye follow karo.",
                "Comment karo: next kis tech topic pe short chahiye?",
                "Aapke stack ka sabse bada bottleneck kya hai, comment karo.",
            ],
        }
    return {
        "hooks": [
            f"{t} ke peeche ka asli game kya hai?",
            f"{t} mein log kis point pe bold move lete hain?",
            f"{t} ka hidden rule jo sab ignore karte hain.",
        ],
        "setup": [
            f"{t} ka scene simple lagta hai, par pressure high hota hai.",
            f"{t} mein pehla impression hi game ka direction badal deta hai.",
            f"{t} ka pattern samjho, phir decision easy ho jayega.",
            f"{t} mein jo nahi dikh raha hota, wahi asli signal deta hai.",
        ],
        "build": [
            "Yahan confidence aur caution ka balance zaroori hota hai.",
            "Aksar log jaldi mein core signal miss kar dete hain.",
            "Ek wrong read, aur poora mood change ho jata hai.",
        ],
        "fix": [
            "Fix: pehle observe karo, phir action lo.",
            "Fix: clear priority set karo, phir move karo.",
            "Fix: small win se momentum build karo.",
            "Fix: pehla decision slow lo, agle decisions fast ho jayenge.",
        ],
        "twist": [
            "Twist: jeet force se nahi, rhythm se milti hai.",
            "Twist: loud move nahi, right move kaam karta hai.",
            "Twist: jahan sab rush karte hain, wahi pause jeetata hai.",
        ],
        "cta": [
            "Agar line hit ki ho toh follow karo.",
            "Apna take comment mein drop karo.",
            "Isko us dost ko bhejo jo ye scene samjhega.",
            "Aisa moment aapke saath hua ho toh comment mein batao.",
        ],
    }


def _fallback_script(topic: str, channel: str, max_scenes: int) -> Dict:
    scene_count = min(max(5, max_scenes), 7)
    base_tokens = _topic_tokens(topic)
    base_kw = base_tokens[0] if base_tokens else "india"
    banks = _channel_fallback_banks(channel, topic)
    blocked_hooks = _load_recent_hook_signatures()
    blocked_scenes = _load_recent_scene_signatures()
    fallback_hook = banks["hooks"][0]

    selected = {
        "hook": _pick_first_unused(banks["hooks"], blocked_hooks, fallback_hook),
        "setup": _pick_first_unused(banks["setup"], blocked_scenes, banks["setup"][0]),
        "build": _pick_first_unused(banks["build"], blocked_scenes, banks["build"][0]),
        "fix": _pick_first_unused(banks["fix"], blocked_scenes, banks["fix"][0]),
        "twist": _pick_first_unused(banks["twist"], blocked_scenes, banks["twist"][0]),
        "cta": _pick_first_unused(banks["cta"], blocked_scenes, banks["cta"][0]),
    }
    extras = _pick_unique(
        [
            f"{topic} mein ye one-line shift kaafi log miss karte hain.",
            f"Aaj se {topic} mein ek hi rule yaad rakho: simple raho, consistent raho.",
            f"Is point ko apply karke kal se {topic} ka output compare karo.",
        ],
        2,
    )
    chosen = [
        selected["hook"],
        selected["setup"],
        selected["build"],
        selected["fix"],
        selected["twist"],
        selected["cta"],
        *extras,
    ][:scene_count]
    scenes = []
    for idx, text in enumerate(chosen):
        scene_tokens = [w.lower() for w in re.findall(r"[a-zA-Z]+", text) if len(w) > 3]
        alt_kw = scene_tokens[0] if scene_tokens else f"scene{idx+1}"
        second_kw = base_tokens[min(idx, len(base_tokens) - 1)] if base_tokens else alt_kw
        scenes.append(
            {
                "text": text,
                "keywords": _derive_keywords(
                    text,
                    [base_kw, second_kw, channel.lower(), "india"],
                ),
                "tone": "engaging",
                "duration_estimate": 6,
            }
        )
    target_total = _target_total_from_scenes(scenes)
    scenes = _rebalance_scene_durations(scenes, target_total=target_total)
    scenes = _sanitize_generic_lines(scenes, topic=topic, channel=channel)
    return {
        "title": f"{channel.title()} Short: {topic.title()}",
        "scenes": scenes[:scene_count],
        "total_duration": int(sum(s["duration_estimate"] for s in scenes[:scene_count])),
    }


def _dedupe_scene_texts(scenes: List[Dict]) -> List[Dict]:
    seen = set()
    fixed: List[Dict] = []
    for idx, scene in enumerate(scenes, start=1):
        text = " ".join(str(scene.get("text", "")).split()).strip()
        low = text.lower()
        if not text:
            text = f"Scene {idx} update."
            low = text.lower()
        if low in seen:
            text = f"{text} - part {idx}"
            low = text.lower()
        seen.add(low)
        scene["text"] = text
        fixed.append(scene)
    return fixed


def _rebalance_scene_durations(scenes: List[Dict], target_total: int = 48) -> List[Dict]:
    # Derive duration from spoken length to avoid long silence after short lines.
    raw: List[int] = []
    for scene in scenes:
        words = len([w for w in str(scene.get("text", "")).split() if w])
        est = max(4, min(11, round(words / 2.4)))  # ~2.4 words/sec for Hinglish delivery
        raw.append(int(est))
    current = sum(raw) or 1
    scale = max(0.7, min(1.4, target_total / current))
    scaled = [max(4, min(11, int(round(x * scale)))) for x in raw]

    # Fine tune by +/-1 sec until total close to target and still in constraints.
    total = sum(scaled)
    i = 0
    while total != target_total and i < 500 and scaled:
        idx = i % len(scaled)
        if total < target_total and scaled[idx] < 11:
            scaled[idx] += 1
            total += 1
        elif total > target_total and scaled[idx] > 4:
            scaled[idx] -= 1
            total -= 1
        i += 1

    for scene, dur in zip(scenes, scaled):
        scene["duration_estimate"] = int(dur)
    return scenes


def _target_total_from_scenes(scenes: List[Dict]) -> int:
    total_words = sum(len([w for w in str(s.get("text", "")).split() if w]) for s in scenes)
    # ~2.1 words/sec spoken Hinglish + buffer
    estimated = int(round(total_words / 2.1)) + 3
    return int(max(30, min(75, estimated)))


def _derive_keywords(text: str, fallback: List[str]) -> List[str]:
    tokens = [w.lower() for w in re.findall(r"[a-zA-Z]+", text) if len(w) > 3]
    uniq = []
    seen = set()
    for t in [*tokens, *fallback]:
        if t not in seen:
            uniq.append(t)
            seen.add(t)
        if len(uniq) >= 4:
            break
    return uniq or fallback[:4]


def _validate_script(data: Dict, max_scenes: int) -> Dict:
    if not isinstance(data, dict):
        raise ValueError("Script payload is not object")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("Missing scenes")
    scenes = scenes[:max_scenes]
    cleaned: List[Dict] = []
    for s in scenes:
        text = " ".join(str(s.get("text", "")).split())
        if not text:
            continue
        fallback_kw = [str(k).strip().lower() for k in s.get("keywords", []) if str(k).strip()]
        cleaned.append(
            {
                "text": text,
                "keywords": _derive_keywords(text, fallback_kw or ["india"]),
                "tone": str(s.get("tone", "neutral")).strip() or "neutral",
                "duration_estimate": int(max(4, min(15, int(s.get("duration_estimate", 8))))),
            }
        )
    if len(cleaned) < 5:
        raise ValueError("Insufficient scenes after cleanup")
    cleaned = _dedupe_scene_texts(cleaned)
    cleaned = _rebalance_scene_durations(cleaned, target_total=_target_total_from_scenes(cleaned))
    total_duration = int(sum(x["duration_estimate"] for x in cleaned))
    data = {
        "title": str(data.get("title", "Daily Short")).strip()[:110],
        "scenes": cleaned,
        "total_duration": int(max(30, min(75, total_duration))),
    }
    return data


def _rewrite_generic_line(text: str, topic: str, channel: str, idx: int) -> str:
    t = topic.strip()
    if idx == 0:
        return f"Wait... {t} mein aap jo ignore karte ho, wahi result decide karta hai. Kya aap bhi ye karte ho?"
    if idx == 1:
        return f"{t} ka real issue bahar se nahi dikhta, daily pattern mein chhupa hota hai."
    if idx == 2:
        return f"Jab focus tut-ta hai, {t} mein chhota error chain ban jaata hai."
    if idx == 3:
        return f"Simple move: {t} start karne se pehle ek clear priority line likho."
    if idx == 4:
        return f"Twist: {t} mein jeet speed se nahi, sahi sequence se aati hai."
    if channel == "bhakti":
        return "Agar bhav connected laga ho toh comment mein 'Radhe Radhe' likhiye."
    return "Relatable laga? Apna real example comment mein drop karo aur next short ke liye follow karo."


def _sanitize_generic_lines(scenes: List[Dict], topic: str, channel: str) -> List[Dict]:
    blocked_recent = _load_recent_scene_signatures()
    fixed: List[Dict] = []
    seen = set()
    for idx, s in enumerate(scenes):
        text = str(s.get("text", "")).strip()
        low = text.lower()
        if any(b in low for b in GENERIC_BANNED_SUBSTRINGS):
            text = _rewrite_generic_line(text, topic=topic, channel=channel, idx=idx)
        sig = _norm_sig(text)
        if sig in seen or sig in blocked_recent:
            text = _rewrite_generic_line(text, topic=topic, channel=channel, idx=idx)
            sig = _norm_sig(text)
        seen.add(sig)
        s["text"] = text
        s["keywords"] = _derive_keywords(text, s.get("keywords", ["india"]))
        fixed.append(s)
    return fixed


def generate_script(channel: str, language_mode: str, prompt_text: str, topics: List[str], max_scenes: int) -> ScriptResult:
    topic = random.choice(topics).strip()
    if not OPENAI_API_KEY:
        fallback = _validate_script(_fallback_script(topic, channel, max_scenes), max_scenes=max_scenes)
        return ScriptResult(fallback, topic, 0)

    user_prompt = (
        f"Channel: {channel}\nTopic: {topic}\nInstructions:\n{prompt_text}\n"
        "Return STRICT JSON in this exact shape: "
        '{"title":"...","scenes":[{"text":"...","keywords":["..."],"tone":"...","duration_estimate":5}],"total_duration":48}'
    )
    banned = ", ".join(GENERIC_BANNED_SUBSTRINGS)
    user_prompt += f"\nAvoid repeating these generic phrases: {banned}."
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.88,
        "max_tokens": 450,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _build_system_prompt(language_mode, max_scenes)},
            {"role": "user", "content": f"{user_prompt}\nVariation token: {random.randint(1000, 999999)}"},
        ],
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        fallback = _validate_script(_fallback_script(topic, channel, max_scenes), max_scenes=max_scenes)
        return ScriptResult(fallback, topic, 1)

    content = r.json()["choices"][0]["message"]["content"]
    try:
        data = json.loads(content)
        data = _validate_script(data, max_scenes)
        data["scenes"] = _sanitize_generic_lines(data["scenes"], topic=topic, channel=channel)
        data["scenes"] = _rebalance_scene_durations(data["scenes"], target_total=_target_total_from_scenes(data["scenes"]))
        data["total_duration"] = int(max(30, min(75, sum(x["duration_estimate"] for x in data["scenes"]))))
    except Exception:
        data = _validate_script(_fallback_script(topic, channel, max_scenes), max_scenes=max_scenes)
    return ScriptResult(data, topic, 1)
