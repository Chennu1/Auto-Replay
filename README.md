# Auto-Replay

AI-powered Instagram + YouTube comment reply agent.

## MVP
- Connect social accounts (OAuth adapters are next)
- Store posts/videos and comments in Supabase
- Analyze comment intent, sentiment and risk
- Generate creator-style replies
- Human approval before publishing
- Creator personality + commenter memory

Auto-posting is intentionally disabled in the MVP.

## Structure
- `backend/` FastAPI API and AI reply engine
- `frontend/` Next.js dashboard
- `docs/` product and integration notes
