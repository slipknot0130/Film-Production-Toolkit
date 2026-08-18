"""
AI Screenwriter & Production Toolkit - Build Script
=====================================================
用 PyInstaller 把 Streamlit + PyWebView 项目打包成独立桌面程序。

使用方法：
  1. 安装 PyInstaller:
     pip install pyinstaller

  2. 运行打包脚本（会自动检测平台）：
     python build.py

  3. 产物位于：
     - Windows: dist/FilmProductionToolkit/FilmProductionToolkit.exe
     - macOS:   dist/FilmProductionToolkit/FilmProductionToolkit.app

  4. （可选）压缩成 zip 用于发布：
     python build.py --zip

注意：
  - 首次打包可能需要几分钟。
  - 单目录模式（onedir）比单文件模式更稳定、启动更快，也减少杀毒软件误报。
  - 如果你的 .venv 有问题（如此仓库的 pydantic 冲突），建议在干净的虚拟环境里打包。
"""

import os
import sys
import shutil
import argparse
import subprocess
import site
from pathlib import Path


APP_NAME = "FilmProductionToolkit"
ENTRY_SCRIPT = "desktop_app.py"


def _get_streamlit_static_path() -> str:
    """定位 streamlit 前端静态资源目录。"""
    try:
        import streamlit
        streamlit_pkg = Path(streamlit.__file__).parent
        static_dir = streamlit_pkg / "static"
        if static_dir.exists():
            return str(static_dir)
    except Exception:
        pass

    # fallback：在 site-packages 里找
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        if not sp:
            continue
        candidate = Path(sp) / "streamlit" / "static"
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("找不到 streamlit/static 目录，请确认 streamlit 已安装")


def _collect_data_files() -> list:
    """收集需要打包到程序目录的资源文件。"""
    files = []
    project_root = Path(__file__).parent

    # 关键入口与配置
    for name in ["app.py", "start.py", "desktop_app.py", "requirements.txt", ".env.example"]:
        src = project_root / name
        if src.exists():
            files.append((str(src), "."))

    # 资源目录
    for dirname in ["assets", "creator", "production", "shared", "harness", "tests"]:
        src = project_root / dirname
        if src.exists():
            files.append((str(src), dirname))

    # 根目录下的风格词、说明文件等
    for pattern in ["StyleTokens.txt", "README*.md", "MERGE_PLAN.md", "Seedance*.md", "setup_and_run.bat", "一键启动.bat"]:
        for src in project_root.glob(pattern):
            files.append((str(src), "."))

    # streamlit 前端静态资源
    files.append((_get_streamlit_static_path(), os.path.join("streamlit", "static")))

    return files


def _build_pyinstaller_args(zip_output: bool = False) -> list:
    """构造 PyInstaller 命令行参数。"""
    sep = ";" if sys.platform == "win32" else ":"
    data_args = []
    for src, dst in _collect_data_files():
        data_args.extend(["--add-data", f"{src}{sep}{dst}"])

    # 隐藏导入：Streamlit、CrewAI、LangChain 等有大量动态导入
    hidden_imports = [
        "streamlit",
        "streamlit.web.cli",
        "streamlit.runtime.scriptrunner.magic_funcs",
        "streamlit.components.v1",
        "openai",
        "httpx",
        "pandas",
        "numpy",
        "openpyxl",
        "docx",
        "requests",
        "dotenv",
        "webview",
        "webview.platforms.winforms",
        "webview.platforms.cocoa",
        "crewai",
        "crewai.agent",
        "crewai.task",
        "crewai.crew",
        "crewai.process",
        "langchain",
        "langchain_openai",
        "langchain_core",
        "pydantic",
        "pydantic_core",
    ]

    args = [
        ENTRY_SCRIPT,
        "--name", APP_NAME,
        "--onedir",
        "--noconfirm",
        "--clean",
        "--console",  # 保留控制台用于首次运行调试；稳定后可改为 --windowed
        "--icon", "assets/app_icon.ico" if os.path.exists("assets/app_icon.ico") else "NONE",
    ] + data_args

    for name in hidden_imports:
        args.extend(["--hidden-import", name])

    # 排除测试/开发用的大包（可选）
    # args.extend(["--exclude-module", "pytest"])

    return args


def _run_pyinstaller(args: list) -> int:
    """调用 PyInstaller。"""
    try:
        import PyInstaller.__main__
        print("[INFO] 使用 PyInstaller API 打包...")
        PyInstaller.__main__.run(args)
        return 0
    except ImportError:
        print("[INFO] 未安装 PyInstaller，尝试通过 subprocess 调用...")
        cmd = [sys.executable, "-m", "PyInstaller"] + args
        return subprocess.call(cmd)


def _create_zip() -> str:
    """把产物压缩成 zip，便于 GitHub Release 分发。"""
    dist_dir = Path("dist") / APP_NAME
    if not dist_dir.exists():
        raise FileNotFoundError(f"找不到产物目录: {dist_dir}")

    zip_name = f"{APP_NAME}-v1.0.0-{sys.platform}"
    if sys.platform == "win32":
        zip_name += "-x64"
    elif sys.platform == "darwin":
        zip_name += "-universal"

    archive_path = Path("dist") / zip_name
    shutil.make_archive(str(archive_path), "zip", root_dir="dist", base_dir=APP_NAME)
    return str(archive_path) + ".zip"


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 AI 剧本创作和制片管理综合工具为桌面程序")
    parser.add_argument("--zip", action="store_true", help="打包后额外生成 zip 压缩包")
    args = parser.parse_args()

    print("=" * 60)
    print("  AI 剧本创作和制片管理综合工具 - 打包脚本")
    print("=" * 60)
    print(f"  平台: {sys.platform}")
    print(f"  Python: {sys.version}")
    print(f"  入口: {ENTRY_SCRIPT}")
    print()

    # 清理旧产物
    for dirname in ["build", "dist"]:
        if os.path.isdir(dirname):
            print(f"[INFO] 清理旧目录: {dirname}")
            shutil.rmtree(dirname)

    pyinst_args = _build_pyinstaller_args(zip_output=args.zip)
    ret = _run_pyinstaller(pyinst_args)
    if ret != 0:
        print("[ERROR] PyInstaller 打包失败")
        return ret

    print()
    print("[OK] 打包完成")
    print(f"  产物目录: dist/{APP_NAME}/")
    if sys.platform == "win32":
        print(f"  可执行文件: dist/{APP_NAME}/{APP_NAME}.exe")
    elif sys.platform == "darwin":
        print(f"  应用程序: dist/{APP_NAME}/{APP_NAME}.app")
    else:
        print(f"  可执行文件: dist/{APP_NAME}/{APP_NAME}")

    if args.zip:
        try:
            zip_path = _create_zip()
            print(f"  发布包: {zip_path}")
        except Exception as exc:
            print(f"[WARN] 生成 zip 失败: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
