
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import requests

app = FastAPI()

# Common config
def get_jira_config():
    return {
        "email": os.getenv("JIRA_EMAIL"),
        "token": os.getenv("JIRA_TOKEN"),
        "url": os.getenv("JIRA_URL"),
        "project_key": os.getenv("JIRA_PROJECT")
    }

@app.get("/projects")
async def get_jira_projects():
    config = get_jira_config()
    url = f"{config['url']}/rest/api/3/project"
    auth = (config["email"], config["token"])
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=auth)
    if response.status_code == 200:
        projects = response.json()
        return [{"key": p["key"], "name": p["name"]} for p in projects]
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})


# Create Jira Ticket
@app.post("/ticket")
async def create_jira_story(req: Request):
    data = await req.json()
    summary = data.get("summary")
    description = data.get("description")
    issue_type = data.get("issue_type", "Bug")

    config = get_jira_config()
    if not all([summary, description, config["email"], config["token"], config["url"], config["project_key"]]):
        return JSONResponse(status_code=400, content={"error": "Missing required fields"})

    valid_types = ["Bug", "Task", "Story", "Improvement"]
    if issue_type not in valid_types:
        return JSONResponse(status_code=400, content={"error": f"Invalid issue type. Must be one of: {', '.join(valid_types)}"})

    url = f"{config['url']}/rest/api/3/issue"
    auth = (config["email"], config["token"])
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "fields": {
            "project": {"key": config["project_key"]},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{
                        "type": "text",
                        "text": description
                    }]
                }]
            },
            "issuetype": {"name": issue_type}
        }
    }
    response = requests.post(url, headers=headers, auth=auth, json=payload)
    if response.status_code == 201:
        return {"message": "Jira issue created successfully.", "issueKey": response.json().get("key")}
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Fetch Jira Ticket
@app.get("/ticket/{issue_key}")
async def fetch_jira_ticket(issue_key: str):
    config = get_jira_config()
    url = f"{config['url']}/rest/api/3/issue/{issue_key}"
    auth = (config["email"], config["token"])
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=auth)
    if response.status_code == 200:
        data = response.json()
        return {
            "summary": data["fields"]["summary"],
            "description": data["fields"]["description"],
            "status": data["fields"]["status"]["name"]
        }
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Update Jira Ticket
@app.patch("/ticket/{issue_key}")
async def update_jira_ticket(issue_key: str, req: Request):
    data = await req.json()
    config = get_jira_config()
    update_fields = {}
    if "summary" in data:
        update_fields["summary"] = data["summary"]
    if "description" in data:
        update_fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": data["description"]
                }]
            }]
        }

    url = f"{config['url']}/rest/api/3/issue/{issue_key}"
    auth = (config["email"], config["token"])
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    response = requests.put(url, headers=headers, auth=auth, json={"fields": update_fields})
    if response.status_code == 204:
        return {"message": f"Ticket {issue_key} updated successfully"}
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Get Ticket Comments
@app.get("/ticket/{issue_key}/comments")
async def get_ticket_comments(issue_key: str):
    config = get_jira_config()
    url = f"{config['url']}/rest/api/3/issue/{issue_key}/comment"
    headers = {"Accept": "application/json"}
    auth = (config["email"], config["token"])

    response = requests.get(url, headers=headers, auth=auth)
    if response.status_code == 200:
        comments = response.json().get("comments", [])
        return [
            {
                "id": c["id"],
                "author": c["author"]["displayName"],
                "body": c["body"]["content"][0]["content"][0]["text"] if c["body"]["content"] else "",
                "created": c["created"]
            }
            for c in comments
        ]
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Add Ticket Comment
@app.post("/ticket/{issue_key}/comments")
async def add_ticket_comment(issue_key: str, req: Request):
    config = get_jira_config()
    url = f"{config['url']}/rest/api/3/issue/{issue_key}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (config["email"], config["token"])
    data = await req.json()
    comment_text = data.get("body")
    if not comment_text:
        return JSONResponse(status_code=400, content={"error": "Missing comment body"})

    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": comment_text
                }]
            }]
        }
    }
    response = requests.post(url, headers=headers, auth=auth, json=payload)
    if response.status_code == 201:
        return {"message": "Comment added successfully."}
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Update Ticket Comment
@app.patch("/ticket/{issue_key}/comments/{comment_id}")
async def update_ticket_comment(issue_key: str, comment_id: str, req: Request):
    config = get_jira_config()
    user_email = config["email"]
    url = f"{config['url']}/rest/api/3/issue/{issue_key}/comment/{comment_id}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (user_email, config["token"])
    data = await req.json()
    new_text = data.get("body")
    is_admin = data.get("is_admin", False)
    current = requests.get(url, headers=headers, auth=auth)
    if current.status_code != 200:
        return JSONResponse(status_code=current.status_code, content={"error": current.text})
    author_email = current.json().get("author", {}).get("emailAddress", "")
    if user_email != author_email and not is_admin:
        return JSONResponse(status_code=403, content={"error": "Permission denied"})

    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": new_text
                }]
            }]
        }
    }
    response = requests.put(url, headers=headers, auth=auth, json=payload)
    if response.status_code == 200:
        return {"message": "Comment updated successfully"}
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Impact Analysis by Label
@app.get("/impact/label/{label}")
async def get_impact_by_label(label: str):
    config = get_jira_config()
    jql = f'project = {config["project_key"]} AND labels = "{label}"'
    url = f"{config['url']}/rest/api/3/search"
    headers = {"Accept": "application/json"}
    auth = (config["email"], config["token"])
    params = {"jql": jql, "maxResults": 100}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]} for i in issues]
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Impact Analysis by Component
@app.get("/impact/component/{component}")
async def get_impact_by_component(component: str):
    config = get_jira_config()
    jql = f'project = {config["project_key"]} AND component = "{component}"'
    url = f"{config['url']}/rest/api/3/search"
    headers = {"Accept": "application/json"}
    auth = (config["email"], config["token"])
    params = {"jql": jql, "maxResults": 100}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]} for i in issues]
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})

# Impact Analysis by Module or Title Keyword
@app.get("/impact/module/{keyword}")
async def get_impact_by_module(keyword: str):
    config = get_jira_config()
    jql = f'project = {config["project_key"]} AND summary ~ "{keyword}"'
    url = f"{config['url']}/rest/api/3/search"
    headers = {"Accept": "application/json"}
    auth = (config["email"], config["token"])
    params = {"jql": jql, "maxResults": 100}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    if response.status_code == 200:
        issues = response.json().get("issues", [])
        return [{"key": i["key"], "summary": i["fields"]["summary"], "description": i["fields"]["description"]} for i in issues]
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})
