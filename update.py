#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地在线更新器 (Local Updater)
=============================
用户在本地通过 git clone 部署本程序后，运行本脚本即可把代码更新到
GitHub 上的最新版本，无需重新手动下载压缩包。

用法：
  python update.py            # 拉取最新代码，并（若依赖有变化）安装依赖，然后提示重启
  python update.py --check    # 仅检查是否有可用更新，不改动任何文件
  python update.py --restart  # 更新完成后自动重启应用（重新运行 start.py）

前置条件：
  - 已安装 git 且在 PATH 中；
  - 当前目录所在仓库的 origin 指向 GitHub 上的本程序仓库；
  - 能访问 GitHub（公开仓库支持匿名 HTTPS 拉取）。

更新策略说明：
  - 采用「快进合并（--ff-only）」：只接受线性前进，绝不会覆盖你本地
    未推送的修改。若你改过代码导致无法快进，脚本会报错并提示你如何解决。
  - 仅当 requirements.txt 在本次更新中发生变化时才执行 pip install，
    避免无谓的重装。
"""

import os
import sys
import time
import argparse
import subprocess

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN_BRANCH = "main"
START_SCRIPT = "start.py"
REQ_FILE = "requirements.txt"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def _run_git(args, timeout=120):
    """在仓库根目录执行 git 命令，返回 CompletedProcess。"""
    return subprocess.run(
        ["git", "-C", REPO_ROOT, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def have_git():
    r = subprocess.run(["git", "--version"], capture_output=True, text=True)
    return r.returncode == 0


def is_git_repo():
    return os.path.isdir(os.path.join(REPO_ROOT, ".git"))


def get_remote_url():
    r = _run_git(["config", "--get", "remote.origin.url"])
    return (r.stdout or "").strip()


def to_https(url):
    """把 SSH 形式的远程地址转换为 HTTPS 地址（公开仓库可匿名拉取）。"""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("ssh://"):
        u = url[len("ssh://"):]
        if u.startswith("git@"):
            u = u[4:]
        host, _, path = u.partition(":")
        if not path:
            host, _, path = u.partition("/")
        return f"https://{host}/{path}"
    if url.startswith("git@"):
        host_path = url[4:]
        host, _, path = host_path.partition(":")
        return f"https://{host}/{path}"
    return url


def get_current_commit():
    """返回 (short_hash, date_str)，失败返回 ('unknown', '')。"""
    r = _run_git(["rev-parse", "--short", "HEAD"])
    if r.returncode != 0:
        return ("unknown", "")
    h = r.stdout.strip()
    d = _run_git(["log", "-1", "--format=%cs", "HEAD"])
    date = d.stdout.strip() if d.returncode == 0 else ""
    return (h, date)


# ---------------------------------------------------------------------------
# 远程同步
# ---------------------------------------------------------------------------

def ensure_fetch():
    """
    更新 origin/main 引用。
    先尝试用已配置的 remote 拉取；若因 SSH 鉴权失败，则临时把 origin 改为
    HTTPS 后重试（公开仓库可匿名拉取）。返回 (ok, error_msg)。
    """
    r = _run_git(["fetch", "origin", MAIN_BRANCH], timeout=180)
    if r.returncode == 0:
        return (True, "")
    err = (r.stderr or r.stdout or "").strip()
    # SSH 鉴权失败的典型提示
    if "Permission denied" in err or "Could not resolve" in err or "ssh" in err.lower():
        url = get_remote_url()
        https = to_https(url)
        if https and https != url:
            _log("INFO", f"SSH 拉取失败，尝试改用 HTTPS: {https}")
            _run_git(["remote", "set-url", "origin", https])
            r2 = _run_git(["fetch", "origin", MAIN_BRANCH], timeout=180)
            if r2.returncode == 0:
                return (True, "")
            return (False, (r2.stderr or r2.stdout or "").strip())
    return (False, err)


def get_behind_info():
    """返回 (behind_count, [subject_lines])。"""
    r = _run_git(["rev-list", "--count", f"HEAD..origin/{MAIN_BRANCH}"])
    if r.returncode != 0:
        return (0, [])
    try:
        behind = int((r.stdout or "0").strip() or 0)
    except ValueError:
        behind = 0
    subjects = []
    if behind > 0:
        max_n = min(behind, 20)
        s = _run_git(["log", "--oneline", f"-{max_n}", f"HEAD..origin/{MAIN_BRANCH}"])
        if s.returncode == 0:
            subjects = [ln for ln in s.stdout.splitlines() if ln.strip()]
    return (behind, subjects)


def requirements_changed():
    """本次更新是否改动了 requirements.txt。"""
    r = _run_git(["diff", "--name-only", "HEAD", f"origin/{MAIN_BRANCH}"])
    if r.returncode != 0:
        return False
    return REQ_FILE in (r.stdout or "")


# ---------------------------------------------------------------------------
# 对外动作
# ---------------------------------------------------------------------------

def do_check():
    _log("INFO", "正在连接 GitHub 检查更新...")
    ok, err = ensure_fetch()
    if not ok:
        _log("ERROR", f"无法获取远程更新信息：{err}")
        _log("INFO", "请检查网络连接，或确认本目录为 git 仓库且 origin 指向 GitHub。")
        return 2
    behind, subjects = get_behind_info()
    cur_h, cur_d = get_current_commit()
    if behind == 0:
        _log("OK", f"已是最新版本（{cur_h} · {cur_d}），无需更新。")
        return 0
    _log("OK", f"发现 {behind} 个可用更新（当前 {cur_h} · {cur_d}）：")
    for s in subjects[:20]:
        _log("  +", s)
    if behind > 20:
        _log("  +", f"... 其余 {behind - 20} 个更新略")
    return 1


def do_update():
    cur_h, cur_d = get_current_commit()
    _log("INFO", f"当前版本：{cur_h} · {cur_d}")
    _log("INFO", "正在拉取最新代码...")
    ok, err = ensure_fetch()
    if not ok:
        _log("ERROR", f"无法连接 GitHub：{err}")
        return 2

    # 检查本地是否领先（有未推送改动），避免误覆盖
    ahead = _run_git(["rev-list", "--count", f"origin/{MAIN_BRANCH}..HEAD"])
    if ahead.returncode == 0 and int((ahead.stdout or "0").strip() or 0) > 0:
        _log("WARN", "检测到本地存在未推送的提交，无法安全快进更新。")
        _log("INFO", "如需强制同步到线上版本（会丢弃本地改动），请先备份，再执行：")
        _log("INFO", "  git reset --hard origin/main")
        return 3

    behind, subjects = get_behind_info()
    if behind == 0:
        _log("OK", "已经是最新版本，无需更新。")
        return 0

    _log("INFO", f"即将拉取 {behind} 个更新：")
    for s in subjects[:20]:
        _log("  +", s)

    pull = _run_git(["pull", "--ff-only", "origin", MAIN_BRANCH], timeout=300)
    if pull.returncode != 0:
        _log("ERROR", f"更新失败（无法快进合并）：{pull.stderr or pull.stdout}")
        _log("INFO", "若你对代码做了本地修改，请先 stash/commit，或用 git reset --hard origin/main 同步。")
        return 4

    new_h, new_d = get_current_commit()
    _log("OK", f"代码已更新到 {new_h} · {new_d}")

    # 依赖安装（仅当 requirements.txt 变化）
    if requirements_changed():
        _log("INFO", f"{REQ_FILE} 有变化，正在安装/更新依赖...")
        inst = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", REQ_FILE, "--quiet"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600,
        )
        if inst.returncode != 0:
            _log("WARN", f"依赖安装失败，请手动执行：pip install -r {REQ_FILE}")
            tail = (inst.stderr or inst.stdout or "").strip()
            _log("WARN", tail[-500:] if tail else "")
        else:
            _log("OK", "依赖已更新。")
    else:
        _log("INFO", f"{REQ_FILE} 无变化，跳过依赖安装。")

    _log("OK", "更新完成！请重启应用以加载新代码（关闭后重新运行 python start.py）。")
    return 0


def restart_app():
    """更新后启动新的 start.py 实例并退出当前进程。"""
    target = os.path.join(REPO_ROOT, START_SCRIPT)
    if not os.path.exists(target):
        _log("WARN", f"未找到 {START_SCRIPT}，无法自动重启，请手动运行。")
        return
    _log("INFO", "正在重启应用...")
    flags = 0
    kwargs = {}
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            [sys.executable, target],
            cwd=REPO_ROOT,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception as e:
        _log("WARN", f"自动重启失败：{e}，请手动运行 python start.py")
        return
    time.sleep(2)
    os._exit(0)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="本地在线更新器：把程序更新到 GitHub 最新版本",
    )
    parser.add_argument("--check", action="store_true", help="仅检查更新，不改动文件")
    parser.add_argument("--restart", action="store_true", help="更新完成后自动重启应用")
    args = parser.parse_args()

    if not have_git():
        _log("ERROR", "未检测到 git，请先安装 git 并确保在 PATH 中。")
        return 1
    if not is_git_repo():
        _log("ERROR", "当前目录不是 git 仓库，无法在线更新。")
        _log("INFO", "请通过 `git clone <仓库地址>` 部署本程序，而非下载压缩包。")
        return 1

    if args.check:
        return do_check()

    rc = do_update()
    if rc == 0 and args.restart:
        restart_app()
    return rc


if __name__ == "__main__":
    sys.exit(main())
