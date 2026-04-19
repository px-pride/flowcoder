"""
Service Factory for creating AI service instances.

There is one underlying service class (`ClaudeEngineService`) backed by
``flowcoder_engine.ClaudeSession`` which spawns the system claude CLI
binary directly. The "Codex" service type is the same class with proxy
env vars injected so the claude CLI routes through anthropic-proxy-rs
to OpenAI.
"""

import logging
from typing import Optional

from .base_service import BaseService
from .claude_engine_service import ClaudeEngineService
from .mock_service import MockClaudeService

logger = logging.getLogger(__name__)


# Default proxy settings for the "codex" service type
DEFAULT_PROXY_URL = "http://127.0.0.1:3000"
DEFAULT_PROXY_MODEL = "gpt-5.4"


class ServiceFactoryError(Exception):
    """Exception raised when service creation fails."""
    pass


class ServiceFactory:
    """
    Factory for creating AI service instances.

    "claude" -> ClaudeEngineService
    "codex"  -> ClaudeEngineService with ANTHROPIC_BASE_URL/ANTHROPIC_MODEL set
    "mock"   -> MockClaudeService
    """

    SERVICE_DISPLAY_NAMES = {
        "claude": "Claude Code",
        "codex": "Codex",
        "mock": "Mock (Testing)"
    }

    @staticmethod
    def create_service(
        service_type: str,
        cwd: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> BaseService:
        """
        Create an AI service instance based on type.

        Args:
            service_type: Type of service ("claude", "codex", or "mock")
            cwd: Working directory for the service
            system_prompt: System prompt for the AI
            **kwargs: Additional service-specific parameters. Recognized:
                proxy_url, proxy_model — override defaults for "codex".

        Returns:
            BaseService instance.

        Raises:
            ServiceFactoryError: If service type is unknown or creation fails.
        """
        service_type = service_type.lower().strip()

        try:
            if service_type == "claude":
                return ServiceFactory._create_claude_service(cwd, system_prompt, **kwargs)
            elif service_type == "codex":
                return ServiceFactory._create_codex_service(cwd, system_prompt, **kwargs)
            elif service_type == "mock":
                return ServiceFactory._create_mock_service(cwd)
            else:
                raise ServiceFactoryError(
                    f"Unknown service type: '{service_type}'. "
                    f"Valid types are: {', '.join(ServiceFactory.SERVICE_DISPLAY_NAMES.keys())}"
                )
        except Exception as e:
            logger.error(f"Failed to create {service_type} service: {e}")
            raise ServiceFactoryError(f"Could not create {service_type} service: {e}")

    @staticmethod
    def _create_claude_service(
        cwd: str,
        system_prompt: Optional[str],
        **kwargs
    ) -> ClaudeEngineService:
        logger.info(f"Creating ClaudeEngineService (cwd={cwd})")

        return ClaudeEngineService(
            cwd=cwd,
            system_prompt=system_prompt,
            permission_mode=kwargs.get("permission_mode", "bypassPermissions"),
            max_retries=kwargs.get("max_retries", 3),
            timeout_seconds=kwargs.get("timeout_seconds", None),
            stderr_callback=kwargs.get("stderr_callback"),
            model=kwargs.get("model"),
        )

    @staticmethod
    def _create_codex_service(
        cwd: str,
        system_prompt: Optional[str],
        **kwargs
    ) -> ClaudeEngineService:
        """
        Create a ClaudeEngineService configured to route through anthropic-proxy.

        Lazily spawns the proxy subprocess on first call. Raises
        ProxyStartupError (wrapped as ServiceFactoryError by the caller) if
        the proxy binary is missing or the subprocess fails to become healthy.
        """
        from .proxy_manager import get_proxy_manager

        proxy_url = kwargs.get("proxy_url") or DEFAULT_PROXY_URL
        proxy_model = kwargs.get("proxy_model") or DEFAULT_PROXY_MODEL

        get_proxy_manager().ensure_started()

        extra_env = {
            "ANTHROPIC_BASE_URL": proxy_url,
            "ANTHROPIC_MODEL": proxy_model,
            # The proxy doesn't validate the API key, but the CLI requires one to be set
            "ANTHROPIC_API_KEY": kwargs.get("anthropic_api_key", "proxy"),
        }

        logger.info(
            f"Creating Codex (proxied) ClaudeEngineService "
            f"(cwd={cwd}, proxy={proxy_url}, model={proxy_model})"
        )

        return ClaudeEngineService(
            cwd=cwd,
            system_prompt=system_prompt,
            permission_mode=kwargs.get("permission_mode", "bypassPermissions"),
            max_retries=kwargs.get("max_retries", 3),
            timeout_seconds=kwargs.get("timeout_seconds", None),
            stderr_callback=kwargs.get("stderr_callback"),
            model=kwargs.get("model"),
            extra_env=extra_env,
        )

    @staticmethod
    def _create_mock_service(cwd: str) -> MockClaudeService:
        logger.info(f"Creating MockClaudeService (cwd={cwd})")
        return MockClaudeService(cwd=cwd)

    @staticmethod
    def get_available_services() -> dict:
        """
        Get a dictionary of available service types and their availability.

        Returns:
            Dict mapping service type to (display_name, is_available, reason).
        """
        return {
            "claude": (
                ServiceFactory.SERVICE_DISPLAY_NAMES["claude"],
                True,
                "System claude CLI via flowcoder_engine"
            ),
            "codex": (
                ServiceFactory.SERVICE_DISPLAY_NAMES["codex"],
                True,
                "Routes through anthropic-proxy to OpenAI (proxy must be running)"
            ),
            "mock": (
                ServiceFactory.SERVICE_DISPLAY_NAMES["mock"],
                True,
                "For testing only"
            ),
        }

    @staticmethod
    def get_service_display_name(service_type: str) -> str:
        return ServiceFactory.SERVICE_DISPLAY_NAMES.get(
            service_type.lower(),
            service_type.title()
        )

    @staticmethod
    def is_service_available(service_type: str) -> bool:
        services = ServiceFactory.get_available_services()
        if service_type.lower() in services:
            _, is_available, _ = services[service_type.lower()]
            return is_available
        return False
