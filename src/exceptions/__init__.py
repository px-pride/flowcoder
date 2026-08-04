"""
Exceptions for FlowCoder

Custom exceptions for enhanced error handling.
"""

from .recursion_error import CommandRecursionError

__all__ = [
    'CommandRecursionError',
]
