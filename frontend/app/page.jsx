"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
);

const tabs = [
  ["needs_review", "Needs review"],
  ["replied", "Replied"],
  ["skipped", "Skipped"],
];

const styles = {
  page: { minHeight: "100vh", background: "#f6f7fb", color: "#15171a", fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" },
  shell: { maxWidth: 1440, margin: "0 auto", padding: "24px 28px 48px" },
  card: { background: "#fff", border: "1px solid #e7e8ec", borderRadius: 18, boxShadow: "0 8px 30px rgba(20,24,40,.05)" },
  button: { border: "1px solid #dfe1e7", background: "#fff", color: "#17191d", borderRadius: 10, padding: "10px 14px", fontWeight: 650, cursor: "pointer" },
  primary: { border: 0, background: "#111318", color: "#fff", borderRadius: 10, padding: "11px 16px", fontWeight: 700, cursor: "pointer" },
  muted: { color: "#737780" },
  input: { width: "100%", boxSizing: "border-box", border: "1px solid #dedfe5", borderRadius: 10, padding: "11px 12px", outline: "none", fontSize: 14 },
};

function riskStyle(risk) {
  if (risk === "high") return { background: "#fff0f0", color: "#b42318", border: "1px solid #ffd1d1" };
  if (risk === "medium") return { background: "#fff8e8", color: "#9a6700", border: "1px solid #f5df9c" };
  return { background: "#eef9f1", color: "#18794e", border: "1px solid #ccebd6" };
}

export default function Home() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [comment, setComment] = useState("");
  const [reply, setReply] = useState("");
  const [context, setContext] = useState("");
  const [result, setResult] = useState(null);
  const [account, setAccount] = useState(null);
  const [automation, setAutomation] = useState(null);
  const [stats, setStats] = useState({total:0,pending:0,needs_review:0,replied:0,replied_by_agent:0,approved_by_human:0,failed:0,skipped:0,open:0});
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [inbox, setInbox] = useState([]);
  const [inboxStatus, setInboxStatus] = useState("needs_review");
  const [selectedComment, setSelectedComment] = useState(null);
  const [inboxLoading, setInboxLoading] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) return;
    loadInbox(inboxStatus);
    loadAccount();
    loadAutomation();
    loadStats();
    const timer = setInterval(() => {
      loadInbox(inboxStatus);
      loadAutomation();
      loadStats();
    }, 30000);
    return () => clearInterval(timer);
  }, [session, inboxStatus]);

  function apiBase() {
    return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  }

  async function auth(mode) {
    setMessage("");
    const action = mode === "signup"
      ? supabase.auth.signUp({ email, password })
      : supabase.auth.signInWithPassword({ email, password });
    const { error } = await action;
    setMessage(error ? error.message : mode === "signup" ? "Account created. Check your email if confirmation is enabled." : "Signed in.");
  }

  async function loadAccount() {
    if (!session) return;
    try {
      const res = await fetch(apiBase() + "/api/instagram/account", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (res.ok) setAccount(data.accounts?.[0] || null);
    } catch {}
  }

  async function loadAutomation() {
    if (!session) return;
    try {
      const res = await fetch(apiBase() + "/api/automation/status", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      if (res.ok) setAutomation(await res.json());
    } catch {}
  }

  async function loadStats() {
    if (!session) return;
    try {
      const res = await fetch(apiBase() + "/api/comments/stats", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      if (res.ok) setStats(await res.json());
    } catch {}
  }

  async function loadInbox(status = inboxStatus) {
    if (!session) return;
    setInboxLoading(true);
    try {
      const res = await fetch(apiBase() + "/api/comments?status=" + encodeURIComponent(status) + "&limit=100", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Could not load comments.");
        return;
      }
      const rows = data.comments || [];
      setInbox(rows);
      if (selectedComment && !rows.some(x => x.id === selectedComment.id)) setSelectedComment(null);

      // Human-review items must always have an AI draft before they reach the
      // approval button. Generate a missing draft automatically and persist it.
      if (status === "needs_review") {
        const missingDraft = rows.find(x => !x.metadata?.ai_reply);
        if (missingDraft) {
          try {
            const draftRes = await fetch(apiBase() + "/api/replies/generate", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: "Bearer " + session.access_token
              },
              body: JSON.stringify({
                comment: missingDraft.body || "",
                comment_id: missingDraft.id
              })
            });
            if (draftRes.ok) {
              const draft = await draftRes.json();
              setInbox(prev => prev.map(x => x.id === missingDraft.id
                ? {
                    ...x,
                    metadata: {
                      ...(x.metadata || {}),
                      ai_reply: draft.recommended_reply || draft.replies?.[0] || "",
                      ai_replies: draft.replies || [],
                      ai_confidence: draft.confidence,
                      understanding_confidence: draft.understanding_confidence,
                      language_confidence: draft.language_confidence,
                      detected_language: draft.language,
                      risk_level: draft.risk_level
                    }
                  }
                : x
              ));
            }
          } catch {}
        }
      }
    } catch {
      setMessage("Could not reach Auto-Replay API.");
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

  function selectForReply(item) {
    setSelectedComment(item);
    setComment(item.body || "");
    setReply("");
    setContext(item.content_items?.caption || "");
    setResult(null);
    setMessage("");
    generate(item);
  }

  async function generate(itemOverride = null) {
    const commentText = itemOverride?.body || comment;
    const commentId = itemOverride?.id || selectedComment?.id || null;
    const contentContext = itemOverride?.content_items?.caption || context;
    if (!commentText.trim()) return;
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/replies/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + session.access_token },
        body: JSON.stringify({ comment: commentText, content_context: contentContext, comment_id: commentId })
      });
      const data = await res.json();
      if (!res.ok || data.detail) {
        setResult(null);
        setMessage(typeof data.detail === "string" ? data.detail : "AI reply generation failed.");
        return;
      }
      setResult(data);
      setReply(data.recommended_reply || data.replies?.[0] || "");
    } catch {
      setResult(null);
      setMessage("Could not reach the AI reply service.");
    } finally {
      setLoading(false);
    }
  }

  async function publishReply(commentId, replyText) {
    if (!commentId || !replyText?.trim()) return;
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/comments/" + encodeURIComponent(commentId) + "/approve-reply", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + session.access_token },
        body: JSON.stringify({ reply: replyText.trim() })
      });
      const data = await res.json();
      if (!res.ok) {
        const d = data.detail;
        setMessage(typeof d === "object" ? (d.message || "Reply blocked.") + ((d.reasons || []).length ? " " + d.reasons.join(" ") : "") : (d || "Instagram reply failed."));
        return false;
      }
      setMessage("Reply published successfully.");
      setSelectedComment(null);
      setResult(null);
      setReply("");
      await loadInbox(inboxStatus);
      await loadStats();
      return true;
    } catch {
      setMessage("Could not reach Instagram.");
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function approveReply() {
    if (!selectedComment || !reply.trim()) return;
    await publishReply(selectedComment.id, reply);
  }

  async function skipItem(commentId) {
    if (!commentId) return;
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/comments/" + encodeURIComponent(commentId) + "/skip", {
        method: "POST",
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Could not skip comment.");
        return false;
      }
      if (selectedComment?.id === commentId) {
        setSelectedComment(null);
        setResult(null);
        setReply("");
      }
      await loadInbox(inboxStatus);
      await loadStats();
      return true;
    } catch {
      setMessage("Could not reach Auto-Replay API.");
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function skipComment() {
    if (!selectedComment) return;
    await skipItem(selectedComment.id);
  }

  const filteredInbox = inbox;



  if (!session) {
    return (
      <main style={{...styles.page, display:"grid", placeItems:"center", padding:24}}>
        <div style={{...styles.card, width:"100%", maxWidth:430, padding:32}}>
          <div style={{fontSize:13,fontWeight:800,letterSpacing:1,color:"#6b5cff"}}>AUTO-REPLAY</div>
          <h1 style={{fontSize:32,margin:"10px 0 8px"}}>Your AI comment desk.</h1>
          <p style={styles.muted}>Understand comments. Match your voice. Review before anything is published.</p>
          <input value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email" type="email" style={{...styles.input,marginTop:18}}/>
          <input value={password} onChange={e=>setPassword(e.target.value)} placeholder="Password" type="password" style={{...styles.input,marginTop:10}}/>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginTop:14}}>
            <button style={styles.primary} onClick={()=>auth("signin")} disabled={!email||!password}>Sign in</button>
            <button style={styles.button} onClick={()=>auth("signup")} disabled={!email||!password}>Create account</button>
          </div>
          {message && <p style={{fontSize:13,marginTop:14}}>{message}</p>}
        </div>
      </main>
    );
  }

  return (
    <main style={styles.page}>
      <div style={styles.shell}>
        <header style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:18,marginBottom:24,flexWrap:"wrap"}}>
          <div>
            <div style={{fontSize:12,fontWeight:800,letterSpacing:1.4,color:"#6b5cff"}}>AUTO-REPLAY</div>
            <h1 style={{margin:"5px 0",fontSize:30}}>Comment command center</h1>
            <p style={{margin:0,...styles.muted}}>AI-assisted engagement for @{account?.metadata?.username || account?.account_name || "Instagram"}</p>
          </div>
          <div style={{display:"flex",gap:9,alignItems:"center"}}>
            <span style={{padding:"8px 11px",borderRadius:999,background:automation ? (automation.enabled ? "#eef9f1" : "#fff0f0") : "#f1f1f3",color:automation ? (automation.enabled ? "#18794e" : "#b42318") : "#444",fontSize:12,fontWeight:750}}>
              {automation ? (automation.enabled ? "● Auto-reply ON" : "● Auto-reply OFF") : "● Checking automation…"}
            </span>
            <button style={styles.button} onClick={()=>supabase.auth.signOut()}>Sign out</button>
          </div>
        </header>

        <section style={{display:"grid",gridTemplateColumns:"repeat(2,minmax(0,1fr))",gap:12,marginBottom:18}}>
          {[
            ["🤖 Agent replied",stats.replied_by_agent,"Published automatically","#eaf8ef","#16834b"],
            ["🧑‍💻 Human approved",stats.approved_by_human,"Approved & published","#eeeaff","#6347d8"],
            ["⚠️ To review",stats.needs_review,"Needs human attention","#fff4df","#b56a00"],
            ["⏳ Pending",stats.pending,"Waiting to be processed","#eaf4ff","#2371c9"],
            ["💬 Total comments",stats.total,"All synced comments","#ffeaf2","#c13c70"],
          ].map(([label,value,sub,bg,fg])=>(
            <div key={label} style={{...styles.card,padding:18,background:bg,border:"1px solid rgba(255,255,255,.7)",boxShadow:"0 8px 25px rgba(20,24,40,.06)"}}>
              <div style={{fontSize:12,color:fg,fontWeight:800}}>{label}</div>
              <div style={{fontSize:31,fontWeight:850,marginTop:7,color:"#15171a"}}>{value}</div>
              <div style={{fontSize:12,color:fg,marginTop:4,fontWeight:650}}>{sub}</div>
            </div>
          ))}
        </section>

        <section style={{...styles.card,padding:16,marginBottom:18,display:"flex",justifyContent:"space-between",alignItems:"center",gap:12,flexWrap:"wrap"}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <span style={{width:9,height:9,borderRadius:99,background:account?.status === "connected" ? "#20a464" : "#aaa"}}/>
            <div>
              <strong>{account?.status === "connected" ? "Instagram connected" : "Instagram not connected"}</strong>
              <div style={{fontSize:12,...styles.muted}}>New comments are checked automatically every minute.</div>
            </div>
          </div>
          <span style={{
            padding:"8px 12px",borderRadius:999,fontSize:12,fontWeight:800,
            background:automation ? (automation.enabled ? "#eef9f1" : "#fff0f0") : "#f1f1f3",
            color:automation ? (automation.enabled ? "#18794e" : "#b42318") : "#444"
          }}>
            {automation ? (automation.enabled ? "● Auto-reply ON · Every 1 minute" : "● Auto-reply OFF") : "● Checking automation…"}
          </span>
        </section>

        {automation && (
          <section style={{...styles.card,padding:14,marginBottom:16,background:"#fff8e8",border:"1px solid #f5df9c",boxShadow:"none"}}>
            <div style={{fontSize:12,fontWeight:850,color:"#9a6700"}}>WORKER STATUS</div>
            <div style={{marginTop:6,fontSize:13}}>
              Started: {automation.worker_started ? "Yes" : "No"} ·
              Alive: {automation.worker_alive ? "Yes" : "No"} ·
              Cycles: {automation.cycle_count ?? 0} ·
              Last check: {automation.last_run_at ? new Date(automation.last_run_at).toLocaleTimeString() : "None yet"}
            </div>
            {automation.last_error && <div style={{marginTop:6,fontSize:12,color:"#b42318",wordBreak:"break-word"}}>Error: {automation.last_error}</div>}
          </section>
        )}

        {message && <div style={{...styles.card,padding:12,marginBottom:16,fontSize:14}}>{message}</div>}

        <section style={{...styles.card,overflow:"hidden"}}>
          <div style={{padding:"20px 20px 14px",borderBottom:"1px solid #ececf0"}}>
            <div style={{display:"flex",justifyContent:"space-between",gap:14,alignItems:"center",flexWrap:"wrap"}}>
              <div>
                <h2 style={{margin:0,fontSize:20}}>Human review</h2>
                <p style={{margin:"4px 0 0",fontSize:13,...styles.muted}}>Comment → AI reply → Approve or Skip.</p>
              </div>

            </div>
            <div style={{display:"flex",gap:7,marginTop:16,flexWrap:"wrap"}}>
              {tabs.map(([value,label])=>(
                <button key={value} onClick={()=>setInboxStatus(value)} style={{
                  ...styles.button,
                  background: inboxStatus===value ? "#111318" : "#fff",
                  color: inboxStatus===value ? "#fff" : "#333",
                  borderColor: inboxStatus===value ? "#111318" : "#dfe1e7"
                }}>{label}</button>
              ))}
            </div>
          </div>

          <div style={{minHeight:300}}>
            <div style={{maxHeight:720,overflowY:"auto"}}>
              {filteredInbox.length===0 && <div style={{padding:28,...styles.muted}}>No comments match this queue.</div>}
              {filteredInbox.map(item=>{
                const selected=selectedComment?.id===item.id;
                const aiReply = inboxStatus === "replied"
                  ? (item.metadata?.reply_text || item.metadata?.ai_reply || "")
                  : (item.metadata?.ai_reply || "");
                return (
                  <div key={item.id} style={{
                    display:"grid",
                    gridTemplateColumns:"minmax(220px,1fr) minmax(280px,1.4fr) 190px",
                    gap:16,
                    alignItems:"center",
                    borderBottom:"1px solid #f0f0f2",
                    background:selected?"#f5f6ff":"#fff",
                    padding:"18px 20px"
                  }}>
                    <div>
                      <div style={{fontSize:10,fontWeight:800,...styles.muted}}>USER COMMENT</div>
                      <div style={{fontWeight:750,fontSize:14,marginTop:5}}>
                        @{item.commenter_username || item.commenter_name || "Instagram user"}
                      </div>
                      <div style={{marginTop:7,fontSize:14,lineHeight:1.45}}>{item.body || "(empty comment)"}</div>
                      {item.platform_created_at && (
                        <div style={{marginTop:5,fontSize:11,...styles.muted}}>
                          Commented: {new Date(item.platform_created_at).toLocaleString()}
                        </div>
                      )}
                    </div>

                    <div style={{padding:12,borderRadius:10,background:"#f7f7f9"}}>
                      <div style={{fontSize:10,fontWeight:800,...styles.muted}}>
                        {inboxStatus === "replied" ? "AGENT REPLIED" : "AI-GENERATED REPLY"}
                      </div>
                      <div style={{marginTop:6,fontSize:14,lineHeight:1.45}}>
                        {aiReply || (inboxStatus === "replied" ? "Reply text unavailable" : "Generating reply…")}
                      </div>
                    </div>

                    {inboxStatus === "needs_review" ? (
                      <div style={{textAlign:"right"}}>
                        <div style={{display:"flex",alignItems:"center",justifyContent:"flex-end",gap:12}}>
                          {item.metadata?.ai_confidence != null && (
                            <div style={{fontSize:12,fontWeight:750,...styles.muted,whiteSpace:"nowrap"}}>
                              AI confidence: {Math.round(Number(item.metadata.ai_confidence) * 100)}%
                            </div>
                          )}
                          <button
                            onClick={()=>publishReply(item.id, aiReply)}
                            disabled={!aiReply || loading}
                            style={styles.primary}
                          >
                            Approve & Reply
                          </button>
                        </div>
                        <button
                          onClick={()=>skipItem(item.id)}
                          disabled={loading}
                          style={{...styles.button,marginTop:8,width:"100%"}}
                        >
                          Skip
                        </button>
                      </div>
                    ) : (
                      <div style={{textAlign:"right",fontSize:12,...styles.muted}}>
                        {inboxStatus === "replied" && item.metadata?.ai_confidence != null && (
                          <div style={{fontWeight:750}}>AI confidence: {Math.round(Number(item.metadata.ai_confidence) * 100)}%</div>
                        )}
                        <div style={{marginTop:4}}>
                          {inboxStatus === "replied" ? "Published automatically" : "Skipped"}
                        </div>
                        {inboxStatus === "replied" && (item.metadata?.replied_at || item.created_at) && (
                          <div style={{marginTop:5,fontSize:11}}>
                            Replied: {new Date(item.metadata?.replied_at || item.created_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

          </div>
        </section>

        <footer style={{marginTop:18,fontSize:12,...styles.muted}}>
          {automation?.enabled
            ? "Auto-reply is ON · checking every minute · sensitive or very-low-confidence comments go to human review."
            : automation
              ? "Auto-reply is OFF."
              : "Checking automation status…"}
          {automation?.last_run_at ? " Last check: " + new Date(automation.last_run_at).toLocaleTimeString() + "." : ""}
          {automation?.last_error ? " Worker error: " + automation.last_error : ""}
        </footer>
      </div>
    </main>
  );
}
