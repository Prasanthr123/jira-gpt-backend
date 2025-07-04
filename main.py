from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os, requests, urllib.parse, logging, sys, uuid

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
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "").strip()

AUTH_BASE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
USER_API_URL = "https://api.atlassian.com/me"
RESOURCE_API = "https://api.atlassian.com/oauth/token/accessible-resources"
SCOPES = ["read:jira-work", "write:jira-work", "read:jira-user"]
user_tokens = {}

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
    user_id = user_info.get("account_id", f"user_{uuid.uuid4()}")
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
    return HTMLResponse(
        content=f"""
        <h2>✅ Jira OAuth Login Successful!</h2>
        <p>You can now return to ChatGPT and continue using the assistant.</p>
        <p><strong>Your Jira ID:</strong> <code>{user_id}</code></p>
        <p>📋 Please copy this ID and paste it into ChatGPT when asked.</p>
        """,
        status_code=200
    )

def get_auth_headers(request: Request):
    # Log all incoming headers for debugging (optional)
    logger.info(f"Incoming headers: {dict(request.headers)}")
    logger.info(f"Incoming query params: {dict(request.query_params)}")

    # Get from query param (new method)
    x_user_id = request.query_params.get("user_id")

    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing user_id. Please log in via /oauth/login.")

    if x_user_id not in user_tokens:
        raise HTTPException(status_code=401, detail="Session expired or user not authenticated.")

    data = user_tokens[x_user_id]

    return {
        "Authorization": f"Bearer {data['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }, data["base_url"]

@app.get("/projects")
async def get_projects(request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    res = requests.get(f"{base_url}/rest/api/3/project", headers=headers)
    return res.json()

@app.post("/ticket")
async def create_ticket(request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    payload = {
        "fields": {
            "project": {"key": data.get("project_key")},
            "summary": data.get("summary"),
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("description", "")}]}]
            },
            "issuetype": {"name": data.get("issue_type", "Bug")}
        }
    }
    res = requests.post(f"{base_url}/rest/api/3/issue", headers=headers, json=payload)
    return res.json() if res.status_code != 201 else {"message": "Ticket created"}

@app.get("/ticket/{issue_key}")
async def fetch_ticket(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    res = requests.get(f"{base_url}/rest/api/3/issue/{issue_key}", headers=headers)
    return res.json()

@app.patch("/ticket/{issue_key}")
async def update_ticket(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    update_fields = {}
    if "summary" in data:
        update_fields["summary"] = data["summary"]
    if "description" in data:
        update_fields["description"] = {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data["description"]}]}]
        }
    res = requests.put(f"{base_url}/rest/api/3/issue/{issue_key}", headers=headers, json={"fields": update_fields})
    return {"message": "Updated"} if res.status_code == 204 else res.json()

@app.get("/ticket/{issue_key}/comments")
async def get_comments(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    res = requests.get(f"{base_url}/rest/api/3/issue/{issue_key}/comment", headers=headers)
    return res.json()

@app.post("/ticket/{issue_key}/comments")
async def add_comment(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    payload = {
        "body": {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("body", "")}]}]
        }
    }
    res = requests.post(f"{base_url}/rest/api/3/issue/{issue_key}/comment", headers=headers, json=payload)
    return res.json()

@app.patch("/ticket/{issue_key}/comments/{comment_id}")
async def update_comment(issue_key: str, comment_id: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    data = await request.json()
    payload = {
        "body": {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("body", "")}]}]
        }
    }
    res = requests.put(f"{base_url}/rest/api/3/issue/{issue_key}/comment/{comment_id}", headers=headers, json=payload)
    return {"message": "Comment updated"} if res.status_code == 200 else res.json()

def jql_search(jql: str, headers, base_url):
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if res.status_code == 200:
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]}
                for i in res.json().get("issues", [])]
    return JSONResponse(status_code=res.status_code, content={"error": res.text})

@app.get("/impact/label/{label}")
async def get_impact_by_label(label: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    return jql_search(f'labels = "{label}"', headers, base_url)

@app.get("/impact/component/{component}")
async def get_impact_by_component(component: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    return jql_search(f'component = "{component}"', headers, base_url)

@app.get("/impact/module/{keyword}")
async def get_impact_by_module(keyword: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    return jql_search(f'summary ~ "{keyword}"', headers, base_url)

@app.get("/tickets/sprint/{sprint_id}")
async def get_tickets_by_sprint(sprint_id: int, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    return jql_search(f"sprint = {sprint_id}", headers, base_url)

@app.get("/tickets/priority/{priority}")
async def get_tickets_by_priority(priority: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url = auth_data
    return jql_search(f'priority = "{priority}"', headers, base_url)
