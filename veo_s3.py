"""
veo_s3.py — S3 integration for the Veo Video Generation Platform
═════════════════════════════════════════════════════════════════

Responsibilities:
  1. Upload generated videos to S3 after local save
  2. Generate public S3 URLs for frontend playback
  3. Soft-delete rejected videos (move to rejected/ prefix, not hard delete)
  4. Write manifest.json per prompt (mirrors existing Nova Reel bucket structure)

Bucket structure (matches existing bedrock-video-generation-us-east-1 pattern):
  videos/{job_id}/prompt_{N}/output.mp4
  videos/{job_id}/prompt_{N}/manifest.json
  rejected/{job_id}/prompt_{N}/output.mp4          ← soft-deleted videos land here

Public URL format:
  https://{bucket}.s3.{region}.amazonaws.com/videos/{job_id}/prompt_{N}/output.mp4

Environment variables required (already in veo.env via AWS credentials):
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_DEFAULT_REGION   (or passed as argument)
  VEO_S3_BUCKET
  VEO_S3_REGION

Called by:
  veo_orchestrator.py  → upload_video() after each successful generation
  veo_main.py          → soft_delete_video() in rerun endpoint before re-generation
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("VEO_S3")


# ── Lazy boto3 import — only fails if boto3 not installed ─────────────────────
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _BOTO3_AVAILABLE = True
except ImportError:
    _BOTO3_AVAILABLE = False
    logger.warning("[S3] boto3 not installed — S3 upload disabled. Run: pip install boto3")


class VeoS3Client:
    """
    Thin wrapper around boto3 S3 client.

    Initialised once at startup (veo_main.py). If S3 is misconfigured or
    boto3 is missing, all methods degrade gracefully — generation continues
    using local files only, with warnings in the log.

    Think of this as a courier: local disk is your in-house storage,
    S3 is the warehouse. If the courier van breaks down, work still
    happens locally — you just don't have offsite backup.
    """

    def __init__(
        self,
        bucket: str,
        region: str,
    ) -> None:
        self.bucket  = bucket
        self.region  = region
        self.enabled = False
        self._client = None

        if not _BOTO3_AVAILABLE:
            logger.warning("[S3] boto3 missing — S3 disabled")
            return

        if not bucket:
            logger.warning("[S3] VEO_S3_BUCKET not set — S3 disabled")
            return

        try:
            self._client = boto3.client(
                "s3",
                region_name = region,
                # Credentials picked up from environment:
                # AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (already in .env)
            )
            # Quick connectivity check — list bucket (raises on auth failure)
            self._client.head_bucket(Bucket=bucket)
            self.enabled = True
            logger.info(f"[S3] Connected — s3://{bucket} ({region})")
        except Exception as e:
            logger.error(f"[S3] Bucket check failed: {e} — S3 disabled")

    # ── Public interface ──────────────────────────────────────────────────────

    def upload_video(
        self,
        local_path: str,
        job_id: str,
        prompt_index: int,
    ) -> Optional[str]:
        """
        Upload a local video file to S3.

        S3 key: videos/{job_id}/prompt_{N}/output.mp4
        Also writes a manifest.json alongside the video.

        Returns the public HTTPS URL on success, None on failure.
        Local file is preserved regardless.
        """
        if not self.enabled or not self._client:
            return None

        # Resolve and normalise the path — handles Windows paths with spaces
        local = Path(local_path).resolve()
        if not local.exists():
            logger.error(f"[S3] Local file not found: {local_path} (resolved: {local})")
            return None
        if local.stat().st_size == 0:
            logger.error(f"[S3] File is 0 bytes — skipping upload: {local}")
            return None

        n          = prompt_index + 1
        video_key  = f"videos/{job_id}/prompt_{n}/output.mp4"
        manifest_key = f"videos/{job_id}/prompt_{n}/manifest.json"

        try:
            size_mb = local.stat().st_size / (1024 * 1024)
            # Upload video — use str(local) with forward-slash normalisation
            local_str = str(local)
            logger.info(f"[S3] Uploading {local.name} ({size_mb:.2f} MB) → s3://{self.bucket}/{video_key}")
            self._client.upload_file(
                Filename  = local_str,
                Bucket    = self.bucket,
                Key       = video_key,
                ExtraArgs = {"ContentType": "video/mp4"},
            )

            # Write manifest (mirrors Nova Reel structure in same bucket)
            manifest = {
                "job_id":        job_id,
                "prompt_index":  n,
                "s3_key":        video_key,
                "local_path":    str(local),
                "file_size_mb":  round(local.stat().st_size / (1024 * 1024), 2),
                "uploaded_at":   datetime.now(timezone.utc).isoformat(),
                "status":        "completed",
                "platform":      "veo",
            }
            self._client.put_object(
                Bucket      = self.bucket,
                Key         = manifest_key,
                Body        = json.dumps(manifest, indent=2).encode(),
                ContentType = "application/json",
            )

            url = self._public_url(video_key)
            logger.info(f"[S3] ✅ Uploaded — {url}")
            return url

        except (BotoCoreError, ClientError) as e:
            logger.error(f"[S3] Upload failed for {video_key}: {e}")
            return None
        except Exception as e:
            logger.error(f"[S3] Unexpected upload error: {e}")
            return None

    def soft_delete_video(
        self,
        job_id: str,
        prompt_index: int,
    ) -> bool:
        """
        Move a video from videos/ to rejected/ prefix (soft delete).

        Source: videos/{job_id}/prompt_{N}/output.mp4
        Dest:   rejected/{job_id}/prompt_{N}/output.mp4

        Also moves the manifest.json alongside.
        Original objects are deleted after copy succeeds.

        Returns True if the move completed, False otherwise.
        """
        if not self.enabled or not self._client:
            return False

        n = prompt_index + 1
        items = [
            (f"videos/{job_id}/prompt_{n}/output.mp4",    f"rejected/{job_id}/prompt_{n}/output.mp4"),
            (f"videos/{job_id}/prompt_{n}/manifest.json", f"rejected/{job_id}/prompt_{n}/manifest.json"),
        ]

        all_ok = True
        for src_key, dst_key in items:
            try:
                # Check source exists first
                self._client.head_object(Bucket=self.bucket, Key=src_key)
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    logger.debug(f"[S3] Soft-delete: {src_key} not found — skipping")
                    continue
                logger.warning(f"[S3] head_object error for {src_key}: {e}")
                all_ok = False
                continue

            try:
                # Copy to rejected/
                self._client.copy_object(
                    Bucket     = self.bucket,
                    CopySource = {"Bucket": self.bucket, "Key": src_key},
                    Key        = dst_key,
                )
                # Delete original
                self._client.delete_object(Bucket=self.bucket, Key=src_key)
                logger.info(f"[S3] Soft-deleted: {src_key} → {dst_key}")
            except (BotoCoreError, ClientError) as e:
                logger.error(f"[S3] Soft-delete failed for {src_key}: {e}")
                all_ok = False

        return all_ok

    def get_public_url(self, job_id: str, prompt_index: int) -> Optional[str]:
        """
        Return the public URL for a video without uploading.
        Used to reconstruct the URL from job data in the API response.
        """
        if not self.enabled:
            return None
        n   = prompt_index + 1
        key = f"videos/{job_id}/prompt_{n}/output.mp4"
        return self._public_url(key)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _public_url(self, key: str) -> str:
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"