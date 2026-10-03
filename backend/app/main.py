from fastapi import FastAPI,HTTPException
from .models import ReplyRequest
from .agent import generate_reply
app=FastAPI(title='Auto-Replay API',version='0.2.0')
@app.get('/health')
def health():return {'status':'ok','service':'auto-replay-api'}
@app.post('/api/replies/generate')
def replies(request:ReplyRequest):
 try:return generate_reply(request)
 except Exception as exc:raise HTTPException(status_code=500,detail=str(exc))
