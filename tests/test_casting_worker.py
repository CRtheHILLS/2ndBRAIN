import base64
import json
import sys
from types import SimpleNamespace

import pytest
from sync import casting_worker as cw


# --- fakes ------------------------------------------------------------------


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class FakeBrainClient:
    def __init__(self, state=None, listing=None):
        self._state = state or {"paused": False, "picked": [], "target": 1}
        self._listing = listing or {"models": [], "picked": []}
        self.uploads = []
        self.state_error = None
        self.state_calls = 0

    def get_state(self):
        self.state_calls += 1
        if self.state_error is not None:
            raise self.state_error
        return self._state

    def get_list(self):
        return self._listing

    def upload(self, model, filename, data):
        self.uploads.append((model, filename, data))

    def delete(self, *a, **kw):  # the worker must never call this
        raise AssertionError("the worker deleted something")


def _payload(data: bytes):
    return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(data).decode())])


class FakeImages:
    FACE = b"face-bytes"
    EDIT = b"openai-edit-bytes"

    def __init__(self):
        self.generate_calls = []
        self.edit_calls = []
        self.fail_next = None

    def _maybe_fail(self):
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc

    def generate(self, model, prompt, size, quality):
        self.generate_calls.append(
            {"model": model, "prompt": prompt, "size": size, "quality": quality}
        )
        self._maybe_fail()
        return _payload(self.FACE)

    def edit(self, model, image, prompt, size, quality):
        self.edit_calls.append(
            {
                "model": model,
                "prompt": prompt,
                "image": image.read(),
                "name": getattr(image, "name", None),
                "size": size,
                "quality": quality,
            }
        )
        self._maybe_fail()
        return _payload(self.EDIT)


class FakeAI:
    def __init__(self):
        self.images = FakeImages()


class Rng:
    """Deterministic stand-in for `random`: always the same slot of a pool."""

    def __init__(self, pick=0):
        self.pick = pick

    def choice(self, pool):
        pool = list(pool)
        return pool[self.pick]


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise StatusError(self.status_code)

    def json(self):
        return self._payload


GROK_BYTES = b"grok-edit-bytes"


def fake_poster(calls, status=200):
    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if status >= 400:
            return FakeResponse({}, status)
        return FakeResponse({"data": [{"b64_json": base64.b64encode(GROK_BYTES).decode()}]})

    return post


def make_grok(calls, status=200):
    return cw.GrokClient("xai-test-key", fake_poster(calls, status))


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def slept(monkeypatch):
    recorded = []
    monkeypatch.setattr(cw, "_sleep", lambda s: recorded.append(s))
    return recorded


@pytest.fixture(autouse=True)
def history_file(tmp_path, monkeypatch):
    p = tmp_path / "brain-casting.json"
    monkeypatch.setattr(cw, "HISTORY", p)
    return p


@pytest.fixture(autouse=True)
def face_dir(tmp_path, monkeypatch):
    d = tmp_path / "faces"
    monkeypatch.setattr(cw, "FACE_DIR", d)
    return d


@pytest.fixture(autouse=True)
def _no_xai_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)


def fresh_history():
    return cw._empty_history()


# --- 1. pool size -----------------------------------------------------------


def _model(name, files=("f.png",)):
    return {"name": name, "files": list(files)}


def test_run_once_does_nothing_when_pool_is_full():
    listing = {"models": [_model(f"Claire M{i}") for i in range(10)], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 10}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    assert client.uploads == []
    assert ai.images.generate_calls == [] and ai.images.edit_calls == []


def test_run_once_creates_exactly_one_model_when_one_short():
    listing = {"models": [_model("Claire A"), _model("Claire B")], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 3}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    names = {n for (n, _, _) in client.uploads}
    assert len(names) == 1
    assert len(client.uploads) == 3


def test_run_once_repeats_within_one_run_until_target():
    client = FakeBrainClient({"paused": False, "picked": [], "target": 3},
                             {"models": [], "picked": []})
    ai = FakeAI()
    history = fresh_history()
    cw.run_once(client, ai, "gpt-image-2", history, Rng())
    names = {n for (n, _, _) in client.uploads}
    assert len(names) == 3
    assert len(client.uploads) == 9
    assert len(history["models"]) == 3


def test_run_once_skips_when_paused():
    client = FakeBrainClient({"paused": True, "picked": [], "target": 10},
                             {"models": [], "picked": []})
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    assert client.uploads == []
    assert ai.images.generate_calls == []


def test_picked_models_do_not_count_towards_the_pool():
    listing = {"models": [], "picked": [_model("Claire Kim")]}
    client = FakeBrainClient({"paused": False, "picked": ["Claire Kim"], "target": 1}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    names = {n for (n, _, _) in client.uploads}
    assert len(names) == 1 and "Claire Kim" not in names


def test_worker_never_deletes():
    client = FakeBrainClient({"paused": False, "picked": [], "target": 2},
                             {"models": [], "picked": []})
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())  # FakeBrainClient.delete raises
    assert len(client.uploads) == 6


# --- 2. reference chain -----------------------------------------------------


def _run_one(rng=None, grok=None, ai=None, client=None):
    client = client or FakeBrainClient({"paused": False, "picked": [], "target": 1},
                                       {"models": [], "picked": []})
    ai = ai or FakeAI()
    history = fresh_history()
    cw.run_once(client, ai, "gpt-image-2", history, rng or Rng(), grok)
    return client, ai, history


def test_face_is_generated_from_the_concept_text():
    client, ai, history = _run_one()
    assert len(ai.images.generate_calls) == 1
    call = ai.images.generate_calls[0]
    assert call["size"] == "1024x1536" and call["quality"] == "medium"
    who = list(history["models"].values())[0]["concept"]
    assert who in call["prompt"]
    assert cw.FACE_SHOT in call["prompt"]
    # the face is uploaded first, before any edit
    assert client.uploads[0][1].endswith("_face.png")


def test_both_edits_use_the_face_image_as_reference():
    calls = []
    client, ai, _ = _run_one(grok=make_grok(calls))
    assert len(ai.images.edit_calls) == 1
    assert ai.images.edit_calls[0]["image"] == FakeImages.FACE
    assert len(calls) == 1
    data_url = calls[0]["json"]["image"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == FakeImages.FACE


def test_openai_edit_reference_is_a_named_png_file():
    _, ai, _ = _run_one()
    assert all(c["name"] == "face.png" for c in ai.images.edit_calls)
    assert all(c["size"] == "1024x1536" and c["quality"] == "medium" for c in ai.images.edit_calls)


def test_grok_takes_torso_and_openai_takes_back_when_rng_picks_first():
    calls = []
    client, ai, _ = _run_one(rng=Rng(0), grok=make_grok(calls))
    by_file = {f: d for (_, f, d) in client.uploads}
    torso = [f for f in by_file if f.endswith("_torso.png")][0]
    back = [f for f in by_file if f.endswith("_back.png")][0]
    assert by_file[torso] == GROK_BYTES
    assert by_file[back] == FakeImages.EDIT


def test_grok_takes_back_and_openai_takes_torso_when_rng_picks_last():
    calls = []
    client, ai, _ = _run_one(rng=Rng(-1), grok=make_grok(calls))
    by_file = {f: d for (_, f, d) in client.uploads}
    torso = [f for f in by_file if f.endswith("_torso.png")][0]
    back = [f for f in by_file if f.endswith("_back.png")][0]
    assert by_file[back] == GROK_BYTES
    assert by_file[torso] == FakeImages.EDIT


def test_without_grok_both_edits_go_to_openai():
    calls = []
    client, ai, _ = _run_one(grok=None)
    assert len(ai.images.edit_calls) == 2
    assert calls == []
    assert all(d in (FakeImages.FACE, FakeImages.EDIT) for (_, _, d) in client.uploads)


def test_make_grok_client_is_none_without_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert cw.make_grok_client() is None


def test_make_grok_client_uses_env_key(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-abc")
    grok = cw.make_grok_client(poster=lambda *a, **k: None)
    assert isinstance(grok, cw.GrokClient) and grok.api_key == "xai-abc"


def test_every_edit_prompt_starts_with_the_reference_sentence():
    calls = []
    client, ai, _ = _run_one(grok=make_grok(calls))
    assert ai.images.edit_calls[0]["prompt"].startswith(cw.REFERENCE_PREFIX)
    assert calls[0]["json"]["prompt"].startswith(cw.REFERENCE_PREFIX)


def test_uploaded_filenames_are_underscored_model_plus_shot():
    client, _, history = _run_one()
    name = list(history["models"])[0]
    stem = name.replace(" ", "_")
    files = sorted(f for (_, f, _) in client.uploads)
    assert files == [f"{stem}_back.png", f"{stem}_face.png", f"{stem}_torso.png"]
    assert all(m == name for (m, _, _) in client.uploads)


def test_grok_edit_payload_shape():
    calls = []
    grok = make_grok(calls)
    out = grok.edit(b"ref", "a prompt")
    assert out == GROK_BYTES
    call = calls[0]
    assert call["url"] == "https://api.x.ai/v1/images/edits"
    assert call["headers"]["Authorization"] == "Bearer xai-test-key"
    body = call["json"]
    assert body["model"] == "grok-imagine-image"
    assert body["response_format"] == "b64_json"
    assert body["image"] == {"url": "data:image/png;base64," + base64.b64encode(b"ref").decode()}
    assert body["prompt"] == "a prompt"


def test_sleeps_twelve_after_openai_and_four_after_grok(slept):
    calls = []
    _run_one(grok=make_grok(calls))
    assert slept.count(12) == 2  # face generate + one openai edit
    assert slept.count(4) == 1


# --- 3. prompts -------------------------------------------------------------


def test_face_prompt_matches_spec():
    assert cw.build_face_prompt("a test woman") == (
        "Photorealistic professional model photography, Vogue editorial level. "
        "Subject: a test woman, 173cm, slender long legs, softly curved feminine "
        "figure, graceful glamorous silhouette. "
        "Extreme close-up beauty portrait, face filling the frame, flawless "
        "natural skin texture, soft studio light, direct eye contact, gentle "
        "confident expression. Fully clothed, tasteful."
    )


def test_soft_prompt_drops_the_figure_phrase():
    soft = cw.build_prompt("a test woman", "Some shot.", soft=True)
    assert "softly curved feminine figure" not in soft
    assert "graceful glamorous silhouette" not in soft
    assert "173cm" in soft


def test_openai_shot_texts_use_an_outfit_and_a_scene():
    rng = Rng()
    torso = cw.openai_shot_text(rng, "torso")
    back = cw.openai_shot_text(rng, "back")
    assert any(o in torso for o in cw.OUTFITS_TORSO)
    assert any(o in back for o in cw.OUTFITS_BACK)
    assert any(s in torso for s in cw.SCENES) and any(s in back for s in cw.SCENES)
    assert "facing the camera" in torso and "from behind" in back


def test_openai_soft_shot_texts_use_plain_outfit_wording():
    rng = Rng()
    torso = cw.openai_shot_text(rng, "torso", soft=True)
    back = cw.openai_shot_text(rng, "back", soft=True)
    assert cw.SOFT_OUTFIT_TORSO in torso and cw.SOFT_OUTFIT_BACK in back


def test_grok_shot_text_is_a_glam_register_ending_with_the_safety_line():
    rng = Rng()
    text = cw.grok_shot_text(rng, "torso")
    assert cw.POSES[0] in text
    assert cw.GLAM_REGISTERS[0] in text
    assert text.endswith("Editorial, tasteful, no lingerie, no nudity.")


def test_at_least_eight_distinct_poses_and_seven_registers():
    assert len(cw.POSES) >= 8 and len(set(cw.POSES)) == len(cw.POSES)
    assert len(cw.GLAM_REGISTERS) >= 7


def test_no_school_uniforms_or_lingerie_anywhere():
    forbidden = ("school", "uniform", "lingerie", "nude")
    texts = cw.OUTFITS_TORSO + cw.OUTFITS_BACK + cw.GLAM_REGISTERS + cw.POSES + cw.SCENES
    for t in texts:
        assert not any(w in t.lower() for w in forbidden), t


# --- 4. concepts and names --------------------------------------------------


ALLOWED_GROUPS = ("American", "Spanish", "Argentinian", "Russian", "French",
                  "Italian", "Scandinavian", "Czech", "Polish", "Korean", "Japanese")


def test_concepts_cover_only_the_allowed_groups():
    for c in cw.CONCEPTS:
        # every concept reads "tall <Group> woman, ..."
        group = c["who"].split()[1]
        assert group in ALLOWED_GROUPS, c["who"]
        assert c["region"] in cw.SURNAMES
    assert {c["who"].split()[1] for c in cw.CONCEPTS} == set(ALLOWED_GROUPS)


def test_korean_and_japanese_concepts_read_as_top_tier_beauty():
    korean = [c["who"] for c in cw.CONCEPTS if c["region"] == "korean"][0]
    japanese = [c["who"] for c in cw.CONCEPTS if c["region"] == "japanese"][0]
    assert "actress-level beauty" in korean and "V-line" in korean
    assert "Tokyo model-level beauty" in japanese
    for who in (korean, japanese):
        assert len(who) > 120  # a full English description, not a stub


def test_weighted_rotation_repeats_the_heavier_concepts():
    history = cw._empty_history()
    seen = [cw.next_concept(history)["region"] for _ in range(len(cw.ROTATION))]
    assert len(cw.ROTATION) > len(cw.CONCEPTS)  # weights actually expand the cycle
    assert seen.count("korean") == 2 and seen.count("japanese") == 2
    assert seen.count("anglo") == 4
    # wraps around
    assert cw.next_concept(history)["region"] == seen[0]


def test_surname_pool_has_at_least_300_unique_ascii_names():
    assert len(cw.ALL_SURNAMES) >= 300
    assert len(set(cw.ALL_SURNAMES)) == len(cw.ALL_SURNAMES)
    assert all(s.isascii() and s.isalpha() for s in cw.ALL_SURNAMES)


def test_surnames_are_grouped_by_region():
    assert {"Kim", "Lee", "Park", "Choi", "Jung", "Kang", "Yoon", "Han", "Seo",
            "Shin", "Song", "Lim"} <= set(cw.SURNAMES["korean"])
    assert {"Sato", "Suzuki", "Takahashi", "Tanaka", "Watanabe"} <= set(cw.SURNAMES["japanese"])


def test_new_name_matches_the_concept_region():
    for concept in cw.CONCEPTS:
        name = cw.new_model_name(concept["region"], set(), Rng())
        assert name.startswith("Claire ")
        assert name.split(" ", 1)[1] in cw.SURNAMES[concept["region"]]


def test_new_name_avoids_server_and_history_names():
    region = "korean"
    taken = {f"Claire {s}" for s in cw.SURNAMES[region][:-1]}
    assert cw.new_model_name(region, taken, Rng()) == f"Claire {cw.SURNAMES[region][-1]}"


def test_run_once_never_reuses_a_server_or_history_name():
    listing = {"models": [_model("Claire Kim")], "picked": [_model("Claire Lee")]}
    client = FakeBrainClient({"paused": False, "picked": ["Claire Lee"], "target": 2}, listing)
    ai = FakeAI()
    history = fresh_history()
    history["used_names"].append("Claire Park")
    # force the korean concept so the collision candidates are in the same pool
    history["concept_idx"] = cw.ROTATION.index(
        [i for i, c in enumerate(cw.CONCEPTS) if c["region"] == "korean"][0]
    )
    cw.run_once(client, ai, "gpt-image-2", history, Rng())
    created = {n for (n, _, _) in client.uploads}
    assert created.isdisjoint({"Claire Kim", "Claire Lee", "Claire Park"})


def test_history_records_concept_region_and_used_name(history_file):
    client, _, history = _run_one()
    name = list(history["models"])[0]
    entry = history["models"][name]
    assert entry["concept"] in [c["who"] for c in cw.CONCEPTS]
    assert entry["region"] in cw.SURNAMES
    assert name in history["used_names"]
    # written to disk before generation, so a crash can't recycle the name
    assert name in json.loads(history_file.read_text("utf-8"))["models"]


def test_history_migrates_the_legacy_flat_cache(history_file):
    history_file.write_text(
        json.dumps({"Claire Larsen": "tall Russian woman...", "_concept_idx": 3}), "utf-8"
    )
    history = cw.load_history()
    assert history["models"]["Claire Larsen"]["concept"] == "tall Russian woman..."
    assert history["used_names"] == ["Claire Larsen"]
    assert history["concept_idx"] == 3


# --- 5. robustness ----------------------------------------------------------


def test_moderation_400_retries_once_with_the_soft_text():
    ai = FakeAI()
    ai.images.fail_next = StatusError(400)
    client, ai, _ = _run_one(ai=ai)
    prompts = [c["prompt"] for c in ai.images.generate_calls]
    assert len(prompts) == 2
    assert "softly curved feminine figure" in prompts[0]
    assert "softly curved feminine figure" not in prompts[1]


def test_moderation_400_on_an_edit_retries_with_plain_outfit_wording():
    ai = FakeAI()
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1},
                             {"models": [], "picked": []})
    history = fresh_history()
    # let the face succeed, then trip the first edit
    orig_edit = ai.images.edit

    def edit(**kw):
        if not ai.images.edit_calls:
            ai.images.fail_next = StatusError(400)
        return orig_edit(**kw)

    ai.images.edit = edit
    cw.run_once(client, ai, "gpt-image-2", history, Rng())
    prompts = [c["prompt"] for c in ai.images.edit_calls]
    assert len(prompts) == 3  # first attempt + soft retry + the other edit
    assert cw.SOFT_OUTFIT_TORSO in prompts[1] or cw.SOFT_OUTFIT_BACK in prompts[1]


def test_rate_limit_429_sleeps_twenty_then_retries(slept):
    ai = FakeAI()
    ai.images.fail_next = StatusError(429)
    cw.generate_face(ai, "gpt-image-2", "a test woman")
    assert len(ai.images.generate_calls) == 2
    assert 20 in slept


def test_other_generation_errors_propagate():
    ai = FakeAI()
    ai.images.fail_next = StatusError(418)
    with pytest.raises(StatusError):
        cw.generate_face(ai, "gpt-image-2", "a test woman")


def test_server_5xx_retries_three_times_with_backoff_then_skips(slept):
    client = FakeBrainClient()
    client.state_error = StatusError(503)
    ai = FakeAI()
    with pytest.raises(cw.SkipLoop):
        cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    assert client.state_calls == 4
    assert slept == [2, 5, 10]


def test_connection_errors_are_retried_too(slept):
    client = FakeBrainClient()
    client.state_error = ConnectionError("refused")
    ai = FakeAI()
    with pytest.raises(cw.SkipLoop):
        cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    assert client.state_calls == 4


def test_client_errors_from_the_server_are_not_retried():
    client = FakeBrainClient()
    client.state_error = StatusError(401)
    ai = FakeAI()
    with pytest.raises(StatusError):
        cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    assert client.state_calls == 1


def test_loop_skips_the_round_instead_of_crashing(history_file):
    client = FakeBrainClient()
    client.state_error = StatusError(500)
    ai = FakeAI()
    cw.loop(client, ai, "gpt-image-2", 90, once=True, rng=Rng())  # must not raise
    assert client.uploads == []


def test_loop_runs_a_single_pass_with_once(history_file):
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1},
                             {"models": [], "picked": []})
    ai = FakeAI()
    cw.loop(client, ai, "gpt-image-2", 90, once=True, rng=Rng())
    assert len(client.uploads) == 3
    assert json.loads(history_file.read_text("utf-8"))["models"]


# --- 6. CLI -----------------------------------------------------------------


def test_main_wires_cli_flags_with_interval_default_90(monkeypatch, history_file):
    monkeypatch.setattr(sys, "argv", ["brain-casting-worker", "--url", "http://x", "--token", "t"])
    monkeypatch.setattr(cw, "make_ai_client", lambda: FakeAI())
    captured = {}

    def fake_loop(brain_client, ai_client, image_model, interval, once, rng=None, grok=None):
        captured.update({"url": brain_client.url, "token": brain_client.token,
                         "interval": interval, "once": once, "grok": grok})

    monkeypatch.setattr(cw, "loop", fake_loop)
    cw.main()
    assert captured == {"url": "http://x", "token": "t", "interval": 90,
                        "once": False, "grok": None}


# --- 7. backfill of half-built models --------------------------------------


def _history_with(name, region="korean"):
    history = fresh_history()
    who = [c["who"] for c in cw.CONCEPTS if c["region"] == region][0]
    history["models"][name] = {"concept": who, "region": region}
    history["used_names"].append(name)
    return history


def test_create_model_caches_the_face_locally(face_dir):
    _, _, history = _run_one()
    name = list(history["models"])[0]
    assert cw.face_path(name).read_bytes() == FakeImages.FACE


def test_backfill_generates_only_the_missing_shot_from_the_cached_face(face_dir):
    name = "Claire Kim"
    cw.save_face(name, FakeImages.FACE)
    listing = {"models": [_model(name, ["Claire_Kim_face.png", "Claire_Kim_torso.png"])],
               "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng())

    assert client.uploads == [(name, "Claire_Kim_back.png", FakeImages.EDIT)]
    assert ai.images.generate_calls == []  # no new face
    assert len(ai.images.edit_calls) == 1
    assert ai.images.edit_calls[0]["image"] == FakeImages.FACE
    assert ai.images.edit_calls[0]["prompt"].startswith(cw.REFERENCE_PREFIX)


def test_backfill_can_use_grok_for_the_missing_shot(face_dir):
    name = "Claire Kim"
    cw.save_face(name, FakeImages.FACE)
    listing = {"models": [_model(name, ["Claire_Kim_face.png", "Claire_Kim_back.png"])],
               "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, listing)
    ai = FakeAI()
    calls = []
    # Rng(0) draws "torso" out of EDIT_SHOTS, which is exactly the missing shot
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng(0), make_grok(calls))

    assert client.uploads == [(name, "Claire_Kim_torso.png", GROK_BYTES)]
    assert len(calls) == 1 and ai.images.edit_calls == []


def test_backfill_skips_models_without_a_local_face(face_dir):
    name = "Claire Kim"  # in history, but no cached face
    listing = {"models": [_model(name, ["Claire_Kim_face.png"])], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng())
    assert client.uploads == []
    assert ai.images.edit_calls == [] and ai.images.generate_calls == []


def test_backfill_skips_models_the_worker_did_not_create(face_dir):
    name = "Uploaded Manually"
    cw.save_face(name, FakeImages.FACE)
    listing = {"models": [_model(name, ["face.png"])], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", fresh_history(), Rng())
    assert client.uploads == []


def test_backfill_leaves_complete_models_alone(face_dir):
    name = "Claire Kim"
    cw.save_face(name, FakeImages.FACE)
    files = ["Claire_Kim_face.png", "Claire_Kim_torso.png", "Claire_Kim_back.png"]
    listing = {"models": [_model(name, files)], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng())
    assert client.uploads == []


def test_backfill_recognises_legacy_bare_shot_filenames(face_dir):
    name = "Claire Kim"
    cw.save_face(name, FakeImages.FACE)
    listing = {"models": [_model(name, ["face.png", "torso.png", "back.png"])], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng())
    assert client.uploads == []


def test_backfill_runs_before_the_top_up_step(face_dir):
    name = "Claire Kim"
    cw.save_face(name, FakeImages.FACE)
    listing = {"models": [_model(name, ["Claire_Kim_face.png"])], "picked": []}
    client = FakeBrainClient({"paused": False, "picked": [], "target": 2}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng())
    order = [(m, f) for (m, f, _) in client.uploads]
    # the two backfilled shots come first, then the brand-new model's three
    assert order[0] == (name, "Claire_Kim_torso.png")
    assert order[1] == (name, "Claire_Kim_back.png")
    assert len(order) == 5
    assert {m for (m, _) in order[2:]} != {name}


def test_backfill_is_skipped_when_paused(face_dir):
    name = "Claire Kim"
    cw.save_face(name, FakeImages.FACE)
    listing = {"models": [_model(name, ["Claire_Kim_face.png"])], "picked": []}
    client = FakeBrainClient({"paused": True, "picked": [], "target": 10}, listing)
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", _history_with(name), Rng())
    assert client.uploads == []
