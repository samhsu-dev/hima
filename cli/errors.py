class CommandError(Exception):
    """User-facing command failure; cli.main prints the message and exits 1."""
