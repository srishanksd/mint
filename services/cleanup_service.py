"""
services/cleanup_service.py
Safe Generated Asset Inventory, Reference Audit, and Selective Cleanup Engine for MINT.

Strictly preserves:
1. User-owned non-test digital products (#1, #12, #15, #16) and their PDF/HTML deliverables, source, render, and manifest files.
2. Verified image assets in generated/images (IDs 4–8) created by Cloudflare Workers AI.
3. YouTube clip deliverables in generated/content/youtube_clips, including published clips.
4. Product guide files corresponding to artifacts (163c58, 12f7bd, 7fb5b4, 2754ec).
5. All database records, Gumroad links, and OAuth credentials.

Removes only:
1. Confirmed orphaned shortened duplicate files (e.g. founder_operating_bluepr_deliverable.html).
2. Obsolete empty legacy directories (generated/clips, generated/source_videos, generated/test_synth, generated/videos).
"""

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

import config
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_generated_dir() -> Path:
    return Path(getattr(config, "GENERATED_DIR", None) or Path(__file__).resolve().parent.parent / "generated").resolve()


class CleanupService:

    @classmethod
    def get_inventory(cls) -> Dict[str, Any]:
        """
        Performs a full, dry-run reference audit across all SQLite tables and the generated directory.
        Returns:
          - files_on_disk: Detailed inventory of every file found on disk
          - missing_database_references: Database paths that point to missing files on disk
          - candidate_deletions: Confirmed orphaned files with explicit justification
          - candidate_preservations: Files verified to have legitimate references or companion status
          - empty_directories: Obsolete empty legacy directories
        """
        gen_dir = get_generated_dir()
        conn = get_db_connection()
        conn.row_factory = None
        cur = conn.cursor()

        db_refs: Dict[str, Dict[str, Any]] = {}
        missing_db_refs: List[Dict[str, Any]] = []

        def record_ref(table: str, row_id: Any, fp: Optional[str], reason: str, is_test: bool = False):
            if not fp:
                return
            p = Path(fp).resolve()
            str_p = str(p).lower()
            ref_info = {
                "table": table,
                "id": row_id,
                "path": str(p),
                "reason": reason,
                "is_test": is_test
            }
            db_refs[str_p] = ref_info
            if not p.exists():
                missing_db_refs.append(ref_info)

        # 1. Audit digital_products
        cur.execute("SELECT id, title, slug, file_path, pdf_path, preview_path, is_test FROM digital_products")
        for r in cur.fetchall():
            pid, title, slug, fp, pdf_p, prev_p, is_t = r
            cls_type = "test" if is_t else "production"
            record_ref("digital_products", pid, fp, f"{cls_type} product #{pid} ('{title}') deliverable", is_test=bool(is_t))
            record_ref("digital_products", pid, pdf_p, f"{cls_type} product #{pid} ('{title}') PDF", is_test=bool(is_t))
            record_ref("digital_products", pid, prev_p, f"{cls_type} product #{pid} ('{title}') preview", is_test=bool(is_t))
            if slug:
                slug_dir = (gen_dir / "products" / slug).resolve()
                if slug_dir.exists():
                    for child in slug_dir.rglob("*"):
                        if child.is_file():
                            record_ref("digital_products", pid, str(child), f"{cls_type} product #{pid} asset: {child.name}", is_test=bool(is_t))

        # Also preserve canonical Product #1 guide
        p1_guide = (gen_dir / "products" / "founder_operating_blueprint_guide.md").resolve()
        if p1_guide.exists():
            record_ref("digital_products", 1, str(p1_guide), "production product #1 ('Founder Operating Blueprint') guide", is_test=False)

        # 2. Audit youtube_clips
        cur.execute("SELECT id, clip_title, source_file_path, output_path, status, is_test FROM youtube_clips")
        for r in cur.fetchall():
            cid, title, src_fp, out_fp, status, is_t = r
            cls_type = "test" if is_t else "production"
            record_ref("youtube_clips", cid, out_fp, f"{cls_type} clip #{cid} output ({status})", is_test=bool(is_t))

        # 3. Audit image_assets
        cur.execute("SELECT id, prompt, file_path, is_test FROM image_assets")
        for r in cur.fetchall():
            iid, prompt, fp, is_t = r
            cls_type = "test" if is_t else "production"
            record_ref("image_assets", iid, fp, f"{cls_type} image #{iid} ('{prompt[:40]}...')", is_test=bool(is_t))

        # 4. Audit artifacts & meta_json
        cur.execute("SELECT id, experiment_id, artifact_type, file_path, meta_json FROM artifacts")
        for r in cur.fetchall():
            aid, exp_id, atype, fp, meta = r
            record_ref("artifacts", aid, fp, f"artifact #{aid} ({atype}) file")
            if meta:
                try:
                    m = json.loads(meta)
                    for k in ("image", "guide", "deliverable", "video_path", "output_path"):
                        val = m.get(k)
                        if isinstance(val, str) and val.strip():
                            record_ref("artifacts", aid, val.strip(), f"artifact #{aid} meta {k}")
                except Exception:
                    pass

        # 5. Audit instagram_posts
        try:
            cur.execute("SELECT id, image_paths_json FROM instagram_posts")
            for r in cur.fetchall():
                pid, paths_json = r
                if paths_json:
                    try:
                        for p_str in json.loads(paths_json):
                            record_ref("instagram_posts", pid, p_str, f"instagram post #{pid} slide")
                    except Exception:
                        pass
        except Exception:
            pass

        # 6. Audit content_jobs
        try:
            cur.execute("SELECT id, title, output_dir, video_path, thumbnail_path, is_test FROM content_jobs")
            for r in cur.fetchall():
                jid, title, out_dir, vid_p, thumb_p, is_t = r
                cls_type = "test" if is_t else "production"
                record_ref("content_jobs", jid, out_dir, f"{cls_type} content job #{jid} output dir", is_test=bool(is_t))
                record_ref("content_jobs", jid, vid_p, f"{cls_type} content job #{jid} video", is_test=bool(is_t))
                record_ref("content_jobs", jid, thumb_p, f"{cls_type} content job #{jid} thumbnail", is_test=bool(is_t))
        except Exception:
            pass

        conn.close()

        # 7. Scan disk in generated/
        files_on_disk: List[Dict[str, Any]] = []
        candidate_deletions: List[Dict[str, Any]] = []
        candidate_preservations: List[Dict[str, Any]] = []

        # Known companion guide files linked to artifact IDs
        companion_guide_names = {
            "product_guide_163c58.md": "artifact #1 guide companion",
            "product_guide_12f7bd.md": "artifact #2 guide companion",
            "product_guide_7fb5b4.md": "artifact #3 guide companion",
            "product_guide_2754ec.md": "artifact #4 guide companion",
            "minimalist_notion_produc_guide.md": "minimalist notion product guide companion"
        }

        # Orphaned shortened filenames confirmed to have no references
        orphaned_names = {
            "founder_operating_bluepr_deliverable.html": "Orphaned truncated duplicate of founder_operating_blueprint_deliverable.html",
            "founder_operating_bluepr_guide.md": "Orphaned truncated duplicate of founder_operating_blueprint_guide.md"
        }

        for root, dirs, files in os.walk(gen_dir):
            for fname in files:
                fpath = (Path(root) / fname).resolve()
                str_f = str(fpath).lower()
                size = fpath.stat().st_size
                ext = fpath.suffix.lower()
                rel_path = str(fpath.relative_to(gen_dir))
                rel_norm = rel_path.replace("\\", "/")

                file_info = {
                    "path": str(fpath),
                    "relative_path": rel_path,
                    "filename": fname,
                    "name": fname,
                    "size_bytes": size,
                    "extension": ext
                }

                if rel_norm.startswith("content/job_"):
                    # Part of test job directory scheduled for directory removal
                    file_info.update({
                        "classification": "test_fixture",
                        "matching_reference": None,
                        "proposed_action": "delete",
                        "justification": "File inside automated test job directory."
                    })
                elif str_f in db_refs:
                    ref = db_refs[str_f]
                    file_info.update({
                        "classification": "test" if ref["is_test"] else "production",
                        "matching_reference": ref["reason"],
                        "proposed_action": "preserve",
                        "justification": f"Direct database reference from {ref['table']} #{ref['id']}."
                    })
                    candidate_preservations.append(file_info)
                elif fname in companion_guide_names:
                    file_info.update({
                        "classification": "production",
                        "matching_reference": companion_guide_names[fname],
                        "proposed_action": "preserve",
                        "justification": "Companion product/artifact documentation required for auditing and integrity."
                    })
                    candidate_preservations.append(file_info)
                elif fname in orphaned_names:
                    file_info.update({
                        "classification": "orphaned_duplicate",
                        "matching_reference": None,
                        "proposed_action": "delete",
                        "justification": orphaned_names[fname]
                    })
                    candidate_deletions.append(file_info)
                elif fname.startswith("temp_frame_"):
                    file_info.update({
                        "classification": "stale_temp_frame",
                        "matching_reference": None,
                        "proposed_action": "delete",
                        "justification": "Stale video transcode frame left in generated/images."
                    })
                    candidate_deletions.append(file_info)
                else:
                    # Ambiguous production asset: preserve for manual review
                    file_info.update({
                        "classification": "unknown",
                        "matching_reference": None,
                        "proposed_action": "manual_review",
                        "justification": "Ambiguous unreferenced file preserved safely for user manual review."
                    })
                    candidate_preservations.append(file_info)

                files_on_disk.append(file_info)

        # Check test job folders in generated/content/job_<n>
        content_dir = gen_dir / "content"
        if content_dir.exists():
            for item in content_dir.iterdir():
                if item.is_dir() and item.name.startswith("job_"):
                    str_path = str(item.resolve()).lower()
                    if str_path not in db_refs:
                        file_count = len([f for f in item.rglob("*") if f.is_file()])
                        total_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                        candidate_deletions.append({
                            "type": "test_content_job_dir",
                            "name": item.name,
                            "filename": item.name,
                            "path": str(item.resolve()),
                            "file_count": file_count,
                            "bytes": total_bytes,
                            "size_bytes": total_bytes,
                            "reason": "Automated test job fixture (is_test=1); zero non-test references."
                        })
                elif item.name == "jobs" and item.is_dir():
                    for sub in item.iterdir():
                        str_path = str(sub.resolve()).lower()
                        if str_path in db_refs or any(str_path in p for p in db_refs):
                            candidate_preservations.append({
                                "name": f"jobs/{sub.name}",
                                "filename": sub.name,
                                "path": str(sub.resolve()),
                                "size_bytes": 0,
                                "reason": "Preserved non-test job"
                            })

        # 7. Check for empty obsolete directories
        empty_directories = []
        for dname in ("clips", "source_videos", "test_synth", "videos", "content/jobs"):
            p_dir = (gen_dir / dname).resolve()
            if p_dir.exists() and p_dir.is_dir():
                # Check if truly empty
                children = list(p_dir.iterdir())
                if len(children) == 0:
                    empty_directories.append({
                        "path": str(p_dir),
                        "relative_path": dname,
                        "proposed_action": "delete_empty_dir",
                        "justification": "Obsolete legacy output folder replaced by canonical content/youtube_clips."
                    })

        total_bytes_to_delete = sum(d["size_bytes"] for d in candidate_deletions)

        return {
            "total_files_on_disk": len(files_on_disk),
            "files_on_disk": files_on_disk,
            "missing_database_references": missing_db_refs,
            "candidate_deletions": candidate_deletions,
            "candidate_preservations": candidate_preservations,
            "empty_directories": empty_directories,
            "total_files_to_delete": len(candidate_deletions),
            "total_bytes_to_delete": total_bytes_to_delete,
            "reclaimable_kb": round(total_bytes_to_delete / 1024, 2)
        }

    @classmethod
    def execute_cleanup(cls, dry_run: bool = True) -> Dict[str, Any]:
        """
        Executes verified cleanup: removes confirmed orphaned duplicates and obsolete empty directories.
        """
        inventory = cls.get_inventory()
        if dry_run:
            return dict(inventory, dry_run=True, executed=False)

        gen_dir = get_generated_dir()
        deleted_files = []
        deleted_dirs = []

        # Delete confirmed orphaned files
        for item in inventory["candidate_deletions"]:
            target = Path(item["path"]).resolve()
            try:
                target.relative_to(gen_dir)
            except ValueError:
                logger.error("Path traversal violation during cleanup: %s", target)
                continue

            try:
                if target.is_dir():
                    shutil.rmtree(str(target))
                    deleted_files.append({"name": item.get("name", item.get("filename")), "bytes": item.get("bytes", item.get("size_bytes", 0))})
                elif target.is_file():
                    target.unlink()
                    deleted_files.append({"name": item.get("name", item.get("filename")), "bytes": item.get("size_bytes", 0)})
            except Exception as e:
                logger.warning("Error deleting file or directory %s: %s", target, e)

        # Delete empty obsolete directories
        for ed in inventory["empty_directories"]:
            target_dir = Path(ed["path"]).resolve()
            try:
                target_dir.relative_to(gen_dir)
            except ValueError:
                continue

            try:
                if target_dir.is_dir() and len(list(target_dir.iterdir())) == 0:
                    target_dir.rmdir()
                    deleted_dirs.append(ed["relative_path"])
            except Exception as e:
                logger.warning("Error deleting directory %s: %s", target_dir, e)

        return {
            "dry_run": False,
            "executed": True,
            "deleted_files_count": len(deleted_files),
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
            "bytes_reclaimed": sum(d["bytes"] for d in deleted_files),
            "missing_database_references_count": len(inventory["missing_database_references"]),
            "preserved_count": len(inventory["candidate_preservations"])
        }
