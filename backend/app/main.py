import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
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

def verify_meta_signed_request(signed_request: str) -> dict:
    """Verify Meta signed_request using the Instagram app secret."""
    secret = os.getenv("INSTAGRAM_APP_SECRET") or os.getenv("META_APP_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="Instagram app secret is not configured")
    try:
        encoded_sig, encoded_payload = signed_request.split(".", 1)
        sig = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
        payload_bytes = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        expected = hmac.new(secret.encode(), encoded_payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("invalid signature")
        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("algorithm", "HMAC-SHA256").upper() != "HMAC-SHA256":
            raise ValueError("unsupported signature algorithm")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid signed_request: {exc}")

def meta_form_value(body: bytes, name: str) -> str | None:
    values = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True).get(name)
    return values[0] if values else None

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
            "token_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(account["token_expires_in"]))).isoformat() if account.get("token_expires_in") else None,
            "status": "connected",
            "metadata": {
                "username": account.get("username"),
                "profile_picture_url": account.get("profile_picture_url"),
            },
        }, on_conflict="user_id,platform,platform_user_id").execute()
        return RedirectResponse(f"{frontend_url}/?instagram_connected={quote(account.get('username') or 'connected')}")
    except Exception as exc:
        return RedirectResponse(f"{frontend_url}/?instagram_error={quote(str(exc))}")

@app.post("/api/instagram/deauthorize")
async def instagram_deauthorize(request: Request):
    """Handle Meta Instagram deauthorization callback."""
    signed_request = meta_form_value(await request.body(), "signed_request")
    if not signed_request:
        raise HTTPException(status_code=400, detail="Missing signed_request")
    payload = verify_meta_signed_request(signed_request)
    platform_user_id = str(payload.get("user_id") or "")
    if not platform_user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    admin_client().table("social_accounts").update({
        "status": "deauthorized",
        "access_token_encrypted": None,
    }).eq("platform", "instagram").eq("platform_user_id", platform_user_id).execute()
    return {"status": "ok"}

@app.post("/api/instagram/data-deletion")
async def instagram_data_deletion(request: Request):
    """Handle Meta data deletion callback and erase connected Instagram data."""
    signed_request = meta_form_value(await request.body(), "signed_request")
    if not signed_request:
        raise HTTPException(status_code=400, detail="Missing signed_request")
    payload = verify_meta_signed_request(signed_request)
    platform_user_id = str(payload.get("user_id") or "")
    if not platform_user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    db = admin_client()
    accounts = db.table("social_accounts").select("id").eq("platform", "instagram").eq("platform_user_id", platform_user_id).execute()
    account_ids = [row["id"] for row in (accounts.data or [])]
    for account_id in account_ids:
        content = db.table("content_items").select("id").eq("social_account_id", account_id).execute()
        content_ids = [row["id"] for row in (content.data or [])]
        if content_ids:
            db.table("comments").delete().in_("content_item_id", content_ids).execute()
        db.table("content_items").delete().eq("social_account_id", account_id).execute()
    for table in ("comment_replies", "ai_analyses", "creator_personality", "commenter_memory", "reply_rules", "agent_runs"):
        if account_ids:
            db.table(table).delete().in_("social_account_id", account_ids).execute()
    if account_ids:
        db.table("social_accounts").delete().in_("id", account_ids).execute()

    secret = os.getenv("INSTAGRAM_APP_SECRET") or os.getenv("META_APP_SECRET")
    confirmation_code = hmac.new(secret.encode(), f"{platform_user_id}:{int(time.time())}".encode(), hashlib.sha256).hexdigest()[:32]
    base_url = os.getenv("META_REDIRECT_URI", "").rsplit("/api/instagram/callback", 1)[0]
    status_url = f"{base_url}/api/instagram/data-deletion/status?code={quote(confirmation_code)}"
    return JSONResponse({"url": status_url, "confirmation_code": confirmation_code})

@app.get("/api/instagram/data-deletion/status")
def instagram_data_deletion_status(code: str | None = None):
    if not code:
        raise HTTPException(status_code=400, detail="Missing confirmation code")
    return {"confirmation_code": code, "status": "completed"}

@app.get("/api/instagram/account")
def instagram_account(authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    result = admin_client().table("social_accounts").select(
        "id,account_name,platform_user_id,status,metadata,created_at"
    ).eq("user_id", str(user.id)).eq("platform", "instagram").execute()
    return {"accounts": result.data or []}

@app.get("/api/instagram/debug-comments")
def instagram_debug_comments(authorization: str | None = Header(default=None)):
    """Return sanitized diagnostics for comment reads across recent Instagram media."""
    user = authenticated_user(authorization)
    db = admin_client()
    account_result = db.table("social_accounts").select(
        "id,platform_user_id,access_token_encrypted"
    ).eq("user_id", str(user.id)).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Instagram account is not connected")

    account = account_result.data[0]
    token = decrypt_token(account["access_token_encrypted"])
    from .instagram import list_media

    media = list_media(account["platform_user_id"], token, 50)
    diagnostics = []

    import requests
    for item in media:
        media_id = item["id"]
        response = requests.get(
            f"https://graph.instagram.com/{media_id}/comments",
            params={
                "fields": "id,text,timestamp,like_count",
                "limit": 50,
                "access_token": token,
            },
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        error = payload.get("error") if isinstance(payload, dict) else None
        rows = payload.get("data") or [] if isinstance(payload, dict) else []
        diagnostics.append({
            "media_id": media_id,
            "caption": (item.get("caption") or "")[:100],
            "http_status": response.status_code,
            "comment_count": len(rows),
            "error_type": error.get("type") if isinstance(error, dict) else None,
            "error_code": error.get("code") if isinstance(error, dict) else None,
            "error_message": error.get("message") if isinstance(error, dict) else None,
        })

    return {
        "media_count": len(media),
        "total_comments_returned": sum(x["comment_count"] for x in diagnostics),
        "media_with_comments": [x for x in diagnostics if x["comment_count"] > 0],
        "errors": [x for x in diagnostics if x["error_message"]],
        "checked_media": diagnostics,
    }

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
    media = list_media(account["platform_user_id"], token, 50)
    synced_comments = 0
    for item in media:
        content = db.table("content_items").upsert({
            "social_account_id": account["id"],
            "platform_content_id": item["id"],
            "content_type": "reel" if item.get("media_product_type") == "REELS" else "post",
            "caption": item.get("caption"),
            "media_url": item.get("media_url") or item.get("thumbnail_url"),
            "published_at": item.get("timestamp"),
        }, on_conflict="social_account_id,platform_content_id").execute()
        content_id = content.data[0]["id"]
        for comment in list_comments(item["id"], token, 50):
            parent_platform_id = (comment.get("parent") or {}).get("id")
            parent_local_id = None
            if parent_platform_id:
                parent_result = db.table("comments").select("id").eq(
                    "social_account_id", account["id"]
                ).eq("platform_comment_id", parent_platform_id).limit(1).execute()
                if parent_result.data:
                    parent_local_id = parent_result.data[0]["id"]

            db.table("comments").upsert({
                "content_item_id": content_id,
                "social_account_id": account["id"],
                "platform_comment_id": comment["id"],
                "parent_comment_id": parent_local_id,
                "commenter_platform_id": (comment.get("from") or {}).get("id"),
                "commenter_username": comment.get("username"),
                "commenter_name": (comment.get("from") or {}).get("name"),
                "body": comment.get("text") or "",
                "status": "new",
                "metadata": {"like_count": comment.get("like_count", 0)},
                "platform_created_at": comment.get("timestamp"),
            }, on_conflict="social_account_id,platform_comment_id").execute()
            synced_comments += 1
    return {"media_synced": len(media), "comments_synced": synced_comments}

