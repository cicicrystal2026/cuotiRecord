import base64
import ctypes
import json
import os
import threading
from urllib.parse import urlparse

from .storage import DATA_DIR

CONFIG_FILE = DATA_DIR / "settings.json"
CONFIG_LOCK = threading.RLock()
DEFAULTS = {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "vision_model": "qwen3-vl-plus", "analysis_model": "qwen3.8-max"}


def protect(secret, encrypt=True):
    if os.name != "nt":
        raise ValueError("当前密钥保存仅支持Windows，请使用DASHSCOPE_API_KEY环境变量")
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    data = secret.encode("utf-8") if encrypt else base64.b64decode(secret)
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ValueError("Windows密钥加密或读取失败，请重新配置")
    try:
        result = ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)
    return base64.b64encode(result).decode() if encrypt else result.decode("utf-8")


def settings(include_secret=False):
    with CONFIG_LOCK:
        value = dict(DEFAULTS)
        if CONFIG_FILE.exists():
            value.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        secret = os.environ.get("DASHSCOPE_API_KEY", "")
        if not secret and value.get("protected_key"):
            try:
                secret = protect(value["protected_key"], False)
            except ValueError:
                secret = ""
        result = {key: value[key] for key in DEFAULTS}
        result["configured"] = bool(secret)
        result["environment_key"] = bool(os.environ.get("DASHSCOPE_API_KEY"))
        if include_secret:
            result["api_key"] = secret
        return result


def validate_endpoint(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        raise ValueError("模型地址必须是阿里云HTTPS接口地址")
    host = parsed.hostname or ""
    if not (host == "aliyuncs.com" or host.endswith(".aliyuncs.com")):
        raise ValueError("本版仅允许阿里云官方aliyuncs.com接口域名")
    if not parsed.path.rstrip("/").endswith("/v1"):
        raise ValueError("请填写以/v1结尾的OpenAI兼容接口地址")
    return url.rstrip("/")


def save_settings(value):
    with CONFIG_LOCK:
        old = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
        for key in DEFAULTS:
            text = str(value.get(key, old.get(key, DEFAULTS[key]))).strip()
            if not text or len(text) > 500:
                raise ValueError("模型配置不能为空或超过长度限制")
            old[key] = validate_endpoint(text) if key == "base_url" else text
        if value.get("clear_key"):
            old.pop("protected_key", None)
        if value.get("api_key"):
            if not isinstance(value["api_key"], str):
                raise ValueError("API Key格式不正确")
            key = value["api_key"].strip()
            if len(key) < 8 or len(key) > 400:
                raise ValueError("API Key格式不正确")
            old["protected_key"] = protect(key)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(CONFIG_FILE)
    return settings()
