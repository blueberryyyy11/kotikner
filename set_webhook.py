import requests
import json

# --- YOUR CONFIGURATION ---
BOT_TOKEN = "8020313173:AAG1V_ytdmVHCL7Jz0Y0MfGHgURe9G9pbnc"
USERNAME = "blueberry111"
# --------------------------

# 1. The target URL where Telegram will send messages
# Note: The URL must be HTTPS and include the token as part of the path for security.
WEBHOOK_URL = f"https://{USERNAME}.pythonanywhere.com/{BOT_TOKEN}"

# 2. The Telegram API endpoint to register the webhook
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}"

print(f"Attempting to register webhook for user: {USERNAME}")
print(f"Target URL: {WEBHOOK_URL}")
print("-" * 30)

try:
    # Send the request to the Telegram API
    response = requests.post(API_URL)
    response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)

    # Print the result from Telegram
    result = response.json()
    print("--- Telegram API Response (setWebhook) ---")
    print(json.dumps(result, indent=4))
    print("------------------------------------------")

    if result.get("ok") and result.get("result"):
        print("\n✅ SUCCESS: Webhook successfully registered!")
    else:
        print(f"\n❌ FAILED: Could not register webhook. Description: {result.get('description', 'No description provided')}")

except requests.exceptions.RequestException as e:
    print(f"\n❌ ERROR: An error occurred during the request: {e}")
