
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os, requests, urllib.parse, logging, sys

app = FastAPI()

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("jira-oauth-backend")

# OAuth setup
CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "https://jira-gpt-backend.onrender.com/oauth/callback")
AUTH_BASE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
USER_API_URL = "https://api.atlassian.com/me"
RESOURCE_API = "https://api.atlassian.com/oauth/token/accessible-resources"
SCOPES = ["read:jira-work", "write:jira-work", "read:jira-user"]
user_tokens = {}
logger.info(f"✅ Loaded OAuth ENV: REDIRECT_URI = {REDIRECT_URI}")
logger.info(f"✅ Loaded OAuth ENV: CLIENT_ID = {CLIENT_ID[:6]}****")  # Masking for security


@app.get("/oauth/login")
def start_oauth():
    query = {
        "audience": "api.atlassian.com",
        "client_id": CLIENT_ID,
        "scope": " ".join(SCOPES),
        "redirect_uri": REDIRECT_URI,
        "state": "secureState123",
        "response_type": "code",
        "prompt": "consent"
    }
    url = f"{AUTH_BASE_URL}?{urllib.parse.urlencode(query)}"
    return RedirectResponse(url)

@app.get("/oauth/callback")
async def oauth_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    token_response = requests.post(TOKEN_URL, json=payload)
    if token_response.status_code != 200:
        return JSONResponse(status_code=token_response.status_code, content=token_response.json())
    tokens = token_response.json()
    access_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    user_info = requests.get(USER_API_URL, headers=headers).json()
    user_id = user_info.get("email", "unknown@example.com")
    cloud_info = requests.get(RESOURCE_API, headers=headers).json()
    if not cloud_info:
        raise HTTPException(status_code=400, detail="No accessible Jira site found")
    cloud_id = cloud_info[0]["id"]
    base_url = f"https://api.atlassian.com/ex/jira/{cloud_id}"
    user_tokens[user_id] = {
        "access_token": access_token,
        "cloud_id": cloud_id,
        "base_url": base_url
    }
    logger.info(f"OAuth Success | User: {user_id}")
    return {"message": "OAuth successful", "user": user_id, "cloud_id": cloud_id}

def get_auth_headers(x_user_id: str = Depends(lambda: "unknown")):
    data = user_tokens.get(x_user_id)
    if not data:
        raise HTTPException(status_code=401, detail="User not authenticated")
    return {
        "Authorization": f"Bearer {data['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }, data["base_url"]

@app.get("/projects")
async def get_projects(request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Fetch Projects")
    res = requests.get(f"{base_url}/rest/api/3/project", headers=headers)
    return res.json()

@app.post("/ticket")
async def create_ticket(request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Create Ticket")
    payload = {
        "fields": {
            "project": {"key": data.get("project_key")},
            "summary": data.get("summary"),
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("description") or ""}]}]
            },
            "issuetype": {"name": data.get("issue_type", "Bug")}
        }
    }
    res = requests.post(f"{base_url}/rest/api/3/issue", headers=headers, json=payload)
    return res.json()

@app.get("/ticket/{issue_key}")
async def fetch_ticket(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Fetch Ticket {issue_key}")
    res = requests.get(f"{base_url}/rest/api/3/issue/{issue_key}", headers=headers)
    return res.json()

@app.patch("/ticket/{issue_key}")
async def update_ticket(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Update Ticket {issue_key}")
    update_fields = {}
    if "summary" in data:
        update_fields["summary"] = data["summary"]
    if "description" in data:
        update_fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data["description"]}]}]
        }
    res = requests.put(f"{base_url}/rest/api/3/issue/{issue_key}", headers=headers, json={"fields": update_fields})
    return {"message": "Updated"} if res.status_code == 204 else res.json()

@app.get("/ticket/{issue_key}/comments")
async def get_comments(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Get Comments {issue_key}")
    res = requests.get(f"{base_url}/rest/api/3/issue/{issue_key}/comment", headers=headers)
    return res.json()

@app.post("/ticket/{issue_key}/comments")
async def add_comment(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Add Comment {issue_key}")
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("body") or ""}]}]
        }
    }
    res = requests.post(f"{base_url}/rest/api/3/issue/{issue_key}/comment", headers=headers, json=payload)
    return res.json()

@app.patch("/ticket/{issue_key}/comments/{comment_id}")
async def update_comment(issue_key: str, comment_id: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    logger.info(f"User: {request.headers.get('X-User-Id')} | Action: Update Comment {comment_id}")
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("body") or ""}]}]
        }
    }
    res = requests.put(f"{base_url}/rest/api/3/issue/{issue_key}/comment/{comment_id}", headers=headers, json=payload)
    return {"message": "Comment updated"} if res.status_code == 200 else res.json()

# 🔍 Impact Analysis by Label
@app.get("/impact/label/{label}")
async def get_impact_by_label(label: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    jql = f'labels = "{label}"'
    response = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]} for i in issues]
    return JSONResponse(status_code=response.status_code, content={"error": response.text})

# 🔍 Impact Analysis by Component
@app.get("/impact/component/{component}")
async def get_impact_by_component(component: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    jql = f'component = "{component}"'
    response = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]} for i in issues]
    return JSONResponse(status_code=response.status_code, content={"error": response.text})

# 🔍 Impact Analysis by Module or Title Keyword
@app.get("/impact/module/{keyword}")
async def get_impact_by_module(keyword: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    jql = f'summary ~ "{keyword}"'
    response = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]} for i in issues]
    return JSONResponse(status_code=response.status_code, content={"error": response.text})

# 🔍 Fetch tickets by Sprint ID
@app.get("/tickets/sprint/{sprint_id}")
async def get_tickets_by_sprint(sprint_id: int, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    jql = f"sprint = {sprint_id}"
    response = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"]} for i in issues]
    return JSONResponse(status_code=response.status_code, content={"error": response.text})

# 🔍 Fetch tickets by Priority
@app.get("/tickets/priority/{priority}")
async def get_tickets_by_priority(priority: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    jql = f'priority = "{priority}"'
    response = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"]} for i in issues]
    return JSONResponse(status_code=response.status_code, content={"error": response.text})

# 🔍 Fetch tickets by Label
@app.get("/tickets/label/{label}")
async def get_tickets_by_label(label: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    jql = f'labels = "{label}"'
    response = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"]} for i in issues]
    return JSONResponse(status_code=response.status_code, content={"error": response.text})

