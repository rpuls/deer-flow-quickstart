"""Provider catalog offered by the quickstart onboarding UI.

Each entry knows how to turn "an API key the operator pasted into the web UI"
into a valid ``config.yaml`` fragment: which LangChain class to instantiate,
which YAML field carries the credential, the default endpoint, and the
thinking/vision capability flags DeerFlow needs in order to expose the model
properly in the chat UI.

Model ids go stale faster than anything else here, so the presets below are a
convenience, not a contract: nearly every provider also declares a
``discovery`` kind, which powers live model listing in the UI
(``POST /api/quickstart/llm/{id}/discover``). Operators can always type a model
id by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

ThinkingStyle = Literal["none", "openai_compat", "anthropic", "ollama"]
# How live model discovery talks to the provider. "none" means the UI must
# fall back to presets and hand-typed model ids.
DiscoveryKind = Literal["none", "openai", "anthropic", "google", "ollama"]

# Enable/disable payloads for providers that gate reasoning behind a request
# field. Mirrors scripts/wizard/providers.py so the UI and the CLI wizard
# produce equivalent model entries.
OPENAI_COMPAT_THINKING: dict[str, Any] = {
    "when_thinking_enabled": {"extra_body": {"thinking": {"type": "enabled"}}},
    "when_thinking_disabled": {"extra_body": {"thinking": {"type": "disabled"}}},
}

ANTHROPIC_THINKING: dict[str, Any] = {
    "when_thinking_enabled": {"thinking": {"type": "enabled", "budget_tokens": 4096}},
    "when_thinking_disabled": {"thinking": {"type": "disabled"}},
}

OLLAMA_THINKING: dict[str, Any] = {"reasoning": True}


@dataclass(frozen=True)
class ModelPreset:
    """A model the UI suggests for a provider."""

    id: str
    label: str
    context_window: int | None = None
    max_tokens: int | None = None
    supports_vision: bool = False
    supports_thinking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "context_window": self.context_window,
            "max_tokens": self.max_tokens,
            "supports_vision": self.supports_vision,
            "supports_thinking": self.supports_thinking,
        }


@dataclass(frozen=True)
class LLMProviderSpec:
    """How to build ``config.yaml`` model entries for one LLM provider."""

    id: str
    label: str
    description: str
    use: str
    presets: tuple[ModelPreset, ...] = ()
    # YAML key that carries the credential. Providers disagree: ChatOpenAI wants
    # ``api_key``, ChatGoogleGenerativeAI wants ``gemini_api_key``.
    api_key_field: str = "api_key"
    # YAML key that carries the endpoint, and its default value. ChatDeepSeek
    # declares ``api_base``; every other BaseChatOpenAI subclass uses ``base_url``.
    base_url_field: str | None = "base_url"
    default_base_url: str | None = None
    requires_api_key: bool = True
    # True when there is no sensible default endpoint (self-hosted, Azure, ...).
    requires_base_url: bool = False
    # How to enumerate this provider's models live, so the UI never depends on
    # the presets above staying current.
    discovery: DiscoveryKind = "openai"
    thinking: ThinkingStyle = "none"
    extra_config: dict[str, Any] = field(default_factory=dict)
    # Extra of the deerflow-harness distribution this provider needs, if any.
    requires_extra: str | None = None
    signup_url: str | None = None
    docs_url: str | None = None
    # Free-form badges rendered by the UI ("free-tier", "local", "gateway", ...).
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "api_key_field": self.api_key_field,
            "base_url_field": self.base_url_field,
            "default_base_url": self.default_base_url,
            "requires_api_key": self.requires_api_key,
            "requires_base_url": self.requires_base_url,
            "supports_discovery": self.discovery != "none",
            "supports_thinking": self.thinking != "none",
            "requires_extra": self.requires_extra,
            "signup_url": self.signup_url,
            "docs_url": self.docs_url,
            "tags": list(self.tags),
            "presets": [preset.to_dict() for preset in self.presets],
        }


@dataclass(frozen=True)
class ToolProviderSpec:
    """A search / fetch provider that backs one built-in tool."""

    id: str
    label: str
    description: str
    use: str
    tool_name: str
    requires_api_key: bool = True
    api_key_field: str = "api_key"
    base_url_field: str | None = None
    default_base_url: str | None = None
    requires_base_url: bool = False
    extra_config: dict[str, Any] = field(default_factory=dict)
    signup_url: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "tool_name": self.tool_name,
            "requires_api_key": self.requires_api_key,
            "base_url_field": self.base_url_field,
            "default_base_url": self.default_base_url,
            "requires_base_url": self.requires_base_url,
            "signup_url": self.signup_url,
            "tags": list(self.tags),
        }


def _openai_compatible(
    provider_id: str,
    label: str,
    description: str,
    base_url: str,
    presets: tuple[ModelPreset, ...],
    *,
    signup_url: str | None = None,
    thinking: ThinkingStyle = "none",
    tags: tuple[str, ...] = (),
    requires_api_key: bool = True,
    extra_config: dict[str, Any] | None = None,
    use: str = "langchain_openai:ChatOpenAI",
) -> LLMProviderSpec:
    """Build a spec for one of the many OpenAI-compatible endpoints."""
    return LLMProviderSpec(
        id=provider_id,
        label=label,
        description=description,
        use=use,
        default_base_url=base_url,
        presets=presets,
        thinking=thinking,
        signup_url=signup_url,
        requires_api_key=requires_api_key,
        tags=tags,
        extra_config={"request_timeout": 600.0, "max_retries": 2, **(extra_config or {})},
    )


LLM_PROVIDERS: tuple[LLMProviderSpec, ...] = (
    # -- First-party SDKs -------------------------------------------------
    LLMProviderSpec(
        id="openai",
        label="OpenAI",
        description="GPT-5 and GPT-4 family, direct from OpenAI.",
        use="langchain_openai:ChatOpenAI",
        default_base_url="https://api.openai.com/v1",
        signup_url="https://platform.openai.com/api-keys",
        tags=("popular",),
        extra_config={"request_timeout": 600.0, "max_retries": 2},
        presets=(
            ModelPreset("gpt-5", "GPT-5", context_window=400000, max_tokens=16384, supports_vision=True),
            ModelPreset("gpt-5-mini", "GPT-5 mini", context_window=400000, max_tokens=16384, supports_vision=True),
            ModelPreset("gpt-4.1", "GPT-4.1", context_window=1047576, max_tokens=32768, supports_vision=True),
            ModelPreset("gpt-4.1-mini", "GPT-4.1 mini", context_window=1047576, max_tokens=32768, supports_vision=True),
            ModelPreset("gpt-4o", "GPT-4o", context_window=128000, max_tokens=16384, supports_vision=True),
        ),
    ),
    LLMProviderSpec(
        id="anthropic",
        label="Anthropic",
        description="Claude models with extended thinking.",
        use="langchain_anthropic:ChatAnthropic",
        base_url_field="base_url",
        default_base_url=None,
        discovery="anthropic",
        thinking="anthropic",
        signup_url="https://console.anthropic.com/settings/keys",
        tags=("popular",),
        extra_config={"default_request_timeout": 600.0, "max_retries": 2},
        presets=(
            ModelPreset("claude-sonnet-4-5", "Claude Sonnet 4.5", context_window=200000, max_tokens=16000, supports_vision=True, supports_thinking=True),
            ModelPreset("claude-opus-4-5", "Claude Opus 4.5", context_window=200000, max_tokens=16000, supports_vision=True, supports_thinking=True),
            ModelPreset("claude-haiku-4-5", "Claude Haiku 4.5", context_window=200000, max_tokens=16000, supports_vision=True),
        ),
    ),
    LLMProviderSpec(
        id="google",
        label="Google Gemini",
        description="Native Gemini SDK via Google AI Studio.",
        use="langchain_google_genai:ChatGoogleGenerativeAI",
        api_key_field="gemini_api_key",
        base_url_field=None,
        discovery="google",
        signup_url="https://aistudio.google.com/app/apikey",
        tags=("popular", "free-tier"),
        extra_config={"timeout": 600.0, "max_retries": 2},
        presets=(
            ModelPreset("gemini-2.5-pro", "Gemini 2.5 Pro", context_window=1048576, max_tokens=8192, supports_vision=True),
            ModelPreset("gemini-2.5-flash", "Gemini 2.5 Flash", context_window=1048576, max_tokens=8192, supports_vision=True),
            ModelPreset("gemini-2.0-flash", "Gemini 2.0 Flash", context_window=1048576, max_tokens=8192, supports_vision=True),
        ),
    ),
    _openai_compatible(
        "google_openai",
        "Google Gemini (OpenAI-compatible)",
        "Same Google AI Studio key, routed through Gemini's OpenAI-compatible endpoint. Preserves thinking.",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        (
            ModelPreset("gemini-2.5-pro", "Gemini 2.5 Pro", context_window=1048576, max_tokens=16384, supports_vision=True, supports_thinking=True),
            ModelPreset("gemini-2.5-flash", "Gemini 2.5 Flash", context_window=1048576, max_tokens=16384, supports_vision=True, supports_thinking=True),
        ),
        signup_url="https://aistudio.google.com/app/apikey",
        thinking="openai_compat",
        use="deerflow.models.patched_openai:PatchedChatOpenAI",
        tags=("free-tier",),
    ),
    # -- Multi-vendor gateways: best odds of matching an existing plan -----
    _openai_compatible(
        "openrouter",
        "OpenRouter",
        "One key, hundreds of models from every major lab.",
        "https://openrouter.ai/api/v1",
        (
            ModelPreset("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", context_window=200000, max_tokens=16384, supports_vision=True),
            ModelPreset("openai/gpt-5", "GPT-5", context_window=400000, max_tokens=16384, supports_vision=True),
            ModelPreset("google/gemini-2.5-pro", "Gemini 2.5 Pro", context_window=1048576, max_tokens=16384, supports_vision=True),
            ModelPreset("deepseek/deepseek-chat", "DeepSeek Chat", context_window=128000, max_tokens=8192),
        ),
        signup_url="https://openrouter.ai/keys",
        tags=("popular", "gateway"),
    ),
    _openai_compatible(
        "groq",
        "Groq",
        "Very fast inference for open-weight models.",
        "https://api.groq.com/openai/v1",
        (
            ModelPreset("llama-3.3-70b-versatile", "Llama 3.3 70B", context_window=131072, max_tokens=32768),
            ModelPreset("openai/gpt-oss-120b", "GPT-OSS 120B", context_window=131072, max_tokens=32768),
            ModelPreset("moonshotai/kimi-k2-instruct", "Kimi K2", context_window=131072, max_tokens=16384),
        ),
        signup_url="https://console.groq.com/keys",
        tags=("free-tier",),
    ),
    _openai_compatible(
        "xai",
        "xAI Grok",
        "Grok models from xAI.",
        "https://api.x.ai/v1",
        (
            ModelPreset("grok-4", "Grok 4", context_window=256000, max_tokens=16384, supports_vision=True),
            ModelPreset("grok-3-mini", "Grok 3 mini", context_window=131072, max_tokens=16384),
        ),
        signup_url="https://console.x.ai",
    ),
    _openai_compatible(
        "mistral",
        "Mistral AI",
        "Mistral Large and open-weight models.",
        "https://api.mistral.ai/v1",
        (
            ModelPreset("mistral-large-latest", "Mistral Large", context_window=131072, max_tokens=16384),
            ModelPreset("mistral-medium-latest", "Mistral Medium", context_window=131072, max_tokens=16384),
            ModelPreset("pixtral-large-latest", "Pixtral Large", context_window=131072, max_tokens=16384, supports_vision=True),
        ),
        signup_url="https://console.mistral.ai/api-keys",
    ),
    LLMProviderSpec(
        id="deepseek",
        label="DeepSeek",
        description="DeepSeek reasoning and chat models.",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        base_url_field="api_base",
        default_base_url="https://api.deepseek.com/v1",
        thinking="openai_compat",
        signup_url="https://platform.deepseek.com/api_keys",
        extra_config={"timeout": 600.0, "max_retries": 2},
        presets=(
            ModelPreset("deepseek-chat", "DeepSeek Chat", context_window=131072, max_tokens=8192),
            ModelPreset("deepseek-reasoner", "DeepSeek Reasoner", context_window=131072, max_tokens=8192, supports_thinking=True),
        ),
    ),
    LLMProviderSpec(
        id="moonshot",
        label="Moonshot Kimi",
        description="Kimi long-context models.",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        base_url_field="api_base",
        default_base_url="https://api.moonshot.ai/v1",
        thinking="openai_compat",
        signup_url="https://platform.moonshot.ai/console/api-keys",
        extra_config={"timeout": 600.0, "max_retries": 2},
        presets=(
            ModelPreset("kimi-k2-turbo-preview", "Kimi K2 Turbo", context_window=262144, max_tokens=32768, supports_thinking=True),
            ModelPreset("moonshot-v1-128k", "Moonshot v1 128k", context_window=131072, max_tokens=16384),
        ),
    ),
    LLMProviderSpec(
        id="volcengine",
        label="Volcengine Ark (Doubao)",
        description="ByteDance Ark endpoint - Doubao plus a multi-vendor coding plan.",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        base_url_field="api_base",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        thinking="openai_compat",
        signup_url="https://console.volcengine.com/ark",
        tags=("gateway",),
        extra_config={"timeout": 600.0, "max_retries": 2},
        presets=(
            ModelPreset("doubao-seed-1-6-250615", "Doubao Seed 1.6", context_window=262144, max_tokens=16384, supports_vision=True, supports_thinking=True),
            ModelPreset("deepseek-v3-250324", "DeepSeek V3 (Ark)", context_window=131072, max_tokens=16384),
        ),
    ),
    _openai_compatible(
        "zai",
        "Z.AI (GLM)",
        "Zhipu GLM models.",
        "https://api.z.ai/api/paas/v4",
        (
            ModelPreset("glm-4.6", "GLM-4.6", context_window=204800, max_tokens=16384, supports_thinking=True),
            ModelPreset("glm-4.5-air", "GLM-4.5 Air", context_window=131072, max_tokens=16384),
        ),
        signup_url="https://z.ai/manage-apikey/apikey-list",
        thinking="openai_compat",
    ),
    _openai_compatible(
        "dashscope",
        "Alibaba DashScope (Qwen)",
        "Qwen models via the international DashScope endpoint.",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        (
            ModelPreset("qwen3-max", "Qwen3 Max", context_window=262144, max_tokens=16384),
            ModelPreset("qwen-plus", "Qwen Plus", context_window=131072, max_tokens=16384),
            ModelPreset("qwen-vl-max", "Qwen VL Max", context_window=131072, max_tokens=16384, supports_vision=True),
        ),
        signup_url="https://bailian.console.alibabacloud.com",
    ),
    _openai_compatible(
        "siliconflow",
        "SiliconFlow",
        "Hosted open-weight models with a generous free tier.",
        "https://api.siliconflow.cn/v1",
        (
            ModelPreset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", context_window=131072, max_tokens=8192),
            ModelPreset("Qwen/Qwen3-235B-A22B", "Qwen3 235B", context_window=131072, max_tokens=8192),
        ),
        signup_url="https://cloud.siliconflow.cn/account/ak",
        tags=("free-tier",),
    ),
    _openai_compatible(
        "together",
        "Together AI",
        "Open-weight models at scale.",
        "https://api.together.xyz/v1",
        (
            ModelPreset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", context_window=131072, max_tokens=8192),
            ModelPreset("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B Turbo", context_window=131072, max_tokens=8192),
        ),
        signup_url="https://api.together.ai/settings/api-keys",
    ),
    _openai_compatible(
        "fireworks",
        "Fireworks AI",
        "Fast serving for open-weight models.",
        "https://api.fireworks.ai/inference/v1",
        (
            ModelPreset("accounts/fireworks/models/deepseek-v3", "DeepSeek V3", context_window=131072, max_tokens=8192),
            ModelPreset("accounts/fireworks/models/qwen3-235b-a22b", "Qwen3 235B", context_window=131072, max_tokens=8192),
        ),
        signup_url="https://fireworks.ai/account/api-keys",
    ),
    _openai_compatible(
        "cerebras",
        "Cerebras",
        "Wafer-scale inference, extremely low latency.",
        "https://api.cerebras.ai/v1",
        (
            ModelPreset("llama-3.3-70b", "Llama 3.3 70B", context_window=131072, max_tokens=8192),
            ModelPreset("qwen-3-235b-a22b-instruct-2507", "Qwen3 235B", context_window=131072, max_tokens=8192),
        ),
        signup_url="https://cloud.cerebras.ai",
        tags=("free-tier",),
    ),
    _openai_compatible(
        "perplexity",
        "Perplexity",
        "Sonar models with built-in web grounding.",
        "https://api.perplexity.ai",
        (
            ModelPreset("sonar-pro", "Sonar Pro", context_window=200000, max_tokens=8192),
            ModelPreset("sonar-reasoning-pro", "Sonar Reasoning Pro", context_window=128000, max_tokens=8192),
        ),
        signup_url="https://www.perplexity.ai/settings/api",
    ),
    _openai_compatible(
        "deepinfra",
        "DeepInfra",
        "Cheap hosted open-weight models.",
        "https://api.deepinfra.com/v1/openai",
        (
            ModelPreset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", context_window=131072, max_tokens=8192),
            ModelPreset("meta-llama/Llama-3.3-70B-Instruct", "Llama 3.3 70B", context_window=131072, max_tokens=8192),
        ),
        signup_url="https://deepinfra.com/dash/api_keys",
    ),
    _openai_compatible(
        "nebius",
        "Nebius AI Studio",
        "Hosted open-weight models with a free tier.",
        "https://api.studio.nebius.com/v1",
        (
            ModelPreset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", context_window=131072, max_tokens=8192),
            ModelPreset("Qwen/Qwen3-235B-A22B", "Qwen3 235B", context_window=131072, max_tokens=8192),
        ),
        signup_url="https://studio.nebius.com",
        tags=("free-tier",),
    ),
    _openai_compatible(
        "hyperbolic",
        "Hyperbolic",
        "Low-cost open-weight inference.",
        "https://api.hyperbolic.xyz/v1",
        (ModelPreset("deepseek-ai/DeepSeek-V3", "DeepSeek V3", context_window=131072, max_tokens=8192),),
        signup_url="https://app.hyperbolic.xyz/settings",
    ),
    _openai_compatible(
        "sambanova",
        "SambaNova",
        "Fast open-weight inference.",
        "https://api.sambanova.ai/v1",
        (ModelPreset("Meta-Llama-3.3-70B-Instruct", "Llama 3.3 70B", context_window=131072, max_tokens=8192),),
        signup_url="https://cloud.sambanova.ai/apis",
        tags=("free-tier",),
    ),
    _openai_compatible(
        "novita",
        "Novita AI",
        "OpenAI-compatible hosting for open-weight models.",
        "https://api.novita.ai/openai",
        (ModelPreset("deepseek/deepseek-v3", "DeepSeek V3", context_window=131072, max_tokens=8192),),
        signup_url="https://novita.ai/settings/key-management",
        thinking="openai_compat",
    ),
    _openai_compatible(
        "minimax",
        "MiniMax",
        "MiniMax M-series (international endpoint).",
        "https://api.minimax.io/v1",
        (ModelPreset("MiniMax-M2", "MiniMax M2", context_window=204800, max_tokens=8192, supports_thinking=True),),
        signup_url="https://platform.minimax.io",
        extra_config={"temperature": 1.0},
    ),
    _openai_compatible(
        "stepfun",
        "StepFun",
        "Step reasoning models.",
        "https://api.stepfun.com/v1",
        (ModelPreset("step-3", "Step 3", context_window=65536, max_tokens=8192, supports_thinking=True),),
        signup_url="https://platform.stepfun.com",
        use="deerflow.models.patched_stepfun:PatchedChatStepFun",
    ),
    _openai_compatible(
        "github_models",
        "GitHub Models",
        "Included with a GitHub account or Copilot plan. Use a PAT with the models scope.",
        "https://models.github.ai/inference",
        (
            ModelPreset("openai/gpt-4.1", "GPT-4.1", context_window=1047576, max_tokens=16384, supports_vision=True),
            ModelPreset("openai/gpt-4o", "GPT-4o", context_window=128000, max_tokens=16384, supports_vision=True),
        ),
        signup_url="https://github.com/settings/personal-access-tokens",
        tags=("free-tier", "subscription"),
    ),
    # -- Bring-your-own endpoint ------------------------------------------
    LLMProviderSpec(
        id="azure_openai",
        label="Azure OpenAI",
        description="Your Azure deployment. Base URL looks like https://<resource>.openai.azure.com/openai/v1.",
        use="langchain_openai:ChatOpenAI",
        default_base_url=None,
        requires_base_url=True,
        signup_url="https://portal.azure.com",
        extra_config={"request_timeout": 600.0, "max_retries": 2},
        presets=(ModelPreset("gpt-4.1", "Your deployment name", context_window=128000, max_tokens=16384, supports_vision=True),),
    ),
    LLMProviderSpec(
        id="ollama",
        label="Ollama (local)",
        description="Local models through Ollama's native API. No API key.",
        use="langchain_ollama:ChatOllama",
        base_url_field="base_url",
        default_base_url="http://host.docker.internal:11434",
        requires_api_key=False,
        discovery="ollama",
        thinking="ollama",
        requires_extra="ollama",
        docs_url="https://ollama.com/library",
        tags=("local", "free"),
        extra_config={"num_predict": 8192, "temperature": 0.7},
        presets=(
            ModelPreset("qwen3:32b", "Qwen3 32B", context_window=32768, supports_thinking=True),
            ModelPreset("llama3.3:70b", "Llama 3.3 70B", context_window=131072),
        ),
    ),
    _openai_compatible(
        "lmstudio",
        "LM Studio (local)",
        "Local models through LM Studio's OpenAI-compatible server. No API key.",
        "http://host.docker.internal:1234/v1",
        (ModelPreset("local-model", "Whatever LM Studio is serving", context_window=32768),),
        requires_api_key=False,
        tags=("local", "free"),
    ),
    LLMProviderSpec(
        id="vllm",
        label="vLLM (self-hosted)",
        description="Your own vLLM server.",
        use="deerflow.models.vllm_provider:VllmChatModel",
        default_base_url=None,
        requires_base_url=True,
        requires_api_key=False,
        docs_url="https://docs.vllm.ai",
        tags=("local",),
        extra_config={"request_timeout": 600.0, "max_retries": 2},
        presets=(ModelPreset("Qwen/Qwen3-32B", "Qwen3 32B", context_window=32768),),
    ),
    LLMProviderSpec(
        id="openai_compatible",
        label="Custom OpenAI-compatible endpoint",
        description="Anything that speaks /v1/chat/completions - a proxy, a gateway, a self-hosted server.",
        use="deerflow.models.patched_openai:PatchedChatOpenAI",
        default_base_url=None,
        requires_base_url=True,
        requires_api_key=False,
        tags=("advanced",),
        extra_config={"request_timeout": 600.0, "max_retries": 2},
        presets=(),
    ),
)


SEARCH_PROVIDERS: tuple[ToolProviderSpec, ...] = (
    ToolProviderSpec(
        id="ddg",
        label="DuckDuckGo",
        description="Default. Works with no API key at all.",
        use="deerflow.community.ddg_search.tools:web_search_tool",
        tool_name="web_search",
        requires_api_key=False,
        extra_config={"max_results": 5},
        tags=("free", "default"),
    ),
    ToolProviderSpec(
        id="tavily",
        label="Tavily",
        description="Search built for agents. Free tier available.",
        use="deerflow.community.tavily.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5},
        signup_url="https://app.tavily.com/home",
        tags=("recommended", "free-tier"),
    ),
    ToolProviderSpec(
        id="brave",
        label="Brave Search",
        description="Independent index with an official API.",
        use="deerflow.community.brave.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5},
        signup_url="https://api-dashboard.search.brave.com",
        tags=("free-tier",),
    ),
    ToolProviderSpec(
        id="exa",
        label="Exa",
        description="Neural plus keyword web search.",
        use="deerflow.community.exa.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5, "search_type": "auto", "contents_max_characters": 1000},
        signup_url="https://dashboard.exa.ai/api-keys",
    ),
    ToolProviderSpec(
        id="firecrawl",
        label="Firecrawl",
        description="Search plus crawl in one API.",
        use="deerflow.community.firecrawl.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5},
        signup_url="https://www.firecrawl.dev/app/api-keys",
    ),
    ToolProviderSpec(
        id="serper",
        label="Serper",
        description="Real-time Google results.",
        use="deerflow.community.serper.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5},
        signup_url="https://serper.dev/api-key",
    ),
    ToolProviderSpec(
        id="serply",
        label="Serply",
        description="Google search, news and scholar results.",
        use="deerflow.community.serply.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5},
        signup_url="https://serply.io",
    ),
    ToolProviderSpec(
        id="searxng",
        label="SearXNG (self-hosted)",
        description="Your own metasearch instance. No API key, but needs a URL.",
        use="deerflow.community.searxng.tools:web_search_tool",
        tool_name="web_search",
        requires_api_key=False,
        base_url_field="base_url",
        default_base_url="http://searxng:8080",
        requires_base_url=True,
        extra_config={"max_results": 5},
        tags=("free", "self-hosted"),
    ),
    ToolProviderSpec(
        id="groundroute",
        label="GroundRoute",
        description="One key across six engines, price-routed with failover.",
        use="deerflow.community.groundroute.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"max_results": 5},
        signup_url="https://groundroute.com",
    ),
    ToolProviderSpec(
        id="infoquest",
        label="InfoQuest",
        description="Vertical search with higher-quality sourcing.",
        use="deerflow.community.infoquest.tools:web_search_tool",
        tool_name="web_search",
        extra_config={"search_time_range": 10},
    ),
)


FETCH_PROVIDERS: tuple[ToolProviderSpec, ...] = (
    ToolProviderSpec(
        id="jina_ai",
        label="Jina AI Reader",
        description="Default. Works with no API key.",
        use="deerflow.community.jina_ai.tools:web_fetch_tool",
        tool_name="web_fetch",
        requires_api_key=False,
        extra_config={"timeout": 10},
        tags=("free", "default"),
    ),
    ToolProviderSpec(
        id="firecrawl",
        label="Firecrawl",
        description="Crawl-grade page fetch with markdown output.",
        use="deerflow.community.firecrawl.tools:web_fetch_tool",
        tool_name="web_fetch",
        signup_url="https://www.firecrawl.dev/app/api-keys",
    ),
    ToolProviderSpec(
        id="exa",
        label="Exa",
        description="Page contents through the Exa API.",
        use="deerflow.community.exa.tools:web_fetch_tool",
        tool_name="web_fetch",
        signup_url="https://dashboard.exa.ai/api-keys",
    ),
    ToolProviderSpec(
        id="crawl4ai",
        label="Crawl4AI (self-hosted)",
        description="Your own headless Chromium renderer. No API key, but needs a URL.",
        use="deerflow.community.crawl4ai.tools:web_fetch_tool",
        tool_name="web_fetch",
        requires_api_key=False,
        base_url_field="base_url",
        default_base_url="http://crawl4ai:11235",
        requires_base_url=True,
        extra_config={"timeout": 30},
        tags=("free", "self-hosted"),
    ),
)


LLM_PROVIDERS_BY_ID: dict[str, LLMProviderSpec] = {spec.id: spec for spec in LLM_PROVIDERS}
SEARCH_PROVIDERS_BY_ID: dict[str, ToolProviderSpec] = {spec.id: spec for spec in SEARCH_PROVIDERS}
FETCH_PROVIDERS_BY_ID: dict[str, ToolProviderSpec] = {spec.id: spec for spec in FETCH_PROVIDERS}


_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def model_entry_name(provider_id: str, model_id: str) -> str:
    """Stable, unique ``models[].name`` for a (provider, model) pair.

    The name is what the chat UI stores against a thread, so it must stay
    stable across restarts and must not collide between two providers offering
    the same model id (``deepseek-chat`` on DeepSeek and on OpenRouter).
    """
    slug = _SLUG_UNSAFE.sub("-", f"{provider_id}-{model_id}".lower()).strip("-")
    return slug or provider_id


def thinking_config(style: ThinkingStyle) -> dict[str, Any]:
    """Extra YAML keys that switch reasoning on and off for a provider family."""
    if style == "openai_compat":
        return dict(OPENAI_COMPAT_THINKING)
    if style == "anthropic":
        return dict(ANTHROPIC_THINKING)
    if style == "ollama":
        return dict(OLLAMA_THINKING)
    return {}


def catalog_payload() -> dict[str, Any]:
    """Everything the onboarding UI needs to render its provider pickers."""
    return {
        "llm": [spec.to_dict() for spec in LLM_PROVIDERS],
        "search": [spec.to_dict() for spec in SEARCH_PROVIDERS],
        "fetch": [spec.to_dict() for spec in FETCH_PROVIDERS],
    }
