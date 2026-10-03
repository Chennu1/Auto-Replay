# Instagram setup

Auto-Replay uses Meta's **Instagram API with Instagram Login / Business Login for Instagram**.

## Current Meta configuration

The Meta app is configured with the **Manage messaging & content on Instagram** use case and these permissions:

- `instagram_business_basic`
- `instagram_business_manage_comments`
- `instagram_business_manage_messages`

The Instagram test account is `@thisismax_18`.

## OAuth redirect URI

Instagram Business Login requires a redirect URI that matches the URI registered in Meta exactly.

Meta will not accept the local callback:

```
http://localhost:8000/api/instagram/callback
```

For local development, expose the backend through a public HTTPS tunnel or deploy the backend to an HTTPS host. Example:

```
https://YOUR_PUBLIC_BACKEND_DOMAIN/api/instagram/callback
```

Set the exact same value in `META_REDIRECT_URI`.

## Token flow

Auto-Replay uses:

1. Instagram OAuth authorization at `instagram.com/oauth/authorize`.
2. Authorization-code exchange at `api.instagram.com/oauth/access_token`.
3. Exchange for a long-lived Instagram access token.
4. Encrypt the long-lived token before storing it in Supabase.
5. Use the token with the Instagram Graph API to read media/comments and reply to comments.

Never paste an access token into GitHub or chat.

## Local secrets

Never commit:

- `INSTAGRAM_APP_SECRET`
- `SUPABASE_SERVICE_ROLE_KEY`
- `TOKEN_ENCRYPTION_KEY`
- `OAUTH_STATE_SECRET`

## Webhooks

Keep the Meta dashboard's webhook subscription **Off** until Auto-Replay has a public HTTPS webhook endpoint. After deployment, configure the comment subscription and test real-time comment delivery.

## MVP behavior

Auto-publishing remains disabled. The first milestone is:

**comment sync → context/AI analysis → suggested reply → human approval → Instagram reply.**
