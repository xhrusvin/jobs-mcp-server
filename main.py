import os
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId
import json
from mcp.server.fastmcp import FastMCP
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

load_dotenv()

# MongoDB connection
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "expresshealth")]
collection = db[os.getenv("MONGO_COLLECTION", "jobs")]

# MCP Server
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    name="ExpressHealth Jobs MCP",
    instructions="You help manage care job assignments at ExpressHealth. "
                 "Use the available tools to list, search, create, and update care jobs."
)



def serialize_doc(doc: dict) -> dict:
    """Convert MongoDB document to JSON-serializable dict."""
    doc = dict(doc)
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, dict):
            doc[key] = serialize_doc(value)
        elif isinstance(value, list):
            doc[key] = [
                serialize_doc(i) if isinstance(i, dict)
                else str(i) if isinstance(i, ObjectId)
                else i
                for i in value
            ]
    return doc


@mcp.tool()
def list_jobs(status: str = None, job_type: str = None, limit: int = 20) -> str:
    query = {"is_active": True}
    if status:
        query["status"] = status
    if job_type:
        query["job_type"] = job_type
    jobs = list(collection.find(query).limit(limit))
    return json.dumps([serialize_doc(j) for j in jobs], indent=2)


@mcp.tool()
def get_job(job_id: str) -> str:
    try:
        job = collection.find_one({"_id": ObjectId(job_id)})
        if not job:
            return json.dumps({"error": f"No job found with id {job_id}"})
        return json.dumps(serialize_doc(job), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def search_jobs(client_name: str = None, location: str = None, date: str = None) -> str:
    query = {"is_active": True}
    if client_name:
        query["client_name"] = {"$regex": client_name, "$options": "i"}
    if location:
        query["location"] = {"$regex": location, "$options": "i"}
    if date:
        try:
            start = datetime.strptime(date, "%Y-%m-%d")
            end = datetime(start.year, start.month, start.day, 23, 59, 59)
            query["scheduled_date"] = {"$gte": start, "$lte": end}
        except ValueError:
            return json.dumps({"error": "Invalid date format. Use YYYY-MM-DD."})
    jobs = list(collection.find(query))
    return json.dumps([serialize_doc(j) for j in jobs], indent=2)


@mcp.tool()
def create_job(title: str, client_name: str, job_type: str, location: str,
               scheduled_date: str, description: str, notes: str = "") -> str:
    try:
        now = datetime.utcnow()
        doc = {
            "title": title, "client_name": client_name, "job_type": job_type,
            "status": "Pending", "location": location,
            "scheduled_date": datetime.strptime(scheduled_date, "%Y-%m-%d"),
            "description": description, "notes": notes,
            "is_active": True, "created_at": now, "updated_at": now,
        }
        result = collection.insert_one(doc)
        return json.dumps({"success": True, "inserted_id": str(result.inserted_id)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def update_job_status(job_id: str, status: str) -> str:
    allowed = {"Pending", "In Progress", "Completed", "Cancelled"}
    if status not in allowed:
        return json.dumps({"error": f"Invalid status. Must be one of: {allowed}"})
    try:
        result = collection.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": status, "updated_at": datetime.utcnow()}},
        )
        if result.matched_count == 0:
            return json.dumps({"error": "Job not found"})
        return json.dumps({"success": True, "modified": result.modified_count})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_todays_jobs() -> str:
    now = datetime.utcnow()
    start = datetime(now.year, now.month, now.day, 0, 0, 0)
    end = datetime(now.year, now.month, now.day, 23, 59, 59)
    jobs = list(collection.find({
        "is_active": True,
        "scheduled_date": {"$gte": start, "$lte": end}
    }))
    return json.dumps([serialize_doc(j) for j in jobs], indent=2)


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=3100,
        forwarded_allow_ips="*",
        proxy_headers=True,
    )