"""Advanced deterministic safety checks for comments and replies."""
import re

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

HIGH_PATTERNS = [
    ("self_harm", r"\b(?:kill myself|suicide|suicidal|self[- ]harm|want to die)\b"),
    ("credible_threat", r"\b(?:i will kill|i'm going to kill|kill you|hurt you|shoot you|bomb you|burn your house)\b"),
    ("doxxing", r"\b(?:doxx|doxxing|leak your address|post your address|home address)\b"),
    ("financial_credentials", r"\b(?:credit card number|cvv|bank account number|otp|one[- ]time password|seed phrase|private key)\b"),
]
MEDIUM_PATTERNS = [
    ("harassment", r"\b(?:idiot|stupid|moron|loser|shut up|you suck|fake creator)\b"),
    ("scam_or_fraud", r"\b(?:scam|fraud|fraudster|crypto giveaway|double your money|guaranteed profit)\b"),
    ("legal_claim", r"\b(?:lawsuit|sue you|legal action|lawyer|court)\b"),
    ("reputation_claim", r"\b(?:fraud|thief|stole|stealing|cheat|cheater|criminal|exposed)\b"),
    ("sensitive_health", r"\b(?:diagnose|diagnosis|medicine|medication|dose|symptoms|cancer|pregnant|pregnancy|depression)\b"),
    ("sensitive_finance", r"\b(?:should i invest|investment advice|stock tip|options trade|loan advice|tax advice)\b"),
    ("personal_data_request", r"\b(?:phone number|address|email address|where do you live|exact location|personal number)\b"),
    ("promotion_or_spam", r"\b(?:dm me|check my page|follow me back|link in bio|make money fast|work from home|promo|collab)\b"),
]
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
REPEATED_RE = re.compile(r"(.)\1{7,}", re.IGNORECASE)

def _scan(text: str):
    text = (text or "").strip()
    lowered = text.lower()
    findings = []
    for category, pattern in HIGH_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE | re.DOTALL):
            findings.append(("high", category))
    for category, pattern in MEDIUM_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE | re.DOTALL):
            findings.append(("medium", category))
    if URL_RE.search(text) and len(text) < 180:
        findings.append(("medium", "external_link"))
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.85:
        findings.append(("medium", "excessive_caps"))
    if REPEATED_RE.search(text):
        findings.append(("medium", "repetitive_spam"))
    return findings

def assess_safety(comment: str, reply: str = "", content_context: str = "") -> dict:
    findings = _scan(comment)
    reply_findings = _scan(reply) if reply else []
    findings += reply_findings
    highest = "low"
    for level, _ in findings:
        if RISK_ORDER[level] > RISK_ORDER[highest]:
            highest = level
    categories = []
    for _, category in findings:
        if category not in categories:
            categories.append(category)
    reasons_map = {
        "self_harm": "Sensitive self-harm language requires careful human handling.",
        "credible_threat": "Threatening language requires human review.",
        "doxxing": "Potential doxxing or location exposure must not be automated.",
        "financial_credentials": "Potential financial credentials or secrets must not be handled by the reply agent.",
        "harassment": "The comment may be abusive or insulting.",
        "scam_or_fraud": "The comment may involve fraud, scams, or misleading financial claims.",
        "legal_claim": "Legal threats or claims should receive human review.",
        "reputation_claim": "Potential reputation or accusation risk needs human review.",
        "sensitive_health": "Health or medical questions need human review and careful wording.",
        "sensitive_finance": "Financial advice or investment claims need human review.",
        "personal_data_request": "The comment requests personal information.",
        "promotion_or_spam": "The comment may be promotional or spam-like.",
        "external_link": "The comment contains an external link and may be promotional or unsafe.",
        "excessive_caps": "The comment uses unusually aggressive all-caps formatting.",
        "repetitive_spam": "The comment contains repetitive spam-like text.",
    }
    reasons = [reasons_map[c] for c in categories if c in reasons_map]
    if highest == "high":
        action = "block_automation"
    elif highest == "medium":
        action = "human_review"
    else:
        action = "safe_to_suggest"
    context_lower = (content_context or "").lower()
    if highest == "low" and any(word in context_lower for word in ("sponsor", "brand", "partnership", "product", "review")):
        if any(x in (comment or "").lower() for x in ("fake", "scam", "refund", "stolen", "fraud")):
            highest = "medium"
            action = "human_review"
            if "reputation_claim" not in categories:
                categories.append("reputation_claim")
                reasons.append(reasons_map["reputation_claim"])
    return {"risk_level": highest, "categories": categories, "reasons": reasons,
            "action": action, "reply_flagged": bool(reply_findings)}

def assess_risk(comment: str) -> str:
    return assess_safety(comment)["risk_level"]
