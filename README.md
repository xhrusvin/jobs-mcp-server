# jobs-mcp-server

MCP server that exposes your MongoDB **healthcare jobs collection** to any MCP-compatible client — ChatGPT (via the OpenAI MCP connector), Claude Desktop, or any other MCP host.

---

## Tools available

| Tool | What it does |
|---|---|
| `list_jobs` | Paginated list with filters (status, job_type, client_name, is_active) |
| `get_job` | Fetch a single job by `_id` |
| `search_jobs` | Full-text search across title, client, location, description, notes |
| `create_job` | Insert a new job |
| `update_job` | Patch any fields on an existing job |
| `delete_job` | Soft-delete (is_active=false) or hard-delete |
| `jobs_summary` | Dashboard counts by status and job type |

---

## Setup

### 1. Install dependencies

```bash
cd jobs-mcp-server
npm install
```

### 2. Configure environment

Create a `.env` file **or** export the variables before running:

```bash
export MONGO_URI="mongodb://localhost:27017"   # your MongoDB connection string
export DB_NAME="xpress_health"                 # your database name
export COLLECTION="jobs"                       # collection name (default: jobs)
```

For MongoDB Atlas:
```bash
export MONGO_URI="mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority"
```

### 3. Run the server

```bash
node server.js
```

The server communicates over **stdio** (standard MCP transport).

---

## Connect to ChatGPT

ChatGPT supports MCP servers via the **OpenAI MCP remote connector**.  
Since ChatGPT requires an **HTTP/SSE endpoint** (not raw stdio), you need to wrap the server with a small HTTP bridge.

### Step 1 – Install the SSE bridge

```bash
npm install -g @modelcontextprotocol/server-stdio-to-sse
# or use npx without installing globally
```

### Step 2 – Run the bridge

```bash
npx @modelcontextprotocol/server-stdio-to-sse \
  --port 3100 \
  -- node /absolute/path/to/jobs-mcp-server/server.js
```

This starts an SSE HTTP server on `http://localhost:3100`.

### Step 3 – Expose it publicly (for ChatGPT to reach it)

ChatGPT needs a public HTTPS URL. Use **ngrok** or any tunnel:

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 3100
# → gives you: https://abc123.ngrok-free.app
```

### Step 4 – Add to ChatGPT

1. Go to **ChatGPT → Settings → Beta Features → MCP Servers** (or the Connectors panel)
2. Click **Add Server**
3. Enter the URL: `https://abc123.ngrok-free.app/sse`
4. Give it a name: `Healthcare Jobs`
5. Save — ChatGPT will auto-discover the 7 tools

Now you can ask ChatGPT:
- *"List all pending jobs"*
- *"Search for wound care jobs in Cork"*
- *"Create a new personal care job for Mary Delaney"*
- *"Give me a summary of all jobs by status"*

---

## Connect to Claude Desktop

Add this to your `claude_desktop_config.json`:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "jobs": {
      "command": "node",
      "args": ["/absolute/path/to/jobs-mcp-server/server.js"],
      "env": {
        "MONGO_URI": "mongodb://localhost:27017",
        "DB_NAME":   "xpress_health",
        "COLLECTION": "jobs"
      }
    }
  }
}
```

Restart Claude Desktop — the jobs tools will appear automatically.

---

## Connect to Cursor / Windsurf / VS Code

Add to your MCP config (`.cursor/mcp.json` or equivalent):

```json
{
  "mcpServers": {
    "jobs": {
      "command": "node",
      "args": ["/absolute/path/to/jobs-mcp-server/server.js"],
      "env": {
        "MONGO_URI": "mongodb://localhost:27017",
        "DB_NAME": "xpress_health"
      }
    }
  }
}
```

---

## Production deployment (HTTPS without ngrok)

Deploy the SSE bridge on any Node.js host (Railway, Render, Fly.io, VPS):

```bash
# On your server
MONGO_URI="mongodb+srv://..." DB_NAME="xpress_health" \
npx @modelcontextprotocol/server-stdio-to-sse \
  --port 3100 \
  -- node /app/jobs-mcp-server/server.js
```

Point your domain / reverse proxy at port 3100 with HTTPS, then use that URL in ChatGPT.

---

## Example ChatGPT prompts once connected

```
List all jobs scheduled this week
Show me all In Progress jobs for wound care
Create a job: Morning Personal Care for Patrick Cronin, Personal Care type, scheduled 2026-05-20
Mark job 683abc... as Completed
How many jobs are in each status?
Search for jobs in Kerry
Delete job 683abc... (soft delete)
```
