"""
CLI for the Ungula node client.

Usage:
    ungula-node connect --gateway ws://host:8001/ws/node --token <token>
    ungula-node pair --gateway ws://host:8001/ws/node --name "My MacBook"
    ungula-node status --gateway http://localhost:8001
    ungula-node approve --gateway http://localhost:8001 <node_id>
    ungula-node reject --gateway http://localhost:8001 <node_id>
"""

import asyncio
import logging
import sys

import click


def _http_base(gateway_url: str) -> str:
    """Derive HTTP base URL from a gateway URL.

    Handles both ws:// URLs and http:// URLs:
      ws://localhost:8001/ws/node -> http://localhost:8001
      http://localhost:8001       -> http://localhost:8001
    """
    url = gateway_url.replace("ws://", "http://").replace("wss://", "https://")
    # Strip /ws/node path if present
    for suffix in ("/ws/node", "/ws"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """Ungula Node Client — connect as a companion device."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@main.command()
@click.option("--gateway", "-g", required=True, help="Gateway WebSocket URL (e.g. ws://localhost:8001/ws/node)")
@click.option("--token", "-t", required=True, help="Pairing token")
@click.option("--platform", "-p", default=None, help="Platform override (macos, linux, etc.)")
@click.option("--heartbeat", default=30, help="Heartbeat interval in seconds")
def connect(gateway: str, token: str, platform: str | None, heartbeat: int):
    """Connect to an Ungula gateway as a node."""
    # Import handlers to register built-in capabilities
    from . import handlers  # noqa: F401
    from .capabilities import get_capabilities
    from .client import NodeClient

    caps = get_capabilities()
    click.echo(f"Registered capabilities: {', '.join(caps)}")
    click.echo(f"Connecting to {gateway}...")

    client = NodeClient(
        gateway_url=gateway,
        token=token,
        node_platform=platform,
        heartbeat_interval=heartbeat,
    )

    try:
        asyncio.run(client.connect())
    except KeyboardInterrupt:
        click.echo("\nDisconnected.")
        client.stop()


@main.command()
@click.option("--gateway", "-g", required=True, help="Gateway WebSocket URL (e.g. ws://localhost:8001/ws/node)")
@click.option("--name", "-n", required=True, help="Node display name")
@click.option("--platform", "-p", default=None, help="Platform override")
def pair(gateway: str, name: str, platform: str | None):
    """Initiate node-side pairing (connect, request, wait for approval)."""
    from . import handlers  # noqa: F401
    from .capabilities import get_capabilities
    from .client import NodeClient

    caps = get_capabilities()
    click.echo(f"Registered capabilities: {', '.join(caps)}")
    click.echo(f"Requesting pairing at {gateway} as '{name}'...")

    client = NodeClient(gateway_url=gateway, token="")

    try:
        asyncio.run(client.pair_and_connect(
            gateway_url=gateway,
            name=name,
            node_platform=platform,
        ))
    except KeyboardInterrupt:
        click.echo("\nCancelled.")
        client.stop()


@main.command()
@click.option("--gateway", "-g", required=True, help="Gateway URL (e.g. http://localhost:8001)")
def status(gateway: str):
    """Show all nodes and pending pairing requests."""
    try:
        import httpx
    except ImportError:
        click.echo("Error: httpx is required for CLI commands: pip install httpx")
        sys.exit(1)

    base = _http_base(gateway)

    with httpx.Client() as client:
        # List nodes
        try:
            resp = client.get(f"{base}/api/nodes/")
            resp.raise_for_status()
            nodes = resp.json().get("nodes", [])
        except Exception as e:
            click.echo(f"Error fetching nodes: {e}")
            sys.exit(1)

        if nodes:
            click.echo("Nodes:")
            for n in nodes:
                status_str = n.get("status", "unknown")
                click.echo(f"  [{status_str:>8}] {n['name']} ({n['platform']}) — {n['id']}")
        else:
            click.echo("No nodes registered.")

        # List pending
        try:
            resp = client.get(f"{base}/api/nodes/pending")
            resp.raise_for_status()
            pending = resp.json().get("pending", [])
        except Exception as e:
            click.echo(f"Error fetching pending: {e}")
            return

        if pending:
            click.echo("\nPending pairing requests:")
            for p in pending:
                click.echo(f"  {p['name']} ({p['platform']}) — {p['node_id']}")


@main.command()
@click.option("--gateway", "-g", required=True, help="Gateway URL (e.g. http://localhost:8001)")
@click.argument("node_id")
def approve(gateway: str, node_id: str):
    """Approve a pending pairing request."""
    try:
        import httpx
    except ImportError:
        click.echo("Error: httpx is required: pip install httpx")
        sys.exit(1)

    base = _http_base(gateway)

    with httpx.Client() as client:
        try:
            resp = client.post(f"{base}/api/nodes/{node_id}/approve")
            resp.raise_for_status()
            data = resp.json()
            click.echo(f"Approved: {data.get('name', node_id)}")
            token = data.get("token")
            if token:
                click.echo(f"Token: {token}")
        except httpx.HTTPStatusError as e:
            click.echo(f"Error: {e.response.json().get('detail', str(e))}")
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error: {e}")
            sys.exit(1)


@main.command()
@click.option("--gateway", "-g", required=True, help="Gateway URL (e.g. http://localhost:8001)")
@click.argument("node_id")
def reject(gateway: str, node_id: str):
    """Reject a pending pairing request."""
    try:
        import httpx
    except ImportError:
        click.echo("Error: httpx is required: pip install httpx")
        sys.exit(1)

    base = _http_base(gateway)

    with httpx.Client() as client:
        try:
            resp = client.post(f"{base}/api/nodes/{node_id}/reject")
            resp.raise_for_status()
            click.echo(f"Rejected: {node_id}")
        except httpx.HTTPStatusError as e:
            click.echo(f"Error: {e.response.json().get('detail', str(e))}")
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error: {e}")
            sys.exit(1)


@main.command()
def capabilities():
    """List registered capabilities."""
    from . import handlers  # noqa: F401
    from .capabilities import get_capabilities

    caps = get_capabilities()
    if caps:
        for cap in caps:
            click.echo(f"  - {cap}")
    else:
        click.echo("No capabilities registered.")


if __name__ == "__main__":
    main()
