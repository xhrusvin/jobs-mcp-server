#!/usr/bin/env python3
"""
jobs_mcp_server.py  –  Fixed version (no $set variable name)
MCP server exposing the healthcare jobs MongoDB collection.
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId
from bson.errors import InvalidId
from mcp.server.fastmcp import FastMCP

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────
MONGO_URI   = os.getenv("MONGO_URI",  "mongodb://localhost:27017")
DB_NAME     = os.getenv("DB_NAME",    "xpress_health")
COLLECTION  = os.getenv("COLLECTION", "jobs")

VALID_STATUSES = {"Pending", "In Progress", "Completed", "On Hold", "Cancelled"}

# ── MongoDB ───────────────────────────────────────────────────────────────
_client = None
_col    = None

def get_col():
    global _client, _col
    if _col is not None:
        return _col
    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    _client.admin.command("ping")
    _col = _client[DB_NAME][COLLECTION]
    print(f"[MCP] Connected to {DB_NAME}.{COLLECTION}", flush=True)
    return _col

# ── Helpers ───────────────────────────────────────────────────────────────
def serialize(job: dict) -> dict:
    out = dict(job)
    out["_id"]       = str(out.get("_id", ""))
    out["client_id"] = str(out["client_id"]) if out.get("client_id") else None
    for field in ("scheduled_date", "created_at", "updated_at"):
        val = out.get(field)
        if isinstance(val, datetime):
            out[field] = val.date().isoformat() if field == "scheduled_date" else val.isoformat()
        else:
            out[field] = None
    return out

def ok(data) -> str:
    return json.dumps(data, indent=2, default=str)

def err(msg: str) -> str:
    return json.dumps({"error": msg})

def parse_oid(raw: str) -> ObjectId:
    try:
        return ObjectId(raw)
    except (InvalidId, TypeError):
        raise ValueError(f"Invalid ObjectId: {raw!r}")

def parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {raw!r} — use YYYY-MM-DD")

# ── MCP server ────────────────────────────────────────────────────────────
mcp = FastMCP("jobs-mcp-server")


@mcp.tool()
def list_jobs(
    status:      Optional[str]  = None,
    job_type:    Optional[str]  = None,
    client_name: Optional[str]  = None,
    is_active:   Optional[bool] = None,
    page:        int = 1,
    per_page:    int = 20,
) -> str:
    """
    List healthcare jobs with optional filters and pagination.

    Args:
        status:      Pending | In Progress | Completed | On Hold | Cancelled
        job_type:    Partial match e.g. 'Personal Care'
        client_name: Partial match on client name
        is_active:   True = active only, False = inactive only
        page:        Page number (default 1)
        per_page:    Results per page (default 20, max 100)
    """
    col   = get_col()
    query = {}
    if status:                query["status"]      = status
    if job_type:              query["job_type"]    = {"$regex": job_type,    "$options": "i"}
    if client_name:           query["client_name"] = {"$regex": client_name, "$options": "i"}
    if is_active is not None: query["is_active"]   = is_active

    per_page = min(max(per_page, 1), 100)
    skip     = (page - 1) * per_page
    total    = col.count_documents(query)
    jobs     = list(col.find(query).sort("scheduled_date", ASCENDING).skip(skip).limit(per_page))

    return ok({
        "total": total, "page": page, "per_page": per_page,
        "pages": -(-total // per_page),
        "jobs":  [serialize(j) for j in jobs],
    })


@mcp.tool()
def get_job(job_id: str) -> str:
    """
    Get a single job by its MongoDB _id.

    Args:
        job_id: MongoDB ObjectId string
    """
    col = get_col()
    try:
        oid = parse_oid(job_id)
    except ValueError as e:
        return err(str(e))
    job = col.find_one({"_id": oid})
    if not job:
        return err(f"Job not found: {job_id}")
    return ok(serialize(job))


@mcp.tool()
def search_jobs(query: str, page: int = 1, per_page: int = 20) -> str:
    """
    Full-text search across title, client name, location, description, notes, job type.

    Args:
        query:    Search term
        page:     Page number
        per_page: Results per page (max 100)
    """
    col   = get_col()
    regex = {"$regex": query, "$options": "i"}
    filt  = {"$or": [
        {"title": regex}, {"client_name": regex}, {"location": regex},
        {"description": regex}, {"job_type": regex}, {"notes": regex},
    ]}
    per_page = min(max(per_page, 1), 100)
    skip     = (page - 1) * per_page
    total    = col.count_documents(filt)
    jobs     = list(col.find(filt).sort("scheduled_date", ASCENDING).skip(skip).limit(per_page))
    return ok({"query": query, "total": total, "page": page, "per_page": per_page,
               "jobs": [serialize(j) for j in jobs]})


@mcp.tool()
def create_job(
    title:          str,
    client_name:    str,
    client_id:      Optional[str] = None,
    job_type:       Optional[str] = None,
    status:         str           = "Pending",
    location:       Optional[str] = None,
    scheduled_date: Optional[str] = None,
    description:    Optional[str] = None,
    notes:          Optional[str] = None,
    is_active:      bool          = True,
) -> str:
    """
    Create a new job.

    Args:
        title:          Job title — required
        client_name:    Client full name — required
        client_id:      Client MongoDB ObjectId (optional)
        job_type:       e.g. Personal Care, Wound Care, Physiotherapy
        status:         Pending | In Progress | Completed | On Hold | Cancelled
        location:       Address or county
        scheduled_date: YYYY-MM-DD
        description:    Summary of work required
        notes:          Carer notes or preferences
        is_active:      True (default)
    """
    col = get_col()
    if not title.strip():       return err("title is required")
    if not client_name.strip(): return err("client_name is required")
    if status not in VALID_STATUSES:
        return err(f"Invalid status. Choose from: {', '.join(VALID_STATUSES)}")

    try:
        sched = parse_date(scheduled_date)
    except ValueError as e:
        return err(str(e))

    try:
        cid = parse_oid(client_id) if client_id else None
    except ValueError as e:
        return err(str(e))

    now = datetime.now(tz=timezone.utc)
    doc = {
        "title":          title.strip(),
        "client_name":    client_name.strip(),
        "client_id":      cid,
        "job_type":       job_type.strip()    if job_type    else None,
        "status":         status,
        "location":       location.strip()    if location    else None,
        "scheduled_date": sched,
        "description":    description.strip() if description else None,
        "notes":          notes.strip()       if notes       else None,
        "is_active":      is_active,
        "created_at":     now,
        "updated_at":     now,
    }
    result     = col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return ok({"success": True, "inserted_id": str(result.inserted_id), "job": serialize(doc)})


@mcp.tool()
def update_job(
    job_id:         str,
    title:          Optional[str]  = None,
    client_name:    Optional[str]  = None,
    job_type:       Optional[str]  = None,
    status:         Optional[str]  = None,
    location:       Optional[str]  = None,
    scheduled_date: Optional[str]  = None,
    description:    Optional[str]  = None,
    notes:          Optional[str]  = None,
    is_active:      Optional[bool] = None,
) -> str:
    """
    Update one or more fields on an existing job. Only provided fields are changed.

    Args:
        job_id: MongoDB ObjectId — required
        All other args optional — only supplied ones are updated.
    """
    col = get_col()
    try:
        oid = parse_oid(job_id)
    except ValueError as e:
        return err(str(e))

    # Build the update payload as a plain Python dict.
    # "$set" is a MongoDB operator used as a STRING KEY — NOT a variable name.
    update_fields = {"updated_at": datetime.now(tz=timezone.utc)}

    if title          is not None: update_fields["title"]          = title.strip()
    if client_name    is not None: update_fields["client_name"]    = client_name.strip()
    if job_type       is not None: update_fields["job_type"]       = job_type.strip()
    if location       is not None: update_fields["location"]       = location.strip()
    if description    is not None: update_fields["description"]    = description.strip()
    if notes          is not None: update_fields["notes"]          = notes.strip()
    if is_active      is not None: update_fields["is_active"]      = is_active

    if status is not None:
        if status not in VALID_STATUSES:
            return err(f"Invalid status. Choose from: {', '.join(VALID_STATUSES)}")
        update_fields["status"] = status

    if scheduled_date is not None:
        try:
            update_fields["scheduled_date"] = parse_date(scheduled_date)
        except ValueError as e:
            return err(str(e))

    updated = col.find_one_and_update(
        {"_id": oid},
        {"$set": update_fields},   # "$set" as a string key — perfectly valid Python
        return_document=True,
    )

    if not updated:
        return err(f"Job not found: {job_id}")

    return ok({"success": True, "job": serialize(updated)})


@mcp.tool()
def delete_job(job_id: str, soft: bool = True) -> str:
    """
    Delete a job.

    Args:
        job_id: MongoDB ObjectId
        soft:   True (default) = soft-delete (is_active=False). False = permanent.
    """
    col = get_col()
    try:
        oid = parse_oid(job_id)
    except ValueError as e:
        return err(str(e))

    if soft:
        col.update_one(
            {"_id": oid},
            {"$set": {"is_active": False, "updated_at": datetime.now(tz=timezone.utc)}}
        )
        return ok({"success": True, "action": "soft_deleted", "job_id": job_id})
    else:
        result = col.delete_one({"_id": oid})
        if result.deleted_count == 0:
            return err(f"Job not found: {job_id}")
        return ok({"success": True, "action": "hard_deleted", "job_id": job_id})


@mcp.tool()
def jobs_summary() -> str:
    """
    Dashboard counts: total jobs, active/inactive, breakdown by status and job type.
    """
    col = get_col()
    by_status = list(col.aggregate([
        {"$group": {"_id": "$status",   "count": {"$sum": 1}}},
        {"$sort":  {"count": DESCENDING}},
    ]))
    by_type = list(col.aggregate([
        {"$group": {"_id": "$job_type", "count": {"$sum": 1}}},
        {"$sort":  {"count": DESCENDING}},
    ]))
    total  = col.count_documents({})
    active = col.count_documents({"is_active": True})
    return ok({
        "total_jobs":    total,
        "active_jobs":   active,
        "inactive_jobs": total - active,
        "by_status":   {(s["_id"] or "Unknown"): s["count"] for s in by_status},
        "by_job_type": {(t["_id"] or "Unknown"): t["count"] for t in by_type},
    })


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 3100))
    print(f"[MCP] Starting SSE server on http://0.0.0.0:{port}/sse", flush=True)

    # Works across all FastMCP versions
    uvicorn.run(
        "jobs_mcp_server:mcp.app",
        host="0.0.0.0",
        port=port,
        forwarded_allow_ips="*",
    )