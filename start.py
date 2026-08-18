"""
AI Screenwriter & Production Toolkit - Unified Launcher
=======================================================
统一入口：支持两种运行形态，底层共用同一套 Streamlit 服务启动逻辑。

用法：
  python start.py            # 默认：用 PyWebView 桌面窗口打开
  python start.py --desktop  # 同上，显式指定桌面窗口
  python start.py --browser  # 用系统默认浏览器打开网页版

Windows 双击安全（已处理 GBK/ASCII 编码问题）。
"""

import sys
import os
import subprocess
import argparse
import webbrowser


# 强制 UTF-8 编码环境（Windows 双点击启动时常为 GBK/ASCII，导致中文日志和 API 请求异常）
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if sys.platform == "win32":
    os.environ.setdefault("LC_ALL", "C.UTF-8")
    try:
        import locale
        locale.setlocale(locale.LC_ALL, "C.UTF-8")
    except Exception:
        pass
    # 确保 stdout/stderr 可写中文
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _ensure_dependency(pkg: str, install_cmd: list = None) -> None:
    """检查包是否已安装，未安装则尝试安装。"""
    try:
        __import__(pkg)
        return
    except ImportError:
        print(f"[WARN] {pkg} not installed. Installing...")
        cmd = install_cmd if install_cmd else [sys.executable, "-m", "pip", "install", pkg]
        subprocess.check_call(cmd)


def _check_dependencies() -> None:
    """依赖检查：核心依赖自动安装，可选依赖给出提示。"""
    # 核心依赖
    _ensure_dependency("streamlit")
    for pkg in ["openai", "httpx", "pandas"]:
        _ensure_dependency(pkg)

    # 桌面模式依赖
    try:
        import pywebview  # noqa: F401
    except ImportError:
        print("[WARN] pywebview not installed. Desktop mode will be unavailable.")
        print("       Install with: pip install pywebview")

    # 可选依赖
    try:
        import crewai
        print(f"[OK] crewai {crewai.__version__}")
    except ImportError:
        print("[INFO] crewai not installed (optional, for storyboard workflow)")
        print("       Install with: pip install crewai langchain-openai")


def _launch_browser_mode(port: int) -> int:
    """浏览器模式：启动 Streamlit 并打开系统默认浏览器。"""
    import desktop_app
    proc = desktop_app._start_streamlit(port)
    log_thread = __import__("threading").Thread(
        target=desktop_app._log_streamlit_output, args=(proc,), daemon=True
    )
    log_thread.start()

    print(f"[INFO] 等待 Streamlit 服务就绪 (port={port})...")
    if not desktop_app._wait_for_server(port, timeout=60.0):
        print("[ERROR] Streamlit 服务在 60 秒内未启动")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 1

    url = f"http://127.0.0.1:{port}"
    print(f"[INFO] Streamlit 已就绪，正在打开浏览器: {url}")
    webbrowser.open(url)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI 剧本创作和制片管理综合工具 - 统一启动器"
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="使用系统默认浏览器打开网页版（默认使用 PyWebView 桌面窗口）",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="使用 PyWebView 桌面窗口打开（默认）",
    )
    args = parser.parse_args()

    # 默认桌面模式；只有显式 --browser 才走浏览器
    use_browser = args.browser and not args.desktop

    # Switch to the directory where this script lives
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print()
    print("=" * 60)
    print("  AI Screenwriter & Production Toolkit v1.0")
    print("  Creator Engine + Production Engine")
    print("=" * 60)
    print()
    print(f"  Working dir: {os.getcwd()}")
    print(f"  Mode: {'浏览器模式' if use_browser else '桌面窗口模式'}")
    print()

    # --- Check Python version ---
    if sys.version_info < (3, 10):
        print("[ERROR] Python 3.10+ required. Current:", sys.version)
        input("Press Enter to exit...")
        return 1
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    # --- Check app.py exists ---
    if not os.path.exists("app.py"):
        print("[ERROR] app.py not found in current directory!")
        input("Press Enter to exit...")
        return 1
    print("[OK] app.py found")

    # --- Check/install dependencies ---
    _check_dependencies()

    # --- Launch ---
    if use_browser:
        import desktop_app
        port = desktop_app._find_free_port()
        return _launch_browser_mode(port)
    else:
        # 复用 desktop_app 的完整桌面启动流程
        import desktop_app
        return desktop_app.main()


if __name__ == "__main__":
    sys.exit(main())
