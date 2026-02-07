"""
Image Processing Tool.

Resize, crop, rotate, convert, and inspect images within the workspace.
Uses Pillow (PIL) for image operations.
"""

import logging
import os
from pathlib import Path
from typing import Any

from ungula.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Reuse the same security helpers as file_ops
_DENIED_EXTENSIONS = [".env", ".key", ".pem"]

_SUPPORTED_FORMATS = {"png", "jpeg", "webp", "bmp"}


def _resolve_safe_path(workspace: Path, user_path: str) -> Path | None:
    """Resolve a user-provided path safely within the workspace."""
    target = (workspace / user_path).resolve()
    workspace_resolved = workspace.resolve()
    try:
        target.relative_to(workspace_resolved)
    except ValueError:
        return None
    if target.is_symlink():
        real = target.resolve()
        try:
            real.relative_to(workspace_resolved)
        except ValueError:
            return None
    return target


def _check_extension(path: Path) -> str | None:
    """Check if file extension is denied. Returns error message or None."""
    for ext in _DENIED_EXTENSIONS:
        if path.name.endswith(ext):
            return f"Access denied: {ext} files are blocked"
    return None


class ImageProcessTool(Tool):
    """Process images in the workspace: resize, crop, rotate, convert, thumbnail, info."""

    name = "image_process"
    description = (
        "Process images in the workspace. Actions: info, resize, crop, rotate, convert, thumbnail."
    )
    parameters = [
        ToolParameter(name="action", description="Action to perform: info, resize, crop, rotate, convert, thumbnail", required=True),
        ToolParameter(name="input_path", description="Input image path relative to workspace", required=True),
        ToolParameter(name="output_path", description="Output image path relative to workspace (not needed for info)", required=False),
        ToolParameter(name="width", description="Target width for resize", type="integer", required=False),
        ToolParameter(name="height", description="Target height for resize", type="integer", required=False),
        ToolParameter(name="maintain_aspect", description="Maintain aspect ratio when resizing (default true)", type="boolean", required=False, default=True),
        ToolParameter(name="left", description="Left coordinate for crop", type="integer", required=False),
        ToolParameter(name="top", description="Top coordinate for crop", type="integer", required=False),
        ToolParameter(name="right", description="Right coordinate for crop", type="integer", required=False),
        ToolParameter(name="bottom", description="Bottom coordinate for crop", type="integer", required=False),
        ToolParameter(name="degrees", description="Rotation angle in degrees", type="number", required=False),
        ToolParameter(name="format", description="Target format for convert: png, jpeg, webp, bmp", required=False),
        ToolParameter(name="max_size", description="Max dimension for thumbnail", type="integer", required=False),
    ]

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the image processing action."""
        try:
            from PIL import Image
        except ImportError:
            return ToolResult(
                success=False, output="",
                error="Pillow is not installed. Install with: pip install Pillow",
            )

        action = kwargs.get("action", "")
        input_path_str = kwargs.get("input_path", "")

        if not action:
            return ToolResult(success=False, output="", error="action is required")
        if not input_path_str:
            return ToolResult(success=False, output="", error="input_path is required")

        valid_actions = ("info", "resize", "crop", "rotate", "convert", "thumbnail")
        if action not in valid_actions:
            return ToolResult(
                success=False, output="",
                error=f"Invalid action: {action}. Must be one of: {', '.join(valid_actions)}",
            )

        # Resolve and validate input path
        input_path = _resolve_safe_path(self.workspace_dir, input_path_str)
        if input_path is None:
            return ToolResult(success=False, output="", error="Input path is outside workspace")

        ext_error = _check_extension(input_path)
        if ext_error:
            return ToolResult(success=False, output="", error=ext_error)

        if not input_path.exists():
            return ToolResult(success=False, output="", error=f"File not found: {input_path_str}")
        if not input_path.is_file():
            return ToolResult(success=False, output="", error=f"Not a file: {input_path_str}")

        # Dispatch to action handlers
        if action == "info":
            return self._action_info(input_path, Image)

        # All other actions need an output path
        output_path_str = kwargs.get("output_path", "")
        if not output_path_str:
            return ToolResult(success=False, output="", error="output_path is required for this action")

        output_path = _resolve_safe_path(self.workspace_dir, output_path_str)
        if output_path is None:
            return ToolResult(success=False, output="", error="Output path is outside workspace")

        ext_error = _check_extension(output_path)
        if ext_error:
            return ToolResult(success=False, output="", error=ext_error)

        if action == "resize":
            return self._action_resize(input_path, output_path, kwargs, Image)
        elif action == "crop":
            return self._action_crop(input_path, output_path, kwargs, Image)
        elif action == "rotate":
            return self._action_rotate(input_path, output_path, kwargs, Image)
        elif action == "convert":
            return self._action_convert(input_path, output_path, kwargs, Image)
        elif action == "thumbnail":
            return self._action_thumbnail(input_path, output_path, kwargs, Image)

        return ToolResult(success=False, output="", error=f"Unknown action: {action}")

    def _action_info(self, input_path: Path, Image) -> ToolResult:
        """Return image metadata."""
        try:
            with Image.open(input_path) as img:
                width, height = img.size
                info = {
                    "width": width,
                    "height": height,
                    "format": img.format,
                    "mode": img.mode,
                    "file_size": os.path.getsize(input_path),
                }
                return ToolResult(
                    success=True,
                    output=f"Image: {width}x{height}, format={img.format}, mode={img.mode}",
                    data=info,
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read image: {e}")

    def _action_resize(self, input_path: Path, output_path: Path, kwargs: dict, Image) -> ToolResult:
        """Resize an image."""
        width = kwargs.get("width")
        height = kwargs.get("height")
        maintain_aspect = kwargs.get("maintain_aspect", True)

        if not width and not height:
            return ToolResult(success=False, output="", error="width and/or height required for resize")

        try:
            with Image.open(input_path) as img:
                orig_w, orig_h = img.size

                if maintain_aspect:
                    if width and height:
                        # Fit within the box while maintaining aspect ratio
                        img.thumbnail((width, height), Image.LANCZOS)
                    elif width:
                        ratio = width / orig_w
                        height = int(orig_h * ratio)
                        img = img.resize((width, height), Image.LANCZOS)
                    else:
                        ratio = height / orig_h
                        width = int(orig_w * ratio)
                        img = img.resize((width, height), Image.LANCZOS)
                else:
                    if not width:
                        width = orig_w
                    if not height:
                        height = orig_h
                    img = img.resize((width, height), Image.LANCZOS)

                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(output_path)

                new_w, new_h = img.size
                rel = str(output_path.relative_to(self.workspace_dir))
                return ToolResult(
                    success=True,
                    output=f"Resized {orig_w}x{orig_h} -> {new_w}x{new_h}, saved to {rel}",
                    data={"path": rel, "width": new_w, "height": new_h},
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Resize failed: {e}")

    def _action_crop(self, input_path: Path, output_path: Path, kwargs: dict, Image) -> ToolResult:
        """Crop an image to a bounding box."""
        left = kwargs.get("left")
        top = kwargs.get("top")
        right = kwargs.get("right")
        bottom = kwargs.get("bottom")

        if any(v is None for v in (left, top, right, bottom)):
            return ToolResult(success=False, output="", error="left, top, right, bottom are all required for crop")

        try:
            with Image.open(input_path) as img:
                cropped = img.crop((left, top, right, bottom))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                cropped.save(output_path)

                w, h = cropped.size
                rel = str(output_path.relative_to(self.workspace_dir))
                return ToolResult(
                    success=True,
                    output=f"Cropped to ({left},{top})-({right},{bottom}) = {w}x{h}, saved to {rel}",
                    data={"path": rel, "width": w, "height": h},
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Crop failed: {e}")

    def _action_rotate(self, input_path: Path, output_path: Path, kwargs: dict, Image) -> ToolResult:
        """Rotate an image."""
        degrees = kwargs.get("degrees")
        if degrees is None:
            return ToolResult(success=False, output="", error="degrees is required for rotate")

        try:
            with Image.open(input_path) as img:
                rotated = img.rotate(degrees, expand=True)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                rotated.save(output_path)

                w, h = rotated.size
                rel = str(output_path.relative_to(self.workspace_dir))
                return ToolResult(
                    success=True,
                    output=f"Rotated {degrees} degrees, saved to {rel} ({w}x{h})",
                    data={"path": rel, "width": w, "height": h},
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Rotate failed: {e}")

    def _action_convert(self, input_path: Path, output_path: Path, kwargs: dict, Image) -> ToolResult:
        """Convert image format."""
        target_format = kwargs.get("format", "")
        if not target_format:
            return ToolResult(success=False, output="", error="format is required for convert")

        target_format = target_format.lower()
        if target_format not in _SUPPORTED_FORMATS:
            return ToolResult(
                success=False, output="",
                error=f"Unsupported format: {target_format}. Supported: {', '.join(sorted(_SUPPORTED_FORMATS))}",
            )

        try:
            with Image.open(input_path) as img:
                # Convert RGBA to RGB for JPEG (no alpha channel support)
                if target_format == "jpeg" and img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(output_path, format=target_format.upper())

                rel = str(output_path.relative_to(self.workspace_dir))
                return ToolResult(
                    success=True,
                    output=f"Converted to {target_format.upper()}, saved to {rel}",
                    data={"path": rel, "format": target_format.upper()},
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Convert failed: {e}")

    def _action_thumbnail(self, input_path: Path, output_path: Path, kwargs: dict, Image) -> ToolResult:
        """Generate a thumbnail."""
        max_size = kwargs.get("max_size")
        if not max_size:
            return ToolResult(success=False, output="", error="max_size is required for thumbnail")

        try:
            with Image.open(input_path) as img:
                orig_w, orig_h = img.size
                img.thumbnail((max_size, max_size), Image.LANCZOS)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(output_path)

                w, h = img.size
                rel = str(output_path.relative_to(self.workspace_dir))
                return ToolResult(
                    success=True,
                    output=f"Thumbnail {orig_w}x{orig_h} -> {w}x{h} (max {max_size}), saved to {rel}",
                    data={"path": rel, "width": w, "height": h},
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Thumbnail failed: {e}")
