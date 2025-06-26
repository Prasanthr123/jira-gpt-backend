from fastapi import FastAPI, Request
import requests

app = FastAPI()

@app.post("/")
async def jira_handler(req: Request):
    data = await req.json()

    jira_email = data.get("email")
    jira_token = data.get("token")
    jira_url = data.get("url")
    project_key = data.get("project_key")
    action = data.get("action")

    auth = (jira_email, jira_token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    if action == "create_bug":
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": data["summary"],
                "description": data["description"],
               "issuetype": {"name": data.get("issue_type", "Bug")},
            }
        }
        r = requests.post(f"{jira_url}/rest/api/3/issue", auth=auth, headers=headers, json=payload)
        return r.json()

    elif action == "get_ticket":
        issue_key = data["issue_key"]
        r = requests.get(f"{jira_url}/rest/api/3/issue/{issue_key}", auth=auth, headers=headers)
        return r.json()

    elif action == "search_issues":
        r = requests.get(f"{jira_url}/rest/api/3/search?jql={data['jql']}", auth=auth, headers=headers)
        return r.json()

    elif action == "add_comment":
        payload = { "body": data["comment"] }
        issue_key = data["issue_key"]
        r = requests.post(f"{jira_url}/rest/api/3/issue/{issue_key}/comment", auth=auth, headers=headers, json=payload)
        return r.json()

    return {"error": "Invalid action"}
