from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import requests

app = FastAPI()

@app.post("/")
async def create_jira_story(req: Request):
    data = await req.json()

    summary = data.get("summary")
    description = data.get("description")
    issue_type = data.get("issue_type", "Story")  # Valid: Bug, Story, Task, Improvement

    if not summary or not description:
        return JSONResponse(status_code=400, content={"error": "Missing fields"})

    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_TOKEN")
    jira_url = os.getenv("JIRA_URL")
    project_key = os.getenv("JIRA_PROJECT")

    url = f"{jira_url}/rest/api/3/issue"
    auth = (jira_email, jira_token)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "fields": {
            "project": {"key": project_key},
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
            "issuetype": {"name": issue_type}valid_types = ["Bug", "Task", "Story", "Improvement"]
if data.get("issue_type") not in valid_types:
    return {"error": "Invalid issue type. Must be one of: " + ", ".join(valid_types)}, 400
        }
    }

    response = requests.post(url, headers=headers, auth=auth, json=payload)

    if response.status_code == 201:
        return {"message": "Story created", "issueKey": response.json().get("key")}
    else:
        return JSONResponse(status_code=response.status_code, content={"error": response.text})
