import os
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId
import json
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import uvicorn

load_dotenv()

# MongoDB connection
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "expresshealth")]
collection = db[os.getenv("MONGO_COLLECTION", "jobs")]

# MCP Server
mcp = FastMCP(
    name="ExpressHealth Jobs MCP",
    instructions="You help manage care job assignments at ExpressHealth. "
                 "Use the available tools to list, search, and fetch care jobs.",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
    stateless_http=True,
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


@mcp.tool(description="List care jobs filtered by status and/or job type. Use this for any query about jobs, assignments or tasks.")
def list_jobs(status: str = None, job_type: str = None, limit: int = 20) -> str:
    query = {"is_active": True}
    if status:
        query["status"] = status
    if job_type:
        query["job_type"] = job_type
    jobs = list(collection.find(query).limit(limit))
    return json.dumps([serialize_doc(j) for j in jobs], indent=2)


@mcp.tool(description="Fetch a specific care job by its ID.")
def fetch(job_id: str) -> str:
    try:
        job = collection.find_one({"_id": ObjectId(job_id)})
        if not job:
            return json.dumps({"error": f"No job found with id {job_id}"})
        return json.dumps(serialize_doc(job), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool(description="Search care jobs by a keyword across client name, location, title, description, and notes.")
def search(keyword: str = None) -> str:
    query = {"is_active": True}
    if keyword:
        query["$or"] = [
            {"client_name": {"$regex": keyword, "$options": "i"}},
            {"location": {"$regex": keyword, "$options": "i"}},
            {"title": {"$regex": keyword, "$options": "i"}},
            {"description": {"$regex": keyword, "$options": "i"}},
            {"notes": {"$regex": keyword, "$options": "i"}},
        ]
    jobs = list(collection.find(query))
    return json.dumps([serialize_doc(j) for j in jobs], indent=2)


@mcp.tool(description="Simple chat tool. Send 'T' to get 'M', send 'U' to get 'N'.")
def chat(message: str) -> str:
    msg = message.strip().upper()
    if msg == "T":
        return "M"
    elif msg == "U":
        return "N"
    else:
        return f"Unknown input '{message}'. Send 'T' (returns M) or 'U' (returns N)."


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=3100,
        forwarded_allow_ips="*",
        proxy_headers=True,
    )