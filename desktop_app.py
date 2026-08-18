"""
AI Screenwriter & Production Toolkit - Desktop Shell
======================================================
用 PyWebView 把 Streamlit 网页应用包装成独立桌面窗口。

运行方式：
  开发环境: python desktop_app.py
  打包环境: 由 PyInstaller 生成 FilmProductionToolkit.exe 后双击运行

Windows / macOS 通用。
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
        logging.FileHandler("desktop_app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("desktop_app")


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
    """后台线程：把 Streamlit 日志输出到 desktop_app.log。"""
    try:
        for line in proc.stdout:
            if line:
                logger.info("[Streamlit] %s", line.rstrip())
    except Exception as exc:
        logger.error("读取 Streamlit 日志出错: %s", exc)


# ── PyWebView 窗口 ──────────────────────────────────────────────────────────
def create_window(url: str, width: int = 1440, height: int = 900) -> None:
    """创建桌面窗口并加载本地 Streamlit 服务。"""
    import webview  # 延迟导入：仅桌面模式需要，浏览器模式无需安装
    webview.create_window(
        title=APP_TITLE,
        url=url,
        width=width,
        height=height,
        min_size=(1024, 640),
        text_select=True,
        confirm_close=True,
    )
    webview.start(
        debug=False,
        http_server=False,
        user_agent="FilmProductionToolkitDesktop/1.0",
    )


# ── 主流程 ─────────────────────────────────────────────────────────────────
def main() -> int:
    logger.info("=" * 60)
    logger.info("  %s v1.0 - Desktop", APP_TITLE)
    logger.info("  APP_DIR:  %s", APP_DIR)
    logger.info("  WORK_DIR: %s", WORK_DIR)
    logger.info("=" * 60)

    # 首次运行：从 .env.example 复制一份 .env（不覆盖已有）
    env_example = os.path.join(APP_DIR, ".env.example")
    env_file = os.path.join(WORK_DIR, ".env")
    if os.path.exists(env_example) and not os.path.exists(env_file):
        try:
            with open(env_example, "r", encoding="utf-8") as src, \
                 open(env_file, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            logger.info("已创建默认 .env 配置文件: %s", env_file)
        except Exception as exc:
            logger.warning("复制 .env.example 失败: %s", exc)

    port = _find_free_port()
    proc = _start_streamlit(port)

    # 启动日志转发线程
    log_thread = threading.Thread(target=_log_streamlit_output, args=(proc,), daemon=True)
    log_thread.start()

    logger.info("等待 Streamlit 服务就绪 (port=%d)...", port)
    if not _wait_for_server(port, timeout=60.0):
        logger.error("Streamlit 服务在 60 秒内未启动")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 1

    url = f"http://127.0.0.1:{port}"
    logger.info("Streamlit 已就绪，打开桌面窗口: %s", url)

    try:
        create_window(url)
    except Exception as exc:
        logger.exception("桌面窗口异常退出: %s", exc)
    finally:
        logger.info("正在关闭 Streamlit 子进程...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        logger.info("已退出")

    return 0


if __name__ == "__main__":
    sys.exit(main())
