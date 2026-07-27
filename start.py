"""
AI Screenwriter & Production Toolkit - Launcher
=================================================
Unified entry point: starts Streamlit app with auto-dependency check.
Safe to double-click on Windows regardless of system encoding.
"""

import sys
import os
import subprocess


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


def main():
    # Switch to the directory where this script lives
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print()
    print("=" * 60)
    print("  AI Screenwriter & Production Toolkit v1.0")
    print("  Creator Engine + Production Engine")
    print("=" * 60)
    print()
    print(f"  Working dir: {os.getcwd()}")
    print()

    # --- Check Python version ---
    if sys.version_info < (3, 10):
        print("[ERROR] Python 3.10+ required. Current:", sys.version)
        input("Press Enter to exit...")
        sys.exit(1)
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    # --- Check app.py exists ---
    if not os.path.exists("app.py"):
        print("[ERROR] app.py not found in current directory!")
        input("Press Enter to exit...")
        sys.exit(1)
    print("[OK] app.py found")

    # --- Check/install streamlit ---
    try:
        import streamlit
        print(f"[OK] streamlit {streamlit.__version__}")
    except ImportError:
        print("[WARN] streamlit not installed. Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    # --- Check other key dependencies ---
    for pkg in ["openai", "httpx", "pandas"]:
        try:
            __import__(pkg)
            print(f"[OK] {pkg}")
        except ImportError:
            print(f"[WARN] {pkg} not installed. Installing...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    # --- Optional: crewai ---
    try:
        import crewai
        print(f"[OK] crewai {crewai.__version__}")
    except ImportError:
        print("[INFO] crewai not installed (optional, for storyboard workflow)")
        print("       Install with: pip install crewai langchain-openai")

    # --- Find available port ---
    import socket
    port = None
    # 使用 8590-8609，避开 Windows 系统保留端口范围 8455-8554
    for try_port in range(8590, 8610):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", try_port))
            sock.close()
            port = try_port
            break
        except OSError as e:
            sock.close()
            if e.winerror == 10013:
                continue  # 系统保留端口，静默跳过
            continue       # 端口被占用，试下一个

    if port is None:
        print("[ERROR] Ports 8590-8609 are all in use!")
        print("        Please close other Streamlit apps or free up a port.")
        input("Press Enter to exit...")
        sys.exit(1)

    print()
    print(f"[INFO] Starting Streamlit on port {port}...")
    print(f"[INFO] Browser will open http://localhost:{port}")
    print("[INFO] Press Ctrl+C to stop")
    print()

    # --- Launch streamlit ---
    try:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.port", str(port)],
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.")
    except Exception as e:
        print(f"[ERROR] {e}")

    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
