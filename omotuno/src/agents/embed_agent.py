from __future__ import annotations

import hashlib
import math
from typing import Protocol

from src.pipeline.config import EMBEDDING_MODEL_ID
from src.pipeline.types import AlertRecord, EmbeddedAlert, Vector


def build_embedding_text(alert: AlertRecord) -> str:
    return f"{alert.rule_description} {alert.full_log}"


class EmbeddingClient(Protocol):
    def embed(self, text: str, model_id: str = EMBEDDING_MODEL_ID) -> Vector:
        ...


class DeterministicEmbeddingClient:
    """
    Deterministic test/default client for offline runs.
    Produces cosine-friendly vectors by emphasizing stable SSH signal
    (rule phrase + srcuser + srcip extracted from the embedded text).
    """

    def __init__(self, dimensions: int = 8) -> None:
        self.dimensions = dimensions
        self.calls: list[str] = []

    def _normalized_vector_from_seed(self, seed: str) -> Vector:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        values = [((digest[i] / 255.0) * 2.0) - 1.0 for i in range(self.dimensions)]
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0:
            return [0.0] * self.dimensions
        return [v / norm for v in values]

    def _stable_seed(self, text: str) -> str:
        # text shape is ADR-001: "{rule.description} {full_log}"
        lower = text.lower()
        user = "unknown-user"
        ip = "unknown-ip"

        marker_for = " for "
        marker_from = " from "
        if marker_for in lower and marker_from in lower:
            for_idx = lower.find(marker_for) + len(marker_for)
            from_idx = lower.find(marker_from, for_idx)
            if from_idx > for_idx:
                user = lower[for_idx:from_idx].strip()
            from_start = from_idx + len(marker_from)
            from_end = lower.find(" ", from_start)
            if from_end > from_start:
                ip = lower[from_start:from_end].strip()

        rule_phrase = lower.split("sshd", 1)[0].strip()
        return f"{rule_phrase}|{user}|{ip}"

    def embed(self, text: str, model_id: str = EMBEDDING_MODEL_ID) -> Vector:
        self.calls.append(text)
        return self._normalized_vector_from_seed(self._stable_seed(text))


class BedrockTitanEmbeddingClient:
    """
    Live Bedrock Titan path, kept behind adapter seam.
    """

    def __init__(self, bedrock_runtime=None) -> None:
        self._runtime = bedrock_runtime

    def embed(self, text: str, model_id: str = EMBEDDING_MODEL_ID) -> Vector:
        runtime = self._runtime
        if runtime is None:
            try:
                import boto3  # type: ignore
            except ImportError as exc:
                raise RuntimeError("boto3 is required for live Bedrock embedding path") from exc
            runtime = boto3.client("bedrock-runtime")
        body = {"inputText": text}
        response = runtime.invoke_model(modelId=model_id, body=__import__("json").dumps(body))
        payload = __import__("json").loads(response["body"].read())
        return list(payload["embedding"])


def embed_alert(alert: AlertRecord, client: EmbeddingClient) -> EmbeddedAlert:
    text = build_embedding_text(alert)
    vector = client.embed(text, model_id=EMBEDDING_MODEL_ID)
    return EmbeddedAlert(alert=alert, text=text, vector=vector)
