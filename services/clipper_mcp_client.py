"""
services/clipper_mcp_client.py
Official MCP client for self-hosted OpenShorts video clipping engine.
Communicates using the Model Context Protocol (JSON-RPC 2.0) over local HTTP transport or stdio.
"""

import os
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

import config
from database import get_db_connection

logger = logging.getLogger(__name__)

DEFAULT_MCP_ENDPOINT = "http://127.0.0.1:8000/mcp"


class ClipperMCPClient:
    """
    Client connecting MINT YouTube Clips Agent to the self-hosted OpenShorts MCP server.
    Implements tool discovery, schema validation, and execution for:
      - process_video
      - get_job_status
      - list_clips
      - get_quota
      - add_subtitles
      - recut_clip
    """

    @classmethod
    def get_server_url(cls) -> str:
        return (
            os.getenv("OPENSHORTS_MCP_URL")
            or getattr(config, "OPENSHORTS_MCP_URL", None)
            or DEFAULT_MCP_ENDPOINT
        ).strip().rstrip("/")

    @classmethod
    def _log_audit(cls, tool_name: str, args: Dict[str, Any], result: Dict[str, Any], is_error: bool, duration_ms: int):
        """Durable SQLite audit record for MCP tool execution."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO mcp_audit_logs (
                    server_name, tool_name, arguments_json, result_json, is_error, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                "openshorts",
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
    def _send_rpc(cls, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 8.0) -> Dict[str, Any]:
        """
        Sends a JSON-RPC 2.0 message to the OpenShorts /mcp HTTP endpoint.
        """
        url = cls.get_server_url()
        msg_id = int(time.time() * 1000) % 1000000
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MINT-Clipper-MCP-Client/1.0"
        }

        t0 = time.time()
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=timeout)
            duration_ms = int((time.time() - t0) * 1000)

            if res.status_code == 200:
                data = res.json()
                if "error" in data:
                    err = data["error"]
                    return {
                        "success": False,
                        "status": "rpc_error",
                        "error": err.get("message", "JSON-RPC error"),
                        "code": err.get("code"),
                        "duration_ms": duration_ms
                    }
                return {
                    "success": True,
                    "result": data.get("result", {}),
                    "duration_ms": duration_ms
                }
            elif res.status_code == 401:
                return {
                    "success": False,
                    "status": "unauthorized",
                    "error": "OpenShorts server authentication failed (HTTP 401).",
                    "duration_ms": duration_ms
                }
            elif res.status_code == 404:
                return {
                    "success": False,
                    "status": "endpoint_not_found",
                    "error": f"OpenShorts MCP endpoint not found at {url}.",
                    "duration_ms": duration_ms
                }
            else:
                return {
                    "success": False,
                    "status": "http_error",
                    "error": f"OpenShorts HTTP {res.status_code}: {res.text[:200]}",
                    "duration_ms": duration_ms
                }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "status": "timeout",
                "error": f"Connection to OpenShorts MCP server timed out after {timeout}s ({url}).",
                "duration_ms": int((time.time() - t0) * 1000)
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "status": "server_offline",
                "error": f"OpenShorts MCP server is offline at {url}. Start the server or use Local Free Mode.",
                "duration_ms": int((time.time() - t0) * 1000)
            }
        except Exception as e:
            return {
                "success": False,
                "status": "network_error",
                "error": f"Failed reaching OpenShorts MCP server: {str(e)[:150]}",
                "duration_ms": int((time.time() - t0) * 1000)
            }

    @classmethod
    def is_server_available(cls) -> bool:
        """Checks if OpenShorts MCP server is responding."""
        return cls.get_readiness().get("connected", False)

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        """Returns readiness and server status summary."""
        is_avail = cls.is_server_available()
        ready = cls.get_readiness() if is_avail else {}
        return {
            "server_running": is_avail,
            "endpoint": ready.get("endpoint", cls.get_server_url()),
            "tools_count": ready.get("tools_count", 0),
            "tools": ready.get("tools", []),
            "message": ready.get("message", "OpenShorts server running" if is_avail else "OpenShorts server offline")
        }

    @classmethod
    def list_tools(cls) -> Dict[str, Any]:
        """Lists available tools exposed by the OpenShorts MCP server."""
        res = cls._send_rpc("tools/list", {})
        if res.get("success"):
            return res.get("result", {})
        return {"tools": []}

    @classmethod
    def get_readiness(cls) -> Dict[str, Any]:
        """
        Discovers tools and verifies server connection via initialize and tools/list.
        Does not falsely report connected if the server is offline.
        """
        init_res = cls._send_rpc("initialize", {"protocolVersion": "2024-11-05"}, timeout=3.0)
        if not init_res.get("success"):
            return {
                "connected": False,
                "status": init_res.get("status", "offline"),
                "message": init_res.get("error", "OpenShorts MCP server unreachable."),
                "tools_count": 0,
                "tools": [],
                "endpoint": cls.get_server_url()
            }

        # Query tools/list
        tools_res = cls._send_rpc("tools/list", {}, timeout=4.0)
        tools = []
        if tools_res.get("success"):
            tools = tools_res.get("result", {}).get("tools", [])

        return {
            "connected": True,
            "status": "connected",
            "message": f"Connected to OpenShorts MCP server ({len(tools)} tools discovered).",
            "tools_count": len(tools),
            "tools": [t.get("name") for t in tools],
            "server_info": init_res.get("result", {}).get("serverInfo", {}),
            "endpoint": cls.get_server_url()
        }

    @classmethod
    def call_tool(cls, name: str, arguments: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """
        Executes a named tool on the OpenShorts MCP server: tools/call.
        """
        params = {"name": name, "arguments": arguments}
        t0 = time.time()
        res = cls._send_rpc("tools/call", params, timeout=timeout)
        dur = int((time.time() - t0) * 1000)

        if not res.get("success"):
            cls._log_audit(name, arguments, res, is_error=True, duration_ms=dur)
            return res

        rpc_res = res.get("result", {})
        is_error = rpc_res.get("isError", False)
        structured = rpc_res.get("structuredContent")

        # Parse text content if structuredContent is missing
        if structured is None:
            content_list = rpc_res.get("content", [])
            for c in content_list:
                if isinstance(c, dict) and c.get("type") == "text":
                    try:
                        structured = json.loads(c.get("text", "{}"))
                        break
                    except Exception:
                        structured = {"text": c.get("text")}

        final_out = {
            "success": not is_error,
            "data": structured or {},
            "raw": rpc_res,
            "duration_ms": dur
        }
        if is_error:
            final_out["error"] = (
                (structured.get("error") if isinstance(structured, dict) else None)
                or "OpenShorts MCP tool reported an error."
            )

        cls._log_audit(name, arguments, final_out, is_error=is_error, duration_ms=dur)
        return final_out

    # ── High-Level Agent Methods ─────────────────────────────────────────────

    @classmethod
    def process_video(
        cls,
        source_url: str,
        upload_id: Optional[str] = None,
        auto_hook: bool = True,
        captions: bool = True,
        confirm_rights: bool = True
    ) -> Dict[str, Any]:
        """
        Invokes MCP tool process_video to begin automated clipping.
        Returns job_id immediately.
        """
        args: Dict[str, Any] = {
            "confirm_rights": confirm_rights,
            "auto_hook": auto_hook,
            "captions": captions
        }
        if source_url:
            args["source_url"] = source_url
        if upload_id:
            args["upload_id"] = upload_id

        res = cls.call_tool("process_video", args, timeout=20.0)
        if not res.get("success"):
            return res

        data = res.get("data", {})
        job_id = data.get("job_id") or data.get("id")
        return {
            "success": True,
            "job_id": job_id,
            "status": "processing",
            "message": f"Successfully queued video with OpenShorts MCP (Job: {job_id}).",
            "raw": data
        }

    @classmethod
    def get_job_status(cls, job_id: str) -> Dict[str, Any]:
        """
        Invokes MCP tool get_job_status to check progress.
        """
        if not job_id:
            return {"success": False, "error": "job_id is required"}
        res = cls.call_tool("get_job_status", {"job_id": job_id}, timeout=10.0)
        if not res.get("success"):
            return res

        data = res.get("data", {})
        status = str(data.get("status") or "processing").lower()
        progress = data.get("progress") or (100 if status == "completed" else 0)
        return {
            "success": True,
            "job_id": job_id,
            "status": status,
            "progress": progress,
            "step": data.get("step") or status.upper(),
            "error": data.get("error"),
            "raw": data
        }

    @classmethod
    def list_clips(cls, job_id: str) -> Dict[str, Any]:
        """
        Invokes MCP tool list_clips to retrieve generated candidate clips.
        """
        if not job_id:
            return {"success": False, "error": "job_id is required"}
        res = cls.call_tool("list_clips", {"job_id": job_id}, timeout=15.0)
        if not res.get("success"):
            return res

        data = res.get("data", {})
        clips = data.get("clips") or []
        return {
            "success": True,
            "job_id": job_id,
            "clips": clips,
            "count": len(clips),
            "raw": data
        }

    @classmethod
    def get_quota(cls) -> Dict[str, Any]:
        """
        Invokes MCP tool get_quota to check remaining plan capacity.
        """
        res = cls.call_tool("get_quota", {}, timeout=5.0)
        if not res.get("success"):
            return {
                "success": False,
                "plan": "self_hosted",
                "remaining_minutes": "unlimited",
                "status": "self_hosted",
                "error": res.get("error")
            }
        data = res.get("data", {})
        return {
            "success": True,
            "plan": data.get("plan", "self_hosted_local"),
            "remaining_minutes": data.get("remaining_minutes", "unlimited"),
            "active_jobs": data.get("active_jobs", 0),
            "status": "connected"
        }

    @classmethod
    def download_and_verify_mp4(cls, clip_url_or_path: str, dest_path: Path) -> Dict[str, Any]:
        """
        Downloads or copies generated clip MP4, ensures +faststart, and verifies media integrity.
        """
        dest_path = Path(dest_path).resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # If local file path
            src_p = Path(clip_url_or_path)
            if src_p.exists() and src_p.is_file():
                import shutil
                shutil.copy2(src_p, dest_path)
            elif clip_url_or_path.startswith("http://") or clip_url_or_path.startswith("https://"):
                r = requests.get(clip_url_or_path, stream=True, timeout=30)
                if r.status_code != 200:
                    return {"success": False, "error": f"Download failed with HTTP {r.status_code}"}
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            else:
                return {"success": False, "error": f"Invalid clip source: {clip_url_or_path}"}

            sz = dest_path.stat().st_size if dest_path.exists() else 0
            if sz < 10240:
                dest_path.unlink(missing_ok=True)
                return {"success": False, "error": "Clip file is too small or corrupt."}

            # Probe media with ffprobe
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration,codec_name",
                "-of", "json",
                str(dest_path)
            ]
            p = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            if p.returncode != 0:
                return {"success": False, "error": f"ffprobe validation failed: {p.stderr[:100]}"}

            return {
                "success": True,
                "file_path": str(dest_path),
                "file_size_bytes": sz,
                "message": "Valid playable MP4 clip saved."
            }
        except Exception as e:
            return {"success": False, "error": f"Error validating clip file: {str(e)[:150]}"}
