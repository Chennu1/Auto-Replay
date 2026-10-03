import os
from urllib.parse import urlencode
import requests

from .security import create_oauth_state, verify_oauth_state, encrypt_token

INSTAGRAM_OAUTH = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_API_BASE = "https://graph.instagram.com"

SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
]


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _app_id() -> str:
    return os.getenv("INSTAGRAM_APP_ID") or _require("META_APP_ID")


def _app_secret() -> str:
    return os.getenv("INSTAGRAM_APP_SECRET") or _require("META_APP_SECRET")


def authorization_url(user_id: str) -> str:
    params = {
        "client_id": _app_id(),
        "redirect_uri": _require("META_REDIRECT_URI"),
        "state": create_oauth_state(user_id),
        "scope": ",".join(SCOPES),
        "response_type": "code",
    }
    return f"{INSTAGRAM_OAUTH}?{urlencode(params)}"


def _response_data(response: requests.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or "error_type" in data or "error" in data:
        message = (
            data.get("error_message")
            or data.get("error_description")
            or data.get("error", {}).get("message")
            or f"Instagram API error {response.status_code}"
        )
        raise RuntimeError(message)
    return data


def exchange_code(code: str) -> str:
    response = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "grant_type": "authorization_code",
            "redirect_uri": _require("META_REDIRECT_URI"),
            "code": code,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        try:
            error_data = response.json()
        except ValueError:
            error_data = {}
        error_type = error_data.get("error_type") or error_data.get("type") or "unknown"
        error_message = error_data.get("error_message") or error_data.get("error_description") or error_data.get("message") or "unknown"
        raise RuntimeError(
            f"Instagram OAuth code exchange failed (HTTP {response.status_code}, {error_type}): {error_message}"
        )
    data = _response_data(response)
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Instagram OAuth exchange did not return an access token")
    return token


def exchange_for_long_lived_token(short_lived_token: str) -> tuple[str, int | None]:
    response = requests.get(
        f"{INSTAGRAM_API_BASE}/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": _app_secret(),
            "access_token": short_lived_token,
        },
        timeout=30,
    )
    data = _response_data(response)
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Instagram long-lived token exchange did not return an access token")
    return token, data.get("expires_in")


def discover_instagram_account(token: str) -> dict:
    response = requests.get(
        f"{INSTAGRAM_API_BASE}/me",
        params={
            "fields": "id,user_id,username,name,profile_picture_url",
            "access_token": token,
        },
        timeout=30,
    )
    profile = _response_data(response)
    ig_user_id = profile.get("user_id") or profile.get("id")
    if not ig_user_id:
        raise RuntimeError("Instagram profile response did not contain a user ID")

    return {
        "ig_user_id": ig_user_id,
        "username": profile.get("username"),
        "name": profile.get("name"),
        "profile_picture_url": profile.get("profile_picture_url"),
    }


def complete_oauth(state: str, code: str) -> tuple[str, dict]:
    user_id = verify_oauth_state(state)
    short_lived_token = exchange_code(code)
    token, expires_in = exchange_for_long_lived_token(short_lived_token)
    account = discover_instagram_account(token)
    account["user_id"] = user_id
    account["encrypted_token"] = encrypt_token(token)
    account["token_expires_in"] = expires_in
    return user_id, account


def _get(path: str, token: str, params=None):
    response = requests.get(
        f"{INSTAGRAM_API_BASE}/{path.lstrip('/')}",
        params={**(params or {}), "access_token": token},
        timeout=30,
    )
    return _response_data(response)


def list_media(ig_user_id: str, token: str, limit: int = 25) -> list:
    data = _get(f"{ig_user_id}/media", token, {
        "fields": "id,caption,media_type,media_product_type,timestamp,permalink,thumbnail_url,media_url",
        "limit": limit,
    })
    return data.get("data", [])


def list_comments(media_id: str, token: str, limit: int = 50) -> list:
    # Keep the first comment read deliberately minimal. With Instagram Login,
    # commenter identity fields can be restricted even when comment moderation
    # itself is permitted. The comment text/timestamp/id are sufficient for the
    # ingestion pipeline and can be enriched separately when available.
    data = _get(f"{media_id}/comments", token, {
        "fields": "id,text,timestamp,like_count",
        "limit": min(limit, 50),
    })
    return data.get("data", [])


def reply_to_comment(comment_id: str, token: str, message: str) -> dict:
    response = requests.post(
        f"{INSTAGRAM_API_BASE}/{comment_id}/replies",
        data={"message": message, "access_token": token},
        timeout=30,
    )
    return _response_data(response)
