import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/create_jira_story", methods=["POST"])
def create_jira_story():
    data = request.get_json()
    summary = data.get("summary")
    description = data.get("description")

    if not summary or not description:
        return jsonify({"error": "Missing summary or description"}), 400

    # ✅ Securely fetch credentials from env
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
            "issuetype": {"name": "Story"}
        }
    }

    response = requests.post(url, headers=headers, auth=auth, json=payload)

    if response.status_code == 201:
        return jsonify({
            "message": "Story created successfully",
            "issueKey": response.json().get("key")
        }), 201
    else:
        return jsonify({
            "error": response.text,
            "status": response.status_code
        }), response.status_code
