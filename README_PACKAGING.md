# AI 剧本创作和制片管理综合工具 - 桌面打包与发布指南

本项目基于 **Streamlit + PyWebView** 构建，可通过 PyInstaller 打包为 Windows / macOS 独立桌面程序，并借助 GitHub Actions 自动发布到 GitHub Releases。

---

## 目录

- [运行方式](#运行方式)
- [快速开始](#快速开始)
- [本地手动打包](#本地手动打包)
- [自动发布（GitHub Actions）](#自动发布github-actions)
- [常见问题](#常见问题)

---

## 运行方式

本项目提供两种运行形态，底层共用同一套 Streamlit 服务，功能完全一致：

| 形态 | 命令 / 操作 | 说明 |
|------|------------|------|
| **桌面窗口版（默认）** | `python start.py` 或 `python desktop_app.py` | 用 PyWebView 打开独立窗口，推荐 |
| **桌面窗口版（显式）** | `python start.py --desktop` | 同上 |
| **浏览器网页版** | `python start.py --browser` | 用系统默认浏览器打开网页 |
| **一键启动（Windows）** | 双击 `一键启动.bat` | 默认启动桌面窗口，失败时回退到浏览器 |
| **一键部署（Windows）** | 双击 `setup_and_run.bat` | 检查依赖后启动桌面窗口 |

> **注意**：所有形态访问的都是同一个 Streamlit 后端，源代码业务逻辑没有任何改动。

---

## 快速开始

### 1. 安装打包依赖

```bash
pip install pyinstaller
```

### 2. 一键打包

```bash
python build.py
```

打包完成后：

- **Windows**：`dist/FilmProductionToolkit/FilmProductionToolkit.exe`
- **macOS**：`dist/FilmProductionToolkit/FilmProductionToolkit.app`

### 3. 生成 zip 发布包

```bash
python build.py --zip
```

产物：`dist/FilmProductionToolkit-v1.0.0-win32-x64.zip`

---

## 本地手动打包

### 环境要求

- Python 3.10+
- 所有 `requirements.txt` 依赖已安装
- 建议在一个**干净的虚拟环境**中打包，避免 `.venv` 中的版本冲突

### 推荐步骤

```bash
# 1. 创建干净虚拟环境
python -m venv venv-pack

# 2. Windows 激活
venv-pack\Scripts\activate

# 3. 安装依赖与 PyInstaller
pip install -r requirements.txt
pip install pyinstaller pywebview

# 4. 打包
python build.py --zip
```

### 打包模式说明

`build.py` 使用 `--onedir`（单目录）模式：

- 启动速度比单文件快
- 被杀毒软件误报的概率更低
- 用户看到的仍是一个 `.exe` / `.app`，无感知差异

---

## 自动发布（GitHub Actions）

### 触发方式

给当前 commit 打一个 tag：

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions 会自动：

1. 在 `windows-latest` 和 `macos-13` 上分别打包
2. 生成 zip 文件
3. 创建 GitHub Release 并上传两个平台安装包

### 手动触发

也可以在 GitHub 仓库页面进入 **Actions → Build Desktop Release → Run workflow**，输入版本号手动运行。

---

## 常见问题

### Q1: 打包后程序很大（> 500MB）？

A: 正常。Streamlit + CrewAI + LangChain + pandas + numpy 本身较大。可通过以下方式优化：

- 使用 `--onedir`（默认已用）
- 在 `build.py` 中取消注释 `--exclude-module pytest` 等排除项
- 使用 UPX 压缩（需本机安装 UPX 并在 build.py 中启用）

### Q2: 双击 exe 后黑窗一闪就消失？

A: 查看程序同级目录下的 `desktop_app.log`，里面会记录 Streamlit 启动失败原因。常见原因：

- `.env` 文件缺失（首次运行会自动从 `.env.example` 复制）
- 端口 8590-8609 被占用
- `streamlit/static` 静态资源未被打包进去

### Q3: macOS 提示「无法打开，因为无法验证开发者」？

A: 因为未签名。用户需要在 **系统设置 → 隐私与安全性** 中点击「仍要打开」。若要做正式分发，需要申请 Apple Developer ID 并签名。

### Q4: 杀毒软件报毒？

A: PyInstaller 打包的程序有时会被 Windows Defender 误报。建议：

- 使用 `--onedir` 模式（已默认）
- 向杀毒软件提交误报申诉
- 如需正式分发，考虑代码签名证书

### Q5: 可以打包成单文件 exe 吗？

A: 可以，但不推荐。把 `build.py` 中的 `"--onedir"` 改为 `"--onefile"` 即可。单文件每次启动都需要解包，启动慢且更容易被杀毒软件误报。

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `desktop_app.py` | PyWebView 桌面窗口入口 |
| `build.py` | PyInstaller 打包脚本 |
| `.github/workflows/build-release.yml` | GitHub Actions 自动打包发版 |
| `.env.example` | 默认环境变量模板 |
| `README_PACKAGING.md` | 本说明文档 |
