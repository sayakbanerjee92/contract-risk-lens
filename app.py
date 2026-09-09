"""Contract Risk Lens: evidence-backed clause extraction and review prioritisation."""
from __future__ import annotations

import html
import io
import re
from collections import defaultdict

import pandas as pd
import streamlit as st

CATEGORY_RULES = {
    "Definitions": ["definition", "defined term", " means "],
    "Scope of Services": ["scope of services", "statement of work", "deliverable", "services"],
    "Fees and Payment": ["fee", "invoice", "payment", "billing", "charges", "tax"],
    "Intellectual Property": ["intellectual property", "ownership", "license", "copyright", "patent"],
    "Confidentiality": ["confidential", "non-disclosure", "nondisclosure"],
    "Data Protection": ["personal data", "personal information", "data protection", "privacy", "controller", "processor"],
    "Information Security": ["information security", "cybersecurity", "security incident", "breach", "encryption"],
    "Representations and Warranties": ["representation", "warranty", "warrants", "disclaimer"],
    "Indemnification": ["indemnif", "hold harmless", "defend"],
    "Limitation of Liability": ["limitation of liability", "liability cap", "consequential damages", "indirect damages"],
    "Insurance": ["insurance", "insured", "coverage"],
    "Term and Termination": ["termination", "terminate", "expiry", "expiration", " term "],
    "SLA / Service Levels": ["service level", "sla", "uptime", "availability", "service credit"],
    "Audit Rights": ["audit", "inspection rights", "inspect records"],
    "Subcontracting": ["subcontract", "subcontractor", "delegate"],
    "Compliance with Laws": ["applicable laws", "compliance", "anti-bribery", "sanctions", "export control"],
    "Non-Solicitation": ["non-solicit", "non solicit", "solicit employees"],
    "Publicity": ["publicity", "press release", "name and logo", "marketing"],
    "Dispute Resolution": ["arbitration", "mediation", "dispute resolution", "venue"],
    "Governing Law": ["governing law", "laws of"],
    "AI / Data Usage": ["artificial intelligence", "machine learning", "model training", "generative ai", "training data"],
}

BASE_RISK = {
    "Limitation of Liability": (5, "Critical"), "Indemnification": (5, "Critical"),
    "Data Protection": (5, "Critical"), "Information Security": (5, "Critical"),
    "AI / Data Usage": (5, "Critical"), "Intellectual Property": (4, "High"),
    "Fees and Payment": (4, "High"), "Term and Termination": (4, "High"),
    "Dispute Resolution": (4, "High"), "SLA / Service Levels": (3, "Moderate"),
    "Confidentiality": (3, "Moderate"), "Insurance": (3, "Moderate"),
}
ESCALATORS = ["unlimited", "without limitation", "sole discretion", "model training", "perpetual", "irrevocable", "all losses"]
HEADING = re.compile(r"(?mi)^\s*(?:(?:section|clause)\s+)?(?P<number>\d+(?:\.\d+){0,5}|[IVXLC]+|[A-Z])(?:\s*[.:)\-])?\s+(?P<title>[^\n]{3,150})\s*$")


def extract_text(uploaded: st.runtime.uploaded_file_manager.UploadedFile) -> str:
    raw = uploaded.getvalue()
    name = uploaded.name.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    if name.endswith(".docx"):
        from docx import Document
        document = Document(io.BytesIO(raw))
        paragraphs = "\n".join(p.text for p in document.paragraphs)
        tables = "\n".join(" | ".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows)
        return paragraphs + "\n" + tables
    return raw.decode("utf-8", errors="replace")


def split_clauses(text: str) -> list[dict]:
    """Preserve an exact source excerpt for each detected provision."""
    clean = re.sub(r"\r\n?", "\n", text)
    hits = list(HEADING.finditer(clean))
    clauses = []
    for position, hit in enumerate(hits):
        end = hits[position + 1].start() if position + 1 < len(hits) else len(clean)
        excerpt = clean[hit.start():end].strip()
        if len(excerpt) >= 35:
            clauses.append({
                "number": hit.group("number").rstrip("."),
                "title": hit.group("title").strip(),
                "text": excerpt,
                "source_start": hit.start(),
                "source_end": end,
            })
    if clauses:
        return clauses
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean) if len(p.strip()) >= 80]
    return [{"number": "Not numbered", "title": p[:90].split(".")[0], "text": p, "source_start": clean.find(p), "source_end": clean.find(p) + len(p)} for p in paragraphs]


def categories_for(clause: dict) -> list[str]:
    corpus = f" {clause['title']} {clause['text']} ".lower()
    found = [category for category, terms in CATEGORY_RULES.items() if any(term in corpus for term in terms)]
    return found or ["Miscellaneous"]


def affected_parties(text: str) -> str:
    corpus = text.lower(); found = []
    if any(term in corpus for term in ("customer", "client")): found.append("Customer")
    if any(term in corpus for term in ("supplier", "vendor", "service provider", "contractor")): found.append("Service Provider")
    if any(term in corpus for term in ("each party", "either party", "both parties")): found.append("Both parties")
    return ", ".join(found) or "Not expressly identifiable"


def score_clause(category: str, text: str) -> tuple[int, str, list[str]]:
    score, level = BASE_RISK.get(category, (2, "Low"))
    corpus = text.lower()
    triggers = [word for word in ESCALATORS if word in corpus]
    if triggers:
        score = min(5, score + 1)
        level = "Critical" if score >= 5 else "High"
    return score, level, triggers


def improvement_focus(category: str, text: str, triggers: list[str]) -> str:
    corpus = text.lower()
    library = {
        "Limitation of Liability": "Confirm an aggregate, clearly quantified liability cap; define the cap base and carve-outs; exclude indirect/consequential loss only where commercially acceptable.",
        "Indemnification": "Narrow covered claims, connect the duty to third-party claims, set defence-control and settlement-consent rules, and align any indemnity with the liability cap or agreed carve-outs.",
        "Data Protection": "Confirm controller/processor roles, permitted processing instructions, subprocessor controls, cross-border transfer terms, breach notice timing, and deletion/return obligations.",
        "Information Security": "Specify minimum security measures, incident notification timing, remediation cooperation, audit evidence, and responsibility for security failures.",
        "AI / Data Usage": "State whether customer data may be used for AI training or service improvement; prohibit use unless expressly approved, and add opt-out, confidentiality, retention, and deletion controls.",
        "Intellectual Property": "Separate background IP from deliverables, state ownership or licence scope, ensure required assignment language, and protect each party's pre-existing materials.",
        "Fees and Payment": "Confirm price, currency, tax treatment, invoice dispute process, payment timing, late-fee limits, and whether any change-control process governs additional charges.",
        "Term and Termination": "Clarify the initial term, renewal, termination-for-cause and convenience rights, cure periods, transition assistance, and consequences on exit.",
        "SLA / Service Levels": "Define measurable service levels, measurement method, exclusions, reporting, severity-based response/restoration times, and service-credit remedies.",
        "Confidentiality": "Define confidential information, permitted recipients and exceptions, required safeguards, survival period, and return/deletion obligations.",
        "Dispute Resolution": "Specify escalation, mediation/arbitration or court process, forum, language, costs, and interim-relief rights.",
    }
    focus = library.get(category, "Verify the operative obligation, exceptions, remedies, notice requirements, and allocation of cost/risk against the business position.")
    absent = []
    if category == "Limitation of Liability" and not any(term in corpus for term in ("cap", "maximum", "aggregate")): absent.append("No express cap wording was detected")
    if category == "Data Protection" and "breach" not in corpus: absent.append("No breach-notice wording was detected")
    if category == "AI / Data Usage" and not any(term in corpus for term in ("consent", "approval", "opt-out", "prohibit")): absent.append("No explicit consent/opt-out safeguard was detected")
    signals = triggers + absent
    return focus + (" Screening signal: " + "; ".join(signals) + "." if signals else "")


def priority_reason(category: str, level: str, triggers: list[str], text: str) -> str:
    reasons = {
        "Limitation of Liability": "the clause can determine the maximum financial exposure and whether important loss categories are recoverable",
        "Indemnification": "the clause can shift third-party claim, defence, settlement, and reimbursement exposure",
        "Data Protection": "the clause can allocate regulated personal-data obligations and incident exposure",
        "Information Security": "the clause can set the security baseline and responsibility for a security incident",
        "AI / Data Usage": "the clause can permit or restrict reuse of customer data for training, analytics, or service improvement",
        "Intellectual Property": "the clause can allocate ownership and use rights in deliverables and pre-existing materials",
        "Fees and Payment": "the clause can create material pricing, timing, tax, and collection consequences",
        "Term and Termination": "the clause can control exit rights, cure opportunities, renewal, and transition obligations",
        "SLA / Service Levels": "the clause can set measurable performance commitments and the remedy for failure",
        "Confidentiality": "the clause can control protection and disclosure of commercially sensitive information",
        "Dispute Resolution": "the clause can determine the path, forum, cost, and speed of enforcement",
    }
    paint = {"Critical": "red", "High": "orange", "Moderate": "amber", "Low": "green"}[level]
    reason = reasons.get(category, "the clause allocates an express operational, legal, or commercial responsibility")
    detail = f"{paint.title()} priority: {category} is rated {level.lower()} because {reason}."
    if triggers:
        detail += " The exact wording also contains escalation signal(s): " + ", ".join(triggers) + "."
    return detail


def drafting_direction(category: str) -> str:
    directions = {
        "Limitation of Liability": "Draft toward an explicit aggregate cap: identify the cap amount or fee-based formula, the claim period, the damages excluded, and any expressly negotiated carve-outs.",
        "Indemnification": "Draft a closed list of covered third-party claims; state who controls defence, when settlement needs consent, and how this obligation interacts with the liability cap.",
        "Data Protection": "Draft a data-processing schedule covering roles, instructions, subprocessors, international transfers, security, breach notice, assistance, and deletion/return of personal data.",
        "Information Security": "Draft measurable baseline controls and incident language: security standard, notice deadline, investigation/remediation cooperation, and evidence/reporting obligations.",
        "AI / Data Usage": "Draft an express permission boundary: prohibit training or service-improvement use of Customer Data unless prior written consent is given; include retention, deletion, confidentiality, and opt-out terms.",
        "Intellectual Property": "Draft separate provisions for background IP and deliverables, then specify ownership/assignment or licence scope, permitted use, and any residual rights.",
        "Fees and Payment": "Draft the commercial mechanics in one place: price, currency, tax, invoice prerequisites, payment date, dispute window, late charges, and change-control approval.",
        "Term and Termination": "Draft clear trigger-and-consequence language: term, renewal, notice, cure period, termination rights, survival, handover, and payment on exit.",
        "SLA / Service Levels": "Draft objective measurement and remedy language: metric, measurement window, exclusions, reporting, severity timetable, service credits, and escalation path.",
        "Confidentiality": "Draft the protected-information definition, permitted disclosures, safeguards, exceptions, survival period, and return/destruction mechanism.",
        "Dispute Resolution": "Draft a stepped process: business escalation, mediation/arbitration or court, governing forum, language, costs, and urgent-relief rights.",
    }
    return directions.get(category, "Draft the operative obligation, scope, exceptions, notice, remedy, and cost allocation explicitly rather than leaving them to implication.")

def highlight_evidence(text: str, category: str, triggers: list[str]) -> str:
    escaped = html.escape(text)
    terms = list(CATEGORY_RULES.get(category, [])) + triggers
    for term in sorted(set(term for term in terms if term.strip()), key=len, reverse=True):
        escaped = re.sub(re.escape(html.escape(term)), lambda m: f"<mark>{m.group(0)}</mark>", escaped, flags=re.I)
    return escaped.replace("\n", "<br>")


def analyze(text: str) -> pd.DataFrame:
    rows = []
    for clause in split_clauses(text):
        refs = re.findall(r"\b(?:section|clause)\s+(\d+(?:\.\d+)*)", clause["text"], flags=re.I)
        for category in categories_for(clause):
            score, level, triggers = score_clause(category, clause["text"])
            rows.append({
                "Clause number": clause["number"], "Clause title": clause["title"], "Relevant text": clause["text"],
                "Provision category": category, "Parties affected": affected_parties(clause["text"]),
                "Related clauses": ", ".join(dict.fromkeys(refs)) or "None identified",
                "Risk score": score, "Risk level": level,
                "Evidence verified": clause["text"] in text,
                "Why this is priority": priority_reason(category, level, triggers, clause["text"]),
                "Review focus / suggested improvement": improvement_focus(category, clause["text"], triggers),
                "Drafting direction": drafting_direction(category),
                "Evidence highlights": highlight_evidence(clause["text"], category, triggers),
            })
    return pd.DataFrame(rows)


CLIENT_PROTECTIONS = [
    ("Scope of Services", "High", "No scope / delivery clause was classified", "Add a statement-of-work, acceptance, dependency, change-control, and remedy framework so the client can measure and enforce delivery."),
    ("Fees and Payment", "High", "No fees and payment clause was classified", "Add fixed or clearly governed pricing, invoicing prerequisites, a dispute mechanism, withholding rights for disputed amounts, and approval for change charges."),
    ("Intellectual Property", "Critical", "No intellectual-property clause was classified", "Add ownership or licence language for deliverables, assignment mechanics where needed, background-IP treatment, and a warranty that the client can use the deliverables without infringement."),
    ("Confidentiality", "High", "No confidentiality clause was classified", "Add mutual confidentiality obligations, permitted-recipient controls, security safeguards, return/deletion rights, and survival after termination."),
    ("Data Protection", "Critical", "No data-protection clause was classified", "Add a data-processing schedule: roles, instructions, subprocessors, transfers, breach notice, assistance, and deletion/return obligations."),
    ("Information Security", "Critical", "No information-security clause was classified", "Add measurable security standards, incident notice and remediation duties, audit evidence, and responsibility for security failures."),
    ("Indemnification", "Critical", "No indemnification clause was classified", "Add client-favourable third-party IP infringement and data/security claim indemnities, together with defence-control and settlement-consent protections."),
    ("Limitation of Liability", "Critical", "No limitation-of-liability clause was classified", "Add a negotiated liability cap, clear carve-outs for the most serious risks, and an exclusion of remote or indirect losses appropriate to the transaction."),
    ("SLA / Service Levels", "High", "No service-level clause was classified", "Add objective service levels, reporting, response/restoration targets, service credits, escalation, and repeated-failure termination rights."),
    ("Audit Rights", "Moderate", "No audit-rights clause was classified", "Add proportionate rights to obtain compliance evidence and audit relevant records, security controls, and subcontractor performance."),
    ("Subcontracting", "High", "No subcontracting clause was classified", "Require prior notice or consent for material subcontractors, flow-down of obligations, and continuing supplier responsibility for subcontractor acts and omissions."),
    ("Term and Termination", "High", "No term and termination clause was classified", "Add defined term and renewal mechanics, breach cure periods, client termination rights, transition assistance, data return, and survival provisions."),
    ("AI / Data Usage", "Critical", "No AI/data-usage clause was classified", "Add an express restriction on using client data for model training or service improvement without prior written consent, plus retention, deletion, and confidentiality controls."),
]


def client_coverage_gaps(results: pd.DataFrame) -> list[dict]:
    detected = set(results["Provision category"].tolist())
    gaps = []
    for category, level, reason, direction in CLIENT_PROTECTIONS:
        if category not in detected:
            gaps.append({"category": category, "level": level, "reason": reason, "direction": direction})
    return gaps


def coverage_gap_card(gap: dict) -> str:
    colour = {"Critical": "#a43d3d", "High": "#c36a2d", "Moderate": "#b58a24"}[gap["level"]]
    return f'''<section style="background:#fff;border:1px solid #d9e1e7;border-left:8px solid {colour};border-radius:10px;padding:14px 16px;margin:10px 0;">
    <b style="color:{colour}">{gap['level'].upper()} CLIENT PROTECTION GAP · {html.escape(gap['category'])}</b>
    <p style="margin:8px 0"><b>Why consider adding it:</b> {html.escape(gap['reason'])}. This is a detection result, not proof that the agreement has no equivalent protection—confirm against the source.</p>
    <div style="background:#eef5f7;border-radius:6px;padding:10px 12px"><b>Client-side drafting direction:</b> {html.escape(gap['direction'])}</div></section>'''

COUNTERPARTY_PROTECTIONS = [
    ("Customer", "Data Protection", "Critical", "The Customer role is traced, but no data-protection provision was classified.", "From the Customer perspective, add processor instructions, breach timing, deletion/return, subprocessor controls, and remedies for non-compliance."),
    ("Customer", "SLA / Service Levels", "High", "The Customer role is traced, but no service-level provision was classified.", "From the Customer perspective, add measurable performance standards, reporting, credits, escalation, and repeated-failure exit rights."),
    ("Customer", "Audit Rights", "Moderate", "The Customer role is traced, but no audit-rights provision was classified.", "From the Customer perspective, add proportionate access to assurance reports, relevant records, and remediation evidence."),
    ("Service Provider", "Scope of Services", "High", "The Service Provider role is traced, but no scope/acceptance provision was classified.", "From the Service Provider perspective, add a precise scope, customer dependencies, acceptance criteria, exclusions, and a written change-control process."),
    ("Service Provider", "Fees and Payment", "High", "The Service Provider role is traced, but no payment provision was classified.", "From the Service Provider perspective, add clear price, invoice timing, payment due date, dispute process, suspension guardrails, and recovery of undisputed sums."),
    ("Service Provider", "Limitation of Liability", "Critical", "The Service Provider role is traced, but no limitation-of-liability provision was classified.", "From the Service Provider perspective, add an aggregate liability cap, defined exclusions of remote loss, claim period, and proportionate carve-outs."),
    ("Service Provider", "Intellectual Property", "High", "The Service Provider role is traced, but no IP allocation was classified.", "From the Service Provider perspective, reserve background tools and know-how, then define the client licence or deliverable ownership precisely."),
    ("Both parties", "Confidentiality", "High", "Both-party obligations are traced, but no confidentiality provision was classified.", "For both parties, add a mutual confidentiality framework with permitted recipients, safeguards, exceptions, survival, and return/deletion duties."),
    ("Both parties", "Dispute Resolution", "High", "Both-party obligations are traced, but no dispute-resolution provision was classified.", "For both parties, add an escalation path, chosen forum or arbitration procedure, governing law, costs, and urgent-relief rights."),
]


def traced_roles(results: pd.DataFrame) -> set[str]:
    roles = set()
    for value in results["Parties affected"].dropna():
        for role in str(value).split(", "):
            if role in {"Customer", "Service Provider", "Both parties"}:
                roles.add(role)
    if "Both parties" in roles:
        roles.update({"Customer", "Service Provider"})
    return roles


def counterparty_coverage_gaps(results: pd.DataFrame) -> list[dict]:
    roles = traced_roles(results)
    detected = set(results["Provision category"].tolist())
    gaps = []
    for role, category, level, reason, direction in COUNTERPARTY_PROTECTIONS:
        applicable = role in roles or (role == "Both parties" and {"Customer", "Service Provider"}.issubset(roles))
        if applicable and category not in detected:
            gaps.append({"role": role, "category": category, "level": level, "reason": reason, "direction": direction})
    return gaps


def counterparty_gap_card(gap: dict) -> str:
    colour = {"Critical": "#a43d3d", "High": "#c36a2d", "Moderate": "#b58a24"}[gap["level"]]
    return f'''<section style="background:#fff;border:1px solid #d9e1e7;border-left:8px solid {colour};border-radius:10px;padding:14px 16px;margin:10px 0;">
    <b style="color:{colour}">{gap['level'].upper()} · {html.escape(gap['role'])} PERSPECTIVE · {html.escape(gap['category'])}</b>
    <p style="margin:8px 0"><b>Why this counterparty needs it:</b> {html.escape(gap['reason'])}</p>
    <div style="background:#eef5f7;border-radius:6px;padding:10px 12px"><b>Drafting direction for this role:</b> {html.escape(gap['direction'])}</div></section>'''

PERSPECTIVE_FOCUS = {
    "Client / Customer": {
        "Limitation of Liability": "Check whether the cap, exclusions, and carve-outs leave the Client without a meaningful remedy for the stated failure.",
        "Indemnification": "Check whether the Client receives a clear defence and reimbursement right for the risks described in the clause.",
        "Data Protection": "Check whether the Client has enforceable controls over its data, incident notification, and downstream processing.",
        "Information Security": "Check whether the Client receives measurable safeguards, timely incident notice, and remediation cooperation.",
        "SLA / Service Levels": "Check whether performance commitments, reporting, and remedies are measurable and enforceable.",
        "Intellectual Property": "Check whether the Client obtains the ownership or licence rights it needs to use the deliverables.",
        "Fees and Payment": "Check whether pricing, approvals, invoice disputes, and payment triggers are sufficiently controlled.",
        "Term and Termination": "Check whether exit rights, transition support, and post-termination data/deliverable rights protect continuity.",
    },
    "Service Provider / Company": {
        "Limitation of Liability": "Check whether the clause contains a defined aggregate cap, loss exclusions, claim period, and carefully scoped carve-outs.",
        "Indemnification": "Check whether covered claims, defence control, settlement approval, and any cap treatment are bounded.",
        "Data Protection": "Check whether processing obligations are tied to documented instructions and realistic operational commitments.",
        "Information Security": "Check whether security requirements, audit scope, and incident duties are specific and achievable.",
        "SLA / Service Levels": "Check whether metrics, exclusions, service credits, and dependency assumptions prevent open-ended performance exposure.",
        "Intellectual Property": "Check whether background tools, know-how, and third-party materials are reserved and the customer grant is clear.",
        "Fees and Payment": "Check whether price, billing prerequisites, payment timing, disputed sums, and change control protect collection.",
        "Term and Termination": "Check whether cure periods, suspension/termination rights, exit scope, and payment consequences are balanced.",
    },
}


def party_sentences(text: str, terms: tuple[str, ...]) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\\s+|\\n+", text)
    return [sentence.strip() for sentence in sentences if any(re.search(r"\\b" + re.escape(term) + r"\\b", sentence, flags=re.I) for term in terms)][:2]


def perspective_lens(row: pd.Series) -> dict[str, dict[str, str]]:
    category, source = row["Provision category"], row["Relevant text"]
    client_cues = party_sentences(source, ("customer", "client"))
    provider_cues = party_sentences(source, ("supplier", "vendor", "service provider", "contractor", "company"))
    output = {}
    for label, cues in (("Client / Customer", client_cues), ("Service Provider / Company", provider_cues)):
        source_cue = " ".join(cues)
        if source_cue:
            evidence = "Source cue: " + source_cue
        else:
            evidence = "No explicit " + ("Customer/Client" if label.startswith("Client") else "Service Provider/Company") + " reference was detected in this excerpt; this is a category-based review prompt, not an allocation finding."
        focus = PERSPECTIVE_FOCUS.get(label, {}).get(category, "Check the operative obligation, exceptions, remedies, notice terms, and cost/risk allocation from this party's position.")
        output[label] = {"evidence": evidence, "focus": focus}
    return output


ALLOCATION_SIGNAL_SPECS = [
    ("Client / Customer obligation", "client-duty", r"\b(?:customer|client)\s+(?:shall|must|will|is required to|agrees to)\b"),
    ("Client / Customer right", "client-right", r"\b(?:customer|client)\s+(?:may|has (?:the )?right to|is entitled to)\b"),
    ("Service Provider / Company obligation", "provider-duty", r"\b(?:service provider|supplier|vendor|contractor|company)\s+(?:shall|must|will|is required to|agrees to)\b"),
    ("Service Provider / Company right", "provider-right", r"\b(?:service provider|supplier|vendor|contractor|company)\s+(?:may|has (?:the )?right to|is entitled to)\b"),
    ("Mutual obligation", "mutual-duty", r"\b(?:each party|either party|both parties)\s+(?:shall|must|will|agrees to)\b"),
]


def allocation_signals(text: str) -> list[dict[str, str]]:
    signals, seen = [], set()
    for label, css_class, pattern in ALLOCATION_SIGNAL_SPECS:
        for match in re.finditer(pattern, text, flags=re.I):
            cue = match.group(0)
            key = (label, cue.lower())
            if key not in seen:
                signals.append({"label": label, "cue": cue, "class": css_class})
                seen.add(key)
    return signals


def allocation_finding(text: str) -> dict[str, str]:
    signals = allocation_signals(text)
    labels = {item["label"] for item in signals}
    client = any(label.startswith("Client") for label in labels)
    provider = any(label.startswith("Service Provider") for label in labels)
    mutual = "Mutual obligation" in labels
    if client and provider:
        finding = "Mixed allocation: the excerpt contains express Client/Customer and Service Provider/Company operative signals."
    elif client:
        finding = "Client/Customer-side allocation signal: the excerpt expressly places a duty or right on the Client/Customer; check whether the reciprocal provider protection is stated."
    elif provider:
        finding = "Service Provider/Company-side allocation signal: the excerpt expressly places a duty or right on the Service Provider/Company; check whether the reciprocal client protection is stated."
    elif mutual:
        finding = "Mutual allocation signal: the excerpt uses an express both-party obligation; verify whether the duties and remedies are genuinely reciprocal."
    else:
        finding = "Allocation unclear: no express party-plus-duty/right signal was detected in this excerpt. Do not treat this as proof of a missing obligation."
    client_focus = "Client lens: " + ("confirm the provider's stated duty/right gives the Client an enforceable protection and remedy." if provider or mutual else "identify whether the Client is carrying a duty without an express counterbalancing provider obligation, right, or remedy.")
    provider_focus = "Service Provider lens: " + ("confirm the Client's stated duty/right is bounded by dependencies, approvals, timing, and remedies." if client or mutual else "identify whether the Service Provider is carrying a duty without a defined cap, exclusion, dependency, or customer cooperation obligation.")
    return {"finding": finding, "client_focus": client_focus, "provider_focus": provider_focus}


def allocation_marked_text(text: str) -> str:
    marked = html.escape(text)
    for _, css_class, pattern in ALLOCATION_SIGNAL_SPECS:
        marked = re.sub(pattern, lambda match: f'<span class="{css_class}">{match.group(0)}</span>', marked, flags=re.I)
    return marked.replace("\n", "<br>")


def allocation_graph_panel(row: pd.Series) -> str:
    finding = allocation_finding(row["Relevant text"])
    excerpt = allocation_marked_text(row["Relevant text"])[:2200]
    return f'''<section style="margin:10px 0 12px;padding:12px;border:1px solid #cad6df;border-radius:8px;background:#f8fafc">
    <b>Allocation finding graph</b><div style="display:flex;gap:7px;flex-wrap:wrap;margin:8px 0"><span style="padding:4px 7px;background:#fff3cf;border-radius:5px">1. Source wording</span><span>→</span><span style="padding:4px 7px;background:#e9edf2;border-radius:5px">2. Allocation finding</span><span>→</span><span style="padding:4px 7px;background:#eaf3ff;border-radius:5px">3. Client lens</span><span>→</span><span style="padding:4px 7px;background:#f3ecff;border-radius:5px">4. Provider lens</span></div>
    <p style="margin:6px 0"><b>Finding:</b> {html.escape(finding['finding'])}</p><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:8px"><div style="background:#eaf3ff;padding:8px;border-radius:6px"><b>Client / Customer gap check</b><br>{html.escape(finding['client_focus'])}</div><div style="background:#f3ecff;padding:8px;border-radius:6px"><b>Service Provider / Company gap check</b><br>{html.escape(finding['provider_focus'])}</div></div>
    <div style="margin-top:9px;background:#fff;padding:9px;border-radius:6px;line-height:1.6"><b>Allocation-marked source:</b><br>{excerpt}</div>
    <style>.client-duty{background:#bddcff;color:#082f5f;font-weight:700;padding:1px 3px;border-radius:3px}.client-right{background:#8fc5ff;color:#082f5f;font-weight:700;padding:1px 3px;border-radius:3px}.provider-duty{background:#dec8ff;color:#3d176f;font-weight:700;padding:1px 3px;border-radius:3px}.provider-right{background:#c09bff;color:#3d176f;font-weight:700;padding:1px 3px;border-radius:3px}.mutual-duty{background:#d6eadb;color:#16482a;font-weight:700;padding:1px 3px;border-radius:3px}</style></section>'''

def perspective_panels(row: pd.Series) -> str:
    lenses = perspective_lens(row)
    client, provider = lenses["Client / Customer"], lenses["Service Provider / Company"]
    return f'''<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin:10px 0 12px">
    <div style="background:#eaf3ff;border-left:5px solid #2463a6;border-radius:7px;padding:10px 12px"><b style="color:#174c83">CLIENT / CUSTOMER LENS</b><br><span style="font-size:0.92em"><b>Evidence:</b> {html.escape(client['evidence'])}</span><br><span style="font-size:0.92em"><b>Prima-facie review:</b> {html.escape(client['focus'])}</span></div>
    <div style="background:#f3ecff;border-left:5px solid #7043a6;border-radius:7px;padding:10px 12px"><b style="color:#563182">SERVICE PROVIDER / COMPANY LENS</b><br><span style="font-size:0.92em"><b>Evidence:</b> {html.escape(provider['evidence'])}</span><br><span style="font-size:0.92em"><b>Prima-facie review:</b> {html.escape(provider['focus'])}</span></div></div>'''

def review_card(row: pd.Series) -> str:
    colour = {"Critical": "#a43d3d", "High": "#c36a2d", "Moderate": "#b58a24", "Low": "#3e7d67"}[row["Risk level"]]
    party_lenses = perspective_lens(row)
    excerpt = row["Evidence highlights"][:2200]
    return f'''<section style="background:#fff;border:1px solid #d9e1e7;border-left:8px solid {colour};border-radius:10px;padding:16px 18px;margin:12px 0;">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;"><div><b>Clause {html.escape(str(row['Clause number']))} · {html.escape(row['Clause title'])}</b><br><span style="color:#536470">{html.escape(row['Provision category'])} · {html.escape(row['Parties affected'])}</span></div><b style="color:{colour}">{row['Risk level'].upper()} · {row['Risk score']}/5</b></div>
    <p style="margin:12px 0 6px;color:{colour}"><b>Why this paint / priority:</b> {html.escape(row['Why this is priority'])}</p>{allocation_graph_panel(row)}{perspective_panels(row)}<p style="margin:8px 0 6px;color:#6d3f20"><b>Review focus:</b> {html.escape(row['Review focus / suggested improvement'])}</p><div style="background:#eef5f7;border-radius:6px;padding:10px 12px;line-height:1.55"><b>Drafting direction:</b> {html.escape(row['Drafting direction'])}</div>
    <div style="background:#fff8e9;padding:10px 12px;border-radius:6px;line-height:1.6"><b>Evidence from the agreement:</b><br>{excerpt}</div>
    <style>mark{{background:#ffd166;color:#1c2730;font-weight:700;padding:1px 2px;border-radius:2px}}</style></section>'''

st.set_page_config(page_title="Contract Risk Lens", page_icon="⚖️", layout="wide")
st.markdown("""<style>.stApp{background:#f4f6f8}.hero{background:linear-gradient(120deg,#102a43,#1f4e5f);color:white;padding:2rem;border-radius:14px;margin-bottom:1rem}.stDataFrame{background:white}</style><div class='hero'><h1>⚖️ Contract Risk Lens</h1><p>Evidence-backed clause extraction, priority review, and improvement guidance for IT services agreements.</p></div>""", unsafe_allow_html=True)
st.caption("Local rule-based analysis: no LLM or API key. Results are screening prompts and require qualified legal review.")
with st.sidebar:
    st.header("Review guide")
    st.write("Upload a searchable PDF, DOCX, or TXT agreement. Every displayed excerpt is retained from the uploaded source; scanned PDFs need OCR first.")
    st.warning("Red/orange cards require priority review. Yellow highlighting marks the category terms and risk escalators found in the source wording.")

uploaded = st.file_uploader("Upload a contract", type=["pdf", "docx", "txt"])
if uploaded:
    try:
        source_text = extract_text(uploaded)
        if not source_text.strip(): st.error("No readable text was found. Apply OCR to a scanned PDF before upload."); st.stop()
        results = analyze(source_text)
        if results.empty: st.warning("No provisions were detected. Review the extracted text and document structure."); st.stop()
        critical = int((results["Risk level"] == "Critical").sum()); high = int((results["Risk level"] == "High").sum())
        a,b,c,d = st.columns(4); a.metric("Evidence-backed provisions", len(results)); b.metric("Critical review items", critical); c.metric("High-priority items", high); d.metric("Verified excerpts", f"{int(results['Evidence verified'].sum())}/{len(results)}")
        selected = st.multiselect("Filter provision categories", sorted(results["Provision category"].unique()), default=sorted(results["Provision category"].unique()))
        view = results[results["Provision category"].isin(selected)].sort_values(["Risk score", "Clause number"], ascending=[False, True])
        st.subheader("Priority evidence review")
        st.caption("The paint explains urgency: red = highest potential financial/regulatory exposure, orange = material commercial allocation, amber = meaningful operating obligation, green = lower-priority allocation. Each card now follows a source → allocation finding → Client lens → Service Provider lens graph. Blue highlights mark Client/Customer duty/right wording, purple highlights mark Service Provider/Company wording, and green highlights mark express mutual duties.")
        for _, row in view.iterrows(): st.markdown(review_card(row), unsafe_allow_html=True)
        gaps = client_coverage_gaps(results)
        st.subheader("Core agreement coverage gaps — suggested provisions to add")
        st.caption("These are agreement-specific suggestions: the app did not classify a clause in the uploaded text under the listed category. They are not findings that a legal protection is definitely absent.")
        if gaps:
            for gap in gaps: st.markdown(coverage_gap_card(gap), unsafe_allow_html=True)
        else:
            st.success("The app detected all core client-protection categories in this agreement. Verify clause adequacy and exceptions in the priority cards above.")
        roles = traced_roles(results)
        st.subheader("Counterparty-balanced coverage gaps")
        st.caption("Roles traced in this agreement: " + (", ".join(sorted(roles)) if roles else "No role could be confidently traced") + ". These suggestions are role-specific and appear only where the related provision was not classified.")
        role_gaps = counterparty_coverage_gaps(results)
        if role_gaps:
            for gap in role_gaps: st.markdown(counterparty_gap_card(gap), unsafe_allow_html=True)
        else:
            st.success("No role-specific gaps were identified for the counterparties traced by the app. Review the clause-level cards for adequacy and exceptions.")
        st.subheader("Structured review table")
        st.dataframe(view.drop(columns=["Evidence highlights"]), use_container_width=True, hide_index=True, column_config={"Relevant text":st.column_config.TextColumn(width="large"),"Risk score":st.column_config.ProgressColumn(min_value=1,max_value=5,format="%d/5")})
        st.download_button("Download evidence review as CSV", view.drop(columns=["Evidence highlights"]).to_csv(index=False).encode("utf-8"), "contract_evidence_review.csv", "text/csv")
        with st.expander("Extracted source text"): st.text(source_text)
    except Exception as exc:
        st.error(f"The document could not be processed: {exc}")
else:
    st.info("Choose a contract to begin.")
