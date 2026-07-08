"""
AutoRedTeam Configuration
Update paths and settings here before running.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ── Project root ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_DIR   = BASE_DIR / "chroma_db"

DATA_DIR.mkdir(exist_ok=True)
DB_DIR.mkdir(exist_ok=True)

# ── NVD API ───────────────────────────────────────────────────
# Get a free API key at https://nvd.nist.gov/developers/request-an-api-key
# Without a key: 5 requests/30s  |  With key: 50 requests/30s
NVD_API_KEY = os.getenv("NVD_API_KEY", "")

# ── Anthropic API ─────────────────────────────────────────────
# Used for synthetic training data generation (Day 2)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NVD_BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# How many CVEs to ingest — start with 2000 for Day 1, bump to 50000 later
NVD_MAX_CVE = 2000

# Only pull CVEs with CVSS >= this score (7.0 = High/Critical only)
# Set to 0.0 to pull everything
NVD_MIN_CVSS = 7.0

# ── Embedding model ───────────────────────────────────────────
# Lightweight & fast — good for security text
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ── ChromaDB collections ──────────────────────────────────────
CVE_COLLECTION      = "cve_knowledge"
ATTACK_COLLECTION   = "mitre_attack"

# ── RAG retrieval ─────────────────────────────────────────────
TOP_K_RESULTS = 5   # how many chunks to return per query

# ── Kali MCP Server ───────────────────────────────────────────
# Set KALI_MCP_URL in .env once Kali VM is running.
# The Kali MCP server exposes all Kali tools over the network.
# Default IP assumes Kali is the third VM on the UTM host-only network.
KALI_MCP_URL = os.getenv("KALI_MCP_URL", "http://192.168.128.3:8765")
