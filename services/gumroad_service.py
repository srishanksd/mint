import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import requests
from dotenv import load_dotenv
from database import get_db_connection

load_dotenv()
logger = logging.getLogger("mint.gumroad")

class GumroadService:
    """
    Isolated integration service for Gumroad API v2.
    Adheres strictly to Gumroad API capabilities:
    - Verifies account access via GET /v2/user
    - Creates/syncs product metadata via POST/PUT /v2/products
    - Enables/publishes products via PUT /v2/products/:id/enable
    - Distinguishes 'published' from 'draft_created' (e.g. when Gumroad requires payout setup)
    - Never leaks access tokens in logs, responses, or client data
    """

    API_BASE = "https://api.gumroad.com/v2"

    @classmethod
    def get_access_token(cls) -> Optional[str]:
        return os.getenv("GUMROAD_ACCESS_TOKEN", "").strip() or None

    @classmethod
    def is_auto_publish_enabled(cls) -> bool:
        val = os.getenv("GUMROAD_AUTO_PUBLISH", "0").strip().lower()
        return val in ("1", "true", "yes", "on")

    @classmethod
    def get_status(cls, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Verifies the Gumroad connection status without exposing the token.
        """
        token = cls.get_access_token()
        if not token:
            return {
                "connected": False,
                "status": "not_configured",
                "message": "Gumroad access token not configured in .env",
                "user": None,
                "auto_publish": cls.is_auto_publish_enabled(),
            }

        try:
            resp = requests.get(
                f"{cls.API_BASE}/user",
                params={"access_token": token},
                timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    user_info = data.get("user", {})
                    return {
                        "connected": True,
                        "status": "connected",
                        "message": f"Connected to Gumroad as {user_info.get('name') or user_info.get('email')}",
                        "user": {
                            "name": user_info.get("name"),
                            "email": user_info.get("email"),
                            "profile_url": user_info.get("url"),
                            "currency_type": user_info.get("currency_type", "usd"),
                        },
                        "auto_publish": cls.is_auto_publish_enabled(),
                    }
                else:
                    return {
                        "connected": False,
                        "status": "rejected",
                        "message": data.get("message", "Gumroad API returned unsuccessful response"),
                        "user": None,
                        "auto_publish": cls.is_auto_publish_enabled(),
                    }
            elif resp.status_code in (401, 403):
                return {
                    "connected": False,
                    "status": "invalid_token",
                    "message": "Gumroad API rejected access token (unauthorized)",
                    "user": None,
                    "auto_publish": cls.is_auto_publish_enabled(),
                }
            else:
                return {
                    "connected": False,
                    "status": "api_error",
                    "message": f"Gumroad API returned HTTP {resp.status_code}",
                    "user": None,
                    "auto_publish": cls.is_auto_publish_enabled(),
                }
        except requests.exceptions.Timeout:
            return {
                "connected": False,
                "status": "timeout",
                "message": "Connection to Gumroad timed out",
                "user": None,
                "auto_publish": cls.is_auto_publish_enabled(),
            }
        except Exception as e:
            logger.warning(f"Gumroad status check failed: {e}")
            return {
                "connected": False,
                "status": "network_error",
                "message": f"Unable to reach Gumroad: {str(e)}",
                "user": None,
                "auto_publish": cls.is_auto_publish_enabled(),
            }

    @classmethod
    def sync_product(cls, product_id: int, auto_publish: Optional[bool] = None) -> Dict[str, Any]:
        """
        Idempotently synchronizes a product with Gumroad.
        If the product already has a remote gumroad_id, updates it; otherwise creates a new product.
        Attempts to enable/publish if auto_publish is requested.
        """
        token = cls.get_access_token()
        if not token:
            return {
                "success": False,
                "status": "not_configured",
                "error": "Cannot sync with Gumroad: GUMROAD_ACCESS_TOKEN is not configured in .env",
            }

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM digital_products WHERE id = ?", (product_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"Product #{product_id} not found."}

        prod = dict(row)
        file_path = prod.get("file_path") or prod.get("pdf_path")
        has_file = bool(file_path and Path(file_path).exists())

        if auto_publish is None:
            auto_publish = cls.is_auto_publish_enabled() or bool(prod.get("auto_publish_gumroad"))

        title = prod.get("title", "Digital Deliverable")
        description = prod.get("description", "")
        price_dollars = float(prod.get("price", 14.99))
        price_cents = max(100, int(round(price_dollars * 100)))
        currency = (prod.get("currency") or "USD").lower()
        slug = prod.get("slug")

        existing_gumroad_id = prod.get("gumroad_id")
        headers = {"Authorization": f"Bearer {token}"}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            if existing_gumroad_id:
                # Update existing product metadata
                url = f"{cls.API_BASE}/products/{existing_gumroad_id}"
                payload = {
                    "name": title,
                    "description": description,
                    "price": price_cents,
                }
                resp = requests.put(url, headers=headers, data=payload, timeout=12)
            else:
                # Create new product draft
                url = f"{cls.API_BASE}/products"
                payload = {
                    "name": title,
                    "description": description,
                    "price": price_cents,
                    "summary": prod.get("value_proposition", "")[:140],
                    "currency": currency,
                    "custom_permalink": slug,
                }
                resp = requests.post(url, headers=headers, data=payload, timeout=12)

            if resp.status_code in (200, 201):
                res_data = resp.json()
                if res_data.get("success"):
                    remote_prod = res_data.get("product", {})
                    remote_id = remote_prod.get("id") or existing_gumroad_id
                    remote_url = remote_prod.get("short_url") or remote_prod.get("url") or f"https://gumroad.com/l/{slug}"
                    edit_url = f"https://gumroad.com/products/{remote_id}/edit" if remote_id else None

                    sync_status = "draft_created"
                    publish_status = "unpublished"
                    existing_att = prod.get("gumroad_attachment_status")
                    attachment_status = existing_att if existing_att == "verified_attached" else "pending_manual_attachment"
                    sync_message = "Draft created on Gumroad — PDF attachment required"
                    payout_required = False

                    # If auto_publish is true, attempt to enable on Gumroad
                    if auto_publish and remote_id:
                        try:
                            en_resp = requests.put(
                                f"{cls.API_BASE}/products/{remote_id}/enable",
                                data={"access_token": token},
                                timeout=10
                            )
                            if en_resp.status_code == 200:
                                en_data = en_resp.json()
                                if en_data.get("success"):
                                    sync_status = "published"
                                    publish_status = "published"
                                    sync_message = "Published live on Gumroad!"
                                else:
                                    msg = en_data.get("message", "")
                                    if "payment method" in msg.lower() or "payout" in msg.lower():
                                        payout_required = True
                                        sync_message = "Draft created on Gumroad — Connect payout method at gumroad.com/settings/payouts to publish."
                                    else:
                                        sync_message = f"Draft created on Gumroad — {msg}"
                        except Exception as e_pub:
                            logger.warning(f"Error during Gumroad enable: {e_pub}")

                    cur.execute("""
                        UPDATE digital_products
                        SET gumroad_id = ?, gumroad_url = ?, gumroad_sync_status = ?,
                            gumroad_publish_status = ?, gumroad_attachment_status = ?,
                            gumroad_edit_url = ?, gumroad_sync_message = ?, gumroad_synced_at = ?, updated_at = ?
                        WHERE id = ?
                    """, (remote_id, remote_url, sync_status, publish_status, attachment_status, edit_url, sync_message, now_str, now_str, product_id))
                    conn.commit()
                    conn.close()

                    return {
                        "success": True,
                        "product_id": product_id,
                        "gumroad_id": remote_id,
                        "gumroad_url": remote_url,
                        "gumroad_edit_url": edit_url,
                        "sync_status": sync_status,
                        "publish_status": publish_status,
                        "attachment_status": attachment_status,
                        "sync_message": sync_message,
                        "pdf_attached": False,
                        "payout_setup_required": payout_required,
                        "payout_settings_url": "https://gumroad.com/settings/payouts" if payout_required else None
                    }
                else:
                    err_msg = res_data.get("message", "Gumroad API returned failure")
                    cur.execute("""
                        UPDATE digital_products
                        SET gumroad_sync_status = 'sync_failed', gumroad_sync_message = ?, updated_at = ?
                        WHERE id = ?
                    """, (err_msg, now_str, product_id))
                    conn.commit()
                    conn.close()
                    return {"success": False, "status": "sync_failed", "error": err_msg}
            else:
                err_text = resp.text[:200]
                cur.execute("""
                    UPDATE digital_products
                    SET gumroad_sync_status = 'sync_failed', gumroad_sync_message = ?, updated_at = ?
                    WHERE id = ?
                """, (f"HTTP {resp.status_code}: {err_text}", now_str, product_id))
                conn.commit()
                conn.close()
                return {"success": False, "status": "sync_failed", "error": f"Gumroad API error ({resp.status_code}): {err_text}"}

        except requests.exceptions.Timeout:
            conn.close()
            return {"success": False, "status": "timeout", "error": "Gumroad API request timed out"}
        except Exception as e:
            conn.close()
            return {"success": False, "status": "error", "error": str(e)}

    @classmethod
    def publish_product(cls, product_id: int) -> Dict[str, Any]:
        """
        Publishes a product on Gumroad using PUT /v2/products/:id/enable.
        Also marks it published locally in MINT.
        """
        token = cls.get_access_token()
        if not token:
            return {"success": False, "error": "Gumroad access token not configured in .env."}

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM digital_products WHERE id = ?", (product_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"Product #{product_id} not found."}

        prod = dict(row)
        remote_id = prod.get("gumroad_id")
        if not remote_id:
            conn.close()
            # First sync metadata to Gumroad
            sync_res = cls.sync_product(product_id, auto_publish=True)
            return sync_res

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            url = f"{cls.API_BASE}/products/{remote_id}/enable"
            resp = requests.put(url, data={"access_token": token}, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    cur.execute("""
                        UPDATE digital_products
                        SET status = 'published', gumroad_sync_status = 'published',
                            gumroad_publish_status = 'published',
                            gumroad_sync_message = 'Published live on Gumroad', updated_at = ?
                        WHERE id = ?
                    """, (now_str, product_id))
                    conn.commit()
                    conn.close()
                    return {
                        "success": True,
                        "status": "published",
                        "publish_status": "published",
                        "message": "Product published live on Gumroad store!",
                        "gumroad_url": prod.get("gumroad_url"),
                        "gumroad_edit_url": f"https://gumroad.com/products/{remote_id}/edit"
                    }
                else:
                    msg = data.get("message", "Unable to publish on Gumroad.")
                    payout_req = "payment method" in msg.lower() or "payout" in msg.lower()
                    cur.execute("""
                        UPDATE digital_products
                        SET status = 'published', gumroad_sync_status = 'draft_created',
                            gumroad_publish_status = 'unpublished',
                            gumroad_sync_message = ?, updated_at = ?
                        WHERE id = ?
                    """, (f"Draft saved on Gumroad ({msg})", now_str, product_id))
                    conn.commit()
                    conn.close()
                    return {
                        "success": False,
                        "status": "draft_created",
                        "publish_status": "unpublished",
                        "published_locally": True,
                        "payout_setup_required": payout_req,
                        "message": msg,
                        "payout_settings_url": "https://gumroad.com/settings/payouts",
                        "gumroad_url": prod.get("gumroad_url"),
                        "gumroad_edit_url": f"https://gumroad.com/products/{remote_id}/edit"
                    }
            else:
                conn.close()
                return {"success": False, "error": f"Gumroad HTTP {resp.status_code}: {resp.text[:150]}"}
        except Exception as e:
            conn.close()
            return {"success": False, "error": str(e)}

    @classmethod
    def mark_attachment_verified(cls, product_id: int, user_confirmed: bool = True) -> Dict[str, Any]:
        """
        Marks that the user has verified attaching the physical PDF deliverable
        in the Gumroad product editor.
        """
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, gumroad_id, gumroad_attachment_status FROM digital_products WHERE id = ?", (product_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return {"success": False, "error": f"Product #{product_id} not found."}

        new_status = "verified_attached" if user_confirmed else "pending_manual_attachment"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            UPDATE digital_products
            SET gumroad_attachment_status = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, now_str, product_id))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "product_id": product_id,
            "gumroad_attachment_status": new_status,
            "message": "Product deliverable attachment verified on Gumroad."
        }
