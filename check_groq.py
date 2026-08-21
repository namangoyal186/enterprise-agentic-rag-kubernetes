import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
print(f"Checking Groq API Key: {api_key[:8]}...{api_key[-4:] if api_key else 'None'}")

url = "https://api.groq.com/openai/v1/models"
response = requests.get(
    url,
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=10,
)

if response.status_code == 200:
    data = response.json().get("data", [])
    model_ids = [m["id"] for m in data]
    print("\n--- AVAILABLE GROQ MODELS FOR YOUR KEY ---")
    for mid in sorted(model_ids):
        print(f"  - {mid}")
else:
    print(f"\nFailed ({response.status_code}): {response.text}")