import threading
import tkinter as tk
from tkinter import messagebox
import keyboard
import comtypes
import comtypes.client
import requests
import os
import sys
import time
import psutil

from pycaw.pycaw import (
    AudioUtilities,
    ISimpleAudioVolume,
    IAudioSessionControl2,
    IAudioSessionManager2,
    IMMDeviceEnumerator,
)
from pycaw.constants import CLSID_MMDeviceEnumerator

EDataFlow_eRender = 0
DEVICE_STATE_ACTIVE = 0x1
IID_IAudioSessionManager2 = comtypes.GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")

CURRENT_VERSION = "1.5.0"
VERSION_URL = "https://raw.githubusercontent.com/Myubd/mute-app/main/version.txt"
EXE_URL = "https://github.com/Myubd/mute-app/releases/latest/download/mute_app.exe"
SHA256_URL = "https://raw.githubusercontent.com/Myubd/mute-app/main/sha256.txt"

BLACKLIST = {
    "shellexperiencehost.exe",
    "explorer.exe",
    "audiodg.exe",
    "systemsettings.exe",
}

C_BG        = "#F7F8FA"
C_SURFACE   = "#FFFFFF"
C_BORDER    = "#E2E5EA"
C_TEXT      = "#1A1D23"
C_MUTED_TXT = "#7A8190"
C_ACCENT    = "#3B82F6"
C_CAPTURE   = "#EFF6FF"   
C_MUTE_ON   = "#EF4444"
C_MUTE_OFF  = "#E8EDF4"
C_BTN_SAVE  = "#3B82F6"
C_BTN_SAVED = "#22C55E"
FONT_UI     = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_SMALL  = ("Segoe UI", 9)
FONT_APP    = ("Segoe UI", 10)

MODIFIER_KEYS = {"ctrl", "shift", "alt", "windows", "left ctrl", "right ctrl",
                 "left shift", "right shift", "left alt", "right alt"}


def get_active_app_names() -> set:
    names = set()
    try:
        sessions = AudioUtilities.GetAllSessions()
        for s in sessions:
            if s.Process:
                name = s.Process.name()
                if name.lower() not in BLACKLIST:
                    names.add(name)
    except Exception as e:
        print(f"[get_active_app_names] {e}")
    return names


def get_volumes_for_app(app_name: str) -> list:
    volumes = []
    try:
        enumerator = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
        )
        devices = enumerator.EnumAudioEndpoints(EDataFlow_eRender, DEVICE_STATE_ACTIVE)
        for i in range(devices.GetCount()):
            device = devices.Item(i)
            try:
                mgr = device.Activate(IID_IAudioSessionManager2, comtypes.CLSCTX_INPROC_SERVER, None)
                mgr2 = mgr.QueryInterface(IAudioSessionManager2)
                session_enum = mgr2.GetSessionEnumerator()
                for j in range(session_enum.GetCount()):
                    session_ctrl = session_enum.GetSession(j)
                    try:
                        ctrl2 = session_ctrl.QueryInterface(IAudioSessionControl2)
                        pid = ctrl2.GetProcessId()
                        if pid == 0:
                            continue
                        proc = psutil.Process(pid)
                        if proc.name().lower() == app_name.lower():
                            vol = session_ctrl.QueryInterface(ISimpleAudioVolume)
                            volumes.append(vol)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception as e:
        print(f"[get_volumes_for_app] {e}")
    return volumes


class AppMuteConfig:
    def __init__(self, app_name: str):
        self.app_name = app_name
        self.hotkey = ""
        self.is_muted = False
        self.is_registered = False


class KeyCaptureEntry(tk.Frame):
    def __init__(self, master, on_captured=None, **kwargs):
        super().__init__(master, bg=kwargs.pop("bg", C_SURFACE))
        self.on_captured = on_captured 
        self._capturing = False
        self._hook = None
        self._pressed = set()   
        self._result = ""       

        self._label = tk.Label(
            self,
            text="クリックして設定",
            font=FONT_UI,
            fg=C_MUTED_TXT,
            bg="#F0F4F8",
            width=16,
            anchor="center",
            cursor="hand2",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT,
            padx=6,
            pady=4,
        )
        self._label.pack(fill="both", expand=True)
        self._label.bind("<Button-1>", self._start_capture)

    def get(self) -> str:
        return self._result

    def set(self, value: str):
        self._result = value
        self._label.config(
            text=value if value else "クリックして設定",
            fg=C_TEXT if value else C_MUTED_TXT,
            bg="#F0F4F8",
            highlightbackground=C_BORDER,
        )

    def _start_capture(self, event=None):
        if self._capturing:
            return
        self._capturing = True
        self._pressed.clear()
        self._label.config(text="キーを押してください", fg=C_ACCENT, bg=C_CAPTURE,
                           highlightbackground=C_ACCENT)

        self._hook = keyboard.hook(self._on_key_event)

        self._label.winfo_toplevel().bind("<Escape>", self._cancel_capture, add=True)

    def _on_key_event(self, event):
        if not self._capturing:
            return

        if event.event_type == keyboard.KEY_DOWN:
            name = event.name.lower()

            if name in MODIFIER_KEYS:
                self._pressed.add(name)
                preview = self._build_combo(name)
                self._label.config(text=f"{preview}+...")
                return

            combo = self._build_combo(name)
            self._finish_capture(combo)

    def _build_combo(self, final_key: str) -> str:
        """修飾キー + 通常キーを keyboard ライブラリの形式に整形"""
        parts = []
        for mod, aliases in [
            ("ctrl",  {"ctrl", "left ctrl", "right ctrl"}),
            ("alt",   {"alt", "left alt", "right alt"}),
            ("shift", {"shift", "left shift", "right shift"}),
        ]:
            if self._pressed & aliases:
                parts.append(mod)
        if final_key not in MODIFIER_KEYS:
            parts.append(final_key)
        return "+".join(parts)

    def _finish_capture(self, combo: str):
        self._capturing = False
        if self._hook:
            keyboard.unhook(self._hook)
            self._hook = None
        self._label.winfo_toplevel().unbind("<Escape>")

        self._result = combo
        self._label.config(text=combo, fg=C_TEXT, bg="#F0F4F8",
                           highlightbackground=C_BORDER)
        if self.on_captured:
            self.on_captured(combo)

    def _cancel_capture(self, event=None):
        self._capturing = False
        if self._hook:
            keyboard.unhook(self._hook)
            self._hook = None
        self._label.winfo_toplevel().unbind("<Escape>")
        prev = self._result or "クリックして設定"
        fg   = C_TEXT if self._result else C_MUTED_TXT
        self._label.config(text=prev, fg=fg, bg="#F0F4F8",
                           highlightbackground=C_BORDER)


class MultiAppMuteGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"App Mute  v{CURRENT_VERSION}")
        self.root.geometry("520x520")
        self.root.minsize(460, 300)
        self.root.configure(bg=C_BG)

        self.app_configs: dict = {}
        self.active_threads = True

        self._build_ui()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._check_update, daemon=True).start()

    def _build_ui(self):
        header = tk.Frame(self.root, bg=C_BG, padx=18, pady=12)
        header.pack(fill="x")

        dot = tk.Canvas(header, width=8, height=8, bg=C_BG, highlightthickness=0)
        dot.pack(side="left", padx=(0, 6), pady=2)
        dot.create_oval(1, 1, 7, 7, fill="#22C55E", outline="")

        tk.Label(header, text="音声アプリ検知中", font=FONT_BOLD, fg=C_TEXT, bg=C_BG).pack(side="left")
        tk.Label(header, text=f"v{CURRENT_VERSION}", font=FONT_SMALL, fg=C_MUTED_TXT, bg=C_BG).pack(side="right", padx=4)

        tk.Frame(self.root, bg=C_BORDER, height=1).pack(fill="x")

        col = tk.Frame(self.root, bg=C_BG, padx=18, pady=6)
        col.pack(fill="x")
        tk.Label(col, text="アプリ名", font=FONT_SMALL, fg=C_MUTED_TXT, bg=C_BG, width=18, anchor="w").pack(side="left")
        tk.Label(col, text="ショートカット（クリックして設定）", font=FONT_SMALL, fg=C_MUTED_TXT, bg=C_BG).pack(side="left", padx=(4, 0))


        list_frame = tk.Frame(self.root, bg=C_BG)
        list_frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(list_frame, bg=C_BG, highlightthickness=0, borderwidth=0)
        self.scroll_frame = tk.Frame(self.canvas, bg=C_BG)
        vsb = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._canvas_window, width=e.width))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1*(e.delta//120), "units"))

        tk.Frame(self.root, bg=C_BORDER, height=1).pack(fill="x")
        sb = tk.Frame(self.root, bg=C_BG, padx=14, pady=5)
        sb.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="音声プロセスを監視中...")
        tk.Label(sb, textvariable=self.status_var, font=FONT_SMALL, fg=C_MUTED_TXT, bg=C_BG, anchor="w").pack(fill="x")

    def _monitor_loop(self):
        while self.active_threads:
            comtypes.CoInitialize()
            try:
                names = get_active_app_names()
                for name in names:
                    if name not in self.app_configs:
                        self.app_configs[name] = AppMuteConfig(name)
                        self.root.after(0, self._add_app_row, name)
            except Exception as e:
                print(f"[monitor] {e}")
            finally:
                comtypes.CoUninitialize()
            time.sleep(1)

    def _add_app_row(self, app_name: str):
        card = tk.Frame(self.scroll_frame, bg=C_SURFACE)
        card.pack(fill="x", padx=12, pady=(4, 0))

        inner = tk.Frame(card, bg=C_SURFACE, padx=14, pady=10)
        inner.pack(fill="x")

        display_name = app_name.replace(".exe", "").replace(".EXE", "")
        tk.Label(inner, text=display_name, font=FONT_APP, fg=C_TEXT, bg=C_SURFACE,
                 width=18, anchor="w").pack(side="left")

        capture = KeyCaptureEntry(inner, bg=C_SURFACE)
        capture.pack(side="left", padx=(8, 6))


        btn_save = tk.Button(
            inner, text="保存", font=FONT_SMALL, fg="#FFFFFF", bg=C_BTN_SAVE,
            relief="flat", padx=10, pady=3, cursor="hand2", bd=0,
            activebackground="#2563EB", activeforeground="#FFFFFF",
        )
        btn_save.pack(side="left", padx=(0, 10))
        btn_save.config(command=lambda: self._apply_shortcut(app_name, capture, btn_save, btn_mute))


        btn_mute = tk.Button(
            inner, text="通常音量", font=FONT_SMALL, fg=C_MUTED_TXT, bg=C_MUTE_OFF,
            relief="flat", padx=10, pady=3, width=9, cursor="hand2", bd=0,
            activebackground="#D1D9E6", activeforeground=C_TEXT,
        )
        btn_mute.pack(side="right")
        btn_mute.config(command=lambda a=app_name, b=btn_mute: self._toggle_mute(a, b))

        tk.Frame(card, bg=C_BORDER, height=1).pack(fill="x", padx=14)

        capture.on_captured = lambda combo, a=app_name, c=capture, bs=btn_save, bm=btn_mute: \
            self.root.after(0, lambda: self._apply_shortcut(a, c, bs, bm))

    def _apply_shortcut(self, app_name, capture_widget, btn_save, btn_mute):
        config = self.app_configs[app_name]
        user_key = capture_widget.get().strip().lower()

        if not user_key:
            messagebox.showerror("エラー", "キーをキャプチャしてください\n入力欄をクリック → キーを押す")
            return

        if config.is_registered:
            try:
                keyboard.remove_hotkey(config.hotkey)
            except Exception:
                pass
            config.is_registered = False

        try:
            config.hotkey = user_key
            keyboard.add_hotkey(user_key, lambda a=app_name, b=btn_mute: self._toggle_mute(a, b))
            config.is_registered = True
            btn_save.config(text="✓ 保存済", bg=C_BTN_SAVED, activebackground="#16A34A")
            self.status_var.set(f"[{app_name}]  ←→  {user_key}")
        except Exception as e:
            messagebox.showerror("キーエラー", f"このキーは登録できませんでした:\n{e}")

    def _toggle_mute(self, app_name: str, btn_mute: tk.Button):
        config = self.app_configs[app_name]
        comtypes.CoInitialize()
        try:
            volumes = get_volumes_for_app(app_name)
            if not volumes:
                self.status_var.set(f"[{app_name}] プロセスが見つかりません")
                return

            target_vol = 0.0 if not config.is_muted else 1.0
            for vol in volumes:
                try:
                    vol.SetMasterVolume(target_vol, None)
                except Exception:
                    pass

            config.is_muted = not config.is_muted

            if config.is_muted:
                self.root.after(0, lambda: btn_mute.config(
                    text="ミュート中", fg="#FFFFFF", bg=C_MUTE_ON,
                    activebackground="#DC2626", activeforeground="#FFFFFF"
                ))
                self.status_var.set(f"[{app_name}]  ミュート中")
            else:
                self.root.after(0, lambda: btn_mute.config(
                    text="通常音量", fg=C_MUTED_TXT, bg=C_MUTE_OFF,
                    activebackground="#D1D9E6", activeforeground=C_TEXT
                ))
                self.status_var.set(f"[{app_name}]  ミュート解除")
        except Exception as e:
            print(f"[toggle_mute] {e}")
        finally:
            comtypes.CoUninitialize()

    @staticmethod
    def _parse_version(v: str) -> tuple:
        try:
            return tuple(map(int, v.strip().lower().replace("v", "").split(".")))
        except Exception:
            return (0, 0, 0)

    def _check_update(self):
        import hashlib
        try:
            r = requests.get(VERSION_URL, timeout=5)
            if r.status_code != 200:
                return
            remote = r.text.strip()
            if self._parse_version(remote) <= self._parse_version(CURRENT_VERSION):
                return

            current_exe = sys.argv[0]
            if not current_exe.endswith(".exe"):
                return

            exe_r  = requests.get(EXE_URL,    timeout=30)
            hash_r = requests.get(SHA256_URL, timeout=5)
            if exe_r.status_code != 200 or hash_r.status_code != 200:
                return

            expected = hash_r.text.strip().lower()
            actual   = hashlib.sha256(exe_r.content).hexdigest()
            if actual != expected:
                print(f"[update] ハッシュ不一致。更新を中止しました。(expected={expected}, actual={actual})")
                return

            old = current_exe + ".old"
            if os.path.exists(old):
                os.remove(old)
            os.rename(current_exe, old)
            with open(current_exe, "wb") as f:
                f.write(exe_r.content)

            messagebox.showinfo("自動更新", f"v{remote} へアップデートしました！\n自動で再起動します。")
            self.active_threads = False
            import subprocess
            subprocess.Popen([current_exe])
            os._exit(0)
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = MultiAppMuteGUI(root)

    def on_closing():
        app.active_threads = False
        for config in app.app_configs.values():
            if config.is_registered:
                try:
                    keyboard.remove_hotkey(config.hotkey)
                except Exception:
                    pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()