"""动态 LangChain 类加载，供 provider 的 use_class 配置使用。

设计参考 Deer Flow 的 reflection/resolvers.py，精简为 Yuxi 所需的聊天模型场景。
管理员可在供应商 extra_json 中配置 ``use_class``（如 ``langchain_ollama:ChatOllama``），
运行时动态导入并实例化，无需修改后端代码即可接入新的自托管框架。
"""

from importlib import import_module

from langchain.chat_models import BaseChatModel

from yuxi.utils.logging_config import logger

_KNOWN_PACKAGES = {
    "langchain_ollama": "langchain-ollama",
    "langchain_anthropic": "langchain-anthropic",
    "langchain_google_genai": "langchain-google-genai",
}


def resolve_chat_model_class(class_path: str) -> type[BaseChatModel]:
    """从 ``module:ClassName`` 路径动态加载 LangChain Chat 模型类。

    示例::

        resolve_chat_model_class("langchain_ollama:ChatOllama")
    """
    try:
        module_path, class_name = class_path.rsplit(":", 1)
    except ValueError as err:
        raise ValueError(
            f"use_class 格式错误: '{class_path}'，"
            f"应为 'module:ClassName'（如 'langchain_ollama:ChatOllama'）"
        ) from err

    try:
        module = import_module(module_path)
    except ImportError as err:
        package = _KNOWN_PACKAGES.get(module_path, module_path.replace("_", "-"))
        raise ImportError(
            f"无法导入 {module_path}，请安装依赖: uv pip install {package}"
        ) from err

    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"{module_path} 中未定义 {class_name}")
    if not (isinstance(cls, type) and issubclass(cls, BaseChatModel)):
        raise ValueError(f"{class_path} 不是 BaseChatModel 的子类")

    logger.debug(f"Resolved use_class '{class_path}' → {cls.__name__}")
    return cls
