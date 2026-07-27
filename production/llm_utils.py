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

def get_llm_client(provider, api_base, api_key):
    """创建 OpenAI Client（制片流接口，兼容B的参数名）"""
    custom_http_client = httpx.Client(timeout=600.0, trust_env=False)
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
        # 修复3：修复未转义的换行符
        text = text.replace('\n', '\\n')
        # 修复4：修复未转义的制表符
        text = text.replace('\t', '\\t')
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
    """智能文本分块（900字符/块），按段落边界切分"""
    paragraphs = text.split('\n')
    chunks, current_chunk = [], ""
    for p in paragraphs:
        if len(current_chunk) + len(p) > max_chars:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = p + "\n"
        else:
            current_chunk += p + "\n"
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
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


def read_uploaded_file(uploaded_file):
    """读取上传的文件（支持 .docx / .txt / .md）"""
    if uploaded_file is None:
        return ""

    file_name = uploaded_file.name.lower()
    if file_name.endswith('.docx'):
        return read_docx(uploaded_file)
    elif file_name.endswith(('.txt', '.md')):
        return str(uploaded_file.read(), encoding='utf-8')
    else:
        # 尝试作为文本读取
        try:
            return str(uploaded_file.read(), encoding='utf-8')
        except Exception:
            st.error(f"❌ 不支持的文件格式: {file_name}")
            return ""
