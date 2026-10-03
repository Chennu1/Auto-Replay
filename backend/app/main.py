from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from .agent import generate_reply

app = FastAPI(title="Auto-Replay API", version="0.1.0")

class ReplyRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)
    content_context: str = Field(default="", max_length=6000)
    creator_style: str = Field(default="casual, short, natural, friendly", max_length=2000)
    commenter_memory: str = Field(default="", max_length=4000)

@app.get("/health")
def health():
    return {"status": "ok", "service": "auto-replay-api"}

@app.post("/api/replies/generate")
def replies(request: ReplyRequest):
    try:
        return generate_reply(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
