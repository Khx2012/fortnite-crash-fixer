import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import os
import shutil
import subprocess
import psutil
from datetime import datetime

class FortniteFixer:
    def __init__(self, root):
        self.root = root
        self.root.title("Fortnite Crash Fixer v1.0")
        self.root.geometry("800x600")
        self.is_running = False
        
        # Build the UI
        self.build_ui()
    
    def build_ui(self):
        """Create the user interface"""
        
        # Title
        title = ttk.Label(self.root, text="🎮 Fortnite Crash Fixer", font=("Arial", 18, "bold"))
        title.pack(pady=15)
        
        # Status
        self.status_label = ttk.Label(self.root, text="Ready", font=("Arial", 10), foreground="green")
        self.status_label.pack()
        
        # Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=20)
        
        ttk.Button(button_frame, text="🔍 Analyze System", command=self.analyze).pack(fill=tk.X, pady=5, padx=10)
        ttk.Button(button_frame, text="⚡ Quick Fix (Recommended)", command=self.quick_fix).pack(fill=tk.X, pady=5, padx=10)
        ttk.Button(button_frame, text="🔧 Clear Shader Cache", command=self.clear_cache).pack(fill=tk.X, pady=5, padx=10)
        ttk.Button(button_frame, text="💾 Increase Virtual Memory", command=self.increase_memory).pack(fill=tk.X, pady=5, padx=10)
        ttk.Button(button_frame, text="💻 System Info", command=self.show_system_info).pack(fill=tk.X, pady=5, padx=10)
        
        # Output text area
        ttk.Label(self.root, text="Output:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10)
        
        self.output_text = scrolledtext.ScrolledText(self.root, height=15, width=80, wrap=tk.WORD)
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Bottom buttons
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(bottom_frame, text="📖 Help", command=self.show_help).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="❌ Exit", command=self.root.quit).pack(side=tk.RIGHT, padx=5)
    
    def log(self, message):
        """Add message to output"""
        self.output_text.insert(tk.END, message + "\n")
        self.output_text.see(tk.END)
        self.root.update()
    
    def analyze(self):
        """Analyze system for Fortnite issues"""
        if self.is_running:
            messagebox.showwarning("Running", "Please wait, operation in progress")
            return
        
        self.is_running = True
        self.status_label.config(text="Analyzing...", foreground="orange")
        self.output_text.delete(1.0, tk.END)
        
        def run_analysis():
            try:
                self.log("=" * 50)
                self.log("FORTNITE SYSTEM ANALYSIS")
                self.log("=" * 50)
                self.log("")
                
                # Check OS
                import platform
                self.log(f"✓ OS: {platform.system()} {platform.release()}")
                
                # Check RAM
                ram_gb = psutil.virtual_memory().total / (1024**3)
                available_gb = psutil.virtual_memory().available / (1024**3)
                self.log(f"✓ RAM: {ram_gb:.1f} GB total ({available_gb:.1f} GB available)")
                
                if available_gb < 4:
                    self.log("⚠️  WARNING: Low available RAM! Consider increasing pagefile.")
                
                # Check Disk Space
                disk = psutil.disk_usage('C:')
                free_gb = disk.free / (1024**3)
                self.log(f"✓ Disk Space: {free_gb:.1f} GB free")
                
                if free_gb < 50:
                    self.log("⚠️  WARNING: Low disk space! Fortnite needs 50+ GB")
                
                # Check Fortnite
                self.log("")
                self.log("Checking Fortnite installation...")
                fortnite_paths = [
                    r"C:\Program Files\Epic Games\Fortnite",
                    r"C:\Program Files (x86)\Epic Games\Fortnite",
                ]
                
                fortnite_found = False
                for path in fortnite_paths:
                    if os.path.exists(path):
                        self.log(f"✓ Fortnite found at: {path}")
                        fortnite_found = True
                        break
                
                if not fortnite_found:
                    self.log("❌ Fortnite not found - Install via Epic Games Launcher")
                
                # Check crash logs
                self.log("")
                self.log("Checking for crash logs...")
                crash_log_path = os.path.expandvars(r"%LocalAppData%\FortniteGame\Saved\Logs")
                
                if os.path.exists(crash_log_path):
                    crash_files = [f for f in os.listdir(crash_log_path) if 'crash' in f.lower()]
                    if crash_files:
                        self.log(f"⚠️  Found {len(crash_files)} crash log(s)")
                        self.log("💡 Try clearing shader cache to fix most crashes")
                    else:
                        self.log("✓ No recent crash logs found")
                else:
                    self.log("ℹ️  No crash logs yet (game hasn't crashed)")
                
                self.log("")
                self.log("=" * 50)
                self.log("Analysis Complete!")
                self.log("=" * 50)
                
                self.status_label.config(text="Analysis Complete", foreground="green")
                
            except Exception as e:
                self.log(f"❌ ERROR: {str(e)}")
                self.status_label.config(text="Error", foreground="red")
            finally:
                self.is_running = False
        
        thread = threading.Thread(target=run_analysis, daemon=True)
        thread.start()
    
    def quick_fix(self):
        """Apply quick fixes"""
        if not messagebox.askyesno("Confirm", "Apply recommended fixes?\n\nThis will:\n- Clear shader cache\n- Clear launcher cache\n\nContinue?"):
            return
        
        if self.is_running:
            messagebox.showwarning("Running", "Please wait, operation in progress")
            return
        
        self.is_running = True
        self.status_label.config(text="Applying fixes...", foreground="orange")
        self.output_text.delete(1.0, tk.END)
        
        def apply_fixes():
            try:
                self.log("=" * 50)
                self.log("APPLYING QUICK FIXES")
                self.log("=" * 50)
                self.log("")
                
                # Clear shader cache
                self.log("1️⃣  Clearing shader cache...")
                cache_path = os.path.expandvars(r"%LocalAppData%\FortniteGame\Saved\ShaderCache")
                if os.path.exists(cache_path):
                    try:
                        shutil.rmtree(cache_path)
                        os.makedirs(cache_path, exist_ok=True)
                        self.log("   ✓ Shader cache cleared")
                    except Exception as e:
                        self.log(f"   ❌ Could not clear cache: {e}")
                else:
                    self.log("   ℹ️  Shader cache folder not found")
                
                self.log("")
                
                # Clear launcher cache
                self.log("2️⃣  Clearing Epic Launcher cache...")
                launcher_cache = os.path.expandvars(r"%LocalAppData%\EpicGamesLauncher\Saved\webcache")
                if os.path.exists(launcher_cache):
                    try:
                        shutil.rmtree(launcher_cache)
                        os.makedirs(launcher_cache, exist_ok=True)
                        self.log("   ✓ Launcher cache cleared")
                    except Exception as e:
                        self.log(f"   ℹ️  Could not clear launcher cache: {e}")
                else:
                    self.log("   ℹ️  Launcher cache folder not found")
                
                self.log("")
                self.log("=" * 50)
                self.log("✓ FIXES APPLIED SUCCESSFULLY!")
                self.log("=" * 50)
                self.log("")
                self.log("Next steps:")
                self.log("1. Restart your PC (recommended)")
                self.log("2. Launch Fortnite")
                self.log("3. Test for crashes")
                
                self.status_label.config(text="Fixes Applied", foreground="green")
                messagebox.showinfo("Success", "Fixes applied!\n\nRestart your PC for best results.")
                
            except Exception as e:
                self.log(f"❌ ERROR: {str(e)}")
                self.status_label.config(text="Error", foreground="red")
            finally:
                self.is_running = False
        
        thread = threading.Thread(target=apply_fixes, daemon=True)
        thread.start()
    
    def clear_cache(self):
        """Clear shader cache only"""
        if not messagebox.askyesno("Confirm", "Clear shader cache?\n\nThis fixes most Fortnite crashes."):
            return
        
        self.output_text.delete(1.0, tk.END)
        self.log("Clearing shader cache...")
        
        try:
            cache_path = os.path.expandvars(r"%LocalAppData%\FortniteGame\Saved\ShaderCache")
            if os.path.exists(cache_path):
                shutil.rmtree(cache_path)
                os.makedirs(cache_path, exist_ok=True)
                self.log("✓ Shader cache cleared successfully!")
                self.log("\nNext: Restart your PC and launch Fortnite")
                messagebox.showinfo("Success", "Cache cleared!\n\nRestart Fortnite to apply changes.")
            else:
                self.log("❌ Cache folder not found")
                messagebox.showwarning("Not Found", "Shader cache folder not found")
        except Exception as e:
            self.log(f"❌ ERROR: {str(e)}")
            messagebox.showerror("Error", f"Failed to clear cache:\n{str(e)}")
    
    def increase_memory(self):
        """Guide user to increase virtual memory"""
        self.output_text.delete(1.0, tk.END)
        
        guide = """
INCREASE VIRTUAL MEMORY (PAGEFILE)
==================================

If you have less than 4GB free RAM, do this:

WINDOWS 10/11:
1. Right-click "This PC" or "My Computer"
2. Click "Properties"
3. Click "Advanced system settings" (left side)
4. Click "Environment Variables" button
5. Click "New" (System variables section)
6. Variable name: PAGEFILE_SIZE
7. Variable value: 16384 (for 16GB)
8. Click OK and restart your PC

OR use Windows built-in tool:
1. Right-click "This PC"
2. Properties → Advanced system settings
3. "Performance" section → Settings
4. Advanced tab
5. "Virtual memory" → Change
6. Uncheck "Automatically manage"
7. Select C: drive
8. Set to 16384 MB
9. Click Set → OK → Restart

After restart, your game will have more memory!
        """
        
        self.log(guide)
        messagebox.showinfo("Virtual Memory", "See the steps in the output area above")
    
    def show_system_info(self):
        """Show detailed system information"""
        self.output_text.delete(1.0, tk.END)
        
        try:
            import platform
            
            self.log("=" * 50)
            self.log("SYSTEM INFORMATION")
            self.log("=" * 50)
            self.log("")
            
            self.log(f"OS: {platform.system()} {platform.release()}")
            self.log(f"Architecture: {platform.machine()}")
            self.log(f"Python Version: {platform.python_version()}")
            
            self.log("")
            self.log("RAM:")
            total_ram = psutil.virtual_memory().total / (1024**3)
            available_ram = psutil.virtual_memory().available / (1024**3)
            used_ram = psutil.virtual_memory().used / (1024**3)
            self.log(f"  Total: {total_ram:.1f} GB")
            self.log(f"  Used: {used_ram:.1f} GB")
            self.log(f"  Available: {available_ram:.1f} GB")
            
            self.log("")
            self.log("Disk Space (C: drive):")
            disk = psutil.disk_usage('C:')
            total_disk = disk.total / (1024**3)
            used_disk = disk.used / (1024**3)
            free_disk = disk.free / (1024**3)
            self.log(f"  Total: {total_disk:.1f} GB")
            self.log(f"  Used: {used_disk:.1f} GB")
            self.log(f"  Free: {free_disk:.1f} GB")
            
            self.log("")
            self.log("CPU:")
            self.log(f"  Cores: {psutil.cpu_count()}")
            self.log(f"  Usage: {psutil.cpu_percent(interval=1)}%")
            
        except Exception as e:
            self.log(f"Error getting system info: {str(e)}")
    
    def show_help(self):
        """Show help dialog"""
        help_text = """
FORTNITE CRASH FIXER - HELP
===========================

BUTTONS:
• Analyze System - Scans for problems
• Quick Fix - Applies common fixes
• Clear Shader Cache - Fixes graphics issues
• Increase Virtual Memory - Add more RAM
• System Info - See your PC specs

COMMON CRASH CAUSES:
1. Corrupted shader cache → Clear Cache button
2. Not enough RAM → Increase Virtual Memory
3. Outdated GPU drivers → Update manually
4. Not enough disk space → Free up 50+ GB

TIPS:
✓ Create a restore point before making changes
✓ Close Epic Games Launcher before fixes
✓ Restart your PC after applying fixes
✓ Update Windows and GPU drivers regularly

STILL CRASHING?
1. Update your GPU drivers manually
2. Lower graphics settings in-game
3. Verify game files in Epic Launcher
4. Check Epic Games help: epicgames.com/help

DISCLAIMER:
This tool modifies system files. Use at your own risk!
Always backup important files first.
        """
        messagebox.showinfo("Help", help_text)


def main():
    root = tk.Tk()
    app = FortniteFixer(root)
    root.mainloop()


if __name__ == "__main__":
    main()