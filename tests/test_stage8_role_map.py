from app.models.schema import PipelineResult, TranscriptTurn
from app.pipeline import stage8_role_map


def _turn(speaker, text):
    return TranscriptTurn(speaker_id=speaker, start=0, end=1, text=text)


def test_two_speaker_role_assignment():
    result = PipelineResult(job_id="t1")
    result.transcript = [
        _turn("SPEAKER_00", "Thank you for calling, how can I help you today?"),
        _turn("SPEAKER_01", "I have a problem with my order, it never arrived."),
        _turn("SPEAKER_00", "I apologize for that. Can you give me your order number?"),
        _turn("SPEAKER_01", "Sure, it is 12345."),
    ]

    result = stage8_role_map.run(result)

    roles = {p.speaker_id: p.role for p in result.speaker_profiles}
    assert roles["SPEAKER_00"] == "agent"
    assert roles["SPEAKER_01"] == "customer"
    assert all(t.role is not None for t in result.transcript)


def test_single_speaker_falls_back_to_unassigned():
    result = PipelineResult(job_id="t2")
    result.transcript = [_turn("SPEAKER_00", "Just talking to myself here.")]

    result = stage8_role_map.run(result)

    assert result.speaker_profiles[0].role == "speaker"
    assert result.speaker_profiles[0].role_confidence == 0.3


def test_empty_transcript_produces_no_profiles():
    result = PipelineResult(job_id="t3")
    result = stage8_role_map.run(result)
    assert result.speaker_profiles == []
