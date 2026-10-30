"""
services/chroma_service.py
ChromaDB Activity & Memory Service for MINT
Stores and queries all key system activities (clips generated, products created,
content jobs, and milestones) with vector search and fast retrieval.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from database import get_db_connection

logger = logging.getLogger(__name__)

# Persistent Chroma directory inside data folder
CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma")
os.makedirs(CHROMA_DIR, exist_ok=True)

_client = None

def get_chroma_client():
    global _client
    if _client is None:
        try:
            import chromadb
            _client = chromadb.PersistentClient(path=CHROMA_DIR)
        except Exception as e:
            logger.warning(f"Could not initialize Chroma PersistentClient: {e}")
            import chromadb
            _client = chromadb.Client()
    return _client

def get_activity_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="mint_important_activities",
        metadata={"description": "All important activities, generated clips, products, and milestones"}
    )

def log_important_activity(
    activity_id: str,
    title: str,
    category: str,
    details: str,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Log an important activity directly into ChromaDB.
    """
    try:
        col = get_activity_collection()
        meta = metadata or {}
        meta["category"] = category
        meta["title"] = title
        meta["timestamp"] = meta.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        doc_text = f"[{category.upper()}] {title}: {details}"
        col.upsert(
            ids=[str(activity_id)],
            documents=[doc_text],
            metadatas=[{k: str(v) if not isinstance(v, (int, float, bool)) else v for k, v in meta.items()}]
        )
        return True
    except Exception as e:
        logger.error(f"Failed to log activity to ChromaDB: {e}")
        return False

def sync_all_database_activities():
    """
    Scans the SQLite database and syncs all important historical activities:
    - YouTube Clips created & published
    - Digital Products authored & exported
    - Content Studio jobs rendered
    - Meaningful logged activities
    """
    try:
        col = get_activity_collection()
        conn = get_db_connection()
        cur = conn.cursor()

        ids_to_add = []
        docs_to_add = []
        metas_to_add = []

        # 1. YouTube Clips
        cur.execute("SELECT id, clip_title, clip_description, status, duration_sec, output_path, youtube_video_url, created_at, published_at FROM youtube_clips")
        for row in cur.fetchall():
            c = dict(row)
            cid = f"clip_{c['id']}"
            title = c.get('clip_title') or f"Clip #{c['id']}"
            desc = c.get('clip_description') or ''
            st = c.get('status') or 'ready'
            dur = c.get('duration_sec') or 0
            yt_url = c.get('youtube_video_url') or ''
            created = c.get('created_at') or ''
            
            doc = f"[YOUTUBE CLIP] Title: {title}. Status: {st}. Duration: {dur}s. Description: {desc}. Link: {yt_url}"
            ids_to_add.append(cid)
            docs_to_add.append(doc)
            metas_to_add.append({
                "category": "youtube_clip",
                "title": title[:100],
                "status": st,
                "duration_sec": float(dur),
                "url": yt_url,
                "timestamp": created
            })

        # 2. Digital Products
        cur.execute("SELECT id, title, slug, price, product_type, audience, status, file_path, created_at FROM digital_products")
        for row in cur.fetchall():
            p = dict(row)
            pid = f"prod_{p['id']}"
            title = p.get('title') or f"Product #{p['id']}"
            price = p.get('price') or 0.0
            ptype = p.get('product_type') or 'guide'
            aud = p.get('audience') or 'general'
            created = p.get('created_at') or ''

            doc = f"[DIGITAL PRODUCT] Title: {title}. Price: ${price:.2f}. Type: {ptype}. Target Audience: {aud}. Status: {p.get('status')}"
            ids_to_add.append(pid)
            docs_to_add.append(doc)
            metas_to_add.append({
                "category": "digital_product",
                "title": title[:100],
                "price": float(price),
                "product_type": ptype,
                "timestamp": created
            })

        # 3. Content Studio Jobs
        cur.execute("SELECT id, title, status, progress_pct, output_dir, video_path, created_at FROM content_jobs")
        for row in cur.fetchall():
            j = dict(row)
            jid = f"job_{j['id']}"
            title = j.get('title') or f"Studio Job #{j['id']}"
            st = j.get('status') or 'completed'
            created = j.get('created_at') or ''

            doc = f"[CONTENT STUDIO] Job: {title}. Status: {st}. Progress: {j.get('progress_pct', 100)}%."
            ids_to_add.append(jid)
            docs_to_add.append(doc)
            metas_to_add.append({
                "category": "content_job",
                "title": title[:100],
                "status": st,
                "timestamp": created
            })

        # 4. Filtered Important Activities from feed
        cur.execute("SELECT id, agent_name, message, severity, timestamp FROM activity_feed WHERE message LIKE '%publish%' OR message LIKE '%render%' OR message LIKE '%generat%' OR message LIKE '%export%' OR severity IN ('warning', 'error') ORDER BY id DESC LIMIT 50")
        for row in cur.fetchall():
            a = dict(row)
            aid = f"feed_{a['id']}"
            agent = a.get('agent_name') or 'System'
            msg = a.get('message') or ''
            ts = a.get('timestamp') or ''

            doc = f"[ACTIVITY LOG] {agent}: {msg}"
            ids_to_add.append(aid)
            docs_to_add.append(doc)
            metas_to_add.append({
                "category": "system_event",
                "title": f"{agent} Event",
                "timestamp": ts
            })

        conn.close()

        if ids_to_add:
            # Batch upsert into Chroma
            batch_size = 50
            for i in range(0, len(ids_to_add), batch_size):
                col.upsert(
                    ids=ids_to_add[i:i+batch_size],
                    documents=docs_to_add[i:i+batch_size],
                    metadatas=metas_to_add[i:i+batch_size]
                )
        return len(ids_to_add)
    except Exception as e:
        logger.error(f"Failed to sync SQLite activities to ChromaDB: {e}")
        return 0

def query_activities(query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """
    Performs semantic vector search across all important activities in ChromaDB.
    """
    try:
        col = get_activity_collection()
        if col.count() == 0:
            sync_all_database_activities()

        res = col.query(
            query_texts=[query],
            n_results=min(n_results, max(1, col.count()))
        )

        results = []
        if res and res.get("documents") and res["documents"][0]:
            docs = res["documents"][0]
            metas = res.get("metadatas", [[]])[0]
            ids = res.get("ids", [[]])[0]
            for i in range(len(docs)):
                results.append({
                    "id": ids[i] if i < len(ids) else "",
                    "document": docs[i],
                    "metadata": metas[i] if i < len(metas) else {}
                })
        return results
    except Exception as e:
        logger.error(f"Error querying ChromaDB: {e}")
        return []

def get_recent_activities(limit: int = 15) -> List[Dict[str, Any]]:
    """
    Fetches the most recent important activities from ChromaDB.
    """
    try:
        col = get_activity_collection()
        if col.count() == 0:
            sync_all_database_activities()

        data = col.get()
        if not data or not data.get("documents"):
            return []

        items = []
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        ids = data.get("ids", [])

        for i in range(len(docs)):
            m = metas[i] if i < len(metas) and metas[i] else {}
            items.append({
                "id": ids[i],
                "document": docs[i],
                "title": m.get("title") or "Activity",
                "category": m.get("category") or "general",
                "timestamp": m.get("timestamp") or "",
                "status": m.get("status") or "completed",
                "url": m.get("url") or ""
            })

        # Sort by timestamp descending
        items.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
        return items[:limit]
    except Exception as e:
        logger.error(f"Error fetching recent activities: {e}")
        return []
