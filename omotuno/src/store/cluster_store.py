from __future__ import annotations

from typing import Protocol

from src.pipeline.types import ClusterState


class ClusterStore(Protocol):
    backend_name: str

    def add(self, cluster: ClusterState) -> None:
        ...

    def all(self) -> list[ClusterState]:
        ...


class _ListBackedClusterStore:
    """
    Adapter seam for vector-store backends.

    For this capstone scope, clustering state remains list-backed so assignment
    semantics stay deterministic across in-memory/FAISS/Chroma modes.
    """

    backend_name = "list"

    def __init__(self) -> None:
        self._clusters: list[ClusterState] = []

    def add(self, cluster: ClusterState) -> None:
        self._clusters.append(cluster)

    def all(self) -> list[ClusterState]:
        return self._clusters


class InMemoryClusterStore(_ListBackedClusterStore):
    backend_name = "in_memory"


class FaissClusterStore(_ListBackedClusterStore):
    backend_name = "faiss"


class ChromaClusterStore(_ListBackedClusterStore):
    backend_name = "chroma"


def create_cluster_store(backend: str = "in_memory") -> ClusterStore:
    normalized = backend.strip().lower()
    if normalized == "in_memory":
        return InMemoryClusterStore()
    if normalized == "faiss":
        return FaissClusterStore()
    if normalized == "chroma":
        return ChromaClusterStore()
    raise ValueError(f"unsupported vector store backend: {backend}")
