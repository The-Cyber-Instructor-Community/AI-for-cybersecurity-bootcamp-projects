# Day 1 Quickstart — AutoRedTeam RAG Pipeline

## 1. Create & activate a virtual environment
```bash
cd autoredteam
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. (Recommended) Get a free NVD API key
Takes 2 minutes. Without it, ingestion is rate-limited to ~3 CVEs/min.
→ https://nvd.nist.gov/developers/request-an-api-key

Then set it:
```bash
export NVD_API_KEY="your-key-here"
# Or create a .env file:  echo NVD_API_KEY=your-key >> .env
```

## 3. Ingest CVE data (High + Critical CVEs)
```bash
python -m rag.ingest_cve
```
Pulls ~2000 HIGH/CRITICAL CVEs from NVD. Takes ~5 min with API key.

## 4. Ingest MITRE ATT&CK techniques
```bash
python -m rag.ingest_attack
```
Downloads the full ATT&CK Enterprise STIX bundle (~650 techniques).

## 5. Validate your RAG pipeline
```bash
python test_rag.py
```
Runs 4 test queries against Metasploitable2-style services.
All 4 should return results — that's your Day 1 done ✓

---

## Project structure so far
```
autoredteam/
├── config.py              # All settings — edit NVD_MAX_CVE, NVD_MIN_CVSS here
├── requirements.txt
├── test_rag.py            # Day 1 validation
├── data/
│   └── enterprise-attack.json    # auto-downloaded
├── chroma_db/             # auto-created by ChromaDB
│   ├── cve_knowledge/
│   └── mitre_attack/
└── rag/
    ├── __init__.py
    ├── ingest_cve.py      # NVD → ChromaDB
    ├── ingest_attack.py   # MITRE ATT&CK → ChromaDB
    └── query.py           # SecurityRAG class (used by agent later)
```

## Coming on Day 2
Fine-tuning Llama 3.1 8B on security data with QLoRA (Google Colab).
We'll build the training dataset from CVE + pentest report data.

## Lab setup (parallel to coding)
- Download VirtualBox: https://www.virtualbox.org/
- Download Metasploitable2: https://sourceforge.net/projects/metasploitable/
- Import the .vmdk into VirtualBox, set network to Host-Only Adapter
- Default creds: msfadmin / msfadmin
