"""Telegram Webhook Registration Utility.

Use this script to configure or check your Telegram bot webhook for local tunnels or Render deployments:
    python scripts/setup_telegram_webhook.py --url https://your-nexa-app.onrender.com/api/v1/integrations/telegram/webhook
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings


async def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Telegram Webhook for NEXA")
    parser.add_argument("--url", type=str, help="Public webhook URL")
    parser.add_argument("--delete", action="store_true", help="Delete the current webhook")
    parser.add_argument("--info", action="store_true", help="Get current webhook info")
    args = parser.parse_args()

    token = settings.TELEGRAM_BOT_TOKEN
    secret = settings.TELEGRAM_WEBHOOK_SECRET

    if not token:
        print("\033[91mError: TELEGRAM_BOT_TOKEN is not configured in .env\033[0m")
        return

    base_url = f"https://api.telegram.org/bot{token}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Check current webhook info
        if args.info or (not args.url and not args.delete):
            resp = await client.get(f"{base_url}/getWebhookInfo")
            print("\n\033[1mCurrent Telegram Webhook Info:\033[0m")
            print(resp.json())
            return

        # Delete webhook
        if args.delete:
            resp = await client.post(f"{base_url}/deleteWebhook")
            print(f"\n\033[92mDelete Webhook Result:\033[0m {resp.json()}")
            return

        # Set webhook
        webhook_url = args.url or settings.TELEGRAM_WEBHOOK_URL
        if not webhook_url:
            print("\033[91mError: Please provide --url (e.g. https://your-app.onrender.com/api/v1/integrations/telegram/webhook)\033[0m")
            return

        payload = {
            "url": webhook_url,
            "drop_pending_updates": True,
            "allowed_updates": ["message", "callback_query"],
        }
        if secret:
            payload["secret_token"] = secret

        resp = await client.post(f"{base_url}/setWebhook", json=payload)
        data = resp.json()
        if data.get("ok"):
            print(f"\n\033[92m✓ Telegram Webhook successfully set to:\033[0m {webhook_url}")
            if secret:
                print("  \033[92m✓ Webhook secret verification enabled.\033[0m")
        else:
            print(f"\n\033[91mFailed to set webhook:\033[0m {data}")


if __name__ == "__main__":
    asyncio.run(main())
