import random
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import tempfile
import os
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import json

class InstagramReporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("IG Mass Report Tool v2.0 (Educational Use Only)")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        
        self.accounts = []  # Will store {user, proxy}; password is transient
        self.passwords = {}  # In-memory only: {username: password}
        self.results = []
        self.is_running = False
        
        self.setup_ui()
    
    def setup_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        accounts_frame = ttk.Frame(notebook)
        notebook.add(accounts_frame, text="Accounts")
        self.setup_accounts_tab(accounts_frame)
        
        settings_frame = ttk.Frame(notebook)
        notebook.add(settings_frame, text="Settings")
        self.setup_settings_tab(settings_frame)
        
        logs_frame = ttk.Frame(notebook)
        notebook.add(logs_frame, text="Logs")
        self.setup_logs_tab(logs_frame)
    
    def setup_accounts_tab(self, parent):
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(btn_frame, text="Load Accounts", command=self.load_accounts).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Save Accounts", command=self.save_accounts).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Add Account", command=self.add_account_row).pack(side=tk.LEFT)
        
        columns = ("#", "Username", "Proxy", "Status")
        self.accounts_tree = ttk.Treeview(parent, columns=columns, show="headings", height=15)
        
        for col in columns:
            self.accounts_tree.heading(col, text=col)
            self.accounts_tree.column(col, width=150)
        
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.accounts_tree.yview)
        self.accounts_tree.configure(yscrollcommand=scrollbar.set)
        self.accounts_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10)
        
        self.add_default_accounts()
    
    def setup_settings_tab(self, parent):
        ttk.Label(parent, text="Target Username:").pack(pady=5)
        self.target_var = tk.StringVar(value="your_target_account")
        ttk.Entry(parent, textvariable=self.target_var, width=50, font=("Arial", 12)).pack(pady=5)
        
        ttk.Label(parent, text="Delay between reports (seconds):").pack(pady=(20,5))
        self.delay_var = tk.DoubleVar(value=60)
        delay_scale = ttk.Scale(parent, from_=10, to=300, variable=self.delay_var, orient=tk.HORIZONTAL)
        delay_scale.pack(fill=tk.X, padx=20, pady=5)
        ttk.Label(parent, textvariable=self.delay_var).pack()
        
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=20)
        
        style = ttk.Style()
        style.configure("Accent.TButton", font=("Arial", 10, "bold"))
        ttk.Button(parent, text="START REPORTING", command=self.start_reporting,
                  style="Accent.TButton").pack(pady=20, ipadx=30, ipady=10)
    
    def setup_logs_tab(self, parent):
        self.log_text = scrolledtext.ScrolledText(parent, height=25, font=("Consolas", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    def _safe_log(self, message):
        """Call only from main thread"""
        self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.log_text.see(tk.END)
    
    def log(self, message):
        """Thread-safe logging"""
        self.root.after(0, self._safe_log, message)
    
    def add_default_accounts(self):
        defaults = [
            {"user": "burner1_test", "proxy": "127.0.0.1:8080"},
            {"user": "burner2_test", "proxy": "127.0.0.1:8080"}
        ]
        for acc in defaults:
            self.add_account_row(acc)
    
    def add_account_row(self, account=None):
        if account is None:
            account = {"user": "", "proxy": ""}
        item = self.accounts_tree.insert("", "end", values=(
            len(self.accounts)+1, account["user"], account["proxy"], "Ready"
        ))
        self.accounts.append(account)
        self.accounts_tree.selection_set(item)
    
    def load_accounts(self):
        try:
            with open("accounts.json", "r") as f:
                data = json.load(f)
                self.accounts = data
                self.accounts_tree.delete(*self.accounts_tree.get_children())
                for i, acc in enumerate(self.accounts):
                    self.accounts_tree.insert("", "end", values=(
                        i+1, acc["user"], acc["proxy"], "Ready"
                    ))
            self.log("✅ Accounts loaded from accounts.json")
        except FileNotFoundError:
            self.log("❌ No accounts.json found")
        except Exception as e:
            self.log(f"❌ Load failed: {e}")
    
    def save_accounts(self):
        try:
            # Rebuild accounts list from tree (without passwords)
            updated_accounts = []
            for item in self.accounts_tree.get_children():
                values = self.accounts_tree.item(item, "values")
                updated_accounts.append({
                    "user": values[1],
                    "proxy": values[2]
                })
            self.accounts = updated_accounts
            
            with open("accounts.json", "w") as f:
                json.dump(self.accounts, f, indent=2)
            self.log("💾 Accounts saved to accounts.json (passwords NOT saved)")
        except Exception as e:
            self.log(f"❌ Save failed: {e}")
    
    def create_stealth_driver(self, proxy_str):
        options = Options()
        options.add_argument("--headless=new")  # Modern headless
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Validate and set proxy
        if proxy_str and proxy_str.lower() != "direct":
            if re.match(r'^[\d.:]+$', proxy_str):  # Basic IP:PORT check
                options.add_argument(f"--proxy-server={proxy_str}")
            else:
                self.log(f"⚠️ Invalid proxy format: {proxy_str}. Using direct.")
        
        # Create isolated temp profile
        user_data_dir = tempfile.mkdtemp()
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument("--disable-extensions")
        
        ua_list = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]
        options.add_argument(f"--user-agent={random.choice(ua_list)}")
        
        try:
            driver = webdriver.Chrome(options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            return driver, user_data_dir
        except WebDriverException as e:
            self.log(f"❌ WebDriver init failed: {e}")
            return None, user_data_dir
    
    def login_and_report(self, account_idx, account, target, password):
        self.log(f"🚀 [{account_idx+1}] @{account['user']} starting...")
        
        driver = None
        temp_dir = None
        try:
            driver, temp_dir = self.create_stealth_driver(account["proxy"])
            if not driver:
                return False
            
            # === LOGIN ===
            driver.get("https://www.instagram.com/accounts/login/")
            time.sleep(random.uniform(3, 5))
            
            try:
                username_field = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "username"))
                )
                username_field.clear()
                username_field.send_keys(account["user"])
                
                password_field = driver.find_element(By.NAME, "password")
                password_field.clear()
                password_field.send_keys(password)
                driver.find_element(By.XPATH, "//button[@type='submit']").click()
                
                time.sleep(8)
                
                # Verify login success
                if "login" in driver.current_url or "challenge" in driver.current_url:
                    raise Exception("Login failed or checkpoint required")
                
            except Exception as e:
                raise Exception(f"Login failed: {str(e)}")
            
            # === NAVIGATE TO TARGET ===
            driver.get(f"https://www.instagram.com/{target}/")
            time.sleep(random.uniform(4, 6))
            
            # Check if target exists
            if "Page Not Found" in driver.title or "Sorry" in driver.page_source:
                raise Exception("Target account not found")
            
            # === REPORT FLOW ===
            more_btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label, 'More options') or contains(@aria-label, 'options')]"))
            )
            more_btn.click()
            
            report_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Report') or @data-testid='report']"))
            )
            report_btn.click()
            
            spam_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Spam') or contains(text(), 'It's spam')]"))
            )
            spam_btn.click()
            
            sub_reason = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Spam') or contains(text(), 'Scam')]"))
            )
            sub_reason.click()
            
            submit_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Submit') or contains(text(), 'Send')]"))
            )
            submit_btn.click()
            
            self.log(f"✅ [{account_idx+1}] @{account['user']} → SUCCESS")
            self.root.after(0, lambda: self.update_status(account_idx, "✅ SUCCESS"))
            return True
            
        except Exception as e:
            self.log(f"❌ [{account_idx+1}] FAILED: {str(e)[:100]}")
            self.root.after(0, lambda: self.update_status(account_idx, "❌ FAILED"))
            return False
        
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
            if temp_dir and os.path.exists(temp_dir):
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass
    
    def update_status(self, idx, status):
        children = self.accounts_tree.get_children()
        if idx < len(children):
            item = children[idx]
            values = list(self.accounts_tree.item(item, "values"))
            values[-1] = status
            self.accounts_tree.item(item, values=values)
    
    def start_reporting(self):
        if self.is_running:
            return
        
        target = self.target_var.get().strip().lstrip('@')
        if not target:
            messagebox.showerror("Error", "Enter target username!")
            return
        if not re.match(r"^[a-zA-Z0-9._]{1,30}$", target):
            messagebox.showerror("Error", "Invalid Instagram username!")
            return
        
        # Prompt for passwords if not already entered
        missing_passwords = []
        for acc in self.accounts:
            if acc["user"] not in self.passwords:
                missing_passwords.append(acc["user"])
        
        if missing_passwords:
            # Simple password prompt (in real app, use secure dialog)
            for user in missing_passwords:
                pwd = tk.simpledialog.askstring("Password", f"Enter password for @{user}:", show='*')
                if pwd is None:
                    self.log("🛑 Reporting cancelled by user")
                    return
                self.passwords[user] = pwd
        
        self.is_running = True
        self.results = []
        self.log(f"🎯 Starting {len(self.accounts)} reports on @{target}")
        
        def run_reports():
            for i, account in enumerate(self.accounts):
                if not self.is_running:
                    break
                
                pwd = self.passwords.get(account["user"], "")
                if not pwd:
                    self.log(f"❌ [{i+1}] No password for @{account['user']}")
                    self.root.after(0, lambda idx=i: self.update_status(idx, "❌ NO PASSWORD"))
                    self.results.append(False)
                    continue
                
                success = self.login_and_report(i, account, target, pwd)
                self.results.append(success)
                
                if i < len(self.accounts) - 1:
                    delay = self.delay_var.get()
                    self.log(f"⏳ Waiting {delay:.0f}s before next...")
                    time.sleep(delay)
            
            total = len(self.accounts)
            success_count = sum(self.results)
            self.log(f"📊 FINAL: {success_count}/{total} SUCCESS ({success_count/total*100:.1f}%)")
            self.root.after(0, self.reporting_complete)
        
        threading.Thread(target=run_reports, daemon=True).start()
    
    def reporting_complete(self):
        self.is_running = False
        messagebox.showinfo("Complete", f"Reports finished!\n{sum(self.results)}/{len(self.accounts)} successful")

def main():
    root = tk.Tk()
    app = InstagramReporterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
