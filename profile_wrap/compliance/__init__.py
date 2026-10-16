"""Compliance lint: the by-construction safety layer 1 (design spec section 13)."""
from .lint import Violation, lint, main, register

__all__ = ["Violation", "lint", "main", "register"]
