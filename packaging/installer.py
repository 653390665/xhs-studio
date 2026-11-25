"""XHS Studio Windows installer.

Bundles payload.zip (the PyInstaller app folder) and installs it per-user:
  %LOCALAPPDATA%\\Programs\\XHSStudio
Creates Start Menu / Desktop shortcuts and registers an uninstaller.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "XHS Studio"
APP_ID = "XHSStudio"
APP_VERSION = "1.2.3"
PUBLISHER = "XHS Studio"


def enable_dpi_awareness() -> None:
    """让窗口尺寸按真实像素算，而不是被系统再缩放一次。

    不声明 DPI 感知时，Tk 按 96 DPI 布局，Windows 再把整窗放大；
    这时 winfo_reqheight() 报的是未缩放的值，按它定窗口高度会偏低。
    声明之后两边单位一致，自适应高度才可靠。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def default_install_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP_ID


def start_menu_shortcut() -> Path:
    appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{APP_NAME}.lnk"


def desktop_shortcut() -> Path:
    return Path.home() / "Desktop" / f"{APP_NAME}.lnk"


def create_shortcut(link: Path, target: Path, workdir: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{link}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.WorkingDirectory = '{workdir}'; "
        f"$s.IconLocation = '{target},0'; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def write_uninstaller(dest: Path) -> None:
    script = f"""$ErrorActionPreference = "SilentlyContinue"
Remove-Item "{start_menu_shortcut()}" -Force
Remove-Item "{desktop_shortcut()}" -Force
Remove-Item "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_ID}" -Recurse -Force
Start-Process -WindowStyle Hidden cmd -ArgumentList '/c','timeout /t 1 >nul & rmdir /s /q "{dest}"'
"""
    (dest / "Uninstall.ps1").write_text(script, encoding="utf-8")


def register_uninstall(dest: Path) -> None:
    import winreg

    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
    exe = dest / f"{APP_ID}.exe"
    values = {
        "DisplayName": APP_NAME,
        "DisplayVersion": APP_VERSION,
        "Publisher": PUBLISHER,
        "InstallLocation": str(dest),
        "DisplayIcon": str(exe),
        "UninstallString": f'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{dest / "Uninstall.ps1"}"',
        "NoModify": 1,
        "NoRepair": 1,
    }
    for name, value in values.items():
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ if isinstance(value, str) else winreg.REG_DWORD, value)
    winreg.CloseKey(key)


def install(dest: Path, desktop: bool, launch: bool, shortcuts: bool = True, progress=None) -> None:
    payload = resource_path("payload.zip")
    if not payload.is_file():
        raise RuntimeError("安装包缺少 payload.zip")
    dest.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("正在解压应用文件…")
    with zipfile.ZipFile(payload) as archive:
        archive.extractall(dest)

    if shortcuts:
        if progress:
            progress("正在创建快捷方式…")
        exe = dest / f"{APP_ID}.exe"
        create_shortcut(start_menu_shortcut(), exe, dest)
        if desktop:
            create_shortcut(desktop_shortcut(), exe, dest)

    if progress:
        progress("正在注册卸载信息…")
    write_uninstaller(dest)
    register_uninstall(dest)

    if launch:
        subprocess.Popen([str(dest / f"{APP_ID}.exe")], cwd=str(dest), close_fds=True)


class InstallerWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} 安装程序")
        self.resizable(False, False)
        self.configure(bg="#f7f7f7")

        tk.Label(
            self,
            text=f"{APP_NAME} {APP_VERSION}",
            font=("Microsoft YaHei UI", 18, "bold"),
            bg="#f7f7f7",
            fg="#1f1f1f",
        ).pack(anchor="w", padx=24, pady=(22, 4))
        tk.Label(
            self,
            text="小红书内容运营工作台 · 安装到当前用户，无需管理员权限",
            font=("Microsoft YaHei UI", 9),
            bg="#f7f7f7",
            fg="#666666",
        ).pack(anchor="w", padx=24)

        frame = tk.Frame(self, bg="#f7f7f7")
        frame.pack(fill="x", padx=24, pady=18)
        tk.Label(frame, text="安装目录", bg="#f7f7f7", font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        row = tk.Frame(frame, bg="#f7f7f7")
        row.pack(fill="x", pady=(4, 0))
        self.path_var = tk.StringVar(value=str(default_install_dir()))
        self.path_entry = tk.Entry(row, textvariable=self.path_var, font=("Microsoft YaHei UI", 9))
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.browse_btn = tk.Button(row, text="浏览…", command=self.browse, font=("Microsoft YaHei UI", 9))
        self.browse_btn.pack(side="left", padx=(6, 0))

        self.desktop_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self,
            text="创建桌面快捷方式",
            variable=self.desktop_var,
            bg="#f7f7f7",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=24)

        self.status_var = tk.StringVar(value="准备就绪")
        tk.Label(self, textvariable=self.status_var, bg="#f7f7f7", fg="#666666", font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", padx=24, pady=(12, 4)
        )
        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=24)

        buttons = tk.Frame(self, bg="#f7f7f7")
        buttons.pack(fill="x", padx=24, pady=16)
        self.install_btn = tk.Button(
            buttons,
            text="开始安装",
            command=self.start_install,
            bg="#1668dc",
            fg="white",
            font=("Microsoft YaHei UI", 10, "bold"),
            relief="flat",
            padx=18,
            pady=4,
        )
        self.install_btn.pack(side="right")
        tk.Button(
            buttons,
            text="取消",
            command=self.destroy,
            font=("Microsoft YaHei UI", 9),
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="right", padx=(0, 8))
        self._installing = False

        # 尺寸必须按内容算，不能写死。
        # Tk 字号是「磅」，系统 DPI 一放大，同样的控件就变高；
        # 之前写死 560x300，而内容实际要 338，按钮那一行整条被裁在窗口外，
        # 用户看到的是「只有进度条，没有开始安装」。
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), 560)
        height = self.winfo_reqheight() + 8
        x = max((self.winfo_screenwidth() - width) // 2, 0)
        y = max((self.winfo_screenheight() - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(width, height)

    def browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(default_install_dir().parent))
        if selected:
            self.path_var.set(selected)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def start_install(self) -> None:
        if self._installing:
            return
        dest = Path(self.path_var.get().strip())
        if not str(dest):
            messagebox.showwarning("提示", "请选择安装目录")
            return
        self._installing = True
        self.install_btn.configure(state="disabled", text="安装中…")
        self.browse_btn.configure(state="disabled")
        self.progress.start(10)
        threading.Thread(
            target=self._run_install,
            args=(dest, self.desktop_var.get()),
            daemon=True,
        ).start()

    def _run_install(self, dest: Path, desktop: bool) -> None:
        try:
            install(
                dest,
                desktop=desktop,
                launch=True,
                progress=lambda text: self.after(0, self.set_status, text),
            )
            self.after(0, self._done)
        except PermissionError:
            self.after(0, lambda: self._failed("无法写入安装目录，请先关闭正在运行的 XHS Studio，或换一个目录。"))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._failed(str(exc)))

    def _done(self) -> None:
        self.progress.stop()
        self.status_var.set("安装完成，正在启动…")
        self.after(600, self.destroy)

    def _failed(self, message: str) -> None:
        self.progress.stop()
        self.status_var.set("安装失败")
        self.install_btn.configure(state="normal", text="重试")
        self.browse_btn.configure(state="normal")
        self._installing = False
        messagebox.showerror("安装失败", message)


def main() -> None:
    enable_dpi_awareness()
    parser = argparse.ArgumentParser(description=f"{APP_NAME} installer")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--dir", default="")
    parser.add_argument("--no-desktop", action="store_true")
    parser.add_argument("--no-shortcuts", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    args = parser.parse_args()

    if args.silent:
        dest = Path(args.dir) if args.dir else default_install_dir()
        try:
            install(
                dest,
                desktop=not args.no_desktop,
                launch=not args.no_launch,
                shortcuts=not args.no_shortcuts,
            )
            print(f"installed to {dest}")
        except Exception as exc:  # noqa: BLE001
            print(f"install failed: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    InstallerWindow().mainloop()


if __name__ == "__main__":
    main()
