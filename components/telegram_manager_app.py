import os
import sys
import time
import threading
import asyncio
import queue
import random
import ctypes
import customtkinter as ctk

# Single Instance Lock
mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "TelegramBulkLeaveManager_Mutex")
if ctypes.windll.kernel32.GetLastError() == 183:
    sys.exit(0)
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
                    await self.send_auth_success()
                except SessionPasswordNeededError:
                    self.update_queue.put({'type': '2fa_needed'})
                except Exception as e:
                    self.update_queue.put({'type': 'auth_error', 'message': str(e)})
                    
            elif action == 'submit_2fa':
                try:
                    await self.client.sign_in(password=cmd['password'])
                    await self.send_auth_success()
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
                await self.handle_fetch()

            elif action == 'leave_chats':
                await self.handle_leave(cmd)
                
            elif action == 'quit':
                if self.client:
                    await self.client.disconnect()
                break

    async def handle_fetch(self):
        try:
            self.update_queue.put({'type': 'log', 'message': "Fetching dialogs (this might take a moment)..."})
            dialogs = await self.client.get_dialogs()
            
            folder_map = {}
            try:
                from telethon.tl.functions.messages import GetDialogFiltersRequest
                import telethon.utils
                filters = await self.client(GetDialogFiltersRequest())
                for f in filters.filters:
                    if hasattr(f, 'title') and hasattr(f, 'include_peers'):
                        for peer in f.include_peers:
                            peer_id = telethon.utils.get_peer_id(peer)
                            if peer_id not in folder_map:
                                folder_map[peer_id] = []
                            folder_map[peer_id].append(f.title)
            except Exception as e:
                self.update_queue.put({'type': 'log', 'message': f"Note: Could not fetch folders ({e})"})
            
            chats = []
            for d in dialogs:
                if getattr(d.entity, 'bot', False):
                    ctype = "Bot"
                elif d.is_group or d.is_channel:
                    ctype = "Channel" if d.is_channel else "Group"
                else:
                    continue
                    
                chats.append({
                    'id': d.id,
                    'title': d.title,
                    'type': ctype,
                    'folders': folder_map.get(d.id, []),
                    'is_creator': getattr(d.entity, 'creator', False)
                })
                    
            self.update_queue.put({'type': 'chats_fetched', 'chats': chats})
        except Exception as e:
            self.update_queue.put({'type': 'error', 'message': f"Fetch error: {str(e)}"})

    async def init_client(self, api_id, api_hash):
        try:
            if self.client:
                await self.client.disconnect()
                
            self.client = TelegramClient(SESSION_NAME, int(api_id), api_hash)
            await self.client.connect()
            
            if await self.client.is_user_authorized():
                await self.send_auth_success()
            else:
                self.update_queue.put({'type': 'auth_needed'})
        except Exception as e:
            self.update_queue.put({'type': 'error', 'message': f"Init error: {e}"})

    async def send_auth_success(self):
        me = await self.client.get_me()
        name = me.username if me.username else (me.first_name or "User")
        self.update_queue.put({'type': 'auth_success', 'user': name})

    async def handle_leave(self, cmd):
        chats_to_leave = cmd['chats']
        bot_action = cmd.get('bot_action', 'BLOCK & DELETE')
        total = len(chats_to_leave)
        for i, chat in enumerate(chats_to_leave, 1):
            if self.cancel_flag:
                self.update_queue.put({'type': 'log', 'message': f"\n⚠️ EMERGENCY STOP TRIGGERED. Aborted."})
                break
                
            title = chat['title']
            chat_id = chat['id']
            ctype = chat['type']
            while True:
                if self.cancel_flag:
                    break
                    
                try:
                    if ctype == "Bot":
                        self.update_queue.put({'type': 'log', 'message': f"[{i}/{total}] Processing Bot '{title}'..."})
                        if bot_action == 'BLOCK & DELETE':
                            from telethon.tl.functions.contacts import BlockRequest
                            await self.client(BlockRequest(id=chat_id))
                            self.update_queue.put({'type': 'log', 'message': f"  ✓ Bot blocked."})
                        await self.client.delete_dialog(chat_id)
                        self.update_queue.put({'type': 'log', 'message': f"  ✓ History deleted."})
                    else:
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
                sleep_dur = random.uniform(1.5, 3.5)
                self.update_queue.put({'type': 'log', 'message': f"  Sleeping {sleep_dur:.1f}s...\n"})
                await asyncio.sleep(sleep_dur)
                
        self.update_queue.put({'type': 'done'})


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Bulk Leave Manager")
        self.geometry("900x750")
        self.minsize(700, 500)
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
        self.search_job = None
        self.render_job = None
        self.render_index = 0
        
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
        self.default_action_var = ctk.StringVar(value="KEEP ALL")
        self.seg_button = ctk.CTkSegmentedButton(ctrl_frame, values=["LEAVE ALL", "KEEP ALL"], 
                                                 command=self.update_all, 
                                                 variable=self.default_action_var)
        self.seg_button.pack(side="left", padx=5)
        self.seg_button.set("KEEP ALL")
        
        self.protect_folders_var = ctk.BooleanVar(value=True)
        self.folder_switch = ctk.CTkSwitch(ctrl_frame, text="Protect folders", variable=self.protect_folders_var, command=self.update_all)
        self.folder_switch.pack(side="left", padx=10)
        
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
        
        lbl = ctk.CTkLabel(self.btn_frame, text="Action for Bots:", text_color="gray", font=ctk.CTkFont(weight="bold"))
        lbl.pack(side="left", padx=5)
        
        self.bot_action_var = ctk.StringVar(value="BLOCK & DELETE")
        self.bot_seg_button = ctk.CTkSegmentedButton(self.btn_frame, values=["JUST DELETE", "BLOCK & DELETE"], variable=self.bot_action_var)
        self.bot_seg_button.pack(side="left", padx=(0, 20))
        
        self.exec_btn = ctk.CTkButton(self.btn_frame, text="Confirm & Execute Removal", 
                                      fg_color="#C21807", hover_color="#8B0000", font=ctk.CTkFont(weight="bold"),
                                      width=250, height=40, command=self.confirm_execution)
        self.exec_btn.pack(side="left")
        
        self.stop_btn = ctk.CTkButton(self.btn_frame, text="EMERGENCY STOP", 
                                      fg_color="#F39C12", hover_color="#D68910", font=ctk.CTkFont(weight="bold"),
                                      text_color="black", width=250, height=40, command=self.emergency_stop)

        self.refresh_btn = ctk.CTkButton(self.btn_frame, text="Finish & Refresh", 
                                      fg_color="#2ECC71", hover_color="#27AE60", font=ctk.CTkFont(weight="bold"),
                                      text_color="black", width=250, height=40, command=self.do_fetch)

    def set_ui_state(self, state, username=""):
        if state == "disconnected":
            self.status_dot.configure(text_color="#E74C3C")
            self.status_lbl.configure(text="Disconnected", text_color="gray")
            self.auth_btn.configure(text="Login", fg_color=["#3B8ED0", "#1F6AA5"], hover_color=["#36719F", "#144870"])
            self.fetch_btn.configure(state="disabled")
            self.seg_button.configure(state="disabled")
            self.bot_seg_button.configure(state="disabled")
            self.folder_switch.configure(state="disabled")
            self.search_entry.configure(state="disabled")
            self.exec_btn.configure(state="disabled")
            for widget in self.scroll_frame.winfo_children():
                widget.destroy()
            self.chats = []
            self.filtered_chats = []
            self.chat_vars = {}
            self.reset_dashboard()
            
        elif state == "connected":
            self.status_dot.configure(text_color="#2ECC71")
            display_text = f"Connected as @{username}" if username else "Connected"
            self.status_lbl.configure(text=display_text, text_color="#2ECC71")
            self.auth_btn.configure(text="Logout", fg_color="#C21807", hover_color="#8B0000")
            self.fetch_btn.configure(state="normal")
            self.seg_button.configure(state="normal")
            self.bot_seg_button.configure(state="normal")
            self.folder_switch.configure(state="normal")
            self.search_entry.configure(state="normal")
            if self.login_modal:
                self.login_modal.destroy()
                self.login_modal = None
                
        elif state == "connecting":
            self.status_dot.configure(text_color="#F1C40F")
            self.status_lbl.configure(text="Connecting...", text_color="#F1C40F")

    def handle_auth_click(self):
        if self.auth_btn.cget("text") == "Logout":
            dialog = ctk.CTkToplevel(self)
            dialog.title("Confirm Logout")
            dialog.geometry("300x150")
            dialog.attributes("-topmost", True)
            dialog.grab_set()
            dialog.focus()
            
            lbl = ctk.CTkLabel(dialog, text="Are you sure you want to logout?\nYou will need your phone to log back in.")
            lbl.pack(pady=20, padx=20)
            
            def confirm():
                dialog.destroy()
                self.set_ui_state("disconnected")
                self.log("Logging out and destroying session...")
                self.command_queue.put({'action': 'logout'})
                
            btn = ctk.CTkButton(dialog, text="Logout", fg_color="#C21807", hover_color="#8B0000", command=confirm)
            btn.pack()
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
        self.login_modal.grab_set()
        self.login_modal.focus()
        
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

    def update_all(self, *args):
        default_val = self.default_action_var.get().split(" ")[0]
        protect = self.protect_folders_var.get()
        
        for chat in self.chats:
            chat_id = chat['id']
            if chat_id in self.chat_vars:
                if chat.get('is_creator'):
                    self.chat_vars[chat_id].set("KEEP")
                elif protect and chat.get('folders'):
                    self.chat_vars[chat_id].set("KEEP")
                else:
                    self.chat_vars[chat_id].set(default_val)

    def do_fetch(self):
        self.reset_dashboard()
        self.fetch_btn.configure(state="disabled")
        self.log("\nFetching chats...")
        self.command_queue.put({'action': 'fetch_chats'})
        
    def reset_dashboard(self):
        self.progress.set(0)
        self.time_lbl.configure(text="Elapsed: 00:00")
        self.start_time = 0
        self.logbox.delete("0.0", "end")
        self.stop_btn.pack_forget()
        self.refresh_btn.pack_forget()
        self.exec_btn.pack(side="left")

    def filter_chats(self, event=None):
        if self.search_job:
            self.after_cancel(self.search_job)
        self.search_job = self.after(300, self._perform_filter)

    def _perform_filter(self):
        query = self.search_entry.get().lower()
        self.filtered_chats = [c for c in self.chats if query in c['title'].lower()]
        self.render_chats()

    def render_chats(self):
        if self.render_job:
            self.after_cancel(self.render_job)
            
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        self.render_index = 0
        self.render_chunk()

    def render_chunk(self):
        chunk_size = 40
        end_idx = min(self.render_index + chunk_size, len(self.filtered_chats))
        
        for i in range(self.render_index, end_idx):
            chat = self.filtered_chats[i]
            bg_color = "transparent" if i % 2 == 0 else ("#d9d9d9", "#3b3b3b")
            frame = ctk.CTkFrame(self.scroll_frame, fg_color=bg_color, corner_radius=5)
            frame.pack(fill="x", padx=10, pady=2)
            
            is_creator = chat.get('is_creator', False)
            
            title_text = chat['title']
            if len(title_text) > 40:
                title_text = title_text[:37] + "..."
                
            title_color = "gray" if is_creator else ("#D3D3D3" if ctk.get_appearance_mode() == "Dark" else "black")
            title_lbl = ctk.CTkLabel(frame, text=title_text, font=ctk.CTkFont(weight="bold"), text_color=title_color, width=330, anchor="w")
            title_lbl.pack(side="left", padx=(10, 5), pady=4)
            
            type_text = f"({chat['type']})"
            if is_creator:
                type_text = f"👑 {type_text}"
                
            type_lbl = ctk.CTkLabel(frame, text=type_text, text_color="gray", width=90, anchor="w")
            type_lbl.pack(side="left", padx=5, pady=4)
            
            if chat.get('folders'):
                folder_str = ", ".join(chat['folders'])
                if len(folder_str) > 25:
                    folder_str = folder_str[:22] + "..."
                folder_lbl = ctk.CTkLabel(frame, text=f"📁 [{folder_str}]", text_color="#F1C40F", width=200, anchor="w")
                folder_lbl.pack(side="left", padx=5, pady=4)
            else:
                empty_lbl = ctk.CTkLabel(frame, text="", width=200)
                empty_lbl.pack(side="left", padx=5, pady=4)
            
            if chat['id'] not in self.chat_vars:
                default_val = self.default_action_var.get().split(" ")[0]
                if is_creator:
                    default_val = "KEEP"
                elif self.protect_folders_var.get() and chat.get('folders'):
                    default_val = "KEEP"
                self.chat_vars[chat['id']] = ctk.StringVar(value=default_val)
                
            switch = ctk.CTkSegmentedButton(frame, values=["LEAVE", "KEEP"], variable=self.chat_vars[chat['id']])
            if is_creator:
                switch.configure(state="disabled")
            switch.pack(side="right", padx=10, pady=4)
            
        self.render_index = end_idx
        if self.render_index < len(self.filtered_chats):
            self.render_job = self.after(15, self.render_chunk)
        else:
            self.render_job = None
            self.exec_btn.configure(state="normal")
            self.fetch_btn.configure(state="normal")
            self.log(f"Displaying {len(self.filtered_chats)} chats.")

    def confirm_execution(self):
        chats_to_leave = [c for c in self.chats if self.chat_vars[c['id']].get() == 'LEAVE']
        if not chats_to_leave:
            self.log("\nNo chats selected to leave! Aborting.")
            return
            
        if len(chats_to_leave) > 500:
            err_dialog = ctk.CTkToplevel(self)
            err_dialog.title("Safety Limit Reached")
            err_dialog.geometry("450x150")
            err_dialog.attributes("-topmost", True)
            err_dialog.grab_set()
            err_dialog.focus()
            
            lbl = ctk.CTkLabel(err_dialog, text=f"To protect your Telegram account from anti-spam bans,\nyou can only leave a maximum of 500 chats per execution.\n\nYou selected {len(chats_to_leave)}. Please KEEP more chats.", font=ctk.CTkFont(weight="bold"))
            lbl.pack(pady=20, padx=20)
            btn = ctk.CTkButton(err_dialog, text="Understood", command=err_dialog.destroy)
            btn.pack()
            return
            
        dialog = ctk.CTkToplevel(self)
        dialog.title("Confirm Removal")
        dialog.geometry("450x200")
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.focus()
        
        lbl = ctk.CTkLabel(dialog, text=f"WARNING: You are about to permanently leave {len(chats_to_leave)} chats.\n\nAre you absolutely sure you want to proceed?", font=ctk.CTkFont(weight="bold"))
        lbl.pack(pady=40, padx=20)
        
        def execute():
            dialog.destroy()
            # UI Swap for Execution
            self.exec_btn.pack_forget()
            self.stop_btn.pack(side="left")
            self.fetch_btn.configure(state="disabled")
            self.seg_button.configure(state="disabled")
            self.bot_seg_button.configure(state="disabled")
            self.folder_switch.configure(state="disabled")
            self.log("\nStarting removal process...")
            self.worker.cancel_flag = False
            self.start_timer()
            self.command_queue.put({'action': 'leave_chats', 'chats': chats_to_leave, 'bot_action': self.bot_action_var.get()})
            
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
        self.refresh_btn.pack(side="left")
        self.fetch_btn.configure(state="normal")
        self.seg_button.configure(state="normal")
        self.bot_seg_button.configure(state="normal")
        self.folder_switch.configure(state="normal")

    def log(self, msg):
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")

    def check_queue(self):
        try:
            while True:
                msg = self.update_queue.get_nowait()
                msg_type = msg['type']
                
                if msg_type == 'auth_success':
                    user = msg.get('user', '')
                    self.set_ui_state("connected", user)
                    self.log(f"Connected securely as @{user}. Ready to fetch chats.")
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
