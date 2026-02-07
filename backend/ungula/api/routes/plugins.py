"""
REST API routes for plugin management.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class InstallRequest(BaseModel):
    path: str


# --- CRUD ---

@router.get("/")
async def list_plugins(request: Request):
    """List all discovered plugins."""
    manager = request.app.state.plugin_manager
    plugins = manager.list_plugins()
    return {"plugins": plugins}


@router.get("/{name}")
async def get_plugin(name: str, request: Request):
    """Get plugin details."""
    manager = request.app.state.plugin_manager
    plugin = manager.get_plugin(name)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return plugin.to_dict()


@router.post("/{name}/enable")
async def enable_plugin(name: str, request: Request):
    """Enable a plugin."""
    manager = request.app.state.plugin_manager
    ok = manager.enable(name)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot enable plugin (not found or has errors)")
    return {"status": "enabled", "name": name}


@router.post("/{name}/disable")
async def disable_plugin(name: str, request: Request):
    """Disable a plugin."""
    manager = request.app.state.plugin_manager
    ok = manager.disable(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"status": "disabled", "name": name}


@router.post("/install")
async def install_plugin(body: InstallRequest, request: Request):
    """Install a plugin from a local path."""
    manager = request.app.state.plugin_manager
    result = manager.install(body.path)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Install failed"))
    return result


@router.delete("/{name}")
async def uninstall_plugin(name: str, request: Request):
    """Uninstall a plugin."""
    manager = request.app.state.plugin_manager
    ok = manager.uninstall(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"status": "uninstalled", "name": name}


@router.post("/reload")
async def reload_plugins(request: Request):
    """Reload all plugins from disk."""
    manager = request.app.state.plugin_manager
    plugins = await manager.reload()
    return {"status": "reloaded", "count": len(plugins)}
