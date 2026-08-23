import os
import sys
import threading
import asyncio
import queue
import random
import customtkinter as ctk
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# Config
load_dotenv()
SESSION_NAME = 'telegram_bulk_session'

class TelegramWorker(threading.Thread):
    def __init__(self, command_queue, update_queue, api_id, api_hash):
        super().__init__(daemon=True)
        self.command_queue = command_queue
        self.update_queue = update_queue
        self.api_id = api_id
        self.api_hash = api_hash
        self.loop = asyncio.new_event_loop()
        self.client = None

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main_loop())

    async def main_loop(self):
        try:
            self.client = TelegramClient(SESSION_NAME, int(self.api_id), self.api_hash)
        except Exception as e:
            self.update_queue.put({'type': 'error', 'message': f"Init error: {e}"})
            return

        while True:
            cmd = await self.loop.run_in_executor(None, self.command_queue.get)
            if cmd['action'] == 'connect':
                await self.handle_connect()
            elif cmd['action'] == 'leave':
                await self.handle_leave(cmd['chats'])
            elif cmd['action'] == 'quit':
                if self.client:
                    await self.client.disconnect()
                break

    async def handle_connect(self):
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                self.update_queue.put({
                    'type': 'error', 
                    'message': 'Not authorized. Please run a basic terminal script first to login with your phone number.'
                })
                return
            
            chats = []
            async for dialog in self.client.iter_dialogs():
                if dialog.is_channel or dialog.is_group:
                    chats.append({
                        'id': dialog.entity.id,
                        'title': dialog.title,
                        'type': 'Supergroup' if getattr(dialog.entity, 'megagroup', False) else ('Channel' if dialog.is_channel else 'Group')
                    })
            self.update_queue.put({'type': 'chats_fetched', 'chats': chats})
        except Exception as e:
            self.update_queue.put({'type': 'error', 'message': str(e)})

    async def handle_leave(self, chats_to_leave):
        total = len(chats_to_leave)
        for i, chat in enumerate(chats_to_leave, 1):
            title = chat['title']
            chat_id = chat['id']
            while True:
                try:
                    self.update_queue.put({'type': 'log', 'message': f"[{i}/{total}] Leaving '{title}'..."})
                    await self.client.delete_dialog(chat_id)
                    self.update_queue.put({'type': 'log', 'message': f"  ✓ Successfully left."})
                    break
                except FloodWaitError as e:
                    wait_time = e.seconds + 10
                    self.update_queue.put({'type': 'log', 'message': f"  ⚠️ Rate limit hit. Waiting {wait_time}s..."})
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    self.update_queue.put({'type': 'log', 'message': f"  ✗ Error leaving: {e}"})
                    break
            
            self.update_queue.put({'type': 'progress', 'value': i / total})
            
            if i < total:
                sleep_dur = random.uniform(5, 12)
                self.update_queue.put({'type': 'log', 'message': f"  Sleeping {sleep_dur:.1f}s before next request...\n"})
                await asyncio.sleep(sleep_dur)
                
        self.update_queue.put({'type': 'done'})


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Bulk Leave Manager")
        self.geometry("900x700")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.command_queue = queue.Queue()
        self.update_queue = queue.Queue()
        self.worker = None
        self.chats = []
        self.chat_vars = {}
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.setup_ui()
        self.check_queue()

    def setup_ui(self):
        # TOP FRAME (Settings)
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        
        lbl_title = ctk.CTkLabel(self.top_frame, text="Global Default Action:", font=ctk.CTkFont(size=14, weight="bold"))
        lbl_title.pack(side="left", padx=10, pady=10)

        self.default_action_var = ctk.StringVar(value="LEAVE")
        self.seg_button = ctk.CTkSegmentedButton(self.top_frame, values=["LEAVE ALL", "KEEP ALL"], 
                                                 command=self.change_default, 
                                                 variable=self.default_action_var)
        self.seg_button.pack(side="left", padx=10, pady=10)
        self.seg_button.set("LEAVE ALL")
        
        self.connect_btn = ctk.CTkButton(self.top_frame, text="Connect & Fetch Chats", font=ctk.CTkFont(weight="bold"), command=self.start_connect)
        self.connect_btn.pack(side="right", padx=10, pady=10)

        # MIDDLE FRAME (Scrollable Table)
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="Channels & Groups Triage")
        self.scroll_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        # BOTTOM FRAME (Execution & Logs)
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=2, column=0, padx=20, pady=(10, 20), sticky="ew")
        
        self.progress = ctk.CTkProgressBar(self.bottom_frame)
        self.progress.pack(fill="x", padx=15, pady=(15, 5))
        self.progress.set(0)
        
        self.logbox = ctk.CTkTextbox(self.bottom_frame, height=120)
        self.logbox.pack(fill="x", padx=15, pady=5)
        
        self.exec_btn = ctk.CTkButton(self.bottom_frame, text="Confirm & Execute Removal", 
                                      fg_color="#C21807", hover_color="#8B0000", font=ctk.CTkFont(weight="bold"),
                                      state="disabled", command=self.confirm_execution)
        self.exec_btn.pack(pady=10)

        self.init_worker()

    def init_worker(self):
        self.api_id = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        
        if self.api_id and self.api_hash:
            self.worker = TelegramWorker(self.command_queue, self.update_queue, self.api_id, self.api_hash)
            self.worker.start()
            self.log("System Ready. Click 'Connect & Fetch Chats' to begin.")
            self.log("Ensure you have set up your API credentials in the .env file.")
        else:
            self.log("CRITICAL ERROR: API_ID or API_HASH missing from .env file.")
            self.connect_btn.configure(state="disabled")

    def log(self, msg):
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")

    def change_default(self, value):
        new_val = value.split(" ")[0] # Extracts 'LEAVE' or 'KEEP'
        for var in self.chat_vars.values():
            var.set(new_val)

    def start_connect(self):
        self.connect_btn.configure(state="disabled")
        self.seg_button.configure(state="disabled")
        self.log("\nConnecting to Telegram and fetching dialogs (this may take a moment)...")
        self.command_queue.put({'action': 'connect'})

    def render_chats(self):
        # Clear existing
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        default_val = self.seg_button.get().split(" ")[0]
        
        for idx, chat in enumerate(self.chats):
            frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            frame.pack(fill="x", padx=5, pady=2)
            
            lbl = ctk.CTkLabel(frame, text=f"{chat['title']} ({chat['type']})")
            lbl.pack(side="left", padx=10, pady=2)
            
            var = ctk.StringVar(value=default_val)
            self.chat_vars[chat['id']] = var
            
            # Using a SegmentedButton as a sleek toggle switch for Keep/Leave
            switch = ctk.CTkSegmentedButton(frame, values=["LEAVE", "KEEP"], variable=var)
            switch.pack(side="right", padx=10, pady=2)
            
        self.exec_btn.configure(state="normal")
        self.seg_button.configure(state="normal")
        self.log(f"Successfully fetched {len(self.chats)} channels/groups.")

    def confirm_execution(self):
        chats_to_leave = []
        for chat in self.chats:
            if self.chat_vars[chat['id']].get() == 'LEAVE':
                chats_to_leave.append(chat)
                
        if not chats_to_leave:
            self.log("\nNo chats selected to leave! Aborting.")
            return
            
        # Confirmation Guardrail Popup
        dialog = ctk.CTkToplevel(self)
        dialog.title("Confirm Removal")
        dialog.geometry("450x200")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        
        lbl = ctk.CTkLabel(dialog, text=f"WARNING: You are about to permanently leave {len(chats_to_leave)} chats.\n\nAre you absolutely sure you want to proceed?", font=ctk.CTkFont(weight="bold"))
        lbl.pack(pady=40, padx=20)
        
        def execute():
            dialog.destroy()
            self.exec_btn.configure(state="disabled")
            self.seg_button.configure(state="disabled")
            self.connect_btn.configure(state="disabled")
            for w in self.scroll_frame.winfo_children():
                for child in w.winfo_children():
                    if isinstance(child, ctk.CTkSegmentedButton):
                        child.configure(state="disabled")
            self.log("\nStarting removal process...")
            self.command_queue.put({'action': 'leave', 'chats': chats_to_leave})
            
        btn = ctk.CTkButton(dialog, text="Yes, Execute Removal", fg_color="#C21807", hover_color="#8B0000", command=execute)
        btn.pack()

    def check_queue(self):
        try:
            while True:
                msg = self.update_queue.get_nowait()
                if msg['type'] == 'log':
                    self.log(msg['message'])
                elif msg['type'] == 'error':
                    self.log(f"\nERROR: {msg['message']}")
                    self.connect_btn.configure(state="normal")
                    self.seg_button.configure(state="normal")
                elif msg['type'] == 'chats_fetched':
                    self.chats = msg['chats']
                    self.render_chats()
                elif msg['type'] == 'progress':
                    self.progress.set(msg['value'])
                elif msg['type'] == 'done':
                    self.log("\nProcess complete!")
                    self.progress.set(1)
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def on_closing(self):
        self.command_queue.put({'action': 'quit'})
        self.destroy()

if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
