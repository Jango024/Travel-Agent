"""Telegram bot interface for the travel agent."""
 from __future__ import annotations
 
 import asyncio
 import logging
 import os
-from typing import Final
+from typing import Any, Final
 
-import requests
+import aiohttp
 from telegram import Update
 from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
 
 logging.basicConfig(level=logging.INFO)
 LOGGER = logging.getLogger(__name__)
 
 BACKEND_URL: Final[str] = os.getenv("TRAVEL_AGENT_BACKEND_URL", "http://localhost:5000")
 BOT_TOKEN: Final[str | None] = os.getenv("TELEGRAM_BOT_TOKEN")
 
 
 async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
     await update.message.reply_text(
         "Hallo! Sende mir deine Reiseanfrage in natürlicher Sprache, z.B. '2 Personen nach Kreta im August, Budget 1200€'."
     )
 
 
 async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
     if not update.message or not update.message.text:
         return
     text = update.message.text
     chat_id = update.effective_chat.id
+    data: dict[str, Any]
     try:
-        response = requests.post(
-            f"{BACKEND_URL}/api/run-from-bot",
-            json={"chat_id": str(chat_id), "message": text},
-            timeout=10,
-        )
-    except requests.RequestException as exc:  # pragma: no cover - network failure handling
+        timeout = aiohttp.ClientTimeout(total=10)
+        async with aiohttp.ClientSession(timeout=timeout) as session:
+            async with session.post(
+                f"{BACKEND_URL}/api/run-from-bot",
+                json={"chat_id": str(chat_id), "message": text},
+            ) as response:
+                if response.status != 200:
+                    error_text = await response.text()
+                    LOGGER.error("Backend error: %s", error_text)
+                    await update.message.reply_text(
+                        "Die Anfrage konnte nicht gestartet werden. Bitte erneut versuchen."
+                    )
+                    return
+                data = await response.json()
+    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:  # pragma: no cover - network failure handling
         LOGGER.error("Backend request failed: %s", exc)
         await update.message.reply_text("Das Backend ist derzeit nicht erreichbar. Bitte später erneut versuchen.")
         return
 
-    if response.status_code != 200:
-        LOGGER.error("Backend error: %s", response.text)
-        await update.message.reply_text("Die Anfrage konnte nicht gestartet werden. Bitte erneut versuchen.")
-        return
-
-    data = response.json()
     status_url = data.get("status_url")
     task_id = data.get("task_id")
     reply = "Suche gestartet!"
     if status_url:
         reply += f"\nStatus abrufen: {status_url}"
     elif task_id:
         reply += f"\nTask-ID: {task_id}"
     await update.message.reply_text(reply)
 
 
 async def main() -> None:
     if not BOT_TOKEN:
         raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")
     application = ApplicationBuilder().token(BOT_TOKEN).build()
     application.add_handler(CommandHandler("start", start_command))
     application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
     await application.run_polling()
 
 
 if __name__ == "__main__":
     asyncio.run(main())
