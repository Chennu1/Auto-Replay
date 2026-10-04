import json
import os

from google import genai
from google.genai import types

from .safety import assess_risk, assess_safety

SYSTEM_PROMPT = """You are Auto-Replay, an AI social comment reply agent.
Sound like a real creator, never a customer-service bot.
Use the comment, content context, creator style and commenter memory.
If visual/video context is supplied, use only what is actually visible or stated.
Never invent facts. Keep replies concise. Do not argue with trolls. Safety is more important than engagement. Never provide medical, legal, financial, or personal-data advice as if you are a professional. Never reveal secrets, credentials, private information, or location. If the comment is abusive, spammy, threatening, sensitive, or reputation-risky, prefer a calm human-review outcome.
Return JSON only with intent, sentiment, risk_level, confidence, language, language_confidence, understood, understanding_confidence, replies
(exactly 3 short candidates), recommended_reply, reason, video_summary.
The reply MUST be written in the same language as the commenter. Support any language you can reliably understand.
If the comment is ambiguous, unreadable, mostly noise, cannot be confidently understood, or the requested context cannot be understood, set understood=false and understanding_confidence below 0.60 when the meaning is genuinely uncertain. If you can safely draft a best-effort reply, still return the candidates so a human can approve or skip them."""

def _fallback(comment, reason="Fallback mode; AI provider temporarily unavailable."):
    safety = assess_safety(comment)
    risk = safety["risk_level"]
    text = comment.lower()
    if risk != "low":
        return {
            "intent": "needs_review",
            "sentiment": "unknown",
            "risk_level": risk,
            "confidence": 1.0,
            "replies": [],
            "recommended_reply": "",
            "reason": "Safety gate requires human review.",
            "video_summary": "",
            "language": "",
            "language_confidence": 0.0,
            "understood": False,
            "understanding_confidence": 0.0,
            "safety_categories": safety["categories"],
            "safety_reasons": safety["reasons"],
            "safety_action": safety["action"],
        }
    if "breed" in text or "what breed" in text:
        replies = ["He’s a Shih Tzu ❤️", "He’s a Shih Tzu! 😊", "He’s our little Shih Tzu 😂"]
        intent = "question"
    elif any(x in text for x in ["cute", "adorable", "handsome", "beautiful", "love max", "nice max"]):
        replies = ["He knows it too 😂", "Haha, he’ll love this ❤️", "He definitely knows he’s cute 😂"]
        intent = "compliment"
    else:
        replies = ["Haha, appreciate it 😄", "😂❤️", "Glad you enjoyed it!"]
        intent = "general"
    return {
        "intent": intent,
        "sentiment": "positive",
        "risk_level": "low",
        "confidence": 0.55,
        "replies": replies,
        "recommended_reply": replies[0],
        "reason": reason,
        "video_summary": "",
        "language": "unknown",
        "language_confidence": 0.0,
        "understood": False,
        "understanding_confidence": 0.0,
        "safety_categories": safety["categories"],
        "safety_reasons": safety["reasons"],
        "safety_action": safety["action"],
    }

def _generate_with_model(client, model, prompt, media_bytes=None, mime_type=None):
    contents = prompt
    if media_bytes:
        contents = [
            types.Part.from_bytes(data=media_bytes, mime_type=mime_type or "video/mp4"),
            prompt,
        ]
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)

def generate_reply(req, media_bytes=None, mime_type=None):
    if not os.getenv("GEMINI_API_KEY"):
        return _fallback(req.comment, "GEMINI_API_KEY is not configured.")

    safety = assess_safety(req.comment, content_context=req.content_context)
    risk = safety["risk_level"]
    if risk == "high":
        return _fallback(req.comment, "Safety gate requires human review.")

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        f"{SYSTEM_PROMPT}\n"
        f"COMMENT:\n{req.comment}\n"
        f"CONTENT:\n{req.content_context}\n"
        f"STYLE:\n{req.creator_style}\n"
        f"MEMORY:\n{req.commenter_memory}"
    )

    primary = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
    errors = []

    for model in dict.fromkeys([primary, fallback_model]):
        try:
            data = _generate_with_model(client, model, prompt, media_bytes, mime_type)
            level = {"low": 0, "medium": 1, "high": 2}
            data["risk_level"] = max(
                data.get("risk_level", "low"),
                risk,
                key=lambda x: level.get(x, 2),
            )
            data["safety_categories"] = safety["categories"]
            data["safety_reasons"] = safety["reasons"]
            data["safety_action"] = safety["action"]
            data["language"] = str(data.get("language") or "").strip() or "unknown"
            data["language_confidence"] = max(0.0, min(1.0, float(data.get("language_confidence", 0.0))))
            data["understood"] = bool(data.get("understood", False))
            data["understanding_confidence"] = max(0.0, min(1.0, float(data.get("understanding_confidence", 0.0))))
            replies = [str(x).strip() for x in (data.get("replies") or []) if str(x).strip()][:3]
            data["replies"] = replies
            data["recommended_reply"] = str(data.get("recommended_reply") or (replies[0] if replies else "")).strip()
            if data["language"] == "unknown" or data["language_confidence"] < 0.60:
                data["understood"] = False
                data["replies"] = []
                data["recommended_reply"] = ""
                data["safety_action"] = "human_review"
                data["risk_level"] = "medium"
                data["reason"] = "Comment language could not be understood with enough confidence; human review required."
            elif not data["understood"] or data["understanding_confidence"] < 0.60:
                data["safety_action"] = "human_review"
                data["risk_level"] = "medium"
                data["reason"] = "Comment meaning could not be understood with enough confidence; human review required."
            if data["risk_level"] == "high":
                data["replies"] = []
                data["recommended_reply"] = ""
                data["safety_action"] = "block_automation"
            elif data["risk_level"] == "medium":
                data["safety_action"] = "human_review"
            data["video_understanding_used"] = bool(media_bytes)
            return data
        except Exception as exc:
            errors.append(f"{model}: {exc}")

    return _fallback(
        req.comment,
        "AI provider temporarily unavailable; generated a safe local suggestion. "
        + " | ".join(errors)[:500],
    )


def learn_creator_personality(samples):
    """Infer a compact creator voice profile from approved reply examples."""
    samples = [str(x).strip() for x in (samples or []) if str(x).strip()]
    if not samples:
        return {
            "tone": "casual",
            "style_instructions": "Short, natural, warm, playful creator voice.",
            "common_phrases": [],
            "emoji_frequency": 0.2,
            "average_reply_length": 80,
        }

    if not os.getenv("GEMINI_API_KEY"):
        return _local_personality(samples)

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = """Analyze these approved Instagram replies from one creator.
Infer the creator's actual writing style, not a generic social-media style.
Return JSON only:
{
  "tone": "one short description",
  "style_instructions": "specific instructions for generating replies",
  "common_phrases": ["up to 8 short recurring phrases"],
  "emoji_frequency": 0.0,
  "average_reply_length": 0
}
Do not invent phrases. Keep style instructions concise.
APPROVED REPLIES:
""" + "\n".join(f"- {x}" for x in samples[-20:])

    for model in dict.fromkeys([
        os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite"),
    ]):
        try:
            data = _generate_with_model(client, model, prompt)
            data["common_phrases"] = [str(x) for x in (data.get("common_phrases") or [])[:8]]
            data["emoji_frequency"] = max(0.0, min(1.0, float(data.get("emoji_frequency", 0.2))))
            data["average_reply_length"] = max(1, min(500, int(data.get("average_reply_length", 80))))
            return data
        except Exception:
            continue
    return _local_personality(samples)


def _local_personality(samples):
    emoji_chars = ("❤️", "😂", "😊", "😄", "🥰", "🐶", "🤣", "😭", "🔥")
    emoji_frequency = sum(any(ch in x for ch in emoji_chars) for x in samples) / len(samples)
    avg = round(sum(len(x) for x in samples) / len(samples))
    tone = "warm, casual and playful" if emoji_frequency >= 0.35 else "casual, natural and friendly"
    return {
        "tone": tone,
        "style_instructions": f"Keep replies around {avg} characters, natural and creator-like; avoid customer-service language.",
        "common_phrases": [],
        "emoji_frequency": round(emoji_frequency, 3),
        "average_reply_length": avg,
    }
