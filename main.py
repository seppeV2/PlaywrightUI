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


def _check_playwright_browsers() -> bool:
    """Check if playwright browsers are installed."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                # Try to get chromium executable path
                _ = p.chromium.executable_path
                return True
            except Exception:
                return False
    except Exception:
        return False


def _install_playwright_browsers_with_ui(page: ft.Page):
    """Install playwright browsers with progress UI."""
    import subprocess
    import threading
    
    # Create loading dialog
    progress_text = ft.Text(
        "First-time setup: Checking browser components...",
        size=16,
        text_align=ft.TextAlign.CENTER
    )
    progress_bar = ft.ProgressBar(width=400)
    
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Setting up Playwright", size=20, weight=ft.FontWeight.BOLD),
        content=ft.Container(
            content=ft.Column(
                [
                    progress_text,
                    ft.Container(height=20),
                    progress_bar,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            width=450,
            padding=20,
        ),
    )
    
    page.dialog = dialog
    dialog.open = True
    page.update()
    
    def install():
        try:
            progress_text.value = "Installing Chromium browser...\nThis may take a few minutes (downloading ~300MB)"
            page.update()
            
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                progress_text.value = "✓ Installation complete!"
                progress_bar.value = 1.0
            else:
                progress_text.value = f"⚠ Installation failed\n\nPlease run manually:\n{sys.executable} -m playwright install"
            
            page.update()
            
            # Close dialog after 2 seconds
            import time
            time.sleep(2)
            dialog.open = False
            page.update()
            
        except Exception as e:
            progress_text.value = f"⚠ Error: {str(e)}\n\nPlease run manually:\n{sys.executable} -m playwright install"
            page.update()
            import time
            time.sleep(3)
            dialog.open = False
            page.update()
    
    # Run installation in background thread
    threading.Thread(target=install, daemon=True).start()


def main(page: ft.Page):
    """Main entry point for Flet."""
    # Check and install playwright browsers if needed (with UI feedback)
    if not _check_playwright_browsers():
        _install_playwright_browsers_with_ui(page)
    
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
