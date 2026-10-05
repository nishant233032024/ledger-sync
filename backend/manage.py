#!/usr/bin/env python
"""Django's command-line entry point."""

import os
import sys


def main() -> None:
    """Run a Django management command."""
    # Tell Django which settings module contains the project configuration.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    # Import Django only after the settings variable has been configured.
    from django.core.management import execute_from_command_line

    # Pass the command-line arguments such as migrate or runserver to Django.
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
