"""Fixed, synthetic MCP stdio server. No shell, network, external accounts or URLs.

This executable owns only a local test outbox and idempotent receipt lookup.
It is never selected by an uploaded descriptor or user-supplied command.
"""
import argparse
import asyncio
import json
from pathlib import Path
import socket
import sqlite3

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp import types


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


SCOPE = {"type": "string", "minLength": 1, "maxLength": 160}
KEY = {"type": "string", "minLength": 8, "maxLength": 200}
SCHEMAS = {
    "read_status": schema({"scope": SCOPE}, ["scope"]),
    "send_note": schema({"scope": SCOPE, "key": KEY, "note": {"type": "string", "minLength": 1, "maxLength": 2000}}, ["scope", "key", "note"]),
    "lookup_receipt": schema({"scope": SCOPE, "key": KEY}, ["scope", "key"]),
}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    path = Path(parser.parse_args().database)
    if path.is_symlink():
        raise ValueError("fixture_database_symlink")
    db = sqlite3.connect(path, timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS outbox(scope TEXT,key TEXT,note TEXT,PRIMARY KEY(scope,key))")
    db.commit()
    # stdio needs pipes, not internet sockets. Explicit outbound denial remains
    # defense-in-depth, not a claim of OS-level filesystem/process isolation.
    def denied(*args, **kwargs):
        raise OSError("fixture_network_disabled")
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    server = Server("workspace-synthetic-fixture-v1")

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=name, description="Synthetic local fixture only.", inputSchema=value) for name, value in SCHEMAS.items()]

    @server.call_tool()
    async def call_tool(name, arguments):
        scope = arguments["scope"]
        if name == "read_status":
            count = db.execute("SELECT COUNT(*) FROM outbox WHERE scope=?", (scope,)).fetchone()[0]
            value = {"fixture": True, "status": "ready", "outbox_count": count, "text": "Synthetic Harbor workspace status. No external service was contacted."}
        elif name == "send_note":
            key, note = arguments["key"], arguments["note"]
            with db:
                old = db.execute("SELECT note FROM outbox WHERE scope=? AND key=?", (scope, key)).fetchone()
                if old and old[0] != note:
                    raise ValueError("fixture_key_conflict")
                db.execute("INSERT OR IGNORE INTO outbox VALUES(?,?,?)", (scope, key, note))
            value = {"fixture": True, "key": key, "delivered": True, "note": note}
        elif name == "lookup_receipt":
            row = db.execute("SELECT note FROM outbox WHERE scope=? AND key=?", (scope, arguments["key"])).fetchone()
            value = {"fixture": True, "found": bool(row), "key": arguments["key"], "delivered": bool(row), "note": row[0] if row else None}
        else:
            raise ValueError("unsupported_fixture_tool")
        return [types.TextContent(type="text", text=json.dumps(value))]

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
