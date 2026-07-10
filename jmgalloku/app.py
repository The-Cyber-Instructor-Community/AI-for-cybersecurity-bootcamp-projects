import streamlit as st
import os
from auditor_engine import get_audit_chain

# Configure the browser page layout
st.set_page_config(page_title="ATLAS Compliance Engine", page_icon="🧭", layout="wide")

st.title("🧭 ATLAS — AI Governance Technical, Legal & Assurance System")
st.caption("Enterprise-grade, zero-leak local compliance testing running completely on-premise.")

# Sidebar for status controls
with st.sidebar:
    st.header("System Status")
    if os.path.exists("./chroma_db"):
        st.success("Knowledge Base: CONNECTED")
    else:
        st.error("Knowledge Base: NOT FOUND. Run ingest.py first!")
    
    st.info("Engine: Ollama (Llama 3 8B)\n\nData Privacy: Local Loopback Active (No Cloud Data Leaks)")

# Main layout input areas
st.subheader("Submit Artifact for Audit")
artifact_input = st.text_area(
    "Paste your policy draft, technical control document, or system architecture description below:",
    height=250,
    placeholder="Example: Password Policy - Employees must use a minimum of 8 characters. Passwords expire every 180 days..."
)

if st.button("Run Compliance Audit"):
    if not artifact_input.strip():
        st.warning("Please provide an artifact or text draft to audit.")
    else:
        with st.spinner("Retrieving framework controls and running compliance analysis..."):
            try:
                # Initialize our backend chain
                audit_pipeline = get_audit_chain()
                
                # Run the text through the local RAG engine
                response = audit_pipeline.invoke({"input": artifact_input})
                
                # Render the clean markdown output onto the web screen
                st.markdown("---")
                st.success("Audit Completed Successfully!")
                st.markdown(response["answer"])
                
            except Exception as e:
                st.error(f"An error occurred during analysis: {e}")