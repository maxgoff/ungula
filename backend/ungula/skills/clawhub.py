"""
ClawHub client for searching and downloading skills.

ClawHub (clawhub.ai) is the public skill registry for OpenClaw agents.
This client enables Ungula to search, browse, and install skills
from the ClawHub registry.

API endpoints (discovered from live site):
  GET /api/search?q=...         -> {results: [{score, slug, displayName, summary, version, updatedAt}]}
  GET /api/skill?slug=...       -> {skill: {..., tags, stats}, latestVersion: {...}, owner: {...}}
  GET /api/download?slug=...    -> ZIP archive of skill files
"""

import logging
import shutil
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://clawhub.ai"


class ClawHubError(Exception):
    """Error communicating with ClawHub."""

    pass


@dataclass
class ClawHubSkillInfo:
    """Summary info for a skill from ClawHub search results."""

    slug: str
    name: str
    description: str
    author: str
    version: str
    downloads: int = 0
    score: float = 0.0


@dataclass
class ClawHubSkillDetail:
    """Detailed info for a skill on ClawHub."""

    slug: str
    name: str
    description: str
    author: str
    version: str
    changelog: str = ""
    stars: int = 0
    downloads: int = 0


class ClawHubClient:
    """HTTP client for the ClawHub skill registry at clawhub.ai."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str) -> list[ClawHubSkillInfo]:
        """Search for skills on ClawHub using vector search.

        ClawHub uses OpenAI embeddings + vector search, so semantic
        queries work well (not just keyword matching).
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/search",
                    params={"q": query},
                )

                if response.status_code != 200:
                    logger.warning(
                        "ClawHub search returned %d: %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return []

                data = response.json()
                results = data.get("results", [])

                return [
                    ClawHubSkillInfo(
                        slug=item.get("slug", ""),
                        name=item.get("displayName", item.get("slug", "")),
                        description=item.get("summary", ""),
                        author=item.get("author", ""),
                        version=item.get("version", "0.0.0"),
                        downloads=item.get("downloads", 0),
                        score=item.get("score", 0.0),
                    )
                    for item in results
                ]

        except httpx.TimeoutException:
            raise ClawHubError("ClawHub search timed out")
        except httpx.ConnectError:
            raise ClawHubError("Could not connect to ClawHub")
        except Exception as e:
            raise ClawHubError(f"ClawHub search failed: {e}")

    async def get_skill(self, slug: str) -> ClawHubSkillDetail:
        """Get detailed info for a skill."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/skill",
                    params={"slug": slug},
                )

                if response.status_code == 404:
                    raise ClawHubError(f"Skill not found: {slug}")
                if response.status_code != 200:
                    raise ClawHubError(f"ClawHub returned {response.status_code}")

                data = response.json()
                skill = data.get("skill", {})
                latest = data.get("latestVersion", {})
                owner = data.get("owner", {})
                stats = skill.get("stats", {})

                return ClawHubSkillDetail(
                    slug=skill.get("slug", slug),
                    name=skill.get("displayName", ""),
                    description=skill.get("summary", ""),
                    author=owner.get("handle", owner.get("displayName", "unknown")),
                    version=latest.get("version", "0.0.0"),
                    changelog=latest.get("changelog", ""),
                    stars=stats.get("stars", 0),
                    downloads=stats.get("downloads", 0),
                )

        except ClawHubError:
            raise
        except Exception as e:
            raise ClawHubError(f"Failed to get skill detail: {e}")

    async def fetch_skill_files(
        self,
        slug: str,
        version: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        """Download a skill and extract file contents in memory (no disk write).

        Used by the compatibility check endpoint to analyze a skill before
        the user decides to install it.

        Returns:
            Tuple of (skill_md_content, supplementary_files_dict).
            supplementary_files_dict maps relative paths to content strings.

        Raises:
            ClawHubError: If download or parsing fails.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params = {"slug": slug}
                if version:
                    params["tag"] = version

                response = await client.get(
                    f"{self.base_url}/api/download",
                    params=params,
                )

                if response.status_code == 404:
                    raise ClawHubError(f"Skill not found: {slug}")
                if response.status_code != 200:
                    raise ClawHubError(f"Download failed with status {response.status_code}")

                skill_md_content: str | None = None
                supplementary_files: dict[str, str] = {}

                try:
                    with zipfile.ZipFile(BytesIO(response.content)) as zf:
                        for name in zf.namelist():
                            if name.endswith("/"):
                                continue  # Skip directories

                            # Normalize path (strip leading directory if nested)
                            parts = Path(name).parts
                            if len(parts) > 1 and parts[0] != "SKILL.md":
                                rel_path = str(Path(*parts[1:]))
                            else:
                                rel_path = name

                            if rel_path == "SKILL.md":
                                skill_md_content = zf.read(name).decode("utf-8")
                            else:
                                try:
                                    supplementary_files[rel_path] = zf.read(name).decode("utf-8")
                                except UnicodeDecodeError:
                                    pass  # Skip binary files

                except zipfile.BadZipFile:
                    # Maybe raw SKILL.md content
                    text = response.text
                    if text.strip().startswith("---") or text.strip().startswith("#"):
                        skill_md_content = text
                    else:
                        raise ClawHubError(f"Unexpected download format for '{slug}'")

                if skill_md_content is None:
                    raise ClawHubError(f"No SKILL.md found in '{slug}'")

                return skill_md_content, supplementary_files

        except ClawHubError:
            raise
        except Exception as e:
            raise ClawHubError(f"Failed to fetch skill files: {e}")

    async def download_skill(
        self,
        slug: str,
        target_dir: Path,
        version: str | None = None,
    ) -> Path:
        """Download a skill zip and extract to target directory.

        The ClawHub download endpoint returns a ZIP archive containing
        the skill files (SKILL.md, references/, etc.).

        Returns:
            Path to the extracted skill directory.
        """
        skill_dir = target_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params = {"slug": slug}
                if version:
                    params["tag"] = version

                response = await client.get(
                    f"{self.base_url}/api/download",
                    params=params,
                )

                if response.status_code == 404:
                    raise ClawHubError(f"Skill not found for download: {slug}")
                if response.status_code != 200:
                    raise ClawHubError(
                        f"Download failed with status {response.status_code}"
                    )

                # Response is a ZIP archive
                try:
                    with zipfile.ZipFile(BytesIO(response.content)) as zf:
                        zf.extractall(skill_dir)
                    logger.info(
                        "Extracted %d files for skill '%s'",
                        len(zf.namelist()),
                        slug,
                    )
                except zipfile.BadZipFile:
                    # Maybe it's raw SKILL.md content
                    content = response.text
                    if content.strip().startswith("---") or content.strip().startswith("#"):
                        (skill_dir / "SKILL.md").write_text(content)
                        logger.info("Wrote raw SKILL.md for skill '%s'", slug)
                    else:
                        raise ClawHubError(
                            f"Download for '{slug}' returned unexpected format"
                        )

        except ClawHubError:
            raise
        except Exception as e:
            raise ClawHubError(f"Failed to download skill: {e}")

        # The zip may contain a SKILL.md at the root, or the files might
        # be nested in a subdirectory. Normalize the layout.
        if not (skill_dir / "SKILL.md").exists():
            for child in skill_dir.iterdir():
                if child.is_dir() and (child / "SKILL.md").exists():
                    for item in child.iterdir():
                        dest = skill_dir / item.name
                        if dest.exists():
                            if dest.is_dir():
                                shutil.rmtree(dest)
                            else:
                                dest.unlink()
                        shutil.move(str(item), str(dest))
                    child.rmdir()
                    break

        if not (skill_dir / "SKILL.md").exists():
            raise ClawHubError(
                f"Downloaded skill '{slug}' does not contain a SKILL.md file"
            )

        return skill_dir
