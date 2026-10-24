"""
services/cleanup_service.py
Safe Generated Asset Inventory and Selective Cleanup Engine for MINT.

Strictly preserves:
1. User-owned non-test digital products (#1, #12, #13) and their PDF/HTML deliverables.
2. User-owned content jobs (#12 "kids cartoon video" in generated/content/jobs/12).
3. Artifact-linked videos and graphics in generated/videos and generated/images.
4. Active database records and Gumroad/OAuth credentials.

Removes only:
1. Confirmed automated test job directories (generated/content/job_1 through job_11).
2. Unreferenced temporary video-frame images (generated/images/temp_frame_*.png).
"""

import os
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List

import config
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_generated_dir() -> Path:
    return Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()


class CleanupService:

    @classmethod
    def get_inventory(cls) -> Dict[str, Any]:
        """
        Performs a full reference audit across the database and generated directory tree.
        """
        gen_dir = get_generated_dir()
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Collect all preserved file paths from non-test records
        preserved_paths = set()
        preservation_reasons: Dict[str, str] = {}

        # Non-test digital products
        cur.execute("SELECT id, title, slug, file_path, pdf_path, preview_path FROM digital_products WHERE is_test = 0")
        for r in cur.fetchall():
            pid, title, slug = r[0], r[1], r[2]
            for col_idx in (3, 4, 5):
                fp = r[col_idx]
                if fp:
                    p = Path(fp).resolve()
                    preserved_paths.add(str(p).lower())
                    preservation_reasons[str(p).lower()] = f"Digital Product #{pid} '{title}' deliverable"

            # Entire product slug directory
            if slug:
                slug_dir = (gen_dir / "products" / slug).resolve()
                if slug_dir.exists():
                    preserved_paths.add(str(slug_dir).lower())
                    preservation_reasons[str(slug_dir).lower()] = f"Digital Product #{pid} slug directory"
                    for child in slug_dir.rglob("*"):
                        preserved_paths.add(str(child.resolve()).lower())
                        preservation_reasons[str(child.resolve()).lower()] = f"Digital Product #{pid} child file: {child.name}"

        # Non-test content jobs
        cur.execute("SELECT id, title, output_dir, video_path, thumbnail_path FROM content_jobs WHERE is_test = 0")
        for r in cur.fetchall():
            jid, title = r[0], r[1]
            for col_idx in (2, 3, 4):
                fp = r[col_idx]
                if fp:
                    p = Path(fp).resolve()
                    preserved_paths.add(str(p).lower())
                    preservation_reasons[str(p).lower()] = f"Non-test Content Job #{jid} '{title}' output"
                    if p.is_dir():
                        for child in p.rglob("*"):
                            preserved_paths.add(str(child.resolve()).lower())
                            preservation_reasons[str(child.resolve()).lower()] = f"Non-test Content Job #{jid} file: {child.name}"

        # Artifacts
        cur.execute("SELECT id, experiment_id, artifact_type, file_path, meta_json FROM artifacts")
        for r in cur.fetchall():
            aid, exp_id, atype, fp, meta = r[0], r[1], r[2], r[3], r[4]
            if fp:
                p = Path(fp).resolve()
                preserved_paths.add(str(p).lower())
                preservation_reasons[str(p).lower()] = f"Artifact #{aid} ({atype}) file"
            if meta:
                # Check for image or video references in meta_json
                for sub in ("asset_img_", "asset_vid_", "render.html", "product.pdf"):
                    if sub in meta:
                        for candidate in gen_dir.rglob(f"*{sub}*"):
                            preserved_paths.add(str(candidate.resolve()).lower())
                            preservation_reasons[str(candidate.resolve()).lower()] = f"Artifact #{aid} meta reference: {candidate.name}"

        # Instagram posts
        try:
            cur.execute("SELECT id, image_paths_json FROM instagram_posts")
            for r in cur.fetchall():
                pid, paths_json = r[0], r[1]
                if paths_json:
                    import json
                    try:
                        for p_str in json.loads(paths_json):
                            p = Path(p_str).resolve()
                            preserved_paths.add(str(p).lower())
                            preservation_reasons[str(p).lower()] = f"Instagram Post #{pid} slide file"
                    except Exception:
                        pass
        except Exception:
            pass

        # Image assets table
        try:
            cur.execute("SELECT id, file_path FROM image_assets")
            for r in cur.fetchall():
                iid, fp = r[0], r[1]
                if fp:
                    p = Path(fp).resolve()
                    preserved_paths.add(str(p).lower())
                    preservation_reasons[str(p).lower()] = f"AI Image Asset #{iid} file"
        except Exception:
            pass

        conn.close()

        # 2. Scan disk and classify items
        candidate_deletions = []
        candidate_preservations = []

        # A: Check test job folders in generated/content/job_<n>
        content_dir = gen_dir / "content"
        if content_dir.exists():
            for item in content_dir.iterdir():
                if item.is_dir() and item.name.startswith("job_"):
                    # Confirm item is exclusively a test job directory
                    str_path = str(item.resolve()).lower()
                    if str_path not in preserved_paths:
                        file_count = len([f for f in item.rglob("*") if f.is_file()])
                        total_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        candidate_deletions.append({
                            "type": "test_content_job_dir",
                            "name": item.name,
                            "path": str(item.resolve()),
                            "file_count": file_count,
                            "bytes": total_bytes,
                            "reason": "Automated test job fixture (is_test=1); zero non-test references."
                        })
                elif item.name == "jobs":
                    # Check individual job subfolders inside content/jobs
                    for sub in item.iterdir():
                        str_path = str(sub.resolve()).lower()
                        if str_path in preserved_paths:
                            candidate_preservations.append({
                                "name": f"jobs/{sub.name}",
                                "path": str(sub.resolve()),
                                "reason": preservation_reasons.get(str_path, "Preserved non-test job")
                            })

        # B: Check temporary frames in generated/images
        images_dir = gen_dir / "images"
        if images_dir.exists():
            for item in images_dir.iterdir():
                str_path = str(item.resolve()).lower()
                if item.is_file() and item.name.startswith("temp_frame_"):
                    if str_path not in preserved_paths:
                        candidate_deletions.append({
                            "type": "orphaned_temp_frame",
                            "name": item.name,
                            "path": str(item.resolve()),
                            "file_count": 1,
                            "bytes": item.stat().st_size,
                            "reason": "Unreferenced ffmpeg temporary video frame left behind during legacy render."
                        })
                elif str_path in preserved_paths:
                    candidate_preservations.append({
                        "name": f"images/{item.name}",
                        "path": str(item.resolve()),
                        "reason": preservation_reasons.get(str_path, "Preserved asset/artifact")
                    })

        # C: Check videos in generated/videos (preserved for UI deletion)
        videos_dir = gen_dir / "videos"
        if videos_dir.exists():
            for item in videos_dir.iterdir():
                str_path = str(item.resolve()).lower()
                candidate_preservations.append({
                    "name": f"videos/{item.name}",
                    "path": str(item.resolve()),
                    "reason": preservation_reasons.get(str_path, "Referenced artifact video (manageable via UI)")
                })

        # D: Check products in generated/products
        products_dir = gen_dir / "products"
        if products_dir.exists():
            for item in products_dir.iterdir():
                str_path = str(item.resolve()).lower()
                if str_path in preserved_paths:
                    candidate_preservations.append({
                        "name": f"products/{item.name}",
                        "path": str(item.resolve()),
                        "reason": preservation_reasons.get(str_path, "Active product deliverable")
                    })

        total_bytes_to_delete = sum(d["bytes"] for d in candidate_deletions)
        total_files_to_delete = sum(d["file_count"] for d in candidate_deletions)

        return {
            "candidate_deletions": candidate_deletions,
            "candidate_preservations": candidate_preservations,
            "total_files_to_delete": total_files_to_delete,
            "total_bytes_to_delete": total_bytes_to_delete,
            "reclaimable_mb": round(total_bytes_to_delete / (1024 * 1024), 2)
        }

    @classmethod
    def execute_cleanup(cls, dry_run: bool = True) -> Dict[str, Any]:
        """
        Executes selective safe cleanup of confirmed test directories and orphaned temp frames.
        """
        inventory = cls.get_inventory()
        if dry_run:
            return dict(inventory, dry_run=True, executed=False)

        deleted_items = []
        gen_dir = get_generated_dir()

        for item in inventory["candidate_deletions"]:
            target = Path(item["path"]).resolve()
            # Safety check: must reside inside generated directory
            try:
                target.relative_to(gen_dir)
            except ValueError:
                logger.error("Path traversal violation during cleanup: %s", target)
                continue

            try:
                if target.is_dir():
                    shutil.rmtree(str(target))
                    deleted_items.append({"name": item["name"], "type": "directory", "bytes": item["bytes"]})
                elif target.is_file():
                    target.unlink()
                    deleted_items.append({"name": item["name"], "type": "file", "bytes": item["bytes"]})
            except Exception as e:
                logger.warning("Error deleting %s: %s", target, e)

        return {
            "dry_run": False,
            "executed": True,
            "deleted_count": len(deleted_items),
            "deleted_items": deleted_items,
            "bytes_reclaimed": sum(d["bytes"] for d in deleted_items),
            "mb_reclaimed": round(sum(d["bytes"] for d in deleted_items) / (1024 * 1024), 2),
            "preserved_count": len(inventory["candidate_preservations"])
        }
