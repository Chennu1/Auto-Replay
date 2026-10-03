import os
import json
from pydantic import BaseModel
from google import genai

class ReplyRequest(BaseModel):
    comment: str
    content_context: str = ""
    creator_style: str = "casual, short, natural, friendly"
    commenter_memory: str = ""

SYSTEM_PROMPT = """You are an AI social comment reply agent. Write replies that feel like the creator, not like a customer-service bot. Use the comment, content context, creator style and commenter memory. Never invent facts. Keep replies concise. Do not argue with trolls. Flag threats, self-harm, sexual content involving minors, doxxing, serious allegations, or other high-risk content for human review instead of generating an auto-publish reply.

Return JSON with: intent, sentiment, risk_level, confidence, replies (array of 3 short replies), recommended_reply, reason."""

def _fallback(req: ReplyRequest):
    text = req.comment.lower()
    if "breed" in text:
        reply = "He’s a Shih Tzu ❤️"
        intent = "question"
    elif any(x in text for x in ["cute", "adorable", "handsome"]):
        reply = "He knows it too 😂"
        intent = "praise"
    else:
        reply = "Haha, appreciate it 😄"
        intent = "general"
    return {"intent": intent, "sentiment": "positive", "risk_level": "low", "confidence": 0.55, "replies": [reply], "recommended_reply": reply, "reason": "Fallback response; configure GEMINI_API_KEY for contextual generation."}

def generate_reply(req: ReplyRequest):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return _fallback(req)
    client = genai.Client(api_key=key)
    prompt = f"{SYSTEM_PROMPT}\n\nCOMMENT:\n{req.comment}\n\nCONTENT CONTEXT:\n{req.content_context}\n\nCREATOR STYLE:\n{req.creator_style}\n\nCOMMENTER MEMORY:\n{req.commenter_memory}\n"
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt, config={"response_mime_type": "application/json"})
    return json.loads(response.text)
