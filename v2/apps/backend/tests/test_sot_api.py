import uuid

import pytest
from fastapi.testclient import TestClient

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.sot.api import sot_subject


def subject(role: Role) -> Subject:
    return Subject(
        user_id=str(uuid.uuid4()),
        issuer="test",
        sub=uuid.uuid4().hex,
        email="person@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


@pytest.mark.parametrize("identity", [None, subject(Role.STAFF)])
def test_anonymous_and_staff_cannot_stage(identity: Subject | None) -> None:
    async def override() -> Subject | None:
        return identity

    app.dependency_overrides[sot_subject] = override
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/sot/packages/stage",
                json={"staging_name": "not-read-because-denied"},
            )
    finally:
        app.dependency_overrides.pop(sot_subject, None)
    assert response.status_code in {401, 403}
    payload = response.json()
    assert payload["error"]["code"] in {
        "authentication_required",
        "curator_role_required",
    }
    assert payload["request_id"]
    assert "/Users/" not in response.text
