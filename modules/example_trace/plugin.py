"""Inert example entry point for the management-only extension milestone."""


def register(context):
    """Declare one synthetic event without touching the host filesystem."""
    context.subscribe_trace("example.synthetic")
