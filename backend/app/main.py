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
from .instagram import authorization_url, complete_oauth, download_media
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

def _personality_text(row: dict | None) -> str:
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


def _memory_text(row: dict | None) -> str:
    if not row:
        return "No previous relationship with this commenter."
    facts = row.get("facts") or []
    return (
        f"Returning commenter. Interaction count: {row.get('interaction_count') or 0}. "
        f"Summary: {row.get('summary') or 'No summary yet'}. "
        f"Known facts: {', '.join(str(x) for x in facts[-10:])}. "
        f"Last interaction: {row.get('last_interaction_at') or 'unknown'}."
    )


def _extract_local_memory(comment: str) -> list[str]:
    """Extract only lightweight, useful conversation facts without inventing details."""
    import re
    facts = []
    text = comment.strip()
    patterns = [
        (r"\bmy dog(?:'s| is| named| called)\s+([A-Za-z0-9_-]{2,30})", "Their dog is {0}."),
        (r"\bmy (?:puppy|pet)(?:'s| is| named| called)\s+([A-Za-z0-9_-]{2,30})", "Their pet is {0}."),
        (r"\bmy dog is a\s+([A-Za-z0-9 -]{2,40})", "Their dog breed is {0}."),
        (r"\b(?:i am|i'm)\s+(\d{1,3})\s*(?:years? old)?\b", "They mentioned age {0}."),
    ]
    for pattern, template in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,!?:;")
            if value:
                facts.append(template.format(value))
    return facts[:3]


def _update_commenter_memory(
    db, user_id: str, comment_row: dict, reply_text: str | None = None
):
    """Upsert lightweight memory for a commenter and retain recent facts."""
    commenter_id = comment_row.get("commenter_platform_id")
    if not commenter_id:
        return False

    account_id = comment_row["social_account_id"]
    result = db.table("commenter_memory").select(
        "id,commenter_name,summary,facts,interaction_count"
    ).eq("user_id", user_id).eq(
        "social_account_id", account_id
    ).eq("commenter_platform_id", str(commenter_id)).limit(1).execute()
    existing = result.data[0] if result.data else None

    facts = list((existing or {}).get("facts") or [])
    for fact in _extract_local_memory(comment_row.get("body") or ""):
        if fact not in facts:
            facts.append(fact)
    facts = facts[-20:]

    old_count = int((existing or {}).get("interaction_count") or 0)
    payload = {
        "user_id": user_id,
        "social_account_id": account_id,
        "commenter_platform_id": str(commenter_id),
        "commenter_name": comment_row.get("commenter_name"),
        "summary": (existing or {}).get("summary")
            or "Returning Instagram commenter; conversation history is being learned.",
        "facts": facts,
        "interaction_count": old_count + 1,
        "last_interaction_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing:
        db.table("commenter_memory").update(payload).eq("id", existing["id"]).execute()
    else:
        db.table("commenter_memory").insert(payload).execute()
    return True


def _get_comment_context(db, user_id: str, comment_id: str | None):
    if not comment_id:
        return None, None, None
    comment_result = db.table("comments").select(
        "id,social_account_id,commenter_platform_id,commenter_name,commenter_username,body,"
        "content_items(id,platform_content_id,content_type,caption,transcript,media_url)"
    ).eq("id", comment_id).limit(1).execute()
    if not comment_result.data:
        raise HTTPException(status_code=404, detail="Comment not found")

    row = comment_result.data[0]
    account_result = db.table("social_accounts").select("id").eq(
        "id", row["social_account_id"]
    ).eq("user_id", user_id).eq("platform", "instagram").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Comment does not belong to your Instagram account")

    personality_result = db.table("creator_personality").select(
        "tone,style_instructions,sample_replies,common_phrases,emoji_frequency,average_reply_length,version"
    ).eq("user_id", user_id).limit(1).execute()

    memory = None
    if row.get("commenter_platform_id"):
        memory_result = db.table("commenter_memory").select(
            "commenter_name,summary,facts,interaction_count,last_interaction_at"
        ).eq("user_id", user_id).eq(
            "social_account_id", row["social_account_id"]
        ).eq("commenter_platform_id", str(row["commenter_platform_id"])).limit(1).execute()
        memory = memory_result.data[0] if memory_result.data else None

    personality = personality_result.data[0] if personality_result.data else None
    content = row.get("content_items") or {}
    return row, personality, memory, content


@app.post("/api/replies/generate")
def replies(request: ReplyRequest, authorization: str | None = Header(default=None)):
    user = authenticated_user(authorization)
    db = admin_client()

    try:
        comment_row, personality, memory, content = _get_comment_context(
            db, str(user.id), request.comment_id
        )
        if comment_row:
            request = request.model_copy(update={
                "comment": comment_row.get("body") or request.comment,
                "content_context": (
                    request.content_context
                    or content.get("caption")
                    or content.get("transcript")
                    or ""
                ),
                "creator_style": _personality_text(personality),
                "commenter_memory": _memory_text(memory),
            })

        media_bytes = None
        media_mime_type = None
        video_download_error = None

        # Analyze a Reel with Gemini on the first request, then persist the
        # generated visual summary in content_items.transcript for reuse.
        if comment_row and content.get("content_type") == "reel" and not (content.get("transcript") or "").strip():
            account_result = db.table("social_accounts").select(
                "access_token_encrypted"
            ).eq("id", comment_row["social_account_id"]).eq(
                "user_id", str(user.id)
            ).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
            if account_result.data and content.get("media_url"):
                try:
                    token = decrypt_token(account_result.data[0]["access_token_encrypted"])
                    media_bytes, media_mime_type = download_media(
                        content["media_url"],
                        token,
                    )
                except Exception as exc:
                    video_download_error = str(exc)[:300]

        if content.get("transcript"):
            request = request.model_copy(update={
                "content_context": (
                    request.content_context
                    + "\nVIDEO UNDERSTANDING:\n"
                    + str(content.get("transcript"))
                ).strip()
            })

        result = generate_reply(
            request,
            media_bytes=media_bytes,
            mime_type=media_mime_type,
        )

        video_summary = (result.get("video_summary") or "").strip()
        if comment_row and video_summary and not (content.get("transcript") or "").strip():
            db.table("content_items").update({
                "transcript": video_summary,
            }).eq("id", content["id"]).execute()

        if comment_row:
            db.table("ai_analyses").insert({
                "comment_id": comment_row["id"],
                "intent": result.get("intent"),
                "sentiment": result.get("sentiment"),
                "risk_level": result.get("risk_level", "low"),
                "confidence": result.get("confidence"),
                "context": {
                    "content_caption": content.get("caption"),
                    "video_understanding_used": bool(media_bytes) or bool(content.get("transcript")),
                    "video_download_error": video_download_error,
                    "creator_personality_version": (personality or {}).get("version", 1),
                    "commenter_interaction_count": (memory or {}).get("interaction_count", 0),
                },
                "reasoning_summary": result.get("reason"),
            }).execute()

        return {
            **result,
            "creator_personality_used": bool(personality),
            "commenter_memory_used": bool(memory),
            "commenter_interaction_count": (memory or {}).get("interaction_count", 0),
            "video_understanding_used": bool(media_bytes) or bool(content.get("transcript")),
            "video_download_error": video_download_error,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/comments/{comment_id}/approve-reply")
def approve_reply(
    comment_id: str,
    request: dict,
    authorization: str | None = Header(default=None),
):
    """Publish an approved reply to Instagram and mark the comment as replied."""
    user = authenticated_user(authorization)
    reply_text = str(request.get("reply") or "").strip()
    if not reply_text:
        raise HTTPException(status_code=400, detail="Reply text is required")
    if len(reply_text) > 1000:
        raise HTTPException(status_code=400, detail="Reply is too long")

    db = admin_client()
    result = db.table("comments").select(
        "id,social_account_id,platform_comment_id,status,body,metadata"
    ).eq("id", comment_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment_row = result.data[0]
    account_result = db.table("social_accounts").select(
        "id,platform_user_id,access_token_encrypted"
    ).eq("id", comment_row["social_account_id"]).eq(
        "user_id", str(user.id)
    ).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Connected Instagram account not found")

    account = account_result.data[0]
    token = decrypt_token(account["access_token_encrypted"])

    existing_metadata = comment_row.get("metadata") or {}
    if not isinstance(existing_metadata, dict):
        existing_metadata = {}

    try:
        from .instagram import reply_to_comment
        instagram_result = reply_to_comment(
            comment_row["platform_comment_id"],
            token,
            reply_text,
        )
    except Exception as exc:
        failed_metadata = {
            **existing_metadata,
            "reply_error": str(exc)[:500],
            "last_reply_attempt": datetime.now(timezone.utc).isoformat(),
        }
        db.table("comments").update({
            "status": "failed",
            "metadata": failed_metadata,
        }).eq("id", comment_id).execute()
        raise HTTPException(status_code=502, detail=f"Instagram reply failed: {exc}")

    replied_metadata = {
        **existing_metadata,
        "reply_text": reply_text,
        "instagram_reply": instagram_result,
        "replied_at": datetime.now(timezone.utc).isoformat(),
    }
    db.table("comments").update({
        "status": "replied",
        "metadata": replied_metadata,
    }).eq("id", comment_id).execute()

    db.table("comment_replies").insert({
        "comment_id": comment_id,
        "reply_body": reply_text,
        "source": "human",
        "status": "published",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "platform_reply_id": str(
            instagram_result.get("id") or instagram_result.get("reply_id") or ""
        ) or None,
    }).execute()

    # Learn from the approved interaction.
    _update_commenter_memory(db, str(user.id), comment_row, reply_text)

    personality_result = db.table("creator_personality").select(
        "id,tone,style_instructions,sample_replies,common_phrases,emoji_frequency,average_reply_length,version"
    ).eq("user_id", str(user.id)).limit(1).execute()
    existing = personality_result.data[0] if personality_result.data else None
    samples = list((existing or {}).get("sample_replies") or [])
    phrases = list((existing or {}).get("common_phrases") or [])
    samples.append(reply_text)
    if len(samples) > 20:
        samples = samples[-20:]

    for phrase in ("❤️", "😂", "😊", "😄", "🥰", "🐶"):
        if phrase in reply_text and phrase not in phrases:
            phrases.append(phrase)
    if len(phrases) > 20:
        phrases = phrases[-20:]

    emoji_count = sum(1 for ch in reply_text if ord(ch) > 0x1F000)
    old_avg = int((existing or {}).get("average_reply_length") or len(reply_text))
    old_count = len((existing or {}).get("sample_replies") or [])
    new_avg = round(((old_avg * old_count) + len(reply_text)) / max(old_count + 1, 1))

    from .agent import learn_creator_personality
    learned = learn_creator_personality(samples)

    personality_payload = {
        "user_id": str(user.id),
        "tone": learned.get("tone") or "casual",
        "style_instructions": learned.get("style_instructions")
            or "Short, natural, warm, playful creator voice. Avoid customer-service language.",
        "sample_replies": samples,
        "common_phrases": learned.get("common_phrases") or phrases,
        "emoji_frequency": learned.get("emoji_frequency", round(
            ((existing or {}).get("emoji_frequency") or 0.2) * 0.8
            + (1 if emoji_count else 0) * 0.2, 3
        )),
        "average_reply_length": learned.get("average_reply_length") or new_avg,
        "version": int((existing or {}).get("version") or 0) + 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if existing:
        db.table("creator_personality").update(personality_payload).eq(
            "id", existing["id"]
        ).execute()
    else:
        db.table("creator_personality").insert(personality_payload).execute()

    return {
        "success": True,
        "comment_id": comment_id,
        "reply": reply_text,
        "instagram": instagram_result,
        "memory_updated": bool(commenter_id),
        "personality_updated": True,
    }

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
                "granted_permissions": account.get("permissions", []),
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


@app.get("/api/comments/{comment_id}/memory")
def get_comment_memory(
    comment_id: str,
    authorization: str | None = Header(default=None),
):
    user = authenticated_user(authorization)
    db = admin_client()
    result = db.table("comments").select(
        "id,social_account_id,commenter_platform_id,commenter_name,commenter_username"
    ).eq("id", comment_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Comment not found")
    row = result.data[0]
    account = db.table("social_accounts").select("id").eq(
        "id", row["social_account_id"]
    ).eq("user_id", str(user.id)).eq("platform", "instagram").limit(1).execute()
    if not account.data:
        raise HTTPException(status_code=404, detail="Comment does not belong to your Instagram account")

    memory = None
    if row.get("commenter_platform_id"):
        result = db.table("commenter_memory").select(
            "commenter_name,summary,facts,interaction_count,last_interaction_at"
        ).eq("user_id", str(user.id)).eq(
            "social_account_id", row["social_account_id"]
        ).eq("commenter_platform_id", str(row["commenter_platform_id"])).limit(1).execute()
        memory = result.data[0] if result.data else None

    return {
        "commenter_username": row.get("commenter_username"),
        "commenter_name": row.get("commenter_name"),
        "memory": memory,
    }

@app.get("/api/comments")
def list_comments_inbox(
    authorization: str | None = Header(default=None),
    status: str = "new",
    limit: int = 50,
):
    """Return the authenticated user's Instagram comments for the review inbox."""
    user = authenticated_user(authorization)
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    allowed_statuses = {"new", "pending", "approved", "replied", "skipped", "failed", "needs_review", "all"}
    if status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Invalid comment status")

    db = admin_client()
    account_result = db.table("social_accounts").select("id,account_name,platform_user_id").eq(
        "user_id", str(user.id)
    ).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Instagram account is not connected")

    account_id = account_result.data[0]["id"]
    query = db.table("comments").select(
        "id,content_item_id,platform_comment_id,commenter_platform_id,commenter_name,"
        "commenter_username,body,status,metadata,platform_created_at,created_at,"
        "content_items(id,caption,media_url,published_at)"
    ).eq("social_account_id", account_id).order("platform_created_at", desc=True).limit(limit)

    if status != "all":
        query = query.eq("status", status)

    result = query.execute()
    rows = result.data or []
    return {
        "comments": rows,
        "count": len(rows),
        "status": status,
    }

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


@app.get("/api/instagram/debug-permissions")
def instagram_debug_permissions(authorization: str | None = Header(default=None)):
    """Report the permissions requested by this app's Instagram Login flow.

    Instagram Login tokens do not expose a /me/permissions edge on graph.instagram.com,
    so token introspection is not available through this API path.
    """
    user = authenticated_user(authorization)
    db = admin_client()
    account_result = db.table("social_accounts").select(
        "access_token_encrypted,metadata,status"
    ).eq("user_id", str(user.id)).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Instagram account is not connected")

    required = [
        "instagram_business_basic",
        "instagram_business_manage_comments",
        "instagram_business_manage_messages",
    ]
    metadata = account_result.data[0].get("metadata") or {}
    oauth_permissions = metadata.get("granted_permissions") or []

    return {
        "source": "Instagram Login OAuth",
        "token_introspection_available": False,
        "message": "Instagram Login does not expose /me/permissions on graph.instagram.com. Permission access must be verified through the OAuth consent/app configuration and endpoint behavior.",
        "requested_permissions": required,
        "oauth_response_permissions": oauth_permissions,
        "comments_permission_configured": "instagram_business_manage_comments" in required,
    }

@app.get("/api/instagram/debug-comment-test")
def instagram_debug_comment_test(authorization: str | None = Header(default=None)):
    """Check the comment edge on every Instagram media item and summarize API behavior."""
    user = authenticated_user(authorization)
    db = admin_client()
    account_result = db.table("social_accounts").select(
        "platform_user_id,access_token_encrypted"
    ).eq("user_id", str(user.id)).eq("platform", "instagram").eq("status", "connected").limit(1).execute()
    if not account_result.data:
        raise HTTPException(status_code=404, detail="Instagram account is not connected")

    account = account_result.data[0]
    token = decrypt_token(account["access_token_encrypted"])
    from .instagram import list_media
    media = list_media(account["platform_user_id"], token, 50)

    import requests
    results = []
    status_counts = {}

    for item in media:
        media_id = item["id"]
        params = {
            "fields": "id,text,timestamp,like_count",
            "limit": 50,
            "access_token": token,
        }
        response = requests.get(
            f"https://graph.instagram.com/{media_id}/comments",
            params=params,
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        rows = payload.get("data") or [] if isinstance(payload, dict) else []
        error = payload.get("error") if isinstance(payload, dict) else None
        status_counts[str(response.status_code)] = status_counts.get(str(response.status_code), 0) + 1

        results.append({
            "media_id": media_id,
            "media_type": item.get("media_type"),
            "media_product_type": item.get("media_product_type"),
            "timestamp": item.get("timestamp"),
            "caption": (item.get("caption") or "")[:120],
            "permalink": item.get("permalink"),
            "http_status": response.status_code,
            "comment_count": len(rows),
            "has_paging": bool(payload.get("paging")) if isinstance(payload, dict) else False,
            "error_type": error.get("type") if isinstance(error, dict) else None,
            "error_code": error.get("code") if isinstance(error, dict) else None,
            "error_message": error.get("message") if isinstance(error, dict) else None,
        })

    total_edge_comments = sum(row["comment_count"] for row in results)
    with_comments = [row for row in results if row["comment_count"] > 0]
    errors = [row for row in results if row["error_message"]]

    # Run one field-expansion check against the newest media. This response nests
    # comments under the "comments" field rather than at the top-level "data".
    expanded = None
    if media:
        newest = media[0]
        response = requests.get(
            f"https://graph.instagram.com/{newest['id']}",
            params={
                "fields": "id,media_type,media_product_type,comments.limit(10){id,text,timestamp,like_count}",
                "access_token": token,
            },
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        nested = ((payload.get("comments") or {}).get("data") or []) if isinstance(payload, dict) else []
        error = payload.get("error") if isinstance(payload, dict) else None
        expanded = {
            "media_id": newest["id"],
            "http_status": response.status_code,
            "comment_count": len(nested),
            "error_message": error.get("message") if isinstance(error, dict) else None,
            "error_code": error.get("code") if isinstance(error, dict) else None,
        }

    return {
        "media_count": len(results),
        "http_status_counts": status_counts,
        "total_direct_edge_comments": total_edge_comments,
        "media_with_comments": with_comments[:20],
        "error_count": len(errors),
        "errors": errors[:20],
        "newest_media": results[0] if results else None,
        "expanded_newest_media": expanded,
    }


@app.post("/api/instagram/debug-manual-token")
def instagram_debug_manual_token(request: dict, authorization: str | None = Header(default=None)):
    """One-time diagnostic for a token generated in Meta App Dashboard.

    The supplied token is used only in memory for this request and is never
    written to Supabase, logs, or the social_accounts table.
    """
    authenticated_user(authorization)
    token = str(request.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Missing access_token")

    import requests
    try:
        profile_response = requests.get(
            f"https://graph.instagram.com/me",
            params={
                "fields": "id,user_id,username,name",
                "access_token": token,
            },
            timeout=30,
        )
        try:
            profile = profile_response.json()
        except ValueError:
            profile = {}

        if profile_response.status_code >= 400 or profile.get("error"):
            error = profile.get("error") or {}
            raise HTTPException(
                status_code=400,
                detail=f"Meta token rejected: {error.get('message') or 'invalid access token'}"
            )

        ig_user_id = profile.get("user_id") or profile.get("id")
        if not ig_user_id:
            raise HTTPException(status_code=400, detail="Meta token did not return an Instagram user ID")

        media_response = requests.get(
            f"https://graph.instagram.com/{ig_user_id}/media",
            params={
                "fields": "id,caption,media_type,media_product_type,timestamp,permalink",
                "limit": 1,
                "access_token": token,
            },
            timeout=30,
        )
        try:
            media_payload = media_response.json()
        except ValueError:
            media_payload = {}
        if media_response.status_code >= 400 or media_payload.get("error"):
            error = media_payload.get("error") or {}
            raise HTTPException(
                status_code=400,
                detail=f"Meta token can read the profile but media request failed: {error.get('message') or 'unknown error'}"
            )

        media_rows = media_payload.get("data") or []
        if not media_rows:
            return {
                "username": profile.get("username"),
                "ig_user_id": str(ig_user_id),
                "media_count": 0,
                "comment_count": 0,
                "comment_preview": [],
                "latest_permalink": None,
            }

        latest = media_rows[0]
        comments_response = requests.get(
            f"https://graph.instagram.com/{latest['id']}/comments",
            params={
                "fields": "id,text,timestamp,like_count",
                "limit": 10,
                "access_token": token,
            },
            timeout=30,
        )
        try:
            comments_payload = comments_response.json()
        except ValueError:
            comments_payload = {}
        if comments_response.status_code >= 400 or comments_payload.get("error"):
            error = comments_payload.get("error") or {}
            raise HTTPException(
                status_code=400,
                detail=f"Media is readable but comments request failed: {error.get('message') or 'unknown error'}"
            )

        rows = comments_payload.get("data") or []
        return {
            "username": profile.get("username"),
            "ig_user_id": str(ig_user_id),
            "media_count": len(media_rows),
            "comment_count": len(rows),
            "comment_preview": [(row.get("text") or "")[:100] for row in rows[:3]],
            "latest_permalink": latest.get("permalink"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Meta token diagnostic failed: {exc}")

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

