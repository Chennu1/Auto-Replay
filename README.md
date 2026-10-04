# Auto-Replay

AI-powered Instagram + YouTube comment reply agent.

## MVP
- Connect social accounts (OAuth adapters are next)
- Store posts/videos and comments in Supabase
- Analyze comment intent, sentiment and risk
- Generate creator-style replies
- Autonomous safe replies for ordinary comments; human approval only for sensitive or very-low-confidence comments
- Creator personality + commenter memory

Autonomous Instagram replies run every minute. Sensitive or very-low-confidence comments are routed to human review; approved comments can be published from the review queue.

## Structure
- `backend/` FastAPI API and AI reply engine
- `frontend/` Next.js dashboard
- `docs/` product and integration notes
