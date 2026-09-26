"""Embedding providers. Default is a local feature-hashing embedder (no network, deterministic);
it captures lexical/character n-gram similarity, not deep semantics. Set EMBEDDING_PROVIDER=voyage
with VOYAGE_API_KEY for neural embeddings."""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

import httpx
import numpy as np

from app.core.config import get_settings

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for t in toks:  # character trigrams help Korean morphology & typos
            padded = f"#{t}#"
            feats += [padded[i:i + 3] for i in range(len(padded) - 2)]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for f in self._features(text):
                h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
                out[i, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str = "voyage-3.5", dim: int = 1024) -> None:
        self.api_key, self.model, self.dim = api_key, model, dim

    def embed(self, texts: list[str]) -> np.ndarray:
        r = httpx.post("https://api.voyageai.com/v1/embeddings", timeout=60,
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json={"input": texts, "model": self.model, "output_dimension": self.dim})
        r.raise_for_status()
        arr = np.array([d["embedding"] for d in r.json()["data"]], dtype=np.float32)
        return arr / np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9, None)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        if s.embedding_provider == "voyage" and s.voyage_api_key:
            _embedder = VoyageEmbedder(s.voyage_api_key)
        else:
            _embedder = HashEmbedder(s.embedding_dim)
    return _embedder
