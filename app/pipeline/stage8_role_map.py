"""
Stage 8 — Role Map.

Assigns a semantic role (e.g. "agent" vs "customer") to each detected
speaker using a keyword + question-frequency heuristic rather than a
trained classifier — this keeps the pipeline dependency-light and fully
explainable, which matters for a "why did it call this speaker the agent"
support question.

Heuristic, roughly:
  - Speakers who ask a high proportion of questions and/or use
    service-oriented phrases ("how can I help", "thank you for calling")
    are scored toward "agent".
  - Speakers who describe a problem, express frustration, or answer more
    than they ask are scored toward "customer".
  - Ties or insufficient signal fall back to "speaker" (unassigned) rather
    than guessing with low confidence.
"""
import re
from collections import defaultdict

from app.models.schema import PipelineResult, SpeakerProfile

AGENT_PHRASES = [
    "how can i help", "how may i help", "thank you for calling",
    "is there anything else", "let me check", "let me look into that",
    "i can help you with that", "one moment please", "i apologize for",
]
CUSTOMER_PHRASES = [
    "i'm calling about", "i have a problem", "i'm not happy",
    "this isn't working", "i need help with", "i want to",
]

QUESTION_PATTERN = re.compile(r"\?\s*$|^\s*(who|what|when|where|why|how|can you|could you|do you|is there)\b", re.IGNORECASE)


def _score_agent_likeness(text_blob: str, question_ratio: float) -> float:
    lower = text_blob.lower()
    agent_hits = sum(1 for p in AGENT_PHRASES if p in lower)
    customer_hits = sum(1 for p in CUSTOMER_PHRASES if p in lower)

    score = 0.5
    score += 0.1 * agent_hits
    score -= 0.1 * customer_hits
    score += 0.3 * (question_ratio - 0.5)  # more questions -> more agent-like
    return max(0.0, min(1.0, score))


def run(result: PipelineResult) -> PipelineResult:
    if not result.transcript:
        result.speaker_profiles = []
        return result

    by_speaker: dict[str, list] = defaultdict(list)
    for turn in result.transcript:
        by_speaker[turn.speaker_id].append(turn)

    profiles: list[SpeakerProfile] = []
    scored: dict[str, float] = {}

    for speaker_id, turns in by_speaker.items():
        text_blob = " ".join(t.text for t in turns)
        word_count = len(text_blob.split())
        question_count = sum(1 for t in turns if QUESTION_PATTERN.search(t.text.strip()))
        question_ratio = question_count / len(turns) if turns else 0.0

        score = _score_agent_likeness(text_blob, question_ratio)
        scored[speaker_id] = score

        profiles.append(
            SpeakerProfile(
                speaker_id=speaker_id,
                word_count=word_count,
                turn_count=len(turns),
                question_count=question_count,
            )
        )

    # Assign roles relative to each other: highest scorer -> agent,
    # lowest -> customer, only when there's a meaningful gap (2 speakers).
    if len(scored) == 2:
        ordered = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
        (top_id, top_score), (bottom_id, bottom_score) = ordered
        gap = top_score - bottom_score
        role_confidence = round(min(0.5 + gap, 0.95), 2) if gap > 0.05 else 0.4

        for p in profiles:
            if p.speaker_id == top_id:
                p.role = "agent" if gap > 0.05 else "speaker"
                p.role_confidence = role_confidence
            elif p.speaker_id == bottom_id:
                p.role = "customer" if gap > 0.05 else "speaker"
                p.role_confidence = role_confidence
    else:
        # 1 or 3+ speakers: not enough structure to confidently call agent/customer
        for p in profiles:
            p.role = "speaker"
            p.role_confidence = 0.3

    role_by_speaker = {p.speaker_id: (p.role, p.role_confidence) for p in profiles}
    for turn in result.transcript:
        role, _ = role_by_speaker.get(turn.speaker_id, (None, 0.0))
        turn.role = role

    result.speaker_profiles = profiles
    return result
