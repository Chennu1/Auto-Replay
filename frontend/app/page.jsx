"use client";
import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
);

export default function Home() {
  const [session, setSession] = useState(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [comment, setComment] = useState("");
  const [context, setContext] = useState("");
  const [result, setResult] = useState(null);
  const [account, setAccount] = useState(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [manualToken, setManualToken] = useState("");

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  async function auth(mode) {
    setMessage("");
    const action = mode === "signup" ? supabase.auth.signUp({ email, password }) : supabase.auth.signInWithPassword({ email, password });
    const { error } = await action;
    if (error) setMessage(error.message);
    else setMessage(mode === "signup" ? "Account created. Check your email if confirmation is enabled." : "Signed in.");
  }

  async function connectInstagram() {
    setMessage("");
    const token = session?.access_token;
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const res = await fetch(base + "/api/instagram/connect", { headers: { Authorization: "Bearer " + token } });
    const data = await res.json();
    if (!res.ok) return setMessage(data.detail || "Unable to start Instagram connection.");
    window.location.href = data.authorization_url;
  }

  async function loadAccount() {
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const res = await fetch(base + "/api/instagram/account", { headers: { Authorization: "Bearer " + session.access_token } });
    const data = await res.json();
    setAccount(data.accounts?.[0] || null);
  }

  async function checkPermissions() {
    setLoading(true); setMessage("");
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      const res = await fetch(base + "/api/instagram/debug-permissions", {
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Permission check failed.");
        return;
      }
      const granted = (data.permissions || [])
        .filter(p => p.status === "granted")
        .map(p => p.permission)
        .join(", ");
      const missing = (data.missing_required || []).join(", ");
      setMessage(
        "Instagram permissions: " + (granted || "none") +
        (missing ? " | Missing: " + missing : " | Required permissions are granted.")
      );
    } catch (error) {
      setMessage("Could not reach Auto-Replay API at " + base + ".");
      console.error("Instagram permission check failed:", error);
    } finally {
      setLoading(false);
    }
  }

  async function testComments() {
    setLoading(true); setMessage("");
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      const res = await fetch(base + "/api/instagram/debug-comment-test", {
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
      if (data.errors?.length) console.warn("Instagram comment API errors:", data.errors);
    } catch (error) {
      setMessage("Could not reach Auto-Replay API at " + base + ".");
      console.error("Instagram comment API test failed:", error);
    } finally {
      setLoading(false);
    }
  }

  async function syncInstagram() {
    setLoading(true); setMessage("");
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      const res = await fetch(base + "/api/instagram/sync", {
        method: "POST",
        headers: { Authorization: "Bearer " + session.access_token }
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(data.detail || "Sync failed.");
        return;
      }

      let diagnostic = "";
      try {
        const debugRes = await fetch(base + "/api/instagram/debug-comments", {
          headers: { Authorization: "Bearer " + session.access_token }
        });
        const debug = await debugRes.json();
        if (debugRes.ok) {
          diagnostic =
            " | Checked media: " + (debug.media_count ?? 0) +
            ", comments returned: " + (debug.total_comments_returned ?? 0) +
            (debug.errors?.length ? ", Meta errors: " + debug.errors.map(e => e.error_message).join(" | ") : "");
        }
      } catch (debugError) {
        console.error("Instagram comment diagnostic failed:", debugError);
      }

      setMessage(
        "Instagram sync complete: " +
        data.comments_synced +
        " comments synced." +
        diagnostic
      );
    } catch (error) {
      setMessage("Could not reach Auto-Replay API at " + base + ". Check Railway deployment/CORS.");
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
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    try {
      const res = await fetch(base + "/api/instagram/debug-manual-token", {
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
        " | Latest media comments: " + (data.comment_count ?? 0) +
        (data.latest_permalink ? " | Latest: " + data.latest_permalink : "") +
        (data.comment_preview?.length ? " | First comment: " + data.comment_preview[0] : "")
      );
    } catch (error) {
      setMessage("Could not reach Auto-Replay API at " + base + ".");
      console.error("Meta-generated token test failed:", error);
    } finally {
      setManualToken("");
      setLoading(false);
    }
  }

  async function generate() {
    setLoading(true);
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const res = await fetch(base + "/api/replies/generate", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({comment, content_context: context})
    });
    setResult(await res.json());
    setLoading(false);
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

  return <main style={{maxWidth:900,margin:"40px auto",padding:24}}>
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
    {message && <p>{message}</p>}

    <section style={{marginTop:24,padding:16,border:"1px solid #ccc"}}>
      <h2>Temporary Meta token test</h2>
      <p style={{fontSize:14}}>
        Paste the token generated by Meta for <strong>thisismax_18</strong>.
        It is sent only for this diagnostic and is not stored by Auto-Replay.
      </p>
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
    <h2>Test AI reply</h2>
    <textarea value={comment} onChange={e=>setComment(e.target.value)} placeholder="Paste a comment..." rows={5} style={{width:"100%",padding:12}}/>
    <textarea value={context} onChange={e=>setContext(e.target.value)} placeholder="What is the Reel/video about?" rows={4} style={{width:"100%",padding:12,marginTop:12}}/>
    <button onClick={generate} disabled={!comment||loading} style={{marginTop:12,padding:"10px 18px"}}>{loading?"Thinking...":"Generate replies"}</button>
    {result&&<section style={{marginTop:24}}><h2>AI analysis</h2><pre style={{whiteSpace:"pre-wrap",background:"#f5f5f5",padding:16}}>{JSON.stringify(result,null,2)}</pre></section>}
  </main>;
}
