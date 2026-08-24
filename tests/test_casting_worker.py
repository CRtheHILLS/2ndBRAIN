import base64
from types import SimpleNamespace

import pytest
from sync import casting_worker as cw


class FakeBrainClient:
    def __init__(self, state, listing):
        self._state = state
        self._listing = listing
        self.uploads = []

    def get_state(self):
        return self._state

    def get_list(self):
        return self._listing

    def upload(self, model, filename, data):
        self.uploads.append((model, filename, data))


class FakeImages:
    def __init__(self):
        self.calls = []
        self.fail_first_with = None  # optional exception to raise once

    def generate(self, model, prompt, size, quality):
        self.calls.append(prompt)
        if self.fail_first_with is not None and len(self.calls) == 1:
            exc = self.fail_first_with
            self.fail_first_with = None
            raise exc
        payload = base64.b64encode(b"png-bytes").decode()
        return SimpleNamespace(data=[SimpleNamespace(b64_json=payload)])


class FakeAI:
    def __init__(self):
        self.images = FakeImages()


class StatusError(Exception):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(cw, "_sleep", lambda s: None)


@pytest.fixture(autouse=True)
def _no_xai_key_by_default(monkeypatch):
    # Keep glam-shot tests hermetic: never let a real environment variable
    # leak in and change behavior of tests that don't set it themselves.
    monkeypatch.delenv("XAI_API_KEY", raising=False)


class FakeXAIResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_xai_post(calls, image_bytes=b"glam-bytes"):
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        payload = base64.b64encode(image_bytes).decode()
        return FakeXAIResponse({"data": [{"b64_json": payload}]})

    return fake_post


def test_run_once_skips_when_paused():
    client = FakeBrainClient({"paused": True, "picked": [], "target": 10}, {"models": [], "picked": []})
    ai = FakeAI()
    cache = cw.run_once(client, ai, "gpt-image-2", {})
    assert client.uploads == []
    assert ai.images.calls == []
    assert cache == {}


def test_run_once_creates_new_model_when_active_under_target(monkeypatch):
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    client = FakeBrainClient({"paused": False, "picked": [], "target": 1}, {"models": [], "picked": []})
    ai = FakeAI()
    cache = cw.run_once(client, ai, "gpt-image-2", {})

    assert len(client.uploads) == 3
    filenames = sorted(f for (_, f, _) in client.uploads)
    assert filenames == ["back.png", "face.png", "torso.png"]
    names = {name for (name, _, _) in client.uploads}
    assert len(names) == 1
    name = names.pop()
    assert name.startswith("Claire ")
    assert cache[name] == cw.CONCEPTS[0]
    for (_, _, data) in client.uploads:
        assert data == b"png-bytes"


def test_run_once_fills_missing_shot_using_cached_description():
    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1},
        {"models": [{"name": "Claire Larsen", "files": ["face.png", "torso.png"]}], "picked": []},
    )
    ai = FakeAI()
    cache = {"Claire Larsen": cw.CONCEPTS[4]}
    cw.run_once(client, ai, "gpt-image-2", cache)
    assert client.uploads == [("Claire Larsen", "back.png", b"png-bytes")]


def test_run_once_skips_fill_when_no_cached_description():
    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1},
        {"models": [{"name": "Uploaded Manually", "files": ["face.png"]}], "picked": []},
    )
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", {})
    assert client.uploads == []


def test_run_once_ignores_picked_models_for_target_math():
    client = FakeBrainClient(
        {"paused": False, "picked": ["Claire Kim"], "target": 1},
        {"models": [], "picked": [{"name": "Claire Kim", "files": ["face.png", "torso.png", "back.png"]}]},
    )
    ai = FakeAI()
    cache = {}
    cw.run_once(client, ai, "gpt-image-2", cache)
    # active (non-picked) count is 0 < target 1, so a new model must be created
    assert len(client.uploads) == 3
    names = {name for (name, _, _) in client.uploads}
    assert "Claire Kim" not in names


def test_brain_client_upload_sends_token_header(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        captured["files"] = files

        class R:
            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr(cw.httpx, "post", fake_post)
    client = cw.BrainClient("http://x/", "tok123")
    client.upload("Claire Larsen", "face.png", b"bytes")

    assert captured["url"] == "http://x/casting/upload"
    assert captured["headers"]["X-Brain-Token"] == "tok123"
    assert captured["data"] == {"model": "Claire Larsen"}
    assert captured["files"]["file"][0] == "face.png"


def test_build_prompt_face_matches_spec():
    prompt = cw.build_prompt("a test woman", "face")
    assert prompt == (
        "Photorealistic professional model photography, Vogue editorial level. "
        "Subject: a test woman, 173cm, slender long-legged model proportions. "
        "Extreme close-up beauty portrait, face filling the frame, flawless "
        "natural skin texture, soft studio light, direct eye contact, gentle "
        "confident expression. Fully clothed, tasteful."
    )


def test_build_prompt_torso_picks_outfit_from_list(monkeypatch):
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    hard = cw.build_prompt("a test woman", "torso", soft=False)
    assert any(outfit in hard for outfit in cw.OUTFITS_TORSO)
    assert any(scene in hard for scene in cw.SCENES)


def test_build_prompt_torso_soft_uses_generic_dress_phrase():
    soft = cw.build_prompt("a test woman", "torso", soft=True)
    assert cw.SOFT_OUTFIT_TORSO in soft
    assert all(outfit not in soft for outfit in cw.OUTFITS_TORSO)


def test_build_prompt_back_picks_outfit_from_list(monkeypatch):
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    hard = cw.build_prompt("a test woman", "back", soft=False)
    assert any(outfit in hard for outfit in cw.OUTFITS_BACK)
    assert any(scene in hard for scene in cw.SCENES)


def test_build_prompt_back_soft_uses_generic_gown_phrase():
    soft = cw.build_prompt("a test woman", "back", soft=True)
    assert cw.SOFT_OUTFIT_BACK in soft
    assert all(outfit not in soft for outfit in cw.OUTFITS_BACK)


def test_outfit_and_scene_lists_meet_minimum_size_with_no_forbidden_items():
    assert len(cw.OUTFITS_TORSO) >= 6
    assert len(cw.OUTFITS_BACK) >= 5
    forbidden = ("school", "uniform", "lingerie")
    for outfit in cw.OUTFITS_TORSO + cw.OUTFITS_BACK:
        lowered = outfit.lower()
        assert not any(word in lowered for word in forbidden)
    for register in cw.GLAM_REGISTERS:
        lowered = register.lower()
        assert not any(word in lowered for word in forbidden)


def test_generate_shot_retries_with_soft_prompt_on_400(monkeypatch):
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    ai = FakeAI()
    ai.images.fail_first_with = StatusError(400)
    data = cw.generate_shot(ai, "a test woman", "torso", "gpt-image-2")
    assert data == b"png-bytes"
    assert len(ai.images.calls) == 2
    assert any(outfit in ai.images.calls[0] for outfit in cw.OUTFITS_TORSO)
    assert cw.SOFT_OUTFIT_TORSO in ai.images.calls[1]


def test_generate_shot_retries_after_sleep_on_429(monkeypatch):
    slept = []
    monkeypatch.setattr(cw, "_sleep", lambda s: slept.append(s))
    ai = FakeAI()
    ai.images.fail_first_with = StatusError(429)
    data = cw.generate_shot(ai, "a test woman", "face", "gpt-image-2")
    assert data == b"png-bytes"
    assert len(ai.images.calls) == 2
    assert slept == [20]


def test_generate_shot_reraises_other_errors():
    ai = FakeAI()
    ai.images.fail_first_with = StatusError(500)
    with pytest.raises(StatusError):
        cw.generate_shot(ai, "a test woman", "face", "gpt-image-2")


def test_new_model_name_avoids_existing_names(monkeypatch):
    existing = {f"Claire {s}" for s in cw.SURNAME_POOL[:-1]}
    name = cw._new_model_name(existing)
    assert name == f"Claire {cw.SURNAME_POOL[-1]}"


def test_concept_rotation_cycles_through_all_concepts():
    cache = {}
    seen = [cw._next_concept(cache) for _ in range(len(cw.CONCEPTS))]
    assert seen == cw.CONCEPTS
    # wraps back around
    assert cw._next_concept(cache) == cw.CONCEPTS[0]
    # the rotation counter must never be treated as a cached model description
    assert "_concept_idx" in cache


# --- Grok glamour slot -------------------------------------------------


def test_poses_list_has_at_least_eight_distinct_entries():
    assert len(cw.POSES) >= 8
    assert len(set(cw.POSES)) == len(cw.POSES)


def test_glam_views_are_front_and_back():
    assert set(cw.GLAM_VIEWS) == {"front", "back"}


def test_build_glam_prompt_contains_identity_pose_register_and_safety():
    prompt = cw.build_glam_prompt(
        "a test woman", "front", cw.POSES[2], cw.GLAM_REGISTERS[1]
    )
    assert "Subject: a test woman, 173cm, slender long-legged model proportions." in prompt
    assert cw.POSES[2] in prompt
    assert cw.GLAM_REGISTERS[1] in prompt
    assert prompt.endswith(cw.GLAM_SAFETY)


def test_generate_glam_shot_returns_none_when_key_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))
    result = cw.generate_glam_shot("a test woman")
    assert result is None
    assert calls == []


def test_generate_glam_shot_calls_xai_with_expected_payload(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))

    data = cw.generate_glam_shot("a test woman")

    assert data == b"glam-bytes"
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == cw.XAI_IMAGE_URL
    assert call["headers"]["Authorization"] == "Bearer xai-test-key"
    assert call["json"]["model"] == "grok-imagine-image-quality"
    assert call["json"]["n"] == 1
    assert call["json"]["response_format"] == "b64_json"
    prompt = call["json"]["prompt"]
    assert cw.POSES[0] in prompt
    assert cw.GLAM_REGISTERS[0] in prompt
    assert prompt.endswith(cw.GLAM_SAFETY)


def test_run_once_generates_glam_for_new_model_when_xai_key_set(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))

    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1}, {"models": [], "picked": []}
    )
    ai = FakeAI()
    cache = cw.run_once(client, ai, "gpt-image-2", {})

    glam_uploads = [u for u in client.uploads if u[1].endswith("_glam.png")]
    assert len(glam_uploads) == 1
    name, filename, data = glam_uploads[0]
    assert name.startswith("Claire ")
    assert filename == f"{name}_glam.png"
    assert data == b"glam-bytes"
    assert cache[name] == cw.CONCEPTS[0]
    # face/torso/back + glam = 4 uploads total
    assert len(client.uploads) == 4


def test_run_once_skips_glam_when_xai_key_missing(monkeypatch):
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    post_calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(post_calls))

    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1}, {"models": [], "picked": []}
    )
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", {})

    assert post_calls == []
    assert len(client.uploads) == 3
    assert all(not f.endswith("_glam.png") for (_, f, _) in client.uploads)


def test_run_once_fills_glam_for_existing_active_model_missing_it(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))

    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1},
        {
            "models": [
                {"name": "Claire Larsen", "files": ["face.png", "torso.png", "back.png"]}
            ],
            "picked": [],
        },
    )
    ai = FakeAI()
    cache = {"Claire Larsen": cw.CONCEPTS[4]}
    cw.run_once(client, ai, "gpt-image-2", cache)

    assert client.uploads == [("Claire Larsen", "Claire Larsen_glam.png", b"glam-bytes")]
    assert len(calls) == 1
    assert "a test woman" not in calls[0]["json"]["prompt"]  # uses the cached concept, not a stub


def test_run_once_skips_glam_for_active_model_that_already_has_it(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))

    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1},
        {
            "models": [
                {
                    "name": "Claire Larsen",
                    "files": [
                        "face.png",
                        "torso.png",
                        "back.png",
                        "Claire Larsen_glam.png",
                    ],
                }
            ],
            "picked": [],
        },
    )
    ai = FakeAI()
    cache = {"Claire Larsen": cw.CONCEPTS[4]}
    cw.run_once(client, ai, "gpt-image-2", cache)

    assert client.uploads == []
    assert calls == []


def test_run_once_skips_glam_for_active_model_without_cached_description(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))

    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1},
        {
            "models": [{"name": "Uploaded Manually", "files": ["face.png"]}],
            "picked": [],
        },
    )
    ai = FakeAI()
    cw.run_once(client, ai, "gpt-image-2", {})

    assert client.uploads == []
    assert calls == []


def test_glam_upload_sleeps_four_seconds(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setattr(cw.random, "choice", lambda pool: pool[0])
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post([]))
    slept = []
    monkeypatch.setattr(cw, "_sleep", lambda s: slept.append(s))

    client = FakeBrainClient(
        {"paused": False, "picked": [], "target": 1},
        {
            "models": [
                {"name": "Claire Larsen", "files": ["face.png", "torso.png", "back.png"]}
            ],
            "picked": [],
        },
    )
    ai = FakeAI()
    cache = {"Claire Larsen": cw.CONCEPTS[4]}
    cw.run_once(client, ai, "gpt-image-2", cache)

    assert 4 in slept


def test_run_once_skips_glam_when_paused(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    calls = []
    monkeypatch.setattr(cw.httpx, "post", _fake_xai_post(calls))

    client = FakeBrainClient(
        {"paused": True, "picked": [], "target": 10},
        {
            "models": [
                {"name": "Claire Larsen", "files": ["face.png", "torso.png", "back.png"]}
            ],
            "picked": [],
        },
    )
    ai = FakeAI()
    cache = {"Claire Larsen": cw.CONCEPTS[4]}
    cw.run_once(client, ai, "gpt-image-2", cache)

    assert client.uploads == []
    assert calls == []
