from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="栖心：东大学子的数字解压阀（Python 桌面 Demo）"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="使用独立的演示数据库，并填充近一个月的示例心情与计划",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="指定 SQLite 数据库路径（适合截图或测试）",
    )
    return parser.parse_args()


def main() -> None:
    _load_local_env()
    args = _arguments()
    try:
        from PIL import ImageTk  # noqa: F401
    except ImportError:
        message = (
            "栖心需要 Pillow 来绘制抗锯齿界面。\n\n"
            "请先运行：python -m pip install -r requirements.txt"
        )
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("缺少依赖", message)
            root.destroy()
        except Exception:
            print(message, file=sys.stderr)
        raise SystemExit(1)

    from .db import Store
    from .ui import QixinApp

    store = Store(args.db, demo=args.demo)
    app = QixinApp(store, demo=args.demo)
    try:
        app.root.mainloop()
    except KeyboardInterrupt:
        app._on_close()


if __name__ == "__main__":
    main()
