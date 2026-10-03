import os
from urllib.parse import urlencode
import requests
from .security import create_oauth_state, verify_oauth_state, encrypt_token

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v26.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
FACEBOOK_OAUTH = "https://www.facebook.com/{}/dialog/oauth".format(GRAPH_VERSION)

SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_manage_comments",
]

def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value

def authorization_url(user_id: str) -> str:
    params = {
        "client_id": _require("META_APP_ID"),
        "redirect_uri": _require("META_REDIRECT_URI"),
        "state": create_oauth_state(user_id),
        "scope": ",".join(SCOPES),
        "response_type": "code",
    }
    return f"{FACEBOOK_OAUTH}?{urlencode(params)}"

def _get(path: str, token: str, params=None):
    response = requests.get(f"{GRAPH_BASE}/{path.lstrip('/')}", params={**(params or {}), "access_token": token}, timeout=30)
    data = response.json()
    if response.status_code >= 400 or "error" in data:
        raise RuntimeError(data.get("error", {}).get("message", f"Meta API error {response.status_code}"))
    return data

def exchange_code(code: str) -> str:
    params = {
        "client_id": _require("META_APP_ID"),
        "client_secret": _require("META_APP_SECRET"),
        "redirect_uri": _require("META_REDIRECT_URI"),
        "code": code,
    }
    response = requests.get(f"{GRAPH_BASE}/oauth/access_token", params=params, timeout=30)
    data = response.json()
    if response.status_code >= 400 or "access_token" not in data:
        raise RuntimeError(data.get("error", {}).get("message", "Meta OAuth exchange failed"))
    return data["access_token"]

def discover_instagram_account(user_token: str) -> dict:
    pages = _get("me/accounts", user_token, {"fields": "id,name,access_token,tasks,instagram_business_account"})
    for page in pages.get("data", []):
        ig = page.get("instagram_business_account")
        if not ig:
            continue
        ig_id = ig["id"]
        profile = _get(ig_id, page["access_token"], {"fields": "id,username,name,profile_picture_url"})
        return {
            "page_id": page["id"],
            "page_name": page.get("name"),
            "page_access_token": page["access_token"],
            "ig_user_id": ig_id,
            "username": profile.get("username"),
            "name": profile.get("name"),
            "profile_picture_url": profile.get("profile_picture_url"),
        }
    raise RuntimeError("No Instagram Professional account linked to a Facebook Page you can manage.")

def complete_oauth(state: str, code: str) -> tuple[str, dict]:
    user_id = verify_oauth_state(state)
    user_token = exchange_code(code)
    account = discover_instagram_account(user_token)
    account["user_id"] = user_id
    account["encrypted_token"] = encrypt_token(account["page_access_token"])
    del account["page_access_token"]
    return user_id, account

def list_media(ig_user_id: str, token: str, limit: int = 25) -> list:
    data = _get(f"{ig_user_id}/media", token, {
        "fields": "id,caption,media_type,media_product_type,timestamp,permalink,thumbnail_url,media_url",
        "limit": limit,
    })
    return data.get("data", [])

def list_comments(media_id: str, token: str, limit: int = 50) -> list:
    data = _get(f"{media_id}/comments", token, {
        "fields": "id,text,username,timestamp,from,like_count,parent",
        "limit": limit,
    })
    return data.get("data", [])

def reply_to_comment(comment_id: str, token: str, message: str) -> dict:
    response = requests.post(
        f"{GRAPH_BASE}/{comment_id}/replies",
        data={"message": message, "access_token": token},
        timeout=30,
    )
    data = response.json()
    if response.status_code >= 400 or "error" in data:
        raise RuntimeError(data.get("error", {}).get("message", f"Meta API error {response.status_code}"))
    return data
