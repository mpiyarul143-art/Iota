"""
Unit tests for the modern TTS engine (utils/tts_engine.py).

These prove the "0 bugs / 0 errors" contract:
  * voice validation rejects unknown/invalid values,
  * the fallback catalogue always has the 37 Bulbul v3 voices,
  * auto-fetch parse normalises the API payload (and degrades to fallback),
  * synthesis + voice cloning handle success AND failure without raising.

Network is fully mocked so the suite runs offline and fast.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
IOTA = os.path.dirname(HERE)
if IOTA not in sys.path:
    sys.path.insert(0, IOTA)

os.environ.setdefault("BOT_TOKEN", "123456:fake-test-token")
os.environ.setdefault("OWNER_ID", "111111")
os.environ.setdefault("MONGO_URI",
                      "mongodb+srv://test:test@cluster0.tjpjh4k.mongodb.net/iota_bot")

import utils.tts_engine as eng  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Fake aiohttp layer ───────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status=200, json_data=None, text="ok"):
        self.status = status
        self._json = json_data or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        return self._json

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, get=None, post=None):
        self._get = get
        self._post = post

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, *a, **k):
        return self._get or _FakeResp()

    def post(self, *a, **k):
        return self._post or _FakeResp()


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation(unittest.TestCase):
    def setUp(self):
        eng._tts_config.update(
            {"model": "bulbul:v3", "speaker": "shubh",
             "pace": 1.0, "temperature": 0.6, "sample_rate": 24000})

    def test_default_speaker_is_valid(self):
        self.assertTrue(eng.is_valid_voice("shubh"))
        self.assertTrue(eng.is_valid_voice("PRIYA"))  # case-insensitive

    def test_unknown_speaker_rejected(self):
        ok, err = eng.set_tts_setting("speaker", "not-a-real-voice")
        self.assertFalse(ok)
        self.assertIn("Invalid speaker", err)

    def test_known_speaker_accepted(self):
        ok, err = eng.set_tts_setting("speaker", "priya")
        self.assertTrue(ok)
        self.assertEqual(eng.get_tts_config()["speaker"], "priya")

    def test_pace_bounds(self):
        self.assertTrue(eng.set_tts_setting("pace", "2.0")[0])
        self.assertFalse(eng.set_tts_setting("pace", "5")[0])   # too fast
        self.assertFalse(eng.set_tts_setting("pace", "abc")[0])  # not a number

    def test_temperature_bounds(self):
        self.assertTrue(eng.set_tts_setting("temperature", "0.01")[0])
        self.assertFalse(eng.set_tts_setting("temperature", "2")[0])

    def test_sample_rate_whitelist(self):
        self.assertTrue(eng.set_tts_setting("sample_rate", "32000")[0])
        self.assertFalse(eng.set_tts_setting("sample_rate", "12345")[0])

    def test_unknown_key_rejected(self):
        ok, err = eng.set_tts_setting("loudness", "1.5")
        self.assertFalse(ok)
        self.assertIn("Unknown", err)

    def test_model_locked_to_v3(self):
        ok, _ = eng.set_tts_setting("model", "bulbul:v2")
        self.assertFalse(ok)
        ok, _ = eng.set_tts_setting("model", "bulbul:v3")
        self.assertTrue(ok)


class TestCatalogue(unittest.TestCase):
    def test_fallback_has_37_voices(self):
        ids = {v["id"] for v in eng.FALLBACK_VOICES}
        self.assertEqual(len(ids), 37)
        males = [v for v in eng.FALLBACK_VOICES if v["gender"] == "male"]
        females = [v for v in eng.FALLBACK_VOICES if v["gender"] == "female"]
        self.assertEqual(len(males), 23)
        self.assertEqual(len(females), 14)

    def test_get_voices_includes_fallback(self):
        ids = eng.get_voice_ids()
        self.assertIn("shubh", ids)
        self.assertIn("ritu", ids)

    def test_voice_display_shows_name(self):
        self.assertIn("Priya", eng.voice_display("priya"))


# ── Auto-fetch ───────────────────────────────────────────────────────────────

class TestFetchVoices(unittest.TestCase):
    def test_parses_live_payload(self):
        payload = {"voices": [
            {"id": "shubh", "name": "Shubh", "gender": "masculine"},
            {"id": "priya", "name": "Priya", "gender": "feminine"},
            {"id": "weird", "name": "Weird"},  # no gender -> kept, gender ""
        ]}
        fake = _FakeSession(get=_FakeResp(json_data=payload))
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah, \
             patch("utils.tts_engine._persist_voices", new=AsyncMock()):
            mock_ah.ClientSession.return_value = fake
            voices = _run(eng.fetch_voices(force=True))
        self.assertEqual(eng.get_voices_source(), "live API")
        ids = {v["id"] for v in voices}
        self.assertIn("shubh", ids)
        self.assertIn("priya", ids)
        # gender normalisation
        genders = {v["id"]: v["gender"] for v in voices}
        self.assertEqual(genders["shubh"], "male")
        self.assertEqual(genders["priya"], "female")

    def test_network_error_falls_back(self):
        class _Boom:
            async def __aenter__(self):
                raise RuntimeError("boom")
            async def __aexit__(self, *a):
                return False
        fake = _FakeSession(get=_Boom())
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah:
            mock_ah.ClientSession.return_value = fake
            voices = _run(eng.fetch_voices(force=True))
        self.assertEqual(len(voices), 37)
        self.assertIn("built-in fallback", eng.get_voices_source())

    def test_no_api_key_uses_fallback(self):
        with patch.object(eng, "SARVAM_API_KEY", ""):
            voices = _run(eng.fetch_voices(force=True))
        self.assertEqual(len(voices), 37)


# ── Synthesis ────────────────────────────────────────────────────────────────

class TestSynthesis(unittest.TestCase):
    def test_returns_bytes_on_200(self):
        fake = _FakeSession(post=_FakeResp(json_data={"audios": ["Zm9vYmFy"]}))
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah:
            mock_ah.ClientSession.return_value = fake
            out = _run(eng.text_to_speech("hello", "en-IN", "priya"))
        self.assertIsNotNone(out)
        self.assertEqual(out, b"foobar")

    def test_returns_none_on_error(self):
        fake = _FakeSession(post=_FakeResp(status=500, text="nope"))
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah:
            mock_ah.ClientSession.return_value = fake
            out = _run(eng.text_to_speech("hello", "en-IN", "priya"))
        self.assertIsNone(out)

    def test_unknown_speaker_falls_back(self):
        captured = {}

        class _Cap(_FakeResp):
            pass
        fake = _FakeSession(post=_FakeResp(json_data={"audios": ["YQ=="]}))

        def _post(url, json=None, **k):
            captured["payload"] = json
            return _FakeResp(json_data={"audios": ["YQ=="]})
        sess = _FakeSession()
        sess.post = _post
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah:
            mock_ah.ClientSession.return_value = sess
            _run(eng.text_to_speech("hi", "en-IN", "ghost-voice"))
        self.assertEqual(captured["payload"]["speaker"], "shubh")


# ── Voice cloning ────────────────────────────────────────────────────────────

class TestCloneVoice(unittest.TestCase):
    def test_success_registers_voice(self):
        fake = _FakeSession(post=_FakeResp(
            status=201, json_data={"voice_id": "clone_abc"}))
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah, \
             patch("utils.tts_engine._persist_cloned_voices", new=AsyncMock()):
            mock_ah.ClientSession.return_value = fake
            ok, vid = _run(eng.clone_voice("My Voice", b"audio", "s.ogg",
                                            owner_id=111111))
        self.assertTrue(ok)
        self.assertEqual(vid, "clone_abc")
        self.assertIn("clone_abc", eng.get_voice_ids())

    def test_api_error_returns_false(self):
        fake = _FakeSession(post=_FakeResp(status=403, text="forbidden"))
        with patch.object(eng, "SARVAM_API_KEY", "key"), \
             patch.object(eng, "aiohttp") as mock_ah:
            mock_ah.ClientSession.return_value = fake
            ok, msg = _run(eng.clone_voice("X", b"audio", "s.ogg"))
        self.assertFalse(ok)
        self.assertIn("403", msg)

    def test_no_api_key_returns_false(self):
        with patch.object(eng, "SARVAM_API_KEY", ""):
            ok, msg = _run(eng.clone_voice("X", b"audio", "s.ogg"))
        self.assertFalse(ok)

    def test_delete_cloned_voice(self):
        with patch("utils.tts_engine._persist_cloned_voices", new=AsyncMock()):
            _run(eng.add_cloned_voice("clone_x", "X"))
            self.assertIn("clone_x", eng.get_voice_ids())
        with patch("utils.tts_engine._persist_cloned_voices", new=AsyncMock()), \
             patch("utils.tts_engine.save_tts_config_db", new=AsyncMock()):
            removed = _run(eng.delete_cloned_voice("clone_x"))
        self.assertTrue(removed)
        self.assertNotIn("clone_x", eng.get_voice_ids())


class TestLoadConfigForcesV3(unittest.TestCase):
    def test_stale_v2_model_is_forced_to_v3(self):
        # Simulate a config doc left behind by the OLD bulbul:v2 code.
        stale = {"_id": "tts_settings", "model": "bulbul:v2",
                 "speaker": "anushka", "pace": 1.0,
                 "temperature": 0.6, "sample_rate": 22050}

        class _FakeColl:
            def find_one(self, *a, **k):
                return _maybe_await(stale)
            def update_one(self, *a, **k):
                return _maybe_await(MagicMock())

        class _FakeDB:
            bot_config = _FakeColl()

        async def _maybe_await(v):
            return v

        with patch("utils.mongo_db.get_db", return_value=_FakeDB()), \
             patch("utils.tts_engine.load_cloned_voices_db", new=AsyncMock()):
            _run(eng.load_tts_config_db())

        # Model MUST be forced to v3 (the only supported model) and the
        # v2-only speaker must be reset to a valid v3 voice.
        self.assertEqual(eng.get_tts_config()["model"], "bulbul:v3")
        self.assertIn(eng.get_tts_config()["speaker"], eng.get_voice_ids())


if __name__ == "__main__":
    unittest.main()
