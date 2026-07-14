"""Inert synthetic Case Pack entry point for documentation and tests."""


def register(context):
    context.add_assertion("example.case.loaded", expected=True)
