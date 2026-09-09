"""Contract Risk Lens — local, evidence-backed contract clause screening."""
from __future__ import annotations

import io
import re
import pandas as pd
import streamlit as st

CATEGORIES = {
    "Definitions": ["definition", "defined term", " means "],
    "Scope of Services": ["scope of services", "statement of work", "deliverable", "services"],
    "Fees and Payment": ["fee", "invoice", "payment", "billing", "charges", "tax"],
    "Intellectual Property": ["intellectual property", "ownership", "license", "copyright", "patent"],
    "Confidentiality": ["confidential", "non-disclosure", "nondisclosure"],
    "Data Protection": ["personal data", "personal information", "data protection", "privacy", "controller", "processor"],
    "Information Security": ["information security", "cybersecurity", "security incident", "breach", "encryption"],
    "Representations and Warranties": ["representation", "warranty", "warrants", "disclaimer"],
    "Indemnification": ["indemnif", "hold harmless"],
    "Limitation of Liability": ["limitation of liability", "liability", "consequential damages", "indirect damages"],
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
RISK = {
    "Limitation of Liability": (5, "Critical"), "Indemnification": (5, "Critical"),
    "Data Protection": (5, "Critical"), "Information Security": (5, "Critical"),
    "AI / Data Usage": (5, "Critical"), "Intellectual Property": (4, "High"),
    "Fees and Payment": (4, "High"), "Term and Termination": (4, "High"),
    "Dispute Resolution": (4, "High"), "SLA / Service Levels": (3, "Moderate"),
    "Confidentiality": (3, "Moderate"), "Insurance": (3, "Moderate"),
}
HEADING = re.compile(r"(?m)^\s*((?:\d+(?:\.\d+){0,4}|[IVXLC]+|[A-Z])\.?)(?:\s*[-:.)])?\s+([^\n]{2,140})\s*$")

def read_document(uploaded):
    raw = uploaded.getvalue()
    if uploaded.name.lower().endswith(".pdf"):
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    if uploaded.name.lower().endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs)
    return raw.decode("utf-8", errors="replace")

def clauses(text):
    text = re.sub(r"\r\n?", "\n", text)
    matches = list(HEADING.finditer(text))
    found = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start():end].strip()
        if len(body) >= 35:
            found.append({"number": match.group(1).rstrip("."), "title": match.group(2).strip(), "text": body})
    if found:
        return found
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 80]
    return [{"number": "Not numbered", "title": p[:80].split(".")[0], "text": p} for p in paragraphs]

def parties(text):
    low = text.lower(); answer = []
    if any(x in low for x in ["customer", "client"]): answer.append("Customer")
    if any(x in low for x in ["supplier", "vendor", "service provider", "contractor"]): answer.append("Service Provider")
    if any(x in low for x in ["each party", "either party", "parties"]): answer.append("Both parties")
    return ", ".join(answer) or "Not expressly identifiable"

def analyze(text):
    rows = []
    for clause in clauses(text):
        corpus = f" {clause['title']} {clause['text']} ".lower()
        categories = [name for name, terms in CATEGORIES.items() if any(term in corpus for term in terms)] or ["Miscellaneous"]
        refs = re.findall(r"\b(?:Section|Clause)\s+(\d+(?:\.\d+)*)", clause["text"], re.I)
        for category in categories:
            score, level = RISK.get(category, (2, "Low"))
            if any(term in corpus for term in ["unlimited", "without limitation", "sole discretion", "model training"]):
                score, level = min(5, score + 1), "Critical" if score >= 4 else level
            rows.append({
                "Clause number": clause["number"], "Clause title": clause["title"], "Relevant text": clause["text"],
                "Provision category": category, "Parties affected": parties(clause["text"]),
                "Related clauses": ", ".join(dict.fromkeys(refs)) or "None identified",
                "Risk score": score, "Risk level": level,
                "Review focus": "Verify the exact wording, applicability, remedies, exceptions, and commercial impact in the original agreement.",
            })
    return pd.DataFrame(rows)

st.set_page_config(page_title="Contract Risk Lens", page_icon="⚖️", layout="wide")
st.markdown("""<style>.stApp{background:#f4f6f8}.hero{background:linear-gradient(120deg,#102a43,#1f4e5f);color:white;padding:2rem;border-radius:14px;margin-bottom:1rem}.risk{border-radius:10px;padding:.7rem;background:white;border-left:6px solid #c36a2d}</style><div class='hero'><h1>⚖️ Contract Risk Lens</h1><p>Evidence-backed, local-first clause extraction and risk screening for IT services agreements.</p></div>""", unsafe_allow_html=True)
st.caption("No LLM, API key, or external model call. Results are first-pass screening prompts, not legal advice.")
with st.sidebar:
    st.header("Review guide")
    st.write("Upload a searchable PDF, DOCX, or TXT agreement. Scanned PDFs require OCR before upload.")
    st.warning("Verify every conclusion against the original agreement before a legal or commercial decision.")
uploaded = st.file_uploader("Upload a contract", type=["pdf", "docx", "txt"])
if uploaded:
    try:
        text = read_document(uploaded)
        if not text.strip(): st.error("No readable text was found. Apply OCR to scanned PDFs and try again."); st.stop()
        result = analyze(text)
        if result.empty: st.warning("No usable provisions were detected. Review the extracted text and document formatting."); st.stop()
        critical = int((result["Risk level"] == "Critical").sum()); high = int((result["Risk level"] == "High").sum())
        a,b,c,d = st.columns(4); a.metric("Classified provisions", len(result)); b.metric("Critical flags", critical); c.metric("High-priority flags", high); d.metric("Average risk", f"{result['Risk score'].mean():.1f}/5")
        st.subheader("Risk concentration")
        st.bar_chart(result.groupby("Risk level").size().reindex(["Critical", "High", "Moderate", "Low"], fill_value=0), color="#c36a2d")
        selected = st.multiselect("Filter provision categories", sorted(set(CATEGORIES) | {"Miscellaneous"}), default=sorted(set(result["Provision category"])))
        view = result[result["Provision category"].isin(selected)].sort_values(["Risk score", "Clause number"], ascending=[False, True])
        st.subheader("Evidence-backed clause review")
        st.dataframe(view, use_container_width=True, hide_index=True, column_config={"Relevant text":st.column_config.TextColumn(width="large"),"Risk score":st.column_config.ProgressColumn(min_value=1,max_value=5,format="%d/5")})
        st.download_button("Download analysis as CSV", view.to_csv(index=False).encode("utf-8"), "contract_risk_analysis.csv", "text/csv")
        with st.expander("Extracted source text"): st.text(text)
    except Exception as exc:
        st.error(f"The document could not be processed: {exc}")
else:
    st.info("Choose a contract to begin.")
