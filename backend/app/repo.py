"""Data access, always scoped to one user.

Every method takes the uid from the verified token. Paths are built as
users/{uid}/{collection}/{doc_id}, so a caller cannot reach another user's
data by construction. The Admin SDK bypasses Firestore security rules, so this
scoping is what enforces isolation on the backend.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Protocol

# Collections the backend may touch. Anything else is rejected.
READABLE = {"sessions", "tasks", "garden", "analysis", "topics", "reviews", "recommendations"}
WRITABLE = {"analysis", "topics", "recommendations", "reviews"}

_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,200}$")


def _check(collection: str, doc_id: str | None, write: bool) -> None:
    allowed = WRITABLE if write else READABLE
    if collection not in allowed:
        raise PermissionError(f"Collection '{collection}' not {'writable' if write else 'readable'}")
    if doc_id is not None and not _ID_RE.match(doc_id):
        raise ValueError("Invalid document id")


class Repository(Protocol):
    def list(self, uid: str, collection: str) -> list[dict[str, Any]]: ...
    def get(self, uid: str, collection: str, doc_id: str) -> dict[str, Any] | None: ...
    def put(self, uid: str, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...
    def delete(self, uid: str, collection: str, doc_id: str) -> None: ...


class InMemoryRepo:
    """Test double. Same scoping and validation rules as the real repo."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def seed(self, uid: str, collection: str, docs: dict[str, dict[str, Any]]) -> None:
        """Test helper: bypasses the write allow-list."""
        self._data.setdefault((uid, collection), {}).update(copy.deepcopy(docs))

    def list(self, uid, collection):
        _check(collection, None, write=False)
        docs = self._data.get((uid, collection), {})
        return [{"id": k, **copy.deepcopy(v)} for k, v in docs.items()]

    def get(self, uid, collection, doc_id):
        _check(collection, doc_id, write=False)
        doc = self._data.get((uid, collection), {}).get(doc_id)
        return None if doc is None else {"id": doc_id, **copy.deepcopy(doc)}

    def put(self, uid, collection, doc_id, data):
        _check(collection, doc_id, write=True)
        self._data.setdefault((uid, collection), {})[doc_id] = copy.deepcopy(
            {k: v for k, v in data.items() if k != "id"}
        )

    def delete(self, uid, collection, doc_id):
        _check(collection, doc_id, write=True)
        self._data.get((uid, collection), {}).pop(doc_id, None)


class FirestoreRepo:
    """Firestore-backed repository (Admin SDK)."""

    def __init__(self) -> None:
        from firebase_admin import firestore

        from .auth import _init_firebase

        _init_firebase()
        self._db = firestore.client()

    def _col(self, uid: str, collection: str):
        return self._db.collection("users").document(uid).collection(collection)

    def list(self, uid, collection):
        _check(collection, None, write=False)
        return [{"id": d.id, **d.to_dict()} for d in self._col(uid, collection).stream()]

    def get(self, uid, collection, doc_id):
        _check(collection, doc_id, write=False)
        snap = self._col(uid, collection).document(doc_id).get()
        return {"id": snap.id, **snap.to_dict()} if snap.exists else None

    def put(self, uid, collection, doc_id, data):
        _check(collection, doc_id, write=True)
        self._col(uid, collection).document(doc_id).set({k: v for k, v in data.items() if k != "id"})

    def delete(self, uid, collection, doc_id):
        _check(collection, doc_id, write=True)
        self._col(uid, collection).document(doc_id).delete()
