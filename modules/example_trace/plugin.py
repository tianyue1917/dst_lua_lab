"""Synthetic Extension API v1 entry point."""


def register(context):
    """Declare one synthetic event without touching the host filesystem."""
    context.subscribe_trace("example.synthetic")
