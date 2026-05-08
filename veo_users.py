"""
veo_users.py — User Management for Veo Studio
═══════════════════════════════════════════════

DynamoDB + bcrypt. Uses the same AWS credentials already configured
for S3 and Bedrock — no new service accounts needed.

DynamoDB table: veo-users (created automatically on first startup)
  Partition key: email (String)
  Attributes:    id, name, role, pw_hash, created_at

Roles:
  admin  — full access, can manage users
  editor — generate, rerun, reject, download
  viewer — view videos only

Environment:
  AWS_REGION      — same region as your S3 bucket
  DYNAMO_TABLE    — table name (default: veo-users)
  ADMIN_EMAIL     — seed admin email
  ADMIN_PASSWORD  — seed admin password (default: changeme)
  ADMIN_NAME      — seed admin display name
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

logger = logging.getLogger("VEO_USERS")

VALID_ROLES = {"admin", "editor", "viewer"}
_TABLE_NAME = os.getenv("DYNAMO_TABLE", "veo-users")
_AWS_REGION = os.getenv("AWS_REGION", os.getenv("VEO_S3_REGION", "us-east-1"))


class UserStore:
    """
    DynamoDB-backed user store with bcrypt password hashing.
    boto3 DynamoDB resource is thread-safe for concurrent reads/writes.
    """

    def __init__(self, table_name: str = _TABLE_NAME, region: str = _AWS_REGION):
        self.table_name = table_name
        self._dynamo    = boto3.resource("dynamodb", region_name=region)
        self._table     = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def init(self) -> None:
        """Create table if needed, seed default admin. Call once at startup."""
        self._table = self._ensure_table()

        if self._count() == 0:
            email    = os.getenv("ADMIN_EMAIL",    "admin@veo.local")
            password = os.getenv("ADMIN_PASSWORD", "changeme")
            name     = os.getenv("ADMIN_NAME",     "Admin")
            self.create(email, password, name, "admin")
            logger.info(f"[USERS] Default admin created: {email}")
            if password == "changeme":
                logger.warning(
                    "[USERS] ⚠️  Default password 'changeme' active — "
                    "set ADMIN_PASSWORD in veo.env before deploying."
                )
        else:
            logger.info(
                f"[USERS] DynamoDB ready — "
                f"{self._count()} user(s) in '{self.table_name}'"
            )

    # ── Public API ─────────────────────────────────────────────────────────────

    def create(
        self,
        email:    str,
        password: str,
        name:     str,
        role:     str = "editor",
    ) -> Dict[str, Any]:
        """Create user. Raises ValueError on duplicate, bad role, or short password."""
        email = email.lower().strip()
        role  = role.lower().strip()

        if role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{role}'. "
                f"Must be one of: {', '.join(sorted(VALID_ROLES))}"
            )
        if self.get(email):
            raise ValueError(f"User '{email}' already exists")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        user_id = str(uuid.uuid4())
        now     = datetime.now(timezone.utc).isoformat()

        item = {
            "email":      email,
            "id":         user_id,
            "name":       name.strip(),
            "role":       role,
            "pw_hash":    pw_hash,
            "created_at": now,
        }
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=Attr("email").not_exists(),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ValueError(f"User '{email}' already exists")
            raise

        logger.info(f"[USERS] Created: {email} ({role})")
        return self._safe(item)

    def verify(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Verify credentials. Always runs bcrypt to prevent timing-based enumeration.
        Returns safe user dict on success, None on failure.
        """
        email = email.lower().strip()
        item  = self._get_raw(email)

        dummy  = b"$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234"
        stored = item["pw_hash"].encode() if item else dummy

        try:
            match = bcrypt.checkpw(password.encode(), stored)
        except Exception:
            match = False

        if not item or not match:
            logger.warning(f"[USERS] Failed login: {email}")
            return None

        logger.info(f"[USERS] Verified: {email} ({item['role']})")
        return self._safe(item)

    def get(self, email: str) -> Optional[Dict[str, Any]]:
        """Return safe user dict by email, or None."""
        item = self._get_raw(email.lower().strip())
        return self._safe(item) if item else None

    def list_users(self) -> List[Dict[str, Any]]:
        """Return all users without password hashes, sorted by created_at."""
        resp  = self._table.scan(
            ProjectionExpression="id, email, #n, #r, created_at",
            ExpressionAttributeNames={"#n": "name", "#r": "role"},
        )
        items = resp.get("Items", [])
        return sorted([self._safe(dict(i)) for i in items], key=lambda x: x.get("created_at", ""))

    def update(
        self,
        email:        str,
        name:         Optional[str] = None,
        role:         Optional[str] = None,
        new_password: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update name, role, and/or password. Raises ValueError if not found."""
        email = email.lower().strip()
        if not self.get(email):
            raise ValueError(f"User '{email}' not found")
        if role and role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'")
        if new_password and len(new_password) < 6:
            raise ValueError("Password must be at least 6 characters")

        set_parts:  List[str]        = []
        expr_names: Dict[str, str]   = {}
        expr_vals:  Dict[str, Any]   = {}

        if name:
            set_parts.append("#n = :n")
            expr_names["#n"] = "name"
            expr_vals[":n"]  = name.strip()
        if role:
            set_parts.append("#r = :r")
            expr_names["#r"] = "role"
            expr_vals[":r"]  = role
        if new_password:
            pw_hash = bcrypt.hashpw(
                new_password.encode(), bcrypt.gensalt(rounds=12)
            ).decode()
            set_parts.append("pw_hash = :pw")
            expr_vals[":pw"] = pw_hash

        if set_parts:
            kwargs: Dict[str, Any] = {
                "Key":             {"email": email},
                "UpdateExpression":"SET " + ", ".join(set_parts),
                "ExpressionAttributeValues": expr_vals,
            }
            if expr_names:
                kwargs["ExpressionAttributeNames"] = expr_names
            self._table.update_item(**kwargs)

        logger.info(f"[USERS] Updated: {email}")
        return self.get(email)

    def delete(self, email: str) -> bool:
        """Delete a user. Returns True if deleted, False if not found."""
        email = email.lower().strip()
        if not self.get(email):
            return False
        self._table.delete_item(Key={"email": email})
        logger.info(f"[USERS] Deleted: {email}")
        return True

    def count(self) -> int:
        return self._count()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _ensure_table(self):
        try:
            table = self._dynamo.Table(self.table_name)
            table.load()
            logger.info(f"[USERS] Table '{self.table_name}' exists")
            return table
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise

        logger.info(f"[USERS] Creating table '{self.table_name}'…")
        table = self._dynamo.create_table(
            TableName=self.table_name,
            KeySchema=[{"AttributeName": "email", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "email", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        logger.info(f"[USERS] Table '{self.table_name}' created")
        return table

    def _get_raw(self, email: str) -> Optional[Dict[str, Any]]:
        resp = self._table.get_item(Key={"email": email})
        item = resp.get("Item")
        return dict(item) if item else None

    def _count(self) -> int:
        return self._table.scan(Select="COUNT").get("Count", 0)

    @staticmethod
    def _safe(item: Dict[str, Any]) -> Dict[str, Any]:
        """Strip pw_hash — never expose to any caller."""
        return {k: v for k, v in item.items() if k != "pw_hash"}