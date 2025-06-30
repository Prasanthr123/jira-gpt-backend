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
    issue_type = data.get("issue_type", "Bug")
# Handle Jira-friendly issue type mappings
jira_friendly_types = {
    "Story": "User Story",
    "Bug": "Bug",
    "Task": "Task",
    "Improvement": "Improvement"
}

# Convert GPT-sent issue type to Jira-compatible name
issue_type = jira_friendly_types.get(issue_type, "Bug")


    # Environment variables (set in Render)
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_TOKEN")
    jira_url = os.getenv("JIRA_URL")
    project_key = os.getenv("JIRA_PROJECT")

    # Validate required fields
    if not all([summary, description, project_key, jira_email, jira_token, jira_url]):
        return JSONResponse(status_code=400, content={"error": "Missing required fields"})

    # Validate issue type
    valid_types = ["Bug", "Task", "Story", "Improvement"]
    if issue_type not in valid_types:
        return JSONResponse(status_code=400, content={
            "error": f"Invalid issue type. Must be one of: {', '.join(valid_types)}"
        })

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
            "issuetype": {"name": issue_type}
        }
    }

    response = requests.post(url, headers=headers, auth=auth, json=payload)

    if response.status_code == 201:
        return {
            "message": "Jira issue created successfully.",
            "issueKey": response.json().get("key")
        }
    else:
        return JSONResponse(status_code=response.status_code, content={
            "error": response.text
        })
