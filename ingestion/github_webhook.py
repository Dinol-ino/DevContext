from fastapi import FastAPI
from extractor import extract_decision
import traceback
from db_insert import insert_decision
app = FastAPI()


@app.post("/github-webhook")
async def github_webhook(payload: dict):
    try:
        action = payload.get("action")
        pr = payload.get("pull_request", {})

        title = pr.get("title", "")
        body = pr.get("body", "")
        url = pr.get("html_url", "")
        author = pr.get("user", {}).get("login", "")
        repo = payload.get("repository", {}).get("full_name", "")
        merged = pr.get("merged", False)

        event_type = "merged" if action == "closed" and merged else action

        pr_text = f"""
Repo: {repo}
Author: {author}
Event: {event_type}
Title: {title}
Body: {body}
URL: {url}
"""

        result = extract_decision(pr_text)
        db_result = insert_decision(result, url)

        return {
            "received": True,
            "event": event_type,
            "extracted": result,
            "saved":True
        }

    except Exception as e:
        return {
            "error": str(e),
            "trace": traceback.format_exc()
        }