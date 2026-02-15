from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Optional

logger = logging.getLogger(__name__)


class QdrantClient:

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection: str = "documents",
        api_key: Optional[str] = None,
        vector_size: int = 384,
    ) -> None:
        self._url = url.rstrip("/")
        self._collection = collection
        self._api_key = api_key
        self._vector_size = vector_size
        self.ensure_collection()

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["api-key"] = self._api_key
        return h

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict | list] = None,
    ) -> dict[str, Any]:
        url = f"{self._url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.error(
                "[QdrantClient] HTTP %s %s -> %d: %s",
                method, url, exc.code, error_body,
            )
            raise
        except urllib.error.URLError as exc:
            logger.error("[QdrantClient] Connection error %s %s: %s", method, url, exc.reason)
            raise

    # ── collection management ──────────────────────────────────────────

    def ensure_collection(self) -> None:
        try:
            self._request("GET", f"/collections/{self._collection}")
            logger.info("[QdrantClient] Collection '%s' already exists", self._collection)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                logger.info("[QdrantClient] Creating collection '%s'", self._collection)
                self._request("PUT", f"/collections/{self._collection}", {
                    "vectors": {
                        "size": self._vector_size,
                        "distance": "Cosine",
                    }
                })
                logger.info("[QdrantClient] Collection '%s' created", self._collection)
            else:
                raise
        except urllib.error.URLError:
            logger.warning(
                "[QdrantClient] Cannot reach Qdrant at %s — operating in offline mode",
                self._url,
            )

    # ── upsert (create or update) ──────────────────────────────────────

    def upsert_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body = {
            "points": [
                {
                    "id": point_id,
                    "vector": vector,
                    "payload": payload or {},
                }
            ]
        }
        try:
            result = self._request(
                "PUT",
                f"/collections/{self._collection}/points?wait=true",
                body,
            )
            logger.info(
                "[QdrantClient] Upserted point id=%s dim=%d into '%s'",
                point_id, len(vector), self._collection,
            )
            return result
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Failed to upsert point %s: %s", point_id, exc)
            return {"status": "error", "point_id": point_id}

    # ── delete ─────────────────────────────────────────────────────────

    def delete_vector(self, point_id: str) -> dict[str, Any]:
        body = {
            "points": [point_id],
        }
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/delete?wait=true",
                body,
            )
            logger.info(
                "[QdrantClient] Deleted point id=%s from '%s'",
                point_id, self._collection,
            )
            return result
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Failed to delete point %s: %s", point_id, exc)
            return {"status": "error", "point_id": point_id}

    # ── search ─────────────────────────────────────────────────────────

    def search(
        self,
        vector: list[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
        }
        if score_threshold is not None:
            body["score_threshold"] = score_threshold
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/search",
                body,
            )
            return result.get("result", [])
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Search failed: %s", exc)
            return []

    # ── upsert metadata-only (zero vector for non-embeddable files) ───

    def upsert_metadata(
        self,
        point_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        zero_vector = [0.0] * self._vector_size
        return self.upsert_vector(point_id=point_id, vector=zero_vector, payload=payload)

    # ── update payload on existing point ───────────────────────────────

    def update_payload(
        self,
        point_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = {
            "points": [point_id],
            "payload": payload,
        }
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/payload",
                body,
            )
            logger.info("[QdrantClient] Updated payload for point id=%s", point_id)
            return result
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Failed to update payload %s: %s", point_id, exc)
            return {"status": "error", "point_id": point_id}

    # ── get single point ───────────────────────────────────────────────

    def get_point(self, point_id: str) -> Optional[dict[str, Any]]:
        try:
            result = self._request(
                "GET",
                f"/collections/{self._collection}/points/{point_id}",
            )
            return result.get("result")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
        except urllib.error.URLError as exc:
            logger.error("[QdrantClient] Failed to get point %s: %s", point_id, exc)
            return None

    # ── scroll / list all points ───────────────────────────────────────

    def scroll(
        self,
        limit: int = 100,
        offset: Optional[str] = None,
        filter_payload: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if offset:
            body["offset"] = offset
        if filter_payload:
            body["filter"] = filter_payload
        try:
            result = self._request(
                "POST",
                f"/collections/{self._collection}/points/scroll",
                body,
            )
            return result.get("result", {}).get("points", [])
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            logger.error("[QdrantClient] Scroll failed: %s", exc)
            return []