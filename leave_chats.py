import os
import csv
import asyncio
import random
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
SESSION_NAME = 'telegram_bulk_session'
CSV_FILENAME = 'telegram_chats_triage.csv'

async def main():
    if not API_ID or not API_HASH:
        print("Error: API_ID or API_HASH not found in .env file.")
        return

    if not os.path.exists(CSV_FILENAME):
        print(f"Error: '{CSV_FILENAME}' not found.")
        print("Please run export_chats.py first to generate the list of chats.")
        return

    # Read CSV and filter
    chats_to_leave = []
    with open(CSV_FILENAME, mode='r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('action', '').strip().upper() == 'LEAVE':
                chats_to_leave.append(row)

    if not chats_to_leave:
        print("No chats marked with 'LEAVE' in the CSV. Everything looks clean!")
        return

    print(f"Found {len(chats_to_leave)} chats to leave.")
    print("Starting Telethon client...")
    
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    await client.start()
    
    print("Client successfully authenticated!")
    print("--------------------------------------------------\n")
    
    for i, chat in enumerate(chats_to_leave, 1):
        chat_id = int(chat['id'])
        title = chat['title']
        
        print(f"[{i}/{len(chats_to_leave)}] Attempting to leave: {title} (ID: {chat_id})")
        
        while True:
            try:
                # delete_dialog automatically determines the correct request based on entity type
                # and removes the chat from your dialog list.
                await client.delete_dialog(chat_id)
                print(f"✓ Successfully left '{title}'.")
                break # Break inner loop on success
            except FloodWaitError as e:
                wait_time = e.seconds + 10
                print(f"\n⚠️ FloodWaitError! Telegram rate limit hit.")
                print(f"Waiting {e.seconds}s + 10s buffer = {wait_time}s...")
                await asyncio.sleep(wait_time)
                print("Resuming...")
            except Exception as e:
                print(f"✗ Failed to leave '{title}': {str(e)}")
                break # Break inner loop on general failure, move to next chat
                
        # Random sleep between requests to avoid triggering rate limits
        if i < len(chats_to_leave):
            sleep_duration = random.uniform(5, 12)
            print(f"Sleeping for {sleep_duration:.2f}s before the next request...\n")
            await asyncio.sleep(sleep_duration)

    print("\n--------------------------------------------------")
    print("Finished processing all targeted chats.")

if __name__ == '__main__':
    asyncio.run(main())
