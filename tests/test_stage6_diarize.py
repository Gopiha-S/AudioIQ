import sys
import types

from app.pipeline import stage6_diarize


class FakePipeline:
    last_kwargs = None

    @classmethod
    def from_pretrained(cls, model_name, **kwargs):
        cls.last_kwargs = kwargs
        if "use_auth_token" in kwargs:
            raise TypeError("Pipeline.from_pretrained() got an unexpected keyword argument 'use_auth_token'")
        return cls()

    def to(self, device):
        return None


def test_pyannote_uses_hf_token_keyword(monkeypatch):
    fake_pyannote = types.ModuleType("pyannote")
    fake_audio = types.ModuleType("pyannote.audio")
    fake_audio.Pipeline = FakePipeline
    fake_pyannote.audio = fake_audio

    monkeypatch.setitem(sys.modules, "pyannote", fake_pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", fake_audio)
    monkeypatch.setattr(stage6_diarize, "_diarization_pipeline", None)
    monkeypatch.setattr(stage6_diarize.settings, "hf_token", "abc123")

    pipeline = stage6_diarize._load_pyannote()

    assert isinstance(pipeline, FakePipeline)
    assert FakePipeline.last_kwargs == {"token": "abc123"}
