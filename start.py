"""
AI Screenwriter & Production Toolkit - Web UI Launcher
=======================================================
网页版启动器：拉取代码后直接运行 `python start.py`，
自动启动 Streamlit 服务并在浏览器打开网页版。

用法：
  python start.py   # 启动网页版（自动安装缺失依赖、打开默认浏览器）

说明：本项目不再提供打包好的桌面安装包，用户拉取源码本地运行即可。
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

    # 可选依赖
    try:
        import crewai
        print(f"[OK] crewai {crewai.__version__}")
    except ImportError:
        print("[INFO] crewai not installed (optional, for storyboard workflow)")
        print("       Install with: pip install crewai langchain-openai")


def _launch_browser_mode(port: int) -> int:
    """浏览器模式：启动 Streamlit 并打开系统默认浏览器。"""
    import app_launcher
    proc = app_launcher._start_streamlit(port)
    log_thread = __import__("threading").Thread(
        target=app_launcher._log_streamlit_output, args=(proc,), daemon=True
    )
    log_thread.start()

    print(f"[INFO] 等待 Streamlit 服务就绪 (port={port})...")
    if not app_launcher._wait_for_server(port, timeout=60.0):
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
    # Switch to the directory where this script lives
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print()
    print("=" * 60)
    print("  AI 剧本创作和制片管理综合工具 v1.0")
    print("  Creator Engine + Production Engine")
    print("=" * 60)
    print()
    print(f"  Working dir: {os.getcwd()}")
    print(f"  UI mode: 浏览器网页版")
    print()
    print("  更新方式: 终端执行 `python update.py` 同步最新版本")
    print("           （或在网页左侧栏「🔄 在线更新」中一键更新）")
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

    # --- Launch web UI in browser ---
    import app_launcher
    port = app_launcher._find_free_port()
    return _launch_browser_mode(port)


if __name__ == "__main__":
    sys.exit(main())
