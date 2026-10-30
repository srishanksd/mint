"""
services/mcp_agent_client.py
Agent-facing MCP client enabling MINT Control Assistant and agents
to discover and execute internal and external MCP tools with audit logging.
"""

import json
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional

from database import get_db_connection
from services.mint_mcp_server import mint_mcp_app
from services.clipper_mcp_client import ClipperMCPClient

logger = logging.getLogger(__name__)


class MCPAgentClient:
    """
    Unified client for agent-driven MCP tool execution.
    Supports in-process tools on MINT MCPServer and external OpenShorts MCP server.
    """

    @classmethod
    def _log_audit(cls, server_name: str, tool_name: str, args: Dict[str, Any], result: Dict[str, Any], is_error: bool, duration_ms: int):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO mcp_audit_logs (
                    server_name, tool_name, arguments_json, result_json, is_error, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                server_name,
                tool_name,
                json.dumps(args, default=str),
                json.dumps(result, default=str)[:3000],
                1 if is_error else 0,
                duration_ms
            ))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to log MCP audit record: %s", exc)

    @classmethod
    def list_available_tools(cls) -> List[Dict[str, Any]]:
        """Returns metadata for all tools exposed by MINT MCP Server and OpenShorts."""
        tools = []
        try:
            mint_tools = asyncio.run(mint_mcp_app.list_tools())
            for t in mint_tools:
                tools.append({
                    "server": "mint_core",
                    "name": t.name,
                    "description": t.description or ""
                })
        except Exception as exc:
            logger.warning("Error querying MINT MCP tools: %s", exc)

        # OpenShorts tools
        tools.extend([
            {"server": "openshorts", "name": "process_video", "description": "Clip YouTube or local video via self-hosted OpenShorts MCP server."},
            {"server": "openshorts", "name": "get_job_status", "description": "Query status of an OpenShorts clipping job."},
            {"server": "openshorts", "name": "list_clips", "description": "List generated clips from an OpenShorts job."},
            {"server": "openshorts", "name": "get_quota", "description": "Check OpenShorts processing quota and resource limits."}
        ])
        return tools

    @classmethod
    def execute_tool(cls, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a registered tool by name with audit logging.
        """
        args = arguments or {}
        t0 = time.time()
        is_error = False

        # 1. Check if tool is an OpenShorts tool
        if tool_name in ["process_video", "get_job_status", "list_clips", "get_quota", "add_subtitles", "recut_clip"]:
            if tool_name == "process_video":
                res = ClipperMCPClient.process_video(
                    source_url=args.get("source_url", args.get("video_url", "")),
                    upload_id=args.get("upload_id"),
                    auto_hook=args.get("auto_hook", True),
                    captions=args.get("captions", True),
                    confirm_rights=args.get("confirm_rights", True)
                )
            elif tool_name == "get_job_status":
                res = ClipperMCPClient.get_job_status(args.get("job_id", ""))
            elif tool_name == "list_clips":
                res = ClipperMCPClient.list_clips(args.get("job_id", ""))
            elif tool_name == "get_quota":
                res = ClipperMCPClient.get_quota()
            else:
                res = {"success": False, "error": f"Tool '{tool_name}' not implemented."}

            duration_ms = int((time.time() - t0) * 1000)
            cls._log_audit("openshorts", tool_name, args, res, not res.get("success", False), duration_ms)
            return res

        # 2. In-process MINT MCP Server execution
        try:
            mcp_res = asyncio.run(mint_mcp_app.call_tool(tool_name, args))
            duration_ms = int((time.time() - t0) * 1000)

            # Extract structured result if present
            if hasattr(mcp_res, "structured_content") and mcp_res.structured_content:
                result = mcp_res.structured_content
                if isinstance(result, dict) and "result" in result and isinstance(result["result"], dict):
                    result = result["result"]
            elif hasattr(mcp_res, "content") and mcp_res.content:
                first_item = mcp_res.content[0]
                text = getattr(first_item, "text", str(first_item))
                try:
                    result = json.loads(text)
                except Exception:
                    result = {"result": text}
            else:
                result = {"result": str(mcp_res)}

            cls._log_audit("mint_core", tool_name, args, result, False, duration_ms)
            return {"success": True, "data": result}
        except Exception as exc:
            duration_ms = int((time.time() - t0) * 1000)
            err_dict = {"success": False, "error": str(exc)}
            cls._log_audit("mint_core", tool_name, args, err_dict, True, duration_ms)
            return err_dict
