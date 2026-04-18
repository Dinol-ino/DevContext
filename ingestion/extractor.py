import os
import json
import requests
from dotenv import load_dotenv

load_dotenv("../.env")

API_KEY = os.getenv("OPENROUTER_API_KEY")


def extract_decision(pr_text):
    prompt = f"""
Return ONLY valid JSON.

{{
  "decision":"",
  "reason":"",
  "services":[]
}}

PR:
{pr_text}
"""

    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        },
        timeout=30
    )

    data = r.json()

    text = data["choices"][0]["message"]["content"].strip()

    text = text.replace("```json", "").replace("```", "").strip()

    if not text:
        return {
            "decision": "No output",
            "reason": "Empty response",
            "services": []
        }

    try:
        return json.loads(text)

    except:
        return {
            "decision": "Parse fallback",
            "reason": text,
            "services": []
        }