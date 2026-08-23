import os
import csv
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient

# Load environment variables
load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
SESSION_NAME = 'telegram_bulk_session'
DEFAULT_ACTION = os.getenv('DEFAULT_ACTION', 'LEAVE').strip().upper()

async def main():
    if not API_ID or not API_HASH:
        print("Error: API_ID or API_HASH not found in .env file.")
        print("Please copy .env.example to .env and fill in your credentials.")
        return

    # Initialize client
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
    
    print("Starting Telethon client...")
    # The client will prompt for phone number and 2FA via the console if it's the first time
    await client.start()
    print("Client successfully authenticated!")

    chats_data = []
    print("Scanning dialogs...")
    
    async for dialog in client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            entity = dialog.entity
            chat_id = entity.id
            title = dialog.title
            
            # Determine type (Supergroup, Channel, Group)
            if getattr(entity, 'megagroup', False):
                chat_type = 'Supergroup'
            elif dialog.is_channel:
                chat_type = 'Channel'
            else:
                chat_type = 'Group'
            
            # Try to get username if it exists (public channels/groups)
            username = getattr(entity, 'username', '') or ''
            
            chats_data.append({
                'id': chat_id,
                'title': title,
                'username': username,
                'type': chat_type,
                'action': DEFAULT_ACTION
            })

    # Export to CSV
    csv_filename = 'telegram_chats_triage.csv'
    fieldnames = ['id', 'title', 'username', 'type', 'action']
    
    with open(csv_filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(chats_data)
        
    print(f"\nExport complete. Found {len(chats_data)} channels/groups.")
    print(f"Please check '{csv_filename}' and change 'action' to 'KEEP' for chats you want to retain.")

if __name__ == '__main__':
    asyncio.run(main())
