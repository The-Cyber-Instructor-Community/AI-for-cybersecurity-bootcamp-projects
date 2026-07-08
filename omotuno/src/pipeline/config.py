from datetime import timedelta

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
SUMMARY_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

SIMILARITY_THRESHOLD = 0.82
WINDOW = timedelta(hours=12)
VECTOR_STORE_BACKEND = "in_memory"  # Supported backends: in_memory | faiss | chroma

# Iteration 3 calibration bounds/steps
SIMILARITY_THRESHOLD_MIN = 0.50
SIMILARITY_THRESHOLD_MAX = 0.95
WINDOW_MIN_HOURS = 1
WINDOW_MAX_HOURS = 24
RECALIBRATION_THRESHOLD_STEP = 0.03
RECALIBRATION_WINDOW_STEP_HOURS = 2
RECALIBRATION_MIN_DIRECTIONAL_EVIDENCE = 2

SUPPRESSION_VOLUME_MULTIPLIER = 3  # Boundary behavior: suppress up to and including 3x baseline, bypass above 3x.
SUPPRESSION_DB_PATH = "data/sift_suppression.sqlite"
REVIEW_DB_PATH = "data/sift_review.sqlite"

DRIFT_THRESHOLD = 0.25
DRIFT_MIN_EVIDENCE = 3  # Contract: count < 3 => insufficient evidence/no flag.
SINGLETON_NOVELTY_THRESHOLD = 0.6  # Boundary behavior: score >= threshold => novel.

BACKSTOP_JUDGMENT_DENYLIST = [
    "benign",
    "routine",
    "low priority",
    "no action needed",
    "false positive",
    "all clear",
    "harmless",
    "automated scan",
]
