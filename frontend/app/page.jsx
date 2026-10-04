"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
);

const tabs = [
  ["new", "Inbox"],
  ["needs_review", "Needs review"],
  ["replied", "Replied"],
  ["all", "All"],
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

function priority(item) {
  const risk = item.metadata?.safety_action ? (item.metadata?.safety_categories?.length ? "medium" : "low") : "low";
  let score = risk === "high" ? 100 : risk === "medium" ? 70 : 20;
  if (item.status === "needs_review") score += 50;
  if (item.body?.includes("?")) score += 10;
  const age = item.platform_created_at ? (Date.now() - new Date(item.platform_created_at).getTime()) / 3600000 : 0;
  score += Math.min(Math.max(age, 0), 48);
  return score;
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
  const [inboxStatus, setInboxStatus] = useState("new");
  const [selectedComment, setSelectedComment] = useState(null);
  const [inboxLoading, setInboxLoading] = useState(false);
  const [memory, setMemory] = useState(null);
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState("priority");

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
      setInbox(data.comments || []);
      if (selectedComment && !data.comments?.some(x => x.id === selectedComment.id)) setSelectedComment(null);
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
      setMessage("Synced " + (data.comments_synced || 0) + " comments.");
      await loadInbox(inboxStatus);
      await loadStats();
    } catch {
      setMessage("Could not reach Auto-Replay API.");
    } finally {
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
    loadMemory(item.id);
    generate(item);
  }

  async function loadMemory(commentId) {
    try {
      const res = await fetch(apiBase() + "/api/comments/" + encodeURIComponent(commentId) + "/memory", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (res.ok) setMemory(data.memory || null);
    } catch {}
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

  async function approveReply() {
    if (!selectedComment || !reply.trim()) return;
    setLoading(true); setMessage("");
    try {
      const res = await fetch(apiBase() + "/api/comments/" + encodeURIComponent(selectedComment.id) + "/approve-reply", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + session.access_token },
        body: JSON.stringify({ reply: reply.trim() })
      });
      const data = await res.json();
      if (!res.ok) {
        const d = data.detail;
        setMessage(typeof d === "object" ? (d.message || "Reply blocked.") + ((d.reasons || []).length ? " " + d.reasons.join(" ") : "") : (d || "Instagram reply failed."));
        return;
      }
      setMessage("Reply published successfully.");
      setResult(null); setReply("");
      await loadInbox(inboxStatus);
      await loadStats();
      setSelectedComment(null);
    } catch {
      setMessage("Could not reach Instagram.");
    } finally {
      setLoading(false);
    }
  }

  const filteredInbox = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = inbox.filter(x =>
      !q ||
      (x.body || "").toLowerCase().includes(q) ||
      (x.commenter_username || "").toLowerCase().includes(q) ||
      (x.commenter_name || "").toLowerCase().includes(q)
    );
    return [...rows].sort((a, b) => {
      if (sortMode === "newest") return new Date(b.platform_created_at || 0) - new Date(a.platform_created_at || 0);
      return priority(b) - priority(a);
    });
  }, [inbox, search, sortMode]);

  const queueStats = useMemo(() => ({
    visible: inbox.length,
    urgent: inbox.filter(x => x.metadata?.safety_action === "block_automation").length,
  }), [inbox]);

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
            <span style={{padding:"8px 11px",borderRadius:999,background:"#eef9f1",color:"#18794e",fontSize:12,fontWeight:750}}>● Auto-reply ON</span>
            <span style={{padding:"8px 11px",borderRadius:999,background:"#f1f1f3",color:"#444",fontSize:12,fontWeight:750}}>Human review fallback ON</span>
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

        <section style={{...styles.card,padding:14,marginBottom:18,display:"flex",justifyContent:"space-between",alignItems:"center",gap:12,flexWrap:"wrap"}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <span style={{width:9,height:9,borderRadius:99,background:account?.status === "connected" ? "#20a464" : "#aaa"}}/>
            <div>
              <strong>{account?.status === "connected" ? "Instagram connected" : "Instagram not connected"}</strong>
              <div style={{fontSize:12,...styles.muted}}>Sync comments whenever you want to refresh the queue.</div>
            </div>
          </div>
          <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
            <button style={styles.button} onClick={connectInstagram}>Connect Instagram</button>
            <button style={styles.button} onClick={async ()=>{
              setLoading(true); setMessage("");
              try {
                const res = await fetch(apiBase()+"/api/automation/run-now",{method:"POST",headers:{Authorization:"Bearer "+session.access_token}});
                const data = await res.json();
                setMessage(res.ok ? "Agent run complete: " + (data.replied||0) + " replied, " + (data.review||0) + " sent to human review." : (data.detail || "Agent run failed."));
                await loadInbox(inboxStatus); await loadAutomation(); await loadStats();
              } catch { setMessage("Could not reach the Auto-Replay API."); }
              finally { setLoading(false); }
            }} disabled={loading}>▶ Run agent now</button>
            <button style={styles.primary} onClick={syncInstagram} disabled={loading}>{loading ? "Syncing…" : "↻ Sync & auto-reply"}</button>
          </div>
        </section>

        {message && <div style={{...styles.card,padding:12,marginBottom:16,fontSize:14}}>{message}</div>}

        <section style={{...styles.card,overflow:"hidden"}}>
          <div style={{padding:"20px 20px 14px",borderBottom:"1px solid #ececf0"}}>
            <div style={{display:"flex",justifyContent:"space-between",gap:14,alignItems:"center",flexWrap:"wrap"}}>
              <div>
                <h2 style={{margin:0,fontSize:20}}>Review queue</h2>
                <p style={{margin:"4px 0 0",fontSize:13,...styles.muted}}>Prioritized comments, learned creator voice, memory and safety.</p>
              </div>
              <button style={styles.button} onClick={()=>loadInbox(inboxStatus)} disabled={inboxLoading}>{inboxLoading ? "Refreshing…" : "Refresh"}</button>
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
            <div style={{display:"grid",gridTemplateColumns:"1fr 170px",gap:9,marginTop:12}}>
              <input style={styles.input} value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search comments or usernames…"/>
              <select style={styles.input} value={sortMode} onChange={e=>setSortMode(e.target.value)}>
                <option value="priority">Priority</option>
                <option value="newest">Newest</option>
              </select>
            </div>
          </div>

          <div style={{display:"grid",gridTemplateColumns:"minmax(320px,.85fr) minmax(500px,1.4fr)",minHeight:650}}>
            <div style={{borderRight:"1px solid #ececf0",maxHeight:720,overflowY:"auto"}}>
              {filteredInbox.length===0 && <div style={{padding:28,...styles.muted}}>No comments match this queue.</div>}
              {filteredInbox.map(item=>{
                const selected=selectedComment?.id===item.id;
                const risk=item.metadata?.safety_action==="block_automation"?"high":item.status==="needs_review"?"medium":"low";
                return (
                  <button key={item.id} onClick={()=>selectForReply(item)} style={{
                    width:"100%",textAlign:"left",border:0,borderBottom:"1px solid #f0f0f2",
                    background:selected?"#f5f6ff":"#fff",padding:"15px 17px",cursor:"pointer"
                  }}>
                    <div style={{display:"flex",justifyContent:"space-between",gap:10}}>
                      <strong style={{fontSize:14}}>@{item.commenter_username || item.commenter_name || "Instagram user"}</strong>
                      <span style={{...riskStyle(risk),fontSize:10,padding:"3px 7px",borderRadius:99,fontWeight:750}}>{risk}</span>
                    </div>
                    <div style={{marginTop:7,fontSize:14,lineHeight:1.4}}>{item.body || "(empty comment)"}</div>
                    <div style={{display:"flex",gap:8,marginTop:9,fontSize:11,...styles.muted}}>
                      <span>{item.status}</span>
                      <span>·</span>
                      <span>{item.platform_created_at ? new Date(item.platform_created_at).toLocaleString() : ""}</span>
                    </div>
                  </button>
                );
              })}
            </div>

            <div style={{padding:22,overflowY:"auto"}}>
              {!selectedComment ? (
                <div style={{height:"100%",minHeight:500,display:"grid",placeItems:"center",textAlign:"center"}}>
                  <div><div style={{fontSize:42}}>✦</div><h3 style={{margin:"10px 0 4px"}}>Select a comment</h3><p style={{...styles.muted,margin:0}}>Auto-Replay will bring the context, memory, safety and reply suggestions here.</p></div>
                </div>
              ) : (
                <>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"start",gap:12}}>
                    <div>
                      <div style={{fontSize:12,...styles.muted}}>COMMENTER</div>
                      <h2 style={{margin:"4px 0"}}>@{selectedComment.commenter_username || selectedComment.commenter_name || "Instagram user"}</h2>
                    </div>
                    <span style={{...riskStyle(result?.risk_level || (selectedComment.status==="needs_review"?"medium":"low")),padding:"5px 9px",borderRadius:99,fontSize:11,fontWeight:800}}>
                      {result?.risk_level || selectedComment.status}
                    </span>
                  </div>

                  <div style={{display:"grid",gap:10,marginTop:18}}>
                    <div style={{background:"#f7f7f9",borderRadius:13,padding:15}}>
                      <div style={{fontSize:11,fontWeight:800,...styles.muted}}>ORIGINAL COMMENT</div>
                      <div style={{marginTop:7,fontSize:16,lineHeight:1.5}}>{selectedComment.body}</div>
                    </div>

                    <div style={{background:"#f7f7f9",borderRadius:13,padding:15}}>
                      <div style={{fontSize:11,fontWeight:800,...styles.muted}}>CONTENT CONTEXT</div>
                      <div style={{marginTop:7,fontSize:14,lineHeight:1.45}}>{selectedComment.content_items?.caption || "No caption available."}</div>
                    </div>

                    <div style={{background:"#f6f9ff",border:"1px solid #dfe8ff",borderRadius:13,padding:15}}>
                      <div style={{fontWeight:750}}>🧠 Commenter memory</div>
                      {memory ? (
                        <>
                          <div style={{display:"flex",gap:8,marginTop:9,flexWrap:"wrap"}}>
                            <span style={{background:"#fff",padding:"5px 8px",borderRadius:8,fontSize:12}}>Interactions: {memory.interaction_count || 0}</span>
                          </div>
                          <p style={{fontSize:13,margin:"9px 0 0"}}>{memory.summary || "Returning commenter."}</p>
                          {(memory.facts || []).length>0 && <p style={{fontSize:12,...styles.muted,margin:"7px 0 0"}}>{memory.facts.join(" • ")}</p>}
                        </>
                      ) : <p style={{fontSize:13,...styles.muted,margin:"7px 0 0"}}>New commenter — no saved relationship yet.</p>}
                    </div>
                  </div>

                  <div style={{marginTop:20}}>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                      <h3 style={{margin:"0 0 8px"}}>AI-generated reply</h3>
                      <span style={{fontSize:11,...styles.muted}}>{loading ? "Generating automatically…" : "Review, edit or approve"}</span>
                    </div>
                    <textarea value={reply} onChange={e=>setReply(e.target.value)} placeholder="Write or generate a reply…" rows={4} style={{...styles.input,resize:"vertical"}}/>
                    <button onClick={()=>generate()} disabled={!comment.trim()||loading} style={{...styles.button,marginTop:9}}>
                      {loading ? "AI is thinking…" : "↻ Regenerate reply"}
                    </button>
                  </div>

                  {result && (
                    <div style={{marginTop:16}}>
                      <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
                        {result.creator_personality_used && <span style={{padding:"5px 8px",borderRadius:99,background:"#eef9f1",fontSize:11}}>Style learned</span>}
                        {result.commenter_interaction_count>0 && <span style={{padding:"5px 8px",borderRadius:99,background:"#eef9f1",fontSize:11}}>Returning commenter · {result.commenter_interaction_count}</span>}
                        {result.video_understanding_used && <span style={{padding:"5px 8px",borderRadius:99,background:"#eef9f1",fontSize:11}}>🎥 Reel understood</span>}
                        <span style={{padding:"5px 8px",borderRadius:99,background:"#f1f1f3",fontSize:11}}>{result.intent || "general"} · {result.sentiment || "unknown"}</span>
                        {result.language && result.language !== "unknown" && <span style={{padding:"5px 8px",borderRadius:99,background:"#f1f1f3",fontSize:11}}>🌐 {result.language}</span>}
                        {result.understood && <span style={{padding:"5px 8px",borderRadius:99,background:"#eef9f1",fontSize:11}}>Meaning understood · {Math.round((result.understanding_confidence || 0) * 100)}%</span>}
                        <span style={{padding:"5px 8px",borderRadius:99,background:"#f1f1f3",fontSize:11}}>Confidence {typeof result.confidence==="number"?Math.round(result.confidence*100)+"%":"—"}</span>
                      </div>

                      {result.video_summary && <div style={{marginTop:10,padding:13,borderRadius:12,background:"#fff9ed",border:"1px solid #f1dfad",fontSize:13}}><strong>🎥 Reel understanding</strong><div style={{marginTop:5}}>{result.video_summary}</div></div>}

                      {result.safety_action && result.safety_action !== "safe_to_suggest" && (
                        <div style={{marginTop:10,padding:13,borderRadius:12,...riskStyle(result.risk_level)}}>
                          <strong>{result.risk_level==="high" ? "🛑 Safety Agent blocked this reply" : "⚠️ Human review required"}</strong>
                          {(result.safety_reasons||[]).length>0 && <ul style={{margin:"7px 0 0",paddingLeft:20,fontSize:13}}>{result.safety_reasons.map((x,i)=><li key={i}>{x}</li>)}</ul>}
                        </div>
                      )}

                      <div style={{marginTop:13,fontSize:12,fontWeight:800,...styles.muted}}>SUGGESTIONS</div>
                      <div style={{display:"grid",gap:7,marginTop:7}}>
                        {(result.replies||[]).map((candidate,i)=><button key={i} onClick={()=>setReply(candidate)} style={{...styles.button,textAlign:"left",background:reply===candidate?"#f4f5ff":"#fff"}}>{candidate}</button>)}
                      </div>
                    </div>
                  )}

                  <div style={{display:"flex",gap:9,marginTop:18}}>
                    <button onClick={approveReply} disabled={!reply.trim()||loading||result?.risk_level==="high"} style={{...styles.primary,flex:1}}>
                      {result?.risk_level==="high" ? "Blocked by Safety Agent" : loading ? "Publishing…" : "Approve & Reply"}
                    </button>
                    <button onClick={()=>{setSelectedComment(null);setReply("");setResult(null)}} disabled={loading} style={styles.button}>Skip</button>
                  </div>
                </>
              )}
            </div>
          </div>
        </section>

        <footer style={{display:"flex",justifyContent:"space-between",gap:12,marginTop:18,fontSize:12,...styles.muted,flexWrap:"wrap"}}>
          <span>{automation?.enabled ? "Auto-reply is ON. Safe, high-confidence comments can be published automatically." : "Auto-reply is OFF."}</span>
          <span>{automation?.last_run_at ? "Agent last ran " + new Date(automation.last_run_at).toLocaleTimeString() : "Agent has not reported a run yet."}{automation?.last_error ? " · Error: " + automation.last_error : ""}</span>
          <span>All languages supported · uncertain language/meaning → human review · AI safety + memory enabled.</span>
        </footer>
      </div>
    </main>
  );
}
