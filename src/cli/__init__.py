"""CLI package for FlowCoder terminal-based agent."""

# Lazy-load CLIAgent so that importing submodules (e.g. src.cli.agent for
# DEFAULT_SYSTEM_PROMPT) doesn't eagerly pull in the full ServiceFactory chain.


def __getattr__(name: str):
    if name == 'CLIAgent':
        from .agent import CLIAgent
        return CLIAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ['CLIAgent']
