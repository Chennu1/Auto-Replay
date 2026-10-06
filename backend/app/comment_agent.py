"""Comment Understanding & Reply Agent facade.

This module exposes the stable public entry point for comment understanding and
reply generation without changing the existing Gemini implementation.
"""

from .agent import generate_reply

__all__ = ["generate_reply"]
