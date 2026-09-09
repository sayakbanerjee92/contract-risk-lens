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
                "Review focus / suggested improvement": improvement_focus(category, clause["text"], triggers),
                "Evidence highlights": highlight_evidence(clause["text"], category, triggers),
            })
    return pd.DataFrame(rows)


def review_card(row: pd.Series) -> str:
    colour = {"Critical": "#a43d3d", "High": "#c36a2d", "Moderate": "#b58a24", "Low": "#3e7d67"}[row["Risk level"]]
    excerpt = row["Evidence highlights"][:2200]
    return f'''<section style="background:#fff;border:1px solid #d9e1e7;border-left:8px solid {colour};border-radius:10px;padding:16px 18px;margin:12px 0;">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;"><div><b>Clause {html.escape(str(row['Clause number']))} · {html.escape(row['Clause title'])}</b><br><span style="color:#536470">{html.escape(row['Provision category'])} · {html.escape(row['Parties affected'])}</span></div><b style="color:{colour}">{row['Risk level'].upper()} · {row['Risk score']}/5</b></div>
    <p style="margin:12px 0 6px;color:#6d3f20"><b>Review focus / improvement:</b> {html.escape(row['Review focus / suggested improvement'])}</p>
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
        st.caption("Each card links the detected clause number and title to exact source wording, an explicit risk signal, and a suggested negotiation/review action.")
        for _, row in view.iterrows(): st.markdown(review_card(row), unsafe_allow_html=True)
        st.subheader("Structured review table")
        st.dataframe(view.drop(columns=["Evidence highlights"]), use_container_width=True, hide_index=True, column_config={"Relevant text":st.column_config.TextColumn(width="large"),"Risk score":st.column_config.ProgressColumn(min_value=1,max_value=5,format="%d/5")})
        st.download_button("Download evidence review as CSV", view.drop(columns=["Evidence highlights"]).to_csv(index=False).encode("utf-8"), "contract_evidence_review.csv", "text/csv")
        with st.expander("Extracted source text"): st.text(source_text)
    except Exception as exc:
        st.error(f"The document could not be processed: {exc}")
else:
    st.info("Choose a contract to begin.")
