"""
AI Screenwriter & Production Toolkit - Web UI Launcher
=======================================================
提供 Streamlit 本地服务启动逻辑，供 start.py 的网页版调用。

不再包含任何桌面窗口（PyWebView）打包相关代码。
用户只需拉取代码，运行 `python start.py` 即可在浏览器使用 Web UI。
"""

import os
import sys
import time
import socket
import subprocess
import threading
import logging


# 日志写到程序同级目录，方便用户反馈问题
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app_launcher.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("app_launcher")


# ── 路径处理：打包后 vs 源码运行 ────────────────────────────────────────────
def _get_app_dir() -> str:
    """返回程序根目录（打包后 _MEIPASS 或源码目录）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后的临时目录
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _get_work_dir() -> str:
    """返回工作目录（可写，用户数据、.env 等应放在这里）。"""
    if getattr(sys, "frozen", False):
        # 打包后放在可执行文件所在目录，避免临时目录被清理
        return os.path.dirname(sys.executable)
    return _get_app_dir()


APP_DIR = _get_app_dir()
WORK_DIR = _get_work_dir()
os.chdir(WORK_DIR)


# ── 启动参数与配置 ─────────────────────────────────────────────────────────
APP_TITLE = "AI 剧本创作和制片管理综合工具"
DEFAULT_PORT = 8590
PORT_RANGE = range(8590, 8610)


def _find_free_port() -> int:
    """在 PORT_RANGE 中找一个可用端口。"""
    for port in PORT_RANGE:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError(f"端口 {list(PORT_RANGE)} 全部被占用")


def _start_streamlit(port: int) -> subprocess.Popen:
    """启动 Streamlit 子进程。"""
    # 强制本地回环，避免外部访问
    env = os.environ.copy()
    env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    env["STREAMLIT_SERVER_ADDRESS"] = "127.0.0.1"
    env["STREAMLIT_SERVER_PORT"] = str(port)
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_ENABLE_CORS"] = "false"
    env["STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION"] = "false"
    # 确保中文不乱码
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    app_path = os.path.join(APP_DIR, "app.py")
    if not os.path.exists(app_path):
        raise FileNotFoundError(f"找不到入口文件: {app_path}")

    # 打包后 sys.executable 就是 exe 本身，需要用内置 Python 解释器
    if getattr(sys, "frozen", False):
        # PyInstaller 单目录模式下 Python 解释器在 _internal/python.exe
        python_exe = os.path.join(os.path.dirname(sys.executable), "_internal", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = os.path.join(APP_DIR, "python.exe")
        if not os.path.exists(python_exe):
            python_exe = sys.executable  # fallback
    else:
        python_exe = sys.executable

    cmd = [
        python_exe,
        "-m",
        "streamlit",
        "run",
        app_path,
        "--server.port",
        str(port),
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--server.enableCORS",
        "false",
        "--server.enableXsrfProtection",
        "false",
    ]

    logger.info("启动 Streamlit: %s", " ".join(cmd))
    return subprocess.Popen(
        cmd,
        cwd=WORK_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _wait_for_server(port: int, timeout: float = 60.0) -> bool:
    """轮询等待 Streamlit 启动完成。"""
    start = time.time()
    while time.time() - start < timeout:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.5)
            sock.connect(("127.0.0.1", port))
            return True
        except OSError:
            time.sleep(0.2)
        finally:
            sock.close()
    return False


def _log_streamlit_output(proc: subprocess.Popen) -> None:
    """后台线程：把 Streamlit 日志输出到 app_launcher.log。"""
    try:
        for line in proc.stdout:
            if line:
                logger.info("[Streamlit] %s", line.rstrip())
    except Exception as exc:
        logger.error("读取 Streamlit 日志出错: %s", exc)


# 本模块只提供 Streamlit 本地启动器逻辑（供 start.py 网页版调用）。
# 不再包含任何桌面窗口（PyWebView）打包相关代码。

