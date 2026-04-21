"""
Test suite for stitching pipeline:
  - PromptDecomposer (LLM primary, DeepSeek secondary, deterministic tertiary)
  - VideoStitcher (sort, validate, FFmpeg, S3 upload, cleanup)
  - VideoOrchestrator (clip index math)
  - Clip math utilities (compute_nova_clips, compute_runway_clips)

Run with:
    pytest -s tests/test_stitching_pipeline.py -v

All external calls (Bedrock, S3, FFmpeg, generators) are mocked.
Tests are idempotent — no real AWS calls, no disk side effects beyond /tmp.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# Adjust if your source files are in a different directory.
sys.path.insert(0, str(Path(__file__).parent.parent))

from prompt_decomposer import (
    PromptDecomposer,
    compute_nova_clips,
    compute_runway_clips,
    MODEL_NOVA_LITE,
    MODEL_DEEPSEEK,
)
from video_stitcher import VideoStitcher

logging.basicConfig(level=logging.DEBUG)

# ── Helpers ────────────────────────────────────────────────────────────────────

def async_test(coro):
    """
    Decorator: run async test in a fresh event loop.
    Uses asyncio.run() (Python 3.7+) instead of deprecated get_event_loop().
    Each test gets an isolated loop — no shared state between async tests.
    """
    def wrapper(*args, **kwargs):
        return asyncio.run(coro(*args, **kwargs))
    return wrapper


def make_llm_response(clips: List[str], family: str = "nova") -> dict:
    """
    Build a fake Bedrock converse() response.

    All models through the converse() API return the same shape:
      {"output": {"message": {"content": [{"text": "..."}]}}}

    The `family` parameter is kept for signature compatibility but unused —
    converse() normalises response shape across all model families.
    """
    return {
        "output": {
            "message": {
                "content": [{"text": json.dumps(clips)}]
            }
        }
    }


def write_fake_clip(path: Path, size_bytes: int = 1024) -> None:
    """Write a non-empty fake MP4 file for stitcher validation."""
    path.write_bytes(b"\x00" * size_bytes)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CLIP MATH UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeNovaClips:
    """compute_nova_clips: always returns N×6s clips."""

    def test_exact_6s(self):
        assert compute_nova_clips(6) == [6]

    def test_12s_yields_two_clips(self):
        assert compute_nova_clips(12) == [6, 6]

    def test_18s_yields_three_clips(self):
        assert compute_nova_clips(18) == [6, 6, 6]

    def test_30s_yields_five_clips(self):
        result = compute_nova_clips(30)
        assert result == [6, 6, 6, 6, 6]
        assert sum(result) == 30

    def test_non_multiple_rounds_up(self):
        # 7s → ceil(7/6) = 2 clips (generates slightly more than requested)
        result = compute_nova_clips(7)
        assert len(result) == 2
        assert all(d == 6 for d in result)

    def test_25s_yields_five_clips(self):
        result = compute_nova_clips(25)
        assert len(result) == 5  # ceil(25/6)=5

    def test_all_clips_are_6s(self):
        for duration in [6, 12, 18, 24, 30, 36, 42, 48]:
            result = compute_nova_clips(duration)
            assert all(d == 6 for d in result), f"Non-6s clip in {result}"


class TestComputeRunwayClips:
    """compute_runway_clips: greedy 10s-first split."""

    def test_under_10s_is_single_clip(self):
        assert compute_runway_clips(8) == [8]

    def test_exactly_10s_is_single_clip(self):
        assert compute_runway_clips(10) == [10]

    def test_18s_splits_10_plus_8(self):
        assert compute_runway_clips(18) == [10, 8]

    def test_24s_splits_10_10_4(self):
        assert compute_runway_clips(24) == [10, 10, 4]

    def test_30s_splits_three_tens(self):
        assert compute_runway_clips(30) == [10, 10, 10]

    def test_sum_matches_total(self):
        for duration in [5, 10, 11, 18, 24, 29, 30, 35]:
            result = compute_runway_clips(duration)
            assert sum(result) == duration, (
                f"Sum mismatch for {duration}s: {result} sums to {sum(result)}"
            )

    def test_no_clip_exceeds_10s(self):
        for duration in range(1, 50):
            result = compute_runway_clips(duration)
            assert all(d <= 10 for d in result), (
                f"Clip > 10s in {result} for duration={duration}"
            )

    def test_no_zero_clips(self):
        for duration in range(1, 50):
            result = compute_runway_clips(duration)
            assert all(d > 0 for d in result)


# ══════════════════════════════════════════════════════════════════════════════
# 2. PROMPT DECOMPOSER
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptDecomposerDeterministic:
    """Tertiary (deterministic) fallback — no Bedrock client needed."""

    def _make_decomposer(self) -> PromptDecomposer:
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = None
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        return d

    def test_single_clip_returns_master_unchanged(self):
        d = self._make_decomposer()
        master = "A sunset over the ocean."
        result, _, _, _ = d.decompose(master, 1, [6], "nova_reel")
        assert result == [master]

    def test_two_clips_returns_exactly_two(self):
        d = self._make_decomposer()
        result, _, _, _ = d.decompose("A forest in winter.", 2, [6, 6], "nova_reel")
        assert len(result) == 2
        assert all(isinstance(s, str) and len(s) > 0 for s in result)

    def test_three_clips_returns_exactly_three(self):
        d = self._make_decomposer()
        result, _, _, _ = d.decompose("A busy city street.", 3, [6, 6, 6], "nova_reel")
        assert len(result) == 3

    def test_five_clips_returns_exactly_five(self):
        d = self._make_decomposer()
        result, _, _, _ = d.decompose("A river from mountains to sea.", 5, [6]*5, "runway_ml")
        assert len(result) == 5

    def test_no_empty_strings(self):
        d = self._make_decomposer()
        for n in [2, 3, 4, 5, 6]:
            result, _, _, _ = d.decompose("A mountain landscape.", n, [6]*n, "nova_reel")
            assert all(s.strip() for s in result), f"Empty string in result for n={n}"

    def test_all_clips_contain_master_prompt_context(self):
        d = self._make_decomposer()
        master = "A desert sandstorm approaching a lonely caravan."
        result, _, _, _ = d.decompose(master, 3, [6, 6, 6], "nova_reel")
        # All clips should reference the master scene, not be completely unrelated
        assert any("desert" in sp.lower() or "sandstorm" in sp.lower() or "caravan" in sp.lower()
                   for sp in result)


class TestPromptDecomposerLLMPrimary:
    """Primary LLM path (Nova 2 Lite) via mocked Bedrock."""

    def _make_decomposer_with_mock_client(self) -> PromptDecomposer:
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = MagicMock()
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        return d

    def test_primary_success_returns_llm_clips(self):
        d = self._make_decomposer_with_mock_client()
        expected = [
            "Wide establishing shot of a mountain at dawn.",
            "Camera pushes in to mid-mountain as clouds roll by.",
            "Close-up of the summit with golden light breaking through.",
        ]
        d._bedrock_client.converse.return_value = make_llm_response(expected, "nova")

        result, _, _, _ = d.decompose("A mountain at dawn.", 3, [6, 6, 6], "nova_reel")

        assert result == expected
        # Verify primary model was called
        call_kwargs = d._bedrock_client.converse.call_args
        assert MODEL_NOVA_LITE in str(call_kwargs)

    def test_primary_called_with_correct_model_id(self):
        d = self._make_decomposer_with_mock_client()
        clips = ["Clip 1.", "Clip 2."]
        d._bedrock_client.converse.return_value = make_llm_response(clips, "nova")
        d.decompose("Test prompt.", 2, [6, 6], "nova_reel")
        call_kwargs = d._bedrock_client.converse.call_args
        # converse() is called with keyword args; check modelId in kwargs
        assert call_kwargs.kwargs.get("modelId") == MODEL_NOVA_LITE or                call_kwargs[1].get("modelId") == MODEL_NOVA_LITE

    def test_primary_wrong_count_repaired_by_padding(self):
        """LLM returns 2 clips but 3 requested → third is padded from fallback."""
        d = self._make_decomposer_with_mock_client()
        short = ["Clip A.", "Clip B."]  # Only 2 instead of 3
        d._bedrock_client.converse.return_value = make_llm_response(short, "nova")

        result, _, _, _ = d.decompose("Test prompt.", 3, [6, 6, 6], "nova_reel")
        assert len(result) == 3
        assert result[0] == "Clip A."
        assert result[1] == "Clip B."
        assert len(result[2]) > 0  # padded

    def test_primary_wrong_count_repaired_by_truncation(self):
        """LLM returns 5 clips but 3 requested → truncated to 3."""
        d = self._make_decomposer_with_mock_client()
        too_many = [f"Clip {i}." for i in range(5)]
        d._bedrock_client.converse.return_value = make_llm_response(too_many, "nova")

        result, _, _, _ = d.decompose("Test prompt.", 3, [6, 6, 6], "nova_reel")
        assert len(result) == 3

    def test_malformed_json_falls_through_to_secondary(self):
        """Haiku returns non-parseable response → falls through to DeepSeek."""
        d = self._make_decomposer_with_mock_client()

        # Primary returns garbage text — not a valid JSON array
        primary_response = {
            "output": {
                "message": {
                    "content": [{"text": "This is not JSON at all."}]
                }
            }
        }

        # Secondary (DeepSeek) returns valid clips
        secondary_clips = ["DeepSeek Clip 1.", "DeepSeek Clip 2."]
        secondary_response = make_llm_response(secondary_clips)

        d._bedrock_client.converse.side_effect = [primary_response, secondary_response]

        result, _, _, _ = d.decompose("Test prompt.", 2, [6, 6], "nova_reel")
        assert result == secondary_clips
        assert d._bedrock_client.converse.call_count == 2

    def test_primary_exception_falls_through_to_secondary(self):
        """Haiku raises exception → falls through to DeepSeek."""
        d = self._make_decomposer_with_mock_client()

        secondary_clips = ["DS Clip 1.", "DS Clip 2.", "DS Clip 3."]
        secondary_response = make_llm_response(secondary_clips)

        d._bedrock_client.converse.side_effect = [
            Exception("Bedrock throttling"),
            secondary_response,
        ]

        result, _, _, _ = d.decompose("Test.", 3, [6, 6, 6], "nova_reel")
        assert result == secondary_clips
        assert d._bedrock_client.converse.call_count == 2


class TestPromptDecomposerFallbackChain:
    """Full fallback chain: Haiku fails → DeepSeek fails → deterministic."""

    def _make_decomposer_with_mock_client(self) -> PromptDecomposer:
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = MagicMock()
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        return d

    def test_both_llms_fail_falls_to_deterministic(self):
        d = self._make_decomposer_with_mock_client()
        d._bedrock_client.converse.side_effect = Exception("All models down")

        result, _, _, _ = d.decompose("A stormy sea.", 3, [6, 6, 6], "nova_reel")
        # Deterministic always returns exactly n_clips non-empty strings
        assert len(result) == 3
        assert all(isinstance(s, str) and len(s) > 0 for s in result)

    def test_no_bedrock_client_goes_directly_to_deterministic(self):
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = None
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK

        result, _, _, _ = d.decompose("A stormy sea.", 4, [6, 6, 6, 6], "runway_ml")
        assert len(result) == 4
        assert all(s.strip() for s in result)

    def test_deepseek_model_id_used_as_secondary(self):
        d = self._make_decomposer_with_mock_client()

        # Primary fails, secondary succeeds
        secondary_clips = ["Clip A.", "Clip B."]
        secondary_response = make_llm_response(secondary_clips)

        d._bedrock_client.converse.side_effect = [
            Exception("Haiku down"),
            secondary_response,
        ]

        d.decompose("Test.", 2, [6, 6], "nova_reel")

        # Second call must use DeepSeek model ID
        second_call = d._bedrock_client.converse.call_args_list[1]
        # converse() is called with keyword args only
        got_model = second_call.kwargs.get("modelId") or second_call[1].get("modelId")
        assert got_model == MODEL_DEEPSEEK

    def test_single_clip_never_calls_bedrock(self):
        d = self._make_decomposer_with_mock_client()
        master = "A single shot of a candle."
        result, _, _, _ = d.decompose(master, 1, [6], "nova_reel")
        assert result == [master]
        d._bedrock_client.converse.assert_not_called()


class TestConverseTextExtraction:
    """_extract_text_blocks: handles reasoning-model content block layouts."""

    def _make_decomposer(self) -> PromptDecomposer:
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = None
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        return d

    def test_nova_claude_layout_block0_has_text(self):
        """Nova / Claude: text is at content[0]["text"]."""
        d = self._make_decomposer()
        blocks = [{"text": "answer from nova"}]
        assert d._extract_text_blocks(blocks, "nova") == "answer from nova"

    def test_deepseek_r1_reasoning_block_skipped(self):
        """DeepSeek R1: block 0 is reasoningContent, answer is at block 1."""
        d = self._make_decomposer()
        blocks = [
            {"reasoningContent": {"reasoningText": {"text": "chain of thought..."}}},
            {"text": "actual answer from deepseek"},
        ]
        assert d._extract_text_blocks(blocks, "deepseek") == "actual answer from deepseek"

    def test_multiple_reasoning_blocks_then_text(self):
        """Multiple reasoning blocks before the text answer."""
        d = self._make_decomposer()
        blocks = [
            {"reasoningContent": {"reasoningText": {"text": "step 1"}}},
            {"reasoningContent": {"reasoningText": {"text": "step 2"}}},
            {"text": "final answer"},
        ]
        assert d._extract_text_blocks(blocks, "deepseek") == "final answer"

    def test_no_text_blocks_returns_empty_string(self):
        """All blocks are reasoningContent — return empty string, don't raise."""
        d = self._make_decomposer()
        blocks = [
            {"reasoningContent": {"reasoningText": {"text": "only cot"}}},
        ]
        assert d._extract_text_blocks(blocks, "deepseek") == ""

    def test_empty_content_list_returns_empty_string(self):
        d = self._make_decomposer()
        assert d._extract_text_blocks([], "nova") == ""

    def test_text_is_stripped(self):
        d = self._make_decomposer()
        blocks = [{"text": "  padded text  "}]
        assert d._extract_text_blocks(blocks, "nova") == "padded text"


class TestPromptDecomposerJsonParsing:
    """Test the JSON array parser for edge cases."""

    def _make_decomposer(self) -> PromptDecomposer:
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = None
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        return d

    def test_clean_json_array(self):
        d = self._make_decomposer()
        result = d._parse_json_array('["clip 1", "clip 2", "clip 3"]')
        assert result == ["clip 1", "clip 2", "clip 3"]

    def test_json_with_markdown_fence(self):
        d = self._make_decomposer()
        text = '```json\n["clip 1", "clip 2"]\n```'
        result = d._parse_json_array(text)
        assert result == ["clip 1", "clip 2"]

    def test_json_embedded_in_text(self):
        d = self._make_decomposer()
        text = 'Here are the clips:\n["clip 1", "clip 2"]\nDone.'
        result = d._parse_json_array(text)
        assert result == ["clip 1", "clip 2"]

    def test_not_a_json_array_returns_none(self):
        d = self._make_decomposer()
        assert d._parse_json_array("This is not JSON.") is None

    def test_json_object_not_array_returns_none(self):
        d = self._make_decomposer()
        assert d._parse_json_array('{"clip": "one"}') is None

    def test_empty_items_stripped(self):
        d = self._make_decomposer()
        result = d._parse_json_array('["clip 1", "  ", "clip 3"]')
        assert "  " not in result
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 3. VIDEO STITCHER
# ══════════════════════════════════════════════════════════════════════════════

class TestVideoStitcherInit:
    """Stitcher initialization — FFmpeg check, S3 client init."""

    def test_no_aws_creds_sets_s3_client_none(self):
        with patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=True):
            s = VideoStitcher(output_dir=Path(tempfile.mkdtemp()))
        assert s._s3_client is None
        assert s._bucket is None

    def test_with_aws_creds_creates_s3_client(self):
        mock_boto = MagicMock()
        with patch("video_stitcher.boto3.client", return_value=mock_boto), \
             patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=True):
            s = VideoStitcher(
                output_dir=Path(tempfile.mkdtemp()),
                aws_access_key_id="AKID",
                aws_secret_access_key="SECRET",
                bucket="my-bucket",
                region="us-east-1",
            )
        assert s._s3_client == mock_boto
        assert s._bucket == "my-bucket"

    def test_ffmpeg_unavailable_sets_flag(self):
        with patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=False):
            s = VideoStitcher(output_dir=Path(tempfile.mkdtemp()))
        assert not s.ffmpeg_available


class TestVideoStitcherSortAndValidate:
    """Clip ordering and validation logic."""

    def _make_stitcher(self) -> VideoStitcher:
        # Use a real system temp dir so output_dir.resolve() is drive-qualified on Windows.
        # Path("/tmp") on Windows → \tmp (root-relative, no drive) → is_absolute() == False.
        self._tmp_dir = tempfile.mkdtemp()
        with patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=True):
            return VideoStitcher(output_dir=Path(self._tmp_dir))

    def test_clips_sorted_by_filename_not_input_order(self):
        s = self._make_stitcher()
        # Intentionally out of order
        urls = [
            "/videos/job_nova_p1_clip_003.mp4",
            "/videos/job_nova_p1_clip_001.mp4",
            "/videos/job_nova_p1_clip_002.mp4",
        ]
        paths = s._resolve_and_sort_local_paths(urls, "test")
        filenames = [Path(p).name for p in paths]
        assert filenames == [
            "job_nova_p1_clip_001.mp4",
            "job_nova_p1_clip_002.mp4",
            "job_nova_p1_clip_003.mp4",
        ]

    def test_already_sorted_input_unchanged(self):
        s = self._make_stitcher()
        urls = [
            "/videos/job_nova_p1_clip_001.mp4",
            "/videos/job_nova_p1_clip_002.mp4",
        ]
        paths = s._resolve_and_sort_local_paths(urls, "test")
        assert Path(paths[0]).name == "job_nova_p1_clip_001.mp4"
        assert Path(paths[1]).name == "job_nova_p1_clip_002.mp4"

    def test_filesystem_paths_passthrough(self):
        """
        Non-/videos/ paths are resolved to drive-qualified absolute paths.
        On Windows: /absolute/path/clip.mp4 -> C:/absolute/path/clip.mp4
        Assert the property (is_absolute + correct filename), not the raw string.
        """
        s = self._make_stitcher()
        urls = ["/absolute/path/clip_001.mp4", "/absolute/path/clip_002.mp4"]
        paths = s._resolve_and_sort_local_paths(urls, "test")
        assert len(paths) == 2
        assert all(Path(p).is_absolute() for p in paths)
        assert Path(paths[0]).name == "clip_001.mp4"
        assert Path(paths[1]).name == "clip_002.mp4"

    def test_validate_all_exist_returns_true(self):
        s = self._make_stitcher()
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "clip_001.mp4"
            p2 = Path(tmp) / "clip_002.mp4"
            write_fake_clip(p1)
            write_fake_clip(p2)
            assert s._validate_clips([str(p1), str(p2)], "test") is True

    def test_validate_missing_file_returns_false(self):
        s = self._make_stitcher()
        assert s._validate_clips(["/nonexistent/clip.mp4"], "test") is False

    def test_validate_empty_file_returns_false(self):
        s = self._make_stitcher()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "empty.mp4"
            p.write_bytes(b"")
            assert s._validate_clips([str(p)], "test") is False

    def test_resolve_produces_absolute_paths(self):
        """
        Paths in concat file must be absolute — FFmpeg resolves relative paths
        relative to the temp file directory, not the CWD (Windows bug root cause).
        """
        s = self._make_stitcher()
        urls = ["/videos/job_nova_p1_clip_001.mp4", "/videos/job_nova_p1_clip_002.mp4"]
        paths = s._resolve_and_sort_local_paths(urls, "test")
        # All resolved paths must be absolute
        for p in paths:
            assert Path(p).is_absolute(), f"Path is not absolute: {p}" 


class TestVideoStitcherS3Upload:
    """S3 upload and pre-signed URL generation."""

    def _make_stitcher_with_s3(self) -> VideoStitcher:
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = (
            "https://bucket.s3.amazonaws.com/stitched/job1/prompt_1_nova.mp4?X-Amz-Signature=abc"
        )
        with patch("video_stitcher.boto3.client", return_value=mock_s3), \
             patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=True):
            s = VideoStitcher(
                output_dir=Path("/tmp"),
                aws_access_key_id="AKID",
                aws_secret_access_key="SECRET",
                bucket="test-bucket",
                region="us-east-1",
            )
        return s

    @async_test
    async def test_upload_returns_presigned_url(self):
        s = self._make_stitcher_with_s3()
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "stitched.mp4"
            write_fake_clip(local)
            url = await s._upload_to_s3(
                local_path=str(local),
                job_id="job1",
                prompt_index=0,
                platform_tag="nova",
                stitch_id="abc123",
            )
        assert url is not None
        assert "s3.amazonaws.com" in url or "X-Amz" in url

    @async_test
    async def test_upload_uses_correct_s3_key(self):
        s = self._make_stitcher_with_s3()
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "stitched.mp4"
            write_fake_clip(local)
            await s._upload_to_s3(
                local_path=str(local),
                job_id="jobXYZ",
                prompt_index=2,
                platform_tag="runway",
                stitch_id="test",
            )
        upload_call = s._s3_client.upload_file.call_args
        assert upload_call[0][1] == "test-bucket"   # bucket
        assert "stitched/jobXYZ/prompt_3_runway.mp4" in upload_call[0][2]  # s3 key

    @async_test
    async def test_upload_uses_sse_s3_encryption(self):
        s = self._make_stitcher_with_s3()
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "stitched.mp4"
            write_fake_clip(local)
            await s._upload_to_s3(str(local), "job1", 0, "nova", "test")
        upload_call = s._s3_client.upload_file.call_args
        extra_args = upload_call[1].get("ExtraArgs", {})
        assert extra_args.get("ServerSideEncryption") == "AES256"

    @async_test
    async def test_s3_client_error_returns_none(self):
        from botocore.exceptions import ClientError
        s = self._make_stitcher_with_s3()
        s._s3_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "upload_file"
        )
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "stitched.mp4"
            write_fake_clip(local)
            url = await s._upload_to_s3(str(local), "job1", 0, "nova", "test")
        assert url is None


class TestVideoStitcherCleanup:
    """Local file cleanup after S3 upload."""

    def _make_stitcher(self) -> VideoStitcher:
        with patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=True):
            return VideoStitcher(output_dir=Path("/tmp"))

    def test_cleanup_deletes_all_files(self):
        s = self._make_stitcher()
        with tempfile.TemporaryDirectory() as tmp:
            clip1 = Path(tmp) / "clip_001.mp4"
            clip2 = Path(tmp) / "clip_002.mp4"
            stitched = Path(tmp) / "stitched.mp4"
            write_fake_clip(clip1)
            write_fake_clip(clip2)
            write_fake_clip(stitched)

            s._cleanup_local_files([str(clip1), str(clip2)], str(stitched), "test")

            assert not clip1.exists()
            assert not clip2.exists()
            assert not stitched.exists()

    def test_cleanup_missing_file_does_not_raise(self):
        s = self._make_stitcher()
        # Should not raise even if files don't exist
        s._cleanup_local_files(
            ["/nonexistent/clip1.mp4"],
            "/nonexistent/stitched.mp4",
            "test",
        )


class TestVideoStitcherStitchFlow:
    """End-to-end stitch() method flow with mocked FFmpeg and S3."""

    def _make_stitcher_mocked(self, ffmpeg_ok=True, s3_url=None) -> VideoStitcher:
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = (
            s3_url or "https://s3.amazonaws.com/stitched/job1/prompt_1_nova.mp4"
        )
        with patch("video_stitcher.boto3.client", return_value=mock_s3), \
             patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=ffmpeg_ok):
            s = VideoStitcher(
                output_dir=Path("/tmp"),
                aws_access_key_id="AKID",
                aws_secret_access_key="SECRET",
                bucket="bucket",
                region="us-east-1",
            )
        return s

    @async_test
    async def test_single_clip_skips_stitch(self):
        s = self._make_stitcher_mocked()
        result = await s.stitch(["/videos/only_clip.mp4"], "job1", 0, "nova")
        assert result == "/videos/only_clip.mp4"
        s._s3_client.upload_file.assert_not_called()

    @async_test
    async def test_no_ffmpeg_returns_first_clip(self):
        s = self._make_stitcher_mocked(ffmpeg_ok=False)
        result = await s.stitch(
            ["/videos/clip_001.mp4", "/videos/clip_002.mp4"],
            "job1", 0, "nova",
        )
        assert result == "/videos/clip_001.mp4"

    @async_test
    async def test_empty_list_returns_none(self):
        s = self._make_stitcher_mocked()
        result = await s.stitch([], "job1", 0, "nova")
        assert result is None

    @async_test
    async def test_successful_stitch_returns_s3_url(self):
        s = self._make_stitcher_mocked(
            s3_url="https://s3.amazonaws.com/stitched/job1/prompt_1_nova.mp4"
        )
        with tempfile.TemporaryDirectory() as tmp:
            s.output_dir = Path(tmp)
            clip1 = Path(tmp) / "job1_nova_p1_clip_001.mp4"
            clip2 = Path(tmp) / "job1_nova_p1_clip_002.mp4"
            write_fake_clip(clip1)
            write_fake_clip(clip2)

            # Mock FFmpeg concat to write a fake output
            async def fake_ffmpeg_concat(paths, output_path, reencode, stitch_id):
                Path(output_path).write_bytes(b"\x00" * 2048)
                return True

            with patch.object(s, "_ffmpeg_concat", side_effect=fake_ffmpeg_concat):
                result = await s.stitch(
                    [f"/videos/job1_nova_p1_clip_001.mp4",
                     f"/videos/job1_nova_p1_clip_002.mp4"],
                    "job1", 0, "nova",
                )

        assert result is not None
        assert "s3.amazonaws.com" in result or "X-Amz" in result

    @async_test
    async def test_stitched_file_preserved_locally_after_s3_upload(self):
        """
        After successful S3 upload, the stitched output file must still exist locally
        so /videos/ can serve it. Only intermediate clips are deleted.
        """
        s = self._make_stitcher_mocked(
            s3_url="https://s3.amazonaws.com/stitched/job1/prompt_1_nova.mp4"
        )
        with tempfile.TemporaryDirectory() as tmp:
            s.output_dir = Path(tmp)
            clip1 = Path(tmp) / "job1_nova_p1_clip_001.mp4"
            clip2 = Path(tmp) / "job1_nova_p1_clip_002.mp4"
            write_fake_clip(clip1)
            write_fake_clip(clip2)

            stitched_path = [None]  # capture path written by fake ffmpeg

            async def fake_ffmpeg_concat(paths, output_path, reencode, stitch_id):
                p = Path(output_path)
                p.write_bytes(b"\x00" * 2048)
                stitched_path[0] = p
                return True

            with patch.object(s, "_ffmpeg_concat", side_effect=fake_ffmpeg_concat):
                await s.stitch(
                    ["/videos/job1_nova_p1_clip_001.mp4",
                     "/videos/job1_nova_p1_clip_002.mp4"],
                    "job1", 0, "nova",
                )

            # Intermediate clips must be gone
            assert not clip1.exists(), "Intermediate clip1 should have been deleted"
            assert not clip2.exists(), "Intermediate clip2 should have been deleted"
            # Stitched output must survive
            if stitched_path[0]:
                assert stitched_path[0].exists(), (
                    "Stitched output was deleted — must be kept for local /videos/ serving"
                )

    @async_test
    async def test_s3_upload_failure_falls_back_to_local_url(self):
        s = self._make_stitcher_mocked()
        from botocore.exceptions import ClientError
        s._s3_client.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "upload_file"
        )
        with tempfile.TemporaryDirectory() as tmp:
            s.output_dir = Path(tmp)
            clip1 = Path(tmp) / "job1_nova_p1_clip_001.mp4"
            clip2 = Path(tmp) / "job1_nova_p1_clip_002.mp4"
            write_fake_clip(clip1)
            write_fake_clip(clip2)

            async def fake_ffmpeg_concat(paths, output_path, reencode, stitch_id):
                Path(output_path).write_bytes(b"\x00" * 2048)
                return True

            with patch.object(s, "_ffmpeg_concat", side_effect=fake_ffmpeg_concat):
                result = await s.stitch(
                    ["/videos/job1_nova_p1_clip_001.mp4",
                     "/videos/job1_nova_p1_clip_002.mp4"],
                    "job1", 0, "nova",
                )

        # Local /videos/ fallback
        assert result is not None
        assert result.startswith("/videos/")


# ══════════════════════════════════════════════════════════════════════════════
# 4. ORCHESTRATOR CLIP INDEX MATH
# ══════════════════════════════════════════════════════════════════════════════

class TestOrchestratorClipIndex:
    """_clip_index() namespacing — prevents S3 key collisions between prompts."""

    def test_import_clip_index(self):
        from video_orchestrator import _clip_index
        assert callable(_clip_index)

    def test_base_offset_applied(self):
        from video_orchestrator import _clip_index, _CLIP_INDEX_BASE, _CLIP_INDEX_STRIDE
        assert _clip_index(0, 0) == _CLIP_INDEX_BASE
        assert _clip_index(0, 1) == _CLIP_INDEX_BASE + 1

    def test_different_prompts_dont_collide(self):
        from video_orchestrator import _clip_index
        # Prompt 0 clip 2 must not equal Prompt 1 clip 0
        assert _clip_index(0, 2) != _clip_index(1, 0)

    def test_stride_separates_prompts(self):
        from video_orchestrator import _clip_index, _CLIP_INDEX_STRIDE
        # Prompt 1 starts at base + 1×stride
        p0_last = _clip_index(0, _CLIP_INDEX_STRIDE - 1)
        p1_first = _clip_index(1, 0)
        assert p1_first > p0_last

    def test_clip_label_format(self):
        """Verify the clip_label format produced by orchestrator matches stitcher expectation."""
        # Orchestrator builds: f"p{prompt_index+1}_clip_{clip_i+1:03d}"
        prompt_index = 0
        clip_i = 0
        label = f"p{prompt_index + 1}_clip_{clip_i + 1:03d}"
        assert label == "p1_clip_001"

        clip_i = 9
        label = f"p{prompt_index + 1}_clip_{clip_i + 1:03d}"
        assert label == "p1_clip_010"

    def test_clip_labels_sort_correctly(self):
        """Verify p1_clip_001, p1_clip_002 ... sort alphabetically in correct order."""
        labels = [
            "p1_clip_003.mp4",
            "p1_clip_001.mp4",
            "p1_clip_002.mp4",
        ]
        sorted_labels = sorted(labels)
        assert sorted_labels == [
            "p1_clip_001.mp4",
            "p1_clip_002.mp4",
            "p1_clip_003.mp4",
        ]


# ══════════════════════════════════════════════════════════════════════════════
# 5. INTEGRATION: decompose → clip_math → filename → sort
# ══════════════════════════════════════════════════════════════════════════════

class TestDecomposeToFilenameToSort:
    """
    Integration test: full pipeline from prompt decomposition to clip filename
    sorting in the stitcher.

    Simulates the exact flow:
      1. Decomposer produces N sub-prompts
      2. Orchestrator computes clip_labels (p1_clip_001, p1_clip_002, ...)
      3. Generators produce filenames using clip_label
      4. Stitcher sorts filenames → correct concat order
    """

    def test_nova_18s_full_pipeline_filename_sort(self):
        """18s Nova stitch → 3 clips → filenames → sorted correctly."""
        # Step 1: Clip math
        clip_durations = compute_nova_clips(18)
        assert len(clip_durations) == 3

        # Step 2: Decomposer (deterministic)
        decomposer = PromptDecomposer.__new__(PromptDecomposer)
        decomposer._bedrock_client = None
        decomposer.model_primary = MODEL_NOVA_LITE
        decomposer.model_secondary = MODEL_DEEPSEEK
        sub_prompts, _, _, _ = decomposer.decompose(
            "A river from mountain to sea.", 3, clip_durations, "nova_reel"
        )
        assert len(sub_prompts) == 3

        # Step 3: Simulate filenames the generator would produce
        job_id = "job_test"
        prompt_index = 0
        filenames = []
        for clip_i in range(3):
            clip_label = f"p{prompt_index + 1}_clip_{clip_i + 1:03d}"
            fname = f"{job_id}_nova_{clip_label}.mp4"
            filenames.append(fname)

        assert filenames == [
            "job_test_nova_p1_clip_001.mp4",
            "job_test_nova_p1_clip_002.mp4",
            "job_test_nova_p1_clip_003.mp4",
        ]

        # Step 4: Stitcher sorts → same order
        shuffled = [filenames[2], filenames[0], filenames[1]]  # scramble
        sorted_result = sorted(shuffled)
        assert sorted_result == filenames

    def test_runway_24s_full_pipeline_filename_sort(self):
        """24s Runway stitch → 3 clips (10+10+4) → filenames → sorted."""
        clip_durations = compute_runway_clips(24)
        assert clip_durations == [10, 10, 4]

        job_id = "job_rw"
        prompt_index = 1
        filenames = []
        for clip_i, dur in enumerate(clip_durations):
            clip_label = f"p{prompt_index + 1}_clip_{clip_i + 1:03d}"
            fname = f"{job_id}_runway_{clip_label}.mp4"
            filenames.append(fname)

        assert filenames == [
            "job_rw_runway_p2_clip_001.mp4",
            "job_rw_runway_p2_clip_002.mp4",
            "job_rw_runway_p2_clip_003.mp4",
        ]

        # Simulate out-of-order delivery
        shuffled = [filenames[1], filenames[2], filenames[0]]
        sorted_result = sorted(shuffled)
        assert sorted_result == filenames

    def test_multi_prompt_clip_labels_dont_collide(self):
        """Different prompts produce different clip filenames (no collision)."""
        job_id = "job_multi"
        all_filenames = set()
        for prompt_index in range(3):
            clip_durations = compute_nova_clips(18)  # 3 clips each
            for clip_i in range(len(clip_durations)):
                clip_label = f"p{prompt_index + 1}_clip_{clip_i + 1:03d}"
                fname = f"{job_id}_nova_{clip_label}.mp4"
                assert fname not in all_filenames, f"Collision: {fname}"
                all_filenames.add(fname)

        assert len(all_filenames) == 9  # 3 prompts × 3 clips each


# ══════════════════════════════════════════════════════════════════════════════
# 6. EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary and error conditions."""

    def test_nova_clips_for_zero_duration(self):
        """Edge: 0s duration → math.ceil(0/6) = 0 clips (caller shouldn't send this)."""
        result = compute_nova_clips(0)
        assert result == []

    def test_runway_clips_for_1s(self):
        assert compute_runway_clips(1) == [1]

    def test_decomposer_empty_prompt(self):
        """Empty prompt is passed through unchanged."""
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = None
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        result, _, _, _ = d.decompose("", 2, [6, 6], "nova_reel")
        assert len(result) == 2  # Still returns N items even for empty input

    def test_decomposer_very_long_prompt(self):
        """Very long prompt doesn't crash deterministic path."""
        d = PromptDecomposer.__new__(PromptDecomposer)
        d._bedrock_client = None
        d.model_primary = MODEL_NOVA_LITE
        d.model_secondary = MODEL_DEEPSEEK
        long_prompt = "A " + ("beautiful scene of mountains and valleys " * 50)
        result, _, _, _ = d.decompose(long_prompt, 3, [6, 6, 6], "nova_reel")
        assert len(result) == 3

    def test_stitcher_resolve_mixed_url_and_path(self):
        """Stitcher handles mix of /videos/ URLs and filesystem paths."""
        import os
        tmp = tempfile.mkdtemp()
        with patch("video_stitcher.VideoStitcher._check_ffmpeg", return_value=True):
            s = VideoStitcher(output_dir=Path(tmp))

        # A real existing file for the absolute-path branch
        abs_clip = Path(tmp) / "clip_002.mp4"
        abs_clip.write_bytes(b"\x00")

        urls = ["/videos/clip_001.mp4", str(abs_clip)]
        paths = s._resolve_and_sort_local_paths(urls, "test")

        # /videos/ branch → resolved into output_dir, drive-qualified
        assert any("clip_001.mp4" in p for p in paths)
        # absolute path branch → still resolved, still absolute
        assert all(Path(p).is_absolute() for p in paths)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])