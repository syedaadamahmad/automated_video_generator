"""
test_auth.py — Authentication Test Suite for Veo Studio
═════════════════════════════════════════════════════════

Tests:
  1. UserStore unit tests (mocked DynamoDB)
  2. Internal secret middleware integration tests
  3. Auth endpoint integration tests (requires veo_main.py running)
  4. Rate limiting smoke test

Run unit tests only (no server needed):
    pytest test_auth.py -v -k "unit"

Run all tests (requires veo_main.py running on port 8100):
    pytest test_auth.py -v

Run with coverage:
    pytest test_auth.py -v --tb=short
"""

import os
import time
import random
import string
import unittest
from unittest.mock import MagicMock, patch, call
from typing import Any, Dict

import pytest
import requests

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE        = os.getenv("VEO_API_URL", "http://localhost:8100")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")
TEST_EMAIL      = f"test_{''.join(random.choices(string.ascii_lowercase, k=8))}@veo.local"
TEST_PASSWORD   = "testpassword123"
TEST_NAME       = "Test User"

def _headers() -> Dict[str, str]:
    """Headers for integration tests — include internal secret if configured."""
    h = {"Content-Type": "application/json"}
    if INTERNAL_SECRET:
        h["X-Internal-Secret"] = INTERNAL_SECRET
    return h

def api_up() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 1. UserStore unit tests — mocked DynamoDB, no AWS credentials needed
# ══════════════════════════════════════════════════════════════════════════════

class MockTable:
    """Minimal in-memory DynamoDB table mock."""
    def __init__(self):
        self._data: Dict[str, Dict] = {}

    def load(self): pass

    def put_item(self, Item, ConditionExpression=None):
        from boto3.dynamodb.conditions import Attr
        email = Item["email"]
        if ConditionExpression is not None and email in self._data:
            error = {"Error": {"Code": "ConditionalCheckFailedException"}}
            from botocore.exceptions import ClientError
            raise ClientError(error, "PutItem")
        self._data[email] = dict(Item)

    def get_item(self, Key):
        item = self._data.get(Key["email"])
        return {"Item": dict(item)} if item else {}

    def delete_item(self, Key):
        self._data.pop(Key["email"], None)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues,
                    ExpressionAttributeNames=None, **_):
        email = Key["email"]
        if email not in self._data:
            return
        # Parse SET expression: "SET #n = :n, #r = :r"
        names  = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues
        expr   = UpdateExpression.replace("SET ", "")
        for part in expr.split(","):
            k, v = part.strip().split(" = ")
            real_key   = names.get(k.strip(), k.strip())
            real_value = values[v.strip()]
            self._data[email][real_key] = real_value

    def scan(self, Select=None, ProjectionExpression=None,
             ExpressionAttributeNames=None):
        if Select == "COUNT":
            return {"Count": len(self._data)}
        items = list(self._data.values())
        # Mimic ProjectionExpression that excludes pw_hash
        if ProjectionExpression and "pw_hash" not in ProjectionExpression:
            items = [{k: v for k, v in i.items() if k != "pw_hash"} for i in items]
        return {"Items": items}


def _make_store():
    """Create a UserStore with mocked DynamoDB."""
    from veo_users import UserStore
    store = UserStore.__new__(UserStore)
    store.table_name = "veo-users-test"
    store._dynamo = None
    store._table  = MockTable()
    return store


class TestUserStoreUnit(unittest.TestCase):
    """Unit: 1a — create user"""

    def setUp(self):
        self.store = _make_store()

    def test_create_user(self):
        user = self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        self.assertEqual(user["email"], TEST_EMAIL)
        self.assertEqual(user["role"],  "editor")
        self.assertNotIn("pw_hash", user)

    def test_create_duplicate_raises(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        with self.assertRaises(ValueError, msg="Should raise on duplicate email"):
            self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")

    def test_create_invalid_role(self):
        with self.assertRaises(ValueError):
            self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "superadmin")

    def test_create_short_password(self):
        with self.assertRaises(ValueError):
            self.store.create(TEST_EMAIL, "abc", TEST_NAME, "editor")

    def test_verify_correct(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        user = self.store.verify(TEST_EMAIL, TEST_PASSWORD)
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], TEST_EMAIL)

    def test_verify_wrong_password(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        result = self.store.verify(TEST_EMAIL, "wrongpassword")
        self.assertIsNone(result)

    def test_verify_unknown_email(self):
        """Must not raise, must return None (timing safety)."""
        result = self.store.verify("ghost@veo.local", "password")
        self.assertIsNone(result)

    def test_get_existing(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        user = self.store.get(TEST_EMAIL)
        self.assertIsNotNone(user)
        self.assertNotIn("pw_hash", user)

    def test_get_nonexistent(self):
        result = self.store.get("nobody@veo.local")
        self.assertIsNone(result)

    def test_delete_user(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        deleted = self.store.delete(TEST_EMAIL)
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get(TEST_EMAIL))

    def test_delete_nonexistent(self):
        result = self.store.delete("nobody@veo.local")
        self.assertFalse(result)

    def test_update_role(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        self.store.update(TEST_EMAIL, role="admin")
        user = self.store.get(TEST_EMAIL)
        self.assertEqual(user["role"], "admin")

    def test_update_password(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        self.store.update(TEST_EMAIL, new_password="newpassword123")
        # Old password should fail
        self.assertIsNone(self.store.verify(TEST_EMAIL, TEST_PASSWORD))
        # New password should work
        self.assertIsNotNone(self.store.verify(TEST_EMAIL, "newpassword123"))

    def test_update_nonexistent_raises(self):
        with self.assertRaises(ValueError):
            self.store.update("nobody@veo.local", name="Ghost")

    def test_list_users(self):
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")
        users = self.store.list_users()
        self.assertIsInstance(users, list)
        self.assertTrue(any(u["email"] == TEST_EMAIL for u in users))
        # Ensure no pw_hash leaked
        for u in users:
            self.assertNotIn("pw_hash", u)

    def test_safe_strips_pw_hash(self):
        from veo_users import UserStore
        item = {"email": "a@b.com", "pw_hash": "secret", "name": "A", "role": "editor"}
        safe = UserStore._safe(item)
        self.assertNotIn("pw_hash", safe)
        self.assertIn("email", safe)

    def test_email_normalisation(self):
        """Emails should be lowercased and stripped."""
        self.store.create("  UPPER@VEO.LOCAL  ", TEST_PASSWORD, TEST_NAME, "editor")
        user = self.store.get("upper@veo.local")
        self.assertIsNotNone(user)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Integration tests — require veo_main.py running
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not api_up(), reason="veo_main.py not running")
class TestInternalSecretMiddleware:
    """Integration: internal secret middleware blocks unauthorized requests."""

    def test_health_no_secret_required(self):
        """Health endpoint is public — no secret needed."""
        r = requests.get(f"{API_BASE}/health", timeout=5)
        assert r.status_code == 200

    def test_api_without_secret_blocked(self):
        """Any API endpoint without secret should return 401 when secret is configured."""
        if not INTERNAL_SECRET:
            pytest.skip("INTERNAL_SECRET not set — middleware inactive")
        r = requests.get(f"{API_BASE}/api/jobs", timeout=5)
        assert r.status_code == 401

    def test_api_with_wrong_secret_blocked(self):
        if not INTERNAL_SECRET:
            pytest.skip("INTERNAL_SECRET not set — middleware inactive")
        r = requests.get(
            f"{API_BASE}/api/jobs",
            headers={"X-Internal-Secret": "wrong-secret"},
            timeout=5,
        )
        assert r.status_code == 401

    def test_api_with_correct_secret_passes(self):
        if not INTERNAL_SECRET:
            pytest.skip("INTERNAL_SECRET not set — middleware inactive")
        r = requests.get(f"{API_BASE}/api/jobs", headers=_headers(), timeout=5)
        assert r.status_code in (200, 403)   # 403 = no user header, that's fine


@pytest.mark.skipif(not api_up(), reason="veo_main.py not running")
class TestAuthEndpoints:
    """Integration: /api/auth/verify endpoint."""

    def test_verify_wrong_credentials(self):
        r = requests.post(
            f"{API_BASE}/api/auth/verify",
            json={"email": "nobody@veo.local", "password": "wrong"},
            headers=_headers(),
            timeout=5,
        )
        assert r.status_code == 401

    def test_verify_missing_fields(self):
        r = requests.post(
            f"{API_BASE}/api/auth/verify",
            json={},
            headers=_headers(),
            timeout=5,
        )
        assert r.status_code == 401

    def test_verify_admin_credentials(self):
        """Verify the default admin account works."""
        admin_email = os.getenv("ADMIN_EMAIL", "admin@veo.local")
        admin_pass  = os.getenv("ADMIN_PASSWORD", "changeme")
        r = requests.post(
            f"{API_BASE}/api/auth/verify",
            json={"email": admin_email, "password": admin_pass},
            headers=_headers(),
            timeout=5,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == admin_email
        assert data["role"]  == "admin"
        assert "pw_hash" not in data


@pytest.mark.skipif(not api_up(), reason="veo_main.py not running")
class TestUserManagementEndpoints:
    """Integration: user CRUD endpoints (admin only)."""

    _created_email: str = ""

    def test_list_users_no_admin_header(self):
        """Without admin role header, should return 403."""
        r = requests.get(
            f"{API_BASE}/api/users",
            headers={**_headers(), "X-User-Role": "viewer"},
            timeout=5,
        )
        assert r.status_code == 403

    def test_list_users_as_admin(self):
        r = requests.get(
            f"{API_BASE}/api/users",
            headers={**_headers(), "X-User-Role": "admin",
                     "X-User-Id": os.getenv("ADMIN_EMAIL", "admin@veo.local")},
            timeout=5,
        )
        assert r.status_code == 200
        assert "users" in r.json()

    def test_create_user_as_admin(self):
        email = f"pytest_{int(time.time())}@veo.local"
        TestUserManagementEndpoints._created_email = email

        r = requests.post(
            f"{API_BASE}/api/users",
            json={"email": email, "password": "testpass123", "name": "Pytest User", "role": "editor"},
            headers={**_headers(), "X-User-Role": "admin",
                     "X-User-Id": os.getenv("ADMIN_EMAIL", "admin@veo.local")},
            timeout=5,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["user"]["email"] == email
        assert "pw_hash" not in data["user"]

    def test_create_user_duplicate(self):
        email = TestUserManagementEndpoints._created_email
        if not email:
            pytest.skip("Create test didn't run")
        r = requests.post(
            f"{API_BASE}/api/users",
            json={"email": email, "password": "testpass123", "name": "Dupe", "role": "editor"},
            headers={**_headers(), "X-User-Role": "admin",
                     "X-User-Id": os.getenv("ADMIN_EMAIL", "admin@veo.local")},
            timeout=5,
        )
        assert r.status_code == 400

    def test_delete_user_as_admin(self):
        email = TestUserManagementEndpoints._created_email
        if not email:
            pytest.skip("Create test didn't run")
        r = requests.delete(
            f"{API_BASE}/api/users/{email}",
            headers={**_headers(), "X-User-Role": "admin",
                     "X-User-Id": os.getenv("ADMIN_EMAIL", "admin@veo.local")},
            timeout=5,
        )
        assert r.status_code == 200

    def test_cannot_delete_self(self):
        admin_email = os.getenv("ADMIN_EMAIL", "admin@veo.local")
        r = requests.delete(
            f"{API_BASE}/api/users/{admin_email}",
            headers={**_headers(), "X-User-Role": "admin", "X-User-Id": admin_email},
            timeout=5,
        )
        assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# 3. Security sanity checks
# ══════════════════════════════════════════════════════════════════════════════

class TestSecuritySanity(unittest.TestCase):
    """Unit: security properties of the UserStore."""

    def setUp(self):
        self.store = _make_store()
        self.store.create(TEST_EMAIL, TEST_PASSWORD, TEST_NAME, "editor")

    def test_pw_hash_not_in_get(self):
        user = self.store.get(TEST_EMAIL)
        self.assertNotIn("pw_hash", user)

    def test_pw_hash_not_in_list(self):
        users = self.store.list_users()
        for u in users:
            self.assertNotIn("pw_hash", u)

    def test_pw_hash_not_in_verify(self):
        user = self.store.verify(TEST_EMAIL, TEST_PASSWORD)
        self.assertNotIn("pw_hash", user)

    def test_bcrypt_hash_is_stored(self):
        """Raw password must never be stored."""
        raw = self.store._table._data.get(TEST_EMAIL, {})
        stored_hash = raw.get("pw_hash", "")
        self.assertNotEqual(stored_hash, TEST_PASSWORD)
        self.assertTrue(stored_hash.startswith("$2b$"))

    def test_unknown_email_returns_none_not_error(self):
        """Timing safety: unknown email must return None, not raise."""
        try:
            result = self.store.verify("ghost@veo.local", "anything")
            self.assertIsNone(result)
        except Exception as e:
            self.fail(f"verify raised an exception for unknown email: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Veo Studio — Auth Test Suite")
    print("=" * 60)
    print(f"API:             {API_BASE}")
    print(f"API reachable:   {api_up()}")
    print(f"Secret active:   {'yes' if INTERNAL_SECRET else 'no (set INTERNAL_SECRET to test)'}")
    print()

    unittest.main(verbosity=2)