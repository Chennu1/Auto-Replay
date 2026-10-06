"""Creator Personality Agent.

Non-invasive facade around the existing personality learner. Keeping the
implementation in agent.py for now avoids changing runtime behavior while
giving the architecture a dedicated module boundary.
"""

from .agent import learn_creator_personality


def format_creator_personality(row: dict | None) -> str:
    if not row:
        return "casual, short, natural, friendly; use light emojis when appropriate."
    phrases = row.get("common_phrases") or []
    samples = row.get("sample_replies") or []
    return (
        f"Tone: {row.get('tone') or 'casual'}. "
        f"Style: {row.get('style_instructions') or 'short, natural, friendly'}. "
        f"Average reply length: {row.get('average_reply_length') or 80} characters. "
        f"Emoji frequency: {row.get('emoji_frequency') or 0.2}. "
        f"Common phrases: {', '.join(phrases[-10:])}. "
        f"Approved reply examples: {' | '.join(samples[-10:])}."
    )


__all__ = ["learn_creator_personality", "format_creator_personality"]
