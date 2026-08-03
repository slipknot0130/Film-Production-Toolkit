"""
production/llm_utils.py — 制片流LLM工具函数
============================================

从 storyboard_local.py 提取的通用工具函数：
- call_llm_json: JSON强制输出+自动重试
- split_script_smart: 智能文本分块
- read_docx: 读取docx文件
- get_llm_client: 创建OpenAI客户端（制片流专用）
- get_llm_kwargs: 获取LLM参数
"""

import streamlit as st
import json
import re
import os
import sys
import traceback
import httpx
from openai import OpenAI


def _safe_print(msg: str):
    """跨平台安全打印：Windows 控制台/管道非 UTF-8 时回退到 errors='replace'"""
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            sys.stdout.buffer.write(msg.encode("utf-8", errors="replace") + b"\n")
        except Exception:
            pass


# =============================================================================
# Ollama 自动拉取（复用 shared 层）
# =============================================================================

def ensure_ollama_model(model_name):
    """Ollama 自动拉取模型（委托给shared层）"""
    from shared.llm_config import ensure_ollama_model as _ensure
    return _ensure(model_name)


# =============================================================================
# OpenAI Client 创建（制片流专用，复用 shared 层的httpx长超时方案）
# =============================================================================

# 复用同一个 httpx.Client，避免 Streamlit 频繁 rerun 下 TCP 连接泄漏（FD 耗尽）
_httpx_client_singleton = None

def _get_shared_http_client():
    global _httpx_client_singleton
    if _httpx_client_singleton is None:
        _httpx_client_singleton = httpx.Client(timeout=600.0, trust_env=False)
    return _httpx_client_singleton


def get_llm_client(provider, api_base, api_key):
    """创建 OpenAI Client（制片流接口，兼容B的参数名）"""
    custom_http_client = _get_shared_http_client()
    if "Ollama" in provider:
        return OpenAI(base_url='http://localhost:11434/v1', api_key='ollama', http_client=custom_http_client)
    else:
        return OpenAI(base_url=api_base, api_key=api_key, http_client=custom_http_client)


def get_llm_kwargs(provider):
    """获取LLM调用参数"""
    if "Ollama" in provider:
        return {"extra_body": {"options": {"num_ctx": 100000, "num_predict": 8192}}}
    else:
        return {"max_tokens": 8192}


# =============================================================================
# call_llm_json — JSON强制输出+自动重试
# =============================================================================

def call_llm_json(client, model_name, sys_prompt, user_prompt, kwargs, temp=0.0, max_retries=3):
    """
    v5.0 优化：调用LLM并强制JSON输出，失败自动重试（max_retries=3，减少token浪费）。
    内置5层JSON解析降级策略，单次重试成功率已很高，无需5次重试。
    """
    strict_sys_prompt = sys_prompt + "\n\n【严格系统指令】：你必须输出合法的 JSON 格式。绝对禁止在 JSON 的字符串值内部使用未转义的双引号、绝对禁止漏掉键值对之间的逗号。"

    def _try_parse_json(raw_text: str) -> dict:
        """尝试多种方式解析JSON，返回最可能的结果"""
        # 方法1：直接解析原始文本
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # 方法2：去除markdown代码块后解析
        cleaned = raw_text
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            if len(parts) >= 3:
                cleaned = parts[1]
                if cleaned.startswith("json") or cleaned.startswith("JSON"):
                    cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 方法3：提取最外层花括号包裹的内容
        start, end = cleaned.find('{'), cleaned.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end+1])
            except json.JSONDecodeError:
                pass

        # 方法4：尝试修复常见JSON错误
        fixed = _fix_common_json_errors(cleaned[start:end+1] if start != -1 and end != -1 else cleaned)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 方法5：提取第一个有效的JSON对象（逐字符尝试）
        if start != -1:
            for i in range(end, start + 10, -1):
                try:
                    return json.loads(cleaned[start:i+1])
                except json.JSONDecodeError:
                    continue

        raise ValueError("所有JSON解析方法均失败")

    def _fix_common_json_errors(text: str) -> str:
        """尝试修复常见的JSON格式错误"""
        # 修复1：去除多余的尾随逗号（在}或]之前的逗号）
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        # 修复2：将单引号替换为双引号（只在键/值的外层引号）
        # 注意：这个修复有风险，但值得尝试
        text = re.sub(r"(?<=[{:,\[])\s*'([^']*?)'\s*:", r'"\1":', text)
        text = re.sub(r":\s*'([^']*?)'\s*(?=[,}\]])", r':"\1"', text)
        # 修复3/4：仅对 JSON 字符串值内部的「真实」换行/回车/制表符做转义
        # （原先的无差别全局 replace 会把结构性空白与已正确转义的字符串也转义，
        #   反而把合法 JSON 弄坏；这里用正则只命中 "..." 字符串值内部的内容）
        try:
            def _escape_str(m):
                s = m.group(0)
                return s.replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
            text = re.sub(r'"((?:[^"\\]|\\.)*)"', _escape_str, text)
        except Exception:
            pass
        return text

    last_error = ""
    for attempt in range(max_retries):
        try:
            # 每次重试略微提高温度，增加输出多样性
            current_temp = min(temp + attempt * 0.05, 0.5)

            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "system", "content": strict_sys_prompt}, {"role": "user", "content": user_prompt}],
                temperature=current_temp,
                response_format={"type": "json_object"},
                **kwargs
            )
            res = response.choices[0].message.content.strip()
            res = re.sub(r'💭.*?💭', '', res, flags=re.DOTALL).strip()

            # 尝试解析
            result = _try_parse_json(res)

            # 如果解析成功且是dict类型，返回
            if isinstance(result, dict):
                return result
            else:
                raise ValueError(f"解析结果不是字典类型: {type(result)}")

        except Exception as e:
            last_error = str(e)
            # 保存原始响应用于调试
            raw_preview = res[:200] if 'res' in dir() else "N/A"
            tb = traceback.format_exc()
            _safe_print(f"[call_llm_json] 尝试 {attempt + 1}/{max_retries} 失败: {last_error}")
            _safe_print(f"[call_llm_json] 原始响应预览: {raw_preview}...")
            _safe_print(f"[call_llm_json] Traceback:\n{tb}")

            if attempt < max_retries - 1:
                st.toast(f"⚠️ JSON 解析遇到错误，正在启动第 {attempt + 2} 次自动重试...")
            else:
                st.error(f"❌ 大模型连接或解析失败，已达最大重试次数（{max_retries}次）。错误详情: {last_error}")
                _safe_print(f"[call_llm_json] 最终失败，返回空字典。最后错误: {last_error}")

    # 所有重试均失败，返回最小可用结果
    return {}


# =============================================================================
# 文本分块
# =============================================================================

def split_script_smart(text, max_chars=900):
    """智能文本分块（max_chars 字符/块）。

    优先按换行/段落边界切分；若单个段落超过 max_chars，则对该段落做
    二次切分（按句子边界，超长单句再按固定字符窗口硬切），确保**任何**
    一个 chunk 都不会超过 max_chars。

    历史 bug：旧实现对超过 max_chars 的单段落不再二次切分，导致整篇
    几乎无换行的长剧本退化成 1 个超大块；该块在下游被 SAFE_CAP(28 镜)
    封顶，最终只产出约 2 分钟分镜。本修复通过二次切分彻底解决。
    """
    if not text or not text.strip():
        return []

    chunks = []
    current_chunk = ""

    def _flush():
        nonlocal current_chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        current_chunk = ""

    # 句子/停顿分隔符（含中英文句号、感叹、问号、分号）
    SENT_ENDERS = set("。！？!?；;\n")

    def _split_long_paragraph(p):
        """对超过 max_chars 的段落按句子/窗口二次切分，返回若干 <= max_chars 的子串。"""
        pieces = []
        buf = ""
        for ch in p:
            buf += ch
            # 硬窗口保护：累积到上限且当前不是句末，立即切（防单句无限增长）
            if len(buf) >= max_chars and ch not in SENT_ENDERS:
                pieces.append(buf)
                buf = ""
            # 句末且已累积到一定量：在句末切，避免产生过碎的块
            elif ch in SENT_ENDERS and len(buf) >= max_chars * 0.4:
                pieces.append(buf)
                buf = ""
        if buf.strip():
            pieces.append(buf.strip())
        return pieces

    for p in text.split('\n'):
        p = p.rstrip('\n')
        if not p.strip():
            # 空行：仅作为段落分隔符保留，**不**强制收尾当前块。
            #
            # 历史 bug（31ee631 引入）：这里曾直接 _flush()，导致
            # 「场标 + 空行 + 台词 + 空行 + 动作」这类最常规的剧本排版
            # 被打碎成几十上百个十几字的小块。下游 Crew 会对每个块各跑
            # 一次 Director+QA，既极慢又产出大量垃圾镜头。
            # 正确策略：空行只写入分隔符，真正的切块只由 max_chars 决定。
            if current_chunk and not current_chunk.endswith("\n\n"):
                current_chunk += "\n"
            continue

        if len(p) > max_chars:
            # 超长段落：先 flush 当前块，再对该段落二次切分
            _flush()
            for sub in _split_long_paragraph(p):
                if len(current_chunk) + len(sub) > max_chars:
                    _flush()
                    current_chunk = sub + "\n"
                else:
                    current_chunk += sub + "\n"
            continue

        if len(current_chunk) + len(p) > max_chars:
            _flush()
            current_chunk = p + "\n"
        else:
            current_chunk += p + "\n"

    _flush()
    return chunks


# =============================================================================
# 文件读取
# =============================================================================

def read_docx(file):
    """读取 .docx 文件，提取所有文本内容"""
    import docx
    doc = docx.Document(file)
    text = []
    for child in doc.element.body:
        if child.tag.endswith('p'):
            text.append(docx.text.paragraph.Paragraph(child, doc).text)
        elif child.tag.endswith('tbl'):
            table = docx.table.Table(child, doc)
            seen_cells = set()
            for row in table.rows:
                for cell in row.cells:
                    if cell._tc in seen_cells:
                        continue
                    seen_cells.add(cell._tc)
                    for p in cell.paragraphs:
                        if p.text.strip():
                            text.append(p.text.strip())
    return '\n'.join(text)


def _read_text_utf8_fallback(uploaded_file):
    """读取上传文本文件，utf-8 失败回退到常见中文编码，避免 UnicodeDecodeError 崩溃。"""
    try:
        raw = uploaded_file.read()
    except Exception:
        st.error("❌ 文件读取失败")
        return ""
    for enc in ("utf-8", "gbk", "gb18030", "shift_jis", "latin-1"):
        try:
            return str(raw, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    st.error("❌ 无法解码文件（已尝试 utf-8/gbk/shift_jis 等编码）")
    return ""


def read_uploaded_file(uploaded_file):
    """读取上传的文件（支持 .docx / .txt / .md）"""
    if uploaded_file is None:
        return ""

    file_name = uploaded_file.name.lower()
    if file_name.endswith('.docx'):
        return read_docx(uploaded_file)
    elif file_name.endswith(('.txt', '.md')):
        return _read_text_utf8_fallback(uploaded_file)
    else:
        # 尝试作为文本读取
        return _read_text_utf8_fallback(uploaded_file)
