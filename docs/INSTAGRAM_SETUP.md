# Instagram setup

Auto-Replay uses Meta's Instagram API with Facebook Login for the first integration. This path supports Instagram Professional accounts (Creator/Business) linked to a Facebook Page and provides the permissions needed to read media/comments and reply to comments.

## Meta app

Create a Meta app and configure Facebook Login/OAuth in the current Meta developer dashboard.

Set the OAuth redirect URI to:

http://localhost:8000/api/instagram/callback

For this MVP, request:
- pages_show_list
- pages_read_engagement
- instagram_basic
- instagram_manage_comments

The current Graph API version is configurable through META_GRAPH_VERSION and defaults to v26.0.

## Local secrets

Never commit these values:
- META_APP_SECRET
- SUPABASE_SERVICE_ROLE_KEY
- TOKEN_ENCRYPTION_KEY
- OAUTH_STATE_SECRET

The Instagram Page access token is encrypted before it is stored in Supabase.

## Connect flow

1. Create/sign into the Auto-Replay account.
2. Click Connect Instagram.
3. Meta OAuth opens.
4. Approve the requested permissions.
5. Auto-Replay discovers the Page-linked Instagram Professional account.
6. The encrypted Page access token is stored server-side.
7. The dashboard shows the connected Instagram username.
8. Click Sync Instagram comments to import recent media and comments.

Auto-publishing remains disabled. The first production milestone is comment sync + AI suggestions + human approval.
