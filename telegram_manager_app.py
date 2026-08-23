import os
import time
import threading
import asyncio
import queue
import random
import customtkinter as ctk
from dotenv import load_dotenv, set_key
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# Config
ENV_FILE = '.env'
load_dotenv(ENV_FILE)
SESSION_NAME = 'telegram_bulk_session'

class TelegramWorker(threading.Thread):
    def __init__(self, command_queue, update_queue):
        super().__init__(daemon=True)
        self.command_queue = command_queue
        self.update_queue = update_queue
        self.loop = asyncio.new_event_loop()
        self.client = None
        self.phone = None
        self.phone_code_hash = None
        self.cancel_flag = False

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main_loop())

    async def main_loop(self):
        # Auto-connect if API keys exist
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        if api_id and api_hash:
            await self.init_client(api_id, api_hash)
            
        while True:
            cmd = await self.loop.run_in_executor(None, self.command_queue.get)
            action = cmd.get('action')
            
            if action == 'init_client':
                await self.init_client(cmd['api_id'], cmd['api_hash'])
            
            elif action == 'send_code':
                self.phone = cmd['phone']
                try:
                    result = await self.client.send_code_request(self.phone)
                    self.phone_code_hash = result.phone_code_hash
                    self.update_queue.put({'type': 'code_sent'})
                except Exception as e:
                    self.update_queue.put({'type': 'auth_error', 'message': str(e)})

            elif action == 'submit_code':
                try:
                    await self.client.sign_in(self.phone, cmd['code'], phone_code_hash=self.phone_code_hash)
                    self.update_queue.put({'type': 'auth_success'})
                except SessionPasswordNeededError:
                    self.update_queue.put({'type': '2fa_needed'})
                except Exception as e:
                    self.update_queue.put({'type': 'auth_error', 'message': str(e)})
                    
            elif action == 'submit_2fa':
                try:
                    await self.client.sign_in(password=cmd['password'])
                    self.update_queue.put({'type': 'auth_success'})
                except Exception as e:
                    self.update_queue.put({'type': 'auth_error', 'message': str(e)})
                    
            elif action == 'logout':
                try:
                    if self.client:
                        await self.client.log_out()
                    self.update_queue.put({'type': 'logged_out'})
                except Exception as e:
                    self.update_queue.put({'type': 'error', 'message': str(e)})
                    
            elif action == 'fetch_chats':
                try:
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

            elif action == 'leave_chats':
                await self.handle_leave(cmd['chats'])
                
            elif action == 'quit':
                if self.client:
                    await self.client.disconnect()
                break

    async def init_client(self, api_id, api_hash):
        try:
            if self.client:
                await self.client.disconnect()
                
            self.client = TelegramClient(SESSION_NAME, int(api_id), api_hash)
            await self.client.connect()
            
            if await self.client.is_user_authorized():
                self.update_queue.put({'type': 'auth_success'})
            else:
                self.update_queue.put({'type': 'auth_needed'})
        except Exception as e:
            self.update_queue.put({'type': 'error', 'message': f"Init error: {e}"})

    async def handle_leave(self, chats_to_leave):
        total = len(chats_to_leave)
        for i, chat in enumerate(chats_to_leave, 1):
            if self.cancel_flag:
                self.update_queue.put({'type': 'log', 'message': f"\n⚠️ EMERGENCY STOP TRIGGERED. Aborted."})
                break
                
            title = chat['title']
            chat_id = chat['id']
            while True:
                if self.cancel_flag:
                    break
                    
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
            
            if self.cancel_flag:
                break
                
            self.update_queue.put({'type': 'progress', 'value': i / total})
            if i < total:
                sleep_dur = random.uniform(5, 12)
                self.update_queue.put({'type': 'log', 'message': f"  Sleeping {sleep_dur:.1f}s...\n"})
                await asyncio.sleep(sleep_dur)
                
        self.update_queue.put({'type': 'done'})


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Bulk Leave Manager")
        self.geometry("900x750")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.command_queue = queue.Queue()
        self.update_queue = queue.Queue()
        self.chats = []
        self.filtered_chats = []
        self.chat_vars = {}
        self.login_modal = None
        self.timer_running = False
        self.start_time = 0
        
        self.worker = TelegramWorker(self.command_queue, self.update_queue)
        self.worker.start()

        self.build_ui()
        self.check_queue()
        self.set_ui_state("disconnected")

    def build_ui(self):
        # TOP FRAME (Header & Auth)
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=25, pady=(20, 5))
        
        self.status_dot = ctk.CTkLabel(header_frame, text="●", font=ctk.CTkFont(size=20), text_color="red")
        self.status_dot.pack(side="left", padx=(0,5))
        self.status_lbl = ctk.CTkLabel(header_frame, text="Disconnected", font=ctk.CTkFont(weight="bold"))
        self.status_lbl.pack(side="left")
        
        self.auth_btn = ctk.CTkButton(header_frame, text="Login", width=120, command=self.handle_auth_click)
        self.auth_btn.pack(side="right")

        # CONTROLS FRAME
        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=20, pady=10)
        
        # Default action set to KEEP
        self.default_action_var = ctk.StringVar(value="KEEP")
        self.seg_button = ctk.CTkSegmentedButton(ctrl_frame, values=["LEAVE ALL", "KEEP ALL"], 
                                                 command=self.change_default, 
                                                 variable=self.default_action_var)
        self.seg_button.pack(side="left", padx=5)
        self.seg_button.set("KEEP ALL")
        
        self.search_entry = ctk.CTkEntry(ctrl_frame, placeholder_text="Search chats...", width=250)
        self.search_entry.pack(side="left", padx=20)
        self.search_entry.bind("<KeyRelease>", self.filter_chats)
        
        self.fetch_btn = ctk.CTkButton(ctrl_frame, text="Fetch Chats", width=120, command=self.do_fetch)
        self.fetch_btn.pack(side="right", padx=5)

        # SCROLLABLE TABLE
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="Channels & Groups")
        self.scroll_frame.pack(fill="both", expand=True, padx=25, pady=5)

        # BOTTOM FRAME (Execution & Logs)
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=25, pady=(10, 20))
        
        prog_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        prog_frame.pack(fill="x", pady=5)
        
        self.time_lbl = ctk.CTkLabel(prog_frame, text="Elapsed: 00:00", text_color="gray")
        self.time_lbl.pack(side="right")
        
        self.progress = ctk.CTkProgressBar(prog_frame)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 20))
        self.progress.set(0)
        
        self.logbox = ctk.CTkTextbox(bottom_frame, height=120)
        self.logbox.pack(fill="x", pady=10)
        
        # Buttons container for execution
        self.btn_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        self.btn_frame.pack(pady=5)
        
        self.exec_btn = ctk.CTkButton(self.btn_frame, text="Confirm & Execute Removal", 
                                      fg_color="#C21807", hover_color="#8B0000", font=ctk.CTkFont(weight="bold"),
                                      width=250, height=40, command=self.confirm_execution)
        self.exec_btn.pack()
        
        self.stop_btn = ctk.CTkButton(self.btn_frame, text="EMERGENCY STOP", 
                                      fg_color="#F39C12", hover_color="#D68910", font=ctk.CTkFont(weight="bold"),
                                      text_color="black", width=250, height=40, command=self.emergency_stop)

    def set_ui_state(self, state):
        if state == "disconnected":
            self.status_dot.configure(text_color="#E74C3C")
            self.status_lbl.configure(text="Disconnected", text_color="gray")
            self.auth_btn.configure(text="Login", fg_color=["#3B8ED0", "#1F6AA5"], hover_color=["#36719F", "#144870"])
            self.fetch_btn.configure(state="disabled")
            self.seg_button.configure(state="disabled")
            self.search_entry.configure(state="disabled")
            self.exec_btn.configure(state="disabled")
            for widget in self.scroll_frame.winfo_children():
                widget.destroy()
            self.chats = []
            self.filtered_chats = []
            self.chat_vars = {}
            self.progress.set(0)
            
        elif state == "connected":
            self.status_dot.configure(text_color="#2ECC71")
            self.status_lbl.configure(text="Connected", text_color="#2ECC71")
            self.auth_btn.configure(text="Logout", fg_color="#C21807", hover_color="#8B0000")
            self.fetch_btn.configure(state="normal")
            self.seg_button.configure(state="normal")
            self.search_entry.configure(state="normal")
            if self.login_modal:
                self.login_modal.destroy()
                self.login_modal = None
                
        elif state == "connecting":
            self.status_dot.configure(text_color="#F1C40F")
            self.status_lbl.configure(text="Connecting...", text_color="#F1C40F")

    def handle_auth_click(self):
        if self.auth_btn.cget("text") == "Logout":
            self.set_ui_state("disconnected")
            self.log("Logging out and destroying session...")
            self.command_queue.put({'action': 'logout'})
        else:
            self.open_login_modal()

    def open_login_modal(self):
        if self.login_modal:
            self.login_modal.destroy()
            
        self.login_modal = ctk.CTkToplevel(self)
        self.login_modal.title("Telegram Authentication")
        self.login_modal.geometry("420x520")
        self.login_modal.attributes("-topmost", True)
        self.login_modal.resizable(False, False)
        
        self.modal_container = ctk.CTkFrame(self.login_modal, fg_color="transparent")
        self.modal_container.pack(fill="both", expand=True, padx=30, pady=30)
        
        self.render_api_setup_view()

    def render_api_setup_view(self):
        for widget in self.modal_container.winfo_children():
            widget.destroy()
            
        lbl = ctk.CTkLabel(self.modal_container, text="API Setup", font=ctk.CTkFont(size=22, weight="bold"))
        lbl.pack(pady=(20, 15))
        
        self.api_id_entry = ctk.CTkEntry(self.modal_container, placeholder_text="API ID")
        self.api_id_entry.pack(fill="x", pady=10)
        
        self.api_hash_entry = ctk.CTkEntry(self.modal_container, placeholder_text="API HASH")
        self.api_hash_entry.pack(fill="x", pady=10)
        
        self.rem_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.modal_container, text="Save to .env", variable=self.rem_var).pack(pady=15)
        
        self.modal_btn = ctk.CTkButton(self.modal_container, text="Connect", height=35, command=self.submit_api_keys)
        self.modal_btn.pack(pady=20, fill="x")
        
        self.modal_err = ctk.CTkLabel(self.modal_container, text="", text_color="#E74C3C")
        self.modal_err.pack()
        
        if os.getenv('API_ID'):
            self.api_id_entry.insert(0, os.getenv('API_ID'))
        if os.getenv('API_HASH'):
            self.api_hash_entry.insert(0, os.getenv('API_HASH'))

    def submit_api_keys(self):
        api_id = self.api_id_entry.get().strip()
        api_hash = self.api_hash_entry.get().strip()
        if not api_id or not api_hash:
            self.modal_err.configure(text="Missing API_ID or API_HASH")
            return
            
        if self.rem_var.get():
            if not os.path.exists(ENV_FILE): open(ENV_FILE, 'w').close()
            set_key(ENV_FILE, 'API_ID', api_id)
            set_key(ENV_FILE, 'API_HASH', api_hash)
            
        self.set_ui_state("connecting")
        self.modal_btn.configure(state="disabled", text="Connecting...")
        self.command_queue.put({'action': 'init_client', 'api_id': api_id, 'api_hash': api_hash})

    def render_auth_input_view(self, state, desc_text):
        for widget in self.modal_container.winfo_children():
            widget.destroy()
            
        self.auth_state = state
        
        lbl = ctk.CTkLabel(self.modal_container, text="Authentication", font=ctk.CTkFont(size=22, weight="bold"))
        lbl.pack(pady=(20, 15))
        
        desc = ctk.CTkLabel(self.modal_container, text=desc_text, wraplength=350)
        desc.pack(pady=15)
        
        self.auth_entry = ctk.CTkEntry(self.modal_container)
        self.auth_entry.pack(fill="x", pady=10)
        if state == "2fa":
            self.auth_entry.configure(show="*")
            
        self.modal_btn = ctk.CTkButton(self.modal_container, text="Submit", height=35, command=self.submit_auth_step)
        self.modal_btn.pack(pady=20, fill="x")
        
        self.modal_err = ctk.CTkLabel(self.modal_container, text="", text_color="#E74C3C")
        self.modal_err.pack()

    def submit_auth_step(self):
        val = self.auth_entry.get().strip()
        if not val: return
        
        self.modal_btn.configure(state="disabled")
        if self.auth_state == "phone":
            self.command_queue.put({'action': 'send_code', 'phone': val})
        elif self.auth_state == "code":
            self.command_queue.put({'action': 'submit_code', 'code': val})
        elif self.auth_state == "2fa":
            self.command_queue.put({'action': 'submit_2fa', 'password': val})

    def change_default(self, value):
        new_val = value.split(" ")[0]
        for var in self.chat_vars.values():
            var.set(new_val)

    def do_fetch(self):
        self.fetch_btn.configure(state="disabled")
        self.log("\nFetching chats...")
        self.command_queue.put({'action': 'fetch_chats'})

    def filter_chats(self, event=None):
        query = self.search_entry.get().lower()
        self.filtered_chats = [c for c in self.chats if query in c['title'].lower()]
        self.render_chats()

    def render_chats(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        for chat in self.filtered_chats:
            frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            frame.pack(fill="x", padx=10, pady=2)
            
            lbl = ctk.CTkLabel(frame, text=f"{chat['title']} ({chat['type']})")
            lbl.pack(side="left", padx=10, pady=2)
            
            if chat['id'] not in self.chat_vars:
                self.chat_vars[chat['id']] = ctk.StringVar(value=self.default_action_var.get().split(" ")[0])
                
            switch = ctk.CTkSegmentedButton(frame, values=["LEAVE", "KEEP"], variable=self.chat_vars[chat['id']])
            switch.pack(side="right", padx=10, pady=2)
            
        self.exec_btn.configure(state="normal")
        self.fetch_btn.configure(state="normal")
        self.log(f"Displaying {len(self.filtered_chats)} chats.")

    def confirm_execution(self):
        chats_to_leave = [c for c in self.chats if self.chat_vars[c['id']].get() == 'LEAVE']
        if not chats_to_leave:
            self.log("\nNo chats selected to leave! Aborting.")
            return
            
        dialog = ctk.CTkToplevel(self)
        dialog.title("Confirm Removal")
        dialog.geometry("450x200")
        dialog.attributes("-topmost", True)
        
        lbl = ctk.CTkLabel(dialog, text=f"WARNING: You are about to permanently leave {len(chats_to_leave)} chats.\n\nAre you absolutely sure you want to proceed?", font=ctk.CTkFont(weight="bold"))
        lbl.pack(pady=40, padx=20)
        
        def execute():
            dialog.destroy()
            # UI Swap for Execution
            self.exec_btn.pack_forget()
            self.stop_btn.pack()
            self.fetch_btn.configure(state="disabled")
            self.seg_button.configure(state="disabled")
            for w in self.scroll_frame.winfo_children():
                for child in w.winfo_children():
                    if isinstance(child, ctk.CTkSegmentedButton):
                        child.configure(state="disabled")
                        
            self.log("\nStarting removal process...")
            self.worker.cancel_flag = False
            self.start_timer()
            self.command_queue.put({'action': 'leave_chats', 'chats': chats_to_leave})
            
        btn = ctk.CTkButton(dialog, text="Yes, Execute Removal", fg_color="#C21807", hover_color="#8B0000", height=35, command=execute)
        btn.pack()

    def emergency_stop(self):
        self.log("\nSending Emergency Stop signal... (Will abort after current wait cycle)")
        self.worker.cancel_flag = True
        self.stop_btn.configure(state="disabled", text="Stopping...")

    def start_timer(self):
        self.start_time = time.time()
        self.timer_running = True
        self.update_timer()
        
    def update_timer(self):
        if self.timer_running:
            elapsed = int(time.time() - self.start_time)
            mins, secs = divmod(elapsed, 60)
            self.time_lbl.configure(text=f"Elapsed: {mins:02d}:{secs:02d}")
            self.after(1000, self.update_timer)
            
    def stop_timer(self):
        self.timer_running = False

    def finish_execution(self):
        self.stop_timer()
        self.stop_btn.pack_forget()
        self.stop_btn.configure(state="normal", text="EMERGENCY STOP")
        self.exec_btn.pack()
        self.fetch_btn.configure(state="normal")
        self.seg_button.configure(state="normal")

    def log(self, msg):
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")

    def check_queue(self):
        try:
            while True:
                msg = self.update_queue.get_nowait()
                msg_type = msg['type']
                
                if msg_type == 'auth_success':
                    self.set_ui_state("connected")
                    self.log("Connected securely. Ready to fetch chats.")
                elif msg_type == 'auth_needed':
                    if not self.login_modal:
                        self.open_login_modal()
                    self.render_auth_input_view("phone", "Enter your Phone Number (incl. country code):")
                elif msg_type == 'code_sent':
                    self.render_auth_input_view("code", "Enter the Authentication Code sent to your Telegram app:")
                elif msg_type == '2fa_needed':
                    self.render_auth_input_view("2fa", "Enter your Two-Step Verification Password:")
                elif msg_type == 'auth_error':
                    if self.login_modal and self.modal_err.winfo_exists():
                        self.modal_err.configure(text=msg['message'])
                        if hasattr(self, 'modal_btn') and self.modal_btn.winfo_exists():
                            self.modal_btn.configure(state="normal", text="Connect")
                    self.set_ui_state("disconnected")
                elif msg_type == 'logged_out':
                    self.log("Successfully logged out.")
                elif msg_type == 'error':
                    self.log(f"ERROR: {msg['message']}")
                    if self.status_lbl.cget("text") == "Connected":
                        self.fetch_btn.configure(state="normal")
                elif msg_type == 'chats_fetched':
                    self.chats = msg['chats']
                    self.filtered_chats = self.chats
                    self.render_chats()
                elif msg_type == 'log':
                    self.log(msg['message'])
                elif msg_type == 'progress':
                    self.progress.set(msg['value'])
                elif msg_type == 'done':
                    self.log("\nProcess complete!")
                    self.progress.set(1)
                    self.finish_execution()
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
