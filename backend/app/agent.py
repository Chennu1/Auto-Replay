import json
import os
from google import genai
from .safety import assess_risk

SYSTEM_PROMPT = """You are Auto-Replay, an AI social comment reply agent.
Sound like a real creator, never a customer-service bot.
Use the comment, content context, creator style and commenter memory.
Never invent facts. Keep replies concise. Do not argue with trolls.
Return JSON only with intent, sentiment, risk_level, confidence, replies
(exactly 3 short candidates), recommended_reply, reason."""

def _fallback(comment, reason="Fallback mode; AI provider temporarily unavailable."):
    risk = assess_risk(comment)
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
    }

def _generate_with_model(client, model, prompt):
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)

def generate_reply(req):
    if not os.getenv("GEMINI_API_KEY"):
        return _fallback(req.comment, "GEMINI_API_KEY is not configured.")

    risk = assess_risk(req.comment)
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
            data = _generate_with_model(client, model, prompt)
            level = {"low": 0, "medium": 1, "high": 2}
            data["risk_level"] = max(
                data.get("risk_level", "low"),
                risk,
                key=lambda x: level.get(x, 2),
            )
            return data
        except Exception as exc:
            errors.append(f"{model}: {exc}")

    return _fallback(
        req.comment,
        "AI provider temporarily unavailable; generated a safe local suggestion. "
        + " | ".join(errors)[:500],
    )
