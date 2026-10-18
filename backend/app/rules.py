from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DOCUMENTS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "documentos.jsonl"
)


class PolicyError(Exception):
    """Error base al resolver la politica documental"""


class PolicyNotFoundError(Exception):
    """Excepcion que se lanza cuando un hotel no tiene politica aprobada activa"""


class PolicyContradictionError(Exception):
    # Se lanza cuando hay dos politicas activas que se contradicen entre si
    pass


@dataclass(frozen=True)
class ResolvedPolicy:
    document_id: str
    org_id: str
    hotel_id: str
    version: int
    content: str
    normal_checkout: str
    late_checkout_limit: str
    fee_eur: int
    requires_manager_approval: bool

    @property
    def evidence(self) -> dict[str, Any]:
        # Formato exigido por el contrato de propuestas en app-api.md
        return {
            "document_id": self.document_id,
            "version": self.version,
            "quote": self.content,
        }


def load_documents(path: Path = DEFAULT_DOCUMENTS_PATH) -> list[dict[str, Any]]:
    """Leer el documento desde un archivo JSONL"""
    docs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        docs.append(json.loads(line))
    return docs


def resolve_hotel_policy(
    org_id: str,
    hotel_id: str,
    *,
    documents: list[dict[str, Any]] | None = None,
    path: Path = DEFAULT_DOCUMENTS_PATH,
) -> ResolvedPolicy:
    """Obtiene la unica politica aprobada, activa y de mayor version para el heusped"""

    corpus = documents if documents is not None else load_documents(path)

    candidates = [
        doc
        for doc in corpus
        if doc.get("org_id") == org_id
        and doc.get("hotel_id") == hotel_id
        and doc.get("authority") == "approved_policy"
        and doc.get("active") is True
        and doc.get("audience") == "guest"
        and isinstance(doc.get("policy"), dict)
    ]

    if not candidates:
        raise PolicyNotFoundError(
            f"No hay politica aprobada activa para {org_id}/{hotel_id}"
        )

    max_version = max(int(doc["version"]) for doc in candidates)
    top_candidates = [doc for doc in candidates if int(doc["version"]) == max_version]
    # Si hay mas de un documento activo en la version maxima, comprobamos si se contradicen
    if len(top_candidates) > 1:
        first_policy = top_candidates[0]["policy"]
        first_content = top_candidates[0].get("content")
        for other in top_candidates[1:]:
            if other["policy"] != first_policy or other.get("content") != first_content:
                raise PolicyContradictionError(
                    f"Contradiccion detectada en politicas v{max_version} de {hotel_id}"
                )
    winner = top_candidates[0]
    policy_data = winner["policy"]

    return ResolvedPolicy(
        document_id=str(winner["document_id"]),
        org_id=str(winner["org_id"]),
        hotel_id=str(winner["hotel_id"]),
        version=int(winner["version"]),
        content=str(winner["content"]),
        normal_checkout=str(policy_data["normal_checkout"]),
        late_checkout_limit=str(policy_data["late_checkout_limit"]),
        fee_eur=int(policy_data["fee_eur"]),
        requires_manager_approval=bool(
            policy_data.get("requires_manager_approval", True)
        ),
    )
