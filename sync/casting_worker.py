"""Local worker that keeps the casting pool topped up with new candidates.

Contract (v2):

* The pool is exactly `target` (default 10) ACTIVE — i.e. not yet picked —
  models. When the server already has that many, the worker does nothing.
  When it has fewer, the worker creates models ONE AT A TIME until the pool is
  full again (repeating inside the same run).
* The worker never deletes anything. It only adds.
* A model is three shots of the SAME woman, held together by a reference
  chain: shot 1 (`face`) is generated from the concept text with OpenAI
  `images.generate`; shots 2 and 3 (`torso`, `back`) are both *edits of the
  face image*. One of them (chosen at random) is edited by OpenAI, the other
  by xAI's Grok image-edit endpoint — so every model gets one "glam register"
  frame. Without XAI_API_KEY both edits go to OpenAI.
* Every PNG is uploaded to the server (POST /casting/upload) immediately after
  it is generated, as `<Model_With_Underscores>_<shot>.png`.
* `--silhouette-ref PATH` (default `~/Desktop/2ndBRAIN/Clair/refs/
  BACK_SILHOUETTE_REF_Petrova.png`) is an optional back-view pose/silhouette
  reference. When the file exists it rides along on every "back" edit shot
  only (face/torso untouched): OpenAI gets it as a second reference image
  with a prefix explaining which image is which, Grok gets the same
  description folded into the prompt as words (its edit endpoint takes one
  image). Missing file -> behaves exactly as before.

State that the server cannot hold (which concept text a model was born from,
and which names have already been burned) lives in ~/.brain-casting.json:

    {"models": {"Claire Kim": {"concept": "...", "region": "korean"}},
     "used_names": ["Claire Kim"], "concept_idx": 3}
"""
import argparse
import base64
import io
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx

HISTORY = Path.home() / ".brain-casting.json"
# Every generated face is kept here so a later run can finish a model whose
# torso/back never made it up (the reference chain needs the original face).
FACE_DIR = Path.home() / ".brain-casting"
# Optional back-view silhouette reference (pose/body-shape only, not a face).
# When present it rides along on every "back" edit shot; when missing the
# worker behaves exactly as before.
DEFAULT_SILHOUETTE_REF = (
    Path.home() / "Desktop" / "2ndBRAIN" / "Clair" / "refs" / "BACK_SILHOUETTE_REF_Petrova.png"
)

TARGET_DEFAULT = 10
SHOT_ORDER = ("face", "torso", "back")
EDIT_SHOTS = ("torso", "back")

# --- prompt scaffolding ----------------------------------------------------

BASE = (
    "Photorealistic professional model photography, Vogue editorial level. "
    "Subject: {who}, 173cm, slender long legs, softly curved feminine figure, "
    "graceful glamorous silhouette. {shot} Fully clothed, tasteful."
)

# Softened variant used for the single moderation retry: the figure phrase is
# dropped entirely.
BASE_SOFT = (
    "Photorealistic professional model photography, Vogue editorial level. "
    "Subject: {who}, 173cm. {shot} Fully clothed, tasteful."
)

REFERENCE_PREFIX = (
    "Same woman as the reference image — identical face, hair, skin and body. "
)

# Back-view silhouette reference: description shared verbatim between the
# OpenAI two-image prefix and the Grok in-words sentence.
SILHOUETTE_DESC = (
    "the body silhouette and pose style to reproduce (figure-hugging gown, "
    "pronounced feminine hip curve, elegant back-arch, glancing over the "
    "shoulder)"
)

SILHOUETTE_PREFIX = (
    "First reference image = the woman (keep her face, hair, skin identical). "
    f"Second reference image = {SILHOUETTE_DESC}. "
)

SILHOUETTE_GROK_SENTENCE = f"Reproduce {SILHOUETTE_DESC}."

FACE_SHOT = (
    "Extreme close-up beauty portrait, face filling the frame, flawless "
    "natural skin texture, soft studio light, direct eye contact, gentle "
    "confident expression."
)

# Outfits are re-rolled for every shot so consecutive models don't all wear
# the same look. No school uniforms and no lingerie in any list.
OUTFITS_TORSO = [
    "an elegant black satin evening dress",
    "a fitted mini cocktail dress",
    "a crop top with a high-waisted mini skirt",
    "a silk camisole with tailored shorts",
    "a bodycon club dress",
    "an off-shoulder summer top",
    "a halter neck cocktail dress",
    "a tailored blazer worn over a silk top",
    "a knitted crop top with wide linen trousers",
    "a slip dress with a delicate gold chain",
]

OUTFITS_BACK = [
    "a figure-hugging satin evening gown",
    "a backless mini dress",
    "a crop top and denim shorts",
    "an open-back club dress",
    "a halter summer dress",
    "a long silk gown with a low open back",
    "a fitted knit dress with a keyhole back",
    "a wrap mini dress and strappy heels",
]

SCENES = [
    "luxury interior",
    "neon-lit club",
    "rooftop at night",
    "sunny summer street",
    "studio backdrop",
]

# Plain wording used by the moderation retry.
SOFT_OUTFIT_TORSO = "an elegant evening dress"
SOFT_OUTFIT_BACK = "an elegant evening gown"
SOFT_REGISTER = "an elegant evening gown"

# --- Grok "glam register" shot ---------------------------------------------

XAI_EDIT_URL = "https://api.x.ai/v1/images/edits"
XAI_IMAGE_MODEL = "grok-imagine-image"

# At least 8 distinct poses, all readable from the front or from behind.
POSES = [
    "mid-stride in a confident walk",
    "seated elegantly on a lounge chair",
    "leaning against a railing, gazing into the distance",
    "hair caught dramatically by the wind",
    "caught mid-turn, glancing over her shoulder",
    "arms raised in a graceful stretch overhead",
    "stepping down a grand staircase",
    "standing tall with one hand resting on her hip",
    "reclining gracefully on a sun lounger",
    "twirling so the fabric flares around her",
]

# One notch more glamorous than the OpenAI shots, but never beyond this set.
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

# --- casting concepts -------------------------------------------------------
# Fixed rotation; no ethnic groups beyond these. `weight` makes a concept come
# round more often. Every entry carries the surname region to draw from.
CONCEPTS = [
    {
        "region": "anglo",
        "weight": 2,
        "who": (
            "tall American woman, mid-20s, sun-kissed fair skin, golden blonde "
            "hair, bright blue eyes, athletic all-American beauty-queen elegance"
        ),
    },
    {
        "region": "anglo",
        "weight": 2,
        "who": (
            "tall American woman, mid-20s, warm fair skin, glossy chestnut-brown "
            "hair, soft brown eyes, polished girl-next-door glamour"
        ),
    },
    {
        "region": "spanish",
        "weight": 1,
        "who": (
            "tall Spanish woman, mid-20s, sun-warmed olive skin, dark wavy hair, "
            "deep brown eyes, fiery flamenco-elegant beauty"
        ),
    },
    {
        "region": "spanish",
        "weight": 1,
        "who": (
            "tall Argentinian woman, mid-20s, fair olive skin, chestnut hair, "
            "striking hazel eyes, sculpted Latin American runway-model beauty"
        ),
    },
    {
        "region": "russian",
        "weight": 1,
        "who": (
            "tall Russian woman, mid-20s, pale porcelain skin, platinum-blonde "
            "hair, ice-blue eyes, poised ice-queen elegance"
        ),
    },
    {
        "region": "french",
        "weight": 1,
        "who": (
            "tall French woman, mid-20s, fair skin, sleek dark bob, refined "
            "cheekbones, understated Parisian elegance"
        ),
    },
    {
        "region": "italian",
        "weight": 1,
        "who": (
            "tall Italian woman, mid-20s, sun-kissed olive skin, glossy "
            "dark-brown hair, warm brown eyes, sculptural Mediterranean elegance"
        ),
    },
    {
        "region": "scandinavian",
        "weight": 1,
        "who": (
            "tall Scandinavian woman, mid-20s, fair porcelain skin, ash-blonde "
            "hair, clear pale-blue eyes, effortless Nordic elegance"
        ),
    },
    {
        "region": "slavic",
        "weight": 1,
        "who": (
            "tall Czech woman, mid-20s, fair skin, light-brown hair, striking "
            "green eyes, high-fashion Prague runway elegance"
        ),
    },
    {
        "region": "slavic",
        "weight": 1,
        "who": (
            "tall Polish woman, mid-20s, fair skin, honey-blonde hair, clear "
            "grey-blue eyes, refined Central European editorial beauty"
        ),
    },
    {
        "region": "korean",
        "weight": 2,
        "who": (
            "tall Korean woman, mid-20s, actress-level beauty, luminous flawless "
            "skin, elegant double-lidded almond eyes, refined small V-line face, "
            "glossy long black hair, sophisticated Seoul-chic elegance"
        ),
    },
    {
        "region": "japanese",
        "weight": 2,
        "who": (
            "tall Japanese woman, mid-20s, Tokyo model-level beauty, porcelain "
            "flawless skin, large expressive double-lidded eyes, delicate refined "
            "features, silky long black hair, elegant Ginza-chic sophistication"
        ),
    },
]


def _build_rotation() -> list:
    """Weighted rotation: heavier concepts reappear in later passes."""
    order = []
    for pass_no in range(max(c["weight"] for c in CONCEPTS)):
        for idx, concept in enumerate(CONCEPTS):
            if concept["weight"] > pass_no:
                order.append(idx)
    return order


ROTATION = _build_rotation()

# --- surname pool (>= 300 unique, grouped by region) ------------------------

SURNAMES = {
    "anglo": [
        "Anderson", "Bailey", "Barnes", "Bennett", "Brooks", "Carter",
        "Chandler", "Coleman", "Collins", "Cooper", "Davis", "Dawson",
        "Ellis", "Foster", "Gibson", "Grant", "Harper", "Hayes", "Hudson",
        "Hunter", "Jenkins", "Kendall", "Lawson", "Mercer", "Mitchell",
        "Morgan", "Parker", "Preston", "Quinn", "Reeves", "Sawyer",
        "Sinclair", "Sullivan", "Turner", "Walker", "Whitaker",
    ],
    "spanish": [
        "Aguilar", "Alvarez", "Blanco", "Cabrera", "Campos", "Castillo",
        "Delgado", "Dominguez", "Escobar", "Espinosa", "Fernandez",
        "Gallardo", "Garrido", "Gimenez", "Guerrero", "Herrera", "Ibarra",
        "Jimenez", "Lozano", "Marquez", "Medina", "Mendoza", "Montoya",
        "Morales", "Moreno", "Navarro", "Ortega", "Pacheco", "Peralta",
        "Quintana", "Reyes", "Rivas", "Salazar", "Serrano", "Valdez", "Vega",
    ],
    "russian": [
        "Andreeva", "Belova", "Bogdanova", "Dmitrieva", "Egorova", "Fedorova",
        "Gordeeva", "Ivanova", "Kalinina", "Karpova", "Kazakova", "Kirillova",
        "Kovaleva", "Kuznetsova", "Lebedeva", "Makarova", "Medvedeva",
        "Melnikova", "Mikhailova", "Morozova", "Nikolaeva", "Novikova",
        "Orlova", "Pavlova", "Petrova", "Popova", "Romanova", "Sergeeva",
        "Smirnova", "Sokolova", "Stepanova", "Tarasova", "Volkova", "Zaitseva",
    ],
    "french": [
        "Allard", "Aubert", "Barbier", "Beaumont", "Bernard", "Blanchard",
        "Bonnet", "Boucher", "Chevalier", "Clement", "Colbert", "Dubois",
        "Duval", "Fabre", "Fontaine", "Gaillard", "Garnier", "Girard",
        "Granger", "Lacroix", "Lambert", "Laurent", "Lefevre", "Leroy",
        "Marchand", "Mercier", "Moreau", "Noel", "Perrin", "Renard",
        "Rousseau", "Thibault", "Vidal", "Voisin",
    ],
    "italian": [
        "Amato", "Barbieri", "Bellini", "Bianchi", "Bruno", "Caruso",
        "Colombo", "Conti", "Costa", "Esposito", "Ferrari", "Ferraro",
        "Fiore", "Fontana", "Gallo", "Gatti", "Giordano", "Greco",
        "Lombardi", "Mancini", "Marchetti", "Marino", "Martini", "Messina",
        "Moretti", "Neri", "Orlando", "Pagano", "Pellegrini", "Ricci",
        "Rizzo", "Romano", "Rossi", "Russo", "Serra", "Vitale",
    ],
    "scandinavian": [
        "Ahlberg", "Andersson", "Aune", "Berg", "Bergman", "Bergstrom",
        "Bjork", "Dahl", "Eklund", "Ekstrom", "Engstrom", "Falk",
        "Fredriksson", "Gustafsson", "Hagen", "Hansen", "Haugen", "Hedlund",
        "Holm", "Jensen", "Johansson", "Karlsson", "Larsen", "Lindberg",
        "Lindgren", "Lund", "Moller", "Nilsson", "Nordstrom", "Olsen",
        "Sandberg", "Sorensen", "Strand", "Sundberg", "Svensson", "Wallin",
    ],
    "slavic": [
        "Adamczyk", "Baran", "Cerny", "Dudek", "Dvorak", "Fiala", "Gorski",
        "Havel", "Horak", "Jankowski", "Jelinek", "Kaminski", "Kovar",
        "Kowalski", "Kral", "Kucera", "Lewandowski", "Majewski", "Marek",
        "Masek", "Nemec", "Novak", "Novotny", "Nowak", "Pawlak", "Pokorny",
        "Prochazka", "Ruzicka", "Sedlak", "Sikora", "Simek", "Sokolowski",
        "Svoboda", "Urban", "Vesely", "Wojcik", "Zawadzki", "Zeman",
        "Zielinski",
    ],
    "korean": [
        "Ahn", "Bae", "Baek", "Chae", "Cho", "Choi", "Chun", "Ha", "Han",
        "Hong", "Hwang", "Jang", "Jeon", "Joo", "Jung", "Kang", "Kim", "Ko",
        "Koo", "Kwon", "Lee", "Lim", "Min", "Moon", "Nam", "Noh", "Oh",
        "Park", "Ryu", "Seo", "Shin", "Sohn", "Song", "Woo", "Yang", "Yeo",
        "Yoon", "Yu",
    ],
    "japanese": [
        "Abe", "Aoki", "Endo", "Fujita", "Fukuda", "Goto", "Hasegawa",
        "Hashimoto", "Hayashi", "Ikeda", "Inoue", "Ishii", "Ishikawa", "Ito",
        "Kato", "Kimura", "Kobayashi", "Kondo", "Matsumoto", "Mori",
        "Murakami", "Nakamura", "Nishimura", "Ogawa", "Okada", "Ota",
        "Sakamoto", "Saito", "Sasaki", "Sato", "Shimizu", "Suzuki",
        "Takahashi", "Tanaka", "Watanabe", "Yamada", "Yamaguchi",
        "Yamamoto", "Yamazaki", "Yoshida",
    ],
}

ALL_SURNAMES = [s for names in SURNAMES.values() for s in names]

# --- small helpers ----------------------------------------------------------

RETRY_BACKOFF = (2, 5, 10)


class SkipLoop(Exception):
    """The server is unreachable; give up on this loop iteration."""


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _status_of(exc: Exception):
    return getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )


def _is_transient(exc: Exception) -> bool:
    status = _status_of(exc)
    if status is not None:
        try:
            return 500 <= int(status) < 600
        except (TypeError, ValueError):
            return False
    return isinstance(exc, (httpx.RequestError, ConnectionError, TimeoutError, OSError))


def _server(fn, *args, **kwargs):
    """Call a server endpoint, retrying 3x on 5xx/connection errors.

    After the last retry raises SkipLoop so the caller can drop this round
    instead of crashing.
    """
    attempts = len(RETRY_BACKOFF) + 1
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if not _is_transient(e):
                raise
            if i == attempts - 1:
                raise SkipLoop(str(e) or type(e).__name__) from e
            _log(f"server error ({e}) — retry {i + 1}/{len(RETRY_BACKOFF)} in {RETRY_BACKOFF[i]}s")
            _sleep(RETRY_BACKOFF[i])


def _guarded(make_prompt, invoke):
    """Run `invoke(make_prompt(soft))`, handling moderation and rate limits.

    400 (moderation) -> one retry with the softened prompt.
    429 (rate limit) -> sleep 20s, one retry with a fresh hard prompt.
    """
    try:
        return invoke(make_prompt(False))
    except Exception as e:
        status = _status_of(e)
        if status == 400:
            _log("moderation reject — retrying once with softened prompt")
            return invoke(make_prompt(True))
        if status == 429:
            _log("rate limited — sleeping 20s then retrying once")
            _sleep(20)
            return invoke(make_prompt(False))
        raise


# --- prompt builders --------------------------------------------------------


def build_prompt(who: str, shot_text: str, soft: bool = False) -> str:
    return (BASE_SOFT if soft else BASE).format(who=who, shot=shot_text)


def build_face_prompt(who: str, soft: bool = False) -> str:
    return build_prompt(who, FACE_SHOT, soft)


def build_edit_prompt(who: str, shot_text: str, soft: bool = False) -> str:
    """Edit prompts always open with the identity-lock sentence."""
    return REFERENCE_PREFIX + build_prompt(who, shot_text, soft)


def torso_shot_text(rng, soft: bool = False) -> str:
    outfit = SOFT_OUTFIT_TORSO if soft else rng.choice(OUTFITS_TORSO)
    scene = rng.choice(SCENES)
    return (
        f"Waist-up editorial portrait facing the camera, wearing {outfit}, "
        "poised posture, warm cinematic light, direct gaze, soft smile, "
        f"{scene}."
    )


def back_shot_text(rng, soft: bool = False) -> str:
    outfit = SOFT_OUTFIT_BACK if soft else rng.choice(OUTFITS_BACK)
    scene = rng.choice(SCENES)
    return (
        f"Full-body photograph from behind, wearing {outfit}, she glances back "
        "over her shoulder at the camera with a subtle smile, cinematic rim "
        f"light, {scene}."
    )


def openai_shot_text(rng, shot: str, soft: bool = False) -> str:
    return torso_shot_text(rng, soft) if shot == "torso" else back_shot_text(rng, soft)


def grok_shot_text(rng, shot: str, soft: bool = False) -> str:
    """The glam register: one notch more glamorous, always safety-capped."""
    pose = rng.choice(POSES)
    register = SOFT_REGISTER if soft else rng.choice(GLAM_REGISTERS)
    view = (
        "Waist-up view facing the camera"
        if shot == "torso"
        else "Full-body view from behind, glancing back over her shoulder"
    )
    return f"{view}, {pose}, wearing {register}. {GLAM_SAFETY}"


# --- image generation -------------------------------------------------------


def _decode_image(result) -> bytes:
    return base64.b64decode(result.data[0].b64_json)


def _as_upload(image_bytes: bytes, name: str = "face.png"):
    buf = io.BytesIO(image_bytes)
    buf.name = name
    return buf


def generate_face(ai_client, image_model: str, who: str) -> bytes:
    """Shot 1: a fresh face from the concept text."""
    return _guarded(
        lambda soft: build_face_prompt(who, soft),
        lambda prompt: _decode_image(
            ai_client.images.generate(
                model=image_model, prompt=prompt, size="1024x1536", quality="medium"
            )
        ),
    )


def edit_with_openai(ai_client, image_model: str, face: bytes, who: str, shot: str, rng,
                     silhouette: bytes = None) -> bytes:
    """Shots 2/3 via OpenAI, using the face image as the reference.

    Back shots additionally take the back-silhouette reference (when
    configured) as a second reference image, with a prefix explaining which
    image is which. Torso/face are unaffected even when a silhouette ref is
    configured.
    """
    use_silhouette = shot == "back" and silhouette is not None

    def make_prompt(soft):
        prompt = build_edit_prompt(who, openai_shot_text(rng, shot, soft), soft)
        return SILHOUETTE_PREFIX + prompt if use_silhouette else prompt

    def invoke(prompt):
        image = (
            [_as_upload(face, "face.png"), _as_upload(silhouette, "silhouette.png")]
            if use_silhouette
            else _as_upload(face)
        )
        return _decode_image(
            ai_client.images.edit(
                model=image_model,
                image=image,
                prompt=prompt,
                size="1024x1536",
                quality="medium",
            )
        )

    return _guarded(make_prompt, invoke)


class GrokClient:
    """xAI image-edit client (image in, edited image out)."""

    def __init__(self, api_key: str, poster=None):
        self.api_key = api_key
        self._post = poster or httpx.post

    def edit(self, image: bytes, prompt: str) -> bytes:
        b64 = base64.b64encode(image).decode()
        r = self._post(
            XAI_EDIT_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": XAI_IMAGE_MODEL,
                "image": {"url": f"data:image/png;base64,{b64}"},
                "prompt": prompt,
                "response_format": "b64_json",
            },
            timeout=180,
        )
        r.raise_for_status()
        return base64.b64decode(r.json()["data"][0]["b64_json"])


def make_grok_client(poster=None):
    """None when XAI_API_KEY isn't set — the caller then uses OpenAI twice."""
    key = os.environ.get("XAI_API_KEY")
    return GrokClient(key, poster) if key else None


def edit_with_grok(grok, face: bytes, who: str, shot: str, rng, silhouette: bytes = None) -> bytes:
    """Grok only ever sees the face image; the silhouette (when configured)
    is folded into the back-shot prompt as words instead of a second image,
    since the xAI edit endpoint takes a single image."""
    use_silhouette = shot == "back" and silhouette is not None

    def make_prompt(soft):
        prompt = build_edit_prompt(who, grok_shot_text(rng, shot, soft), soft)
        return f"{prompt} {SILHOUETTE_GROK_SENTENCE}" if use_silhouette else prompt

    return _guarded(make_prompt, lambda prompt: grok.edit(face, prompt))


# --- history ----------------------------------------------------------------


def _empty_history() -> dict:
    return {"models": {}, "used_names": [], "concept_idx": 0}


def _normalize_history(data) -> dict:
    """Accept the v1 flat cache ({name: who, _concept_idx: n}) too."""
    history = _empty_history()
    if not isinstance(data, dict):
        return history
    if "models" in data or "used_names" in data:
        history["models"] = dict(data.get("models") or {})
        history["used_names"] = list(data.get("used_names") or [])
        history["concept_idx"] = int(data.get("concept_idx") or 0)
    else:
        for name, who in data.items():
            if name.startswith("_") or not isinstance(who, str):
                continue
            history["models"][name] = {"concept": who, "region": None}
        history["concept_idx"] = int(data.get("_concept_idx") or 0)
    for name in history["models"]:
        if name not in history["used_names"]:
            history["used_names"].append(name)
    return history


def load_history() -> dict:
    if not HISTORY.exists():
        return _empty_history()
    try:
        return _normalize_history(json.loads(HISTORY.read_text("utf-8")))
    except (json.JSONDecodeError, OSError):
        return _empty_history()


def save_history(history: dict) -> None:
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1), "utf-8")


def next_concept(history: dict) -> dict:
    idx = int(history.get("concept_idx", 0)) % len(ROTATION)
    history["concept_idx"] = (idx + 1) % len(ROTATION)
    return CONCEPTS[ROTATION[idx]]


def new_model_name(region: str, taken, rng) -> str:
    """"Claire <surname>", surname drawn from the concept's own region."""
    pool = [s for s in SURNAMES.get(region, []) if f"Claire {s}" not in taken]
    if not pool:  # region exhausted — fall back to the whole pool
        pool = [s for s in ALL_SURNAMES if f"Claire {s}" not in taken]
    if not pool:
        raise RuntimeError("surname pool exhausted")
    return "Claire " + rng.choice(pool)


# --- server client ----------------------------------------------------------


class BrainClient:
    """Thin sync HTTP client for the casting endpoints this worker uses."""

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


def shot_filename(name: str, shot: str) -> str:
    return f"{name.replace(' ', '_')}_{shot}.png"


def face_path(name: str) -> Path:
    return FACE_DIR / shot_filename(name, "face")


def save_face(name: str, data: bytes) -> None:
    FACE_DIR.mkdir(parents=True, exist_ok=True)
    face_path(name).write_bytes(data)


def load_face(name: str):
    p = face_path(name)
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def load_silhouette_ref(path) -> bytes:
    """Read the back-view silhouette reference PNG.

    Returns None (and the worker behaves exactly as before) when the file is
    missing or unreadable.
    """
    p = Path(path)
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def has_shot(files, shot: str) -> bool:
    """Tolerates both `<Model>_torso.png` and the older bare `torso.png`."""
    for f in files or []:
        stem = Path(f).stem.lower()
        if stem == shot or stem.endswith(f"_{shot}"):
            return True
    return False


# --- the pipeline -----------------------------------------------------------


def generate_edit_shots(brain_client, ai_client, image_model, name, who, face, rng,
                        grok=None, shots=EDIT_SHOTS, silhouette=None):
    """Edit `face` into the requested shots and upload each one.

    The Grok/OpenAI split is always drawn over both edit shots, so a backfill
    of a single missing shot follows exactly the same random rule as a fresh
    model. `silhouette` (back-view reference bytes, or None) is only ever
    used on the "back" shot, regardless of which provider handles it.
    """
    grok_shot = rng.choice(EDIT_SHOTS) if grok is not None else None
    for shot in shots:
        if shot == grok_shot:
            data = edit_with_grok(grok, face, who, shot, rng, silhouette)
            _server(brain_client.upload, name, shot_filename(name, shot), data)
            _log(f"{name}: {shot} uploaded (grok edit)")
            _sleep(4)
        else:
            data = edit_with_openai(ai_client, image_model, face, who, shot, rng, silhouette)
            _server(brain_client.upload, name, shot_filename(name, shot), data)
            _log(f"{name}: {shot} uploaded (openai edit)")
            _sleep(12)


def create_model(brain_client, ai_client, image_model, name, who, rng, grok=None, silhouette=None):
    """Generate + upload the three shots of one model, face first."""
    face = generate_face(ai_client, image_model, who)
    save_face(name, face)
    _server(brain_client.upload, name, shot_filename(name, "face"), face)
    _log(f"{name}: face uploaded")
    _sleep(12)
    generate_edit_shots(brain_client, ai_client, image_model, name, who, face, rng, grok,
                        silhouette=silhouette)


def backfill_missing_shots(brain_client, ai_client, image_model, models, history,
                           rng=random, grok=None, silhouette=None) -> int:
    """Finish half-built models so they don't waste a slot in the pool.

    Only models we created ourselves (present in the local history) and whose
    face PNG is still cached locally can be finished — the reference chain
    needs those exact face bytes. Anything else is left untouched; the worker
    never deletes.
    """
    filled = 0
    for m in models:
        name = m.get("name")
        entry = history["models"].get(name)
        if not entry:
            continue
        missing = [s for s in EDIT_SHOTS if not has_shot(m.get("files"), s)]
        if not missing:
            continue
        face = load_face(name)
        if face is None:
            _log(f"{name}: missing {', '.join(missing)} but no local face — skipping")
            continue
        _log(f"{name}: backfilling {', '.join(missing)}")
        generate_edit_shots(brain_client, ai_client, image_model, name, entry["concept"],
                            face, rng, grok, shots=missing, silhouette=silhouette)
        filled += 1
    return filled


def run_once(brain_client, ai_client, image_model: str, history: dict, rng=random, grok=None,
            silhouette=None) -> dict:
    """One pass: top the ACTIVE pool back up to `target`, one model at a time."""
    state = _server(brain_client.get_state)
    if state.get("paused"):
        _log("generation paused — nothing to do")
        return history

    try:
        target = int(state.get("target") or TARGET_DEFAULT)
    except (TypeError, ValueError):
        target = TARGET_DEFAULT

    listing = _server(brain_client.get_list)
    active = listing.get("models") or []
    picked = listing.get("picked") or []
    taken = {m["name"] for m in active} | {m["name"] for m in picked} | set(history["used_names"])

    backfill_missing_shots(brain_client, ai_client, image_model, active, history, rng, grok,
                           silhouette)

    count = len(active)
    if count >= target:
        _log(f"pool full ({count}/{target}) — nothing to do")
        return history

    while count < target:
        concept = next_concept(history)
        name = new_model_name(concept["region"], taken, rng)
        # Burn the name before generating: a crash mid-model must not hand the
        # same name to the next run.
        history["models"][name] = {"concept": concept["who"], "region": concept["region"]}
        history["used_names"].append(name)
        taken.add(name)
        save_history(history)
        _log(f"creating {name} ({concept['region']}) — pool {count + 1}/{target}")
        create_model(brain_client, ai_client, image_model, name, concept["who"], rng, grok,
                     silhouette)
        count += 1

    return history


def make_ai_client():
    from openai import OpenAI

    return OpenAI()


def loop(brain_client, ai_client, image_model: str, interval: int, once: bool,
         rng=random, grok=None, silhouette=None) -> None:
    history = load_history()
    while True:
        try:
            history = run_once(brain_client, ai_client, image_model, history, rng, grok,
                               silhouette)
            save_history(history)
        except SkipLoop as e:
            _log(f"server unavailable ({e}) — skipping this round")
        except Exception as e:  # never crash the worker
            _log(f"error: {e}")
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
    a.add_argument("--interval", type=int, default=90)
    a.add_argument("--once", action="store_true")
    a.add_argument("--silhouette-ref", default=str(DEFAULT_SILHOUETTE_REF))
    ns = a.parse_args()

    brain_client = BrainClient(ns.url, ns.token)
    ai_client = make_ai_client()
    grok = make_grok_client()
    image_model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
    silhouette = load_silhouette_ref(ns.silhouette_ref)
    _log(f"casting worker up — {ns.url} (grok: {'on' if grok else 'off'}, "
        f"silhouette ref: {'on' if silhouette else 'off'})")
    loop(brain_client, ai_client, image_model, ns.interval, ns.once, random, grok, silhouette)


if __name__ == "__main__":
    main()
