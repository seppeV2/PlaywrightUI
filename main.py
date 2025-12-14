#!/usr/bin/env python3
"""
Playwright UI - D365 F&O Test Recorder
Entry point for the application.

Usage:
    python main.py              # Run with full features
    python main.py --skip-devops # Run without DevOps integration (for testing)
    flet run main.py            # Run with Flet hot reload
    flet build macos            # Build for macOS
    
By 9altitudes
"""

import flet as ft
import argparse
import sys
import os

# Global flag for DevOps skip (set before import)
_skip_devops = False


def main(page: ft.Page):
    """Main entry point for Flet."""
    from src.app import PlaywrightUIApp
    app = PlaywrightUIApp(page, skip_devops=_skip_devops)


def run():
    """Run the application with argument parsing."""
    global _skip_devops
    
    parser = argparse.ArgumentParser(
        description="Playwright UI - D365 F&O Test Recorder by 9altitudes"
    )
    parser.add_argument(
        "--skip-devops",
        action="store_true",
        help="Skip Azure DevOps integration (useful for local testing)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    _skip_devops = args.skip_devops
    
    # Configure logging
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)
    
    # Run the Flet app
    ft.app(target=main)


if __name__ == "__main__":
    run()
