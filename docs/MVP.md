# MVP workflow

1. Social OAuth connection
2. Pull recent Instagram/YouTube comments
3. Store normalized comments in Supabase
4. Load content context + creator personality + commenter memory
5. Analyze intent, sentiment and risk
6. Generate three candidate replies
7. Human approves/edits/rejects
8. Publish through the platform adapter
9. Save reply + update commenter memory

Auto-publish remains off until reply quality is tuned on the creator's own accounts.
