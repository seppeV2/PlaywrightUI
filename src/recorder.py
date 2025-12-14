"""
Playwright recording wrapper module.
Handles launching Playwright codegen and managing recorded test files.
"""

import asyncio
import logging
import os
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class D365Credentials:
    """D365 login credentials."""
    username: str
    password: str
    totp_secret: str = ""  # TOTP secret for auto MFA (optional)


@dataclass
class RecordingSession:
    """Information about a recording session."""
    test_name: str
    description: str
    target_url: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    output_file: Optional[str] = None
    raw_output: str = ""
    is_complete: bool = False
    error: Optional[str] = None
    auto_login: bool = False


@dataclass
class RecordingResult:
    """Result of a recording session."""
    success: bool
    session: RecordingSession
    generated_code: Optional[str] = None
    file_path: Optional[str] = None
    message: str = ""


class PlaywrightRecorder:
    """
    Wrapper around Playwright codegen for recording tests.
    Supports auto-login to D365 F&O using credentials from Key Vault.
    """
    
    # D365 F&O specific wait selectors and login handling
    D365_LOGIN_SCRIPT = '''
# D365 F&O Auto-login script
import os

async def d365_auto_login(page, username: str, password: str):
    """Perform D365 F&O login."""
    # Wait for Microsoft login page
    try:
        # Enter email/username
        await page.wait_for_selector('input[type="email"]', timeout=10000)
        await page.fill('input[type="email"]', username)
        await page.click('input[type="submit"]')
        
        # Wait for password field
        await page.wait_for_selector('input[type="password"]', timeout=10000)
        await page.fill('input[type="password"]', password)
        await page.click('input[type="submit"]')
        
        # Handle "Stay signed in?" prompt if present
        try:
            await page.wait_for_selector('input#idBtn_Back', timeout=5000)
            await page.click('input#idBtn_Back')  # Click "No"
        except:
            pass
        
        # Wait for D365 to load
        await page.wait_for_load_state('networkidle', timeout=60000)
        
        return True
    except Exception as e:
        print(f"Auto-login failed: {e}")
        return False
'''
    
    def __init__(self, config, credentials: Optional[D365Credentials] = None):
        """
        Initialize the recorder.
        
        Args:
            config: AppConfig instance
            credentials: Optional D365 credentials for auto-login
        """
        from .config import AppConfig
        self.config = config
        self.credentials = credentials
        self._current_session: Optional[RecordingSession] = None
        self._process: Optional[subprocess.Popen] = None
        self._is_recording = False
    
    def set_credentials(self, credentials: D365Credentials):
        """Set credentials for auto-login."""
        self.credentials = credentials
    
    @property
    def is_recording(self) -> bool:
        """Check if recording is in progress."""
        return self._is_recording
    
    @property
    def current_session(self) -> Optional[RecordingSession]:
        """Get current recording session."""
        return self._current_session
    
    @property
    def has_credentials(self) -> bool:
        """Check if credentials are available for auto-login."""
        return self.credentials is not None
    
    def _generate_file_name(self, test_name: str) -> str:
        """Generate a file name with timestamp."""
        # Sanitize test name
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in test_name)
        safe_name = safe_name.strip("_").lower()
        
        # Add timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        return f"test_{safe_name}_{timestamp}.py"
    
    def _get_viewport_args(self) -> list:
        """Get viewport command line arguments."""
        from .config import ViewportPreset
        
        preset = self.config.recording.viewport_preset
        
        if preset == ViewportPreset.MATCH_WINDOW:
            # Use default dimensions for match window
            width, height = 1920, 1080
        elif preset == ViewportPreset.CUSTOM:
            width = self.config.recording.custom_width
            height = self.config.recording.custom_height
        else:
            width, height = preset.value.split('x')
        
        return ["--viewport-size", f"{width},{height}"]
    
    def _get_browser_args(self) -> list:
        """Get browser command line arguments."""
        browser = self.config.recording.browser.value
        return ["--browser", browser]
    
    def _build_codegen_command(
        self,
        output_path: str,
        target_url: str
    ) -> list:
        """Build the playwright codegen command."""
        cmd = ["playwright", "codegen"]
        
        # Add output file
        cmd.extend(["--output", output_path])
        
        # Add browser
        cmd.extend(self._get_browser_args())
        
        # Add viewport
        cmd.extend(self._get_viewport_args())
        
        # Add target URL
        cmd.append(target_url)
        
        return cmd
    
    def _cleanup_recorded_code(self, raw_code: str) -> str:
        """
        Clean up recorded code by removing unnecessary/redundant actions
        and extracting only the page actions from playwright codegen output.
        
        Args:
            raw_code: Raw code generated by playwright codegen
            
        Returns:
            Cleaned up code with just the page actions
        """
        import re
        import textwrap
        
        lines = raw_code.split('\n')
        
        # First pass: Extract only the page.* action lines
        # Playwright codegen generates code inside a run() function
        # We need to extract just the page actions and dedent them
        page_actions = []
        in_run_function = False
        base_indent = 0
        
        for line in lines:
            stripped = line.strip()
            
            # Detect start of run function
            if re.match(r'def run\(playwright.*\).*:', stripped):
                in_run_function = True
                continue
            
            # Skip these boilerplate lines entirely
            skip_patterns = [
                r'^browser\s*=\s*playwright\.',
                r'^context\s*=\s*browser\.new_context',
                r'^page\s*=\s*context\.new_page\(\)',
                r'^context\.close\(\)',
                r'^browser\.close\(\)',
                r'^with sync_playwright\(\)',
                r'^run\(playwright\)',
                r'^from playwright',
                r'^import re$',
            ]
            
            should_skip = False
            for pattern in skip_patterns:
                if re.match(pattern, stripped):
                    should_skip = True
                    break
            
            if should_skip:
                continue
            
            # Skip empty lines at the beginning
            if not page_actions and not stripped:
                continue
            
            # If we're in the run function and see a page action, capture it
            if stripped.startswith('page.') or (in_run_function and stripped and not stripped.startswith('def ') and not stripped.startswith('with ')):
                # Dedent the line - remove leading whitespace
                page_actions.append(stripped)
            elif stripped.startswith('expect('):
                page_actions.append(stripped)
        
        # If no page actions found, fall back to keeping non-boilerplate lines
        if not page_actions:
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('page.') or stripped.startswith('expect('):
                    page_actions.append(stripped)
        
        # Second pass: Clean up the extracted page actions
        cleaned_actions = []
        prev_line = ""
        
        # Patterns to remove (unnecessary clicks, waits, etc.)
        patterns_to_remove = [
            r'^page\.click\(["\']body["\']\)',
            r'^page\.click\(["\']html["\']\)',
            r'^page\.wait_for_timeout\(0\)',
            r'^page\.click\(["\']div["\']\s*\)',
            r'^page\.click\(["\']span["\']\s*\)',
            r'^page\.mouse\.move\(',
            r'^page\.hover\(["\']body["\']\)',
            r'^page\.focus\(["\']body["\']\)',
            r'^page\.focus\(["\']html["\']\)',
        ]
        
        # Patterns for login-related actions (remove these since login is automated)
        login_patterns = [
            r'.*input\[type="email"\].*',
            r'.*input\[type="password"\].*',
            r'.*login\.microsoftonline\.com.*',
            r'.*idSIButton9.*',
            r'.*idBtn_Back.*',
            r'.*#idTxtBx_SAOTCC_OTC.*',
            r'.*#idSubmit_SAOTCC_Continue.*',
        ]
        
        for line in page_actions:
            should_remove = False
            
            # Check removal patterns
            for pattern in patterns_to_remove:
                if re.match(pattern, line):
                    should_remove = True
                    break
            
            # Check login patterns
            if not should_remove:
                for pattern in login_patterns:
                    if re.match(pattern, line):
                        should_remove = True
                        break
            
            # Remove duplicate consecutive clicks
            if line.startswith('page.click(') and prev_line == line:
                should_remove = True
            
            # Remove very short timeouts
            timeout_match = re.match(r'^page\.wait_for_timeout\((\d+)\)', line)
            if timeout_match:
                timeout_val = int(timeout_match.group(1))
                if timeout_val < 100:
                    should_remove = True
            
            # Remove storage_state references
            if 'storage_state=' in line and 'playwright_auth_state' in line:
                line = re.sub(r',?\s*storage_state="[^"]*"', '', line)
            
            if not should_remove:
                # Add proper indentation (4 spaces for inside test function)
                cleaned_actions.append('    ' + line)
                prev_line = line
        
        # Remove trailing empty lines
        while cleaned_actions and not cleaned_actions[-1].strip():
            cleaned_actions.pop()
        
        return '\n'.join(cleaned_actions)
    
    def _extract_page_actions_only(self, raw_code: str) -> str:
        """
        Extract page actions from codegen output without any cleanup.
        Used when cleanup is disabled - keeps all actions but removes boilerplate.
        
        Args:
            raw_code: Raw code generated by playwright codegen
            
        Returns:
            Page actions properly indented for test function
        """
        import re
        
        lines = raw_code.split('\n')
        page_actions = []
        in_run_function = False
        
        for line in lines:
            stripped = line.strip()
            
            # Detect start of run function
            if re.match(r'def run\(playwright.*\).*:', stripped):
                in_run_function = True
                continue
            
            # Skip boilerplate lines
            skip_patterns = [
                r'^browser\s*=\s*playwright\.',
                r'^context\s*=\s*browser\.new_context',
                r'^page\s*=\s*context\.new_page\(\)',
                r'^context\.close\(\)',
                r'^browser\.close\(\)',
                r'^with sync_playwright\(\)',
                r'^run\(playwright\)',
                r'^from playwright',
                r'^import re$',
            ]
            
            should_skip = False
            for pattern in skip_patterns:
                if re.match(pattern, stripped):
                    should_skip = True
                    break
            
            if should_skip:
                continue
            
            # Skip empty lines at the beginning
            if not page_actions and not stripped:
                continue
            
            # Keep all page actions and expect statements
            if stripped.startswith('page.') or stripped.startswith('expect('):
                # Remove storage_state references
                if 'storage_state=' in stripped and 'playwright_auth_state' in stripped:
                    stripped = re.sub(r',?\s*storage_state="[^"]*"', '', stripped)
                page_actions.append('    ' + stripped)
        
        # Remove trailing empty lines
        while page_actions and not page_actions[-1].strip():
            page_actions.pop()
        
        return '\n'.join(page_actions)

    def _generate_test_wrapper(
        self,
        raw_code: str,
        session: RecordingSession
    ) -> str:
        """
        Wrap the generated code with D365-specific setup and metadata.
        
        Args:
            raw_code: Raw generated code from playwright codegen
            session: Recording session info
            
        Returns:
            Enhanced test code
        """
        timestamp = session.started_at.strftime("%Y-%m-%d %H:%M:%S")
        test_func_name = self._sanitize_test_name(session.test_name)
        target_url = session.target_url
        
        # Build imports and setup
        header = f'''"""
D365 F&O Automated Test
=======================
Test Name: {session.test_name}
Description: {session.description}
Recorded: {timestamp}
Target URL: {target_url}

Generated by Playwright UI - 9altitudes
"""

import os
import re
import time
from playwright.sync_api import Page, expect
import pytest
from datetime import datetime

# Import pyotp for TOTP MFA handling
try:
    import pyotp
    HAS_PYOTP = True
except ImportError:
    HAS_PYOTP = False

# Test Configuration
TEST_TIMEOUT = {self.config.recording.test_timeout}  # milliseconds
TARGET_URL = "{target_url}"

# =============================================================================
# CREDENTIALS - Set via environment variables for security
# =============================================================================
# Set these environment variables before running:
#   D365_USERNAME - Your D365 username/email
#   D365_PASSWORD - Your D365 password  
#   D365_TOTP_SECRET - (Optional) TOTP secret for MFA
#
# Or the test runner will set them automatically from Key Vault
# =============================================================================

'''
        
        # Add retry count variable if enabled
        if self.config.recording.add_retry:
            header += f'''
# Retry configuration - tests will be rerun on failure
RETRY_COUNT = {self.config.recording.retry_count}
'''
        
        # Add auto-login fixture
        header += '''
def _check_login_error(page) -> tuple:
    """Check if there is a login error on the page. Returns (has_error, error_message)."""
    try:
        page_content = page.content().lower()
        error_codes = ['500121', 'aadsts90014', 'aadsts50011', 'aadsts50059', 'aadsts90019', 'aadsts900561']
        for code in error_codes:
            if code in page_content:
                return True, f"Login error detected: {code}"
        
        error_selectors = ['#errorMessage', '.alert-error', '#service_exception_message']
        for selector in error_selectors:
            try:
                elem = page.query_selector(selector)
                if elem and elem.is_visible():
                    return True, f"Error element found: {selector}"
            except:
                pass
        return False, ""
    except:
        return False, ""

def d365_auto_login(page: Page, max_retries: int = 2) -> bool:
    """
    Perform D365 F&O auto-login using credentials from environment variables.
    Returns True if login was successful or already logged in.
    
    Set these environment variables before running:
      D365_USERNAME - Your D365 username/email
      D365_PASSWORD - Your D365 password
      D365_TOTP_SECRET - (Optional) TOTP secret for MFA
    """
    username = os.environ.get("D365_USERNAME", "")
    password = os.environ.get("D365_PASSWORD", "")
    totp_secret = os.environ.get("D365_TOTP_SECRET", "")
    
    if not username or not password:
        print("⚠ No credentials provided - skipping auto-login")
        print("  Set D365_USERNAME and D365_PASSWORD environment variables")
        return False
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                print(f"")
                print(f"⟳ Retry attempt {attempt}/{max_retries}")
                page.reload(wait_until="networkidle", timeout=30000)
                time.sleep(3)
            
            # Check for errors before starting
            has_error, error_msg = _check_login_error(page)
            if has_error:
                print(f"⚠ {error_msg}")
                if attempt < max_retries:
                    continue
                else:
                    return False
            
            # CRITICAL: Wait for page to fully load before any interaction
            print("=" * 50)
            print("D365 AUTO-LOGIN")
            print("=" * 50)
            
            # Wait for complete page load including all JavaScript
            print("Waiting for page to fully load...")
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            time.sleep(3)  # Extra wait for Microsoft JS to initialize
            
            # Check if already on D365 (not on login page)
            current_url = page.url.lower()
            if "dynamics.com" in current_url and "login.microsoftonline" not in current_url:
                print("✓ Already logged in to D365")
                return True
            
            # Multiple selectors for Microsoft login email field
            email_selectors = [
                'input[name="loginfmt"]',           # Microsoft standard
                'input[type="email"]',              # Generic email
                '#i0116',                           # Microsoft ID
            ]
            
            # Wait for Microsoft login page to be ready
            email_input = None
            print("Looking for email field...")
            
            for selector in email_selectors:
                try:
                    page.wait_for_selector(selector, timeout=5000, state="visible")
                    email_input = selector
                    print(f"✓ Found email field: {selector}")
                    break
                except:
                    continue
            
            if not email_input:
                # Check if already logged in
                if "dynamics.com" in page.url.lower():
                    print("✓ Already on D365")
                    return True
                print("⚠ Login page not found")
                if attempt < max_retries:
                    continue
                return False
            
            # CRITICAL: Wait for input to be fully interactive
            # Microsoft login requires the input field's JS handlers to be attached
            page.wait_for_selector(email_input, state="visible")
            time.sleep(1)  # Wait for JS event handlers to attach
            
            # Click on the field first to ensure focus
            page.click(email_input)
            time.sleep(0.5)
            
            # Clear any existing value and enter email
            print(f"Entering username: {username[:3]}***")
            page.fill(email_input, "")  # Clear first
            time.sleep(0.3)
            page.fill(email_input, username)
            time.sleep(0.5)
            
            # Wait for Next button to be ready
            time.sleep(1)
            
            # Click Next button
            next_buttons = ['#idSIButton9', 'input[type="submit"]', 'button[type="submit"]']
            clicked = False
            for btn in next_buttons:
                try:
                    page.wait_for_selector(btn, state="visible", timeout=3000)
                    btn_elem = page.query_selector(btn)
                    if btn_elem and btn_elem.is_visible():
                        time.sleep(0.5)  # Wait before clicking
                        page.click(btn)
                        print("✓ Clicked Next")
                        clicked = True
                        break
                except:
                    continue
            
            if not clicked:
                print("⚠ Could not find Next button")
                if attempt < max_retries:
                    continue
                return False
            
            # CRITICAL: Wait for password page to fully load
            # This is where AADSTS90014 often occurs if we proceed too fast
            print("Waiting for password page...")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except:
                pass
            time.sleep(3)  # Extra wait for page transition
            
            # Check for errors after email submission
            has_error, error_msg = _check_login_error(page)
            if has_error:
                print(f"⚠ {error_msg}")
                if attempt < max_retries:
                    continue
                return False
            
            # Wait for password field
            print("Looking for password field...")
            password_selectors = [
                'input[name="passwd"]',             # Microsoft standard
                'input[type="password"]:visible',   # Generic password
                '#i0118',                           # Microsoft ID
            ]
            
            password_input = None
            for selector in password_selectors:
                try:
                    page.wait_for_selector(selector, timeout=10000, state="visible")
                    password_input = selector
                    print(f"✓ Found password field: {selector}")
                    break
                except:
                    continue
            
            if not password_input:
                print("⚠ Password field not found")
                # Check for error message
                try:
                    error_text = page.query_selector('.alert-error, #passwordError, .error')
                    if error_text:
                        print(f"⚠ Error on page: {error_text.inner_text()}")
                except:
                    pass
                if attempt < max_retries:
                    continue
                return False
            
            # Wait for password input to be fully interactive
            page.wait_for_selector(password_input, state="visible")
            time.sleep(1)
            
            # Click and fill password
            page.click(password_input)
            time.sleep(0.3)
            print("Entering password...")
            page.fill(password_input, "")  # Clear first
            time.sleep(0.3)
            page.fill(password_input, password)
            time.sleep(0.5)
            
            # Wait before clicking Sign in
            time.sleep(1)
            
            # Click Sign in button
            clicked = False
            for btn in next_buttons:
                try:
                    page.wait_for_selector(btn, state="visible", timeout=3000)
                    btn_elem = page.query_selector(btn)
                    if btn_elem and btn_elem.is_visible():
                        time.sleep(0.5)
                        page.click(btn)
                        print("✓ Clicked Sign in")
                        clicked = True
                        break
                except:
                    continue
            
            if not clicked:
                print("⚠ Could not find Sign in button")
                if attempt < max_retries:
                    continue
                return False
            
            # Wait for next page to fully load
            print("Waiting for response...")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except:
                pass
            time.sleep(3)
            
            # Handle MFA - Detect screen state and navigate to TOTP input
            # Note: We DON'T check for errors here because MFA error pages are normal and handled by the state machine
            print("Checking for MFA...")
            time.sleep(2)  # Wait for MFA page to fully render
            
            # MFA State Machine - Keep trying until we reach TOTP input or timeout
            mfa_max_attempts = 10
            mfa_attempt = 0
            totp_field_found = False
            
            while mfa_attempt < mfa_max_attempts and not totp_field_found:
                mfa_attempt += 1
                print(f"MFA navigation attempt {mfa_attempt}/{mfa_max_attempts}...")
                
                try:
                    page_content = page.content().lower()
                    
                    # STATE 1: Check if we're already on TOTP input screen
                    if page.query_selector('#idTxtBx_SAOTCC_OTC'):
                        print("  ✓ Already on verification code input screen")
                        totp_field_found = True
                        break
                    
                    # STATE 2: Check if we're on push notification screen (with number)
                    # Look for "I can't use my Microsoft Authenticator app right now" link
                    try:
                        cant_use_link = page.get_by_text("I can't use my Microsoft Authenticator app right now")
                        if cant_use_link.is_visible(timeout=1000):
                            print("  📱 Push notification screen detected")
                            print("  Clicking 'I can't use my Microsoft Authenticator app right now'...")
                            cant_use_link.click()
                            time.sleep(2)
                            continue  # Re-check state after click
                    except:
                        pass
                    
                    # STATE 3: Check if we're on error/options screen
                    # Look for "Use a verification code" button/option
                    verification_clicked = False
                    
                    # Try multiple selectors in order of reliability
                    selectors_to_try = [
                        ('div[data-value="PhoneAppOTP"]', 'data-value attribute'),
                        ('[aria-label*="verification code"]', 'aria-label'),
                        ('div:has-text("Use a verification code")', 'div with text'),
                    ]
                    
                    for selector, desc in selectors_to_try:
                        if verification_clicked:
                            break
                        try:
                            code_option = page.query_selector(selector)
                            if code_option and code_option.is_visible():
                                print(f"  🔐 MFA options screen detected ({desc})")
                                print(f"  Clicking 'Use a verification code' via {desc}...")
                                code_option.click()
                                time.sleep(2)
                                verification_clicked = True
                                break
                        except Exception as e:
                            print(f"  ℹ {desc} selector failed: {e}")
                    
                    # Last resort: try get_by_text
                    if not verification_clicked:
                        try:
                            code_option = page.get_by_text("Use a verification code", exact=False)
                            count = code_option.count()
                            print(f"  ℹ Found {count} elements with 'Use a verification code' text")
                            if count > 0:
                                print("  🔐 MFA options screen detected (text selector)")
                                print("  Clicking 'Use a verification code'...")
                                code_option.first.click()
                                time.sleep(2)
                                verification_clicked = True
                        except Exception as e:
                            print(f"  ⚠ Error with text selector: {e}")
                    
                    if verification_clicked:
                        continue  # Re-check state after click
                    
                    # STATE 4: Check for MFA error message
                    if "sorry, we're having trouble" in page_content or "please try again" in page_content:
                        print("  ⚠ MFA error detected - will retry clicking verification code...")
                        time.sleep(1)
                        continue  # Go back to top of loop to re-detect state
                    
                    # STATE 5: Check if we're still on a generic MFA page
                    mfa_indicators = ['verify your identity', 'approve a request', 'authenticator app', 'verification code']
                    is_mfa_page = any(indicator in page_content for indicator in mfa_indicators)
                    
                    if is_mfa_page:
                        print("  ℹ MFA page detected but no actionable elements found, waiting...")
                        time.sleep(2)
                        continue
                    else:
                        # Not on MFA page anymore, might have moved forward
                        print("  ℹ No longer on MFA page")
                        break
                        
                except Exception as state_ex:
                    print(f"  ⚠ Error detecting MFA state: {state_ex}")
                    time.sleep(1)
            
            # After navigation loop, try to fill TOTP if we have the secret
            if totp_secret and HAS_PYOTP:
                try:
                    # Wait for TOTP input field
                    page.wait_for_selector('#idTxtBx_SAOTCC_OTC', timeout=10000, state="visible")
                    time.sleep(0.5)
                    
                    # Generate and enter TOTP code
                    totp = pyotp.TOTP(totp_secret)
                    code = totp.now()
                    print(f"  Entering TOTP code: {code}")
                    page.fill('#idTxtBx_SAOTCC_OTC', code)
                    time.sleep(0.3)
                    page.click('#idSubmit_SAOTCC_Continue')
                    print("  ✓ TOTP submitted")
                    time.sleep(3)
                except Exception as otp_ex:
                    print(f"  ⚠ TOTP auto-fill failed: {otp_ex}")
                    print("  Please enter the verification code manually from your Authenticator app...")
            else:
                print("  ⚠ No TOTP secret configured for auto-fill")
                print("  Please enter the verification code manually from your Authenticator app...")
                
                # Wait for user to enter code manually - check for OTC field and wait until it's submitted
                print("  Waiting for manual MFA completion (up to 60 seconds)...")
                mfa_wait_start = time.time()
                while time.time() - mfa_wait_start < 60:
                    try:
                        # Check if we've moved past MFA (reached D365 or Stay signed in)
                        current_url = page.url.lower()
                        if "dynamics.com" in current_url and "login.microsoftonline" not in current_url:
                            print("  ✓ MFA completed - reached D365")
                            break
                        
                        # Check if "Stay signed in" appeared (means MFA is done)
                        if page.query_selector('#idBtn_Back') or page.query_selector('#KmsiBanner'):
                            print("  ✓ MFA completed")
                            break
                        
                        # Check for errors
                        has_error, error_msg = _check_login_error(page)
                        if has_error:
                            print(f"  ⚠ {error_msg}")
                            break
                            
                    except:
                        pass
                    time.sleep(1)
            
            # Wait for login to complete (handle "Stay signed in?", MFA push, or D365 load)
            print("Waiting for login to complete...")
            wait_max = 90  # 90 seconds max for MFA approval
            wait_start = time.time()
            error_retry_count = 0
            
            while time.time() - wait_start < wait_max:
                current_url = page.url.lower()
                
                # Check for errors during wait
                has_error, error_msg = _check_login_error(page)
                if has_error:
                    print(f"⚠ {error_msg}")
                    # For AADSTS900561, try refreshing the page once
                    if 'aadsts900561' in error_msg.lower() and error_retry_count < 2:
                        error_retry_count += 1
                        print(f"  Attempting recovery (attempt {error_retry_count})...")
                        time.sleep(2)
                        page.reload(wait_until="networkidle", timeout=30000)
                        time.sleep(3)
                        continue
                    if attempt < max_retries:
                        break  # Break inner while loop to retry
                    return False
                
                # Check if we reached D365
                if "dynamics.com" in current_url and "login.microsoftonline" not in current_url:
                    print("✓ Successfully logged in to D365!")
                    # Wait for D365 to fully load
                    try:
                        page.wait_for_load_state('networkidle', timeout=30000)
                    except:
                        pass
                    print("=" * 50)
                    print("✓ AUTO-LOGIN COMPLETE")
                    print("=" * 50)
                    return True
                
                # Handle "Stay signed in?" prompt
                try:
                    if page.query_selector('#idBtn_Back'):
                        page.click('#idBtn_Back')
                        print("  Clicked 'No' on 'Stay signed in?'")
                        time.sleep(1)
                        continue
                    elif page.query_selector('#idSIButton9'):
                        # Check if this is the "Stay signed in" page
                        try:
                            if page.query_selector('#KmsiBanner') or "stay signed in" in page.content().lower():
                                page.click('#idSIButton9')
                                print("  Clicked 'Yes' on 'Stay signed in?'")
                                time.sleep(1)
                                continue
                        except:
                            pass
                except:
                    pass
                
                time.sleep(1)
            
            # If we get here without returning, the login didn't complete
            print("⚠ Login may not have completed")
            if attempt < max_retries:
                continue
            return False
            
        except Exception as e:
            print(f"❌ Auto-login attempt failed: {e}")
            if attempt < max_retries:
                continue
            return False
    
    # All retries exhausted
    return False

'''
        
        # Add screenshot configuration
        if self.config.recording.add_screenshots:
            screenshot_dir = self.config.recording.screenshot_output_dir
            if screenshot_dir:
                header += f'''
@pytest.fixture(autouse=True)
def screenshot_on_failure(request, page: Page):
    """Take screenshot on test failure."""
    yield
    if hasattr(request.node, 'rep_call') and request.node.rep_call.failed:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_dir = "{screenshot_dir}"
        os.makedirs(screenshot_dir, exist_ok=True)
        page.screenshot(path=os.path.join(screenshot_dir, f"screenshot_{{timestamp}}.png"))
'''
            else:
                header += '''
@pytest.fixture(autouse=True)
def screenshot_on_failure(request, page: Page):
    """Take screenshot on test failure."""
    yield
    if hasattr(request.node, 'rep_call') and request.node.rep_call.failed:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        page.screenshot(path=f"screenshot_{timestamp}.png")
'''
        
        # Add test variables section
        header += '''

# =============================================================================
# TEST VARIABLES - Modify these values as needed
# =============================================================================
# Variables extracted from recorded test - edit values below:
TEST_VARIABLES = {
    # Add your variables here after post-processing
    # Example: "ORDER_NUMBER": "SO-001234",
}

def get_var(name: str, default: str = "") -> str:
    """Get a test variable value."""
    return TEST_VARIABLES.get(name, default)

# =============================================================================
# RECORDED TEST
# =============================================================================

'''
        
        # Build decorators for the test function
        decorators = []
        if self.config.recording.add_retry:
            decorators.append(f"@pytest.mark.flaky(reruns={self.config.recording.retry_count})")
        decorators.append(f"@pytest.mark.timeout({self.config.recording.test_timeout // 1000})")
        
        decorator_str = "\n".join(decorators)
        
        # The raw_code at this point should already be cleaned and indented page actions
        # Build the complete test function with auto-login at the start
        test_function = f'''{decorator_str}
def test_{test_func_name}(page: Page):
    """
    {session.description}
    
    Recorded: {timestamp}
    """
    # Navigate to D365 and perform auto-login if needed
    page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
    d365_auto_login(page)
    
    # Recorded test actions
{raw_code}
'''
        
        return header + test_function
    
    def _sanitize_test_name(self, name: str) -> str:
        """Convert a test name to a valid Python function name."""
        import re
        # Replace spaces and special chars with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower())
        # Remove consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        # Remove leading/trailing underscores
        sanitized = sanitized.strip('_')
        # Ensure it doesn't start with a number
        if sanitized and sanitized[0].isdigit():
            sanitized = 'test_' + sanitized
        return sanitized or 'recorded_test'

    def start_recording(
        self,
        test_name: str,
        description: str,
        auto_login: bool = True,
        on_complete: Optional[Callable[[RecordingResult], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ) -> RecordingSession:
        """
        Start a new recording session.
        
        Args:
            test_name: Name for the test
            description: Description of what's being tested
            auto_login: If True and credentials are available, auto-login to D365
            on_complete: Callback when recording completes
            on_error: Callback on error
            
        Returns:
            RecordingSession object
        """
        if self._is_recording:
            raise RuntimeError("Recording already in progress")
        
        # Create session
        target_url = self.config.d365.environment_url
        if not target_url:
            raise ValueError("D365 environment URL not configured")
        
        # Determine if we should auto-login
        do_auto_login = auto_login and self.has_credentials
        
        self._current_session = RecordingSession(
            test_name=test_name,
            description=description,
            target_url=target_url,
            auto_login=do_auto_login
        )
        
        # Generate output file name
        file_name = self._generate_file_name(test_name)
        
        # Determine output path
        output_dir = self.config.local_storage.output_directory
        if not output_dir:
            output_dir = tempfile.gettempdir()
        
        output_path = os.path.join(output_dir, file_name)
        self._current_session.output_file = output_path
        
        # Start recording in background thread
        def run_recording():
            self._is_recording = True
            try:
                if do_auto_login:
                    result = self._run_with_auto_login(output_path, target_url)
                else:
                    result = self._run_codegen(output_path, target_url)
                
                self._current_session.ended_at = datetime.now()
                self._current_session.is_complete = True
                
                if on_complete:
                    on_complete(result)
                    
            except Exception as e:
                self._current_session.error = str(e)
                logger.error(f"Recording failed: {e}")
                if on_error:
                    on_error(str(e))
            finally:
                self._is_recording = False
        
        thread = threading.Thread(target=run_recording, daemon=True)
        thread.start()
        
        return self._current_session
    
    def _run_with_auto_login(self, output_path: str, target_url: str) -> RecordingResult:
        """Run recording with auto-login to D365 - visible browser session."""
        logger.info(f"Starting recording with auto-login to {target_url}")
        
        from playwright.sync_api import sync_playwright
        import pyotp
        import time
        
        storage_state_path = os.path.join(tempfile.gettempdir(), 'playwright_auth_state.json')
        
        def check_for_login_error(page) -> tuple[bool, str]:
            """Check if there's a login error on the page. Returns (has_error, error_message)."""
            try:
                # Check for error codes in page content
                page_content = page.content().lower()
                error_codes = ['500121', 'aadsts90014', 'aadsts50011', 'aadsts50059', 'aadsts90019', 'aadsts900561']
                for code in error_codes:
                    if code in page_content:
                        return True, f"Login error detected: {code}"
                
                # Check for visible error text
                error_selectors = [
                    '#errorMessage',
                    '.alert-error',
                    '#service_exception_message',
                    '.error-page-content'
                ]
                for selector in error_selectors:
                    try:
                        elem = page.query_selector(selector)
                        if elem and elem.is_visible():
                            return True, f"Error element found: {selector}"
                    except:
                        pass
                
                return False, ""
            except:
                return False, ""
        
        def perform_login_with_retry(page, max_retries: int = 2) -> bool:
            """Perform login with retry logic for session errors."""
            for attempt in range(max_retries + 1):
                if attempt > 0:
                    print(f"")
                    print(f"⟳ Retry attempt {attempt}/{max_retries}")
                    # Go back to start fresh
                    page.goto(target_url, wait_until="networkidle", timeout=60000)
                    time.sleep(3)
                
                # Check for error before starting
                has_error, error_msg = check_for_login_error(page)
                if has_error:
                    print(f"⚠ {error_msg}")
                    if attempt < max_retries:
                        print("Refreshing page to retry...")
                        page.reload(wait_until="networkidle", timeout=30000)
                        time.sleep(3)
                        continue
                    else:
                        print("Max retries reached")
                        return False
                
                # Check if already logged in
                if 'dynamics.com' in page.url.lower() and 'login.microsoftonline' not in page.url.lower():
                    print("✓ Already logged in to D365!")
                    return True
                
                # Wait for page to fully load
                print("Waiting for login page to fully load...")
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                except:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(3)  # Critical: wait for Microsoft JS to initialize
                
                # Multiple selectors for Microsoft login email field
                email_selectors = [
                    'input[name="loginfmt"]',
                    'input[type="email"]',
                    '#i0116',
                ]
                
                email_input = None
                print("Looking for email field...")
                
                for selector in email_selectors:
                    try:
                        page.wait_for_selector(selector, timeout=5000, state="visible")
                        email_input = selector
                        print(f"✓ Found email field: {selector}")
                        break
                    except:
                        continue
                
                if not email_input:
                    if "dynamics.com" in page.url.lower():
                        print("✓ Already on D365 - no login needed")
                        return True
                    print("⚠ Login page not detected")
                    continue
                
                # Enter email
                page.wait_for_selector(email_input, state="visible")
                time.sleep(1)
                page.click(email_input)
                time.sleep(0.5)
                
                print(f"Entering username: {self.credentials.username[:3]}***")
                page.fill(email_input, "")
                time.sleep(0.3)
                page.fill(email_input, self.credentials.username)
                time.sleep(1)
                
                # Click Next button
                next_buttons = ['#idSIButton9', 'input[type="submit"]', 'button[type="submit"]']
                clicked = False
                for btn in next_buttons:
                    try:
                        page.wait_for_selector(btn, state="visible", timeout=3000)
                        btn_elem = page.query_selector(btn)
                        if btn_elem and btn_elem.is_visible():
                            time.sleep(0.5)
                            page.click(btn)
                            print("✓ Clicked Next")
                            clicked = True
                            break
                    except:
                        continue
                
                if not clicked:
                    print("⚠ Could not find Next button")
                    continue
                
                # Wait for password page
                print("Waiting for password page...")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except:
                    pass
                time.sleep(3)
                
                # Check for error after email submission
                has_error, error_msg = check_for_login_error(page)
                if has_error:
                    print(f"⚠ {error_msg}")
                    if attempt < max_retries:
                        continue
                    else:
                        return False
                
                # Wait for password field
                print("Looking for password field...")
                password_selectors = [
                    'input[name="passwd"]',
                    'input[type="password"]:visible',
                    '#i0118',
                ]
                
                password_input = None
                for selector in password_selectors:
                    try:
                        page.wait_for_selector(selector, timeout=10000, state="visible")
                        password_input = selector
                        print(f"✓ Found password field: {selector}")
                        break
                    except:
                        continue
                
                if not password_input:
                    print("⚠ Password field not found")
                    continue
                
                # Enter password
                page.wait_for_selector(password_input, state="visible")
                time.sleep(1)
                page.click(password_input)
                time.sleep(0.3)
                
                print("Entering password...")
                page.fill(password_input, "")
                time.sleep(0.3)
                page.fill(password_input, self.credentials.password)
                time.sleep(1)
                
                # Click Sign in button
                clicked = False
                for btn in next_buttons:
                    try:
                        page.wait_for_selector(btn, state="visible", timeout=3000)
                        btn_elem = page.query_selector(btn)
                        if btn_elem and btn_elem.is_visible():
                            time.sleep(0.5)
                            page.click(btn)
                            print("✓ Clicked Sign in")
                            clicked = True
                            break
                    except:
                        continue
                
                if not clicked:
                    print("⚠ Could not find Sign in button")
                    continue
                
                # Wait for response
                print("Waiting for response...")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except:
                    pass
                time.sleep(3)
                
                # Handle MFA - Detect screen state and navigate to TOTP input
                # Note: We DON'T check for errors here because MFA error pages are normal and handled by the state machine
                print("Checking for MFA...")
                time.sleep(2)  # Wait for MFA page to fully render
                
                # MFA State Machine - Keep trying until we reach TOTP input or timeout
                mfa_max_attempts = 10
                mfa_attempt = 0
                totp_field_found = False
                
                while mfa_attempt < mfa_max_attempts and not totp_field_found:
                    mfa_attempt += 1
                    print(f"MFA navigation attempt {mfa_attempt}/{mfa_max_attempts}...")
                    
                    try:
                        page_content = page.content().lower()
                        
                        # STATE 1: Check if we're already on TOTP input screen
                        if page.query_selector('#idTxtBx_SAOTCC_OTC'):
                            print("  ✓ Already on verification code input screen")
                            totp_field_found = True
                            break
                        
                        # STATE 2: Check if we're on push notification screen (with number)
                        # Look for "I can't use my Microsoft Authenticator app right now" link
                        try:
                            cant_use_link = page.get_by_text("I can't use my Microsoft Authenticator app right now")
                            if cant_use_link.is_visible(timeout=1000):
                                print("  📱 Push notification screen detected")
                                print("  Clicking 'I can't use my Microsoft Authenticator app right now'...")
                                cant_use_link.click()
                                time.sleep(2)
                                continue  # Re-check state after click
                        except:
                            pass
                        
                        # STATE 3: Check if we're on error/options screen
                        # Look for "Use a verification code" button/option
                        verification_clicked = False
                        
                        # Try multiple selectors in order of reliability
                        selectors_to_try = [
                            ('div[data-value="PhoneAppOTP"]', 'data-value attribute'),
                            ('[aria-label*="verification code"]', 'aria-label'),
                            ('div:has-text("Use a verification code")', 'div with text'),
                        ]
                        
                        for selector, desc in selectors_to_try:
                            if verification_clicked:
                                break
                            try:
                                code_option = page.query_selector(selector)
                                if code_option and code_option.is_visible():
                                    print(f"  🔐 MFA options screen detected ({{desc}})")
                                    print(f"  Clicking 'Use a verification code' via {{desc}}...")
                                    code_option.click()
                                    time.sleep(2)
                                    verification_clicked = True
                                    break
                            except Exception as e:
                                print(f"  ℹ {{desc}} selector failed: {{e}}")
                        
                        # Last resort: try get_by_text
                        if not verification_clicked:
                            try:
                                code_option = page.get_by_text("Use a verification code", exact=False)
                                count = code_option.count()
                                print(f"  ℹ Found {{count}} elements with 'Use a verification code' text")
                                if count > 0:
                                    print("  🔐 MFA options screen detected (text selector)")
                                    print("  Clicking 'Use a verification code'...")
                                    code_option.first.click()
                                    time.sleep(2)
                                    verification_clicked = True
                            except Exception as e:
                                print(f"  ⚠ Error with text selector: {{e}}")
                        
                        if verification_clicked:
                            continue  # Re-check state after click
                        
                        # STATE 4: Check for MFA error message
                        if "sorry, we're having trouble" in page_content or "please try again" in page_content:
                            print("  ⚠ MFA error detected - will retry clicking verification code...")
                            time.sleep(1)
                            continue  # Go back to top of loop to re-detect state
                        
                        # STATE 5: Check if we're still on a generic MFA page
                        mfa_indicators = ['verify your identity', 'approve a request', 'authenticator app', 'verification code']
                        is_mfa_page = any(indicator in page_content for indicator in mfa_indicators)
                        
                        if is_mfa_page:
                            print("  ℹ MFA page detected but no actionable elements found, waiting...")
                            time.sleep(2)
                            continue
                        else:
                            # Not on MFA page anymore, might have moved forward
                            print("  ℹ No longer on MFA page")
                            break
                            
                    except Exception as state_ex:
                        print(f"  ⚠ Error detecting MFA state: {{state_ex}}")
                        time.sleep(1)
                
                # After navigation loop, try to fill TOTP if we have the secret
                if self.credentials.totp_secret:
                    try:
                        # Wait for TOTP input field
                        page.wait_for_selector('#idTxtBx_SAOTCC_OTC', timeout=10000, state="visible")
                        time.sleep(0.5)
                        
                        # Generate and enter TOTP code
                        totp = pyotp.TOTP(self.credentials.totp_secret)
                        code = totp.now()
                        print(f"  Entering TOTP code: {code}")
                        page.fill('#idTxtBx_SAOTCC_OTC', code)
                        time.sleep(0.3)
                        page.click('#idSubmit_SAOTCC_Continue')
                        print("  ✓ TOTP submitted")
                        time.sleep(3)
                    except Exception as otp_ex:
                        print(f"  ⚠ TOTP auto-fill failed: {otp_ex}")
                        print("  Please enter the verification code manually from your Authenticator app...")
                else:
                    print("  ⚠ No TOTP secret configured for auto-fill")
                    print("  Please enter the verification code manually from your Authenticator app...")
                
                # Login steps completed - return True to let the wait loop handle the rest
                return True
            
            return False
        
        try:
            # Step 1: Perform auto-login in VISIBLE browser and save auth state
            print("=" * 60)
            print("STEP 1: Auto-login to D365")
            print("=" * 60)
            print("")
            
            with sync_playwright() as p:
                # Get browser and viewport settings
                browser_name = self.config.recording.browser.value
                browser_launcher = getattr(p, browser_name)
                
                from .config import ViewportPreset
                preset = self.config.recording.viewport_preset
                if preset == ViewportPreset.MATCH_WINDOW:
                    # Use default dimensions for auto-login (will be adjusted later)
                    width, height = 1920, 1080
                elif preset == ViewportPreset.CUSTOM:
                    width = self.config.recording.custom_width
                    height = self.config.recording.custom_height
                else:
                    width, height = map(int, preset.value.split('x'))
                
                # Launch browser VISIBLE so user can see/complete login
                print("Launching browser for login...")
                slow_mo = self.config.recording.slow_mo if self.config.recording.slow_mo > 0 else None
                browser = browser_launcher.launch(headless=False, slow_mo=slow_mo)
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                
                # Navigate to D365
                print(f"Navigating to: {target_url}")
                page.goto(target_url, wait_until="networkidle", timeout=60000)
                
                # Perform login with retry logic
                login_success = perform_login_with_retry(page, max_retries=2)
                
                if login_success:
                    # Wait for user to complete any remaining authentication
                    print("")
                    print("Waiting for D365 to load...")
                    print("(Complete any MFA prompts in the browser if needed)")
                    print("")
                    
                    # Wait for either D365 to load or "Stay signed in" prompt
                    max_wait = 120  # 2 minutes max
                    start_time = time.time()
                    logged_in = False
                    
                    while time.time() - start_time < max_wait:
                        current_url = page.url.lower()
                        
                        # Check for login errors
                        has_error, error_msg = check_for_login_error(page)
                        if has_error:
                            print(f"⚠ {error_msg}")
                            print("Refreshing page to retry...")
                            page.reload(wait_until="networkidle", timeout=30000)
                            time.sleep(3)
                            continue
                        
                        if 'dynamics.com' in current_url and 'login.microsoftonline' not in current_url:
                            print("✓ Successfully reached D365!")
                            logged_in = True
                            break
                        
                        # Handle "Stay signed in?" prompt
                        try:
                            if page.query_selector('#idBtn_Back'):
                                page.click('#idBtn_Back')
                                print("✓ Clicked 'No' on 'Stay signed in?'")
                                time.sleep(2)
                                continue
                            elif page.query_selector('#idSIButton9'):
                                page.click('#idSIButton9')
                                print("✓ Clicked 'Yes' on 'Stay signed in?'")
                                time.sleep(2)
                                continue
                        except:
                            pass
                        
                        time.sleep(1)
                    
                    if not logged_in:
                        # One more check
                        if 'dynamics.com' in page.url.lower():
                            logged_in = True
                        else:
                            print("⚠ Login timeout - saving current state anyway...")
                    
                    # Wait for page to stabilize
                    try:
                        page.wait_for_load_state('networkidle', timeout=30000)
                    except:
                        pass
                
                # Save authentication state
                print("Saving authentication state...")
                context.storage_state(path=storage_state_path)
                print("✓ Authentication state saved")
                
                browser.close()
                print("")
            
            # Step 2: Launch playwright codegen with saved auth state
            print("=" * 60)
            print("STEP 2: Recording your test actions")
            print("=" * 60)
            print("")
            print("A new browser window will open.")
            print("You should be logged in already.")
            print("Perform your test actions, then CLOSE the browser to save.")
            print("")
            
            cmd = self._build_codegen_command(output_path, target_url)
            cmd.extend(["--load-storage", storage_state_path])
            
            logger.info(f"Starting codegen: {' '.join(cmd)}")
            
            # Run codegen (blocks until user closes the browser)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=os.environ.copy()
            )
            
            self._current_session.raw_output = result.stdout + result.stderr
            
            # Clean up auth state file
            try:
                os.remove(storage_state_path)
            except:
                pass
            
            # Process the recorded output
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    raw_code = f.read()
                
                # Clean up the recorded code (if enabled)
                if self.config.recording.cleanup_code:
                    cleaned_code = self._cleanup_recorded_code(raw_code)
                else:
                    cleaned_code = self._extract_page_actions_only(raw_code)
                
                # Wrap with D365 setup
                enhanced_code = self._generate_test_wrapper(
                    cleaned_code,
                    self._current_session
                )
                
                # Write enhanced code back
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(enhanced_code)
                
                return RecordingResult(
                    success=True,
                    session=self._current_session,
                    generated_code=enhanced_code,
                    file_path=output_path,
                    message="Recording completed successfully (with auto-login)"
                )
            else:
                return RecordingResult(
                    success=False,
                    session=self._current_session,
                    message="No test file generated. Recording may have been cancelled."
                )
                
        except Exception as e:
            logger.error(f"Recording with auto-login failed: {e}")
            return RecordingResult(
                success=False,
                session=self._current_session,
                message=f"Recording with auto-login failed: {str(e)}"
            )
    
    def _run_codegen(self, output_path: str, target_url: str) -> RecordingResult:
        """Run playwright codegen subprocess."""
        cmd = self._build_codegen_command(output_path, target_url)
        
        logger.info(f"Starting codegen: {' '.join(cmd)}")
        
        try:
            # Run codegen (blocks until user closes the browser)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=os.environ.copy()
            )
            
            self._current_session.raw_output = result.stdout + result.stderr
            
            # Check if output file was created
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    raw_code = f.read()
                
                # Clean up the recorded code (if enabled)
                if self.config.recording.cleanup_code:
                    cleaned_code = self._cleanup_recorded_code(raw_code)
                else:
                    # Keep raw code but extract page actions for the test function
                    cleaned_code = self._extract_page_actions_only(raw_code)
                
                # Wrap with D365 setup
                enhanced_code = self._generate_test_wrapper(
                    cleaned_code,
                    self._current_session
                )
                
                # Write enhanced code back
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(enhanced_code)
                
                return RecordingResult(
                    success=True,
                    session=self._current_session,
                    generated_code=enhanced_code,
                    file_path=output_path,
                    message="Recording completed successfully"
                )
            else:
                return RecordingResult(
                    success=False,
                    session=self._current_session,
                    message="No test file generated. Recording may have been cancelled."
                )
                
        except subprocess.TimeoutExpired:
            return RecordingResult(
                success=False,
                session=self._current_session,
                message="Recording timed out"
            )
        except Exception as e:
            return RecordingResult(
                success=False,
                session=self._current_session,
                message=f"Recording failed: {str(e)}"
            )
    
    def stop_recording(self) -> None:
        """Stop the current recording (if possible)."""
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._is_recording = False


class TestFileManager:
    """
    Manages recorded test files - saving locally and to DevOps.
    """
    
    def __init__(self, config, devops_manager=None):
        """
        Initialize the file manager.
        
        Args:
            config: AppConfig instance
            devops_manager: Optional DevOpsManager instance
        """
        self.config = config
        self.devops_manager = devops_manager
    
    def save_test(
        self,
        file_name: str,
        content: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Save test file according to configured destination.
        
        Args:
            file_name: Name of the test file
            content: Test file content
            description: Test description
            
        Returns:
            Dict with results for each destination
        """
        from .config import SaveDestination
        
        results = {
            "local": {"success": False, "message": "", "path": None},
            "devops": {"success": False, "message": "", "commit_id": None}
        }
        
        destination = self.config.save_destination
        
        # Save locally
        if destination in (SaveDestination.LOCAL_ONLY, SaveDestination.LOCAL_AND_DEVOPS):
            local_result = self._save_local(file_name, content)
            results["local"] = local_result
        
        # Push to DevOps
        if destination in (SaveDestination.DEVOPS_ONLY, SaveDestination.LOCAL_AND_DEVOPS):
            if self.devops_manager and self.devops_manager.is_available():
                devops_result = self._push_to_devops(file_name, content, description)
                results["devops"] = devops_result
            else:
                results["devops"] = {
                    "success": False,
                    "message": "DevOps not configured or unavailable"
                }
        
        return results
    
    def _save_local(self, file_name: str, content: str) -> Dict[str, Any]:
        """Save file locally."""
        try:
            output_dir = self.config.local_storage.output_directory
            if not output_dir:
                return {
                    "success": False,
                    "message": "Output directory not configured"
                }
            
            # Ensure directory exists
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            file_path = os.path.join(output_dir, file_name)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return {
                "success": True,
                "message": f"Saved to {file_path}",
                "path": file_path
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to save locally: {str(e)}"
            }
    
    def _push_to_devops(
        self,
        file_name: str,
        content: str,
        description: str
    ) -> Dict[str, Any]:
        """Push file to Azure DevOps."""
        try:
            result = self.devops_manager.push_test_file(
                file_name=file_name,
                content=content,
                description=description
            )
            
            return {
                "success": result.success,
                "message": result.message,
                "commit_id": result.commit_id
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to push to DevOps: {str(e)}"
            }
