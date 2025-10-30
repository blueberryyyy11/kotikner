import requests
import json

# --- YOUR CONFIGURATION ---
# Bot Token provided by BotFather (Using the token from set_webhook.py)
BOT_TOKEN = "8020313173:AAG1V_ytdmVHCL7Jz0Y0MfGHgURe9G9pbnc"
# --------------------------

# The Telegram API endpoint to get webhook information
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"

print(f"Checking status for bot: {BOT_TOKEN.split(':')[0]}...")
print("-" * 30)

try:
    # Send the GET request to the Telegram API
    response = requests.get(API_URL)
    response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)

    # Print the result from Telegram
    result = response.json()
    
    if result.get("ok") and result.get("result"):
        info = result["result"]
        print("--- Webhook Information ---")
        print(f"URL: {info.get('url')}")
        print(f"Pending Update Count: {info.get('pending_update_count')}")
        
        last_error_date = info.get('last_error_date')
        error_message = info.get('last_error_message')

        if last_error_date:
            print(f"LAST ERROR: {error_message}")
        else:
            print("Status: Webhook appears to be active and healthy. ")
        print("---------------------------")
    else:
        print(f"❌ ERROR: Could not retrieve webhook info. Description: {result.get('description', 'N/A')}")

except requests.exceptions.RequestException as e:
    print(f"\n❌ ERROR: An error occurred during the request: {e}")
