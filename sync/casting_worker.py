"""Local worker that keeps the casting pipeline fed with generated candidates.

Polls the 2nd BRAIN server's /casting/state and /casting/list endpoints. When
generation isn't paused it (a) fills in any missing shot (face/torso/back)
for active (non-picked) models, (b) spins up a brand-new model from the
CONCEPTS rotation whenever the active headcount is below the round's target,
generating all three of its shots, and (c) ensures every active
cached-description model also has a `<Model>_glam.png` bonus shot. Every
generated PNG is uploaded back to the server via POST /casting/upload.

Image generation goes through OpenAI's images API (`OpenAI().images.generate`)
for face/torso/back, and through xAI's Grok image endpoint for the glam bonus
shot (skipped silently when XAI_API_KEY isn't set).
Since the server has no place to durably store "who is this model" free text,
this worker keeps its own small local cache (~/.brain-casting.json) mapping
model name -> concept description, so a later run can regenerate a missing
shot for a model it created earlier with the same description. Models that
show up in /casting/list without a cache entry (e.g. uploaded manually) are
left alone for step (a) — there's nothing to regenerate them from.
"""
import argparse
import base64
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx

CACHE = Path.home() / ".brain-casting.json"

SHOT_ORDER = ("face", "torso", "back")

BASE = (
    "Photorealistic professional model photography, Vogue editorial level. "
    "Subject: {who}, 173cm, slender long-legged model proportions. {shot} "
    "Fully clothed, tasteful."
)

SHOTS = {
    "face": (
        "Extreme close-up beauty portrait, face filling the frame, flawless "
        "natural skin texture, soft studio light, direct eye contact, gentle "
        "confident expression."
    ),
}

# Outfits for the torso/back shots are picked at random each generation so
# consecutive models don't all wear the same look. No school-uniform or
# lingerie items in either list.
OUTFITS_TORSO = [
    "an elegant black satin evening dress",
    "a fitted mini cocktail dress",
    "a crop top with a high-waisted mini skirt",
    "a silk camisole with tailored shorts",
    "a bodycon club dress",
    "an off-shoulder summer top",
]

OUTFITS_BACK = [
    "a figure-hugging satin evening gown",
    "a backless mini dress",
    "a crop top and denim shorts",
    "an open-back club dress",
    "a halter summer dress",
]

# Backdrop for the torso/back shots, also picked at random each generation.
SCENES = [
    "luxury interior",
    "neon-lit club",
    "rooftop at night",
    "sunny summer street",
    "studio backdrop",
]

# Softer, generic outfit phrasing used as a single retry when the primary
# prompt trips moderation (HTTP 400). Only torso/back need softening; face
# is unchanged.
SOFT_OUTFIT_TORSO = "an elegant evening dress"
SOFT_OUTFIT_BACK = "an elegant evening gown"


def _torso_shot_text(soft: bool = False) -> str:
    outfit = SOFT_OUTFIT_TORSO if soft else random.choice(OUTFITS_TORSO)
    scene = random.choice(SCENES)
    return (
        f"Waist-up editorial portrait facing the camera, wearing {outfit}, "
        "delicate necklace, poised posture, warm cinematic light, direct "
        f"gaze, soft smile, {scene}."
    )


def _back_shot_text(soft: bool = False) -> str:
    outfit = SOFT_OUTFIT_BACK if soft else random.choice(OUTFITS_BACK)
    scene = random.choice(SCENES)
    return (
        f"Full-body photograph from behind, wearing {outfit}, she glances "
        "back over her shoulder at the camera with a subtle smile, "
        f"cinematic rim light, {scene}."
    )


# Grok "glamour" bonus shot: one extra image per model, generated via xAI's
# Grok image endpoint instead of OpenAI. Silently skipped when XAI_API_KEY
# isn't set. View and pose/register are chosen at random each time.
XAI_IMAGE_URL = "https://api.x.ai/v1/images/generations"
XAI_IMAGE_MODEL = "grok-imagine-image-quality"

GLAM_VIEWS = ("front", "back")

# At least 8 distinct, elegant, dynamic poses.
POSES = [
    "walking toward the camera mid-stride",
    "seated elegantly on a lounge chair",
    "leaning against a railing, gazing into the distance",
    "hair caught dramatically by the wind",
    "caught mid-turn, glancing back over her shoulder",
    "arms raised in a graceful stretch overhead",
    "stepping down a grand staircase",
    "looking back mid-stride with a confident glance",
]

# Styling register: one notch more glamorous than the other shots, but never
# beyond this fixed set.
GLAM_REGISTERS = [
    "elegant resort swimwear beside an infinity pool",
    "an evening gown with a dramatic open back",
    "a gown with an elegant leg slit",
    "an off-shoulder summer dress on a sunlit terrace",
    "a sexy mini skirt and heels on a city night street",
    "a club outfit under neon lights",
    "a crop top and mini shorts on a beach boardwalk",
]

GLAM_SAFETY = "Editorial, tasteful, no lingerie, no nudity."

GLAM_IDENTITY = (
    "Photorealistic professional model photography, Vogue editorial level. "
    "Subject: {who}, 173cm, slender long-legged model proportions."
)


def build_glam_prompt(who: str, view: str, pose: str, register: str) -> str:
    view_desc = "Front view" if view == "front" else "Back view"
    identity = GLAM_IDENTITY.format(who=who)
    return (
        f"{identity} {view_desc}, one notch more glamorous, {pose}, "
        f"wearing {register}. {GLAM_SAFETY}"
    )


def _glam_filename(name: str) -> str:
    return f"{name}_glam.png"


def _has_glam(name: str, files) -> bool:
    target = Path(_glam_filename(name)).stem
    return any(Path(f).stem == target for f in files)


def generate_glam_shot(who: str):
    """Generate one Grok glamour PNG for `who`, or None if XAI_API_KEY unset."""
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return None
    view = random.choice(GLAM_VIEWS)
    pose = random.choice(POSES)
    register = random.choice(GLAM_REGISTERS)
    prompt = build_glam_prompt(who, view, pose, register)
    r = httpx.post(
        XAI_IMAGE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": XAI_IMAGE_MODEL,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        },
        timeout=120,
    )
    r.raise_for_status()
    payload = r.json()
    return base64.b64decode(payload["data"][0]["b64_json"])


# Casting pool: no ethnicities beyond this fixed rotation. Each entry is a
# full English description in the same style as the Korean example.
CONCEPTS = [
    "tall American woman, mid-20s, sun-kissed fair skin, golden blonde hair, "
    "bright blue eyes, athletic all-American beauty-queen elegance",
    "tall American woman, mid-20s, warm fair skin, glossy chestnut-brown hair, "
    "soft brown eyes, approachable girl-next-door glamour",
    "tall Spanish woman, mid-20s, sun-warmed olive skin, dark wavy hair, deep "
    "brown eyes, fiery flamenco-elegant beauty",
    "tall Argentinian woman, mid-20s, fair olive skin, chestnut hair, "
    "striking hazel eyes, sculpted Latin American runway-model beauty",
    "tall Russian woman, mid-20s, pale porcelain skin, platinum-blonde hair, "
    "ice-blue eyes, poised ice-queen elegance",
    "tall French woman, mid-20s, fair skin, sleek dark bob, refined "
    "cheekbones, understated Parisian elegance",
    "tall Italian woman, mid-20s, sun-kissed olive skin, glossy dark-brown "
    "hair, warm brown eyes, sculptural Mediterranean elegance",
    "tall Scandinavian woman, mid-20s, fair porcelain skin, ash-blonde hair, "
    "clear pale-blue eyes, effortless Nordic elegance",
    "tall Korean woman, mid-20s, luminous fair skin, sleek long black hair, "
    "elegant cat-like eyes, sophisticated Seoul-chic beauty",
    "tall Japanese woman, mid-20s, porcelain-fair skin, silky black hair, "
    "delicate features, ethereal East-Asian beauty",
]

SURNAME_POOL = [
    "Larsen", "Bergström", "Nilsson", "Andersson", "Karlsson", "Johansson",
    "Svensson", "Lindgren", "Ahlberg", "Sorensen", "Dahl", "Ekstrom",
    "Holt", "Reyes", "Moreno", "Delgado", "Rossi", "Romano", "Conti",
    "Marchetti", "Fontaine", "Moreau", "Lefevre", "Bernard", "Petrov",
    "Ivanova", "Volkova", "Sokolova", "Kim", "Park", "Lee", "Choi",
    "Tanaka", "Sato", "Suzuki", "Watanabe",
]


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def build_prompt(who: str, shot: str, soft: bool = False) -> str:
    if shot == "torso":
        shot_text = _torso_shot_text(soft)
    elif shot == "back":
        shot_text = _back_shot_text(soft)
    else:
        shot_text = SHOTS[shot]
    return BASE.format(who=who, shot=shot_text)


def _status_of(exc: Exception):
    return getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )


def _call_images_generate(client, model: str, prompt: str):
    return client.images.generate(
        model=model, prompt=prompt, size="1024x1536", quality="medium"
    )


def _decode_image(result) -> bytes:
    return base64.b64decode(result.data[0].b64_json)


def generate_shot(client, who: str, shot: str, model: str) -> bytes:
    """Generate one PNG for `who`/`shot` and return its raw bytes.

    On a 400 (moderation reject) retries once with the softened prompt.
    On a 429 (rate limit) sleeps 20s and retries once with the same prompt.
    Any other error, or a second failure, propagates.
    """
    try:
        result = _call_images_generate(client, model, build_prompt(who, shot, soft=False))
    except Exception as e:
        status = _status_of(e)
        if status == 400:
            result = _call_images_generate(client, model, build_prompt(who, shot, soft=True))
        elif status == 429:
            _sleep(20)
            result = _call_images_generate(client, model, build_prompt(who, shot, soft=False))
        else:
            raise
    return _decode_image(result)


def _next_concept(cache: dict) -> str:
    idx = cache.get("_concept_idx", 0) % len(CONCEPTS)
    cache["_concept_idx"] = (idx + 1) % len(CONCEPTS)
    return CONCEPTS[idx]


def _new_model_name(existing: set) -> str:
    pool = [s for s in SURNAME_POOL if f"Claire {s}" not in existing]
    if not pool:
        pool = SURNAME_POOL
    return "Claire " + random.choice(pool)


class BrainClient:
    """Thin sync HTTP client for the casting API endpoints this worker uses."""

    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def get_state(self) -> dict:
        r = httpx.get(f"{self.url}/casting/state", timeout=30)
        r.raise_for_status()
        return r.json()

    def get_list(self) -> dict:
        r = httpx.get(f"{self.url}/casting/list", timeout=30)
        r.raise_for_status()
        return r.json()

    def upload(self, model: str, filename: str, data: bytes) -> None:
        r = httpx.post(
            f"{self.url}/casting/upload",
            headers={"X-Brain-Token": self.token},
            data={"model": model},
            files={"file": (filename, data, "image/png")},
            timeout=120,
        )
        r.raise_for_status()


def _generate_and_upload(brain_client, ai_client, image_model, name, who, shot):
    data = generate_shot(ai_client, who, shot, image_model)
    brain_client.upload(name, f"{shot}.png", data)
    _sleep(12)


def _generate_and_upload_glam(brain_client, name, who):
    data = generate_glam_shot(who)
    if data is None:
        return
    brain_client.upload(name, _glam_filename(name), data)
    _sleep(4)


def run_once(brain_client, ai_client, image_model: str, cache: dict) -> dict:
    """Run a single pipeline pass. Returns the (possibly updated) cache dict.

    `cache` maps model name -> concept description; a reserved "_concept_idx"
    key tracks rotation position and is never treated as a model name.
    """
    state = brain_client.get_state()
    if state.get("paused"):
        return cache

    listing = brain_client.get_list()
    active_models = listing.get("models", [])
    picked_models = listing.get("picked", [])
    all_names = {m["name"] for m in active_models} | {m["name"] for m in picked_models}

    # (a) fill missing shots for active (non-picked) models
    for m in active_models:
        name = m["name"]
        have = {Path(f).stem for f in m["files"]}
        missing = [s for s in SHOT_ORDER if s not in have]
        if not missing:
            continue
        who = cache.get(name)
        if not who:
            continue  # no cached description for this model; can't regenerate it
        for shot in missing:
            _generate_and_upload(brain_client, ai_client, image_model, name, who, shot)

    # (b) top up the round if we're under target
    target = state.get("target", 10)
    if len(active_models) < target:
        name = _new_model_name(all_names)
        who = _next_concept(cache)
        cache[name] = who
        for shot in SHOT_ORDER:
            _generate_and_upload(brain_client, ai_client, image_model, name, who, shot)
        _generate_and_upload_glam(brain_client, name, who)

    # (c) ensure every other active cached-description model has a glam shot
    for m in active_models:
        name = m["name"]
        who = cache.get(name)
        if not who:
            continue
        if _has_glam(name, m["files"]):
            continue
        _generate_and_upload_glam(brain_client, name, who)

    return cache


def _load_cache() -> dict:
    return json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}


def _save_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), "utf-8")


def make_ai_client():
    from openai import OpenAI

    return OpenAI()


def loop(brain_client, ai_client, image_model: str, interval: int, once: bool) -> None:
    cache = _load_cache()
    while True:
        try:
            cache = run_once(brain_client, ai_client, image_model, cache)
            _save_cache(cache)
        except Exception as e:
            print(f"casting worker error: {e}", file=sys.stderr)
        if once:
            return
        _sleep(interval)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    a = argparse.ArgumentParser(prog="brain-casting-worker")
    a.add_argument("--url", required=True)
    a.add_argument("--token", required=True)
    a.add_argument("--interval", type=int, default=60)
    a.add_argument("--once", action="store_true")
    ns = a.parse_args()

    brain_client = BrainClient(ns.url, ns.token)
    ai_client = make_ai_client()
    image_model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
    loop(brain_client, ai_client, image_model, ns.interval, ns.once)


if __name__ == "__main__":
    main()
