import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

TG_HOST = os.environ["TG_HOST"].rstrip("/")
TG_GRAPH = os.environ.get("TG_GRAPHNAME", "FraudGraph")
TG_SECRET = os.environ.get("TG_SECRET", "")

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
EMBED_DIM = 384

DATASET = ROOT / "dataset"
PREP = ROOT / "data_prep"
