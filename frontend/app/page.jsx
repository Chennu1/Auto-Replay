"use client";
import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
);

const statusTabs = [
  ["new", "New"],
  ["needs_review", "Needs Review"],
  ["replied", "Replied"],
  ["all", "All"],
];

export default function Home() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [comment, setComment] = useState("");
  const [reply, setReply] = useState("");
  const [context, setContext] = useState("");
  const [result, setResult] = useState(null);
  const [account, setAccount] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [manualToken, setManualToken] = useState("");
  const [inbox, setInbox] = useState([]);
  const [inboxStatus, setInboxStatus] = useState("new");
  const [selectedComment, setSelectedComment] = useState(null);
  const [inboxLoading, setInboxLoading] = useState(false);
  const [memory, setMemory] = useState(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session) loadInbox(inboxStatus);
  }, [session, inboxStatus]);

  async function auth(mode) {
    setMessage("");
    const action = mode === "signup"
      ? supabase.auth.signUp({ email, password })
      : supabase.auth.signInWithPassword({ email, password });
    const { error } = await action;
    if (error) setMessage(error.message);
    else setMessage(mode === "signup" ? "Account created. Check your email if confirmation is enabled." : "Signed in.");
  }

  function apiBase() {
    return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  }

  async function loadInbox(status = inboxStatus) {
    if (!session) return;
    setInboxLoading(true);
    try {
      const res = await fetch(apiBase() + "/api/comments?status=" + encodeURIComponent(status) + "&limit=50", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Could not load comments.");
        return;
      }
      setInbox(data.comments || []);
      if (selectedComment && !data.comments?.some(item => item.id === selectedComment.id)) {
        setSelectedComment(null);
      }
    } catch (error) {
      setMessage("Could not reach Auto-Replay API.");
      console.error("Comments inbox failed:", error);
    } finally {
      setInboxLoading(false);
    }
  }

  async function connectInstagram() {
    setMessage("");
    const res = await fetch(apiBase() + "/api/instagram/connect", {
      headers: { Authorization: "Bearer " + session?.access_token }
    });
    const data = await res.json();
    if (!res.ok) return setMessage(data.detail || "Unable to start Instagram connection.");
    window.location.href = data.authorization_url;
  }

  async function loadAccount() {
    const res = await fetch(apiBase() + "/api/instagram/account", {
      headers: { Authorization: "Bearer " + session.access_token }
    });
    const data = await res.json();
    setAccount(data.accounts?.[0] || null);
  }

  async function checkPermissions() {
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/instagram/debug-permissions", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Permission check failed.");
        return;
      }
      setMessage(
        "Instagram permissions configured: " +
        (data.requested_permissions || []).join(", ")
      );
    } catch (error) {
      setMessage("Could not reach Auto-Replay API.");
      console.error("Instagram permission check failed:", error);
    } finally {
      setLoading(false);
    }
  }

  async function testComments() {
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/instagram/debug-comment-test", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Comment API test failed.");
        return;
      }
      const newest = data.newest_media || {};
      const expanded = data.expanded_newest_media || {};
      setMessage(
        "Comment API test | Media checked: " + (data.media_count ?? 0) +
        " | HTTP: " + JSON.stringify(data.http_status_counts || {}) +
        " | Direct comments: " + (data.total_direct_edge_comments ?? 0) +
        " | Newest Reel direct: " + (newest.comment_count ?? 0) +
        " | Expanded: " + (expanded.comment_count ?? 0) +
        (data.error_count ? " | API errors: " + data.error_count : "") +
        (newest.permalink ? " | Newest: " + newest.permalink : "")
      );
    } catch (error) {
      setMessage("Could not reach Auto-Replay API.");
      console.error("Instagram comment API test failed:", error);
    } finally {
      setLoading(false);
    }
  }

  async function syncInstagram() {
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/instagram/sync", {
        method: "POST",
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Sync failed.");
        return;
      }
      setMessage("Instagram sync complete: " + data.comments_synced + " comments synced.");
      await loadInbox(inboxStatus);
    } catch (error) {
      setMessage("Could not reach Auto-Replay API. Check Railway deployment/CORS.");
      console.error("Instagram sync request failed:", error);
    } finally {
      setLoading(false);
    }
  }

  async function testMetaGeneratedToken() {
    if (!manualToken.trim()) {
      setMessage("Paste the Meta-generated token first.");
      return;
    }
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/instagram/debug-manual-token", {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + session.access_token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ access_token: manualToken.trim() })
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Meta-generated token test failed.");
        return;
      }
      setMessage(
        "Meta-generated token test | @" + (data.username || "unknown") +
        " | Token account ID: " + (data.ig_user_id || "unknown") +
        " | Media checked: " + (data.media_count ?? 0) +
        " | Latest media comments: " + (data.comment_count ?? 0)
      );
    } catch (error) {
      setMessage("Could not reach Auto-Replay API.");
    } finally {
      setManualToken("");
      setLoading(false);
    }
  }

  function selectForReply(item) {
    setSelectedComment(item);
    setComment(item.body || "");
    setReply("");
    setContext(item.content_items?.caption || "");
    setResult(null);
    setMemory(null);
    setMessage("");
  }

  async function loadMemory(commentId) {
    try {
      const res = await fetch(
        apiBase() + "/api/comments/" + encodeURIComponent(commentId) + "/memory",
        { headers: { Authorization: "Bearer " + session.access_token } }
      );
      const data = await res.json();
      if (res.ok) setMemory(data.memory || null);
    } catch (error) {
      console.error("Memory load failed:", error);
    }
  }

  async function generate() {
    setLoading(true);
    setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/replies/generate", {
        method: "POST",
        headers: {
          "Content-Type":"application/json",
          Authorization: "Bearer " + session.access_token
        },
        body: JSON.stringify({
          comment,
          content_context: context,
          comment_id: selectedComment?.id || null
        })
      });
      const data = await res.json();
      if (!res.ok || data.detail) {
        setResult(null);
        setMessage(data.detail || "AI reply generation failed.");
        return;
      }
      setResult(data);
      setReply(data.recommended_reply || data.replies?.[0] || "");
    } catch (error) {
      setResult(null);
      setMessage("Could not reach the AI reply service.");
      console.error("AI reply generation failed:", error);
    } finally {
      setLoading(false);
    }
  }

  async function approveReply() {
    if (!selectedComment || !reply.trim()) return;
    setLoading(true);
    setMessage("");
    try {
      const res = await fetch(
        apiBase() + "/api/comments/" + encodeURIComponent(selectedComment.id) + "/approve-reply",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer " + session.access_token
          },
          body: JSON.stringify({ reply: reply.trim() })
        }
      );
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Instagram reply failed.");
        return;
      }

      setMessage("Reply published to Instagram successfully.");
      setResult(null);
      setReply("");
      const currentIndex = inbox.findIndex(item => item.id === selectedComment.id);
      const nextComment = inbox[currentIndex + 1];
      await loadInbox(inboxStatus);
      if (nextComment) {
        selectForReply(nextComment);
      } else {
        setSelectedComment(null);
      }
    } catch (error) {
      setMessage("Could not reach the Instagram reply service.");
      console.error("Approve & Reply failed:", error);
    } finally {
      setLoading(false);
    }
  }

  function skipComment() {
    if (!selectedComment) return;
    const currentIndex = inbox.findIndex(item => item.id === selectedComment.id);
    const nextComment = inbox[currentIndex + 1];
    if (nextComment) {
      selectForReply(nextComment);
    } else {
      setSelectedComment(null);
      setReply("");
      setResult(null);
    }
  }

  if (!session) {
    return <main style={{maxWidth:520,margin:"80px auto",padding:24}}>
      <h1>Auto-Replay</h1>
      <p>Sign in to connect your Instagram account.</p>
      <input value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" type="email" style={{width:"100%",padding:12,marginTop:8}}/>
      <input value={password} onChange={e=>setPassword(e.target.value)} placeholder="Password" type="password" style={{width:"100%",padding:12,marginTop:8}}/>
      <div style={{display:"flex",gap:8,marginTop:12}}>
        <button onClick={()=>auth("signin")} disabled={!email||!password}>Sign in</button>
        <button onClick={()=>auth("signup")} disabled={!email||!password}>Create account</button>
      </div>
      {message && <p>{message}</p>}
    </main>;
  }

  return <main style={{maxWidth:1200,margin:"32px auto",padding:24,fontFamily:"Arial, sans-serif"}}>
    <h1>Auto-Replay</h1>
    <p>Instagram comment AI for <strong>@thisismax18</strong>.</p>

    <div style={{display:"flex",gap:8,flexWrap:"wrap",margin:"20px 0"}}>
      <button onClick={connectInstagram}>Connect Instagram</button>
      <button onClick={loadAccount}>Check connection</button>
      <button onClick={syncInstagram} disabled={loading}>{loading ? "Syncing..." : "Sync Instagram comments"}</button>
      <button onClick={checkPermissions} disabled={loading}>Check Instagram permissions</button>
      <button onClick={testComments} disabled={loading}>Test comment API</button>
      <button onClick={()=>supabase.auth.signOut()}>Sign out</button>
    </div>

    {account && <p>Connected: @{account.metadata?.username || account.account_name}</p>}
    {message && <p style={{padding:12,background:"#f4f4f4",borderRadius:8}}>{message}</p>}

    <section style={{marginTop:28}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:12,flexWrap:"wrap"}}>
        <div>
          <h2 style={{marginBottom:4}}>Comments Inbox</h2>
          <p style={{marginTop:0,color:"#666"}}>Human approval is required. Auto-publishing is OFF.</p>
        </div>
        <button onClick={()=>loadInbox(inboxStatus)} disabled={inboxLoading}>
          {inboxLoading ? "Loading..." : "Refresh"}
        </button>
      </div>

      <div style={{display:"flex",gap:8,margin:"16px 0",flexWrap:"wrap"}}>
        {statusTabs.map(([value,label]) => (
          <button
            key={value}
            onClick={()=>setInboxStatus(value)}
            style={{
              fontWeight: inboxStatus === value ? "700" : "400",
              border: inboxStatus === value ? "2px solid #111" : "1px solid #ccc"
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"minmax(320px, 1fr) minmax(360px, 1.2fr)",gap:20}}>
        <div style={{border:"1px solid #ddd",borderRadius:10,overflow:"hidden"}}>
          {inbox.length === 0 && <p style={{padding:20,color:"#666"}}>No comments in this view.</p>}
          {inbox.map(item => (
            <button
              key={item.id}
              onClick={()=>selectForReply(item)}
              style={{
                display:"block",width:"100%",textAlign:"left",padding:16,
                border:0,borderBottom:"1px solid #eee",
                background:selectedComment?.id === item.id ? "#f0f6ff" : "#fff",
                cursor:"pointer"
              }}
            >
              <strong>@{item.commenter_username || item.commenter_name || "Instagram user"}</strong>
              <div style={{marginTop:6}}>{item.body || "(empty comment)"}</div>
              <small style={{display:"block",marginTop:8,color:"#777"}}>
                {item.status} · {item.platform_created_at ? new Date(item.platform_created_at).toLocaleString() : ""}
              </small>
            </button>
          ))}
        </div>

        <div style={{border:"1px solid #ddd",borderRadius:10,padding:20,minHeight:300}}>
          {!selectedComment ? (
            <p style={{color:"#666"}}>Select a comment to review it.</p>
          ) : (
            <>
              <h3 style={{marginTop:0}}>@{selectedComment.commenter_username || selectedComment.commenter_name || "Instagram user"}</h3>

              <div style={{padding:14,background:"#f7f7f7",borderRadius:8}}>
                <strong>Original comment</strong>
                <p style={{marginBottom:0,whiteSpace:"pre-wrap"}}>{selectedComment.body}</p>
              </div>

              <div style={{padding:12,background:"#f7f7f7",borderRadius:8,marginTop:12}}>
                <strong>Reel context</strong>
                <p style={{marginBottom:0}}>{selectedComment.content_items?.caption || "No caption available."}</p>
              </div>

              <div style={{padding:12,background:"#f7fbff",border:"1px solid #d8e9ff",borderRadius:8,marginTop:12}}>
                <strong>🧠 Commenter Memory</strong>
                {memory ? (
                  <>
                    <p style={{margin:"6px 0"}}><b>Interactions:</b> {memory.interaction_count || 0}</p>
                    <p style={{margin:"6px 0"}}><b>Summary:</b> {memory.summary || "No summary yet."}</p>
                    {(memory.facts || []).length > 0 && (
                      <p style={{margin:"6px 0"}}><b>Known facts:</b> {(memory.facts || []).join(" • ")}</p>
                    )}
                  </>
                ) : (
                  <p style={{margin:"6px 0",color:"#666"}}>No memory yet — this commenter is new to Auto-Replay.</p>
                )}
              </div>

              <div style={{padding:12,background:"#f7fbff",border:"1px solid #d8e9ff",borderRadius:8,marginTop:12}}>
                <strong>🧠 AI Memory & Personality</strong>
                <p style={{margin:"6px 0 0",color:"#555",fontSize:14}}>
                  Auto-Replay uses your approved replies to learn your creator style and
                  builds memory for returning commenters. Learning is active.
                </p>
              </div>

              <h3>AI Reply</h3>
              <textarea
                value={reply}
                onChange={e=>setReply(e.target.value)}
                placeholder="Generate an AI reply, or type your own reply..."
                rows={3}
                style={{width:"100%",padding:10,boxSizing:"border-box"}}
              />
              <button onClick={generate} disabled={!comment || loading} style={{marginTop:10,padding:"10px 18px"}}>
                {loading ? "Thinking..." : "Generate AI replies"}
              </button>

              {result && (
                <div style={{marginTop:16}}>
                  <div style={{display:"flex",gap:8,flexWrap:"wrap",marginBottom:12}}>
                    {result.commenter_interaction_count > 0 && (
                      <span style={{padding:"5px 9px",borderRadius:999,background:"#eef7ee"}}>
                        Returning commenter · {result.commenter_interaction_count} prior interactions
                      </span>
                    )}
                    {result.creator_personality_used && (
                      <span style={{padding:"5px 9px",borderRadius:999,background:"#eef7ee"}}>
                        Creator style learned
                      </span>
                    )}
                    <span style={{padding:"5px 9px",borderRadius:999,background:"#eee"}}>Intent: {result.intent || "unknown"}</span>
                    <span style={{padding:"5px 9px",borderRadius:999,background:"#eee"}}>Sentiment: {result.sentiment || "unknown"}</span>
                    <span style={{padding:"5px 9px",borderRadius:999,background:"#eee"}}>Risk: {result.risk_level || "unknown"}</span>
                    <span style={{padding:"5px 9px",borderRadius:999,background:"#eee"}}>Confidence: {typeof result.confidence === "number" ? Math.round(result.confidence * 100) + "%" : "—"}</span>
                  </div>

                  <strong>AI suggestions</strong>
                  <div style={{display:"grid",gap:8,marginTop:8}}>
                    {(result.replies || []).map((candidate, index) => (
                      <button
                        key={index}
                        onClick={()=>setReply(candidate)}
                        style={{
                          textAlign:"left",
                          padding:12,
                          border:"1px solid #ddd",
                          borderRadius:8,
                          background:reply === candidate ? "#f0f6ff" : "#fff",
                          cursor:"pointer"
                        }}
                      >
                        {candidate}
                      </button>
                    ))}
                  </div>

                  {result.reason && (
                    <p style={{fontSize:13,color:"#666",marginBottom:0}}>
                      {result.reason}
                    </p>
                  )}
                </div>
              )}

              <div style={{display:"flex",gap:8,marginTop:16}}>
                <button onClick={approveReply} disabled={!reply.trim() || loading}>
                  {loading ? "Publishing..." : "Approve & Reply"}
                </button>
                <button onClick={skipComment} disabled={loading}>Skip (next)</button>
              </div>
            </>
          )}
        </div>
      </div>
    </section>

    <details style={{marginTop:32}}>
      <summary>Developer diagnostics</summary>
      <section style={{marginTop:16,padding:16,border:"1px solid #ccc"}}>
        <h3>Temporary Meta token test</h3>
        <p style={{fontSize:14}}>Diagnostic only. Tokens are never stored by Auto-Replay.</p>
        <input
          value={manualToken}
          onChange={e=>setManualToken(e.target.value)}
          placeholder="Paste Meta-generated access token"
          type="password"
          autoComplete="off"
          style={{width:"100%",padding:12}}
        />
        <button onClick={testMetaGeneratedToken} disabled={!manualToken||loading} style={{marginTop:10}}>
          Test Meta-generated token
        </button>
      </section>
      <hr/>
      <h3>Manual AI reply test</h3>
      <textarea value={comment} onChange={e=>setComment(e.target.value)} placeholder="Paste a comment..." rows={4} style={{width:"100%",padding:12}}/>
      <textarea value={context} onChange={e=>setContext(e.target.value)} placeholder="What is the Reel/video about?" rows={3} style={{width:"100%",padding:12,marginTop:12}}/>
      <button onClick={generate} disabled={!comment||loading} style={{marginTop:12,padding:"10px 18px"}}>Generate replies</button>
    </details>
  </main>;
}