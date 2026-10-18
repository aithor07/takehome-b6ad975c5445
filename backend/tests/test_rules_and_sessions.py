import pytest

from app.rules import PolicyContradictionError, load_documents, resolve_hotel_policy
from app.sessions import AppError, require_guest, require_manager, resolve_session_token


def test_resolve_coral_policy_picks_v2_and_ignores_web_and_notes():
    policy = resolve_hotel_policy("org-coral", "hotel-alba")
    assert policy.document_id == "coral-alba-policy"
    assert policy.version == 2
    assert policy.late_checkout_limit == "14:00"
    assert policy.fee_eur == 25
    assert policy.evidence["version"] == 2


def test_resolve_brisa_policy():
    policy = resolve_hotel_policy("org-brisa", "hotel-alba-b")
    assert policy.document_id == "brisa-alba-policy"
    assert policy.version == 2
    assert policy.late_checkout_limit == "12:00"
    assert policy.fee_eur == 15


def test_contradictory_v2_policies_trigger_handoff_error():
    docs = load_documents()
    docs.append(
        {
            "document_id": "coral-alba-policy-alt",
            "org_id": "org-coral",
            "hotel_id": "hotel-alba",
            "version": 2,
            "authority": "approved_policy",
            "active": True,
            "audience": "guest",
            "content": "Otra política v2 con 20 EUR.",
            "policy": {
                "normal_checkout": "11:00",
                "late_checkout_limit": "14:00",
                "fee_eur": 20,
                "requires_manager_approval": True,
            },
        }
    )
    with pytest.raises(PolicyContradictionError):
        resolve_hotel_policy("org-coral", "hotel-alba", documents=docs)


# Test para comprobar el acceso permitido y la denegacion de acceso para usuario sin privilegios
def test_session_roles():
    guest = resolve_session_token("guest-a1")
    assert require_guest(guest).stay_id == "STAY-A1"
    with pytest.raises(AppError) as exc:
        require_manager(guest)
    assert exc.value.status_code == 403


# Test para comprobar que si falta token salte error 401
def test_missing_token_is_401():
    with pytest.raises(AppError) as exc:
        resolve_session_token(None)
    assert exc.value.status_code == 401


# Test para comprobar que un token desconocido/no existe salte error 401
def test_unknown_token_is_401():
    with pytest.raises(AppError) as exc:
        resolve_session_token("no-existe")
    assert exc.value.status_code == 401
