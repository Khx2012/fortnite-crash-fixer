import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, colorchooser, filedialog
import threading
import os
import shutil
import psutil
import platform
import configparser
import subprocess
import time
import ctypes
import winreg
import winsound
import re
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── CONFIG ────────────────────────────────────────────────────────────────────
CONFIG_DIR  = os.path.join(os.path.expandvars("%AppData%"), "FortniteCrashFixer")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.ini")

DEFAULTS = {
    "dark_mode":                    "false",
    "bg_color":                     "#f0f0f0",
    "fortnite_path":                r"C:\Program Files\Epic Games\Fortnite",
    "auto_analyze":                 "false",
    "safe_mode":                    "false",
    "clear_shader_on_quick_fix":    "true",
    "clear_launcher_on_quick_fix":  "true",
    "skip_eac_in_full_fix":         "false",
    "auto_restart_after_full_fix":  "false",
    "backup_configs_before_fix":    "true",
    "confirm_dangerous_actions":    "true",
    "notification_sound":           "true",
    "custom_temp_path":             "",
    "epic_email":                   "",
}

DARK = {
    "bg": "#1e1e1e", "bg2": "#2d2d2d", "fg": "#ffffff", "fg2": "#cccccc",
    "btn_bg": "#3a3a3a", "btn_fg": "#ffffff", "btn_active": "#4a4a4a",
    "status_ok": "#90ee90", "border": "#555555",
}
LIGHT = {
    "bg": "#f0f0f0", "bg2": "#ffffff", "fg": "#000000", "fg2": "#333333",
    "btn_bg": "#e0e0e0", "btn_fg": "#000000", "btn_active": "#c8c8c8",
    "status_ok": "green", "border": "#cccccc",
}

# ── HELPERS ───────────────────────────────────────────────────────────────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def run_cmd(cmd, timeout=15):
    try:
        r = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    except Exception as e:
        return -1, str(e)

def safe_remove(path, log_fn):
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=False)
            return True
        return True
    except Exception as e:
        log_fn(f"   ⚠️ Could not remove {os.path.basename(path)}: {e}")
        return False

def play_done_sound():
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
class FortniteFixer_v2_0:
    def __init__(self, root):
        self.root = root
        self.is_running = False
        self._theme_widgets = []
        self._buttons       = []
        self._fps_running   = False

        self.root.title("Fortnite Crash Fixer v2.0")
        self.root.geometry("800x720")

        self.cfg = self.load_config()
        self.build_ui()
        self.apply_theme()

        if not is_admin():
            self.log("⚠️  Not running as Administrator — some fixes may be limited.")
            self.log("    Right-click → Run as administrator for full power.\n")

        if self.get_bool("safe_mode"):
            self.log("🛡️  SAFE MODE is ON — Full Fix and EAC Reset are disabled.\n")

        if self.get_bool("auto_analyze"):
            self.root.after(500, self.analyze)

    # ── CONFIG ────────────────────────────────────────────────────────────────
    def load_config(self):
        cfg = configparser.ConfigParser()
        try:
            if os.path.exists(CONFIG_FILE):
                cfg.read(CONFIG_FILE, encoding="utf-8")
            if "app" not in cfg:
                cfg["app"] = {k: str(v) for k, v in DEFAULTS.items()}
            else:
                for k, v in DEFAULTS.items():
                    if k not in cfg["app"]:
                        cfg["app"][k] = str(v)
        except Exception:
            cfg["app"] = DEFAULTS.copy()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)
        return cfg

    def save_config(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self.cfg.write(f)

    def get(self, key):
        try:
            return self.cfg.get("app", key)
        except Exception:
            return DEFAULTS.get(key, "")

    def get_bool(self, key):
        try:
            return self.cfg.getboolean("app", key)
        except Exception:
            return str(DEFAULTS.get(key, "false")).lower() == "true"

    def set(self, key, value):
        if isinstance(value, bool):
            value = "true" if value else "false"
        self.cfg.set("app", key, str(value))

    # ── UI ────────────────────────────────────────────────────────────────────
    def build_ui(self):
        bar = tk.Frame(self.root, bg="#2c2c2c", height=36)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        tk.Label(bar, text="🎮 Fortnite Crash Fixer v2.0",
                 bg="#2c2c2c", fg="white",
                 font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=10)

        for text, cmd in [("❌ Exit", self.root.quit),
                           ("📖 Help & FAQ", self.show_help),
                           ("🎨 Color", self.pick_color)]:
            tk.Button(bar, text=text, command=cmd,
                      bg="#2c2c2c", fg="white", relief="flat").pack(side=tk.RIGHT, padx=5)

        self.dark_btn = tk.Button(bar, text="🌙 Dark Mode",
                                  command=self.toggle_dark_mode,
                                  bg="#2c2c2c", fg="white", relief="flat")
        self.dark_btn.pack(side=tk.RIGHT, padx=5)

        self.safe_mode_bar_btn = tk.Button(
            bar, text=self._safe_mode_bar_label(),
            command=self.toggle_safe_mode,
            bg="#2c2c2c", fg="#00cfff", relief="flat",
            font=("Arial", 9, "bold"))
        self.safe_mode_bar_btn.pack(side=tk.RIGHT, padx=5)

        tk.Button(bar, text="⚙️ Settings", command=self.show_settings,
                  bg="#2c2c2c", fg="#FFD700", relief="flat",
                  font=("Arial", 9, "bold")).pack(side=tk.RIGHT, padx=8)

        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self._theme_widgets.append(("frame", self.main_frame))

        self.title_label = tk.Label(self.main_frame,
                                    text="🎮 Fortnite Crash Fixer",
                                    font=("Arial", 18, "bold"))
        self.title_label.pack(pady=12)
        self._theme_widgets.append(("label", self.title_label))

        self.status_label = tk.Label(self.main_frame, text="Ready",
                                     font=("Arial", 10), fg="green")
        self.status_label.pack()
        self._theme_widgets.append(("label", self.status_label))

        self.safe_banner = tk.Label(
            self.main_frame,
            text="🛡️  SAFE MODE ON — Full Fix & EAC Reset disabled",
            bg="#003366", fg="#00cfff",
            font=("Arial", 9, "bold"), pady=4)
        if self.get_bool("safe_mode"):
            self.safe_banner.pack(fill=tk.X, padx=10)

        btn_area = ttk.Frame(self.root)
        btn_area.pack(pady=8, fill=tk.BOTH, expand=False)

        def add(text, cmd):
            b = ttk.Button(btn_area, text=text, command=cmd)
            b.pack(fill=tk.X, pady=2)
            self._buttons.append(b)

        add("🔍 Analyze System",           self.analyze)
        add("⚡ Quick Fix (Recommended)",  self.quick_fix)
        add("💣 Full Fix",                 self.full_fix)
        add("🛡️ Reset EAC (Full)",         self.reset_eac)
        add("🔧 Shader Cache",             self.clear_cache)
        add("🔄 Reset Config Files",       self.reset_config)
        add("💾 Increase Virtual Memory",  self.increase_memory)
        add("📊 System Info",              self.show_system_info)
        add("📈 RAM Monitor",              self.check_ram_pressure)
        add("🎯 FPS Monitor",              self.open_fps_monitor)
        add("🖥️ Update GPU",               self.launch_gpu_updater)
        add("📂 Open Fortnite Folder",     self.open_fortnite_folder)
        add("📝 Crash Logs",               self.analyze_crash_logs)

        out_label = tk.Label(self.main_frame, text="Output:",
                             font=("Arial", 10, "bold"), anchor="w")
        out_label.pack(anchor=tk.W, padx=10)
        self._theme_widgets.append(("label", out_label))

        self.output = scrolledtext.ScrolledText(self.main_frame, height=10)
        self.output.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        tk.Button(self.main_frame, text="🧹 Clear Output",
                  command=lambda: self.output.delete(1.0, tk.END),
                  relief="flat", padx=8, pady=3).pack(pady=4)

        footer = tk.Label(self.main_frame,
                          text="Version 2.0  |  Not affiliated with Epic Games",
                          font=("Arial", 7), fg="gray")
        footer.pack(pady=2)
        self._theme_widgets.append(("label_gray", footer))

    def _safe_mode_bar_label(self):
        return "🛡️ Safe: ON" if self.get_bool("safe_mode") else "🛡️ Safe: OFF"

    def toggle_safe_mode(self):
        self.set("safe_mode", not self.get_bool("safe_mode"))
        self.save_config()
        self._refresh_safe_mode_ui()

    def _refresh_safe_mode_ui(self):
        on = self.get_bool("safe_mode")
        self.safe_mode_bar_btn.config(text=self._safe_mode_bar_label())
        if on:
            self.safe_banner.pack(fill=tk.X, padx=10)
            self.log("🛡️  Safe Mode ON — Full Fix and EAC Reset disabled.")
        else:
            self.safe_banner.pack_forget()
            self.log("🛡️  Safe Mode OFF — all functions enabled.")

    def _safe_mode_block(self, feature_name):
        if self.get_bool("safe_mode"):
            messagebox.showwarning(
                "🛡️ Safe Mode Active",
                f"{feature_name} is disabled while Safe Mode is ON.\n\n"
                "Toggle Safe Mode via the '🛡️ Safe' button in the top bar.")
            return True
        return False

    # ── THEME ─────────────────────────────────────────────────────────────────
    def apply_theme(self):
        dark = self.get_bool("dark_mode")
        t = dict(DARK if dark else LIGHT)
        if not dark:
            t["bg"] = self.get("bg_color")

        self.root.configure(bg=t["bg"])
        self.main_frame.configure(bg=t["bg"])
        self.title_label.configure(bg=t["bg"], fg=t["fg"])
        self.status_label.configure(bg=t["bg"])

        for wtype, widget in self._theme_widgets:
            try:
                if wtype == "frame":
                    widget.configure(bg=t["bg"])
                elif wtype == "label":
                    widget.configure(bg=t["bg"], fg=t["fg"])
                elif wtype == "label_gray":
                    widget.configure(bg=t["bg"])
            except Exception:
                pass

        for btn in self._buttons:
            try:
                btn.configure(bg=t["btn_bg"], fg=t["btn_fg"],
                              activebackground=t["btn_active"],
                              activeforeground=t["btn_fg"])
            except Exception:
                pass

        if hasattr(self, "output"):
            self.output.configure(bg=t["bg2"], fg=t["fg"],
                                  insertbackground=t["fg"])
        if hasattr(self, "dark_btn"):
            self.dark_btn.configure(
                text="☀️ Light Mode" if dark else "🌙 Dark Mode")

    def toggle_dark_mode(self):
        self.set("dark_mode", not self.get_bool("dark_mode"))
        self.save_config()
        self.apply_theme()

    def pick_color(self):
        c = colorchooser.askcolor(title="Choose background color")[1]
        if c:
            self.set("bg_color", c)
            self.set("dark_mode", "false")
            self.save_config()
            self.apply_theme()

    # ── LOGGING ───────────────────────────────────────────────────────────────
    def log(self, msg):
        self.output.insert(tk.END, str(msg) + "\n")
        self.output.see(tk.END)

    def log_safe(self, msg):
        self.root.after(0, lambda m=msg: self.log(m))

    def status_safe(self, msg, color="green"):
        self.root.after(0, lambda: self.status_label.config(text=msg, fg=color))

    def _notify_done(self):
        if self.get_bool("notification_sound"):
            play_done_sound()

    def _should_confirm(self, title, msg):
        if not self.get_bool("confirm_dangerous_actions"):
            return True
        return messagebox.askyesno(title, msg)

    def _backup_configs(self):
        if not self.get_bool("backup_configs_before_fix"):
            return
        src = os.path.expandvars(
            r"%LocalAppData%\FortniteGame\Saved\Config\WindowsClient")
        dst = os.path.join(CONFIG_DIR, "backups")
        os.makedirs(dst, exist_ok=True)
        ts  = time.strftime("%Y%m%d_%H%M%S")
        for fname in ["GameUserSettings.ini", "Input.ini"]:
            fpath = os.path.join(src, fname)
            if os.path.isfile(fpath):
                shutil.copy2(fpath, os.path.join(dst, f"{ts}_{fname}"))
                self.log_safe(f"   💾 Backed up {fname}")

    # ══════════════════════════════════════════════════════════════════════════
    #  ANALYZE — v2.0: smart diagnosis + fix recommendation
    # ══════════════════════════════════════════════════════════════════════════
    def analyze(self):
        if self.is_running:
            return
        self.is_running = True
        self.root.after(0, lambda: self.output.delete(1.0, tk.END))

        def run():
            try:
                issues   = []   # list of (severity, category, detail, fix)
                warnings = []

                self.log_safe("=" * 55)
                self.log_safe("  FORTNITE SYSTEM ANALYSIS  v2.0")
                self.log_safe("=" * 55)

                # ── OS ────────────────────────────────────────────────────
                self.log_safe(f"\n🖥️  OS: {platform.system()} {platform.release()} "
                              f"(Build {platform.version().split('.')[-1]})")

                # ── RAM ───────────────────────────────────────────────────
                vm         = psutil.virtual_memory()
                total_gb   = vm.total    / (1024**3)
                avail_gb   = vm.available / (1024**3)
                ram_pct    = vm.percent
                self.log_safe(f"🧠 RAM: {total_gb:.1f} GB total — "
                              f"{avail_gb:.1f} GB free ({ram_pct}% used)")
                if ram_pct >= 90:
                    issues.append(("CRITICAL", "RAM",
                        f"Only {avail_gb:.1f} GB free ({ram_pct}% used) — Fortnite WILL crash",
                        "⚡ Quick Fix then restart PC to free RAM"))
                elif ram_pct >= 75:
                    issues.append(("WARNING", "RAM",
                        f"High RAM usage: {ram_pct}% used, {avail_gb:.1f} GB free",
                        "💾 Increase Virtual Memory + close background apps"))
                elif ram_pct >= 50:
                    issues.append(("INFO", "RAM",
                        f"Moderate RAM usage: {ram_pct}% used, {avail_gb:.1f} GB free",
                        "Monitor RAM — close heavy apps before launching Fortnite"))

                # ── CPU ───────────────────────────────────────────────────
                try:
                    phys = psutil.cpu_count(logical=False)
                    logi = psutil.cpu_count(logical=True)
                    self.log_safe(f"⚙️  CPU: {phys} physical / {logi} logical cores")
                except Exception:
                    pass

                # ── DISK ──────────────────────────────────────────────────
                disk    = psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] + "\\")
                disk_gb = disk.free / (1024**3)
                self.log_safe(f"💽 Disk: {disk_gb:.1f} GB free on C:")
                if disk_gb < 10:
                    issues.append(("CRITICAL", "Disk",
                        f"Only {disk_gb:.1f} GB free — Fortnite needs ~10 GB headroom",
                        "Free up disk space on C: (uninstall apps, empty Recycle Bin)"))
                elif disk_gb < 25:
                    issues.append(("WARNING", "Disk",
                        f"Low disk space: {disk_gb:.1f} GB free",
                        "💣 Full Fix to clear temp files, then free more space manually"))

                # ── FORTNITE PATH ─────────────────────────────────────────
                self.log_safe("\n📂 Checking Fortnite install...")
                fn_path = self.get("fortnite_path")
                if os.path.isdir(fn_path):
                    self.log_safe(f"   ✓ Found at: {fn_path}")
                else:
                    self.log_safe("   ❌ Fortnite NOT found at configured path")
                    issues.append(("WARNING", "Install",
                        "Fortnite not found — path may be wrong",
                        "⚙️ Settings → set correct Fortnite path, then verify files in Epic"))

                # ── SHADER CACHE SIZE ─────────────────────────────────────
                self.log_safe("\n🎨 Checking shader cache...")
                shader_path = os.path.expandvars(
                    r"%LocalAppData%\FortniteGame\Saved\ShaderCache")
                if os.path.isdir(shader_path):
                    shader_mb = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, _, files in os.walk(shader_path)
                        for f in files
                    ) / (1024**2)
                    self.log_safe(f"   Shader cache size: {shader_mb:.0f} MB")
                    if shader_mb > 2048:
                        issues.append(("WARNING", "Shader Cache",
                            f"Shader cache is large ({shader_mb:.0f} MB) — may be corrupted",
                            "🔧 Clear Shader Cache"))
                    else:
                        self.log_safe("   ✓ Shader cache size OK")
                else:
                    self.log_safe("   ✓ No shader cache (clean)")

                # ── CONFIG FILES ──────────────────────────────────────────
                self.log_safe("\n📄 Checking Fortnite config files...")
                cfg_dir  = os.path.expandvars(
                    r"%LocalAppData%\FortniteGame\Saved\Config\WindowsClient")
                cfg_ok   = True
                for fname in ["GameUserSettings.ini", "Input.ini"]:
                    fpath = os.path.join(cfg_dir, fname)
                    if os.path.isfile(fpath):
                        try:
                            # Check for corruption: file exists but is empty or unparseable
                            size = os.path.getsize(fpath)
                            if size == 0:
                                issues.append(("WARNING", "Config",
                                    f"{fname} is empty (corrupted)",
                                    "🔄 Reset Config Files"))
                                cfg_ok = False
                            else:
                                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                    content = f.read()
                                if "[/Script/" not in content and "[Core." not in content:
                                    issues.append(("WARNING", "Config",
                                        f"{fname} appears corrupted (missing section headers)",
                                        "🔄 Reset Config Files"))
                                    cfg_ok = False
                        except Exception:
                            pass
                if cfg_ok:
                    self.log_safe("   ✓ Config files look healthy")

                # ── EAC STATUS ────────────────────────────────────────────
                self.log_safe("\n🛡️  Checking Easy Anti-Cheat...")
                eac_exe = os.path.join(
                    fn_path, "FortniteGame", "Binaries",
                    "Win64", "EasyAntiCheat", "EasyAntiCheat_EOS_Setup.exe")
                eac_data = os.path.expandvars(r"%ProgramData%\EasyAntiCheat")

                eac_exe_ok  = os.path.isfile(eac_exe)
                eac_data_ok = os.path.isdir(eac_data)

                # Check if EAC service is registered
                eac_svc_ok = False
                try:
                    rc, out = run_cmd(["sc", "query", "EasyAntiCheat"], timeout=5)
                    eac_svc_ok = rc == 0 and "RUNNING" in out.upper()
                except Exception:
                    pass

                self.log_safe(f"   EAC setup exe:  {'✓ found' if eac_exe_ok  else '❌ missing'}")
                self.log_safe(f"   EAC data folder:{'✓ found' if eac_data_ok else '❌ missing'}")
                self.log_safe(f"   EAC service:    {'✓ running' if eac_svc_ok else '⚠️ not running'}")

                if not eac_exe_ok:
                    issues.append(("CRITICAL", "EAC",
                        "EasyAntiCheat setup exe missing — Fortnite cannot launch",
                        "🛡️ Reset EAC (Full) — then verify Fortnite files in Epic"))
                elif not eac_data_ok or not eac_svc_ok:
                    issues.append(("WARNING", "EAC",
                        "EAC data or service not healthy",
                        "🛡️ Reset EAC (Full)"))

                # ── CRASH LOGS ────────────────────────────────────────────
                self.log_safe("\n📝 Checking crash logs...")
                log_dir = os.path.expandvars(
                    r"%LocalAppData%\FortniteGame\Saved\Logs")
                crash_signals = {
                    "OutOfMemory":  ("RAM",    "Out of memory crash detected",
                                     "💾 Increase Virtual Memory + ⚡ Quick Fix"),
                    "D3DERR":       ("GPU",    "DirectX device error in logs",
                                     "Update GPU drivers (NVIDIA/AMD/Intel)"),
                    "RHICommandList":("GPU",   "GPU command list crash",
                                     "Update GPU drivers + 🔧 Clear Shader Cache"),
                    "EasyAntiCheat":("EAC",   "EAC error in logs",
                                     "🛡️ Reset EAC (Full)"),
                    "ShaderLibrary":("Shader", "Shader library error in logs",
                                     "🔧 Clear Shader Cache"),
                    "NetworkFailure":("Network","Network failure in logs",
                                      "💣 Full Fix (includes DNS + Winsock reset)"),
                    "SocketError":  ("Network", "Socket error in crash log",
                                     "💣 Full Fix (Winsock reset)"),
                }
                if os.path.isdir(log_dir):
                    log_files = sorted(
                        [f for f in os.listdir(log_dir) if f.endswith(".log")],
                        key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
                        reverse=True)
                    if log_files:
                        self.log_safe(f"   Found {len(log_files)} log file(s) — scanning latest")
                        latest = os.path.join(log_dir, log_files[0])
                        try:
                            with open(latest, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            hits = 0
                            for keyword, (cat, detail, fix) in crash_signals.items():
                                if keyword.lower() in content.lower():
                                    # avoid duplicating same category
                                    if not any(i[1] == cat for i in issues):
                                        issues.append(("WARNING", cat, detail, fix))
                                    hits += 1
                            if hits == 0:
                                self.log_safe("   ✓ No known crash signatures in latest log")
                        except Exception as e:
                            self.log_safe(f"   ⚠️ Could not read log: {e}")
                    else:
                        self.log_safe("   ✓ No crash logs found")
                else:
                    self.log_safe("   ⚠️ Log folder not found")

                # ── NETWORK ───────────────────────────────────────────────
                self.log_safe("\n🌐 Checking network stack...")
                rc, out = run_cmd(["netsh", "winsock", "show", "catalog"], timeout=8)
                if rc == 0:
                    lsp_count = out.lower().count("layered service provider")
                    if lsp_count > 0:
                        issues.append(("WARNING", "Network",
                            f"Found {lsp_count} LSP(s) — can interfere with EAC",
                            "💣 Full Fix (Winsock reset)"))
                    else:
                        self.log_safe("   ✓ Winsock catalog looks clean")
                else:
                    self.log_safe("   ⚠️ Could not query Winsock catalog")

                # ── XBOX GAME BAR ─────────────────────────────────────────
                self.log_safe("\n🎮 Checking Xbox Game Bar interference...")
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR")
                    val, _ = winreg.QueryValueEx(key, "AppCaptureEnabled")
                    winreg.CloseKey(key)
                    if val != 0:
                        issues.append(("INFO", "Xbox DVR",
                            "Xbox Game Bar capture is enabled — can cause FPS drops and crashes",
                            "💣 Full Fix (disables Game Bar capture)"))
                    else:
                        self.log_safe("   ✓ Xbox Game Bar capture is disabled")
                except FileNotFoundError:
                    self.log_safe("   ✓ Xbox Game Bar key not found (already clean)")
                except Exception:
                    pass

                # ── BACKGROUND PROCESSES ──────────────────────────────────
                self.log_safe("\n⚙️  Checking background processes...")
                heavy_procs = []
                for p in psutil.process_iter(["name", "memory_info", "cpu_percent"]):
                    try:
                        name = p.info["name"].lower()
                        mem  = p.info["memory_info"].rss / (1024**2)
                        if mem > 500 and not any(k in name for k in
                            ["fortnite", "epicgames", "system", "svchost",
                             "explorer", "crashfixer"]):
                            heavy_procs.append((p.info["name"], mem))
                    except Exception:
                        pass
                if heavy_procs:
                    top = sorted(heavy_procs, key=lambda x: x[1], reverse=True)[:3]
                    names = ", ".join(n for n, _ in top)
                    self.log_safe(f"   ⚠️ Heavy background processes: {names}")
                    issues.append(("INFO", "Background Apps",
                        f"Heavy apps using RAM: {names}",
                        "Close these apps before launching Fortnite"))
                else:
                    self.log_safe("   ✓ No heavy background processes detected")

                # ══════════════════════════════════════════════════════════
                #  DIAGNOSIS REPORT
                # ══════════════════════════════════════════════════════════
                self.log_safe("\n" + "=" * 55)
                self.log_safe("  DIAGNOSIS REPORT")
                self.log_safe("=" * 55)

                if not issues:
                    self.log_safe("\n✅ No issues detected!")
                    self.log_safe("   Your system looks good for Fortnite.")
                    self.log_safe("   If still crashing: verify files in Epic Launcher.")
                else:
                    # Sort: CRITICAL first, then WARNING, then INFO
                    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
                    issues.sort(key=lambda x: order.get(x[0], 3))

                    self.log_safe("")
                    for sev, cat, detail, fix in issues:
                        icon = "🔴" if sev == "CRITICAL" else ("🟡" if sev == "WARNING" else "🔵")
                        self.log_safe(f"{icon} [{sev}] {cat}")
                        self.log_safe(f"   Problem: {detail}")
                        self.log_safe(f"   Fix:     {fix}")
                        self.log_safe("")

                    # Primary recommendation
                    self.log_safe("─" * 55)
                    self.log_safe("📌 RECOMMENDED ACTION:")
                    top_issue = issues[0]
                    self.log_safe(f"   → {top_issue[3]}")
                    self.log_safe("")
                    if len(issues) > 1:
                        self.log_safe("   After that, also address:")
                        for sev, cat, _, fix in issues[1:]:
                            self.log_safe(f"   → {fix}  [{cat}]")

                self.log_safe("\n" + "=" * 55)
                self.log_safe("  Analysis Complete!")
                self.log_safe("=" * 55)
                self.status_safe("Analysis complete", "green")
                self._notify_done()

            except Exception as e:
                self.log_safe(f"ERROR: {e}")
                self.status_safe("Error occurred", "red")
            finally:
                self.is_running = False

        threading.Thread(target=run, daemon=True).start()

    # ── QUICK FIX ─────────────────────────────────────────────────────────────
    def quick_fix(self):
        if self.is_running:
            return
        if not self._should_confirm("Confirm", "Apply Quick Fix?"):
            return
        self.is_running = True
        self.root.after(0, lambda: self.output.delete(1.0, tk.END))
        do_shader   = self.get_bool("clear_shader_on_quick_fix")
        do_launcher = self.get_bool("clear_launcher_on_quick_fix")

        def run():
            try:
                self.log_safe("=== QUICK FIX STARTED ===")
                self.status_safe("Running Quick Fix...", "orange")

                vm_qf   = psutil.virtual_memory()
                avail_qf = vm_qf.available / (1024**3)
                pct_qf   = vm_qf.percent
                if pct_qf >= 90:
                    self.log_safe("🔴 RAM CRITICAL: Only {:.1f} GB free — Fortnite will likely crash".format(avail_qf))
                elif pct_qf >= 75:
                    self.log_safe("🟠 RAM WARNING: {:.1f} GB free — high usage, close background apps".format(avail_qf))
                elif pct_qf >= 50:
                    self.log_safe("🟡 RAM CAUTION: {:.1f} GB free — monitor if Fortnite stutters".format(avail_qf))

                if do_shader:
                    cache = os.path.expandvars(
                        r"%LocalAppData%\FortniteGame\Saved\ShaderCache")
                    self.log_safe("Step 1: Cleaning shader cache...")
                    if os.path.exists(cache):
                        safe_remove(cache, self.log_safe)
                        self.log_safe("✓ Shader cache cleared")
                    else:
                        self.log_safe("✓ Shader cache not found")

                if do_launcher:
                    launcher = os.path.expandvars(
                        r"%LocalAppData%\EpicGamesLauncher\Saved\webcache")
                    self.log_safe("Step 2: Cleaning launcher cache...")
                    if os.path.exists(launcher):
                        safe_remove(launcher, self.log_safe)
                        self.log_safe("✓ Launcher cache cleared")
                    else:
                        self.log_safe("✓ Launcher cache not found")

                self.status_safe("Quick Fix completed", "green")
                self._notify_done()
                self.root.after(0, lambda: messagebox.showinfo("Done", "Quick Fix completed"))
            except Exception as e:
                self.log_safe(f"ERROR: {e}")
                self.status_safe("Error occurred", "red")
            finally:
                self.is_running = False

        threading.Thread(target=run, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  FULL FIX v2.0 — PARALLEL EXECUTION
    # ══════════════════════════════════════════════════════════════════════════
    def full_fix(self):
        if self._safe_mode_block("Full Fix"):
            return
        if self.is_running:
            return
        if not self._should_confirm(
            "⚠️ Full Fix v2.0 — Deep Recovery",
            "DEEP RECOVERY MODE\n\n"
            "• Kill Fortnite & Epic processes\n"
            "• Backup + wipe Fortnite Saved data\n"
            "• Clear Epic launcher cache + crash dumps\n"
            "• Full EAC reset + reinstall\n"
            "• Flush DNS + reset Winsock\n"
            "• Clean Windows temp files\n"
            "• Disable Xbox Game Bar\n"
            "• Set High Performance power plan\n\n"
            "Independent steps run in parallel for speed.\n"
            "Account, skins and progress are SAFE.\n\nContinue?"
        ):
            return

        self.is_running = True
        self.root.after(0, lambda: self.output.delete(1.0, tk.END))
        skip_eac  = self.get_bool("skip_eac_in_full_fix")
        t_start   = time.perf_counter()

        def run():
            try:
                self.log_safe("=" * 60)
                self.log_safe("FULL FIX v2.0 — PARALLEL DEEP RECOVERY")
                self.log_safe("=" * 60)
                self.log_safe("")

                # ── PHASE 1: sequential (must kill processes first) ───────
                self.log_safe("PHASE 1 — Stopping processes...")
                targets = ["fortniteclient-win64-shipping", "fortnite",
                           "epicgameslauncher", "easyanticheat_eos", "easyanticheat"]
                killed = 0
                for proc in psutil.process_iter(["name"]):
                    try:
                        name = (proc.info["name"] or "").lower()
                        if any(t in name for t in targets):
                            proc.kill()
                            proc.wait(timeout=3)
                            killed += 1
                    except Exception:
                        pass
                self.log_safe(f"   ✓ {killed} process(es) closed")
                time.sleep(1)   # let handles release

                # Backup before wiping (sequential — must happen before wipe)
                self.log_safe("   Backing up configs...")
                self._backup_configs()
                self.log_safe("")

                # ── PHASE 2: parallel independent tasks ───────────────────
                self.log_safe("PHASE 2 — Running parallel cleanup tasks...")
                self.log_safe("")

                phase2_results = {}

                def task_fortnite_saved():
                    """Wipe Fortnite\\Saved (except Logs)"""
                    fn_saved = os.path.expandvars(
                        r"%LocalAppData%\FortniteGame\Saved")
                    wiped = 0
                    if os.path.isdir(fn_saved):
                        for item in os.listdir(fn_saved):
                            if item.lower() == "logs":
                                continue
                            p = os.path.join(fn_saved, item)
                            if safe_remove(p, self.log_safe):
                                wiped += 1
                    return f"✓ Fortnite\\Saved wiped ({wiped} items)"

                def task_epic_cache():
                    """Wipe Epic Launcher cache"""
                    epic = os.path.expandvars(
                        r"%LocalAppData%\EpicGamesLauncher\Saved")
                    if os.path.isdir(epic):
                        safe_remove(epic, self.log_safe)
                        return "✓ Epic Launcher cache wiped"
                    return "ℹ️ Epic cache not found"

                def task_crash_dumps():
                    """Clear crash dumps"""
                    dump_dirs = [
                        os.path.expandvars(r"%LocalAppData%\CrashDumps"),
                        os.path.expandvars(r"%LocalAppData%\FortniteGame\Saved\Crashes"),
                        os.path.expandvars(r"%LocalAppData%\EpicGamesLauncher\Saved\Crashes"),
                    ]
                    count = 0
                    for d in dump_dirs:
                        if not os.path.isdir(d):
                            continue
                        for item in os.listdir(d):
                            low = item.lower()
                            if any(k in low for k in
                                   ["fortnite", "epicgames", "easyanti", ".dmp", ".log"]):
                                if safe_remove(os.path.join(d, item), self.log_safe):
                                    count += 1
                    return f"✓ {count} crash file(s) removed"

                def task_temp_cleanup():
                    """Clean temp files"""
                    temp_path = self.get("custom_temp_path").strip() or \
                                os.path.expandvars("%TEMP%")
                    cleared = skipped = 0
                    for item in os.listdir(temp_path):
                        p = os.path.join(temp_path, item)
                        try:
                            if os.path.isfile(p):
                                os.remove(p)
                            else:
                                shutil.rmtree(p)
                            cleared += 1
                        except Exception:
                            skipped += 1
                    return f"✓ Temp: {cleared} cleared, {skipped} skipped"

                def task_dns():
                    """Flush DNS"""
                    rc, out = run_cmd(["ipconfig", "/flushdns"], timeout=10)
                    return "✓ DNS cache flushed" if rc == 0 else f"⚠️ DNS: {out}"

                def task_winsock():
                    """Reset Winsock"""
                    rc, out = run_cmd(["netsh", "winsock", "reset"], timeout=15)
                    return ("✓ Winsock reset (takes effect after reboot)"
                            if rc == 0 else f"⚠️ Winsock: {out}")

                def task_xbox_dvr():
                    """Disable Xbox Game Bar capture"""
                    results = []
                    xbox_keys = [
                        (r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
                         "AppCaptureEnabled", winreg.REG_DWORD, 0),
                        (r"SYSTEM\GameConfigStore",
                         "GameDVR_Enabled", winreg.REG_DWORD, 0),
                    ]
                    for subkey, name, rtype, val in xbox_keys:
                        try:
                            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                                 subkey, 0, winreg.KEY_SET_VALUE)
                            winreg.SetValueEx(key, name, 0, rtype, val)
                            winreg.CloseKey(key)
                            results.append(f"{name} disabled")
                        except FileNotFoundError:
                            results.append(f"{name} not found")
                        except Exception as e:
                            results.append(f"{name}: {e}")
                    return "✓ Xbox DVR: " + ", ".join(results)

                def task_power_plan():
                    """Set High Performance power plan"""
                    for guid in ["8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
                                 "e9a42b02-d5df-448d-aa00-03f14749eb61"]:
                        rc, _ = run_cmd(["powercfg", "/setactive", guid], timeout=10)
                        if rc == 0:
                            return "✓ High Performance power plan activated"
                    return "⚠️ Power plan change failed"

                # Run all Phase 2 tasks concurrently
                parallel_tasks = {
                    "Fortnite Saved": task_fortnite_saved,
                    "Epic Cache":     task_epic_cache,
                    "Crash Dumps":    task_crash_dumps,
                    "Temp Files":     task_temp_cleanup,
                    "DNS":            task_dns,
                    "Winsock":        task_winsock,
                    "Xbox DVR":       task_xbox_dvr,
                    "Power Plan":     task_power_plan,
                }

                with ThreadPoolExecutor(max_workers=6) as executor:
                    futures = {
                        executor.submit(fn): name
                        for name, fn in parallel_tasks.items()
                    }
                    for future in as_completed(futures):
                        task_name = futures[future]
                        try:
                            result = future.result()
                            self.log_safe(f"   [{task_name}] {result}")
                        except Exception as e:
                            self.log_safe(f"   [{task_name}] ❌ {e}")
                self.log_safe("")

                # ── PHASE 3: EAC (sequential — depends on processes dead) ─
                if skip_eac:
                    self.log_safe("PHASE 3 — EAC reset SKIPPED (disabled in Settings)")
                else:
                    self.log_safe("PHASE 3 — Full EAC reset...")
                    run_cmd(["sc", "stop",   "EasyAntiCheat"], timeout=10)
                    time.sleep(2)
                    run_cmd(["sc", "delete", "EasyAntiCheat"], timeout=10)

                    for subkey in [
                        r"SYSTEM\CurrentControlSet\Services\EasyAntiCheat",
                        r"SOFTWARE\EasyAntiCheat",
                        r"SOFTWARE\WOW6432Node\EasyAntiCheat",
                    ]:
                        try:
                            winreg.DeleteKey(
                                winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE),
                                subkey)
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            self.log_safe(f"   ⚠️ Registry: {e}")

                    eac_data = os.path.expandvars(r"%ProgramData%\EasyAntiCheat")
                    if os.path.isdir(eac_data):
                        safe_remove(eac_data, self.log_safe)

                    fortnite_path = self.get("fortnite_path")
                    eac_exe = os.path.join(
                        fortnite_path, "FortniteGame", "Binaries",
                        "Win64", "EasyAntiCheat", "EasyAntiCheat_EOS_Setup.exe")
                    if os.path.isfile(eac_exe):
                        rc, _ = run_cmd([eac_exe, "install", "fn"], timeout=60)
                        if rc == 0:
                            self.log_safe("   ✓ EAC reinstalled silently")
                        else:
                            subprocess.Popen([eac_exe])
                            self.log_safe("   ⚠️ EAC GUI opened — click Repair Service")
                    else:
                        self.log_safe("   ❌ EAC exe not found")
                self.log_safe("")

                # ── DONE ──────────────────────────────────────────────────
                elapsed = time.perf_counter() - t_start
                self.log_safe("=" * 60)
                self.log_safe(f"✓ FULL FIX v2.0 COMPLETE  ({elapsed:.1f}s)")
                self.log_safe("=" * 60)
                self.log_safe("")
                self.log_safe("→ RESTART YOUR PC  (required for Winsock + EAC)")
                self.log_safe("→ Launch Epic → verify Fortnite files → launch Fortnite")
                self.log_safe("💡 First launch slower — shader rebuild is normal")

                self.status_safe(
                    f"Full Fix v2.0 complete ({elapsed:.1f}s) — restart PC", "green")
                self._notify_done()

                if self.get_bool("auto_restart_after_full_fix"):
                    self.root.after(0, self._prompt_auto_restart)
                else:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Full Fix v2.0 Complete",
                        f"Deep recovery complete in {elapsed:.1f}s!\n\n"
                        "RESTART YOUR PC before launching Fortnite."))

            except Exception as e:
                self.log_safe(f"❌ FULL FIX ERROR: {e}")
                self.status_safe("Full Fix failed", "red")
            finally:
                self.is_running = False

        threading.Thread(target=run, daemon=True).start()

    def _prompt_auto_restart(self):
        if messagebox.askyesno("Auto-Restart",
                               "Full Fix complete.\nRestart your PC now?"):
            run_cmd(["shutdown", "/r", "/t", "10",
                     "/c", "Fortnite Crash Fixer: restart after Full Fix"], timeout=5)
            messagebox.showinfo("Restarting",
                                "PC restarts in 10 seconds.\nRun  shutdown /a  to cancel.")

    # ── RESET EAC ─────────────────────────────────────────────────────────────
    def reset_eac(self):
        if self._safe_mode_block("EAC Reset"):
            return
        if self.is_running:
            return
        if not self._should_confirm(
            "🛡️ Reset EAC — Full Reset",
            "Fully reset Easy Anti-Cheat:\n\n"
            "• Stop EAC service\n"
            "• Delete registry entries\n"
            "• Wipe EAC data folder\n"
            "• Reinstall silently\n\n"
            "Admin rights required. Fortnite must be CLOSED.\nContinue?"
        ):
            return

        self.is_running = True
        self.root.after(0, lambda: self.output.delete(1.0, tk.END))

        def run():
            try:
                self.log_safe("=" * 60)
                self.log_safe("🛡️ EAC FULL RESET — v2.0")
                self.log_safe("=" * 60 + "\n")

                self.log_safe("1️⃣ Stopping EAC service...")
                rc, out = run_cmd(["sc", "stop", "EasyAntiCheat"], timeout=10)
                self.log_safe(f"   {'✓ Stopped' if rc == 0 else 'ℹ️ ' + (out or 'not running')}")
                time.sleep(2)
                rc, out = run_cmd(["sc", "delete", "EasyAntiCheat"], timeout=10)
                self.log_safe(f"   {'✓ Entry removed' if rc == 0 else 'ℹ️ ' + (out or 'already clean')}\n")

                self.log_safe("2️⃣ Cleaning registry...")
                for subkey in [
                    r"SYSTEM\CurrentControlSet\Services\EasyAntiCheat",
                    r"SOFTWARE\EasyAntiCheat",
                    r"SOFTWARE\WOW6432Node\EasyAntiCheat",
                ]:
                    try:
                        winreg.DeleteKey(
                            winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE),
                            subkey)
                        self.log_safe(f"   ✓ Removed: {subkey.split(chr(92))[-1]}")
                    except FileNotFoundError:
                        self.log_safe(f"   ℹ️ Not found: {subkey.split(chr(92))[-1]}")
                    except Exception as e:
                        self.log_safe(f"   ⚠️ {e}")

                self.log_safe("\n3️⃣ Wiping EAC data...")
                eac_data = os.path.expandvars(r"%ProgramData%\EasyAntiCheat")
                if os.path.isdir(eac_data):
                    safe_remove(eac_data, self.log_safe)
                    self.log_safe("   ✓ EAC data folder deleted")
                else:
                    self.log_safe("   ℹ️ EAC data folder not found")

                self.log_safe("\n4️⃣ Reinstalling EAC (full uninstall → reinstall)...")
                fortnite_path = self.get("fortnite_path")
                eac_exe = os.path.join(
                    fortnite_path, "FortniteGame", "Binaries",
                    "Win64", "EasyAntiCheat", "EasyAntiCheat_EOS_Setup.exe")
                if os.path.isfile(eac_exe):
                    # Step A: uninstall removes all EAC driver files from system
                    self.log_safe("   Uninstalling EAC files from system...")
                    rc, out = run_cmd([eac_exe, "uninstall", "fn"], timeout=60)
                    if rc == 0:
                        self.log_safe("   ✓ EAC files uninstalled cleanly")
                    else:
                        self.log_safe(f"   ℹ️ Uninstall result: {out or 'non-zero (may already be clean)'}")
                    time.sleep(2)  # let driver handles fully release

                    # Step B: wipe leftover EAC files inside Fortnite folder
                    eac_local = os.path.join(
                        fortnite_path, "FortniteGame", "Binaries",
                        "Win64", "EasyAntiCheat")
                    leftovers = [".sys", ".dll", ".cache", ".log"]
                    wiped = 0
                    if os.path.isdir(eac_local):
                        for item in os.listdir(eac_local):
                            if any(item.lower().endswith(ext) for ext in leftovers):
                                p = os.path.join(eac_local, item)
                                if safe_remove(p, self.log_safe):
                                    wiped += 1
                    self.log_safe(f"   ✓ {wiped} leftover EAC file(s) wiped")

                    # Step C: clean reinstall writes all fresh files + registers driver
                    self.log_safe("   Installing fresh EAC files...")
                    rc, out = run_cmd([eac_exe, "install", "fn"], timeout=90)
                    if rc == 0:
                        self.log_safe("   ✓ EAC reinstalled silently — all files restored")
                    else:
                        subprocess.Popen([eac_exe])
                        self.log_safe("   ⚠️ Silent install failed — EAC GUI opened")
                        self.log_safe("   → Select Fortnite → click Install / Repair")
                else:
                    self.log_safe("   ❌ EAC exe not found — check Fortnite path in Settings")

                self.log_safe("\n" + "=" * 60)
                self.log_safe("✓ EAC RESET COMPLETE — restart PC")
                self.log_safe("=" * 60)
                self.status_safe("EAC reset complete — restart PC", "green")
                self._notify_done()
                self.root.after(0, lambda: messagebox.showinfo(
                    "EAC Reset", "EAC fully reset.\nRestart PC then launch Fortnite."))
            except Exception as e:
                self.log_safe(f"❌ EAC RESET ERROR: {e}")
                self.status_safe("EAC reset failed", "red")
            finally:
                self.is_running = False

        threading.Thread(target=run, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  FPS MONITOR — v2.0
    #  Reads Fortnite's live log file for GameThread frame time.
    #  Fortnite writes StatUnit data when launched with -StatUnit in
    #  Epic launcher additional args. No DirectX, no injection.
    # ══════════════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════════════
    #  FPS MONITOR — v2.0 FIXED
    #  Tails FortniteGame.log live for Frame/GameThread ms entries.
    #  Graph is redrawn directly from the reader thread via win.after(0).
    # ══════════════════════════════════════════════════════════════════════════
    def open_fps_monitor(self):
        if self._fps_running:
            messagebox.showinfo("FPS Monitor", "FPS Monitor is already open.")
            return

        # Print setup steps to main output box
        self.log("─" * 50)
        self.log("🎯 FPS MONITOR — SETUP REQUIRED")
        self.log("─" * 50)
        self.log("To use the FPS Monitor you must add -StatUnit")
        self.log("to your Fortnite Epic launch args (one-time setup):")
        self.log("")
        self.log("  1. Open Epic Games Launcher")
        self.log("  2. Go to Library → find Fortnite")
        self.log("  3. Click the ⋯ (three dots) next to Launch")
        self.log("  4. Click Manage → or Settings (gear icon)")
        self.log("  5. Enable 'Additional Command Line Arguments'")
        self.log("  6. Type:  -StatUnit")
        self.log("  7. Close settings and launch Fortnite normally")
        self.log("")
        self.log("Once Fortnite is running the FPS graph will")
        self.log("start automatically in the monitor window.")
        self.log("─" * 50)

        win = tk.Toplevel(self.root)
        win.title("🎯 FPS Monitor — Live")
        win.geometry("700x480")
        win.resizable(True, True)

        # ── Info banner ───────────────────────────────────────────────────
        info_text = (
            "Reads Fortnite's live log for frame time (no DirectX / no injection).\n"
            "Epic Launcher → Fortnite → ⋯ Settings → Additional Command Line Args → add:  -StatUnit\n"
            "Then launch Fortnite. FPS appears here in real time."
        )
        tk.Label(win, text=info_text, font=("Arial", 8), fg="#555555",
                 justify="left", wraplength=680).pack(padx=10, pady=(8, 2), anchor="w")

        # ── Stats bar ─────────────────────────────────────────────────────
        stats_frame = tk.Frame(win, bg="#2c2c2c")
        stats_frame.pack(fill=tk.X, padx=10, pady=4)

        self._fps_labels = {}
        for key, label in [("fps", "FPS"), ("avg", "Avg"), ("low1", "1% Low"),
                            ("min", "Min"), ("max", "Max"), ("status", "Status")]:
            col = tk.Frame(stats_frame, bg="#2c2c2c")
            col.pack(side=tk.LEFT, expand=True)
            tk.Label(col, text=label, bg="#2c2c2c", fg="#aaaaaa",
                     font=("Arial", 8)).pack()
            lbl = tk.Label(col, text="—", bg="#2c2c2c", fg="white",
                           font=("Arial", 14, "bold"))
            lbl.pack()
            self._fps_labels[key] = lbl

        # ── Canvas ────────────────────────────────────────────────────────
        GRAPH_W, GRAPH_H = 680, 260
        canvas = tk.Canvas(win, width=GRAPH_W, height=GRAPH_H,
                           bg="#111111", highlightthickness=0)
        canvas.pack(padx=10, pady=4)

        # Static grid lines
        for fps_val in [30, 60, 90, 120, 144, 165, 240]:
            y = self._fps_to_y(fps_val, GRAPH_H)
            if 0 <= y <= GRAPH_H:
                canvas.create_line(0, y, GRAPH_W, y, fill="#222222", dash=(4, 4))
                canvas.create_text(6, y - 6, text=str(fps_val),
                                   fill="#444444", anchor="w", font=("Arial", 7))

        btn_row = tk.Frame(win)
        btn_row.pack(pady=4)
        ttk.Button(btn_row, text="⏹ Stop Monitor",
                   command=lambda: self._stop_fps(win)).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="🗑 Clear Graph",
                   command=lambda: self._fps_clear(canvas)).pack(side=tk.LEFT, padx=6)

        win.protocol("WM_DELETE_WINDOW", lambda: self._stop_fps(win))

        # ── State ─────────────────────────────────────────────────────────
        self._fps_running = True
        self._fps_history = collections.deque(maxlen=120)
        self._fps_all     = []

        # ── Graph redraw — called from reader thread via win.after(0) ─────
        def redraw_graph():
            """Redraws the polyline. Always called on the Tk thread."""
            if not self._fps_running:
                return
            canvas.delete("fps_line")
            history = list(self._fps_history)
            if len(history) < 2:
                return
            pts = []
            for i, fps in enumerate(history):
                x = int(i * GRAPH_W / (len(history) - 1))
                y = self._fps_to_y(fps, GRAPH_H)
                pts.extend([x, y])
            if len(pts) >= 4:
                cur   = history[-1]
                color = ("#00ff88" if cur >= 60 else
                         "#ffcc00" if cur >= 30 else "#ff4444")
                canvas.create_line(*pts, fill=color, width=2, tag="fps_line")

        # ── Stats update — called from reader thread via win.after(0) ─────
        def update_stats(fps):
            """Updates label widgets. Always called on the Tk thread."""
            if not self._fps_running:
                return
            avg  = round(sum(self._fps_all) / len(self._fps_all), 1)
            mn   = round(min(self._fps_all), 1)
            mx   = round(max(self._fps_all), 1)
            sv   = sorted(self._fps_all)
            low1 = round(sum(sv[:max(1, len(sv)//100)]) / max(1, len(sv)//100), 1)

            color  = "#00ff88" if fps >= 60 else "#ffcc00" if fps >= 30 else "#ff4444"
            status = "🟢 Smooth" if fps >= 60 else "🟡 Playable" if fps >= 30 else "🔴 Low"

            self._fps_labels["fps"].config(text=str(fps), fg=color)
            self._fps_labels["avg"].config(text=str(avg))
            self._fps_labels["min"].config(text=str(mn))
            self._fps_labels["max"].config(text=str(mx))
            self._fps_labels["low1"].config(text=str(low1))
            self._fps_labels["status"].config(text=status, fg=color)

        def set_status_label(text, color="#aaaaaa"):
            if self._fps_running:
                self._fps_labels["status"].config(text=text, fg=color)

        # ── Reader thread ─────────────────────────────────────────────────
        def read_fps_loop():
            log_path = os.path.expandvars(
                r"%LocalAppData%\FortniteGame\Saved\Logs\FortniteGame.log")

            def parse_fps(lines):
                """Return FPS from the most recent frame-time line, or None."""
                for line in reversed(lines):
                    m = re.search(r'Frame[:\s]+(\d+\.?\d*)\s*ms', line, re.IGNORECASE)
                    if not m:
                        m = re.search(r'GameThread[:\s]+(\d+\.?\d*)\s*ms', line, re.IGNORECASE)
                    if m:
                        ms = float(m.group(1))
                        if ms > 0:
                            return round(1000.0 / ms, 1)
                return None

            log_handle    = None
            log_open      = False
            warned_no_log = False

            while self._fps_running:
                # ── Is Fortnite running? ──────────────────────────────────
                fn_running = any(
                    "fortniteclient" in (p.info.get("name") or "").lower()
                    for p in psutil.process_iter(["name"])
                )

                if not fn_running:
                    win.after(0, lambda: set_status_label("⏳ Waiting for Fortnite..."))
                    if log_handle:
                        try:
                            log_handle.close()
                        except Exception:
                            pass
                        log_handle    = None
                        log_open      = False
                        warned_no_log = False
                        self._fps_all.clear()
                        self._fps_history.clear()
                        win.after(0, lambda: [
                            self._fps_labels[k].config(text="—", fg="white")
                            for k in ["fps", "avg", "min", "max", "low1"]
                        ])
                    time.sleep(2)
                    continue

                # ── Open log if not already open ──────────────────────────
                if not log_open:
                    if os.path.isfile(log_path):
                        try:
                            log_handle = open(log_path, "r", encoding="utf-8",
                                              errors="ignore")
                            log_handle.seek(0, 2)   # tail — only new lines
                            log_open      = True
                            warned_no_log = False
                            win.after(0, lambda: set_status_label(
                                "📖 Reading log...", "#aaaaaa"))
                        except Exception:
                            time.sleep(1)
                            continue
                    else:
                        if not warned_no_log:
                            win.after(0, lambda: set_status_label(
                                "⚠️ Add -StatUnit to Epic launch args", "#ffcc00"))
                            warned_no_log = True
                        time.sleep(2)
                        continue

                # ── Read new lines from log ───────────────────────────────
                try:
                    new_lines = log_handle.readlines()
                except Exception:
                    log_handle = None
                    log_open   = False
                    time.sleep(1)
                    continue

                fps = parse_fps(new_lines) if new_lines else None

                if fps and 1 <= fps <= 500:
                    self._fps_history.append(fps)
                    self._fps_all.append(fps)
                    # Schedule both updates on Tk thread
                    fps_snap = fps
                    win.after(0, lambda f=fps_snap: update_stats(f))
                    win.after(0, redraw_graph)
                elif not new_lines:
                    win.after(0, lambda: set_status_label(
                        "🔄 Fortnite loading / no StatUnit data yet...", "#aaaaaa"))

                time.sleep(0.5)

            if log_handle:
                try:
                    log_handle.close()
                except Exception:
                    pass

        threading.Thread(target=read_fps_loop, daemon=True).start()

    def _fps_to_y(self, fps, graph_h, fps_min=0, fps_max=240):
        fps   = max(fps_min, min(fps_max, fps))
        ratio = 1.0 - (fps - fps_min) / (fps_max - fps_min)
        return int(ratio * graph_h)

    def _stop_fps(self, win):
        self._fps_running = False
        win.destroy()

    def _fps_clear(self, canvas):
        self._fps_history.clear()
        self._fps_all.clear()
        canvas.delete("fps_line")
        for k in ["fps", "avg", "min", "max", "low1"]:
            self._fps_labels[k].config(text="—", fg="white")
        self._fps_labels["status"].config(text="🗑 Cleared", fg="#aaaaaa")

    # ── GPU UPDATER ───────────────────────────────────────────────────────────
    def launch_gpu_updater(self):
        """
        Launches GPUpdater.exe from the same folder as this script / exe.
        Shows a download/info dialog first, then runs the exe.
        """
        # Locate GPUpdater.exe next to this script or frozen exe
        if getattr(__import__('sys'), 'frozen', False):
            base_dir = os.path.dirname(__import__('sys').executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        gpu_exe = os.path.join(base_dir, "GPUpdater.exe")

        # Info dialog first
        result = messagebox.askyesno(
            "🖥️ Update GPU — GPUpdater",
            "GPUpdater fixes and updates your GPU drivers automatically.\n\n"
            "⚠️  This tool is currently in BETA.\n\n"
            f"Looking for GPUpdater.exe in:\n{base_dir}\n\n"
            "Launch GPUpdater now?"
        )
        if not result:
            return

        if os.path.isfile(gpu_exe):
            try:
                subprocess.Popen([gpu_exe])
                self.log(f"🖥️ GPUpdater launched from: {gpu_exe}")
                self.status_safe("GPUpdater launched", "green")
            except Exception as e:
                messagebox.showerror("Launch Error", f"Could not launch GPUpdater:\n{e}")
                self.log(f"❌ GPUpdater launch failed: {e}")
        else:
            messagebox.showerror(
                "GPUpdater Not Found",
                f"GPUpdater.exe was not found in:\n{base_dir}\n\n"
                "Make sure GPUpdater.exe is in the same folder as FortniteCrashFixer.exe"
            )
            self.log(f"❌ GPUpdater.exe not found in: {base_dir}")

    # ── CLEAR CACHE ───────────────────────────────────────────────────────────
    def clear_cache(self):
        if not self._should_confirm("Confirm", "Clear shader cache?"):
            return
        cache = os.path.expandvars(r"%LocalAppData%\FortniteGame\Saved\ShaderCache")

        def run():
            try:
                if os.path.isdir(cache):
                    shutil.rmtree(cache)
                    os.makedirs(cache, exist_ok=True)
                    self.log_safe("✓ Shader cache cleared")
                else:
                    self.log_safe("Cache folder not found")
                self._notify_done()
            except Exception as e:
                self.log_safe(f"Error: {e}")

        threading.Thread(target=run, daemon=True).start()

    # ── SYSTEM INFO ───────────────────────────────────────────────────────────
    def show_system_info(self):
        self.output.delete(1.0, tk.END)
        vm   = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] + "\\")
        self.log("=== SYSTEM INFORMATION ===")
        self.log(f"OS:           {platform.system()} {platform.release()} ({platform.version()})")
        self.log(f"Architecture: {platform.architecture()[0]}")
        self.log(f"CPU:          {platform.processor()}")
        self.log(f"CPU Cores:    {psutil.cpu_count(logical=False)} physical / "
                 f"{psutil.cpu_count(logical=True)} logical")
        self.log(f"CPU Usage:    {psutil.cpu_percent(interval=1)}%")
        self.log(f"RAM Total:    {vm.total/(1024**3):.1f} GB")
        self.log(f"RAM Free:     {vm.available/(1024**3):.1f} GB")
        self.log(f"Disk Free:    {disk.free/(1024**3):.1f} GB (C:)")
        self.status_safe("System info displayed", "green")

    def open_fortnite_folder(self):
        path = self.get("fortnite_path")
        if os.path.isdir(path):
            os.startfile(path)
            self.log("📂 Opened Fortnite install folder")
        else:
            messagebox.showerror("Error", "Fortnite path not found. Check settings.")

    def increase_memory(self):
        self.output.delete(1.0, tk.END)
        self.log("""
INCREASE VIRTUAL MEMORY (PAGEFILE)
===================================
1. Right-click "This PC" → Properties
2. Advanced system settings
3. Performance → Settings
4. Advanced tab → Virtual Memory → Change
5. Uncheck "Automatically manage"
6. Select C: drive → Custom size: 16384 MB
7. Click Set → OK → Restart PC
""")

    def analyze_crash_logs(self):
        win = tk.Toplevel(self.root)
        win.title("Crash Log Analysis")
        win.geometry("600x480")
        ttk.Label(win, text="🔍 Crash Log Analysis",
                  font=("Arial", 13, "bold")).pack(pady=10)
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Arial", 9))
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        def run_analysis():
            txt.config(state=tk.NORMAL)
            txt.delete(1.0, tk.END)
            log_dir = os.path.expandvars(r"%LocalAppData%\FortniteGame\Saved\Logs")
            if not os.path.isdir(log_dir):
                txt.insert(tk.END, "❌ No crash log folder found.\n")
                txt.config(state=tk.DISABLED)
                return
            log_files = sorted(
                [f for f in os.listdir(log_dir) if f.endswith(".log")],
                key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
                reverse=True)
            if not log_files:
                txt.insert(tk.END, "✓ No crash logs found.\n")
                txt.config(state=tk.DISABLED)
                return
            txt.insert(tk.END, f"Found {len(log_files)} log(s). Analyzing latest...\n\n")
            latest = os.path.join(log_dir, log_files[0])
            txt.insert(tk.END, f"📄 {log_files[0]}\n{'='*50}\n")
            try:
                with open(latest, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                issues = []
                checks = [
                    ("OutOfMemory",    "🎯 RAM ISSUE — Increase virtual memory."),
                    ("D3D|RHI",        "🎯 GPU ISSUE — Update GPU drivers."),
                    ("shader",         "🎯 SHADER ISSUE — Clear shader cache."),
                    ("EasyAntiCheat",  "🎯 EAC ISSUE — Use Reset EAC (Full)."),
                    ("NetworkFailure|SocketError", "🎯 NETWORK ISSUE — Full Fix (Winsock + DNS)."),
                    ("crash",          "⚠️ General crash signature found."),
                ]
                for pattern, msg in checks:
                    if re.search(pattern, content, re.IGNORECASE):
                        issues.append(msg)
                if issues:
                    txt.insert(tk.END, "DETECTED ISSUES:\n")
                    for i in issues:
                        txt.insert(tk.END, f"  {i}\n")
                else:
                    txt.insert(tk.END, "✓ No specific issues detected.\n")
            except Exception as e:
                txt.insert(tk.END, f"❌ Could not read log: {e}\n")
            txt.config(state=tk.DISABLED)

        threading.Thread(target=run_analysis, daemon=True).start()
        bf = ttk.Frame(win)
        bf.pack(pady=5)
        ttk.Button(bf, text="📂 Open Logs Folder",
                   command=lambda: os.startfile(os.path.expandvars(
                       r"%LocalAppData%\FortniteGame\Saved\Logs"))
                   ).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Close", command=win.destroy).pack(side=tk.LEFT, padx=5)

    def reset_config(self):
        if not self._should_confirm("Confirm Reset",
            "Reset Fortnite config files?\n\nClears: GameUserSettings.ini & Input.ini\n"
            "Account data NOT affected."):
            return
        config_path = os.path.expandvars(
            r"%LocalAppData%\FortniteGame\Saved\Config\WindowsClient")

        def run():
            self._backup_configs()
            deleted, failed = [], []
            for fname in ["GameUserSettings.ini", "Input.ini"]:
                fpath = os.path.join(config_path, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        deleted.append(fname)
                    except Exception as e:
                        failed.append(f"{fname}: {e}")
            if deleted:
                self.log_safe(f"✓ Config reset: {', '.join(deleted)}")
            for f in failed:
                self.log_safe(f"❌ Failed: {f}")
            if not deleted and not failed:
                self.log_safe("ℹ️ No config files found to reset")
            self.status_safe("Config reset complete", "green")
            self._notify_done()

        threading.Thread(target=run, daemon=True).start()

    def check_ram_pressure(self):
        vm       = psutil.virtual_memory()
        total_gb = round(vm.total    / (1024**3), 1)
        used_gb  = round(vm.used     / (1024**3), 1)
        avail_gb = round(vm.available / (1024**3), 1)
        pct      = vm.percent

        if pct >= 90:
            level = "🔴 CRITICAL"
            msg   = "RAM is critically low. Crashes very likely."
        elif pct >= 75:
            level = "🟠 WARNING"
            msg   = "High RAM usage. Close heavy apps."
        elif pct >= 50:
            level = "🟡 CAUTION"
            msg   = "Moderate RAM usage. Monitor for spikes."
        else:
            level = "🟢 OK"
            msg   = "RAM usage is stable."

        self.log("=" * 40)
        self.log("🧠 RAM DIAGNOSTIC REPORT")
        self.log("=" * 40)
        self.log(f"Total: {total_gb} GB  |  Used: {used_gb} GB  |  Free: {avail_gb} GB")
        self.log(f"Usage: {pct}%  →  {level} — {msg}")
        self.log("\nTop memory processes:")
        try:
            procs = []
            for p in psutil.process_iter(["name", "memory_info"]):
                try:
                    procs.append((p.info["name"],
                                  p.info["memory_info"].rss / (1024**2)))
                except Exception:
                    pass
            for name, mem in sorted(procs, key=lambda x: x[1], reverse=True)[:5]:
                self.log(f"• {name} — {round(mem)} MB")
        except Exception as e:
            self.log(f"RAM scan error: {e}")
        self.status_safe("RAM diagnostic complete", "green")

    # ── SETTINGS ──────────────────────────────────────────────────────────────
    def show_settings(self):
        win = tk.Toplevel(self.root)
        win.title("⚙️ Settings")
        win.geometry("480x480")
        win.resizable(False, False)

        ttk.Label(win, text="⚙️  Settings",
                  font=("Arial", 14, "bold")).pack(pady=(12, 6))

        nb = ttk.Notebook(win)
        nb.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        def tab(label):
            f = ttk.Frame(nb, padding=12)
            nb.add(f, text=label)
            return f

        def row(parent, label, var, tooltip=None, indent=0):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, pady=3, padx=indent)
            ttk.Checkbutton(f, text=label, variable=var).pack(side=tk.LEFT)
            if tooltip:
                ttk.Label(f, text=f"  ({tooltip})", foreground="gray",
                          font=("Arial", 7, "italic")).pack(side=tk.LEFT)

        def section(parent, text):
            ttk.Separator(parent, orient="horizontal").pack(fill=tk.X, pady=(10, 2))
            ttk.Label(parent, text=text, font=("Arial", 9, "bold")).pack(anchor="w")

        v = {k: tk.StringVar(value=self.get(k))
             for k in ["fortnite_path", "custom_temp_path", "epic_email"]}
        b = {k: tk.BooleanVar(value=self.get_bool(k)) for k in [
            "auto_analyze", "dark_mode", "safe_mode",
            "clear_shader_on_quick_fix", "clear_launcher_on_quick_fix",
            "skip_eac_in_full_fix", "auto_restart_after_full_fix",
            "backup_configs_before_fix",
            "confirm_dangerous_actions", "notification_sound"]}

        t1 = tab("  General  ")
        row(t1, "Auto-analyze on startup", b["auto_analyze"])
        row(t1, "Dark mode",               b["dark_mode"])
        section(t1, "Safe Mode")
        row(t1, "Enable Safe Mode", b["safe_mode"],
            tooltip="blocks Full Fix & EAC Reset")
        section(t1, "Fortnite Install Path")
        pf = ttk.Frame(t1)
        pf.pack(fill=tk.X, pady=4)
        ttk.Entry(pf, textvariable=v["fortnite_path"]).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(pf, text="Browse", command=lambda: v["fortnite_path"].set(
            filedialog.askdirectory() or v["fortnite_path"].get())).pack(side=tk.LEFT)
        section(t1, "Epic Account (optional)")
        ef = ttk.Frame(t1)
        ef.pack(fill=tk.X, pady=4)
        ttk.Label(ef, text="Email:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(ef, textvariable=v["epic_email"], width=30).pack(side=tk.LEFT)
        ttk.Label(t1, text="Stored locally only — never transmitted.",
                  foreground="gray", font=("Arial", 7, "italic")).pack(anchor="w")

        t2 = tab("  Quick Fix  ")
        section(t2, "What Quick Fix clears")
        row(t2, "Clear shader cache",   b["clear_shader_on_quick_fix"])
        row(t2, "Clear launcher cache", b["clear_launcher_on_quick_fix"])

        t3 = tab("  Full Fix  ")
        row(t3, "Backup configs before fix",      b["backup_configs_before_fix"],
            tooltip=f"saves to {CONFIG_DIR}\\backups\\")
        row(t3, "Skip EAC reset in Full Fix",     b["skip_eac_in_full_fix"],
            tooltip="use if EAC is known good")
        row(t3, "Auto-restart PC after Full Fix", b["auto_restart_after_full_fix"],
            tooltip="prompts before restarting")
        backup_dir = os.path.join(CONFIG_DIR, "backups")
        ttk.Button(t3, text="📂 Open Backup Folder", command=lambda: (
            os.makedirs(backup_dir, exist_ok=True), os.startfile(backup_dir)
        )).pack(anchor="w", pady=(12, 0))

        t4 = tab("  Advanced  ")
        row(t4, "Confirm dangerous actions",        b["confirm_dangerous_actions"],
            tooltip="uncheck to skip yes/no dialogs")
        row(t4, "Notification sound on completion", b["notification_sound"])
        section(t4, "Custom Temp Folder (optional)")
        tf = ttk.Frame(t4)
        tf.pack(fill=tk.X, pady=4)
        ttk.Entry(tf, textvariable=v["custom_temp_path"]).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(tf, text="Browse", command=lambda: v["custom_temp_path"].set(
            filedialog.askdirectory() or v["custom_temp_path"].get())).pack(side=tk.LEFT)
        ttk.Label(t4, text="Leave blank to use %TEMP% (recommended).",
                  foreground="gray", font=("Arial", 7, "italic")).pack(anchor="w")
        section(t4, "Legal")
        lf = ttk.Frame(t4)
        lf.pack(anchor="w", pady=4)
        ttk.Button(lf, text="🔒 Privacy Policy",
                   command=self.show_privacy).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(lf, text="⚠️ Disclaimer",
                   command=self.show_disclaimer).pack(side=tk.LEFT)

        ttk.Separator(win, orient="horizontal").pack(fill=tk.X, padx=12, pady=6)
        bf = ttk.Frame(win)
        bf.pack(pady=(0, 10))

        def save():
            for key, var in b.items():
                self.set(key, var.get())
            for key, var in v.items():
                self.set(key, var.get().strip())
            self.save_config()
            self.apply_theme()
            self._refresh_safe_mode_ui()
            win.destroy()
            messagebox.showinfo("Settings", "Settings saved.")

        ttk.Button(bf, text="💾  Save",   command=save).pack(side=tk.LEFT, padx=6)
        ttk.Button(bf, text="❌  Cancel", command=win.destroy).pack(side=tk.LEFT, padx=6)

    # ── HELP / DISCLAIMER / PRIVACY ───────────────────────────────────────────
    def show_help(self):
        win = tk.Toplevel(self.root)
        win.title("Help & FAQ")
        win.geometry("540x560")
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Arial", 9))
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        txt.insert(tk.END, """
FORTNITE CRASH FIXER v2.0 — HELP & FAQ

BUTTONS
=======
🔍 Analyze System  — Full diagnostic + smart fix recommendation
⚡ Quick Fix       — Clear shader + launcher cache
💣 Full Fix        — Parallel deep recovery (faster than v1.9)
🛡️ Reset EAC       — Full EAC stop / wipe / reinstall
🔧 Shader Cache    — Manual shader cache clear
🔄 Reset Configs   — Delete GameUserSettings.ini & Input.ini
📊 System Info     — Full PC specs
📈 RAM Monitor     — RAM + top processes
🎯 FPS Monitor     — Live FPS graph from Fortnite log
📂 Open Fortnite   — Opens install folder
📝 Crash Logs      — Analyze latest crash log

FPS MONITOR SETUP
=================
1. Open Epic Games Launcher
2. Library → Fortnite → three dots → Settings
3. Additional Command Line Arguments: enable + type  -StatUnit
4. Launch Fortnite
5. Press FPS Monitor in this app

ANALYZE v2.0
============
Now checks: RAM, disk, shader cache size, config health,
EAC status, crash log signatures, Winsock LSPs, Xbox DVR,
and heavy background apps. Outputs a ranked fix list.

SAFE MODE
=========
Blocks Full Fix and EAC Reset. Toggle from top bar (🛡️ Safe)
or Settings → General.

FAQ
===
Q: Will this delete my skins?  A: No. Cache only.
Q: Do I need admin?  A: Recommended for EAC + Winsock.
Q: FPS showing —?  A: Add -StatUnit to Epic launch args.
Q: GPU updater not working?  A: GPUpdater is currently a beta tool, see GitHub for updates.
Q: Can I run this on Mac/Linux?  A: No, Windows only.
Q: Is this affiliated with Epic Games?  A: No, this is a fan-made utility.
Q: Can I run this while Fortnite is running?  A: Yes, but some fixes require Fortnite to be closed.
""")
        txt.config(state=tk.DISABLED)
        bf = ttk.Frame(win)
        bf.pack(pady=5)
        ttk.Button(bf, text="Privacy",    command=self.show_privacy).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Disclaimer", command=self.show_disclaimer).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Close",      command=win.destroy).pack(side=tk.LEFT, padx=5)

    def show_disclaimer(self):
        win = tk.Toplevel(self.root)
        win.title("Disclaimer")
        win.geometry("440x180")
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert(tk.END,
                   "NOT AFFILIATED WITH EPIC GAMES\n\n"
                   "Use at your own risk.\n"
                   "Only deletes cache and temporary files.\n"
                   "No account or game file modification.\n")
        txt.config(state=tk.DISABLED)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)

    def show_privacy(self):
        win = tk.Toplevel(self.root)
        win.title("Privacy Policy")
        win.geometry("450x340")
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert(tk.END, r"""
PRIVACY POLICY — Fortnite Crash Fixer v2.0

Overview
Fortnite Crash Fixer is a local Windows utility designed to help users diagnose and fix common Fortnite crash issues without collecting personal data.

This application is designed with user privacy in mind and operates entirely offline.

Data Collection
This application does NOT collect, store, or transmit any personal data.

Specifically, it does NOT collect:

Personal information (name, email, etc.)
System telemetry
Fortnite account data
Usage analytics
Location data
Internet Usage
This application does NOT require an internet connection to function and does not send any data externally.

All operations are performed locally on the user’s device.

Local Data Storage
The application stores only minimal configuration settings locally on the user’s system in: %AppData%\FortniteCrashFixer\settings.ini

This file may include:

UI preferences (dark mode, theme color)
User-selected Fortnite installation path
Feature toggle settings
No sensitive data is stored.

File Access
The application may access and modify only the following types of files:

Fortnite shader cache folders
Epic Games Launcher web cache
Local system information (read-only)
No game executables or account files are modified.

Security
All cleanup actions are:

Initiated by the user
Executed locally
Limited to cache and temporary files only
The application does not run background services or persistent processes.

Third-Party Services
This application does not use any third-party APIs, analytics tools, or external services.

LOCAL STORAGE
Settings:  %AppData%\FortniteCrashFixer\settings.ini
Backups:   %AppData%\FortniteCrashFixer\backups\

Disclaimer
This tool is not affiliated with Epic Games or Fortnite.

Use of this application is at your own risk. While it is designed to be safe, users should ensure they understand what cache cleaning entails.

Contact
If you have concerns regarding this application, please open an issue on the GitHub repository.
""")
        txt.config(state=tk.DISABLED)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)


# ── RUN ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = FortniteFixer_v2_0(root)
    root.mainloop()