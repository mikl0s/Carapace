#!/usr/bin/env python3
"""
Carapace main entry point
Launches TUI by default, CLI when arguments provided
"""

import sys

def main():
    # If no arguments (just 'python -m carapace'), launch TUI
    if len(sys.argv) == 1:
        from carapace.tui import CarapaceApp
        app = CarapaceApp()
        app.run()
    else:
        # Otherwise use the CLI
        from carapace.cli import app
        app()

if __name__ == "__main__":
    main()