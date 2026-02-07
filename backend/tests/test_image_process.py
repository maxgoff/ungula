"""
Tests for the image_process tool.

Covers all actions (info, resize, crop, rotate, convert, thumbnail),
path traversal protection, missing files, and invalid actions.
Uses real Pillow operations with tmp_path fixtures.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock missing third-party LLM provider SDKs before importing tools.
# ---------------------------------------------------------------------------

_MOCK_MODULES = ["anthropic", "openai", "httpx"]
_MOCK_GOOGLE_SUBS = ["google.generativeai", "google.genai", "google.genai.types"]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if "google" not in sys.modules:
    _google_mock = types.ModuleType("google")
    _google_mock.__path__ = []  # type: ignore[attr-defined]
    sys.modules["google"] = _google_mock

for _sub in _MOCK_GOOGLE_SUBS:
    if _sub not in sys.modules:
        sys.modules[_sub] = MagicMock()

from PIL import Image

from ungula.skills.builtin.image_process.tool import ImageProcessTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace directory with a test image."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def tool(workspace: Path) -> ImageProcessTool:
    return ImageProcessTool(workspace)


@pytest.fixture
def png_image(workspace: Path) -> Path:
    """Create a 100x80 RGBA PNG test image."""
    img = Image.new("RGBA", (100, 80), color=(255, 0, 0, 255))
    path = workspace / "test.png"
    img.save(path, format="PNG")
    return path


@pytest.fixture
def rgb_image(workspace: Path) -> Path:
    """Create a 200x150 RGB JPEG test image."""
    img = Image.new("RGB", (200, 150), color=(0, 128, 255))
    path = workspace / "test.jpg"
    img.save(path, format="JPEG")
    return path


# ---------------------------------------------------------------------------
# Info action
# ---------------------------------------------------------------------------


class TestInfoAction:
    async def test_info_returns_correct_metadata(self, tool, png_image):
        result = await tool.execute(action="info", input_path="test.png")
        assert result.success is True
        assert result.data["width"] == 100
        assert result.data["height"] == 80
        assert result.data["format"] == "PNG"
        assert result.data["mode"] == "RGBA"
        assert result.data["file_size"] > 0

    async def test_info_jpeg(self, tool, rgb_image):
        result = await tool.execute(action="info", input_path="test.jpg")
        assert result.success is True
        assert result.data["width"] == 200
        assert result.data["height"] == 150
        assert result.data["format"] == "JPEG"
        assert result.data["mode"] == "RGB"


# ---------------------------------------------------------------------------
# Resize action
# ---------------------------------------------------------------------------


class TestResizeAction:
    async def test_resize_to_exact_dimensions(self, tool, png_image, workspace):
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="resized.png",
            width=50,
            height=40,
            maintain_aspect=False,
        )
        assert result.success is True
        out = Image.open(workspace / "resized.png")
        assert out.size == (50, 40)

    async def test_resize_maintain_aspect_width_only(self, tool, png_image, workspace):
        # Original is 100x80, resize to width=50 maintaining aspect -> 50x40
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="resized.png",
            width=50,
            maintain_aspect=True,
        )
        assert result.success is True
        out = Image.open(workspace / "resized.png")
        assert out.size[0] == 50
        assert out.size[1] == 40  # 80 * (50/100)

    async def test_resize_maintain_aspect_height_only(self, tool, png_image, workspace):
        # Original is 100x80, resize to height=40 maintaining aspect -> 50x40
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="resized.png",
            height=40,
            maintain_aspect=True,
        )
        assert result.success is True
        out = Image.open(workspace / "resized.png")
        assert out.size[0] == 50
        assert out.size[1] == 40

    async def test_resize_maintain_aspect_both_dimensions(self, tool, png_image, workspace):
        # Original is 100x80, resize with box 60x60 maintaining aspect
        # thumbnail fits within 60x60 -> 60x48
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="resized.png",
            width=60,
            height=60,
            maintain_aspect=True,
        )
        assert result.success is True
        out = Image.open(workspace / "resized.png")
        # thumbnail fits within the box, so max dim is 60
        assert out.size[0] <= 60
        assert out.size[1] <= 60

    async def test_resize_no_dimensions(self, tool, png_image):
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="resized.png",
        )
        assert result.success is False
        assert "width" in result.error.lower()


# ---------------------------------------------------------------------------
# Crop action
# ---------------------------------------------------------------------------


class TestCropAction:
    async def test_crop_to_box(self, tool, png_image, workspace):
        result = await tool.execute(
            action="crop",
            input_path="test.png",
            output_path="cropped.png",
            left=10,
            top=10,
            right=60,
            bottom=50,
        )
        assert result.success is True
        out = Image.open(workspace / "cropped.png")
        assert out.size == (50, 40)  # (60-10, 50-10)

    async def test_crop_missing_coordinates(self, tool, png_image):
        result = await tool.execute(
            action="crop",
            input_path="test.png",
            output_path="cropped.png",
            left=10,
            top=10,
            # missing right and bottom
        )
        assert result.success is False
        assert "required" in result.error.lower()


# ---------------------------------------------------------------------------
# Rotate action
# ---------------------------------------------------------------------------


class TestRotateAction:
    async def test_rotate_90_degrees(self, tool, png_image, workspace):
        # Original is 100x80; rotating 90 degrees should swap dimensions
        result = await tool.execute(
            action="rotate",
            input_path="test.png",
            output_path="rotated.png",
            degrees=90,
        )
        assert result.success is True
        out = Image.open(workspace / "rotated.png")
        assert out.size == (80, 100)  # dimensions swapped

    async def test_rotate_180_degrees(self, tool, png_image, workspace):
        result = await tool.execute(
            action="rotate",
            input_path="test.png",
            output_path="rotated.png",
            degrees=180,
        )
        assert result.success is True
        out = Image.open(workspace / "rotated.png")
        assert out.size == (100, 80)  # same dimensions

    async def test_rotate_missing_degrees(self, tool, png_image):
        result = await tool.execute(
            action="rotate",
            input_path="test.png",
            output_path="rotated.png",
        )
        assert result.success is False
        assert "degrees" in result.error.lower()


# ---------------------------------------------------------------------------
# Convert action
# ---------------------------------------------------------------------------


class TestConvertAction:
    async def test_convert_png_to_jpeg(self, tool, png_image, workspace):
        result = await tool.execute(
            action="convert",
            input_path="test.png",
            output_path="converted.jpg",
            format="jpeg",
        )
        assert result.success is True
        out = Image.open(workspace / "converted.jpg")
        assert out.format == "JPEG"

    async def test_convert_jpeg_to_png(self, tool, rgb_image, workspace):
        result = await tool.execute(
            action="convert",
            input_path="test.jpg",
            output_path="converted.png",
            format="png",
        )
        assert result.success is True
        out = Image.open(workspace / "converted.png")
        assert out.format == "PNG"

    async def test_convert_to_webp(self, tool, png_image, workspace):
        result = await tool.execute(
            action="convert",
            input_path="test.png",
            output_path="converted.webp",
            format="webp",
        )
        assert result.success is True
        out = Image.open(workspace / "converted.webp")
        assert out.format == "WEBP"

    async def test_convert_unsupported_format(self, tool, png_image):
        result = await tool.execute(
            action="convert",
            input_path="test.png",
            output_path="converted.tiff",
            format="tiff",
        )
        assert result.success is False
        assert "Unsupported format" in result.error

    async def test_convert_missing_format(self, tool, png_image):
        result = await tool.execute(
            action="convert",
            input_path="test.png",
            output_path="converted.jpg",
        )
        assert result.success is False
        assert "format" in result.error.lower()


# ---------------------------------------------------------------------------
# Thumbnail action
# ---------------------------------------------------------------------------


class TestThumbnailAction:
    async def test_thumbnail_fits_within_max_size(self, tool, png_image, workspace):
        # Original 100x80, thumbnail max_size=40 -> should fit within 40x40
        result = await tool.execute(
            action="thumbnail",
            input_path="test.png",
            output_path="thumb.png",
            max_size=40,
        )
        assert result.success is True
        out = Image.open(workspace / "thumb.png")
        assert out.size[0] <= 40
        assert out.size[1] <= 40

    async def test_thumbnail_preserves_aspect_ratio(self, tool, png_image, workspace):
        # Original 100x80. Thumbnail(50) -> 50x40
        result = await tool.execute(
            action="thumbnail",
            input_path="test.png",
            output_path="thumb.png",
            max_size=50,
        )
        assert result.success is True
        out = Image.open(workspace / "thumb.png")
        assert out.size == (50, 40)

    async def test_thumbnail_missing_max_size(self, tool, png_image):
        result = await tool.execute(
            action="thumbnail",
            input_path="test.png",
            output_path="thumb.png",
        )
        assert result.success is False
        assert "max_size" in result.error.lower()


# ---------------------------------------------------------------------------
# Security: path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    async def test_input_path_traversal_blocked(self, tool):
        result = await tool.execute(
            action="info",
            input_path="../../../etc/passwd",
        )
        assert result.success is False
        assert "outside workspace" in result.error.lower()

    async def test_output_path_traversal_blocked(self, tool, png_image):
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="../../../tmp/evil.png",
            width=50,
            height=50,
        )
        assert result.success is False
        assert "outside workspace" in result.error.lower()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_missing_input_file(self, tool):
        result = await tool.execute(action="info", input_path="nonexistent.png")
        assert result.success is False
        assert "not found" in result.error.lower()

    async def test_invalid_action(self, tool, png_image):
        result = await tool.execute(action="blur", input_path="test.png")
        assert result.success is False
        assert "Invalid action" in result.error

    async def test_missing_action(self, tool, png_image):
        result = await tool.execute(input_path="test.png")
        assert result.success is False
        assert "action is required" in result.error

    async def test_missing_input_path(self, tool):
        result = await tool.execute(action="info")
        assert result.success is False
        assert "input_path is required" in result.error

    async def test_missing_output_path_for_resize(self, tool, png_image):
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            width=50,
        )
        assert result.success is False
        assert "output_path" in result.error.lower()

    async def test_denied_extension(self, tool, workspace):
        # Create a file with denied extension
        env_file = workspace / "secrets.env"
        env_file.write_text("SECRET=123")
        result = await tool.execute(action="info", input_path="secrets.env")
        assert result.success is False
        assert "blocked" in result.error.lower()


# ---------------------------------------------------------------------------
# Subdirectory output
# ---------------------------------------------------------------------------


class TestSubdirectoryOutput:
    async def test_creates_parent_directories(self, tool, png_image, workspace):
        result = await tool.execute(
            action="resize",
            input_path="test.png",
            output_path="sub/dir/resized.png",
            width=50,
            height=40,
            maintain_aspect=False,
        )
        assert result.success is True
        assert (workspace / "sub" / "dir" / "resized.png").exists()
