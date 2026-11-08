"""Backward-compatible import location for the public claim() function."""

from one_rupee.claim import claim

__all__ = ["claim"]


def main():
    """Console-script entry point; the public API remains claim()."""
    claim()
