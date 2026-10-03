import os
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from supabase import create_client

from .models import ReplyRequest
from .agent import generate_reply
from .instagram import authorization_url, complete_oauth
from .security import decrypt_token

load_dotenv()

app = FastAPI(title="Auto-Replay API", version="0.3.0")
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def admin_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase server credentials are required")
    return create_client(url, key)

def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1]

def authenticated_user(authorization: str | None):
    token = bearer_token(authorization)
    try:
        user = admin_client().auth.get_user(token)
        return user.user
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid session: {exc}")

@app.get("/health")
def health():
    return {"status": "ok", "service": "auto-replay-api"}

@app.post("/api/replies/generate")
def replies(request: ReplyRequest):
    try:
        return generate_reply(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/instagram/connect")
def instagram_connect(authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    return {"authorization_url": authorization_url(str(user.id))}

@app.get("/api/instagram/callback")
def instagram_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(f"{frontend_url}/?instagram_error={quote(error)}")
    if not code or not state:
        return RedirectResponse(f"{frontend_url}/?instagram_error=missing_oauth_response")
    try:
        user_id, account = complete_oauth(state, code)
        db = admin_client()
        db.table("profiles").upsert({"id": user_id}, on_conflict="id").execute()
        db.table("social_accounts").upsert({
            "user_id": user_id,
            "platform": "instagram",
            "account_name": account.get("name") or account.get("username"),
            "platform_user_id": account["ig_user_id"],
            "access_token_encrypted": account["encrypted_token"],
            "status": "connected",
            "metadata": {
                "username": account.get("username"),
                "profile_picture_url": account.get("profile_picture_url"),
                "page_id": account.get("page_id"),
                "page_name": account.get("page_name"),
            },
        }, on_conflict="user_id,platform,platform_user_id").execute()
        return RedirectResponse(f"{frontend_url}/?instagram_connected={quote(account.get('username') or 'connected')}")
    except Exception as exc:
        return RedirectResponse(f"{frontend_url}/?instagram_error={quote(str(exc))}")

@app.get("/api/instagram/account")
def instagram_account(authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    result = admin_client().table("social_accounts").select(
        "id,account_name,platform_user_id,status,metadata,created_at"
    ).eq("user_id", str(user.id)).eq("platform", "instagram").execute()
    return {"accounts": result.data or []}

@app.post("/api/instagram/sync")
def instagram_sync(authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    db = admin_client()
    account_result = db.table("social_accounts").select(
        "id,platform_user_id,access_token_encrypted,metadata"
    ).eq("user_id", str(user.id)).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Instagram account is not connected")
    account = account_result.data[0]
    token = decrypt_token(account["access_token_encrypted"])
    from .instagram import list_media, list_comments
    media = list_media(account["platform_user_id"], token, 25)
    synced_comments = 0
    for item in media:
        content = db.table("content_items").upsert({
            "social_account_id": account["id"],
            "platform_content_id": item["id"],
            "content_type": "reel" if item.get("media_product_type") == "REELS" else "post",
            "caption": item.get("caption"),
            "media_url": item.get("media_url") or item.get("thumbnail_url"),
            "permalink": item.get("permalink"),
            "published_at": item.get("timestamp"),
        }, on_conflict="social_account_id,platform_content_id").execute()
        content_id = content.data[0]["id"]
        for comment in list_comments(item["id"], token, 50):
            db.table("comments").upsert({
                "content_item_id": content_id,
                "social_account_id": account["id"],
                "platform_comment_id": comment["id"],
                "parent_comment_id": (comment.get("parent") or {}).get("id"),
                "commenter_platform_id": (comment.get("from") or {}).get("id"),
                "commenter_username": comment.get("username"),
                "commenter_name": (comment.get("from") or {}).get("name"),
                "body": comment.get("text") or "",
                "status": "new",
                "metadata": {"like_count": comment.get("like_count", 0)},
                "published_at": comment.get("timestamp"),
            }, on_conflict="social_account_id,platform_comment_id").execute()
            synced_comments += 1
    return {"media_synced": len(media), "comments_synced": synced_comments}

