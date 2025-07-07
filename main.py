from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os, requests, urllib.parse, logging, sys, uuid
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("human-friendly-logger")

user_tokens = {}  # Now includes project_key too

@app.middleware("http")
async def user_friendly_logger(request: Request, call_next):
    user_id = request.query_params.get("user_id", "unknown_user")
    ip = request.client.host if request.client else "unknown_ip"
    path = request.url.path
    method = request.method
    timestamp = datetime.utcnow().strftime("%b %d %Y %I:%M:%S %p")

    action_map = {
        "/oauth/login": "started login",
        "/oauth/callback": "completed login",
        "/generate_test_case": "requested test case generation",
        "/report_defect": "reported a defect",
        "/impact_analysis": "ran impact analysis",
        "/ticket": "created a Jira ticket",
        "/": "pinged home"
    }
    action = action_map.get(path, f"accessed {path}")

    logger.info(f"\n\U0001F4E5 REQUEST | [{timestamp}]")
    logger.info(f"User ID: {user_id}")
    logger.info(f"IP Address: {ip}")
    logger.info(f"Action: {action}")
    logger.info(f"Method: {method}")
    logger.info(f"Path: {path}")

    response = await call_next(request)
    logger.info(f"📤 RESPONSE | Status Code: {response.status_code}")
    logger.info("-" * 60)
    return response

@app.get("/")
async def home():
    return {"message": "Welcome to QA GPT backend"}

CLIENT_ID = os.getenv("ATLASSIAN_CLIENT_ID")
CLIENT_SECRET = os.getenv("ATLASSIAN_CLIENT_SECRET")
REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "").strip()

AUTH_BASE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
USER_API_URL = "https://api.atlassian.com/me"
RESOURCE_API = "https://api.atlassian.com/oauth/token/accessible-resources"
SCOPES = ["read:jira-work", "write:jira-work", "read:jira-user"]

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
        "base_url": base_url,
        "project_key": None
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
    x_user_id = request.query_params.get("user_id")
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing user_id. Please log in via /oauth/login.")
    if x_user_id not in user_tokens:
        raise HTTPException(status_code=401, detail="Session expired or user not authenticated.")
    data = user_tokens[x_user_id]
    if not data.get("project_key"):
        raise HTTPException(status_code=400, detail="Project key not set. Please call /set-project first.")
    return {
        "Authorization": f"Bearer {data['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }, data["base_url"], data["project_key"]

@app.get("/projects")
async def get_projects(request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
    res = requests.get(f"{base_url}/rest/api/3/project", headers=headers)
    return res.json()

@app.post("/ticket")
async def create_ticket(request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, project_key = auth_data
    data = await request.json()
    payload = {
        "fields": {
            "project": {"key": project_key},
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
    headers, base_url, _ = auth_data
    res = requests.get(f"{base_url}/rest/api/3/issue/{issue_key}", headers=headers)
    return res.json()

@app.patch("/ticket/{issue_key}")
async def update_ticket(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
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
    headers, base_url, _ = auth_data
    res = requests.get(f"{base_url}/rest/api/3/issue/{issue_key}/comment", headers=headers)
    return res.json()

@app.post("/ticket/{issue_key}/comments")
async def add_comment(issue_key: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
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
    headers, base_url, _ = auth_data
    data = await request.json()
    payload = {
        "body": {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": data.get("body", "")}]}]
        }
    }
    res = requests.put(f"{base_url}/rest/api/3/issue/{issue_key}/comment/{comment_id}", headers=headers, json=payload)
    return {"message": "Comment updated"} if res.status_code == 200 else res.json()


def jql_search(jql: str, headers, base_url, source_ticket_key: str = None):
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    if res.status_code == 200:
        issues = []
        for i in res.json().get("issues", []):
            key = i["key"]
            if source_ticket_key and key == source_ticket_key:
                logger.info(f"Skipping source ticket {key} from impact analysis.")
                continue
            issue_type = i["fields"].get("issuetype", {}).get("name", "").lower()
            description = i["fields"].get("description", "")
            if issue_type in ["epic", "parent"]:
                if not description:
                    logger.info(f"Skipping Epic/Parent ticket {key} with no description.")
                    continue
                text = description if isinstance(description, str) else str(description)
                logic_keywords = ["verify", "check", "validate", "flow", "test", "should"]
                if not any(word in text.lower() for word in logic_keywords):
                    logger.info(f"Skipping Epic/Parent ticket {key} without logic keywords.")
                    continue
            issues.append({
                "key": key,
                "summary": i["fields"]["summary"],
                "description": description
            })
        return issues
    return JSONResponse(status_code=res.status_code, content={"error": res.text})

@app.get("/impact/label/{label}")
async def get_impact_by_label(label: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
    source_ticket_key = request.query_params.get("source_ticket")
    jql = f'labels = "{label}"'
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    return res.json()

@app.get("/impact/component/{component}")
async def get_impact_by_component(component: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
    source_ticket_key = request.query_params.get("source_ticket")
    jql = f'component = "{component}"'
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    return res.json()

@app.get("/impact/module/{keyword}")
async def get_impact_by_module(keyword: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
    source_ticket_key = request.query_params.get("source_ticket")
    jql = f'summary ~ "{keyword}"'
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    return res.json()

@app.get("/tickets/sprint/{sprint_id}")
async def get_tickets_by_sprint(sprint_id: int, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
    jql = f"sprint = {sprint_id}"
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    return res.json()

@app.get("/tickets/priority/{priority}")
async def get_tickets_by_priority(priority: str, request: Request, auth_data=Depends(get_auth_headers)):
    headers, base_url, _ = auth_data
    jql = f'priority = "{priority}"'
    res = requests.get(f"{base_url}/rest/api/3/search", headers=headers, params={"jql": jql, "maxResults": 100})
    return res.json()
