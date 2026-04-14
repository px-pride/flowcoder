"""
Service Factory for creating AI service instances.

Centralizes the logic for instantiating different types of AI services
(Claude, Codex, Mock) based on service type.
"""

import logging
from typing import Optional

from .base_service import BaseService
from .claude_service import ClaudeAgentService, MockClaudeService
from .codex_service import CodexService, CODEX_SDK_AVAILABLE

logger = logging.getLogger(__name__)


class ServiceFactoryError(Exception):
    """Exception raised when service creation fails."""
    pass


class ServiceFactory:
    """
    Factory for creating AI service instances.

    Uses the Factory Pattern to centralize service creation logic.
    This makes it easy to add new service types without modifying existing code.
    """

    # Map of service type names to display names
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
            **kwargs: Additional service-specific parameters

        Returns:
            BaseService instance (ClaudeAgentService, CodexService, or MockClaudeService)

        Raises:
            ServiceFactoryError: If service type is unknown or creation fails
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
    ) -> ClaudeAgentService:
        """
        Create a Claude Agent service instance.

        Args:
            cwd: Working directory
            system_prompt: System prompt
            **kwargs: Additional parameters (permission_mode, max_retries, etc.)

        Returns:
            ClaudeAgentService instance
        """
        logger.info(f"Creating ClaudeAgentService (cwd={cwd})")

        return ClaudeAgentService(
            cwd=cwd,
            system_prompt=system_prompt,
            permission_mode=kwargs.get("permission_mode", "bypassPermissions"),
            max_retries=kwargs.get("max_retries", 3),
            timeout_seconds=kwargs.get("timeout_seconds", None),  # Timeouts disabled
            stderr_callback=kwargs.get("stderr_callback"),
            model=kwargs.get("model")
        )

    @staticmethod
    def _create_codex_service(
        cwd: str,
        system_prompt: Optional[str],
        **kwargs
    ) -> CodexService:
        """
        Create a Codex service instance.

        Args:
            cwd: Working directory
            system_prompt: System prompt
            **kwargs: Additional parameters (max_retries, timeout_seconds, etc.)

        Returns:
            CodexService instance

        Raises:
            ServiceFactoryError: If Codex SDK not available
        """
        if not CODEX_SDK_AVAILABLE:
            raise ServiceFactoryError(
                "Codex SDK is not installed. "
                "To use Codex, install it with: pip install codex-sdk"
            )

        logger.info(f"Creating CodexService (cwd={cwd})")

        return CodexService(
            cwd=cwd,
            system_prompt=system_prompt,
            max_retries=kwargs.get("max_retries", 3),
            timeout_seconds=kwargs.get("timeout_seconds", None),  # Timeouts disabled
            stderr_callback=kwargs.get("stderr_callback")
        )

    @staticmethod
    def _create_mock_service(cwd: str) -> MockClaudeService:
        """
        Create a mock service instance for testing.

        Args:
            cwd: Working directory

        Returns:
            MockClaudeService instance
        """
        logger.info(f"Creating MockClaudeService (cwd={cwd})")

        return MockClaudeService(cwd=cwd)

    @staticmethod
    def get_available_services() -> dict:
        """
        Get a dictionary of available service types and their availability.

        Returns:
            Dict mapping service type to tuple of (display_name, is_available, reason)
        """
        services = {}

        # Claude is always available (uses try/catch for SDK import)
        services["claude"] = (
            ServiceFactory.SERVICE_DISPLAY_NAMES["claude"],
            True,
            "Claude Agent SDK"
        )

        # Codex availability depends on SDK installation
        services["codex"] = (
            ServiceFactory.SERVICE_DISPLAY_NAMES["codex"],
            CODEX_SDK_AVAILABLE,
            "Codex SDK" if CODEX_SDK_AVAILABLE else "Codex SDK not installed"
        )

        # Mock is always available
        services["mock"] = (
            ServiceFactory.SERVICE_DISPLAY_NAMES["mock"],
            True,
            "For testing only"
        )

        return services

    @staticmethod
    def get_service_display_name(service_type: str) -> str:
        """
        Get the display name for a service type.

        Args:
            service_type: Service type ("claude", "codex", "mock")

        Returns:
            Display name for the service
        """
        return ServiceFactory.SERVICE_DISPLAY_NAMES.get(
            service_type.lower(),
            service_type.title()
        )

    @staticmethod
    def is_service_available(service_type: str) -> bool:
        """
        Check if a service type is available.

        Args:
            service_type: Service type to check

        Returns:
            True if service is available, False otherwise
        """
        services = ServiceFactory.get_available_services()
        if service_type.lower() in services:
            _, is_available, _ = services[service_type.lower()]
            return is_available
        return False
