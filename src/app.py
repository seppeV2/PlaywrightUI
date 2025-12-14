"""
Playwright UI - D365 F&O Test Recorder
Main Flet Application

A user-friendly interface for recording Playwright tests for Dynamics 365 F&O,
with Azure Key Vault integration and Azure DevOps Git push capabilities.

By 9altitudes
"""

import flet as ft
import logging
import os
import threading
from datetime import datetime
from typing import Optional, List, Callable

from .config import (
    ConfigManager, get_config_manager, AppConfig,
    SaveDestination, BrowserType, ViewportPreset
)
from .theme import NineAltitudesTheme as theme
from .keyvault import CredentialsManager, KeyVaultClient
from .devops import AzureDevOpsClient, DevOpsManager
from .recorder import PlaywrightRecorder, TestFileManager, RecordingResult
from .postprocess import PostProcessor, DetectedInput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PlaywrightUIApp:
    """Main application class."""
    
    def __init__(self, page: ft.Page, skip_devops: bool = False):
        """
        Initialize the application.
        
        Args:
            page: Flet page instance
            skip_devops: If True, skip DevOps integration for testing
        """
        self.page = page
        self.skip_devops = skip_devops
        
        # Managers
        self.config_manager = get_config_manager()
        self.credentials_manager: Optional[CredentialsManager] = None
        self.devops_manager: Optional[DevOpsManager] = None
        self.recorder: Optional[PlaywrightRecorder] = None
        self.file_manager: Optional[TestFileManager] = None
        
        # State
        self.current_recording_result: Optional[RecordingResult] = None
        self.post_processor: Optional[PostProcessor] = None
        
        # UI Components
        self._build_ui()
    
    @property
    def config(self) -> AppConfig:
        """Get current configuration."""
        return self.config_manager.config
    
    def _build_ui(self):
        """Build the main UI."""
        # Page setup
        self.page.title = "Playwright UI - D365 Test Recorder"
        self.page.theme = theme.get_theme()
        self.page.bgcolor = theme.BACKGROUND
        self.page.window.full_screen = True
        self.page.window.min_width = 900
        self.page.window.min_height = 600
        
        # File pickers
        self.folder_picker = ft.FilePicker(on_result=self._on_folder_picked)
        self.test_file_picker = ft.FilePicker(on_result=self._on_test_file_picked)
        self.page.overlay.extend([self.folder_picker, self.test_file_picker])
        
        # Build tabs
        self.tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(
                    text="Record Test",
                    icon=ft.Icons.FIBER_MANUAL_RECORD,
                    content=self._build_record_tab()
                ),
                ft.Tab(
                    text="Post-Process",
                    icon=ft.Icons.EDIT_NOTE,
                    content=self._build_postprocess_tab()
                ),
                ft.Tab(
                    text="Run Tests",
                    icon=ft.Icons.PLAY_ARROW,
                    content=self._build_run_tests_tab()
                ),
                ft.Tab(
                    text="Settings",
                    icon=ft.Icons.SETTINGS,
                    content=self._build_settings_tab()
                ),
            ],
            expand=True,
            label_color=theme.TEXT_SECONDARY,
            indicator_color=theme.ACCENT,
            divider_color=theme.DIVIDER,
        )
        
        # Main layout
        self.page.add(
            ft.Column(
                controls=[
                    theme.header_bar(
                        "Playwright Test Recorder",
                        "D365 Finance & Operations - by 9altitudes"
                    ),
                    self.tabs,
                ],
                expand=True,
                spacing=0,
            )
        )
        
        # Load saved config into UI
        self._load_config_to_ui()
    
    # =========================================================================
    # RECORD TAB
    # =========================================================================
    
    def _build_record_tab(self) -> ft.Container:
        """Build the recording tab content."""
        
        # Test info fields
        self.test_name_field = theme.styled_textfield(
            label="Test Name",
            hint_text="e.g., Create Sales Order",
            icon=ft.Icons.LABEL,
        )
        
        self.test_description_field = theme.styled_textfield(
            label="Test Description",
            hint_text="Describe what this test covers...",
            multiline=True,
            icon=ft.Icons.DESCRIPTION,
        )
        
        # Status display
        self.recording_status = ft.Text(
            "Ready to record",
            size=14,
            color=theme.TEXT_SECONDARY
        )
        
        self.recording_progress = ft.ProgressRing(
            visible=False,
            width=24,
            height=24,
            stroke_width=3,
            color=theme.ACCENT
        )
        
        # Auto-login checkbox
        self.auto_login_checkbox = ft.Checkbox(
            label="Auto-login to D365 (uses Key Vault credentials)",
            value=True,
        )
        
        # Buttons
        self.start_record_btn = theme.accent_button(
            text="Start Recording",
            icon=ft.Icons.FIBER_MANUAL_RECORD,
            on_click=self._on_start_recording
        )
        
        # Config summary
        self.config_summary = self._build_config_summary()
        
        content = ft.Column(
            controls=[
                # Test Info Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Test Information", ft.Icons.INFO),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.test_name_field,
                        self.test_description_field,
                    ], spacing=16)
                ),
                
                ft.Container(height=16),
                
                # Recording Controls
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Recording", ft.Icons.VIDEOCAM),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.auto_login_checkbox,
                        ft.Text(
                            "When enabled, the app will automatically log into D365 using credentials from Key Vault before recording starts.",
                            color=theme.TEXT_SECONDARY,
                            size=12,
                        ),
                        ft.Container(height=8),
                        ft.Row([
                            self.recording_progress,
                            self.recording_status,
                        ], spacing=12),
                        ft.Container(height=8),
                        ft.Row([
                            self.start_record_btn,
                        ]),
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # Current Configuration Summary
                self.config_summary,
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )
    
    def _build_config_summary(self) -> ft.Container:
        """Build configuration summary card."""
        # These will be updated when config changes
        self.summary_d365_url = ft.Text("Not configured", color=theme.TEXT_SECONDARY)
        self.summary_keyvault = ft.Text("Not configured", color=theme.TEXT_SECONDARY)
        self.summary_devops = ft.Text("Disabled", color=theme.TEXT_SECONDARY)
        self.summary_output = ft.Text("Not set", color=theme.TEXT_SECONDARY)
        self.summary_destination = ft.Text("Local only", color=theme.TEXT_SECONDARY)
        
        return theme.styled_card(
            ft.Column([
                theme.section_title("Current Configuration", ft.Icons.CHECK_CIRCLE),
                ft.Divider(height=1, color=theme.DIVIDER),
                ft.Row([
                    ft.Text("D365 URL:", weight=ft.FontWeight.BOLD, width=120),
                    self.summary_d365_url,
                ]),
                ft.Row([
                    ft.Text("Key Vault:", weight=ft.FontWeight.BOLD, width=120),
                    self.summary_keyvault,
                ]),
                ft.Row([
                    ft.Text("DevOps:", weight=ft.FontWeight.BOLD, width=120),
                    self.summary_devops,
                ]),
                ft.Row([
                    ft.Text("Output Dir:", weight=ft.FontWeight.BOLD, width=120),
                    self.summary_output,
                ]),
                ft.Row([
                    ft.Text("Destination:", weight=ft.FontWeight.BOLD, width=120),
                    self.summary_destination,
                ]),
                ft.Container(height=8),
                ft.TextButton(
                    "Go to Settings",
                    icon=ft.Icons.SETTINGS,
                    on_click=lambda _: self._switch_to_tab(2)
                )
            ], spacing=8)
        )
    
    def _update_config_summary(self):
        """Update the configuration summary display."""
        config = self.config
        
        # D365 URL
        if config.d365.environment_url:
            url = config.d365.environment_url
            if len(url) > 50:
                url = url[:50] + "..."
            self.summary_d365_url.value = url
            self.summary_d365_url.color = theme.SUCCESS
        else:
            self.summary_d365_url.value = "Not configured"
            self.summary_d365_url.color = theme.ERROR
        
        # Key Vault
        if self.config_manager.is_keyvault_configured():
            self.summary_keyvault.value = "Configured ✓"
            self.summary_keyvault.color = theme.SUCCESS
        else:
            self.summary_keyvault.value = "Not configured"
            self.summary_keyvault.color = theme.WARNING
        
        # DevOps
        if self.skip_devops:
            self.summary_devops.value = "Skipped (test mode)"
            self.summary_devops.color = theme.TEXT_SECONDARY
        elif config.devops.enabled and self.config_manager.is_devops_configured():
            self.summary_devops.value = f"Enabled - {config.devops.branch}"
            self.summary_devops.color = theme.SUCCESS
        else:
            self.summary_devops.value = "Disabled"
            self.summary_devops.color = theme.TEXT_SECONDARY
        
        # Output directory
        if config.local_storage.output_directory:
            path = config.local_storage.output_directory
            if len(path) > 40:
                path = "..." + path[-40:]
            self.summary_output.value = path
            self.summary_output.color = theme.SUCCESS
        else:
            self.summary_output.value = "Not set"
            self.summary_output.color = theme.WARNING
        
        # Destination
        dest_map = {
            SaveDestination.LOCAL_ONLY: "Local only",
            SaveDestination.DEVOPS_ONLY: "DevOps only",
            SaveDestination.LOCAL_AND_DEVOPS: "Local + DevOps",
        }
        self.summary_destination.value = dest_map.get(config.save_destination, "Unknown")
        self.summary_destination.color = theme.TEXT_PRIMARY
        
        self.page.update()
    
    def _on_start_recording(self, e):
        """Handle start recording button click."""
        # Validate inputs
        test_name = self.test_name_field.value.strip()
        if not test_name:
            self._show_snackbar("Please enter a test name", "error")
            return
        
        if not self.config.d365.environment_url:
            self._show_snackbar("Please configure D365 URL in Settings first", "error")
            return
        
        if not self.config.local_storage.output_directory:
            self._show_snackbar("Please set output directory in Settings first", "error")
            return
        
        # Initialize managers if needed
        self._initialize_managers()
        
        # Check if auto-login is requested but no credentials available
        auto_login = self.auto_login_checkbox.value
        if auto_login and not self.recorder.has_credentials:
            self._show_snackbar(
                "Auto-login enabled but Key Vault credentials not configured. Configure in Settings or disable auto-login.",
                "warning"
            )
            return
        
        # Start recording
        status_msg = "Recording in progress... "
        if auto_login and self.recorder.has_credentials:
            status_msg += "Auto-logging in to D365..."
        else:
            status_msg += "Close the browser when done."
        
        self.recording_status.value = status_msg
        self.recording_status.color = theme.ACCENT
        self.recording_progress.visible = True
        self.start_record_btn.disabled = True
        self.page.update()
        
        description = self.test_description_field.value.strip()
        
        try:
            self.recorder.start_recording(
                test_name=test_name,
                description=description,
                auto_login=auto_login,
                on_complete=self._on_recording_complete,
                on_error=self._on_recording_error
            )
        except Exception as ex:
            self._on_recording_error(str(ex))
    
    def _on_recording_complete(self, result: RecordingResult):
        """Handle recording completion."""
        self.current_recording_result = result
        
        def update_ui():
            self.recording_progress.visible = False
            self.start_record_btn.disabled = False
            
            if result.success:
                self.recording_status.value = f"Recording saved: {result.file_path}"
                self.recording_status.color = theme.SUCCESS
                
                # Initialize post-processor
                if result.generated_code:
                    self.post_processor = PostProcessor(result.generated_code)
                    self._update_postprocess_tab()
                    self._show_snackbar(
                        "Recording complete! Go to Post-Process tab to review inputs.",
                        "success"
                    )
                    # Switch to post-process tab
                    self._switch_to_tab(1)
                
                # Refresh recent tests dropdown so new test appears
                self._refresh_recent_tests()
            else:
                self.recording_status.value = result.message
                self.recording_status.color = theme.ERROR
                self._show_snackbar(result.message, "error")
            
            self.page.update()
        
        # Update UI from main thread
        update_ui()
    
    def _on_recording_error(self, error: str):
        """Handle recording error."""
        def update_ui():
            self.recording_progress.visible = False
            self.start_record_btn.disabled = False
            self.recording_status.value = f"Error: {error}"
            self.recording_status.color = theme.ERROR
            self.page.update()
            self._show_snackbar(f"Recording failed: {error}", "error")
        
        update_ui()
    
    # =========================================================================
    # POST-PROCESS TAB
    # =========================================================================
    
    def _build_postprocess_tab(self) -> ft.Container:
        """Build the post-processing tab content."""
        
        # Inputs list view
        self.inputs_list = ft.ListView(
            expand=True,
            spacing=8,
            padding=8,
        )
        
        # No recording message
        self.no_recording_message = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.PENDING_ACTIONS, size=64, color=theme.TEXT_SECONDARY),
                ft.Text(
                    "No recording to process",
                    size=18,
                    color=theme.TEXT_SECONDARY,
                    text_align=ft.TextAlign.CENTER
                ),
                ft.Text(
                    "Record a test first, then come back here to modify input values.",
                    color=theme.TEXT_SECONDARY,
                    text_align=ft.TextAlign.CENTER
                ),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            alignment=ft.alignment.center,
            expand=True,
        )
        
        # Action buttons
        self.save_changes_btn = theme.accent_button(
            text="Save & Export",
            icon=ft.Icons.SAVE,
            on_click=self._on_save_changes,
            disabled=True
        )
        
        self.reset_changes_btn = theme.styled_button(
            text="Reset Changes",
            icon=ft.Icons.RESTORE,
            on_click=self._on_reset_changes,
            primary=False,
            disabled=True
        )
        
        # Summary
        self.postprocess_summary = ft.Text(
            "0 inputs detected",
            color=theme.TEXT_SECONDARY
        )
        
        content = ft.Column(
            controls=[
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Detected Inputs", ft.Icons.INPUT),
                        ft.Text(
                            "Review and modify the input values used in your recorded test. "
                            "You can convert values to variables or change them directly.",
                            color=theme.TEXT_SECONDARY,
                            size=13
                        ),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.postprocess_summary,
                        ft.Container(
                            content=ft.Stack([
                                self.no_recording_message,
                                self.inputs_list,
                            ]),
                            height=400,
                            border=ft.border.all(1, theme.BORDER),
                            border_radius=8,
                        ),
                        ft.Container(height=8),
                        ft.Row([
                            self.reset_changes_btn,
                            self.save_changes_btn,
                        ], spacing=12),
                    ], spacing=12)
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        
        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )
    
    def _update_postprocess_tab(self):
        """Update the post-process tab with detected inputs."""
        if not self.post_processor:
            self.no_recording_message.visible = True
            self.inputs_list.visible = False
            self.save_changes_btn.disabled = True
            self.reset_changes_btn.disabled = True
            self.postprocess_summary.value = "0 inputs detected"
            return
        
        inputs = self.post_processor.get_inputs()
        
        if not inputs:
            self.no_recording_message.visible = True
            self.inputs_list.visible = False
            self.save_changes_btn.disabled = True
            self.reset_changes_btn.disabled = True
            self.postprocess_summary.value = "No input values detected in the recording"
            self.page.update()
            return
        
        self.no_recording_message.visible = False
        self.inputs_list.visible = True
        self.save_changes_btn.disabled = False
        self.reset_changes_btn.disabled = False
        
        # Build input items
        self.inputs_list.controls.clear()
        
        for inp in inputs:
            self.inputs_list.controls.append(
                self._build_input_item(inp)
            )
        
        summary = self.post_processor.get_summary()
        self.postprocess_summary.value = (
            f"{summary['total_inputs']} inputs detected, "
            f"{summary['modified_inputs']} modified"
        )
        
        self.page.update()
    
    def _build_input_item(self, inp: DetectedInput) -> ft.Container:
        """Build a single input item for the list."""
        suggested_name = self.post_processor.get_suggested_name(inp)
        
        # Value field
        value_field = ft.TextField(
            value=inp.display_value,
            label="Value",
            dense=True,
            border_radius=6,
            expand=True,
            on_change=lambda e, i=inp: self._on_input_value_changed(e, i),
        )
        
        # Variable name field
        var_field = ft.TextField(
            value=inp.variable_name or "",
            label="Variable Name (optional)",
            hint_text=suggested_name,
            dense=True,
            border_radius=6,
            width=200,
            on_change=lambda e, i=inp: self._on_input_variable_changed(e, i),
        )
        
        # Use suggested name button
        use_suggested_btn = ft.IconButton(
            icon=ft.Icons.AUTO_FIX_HIGH,
            tooltip=f"Use suggested: {suggested_name}",
            on_click=lambda e, i=inp, v=var_field, s=suggested_name: self._use_suggested_name(i, v, s),
        )
        
        # Type badge
        type_badge = theme.status_badge(
            inp.input_type.value,
            status="info" if inp.input_type.value in ["text", "number"] else "warning"
        )
        
        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(f"Line {inp.line_number}", weight=ft.FontWeight.BOLD),
                    type_badge,
                    ft.Text(f"Action: {inp.action}", color=theme.TEXT_SECONDARY, size=12),
                ], spacing=8),
                ft.Row([
                    value_field,
                    var_field,
                    use_suggested_btn,
                ], spacing=8),
            ], spacing=8),
            padding=12,
            bgcolor=theme.SURFACE,
            border=ft.border.all(1, theme.BORDER if not inp.is_modified else theme.ACCENT),
            border_radius=8,
        )
    
    def _on_input_value_changed(self, e, inp: DetectedInput):
        """Handle input value change."""
        new_value = e.control.value
        if new_value != inp.value:
            self.post_processor.set_new_value(inp, new_value)
        else:
            inp.new_value = None
        self._update_postprocess_summary()
    
    def _on_input_variable_changed(self, e, inp: DetectedInput):
        """Handle variable name change."""
        var_name = e.control.value.strip()
        if var_name:
            self.post_processor.set_variable(inp, var_name)
        else:
            inp.variable_name = None
        self._update_postprocess_summary()
    
    def _use_suggested_name(self, inp: DetectedInput, var_field: ft.TextField, suggested: str):
        """Use the suggested variable name."""
        var_field.value = suggested
        self.post_processor.set_variable(inp, suggested)
        self._update_postprocess_summary()
        self.page.update()
    
    def _update_postprocess_summary(self):
        """Update the post-process summary."""
        if self.post_processor:
            summary = self.post_processor.get_summary()
            self.postprocess_summary.value = (
                f"{summary['total_inputs']} inputs detected, "
                f"{summary['modified_inputs']} modified"
            )
            self.page.update()
    
    def _on_save_changes(self, e):
        """Handle save changes button."""
        if not self.post_processor or not self.current_recording_result:
            self._show_snackbar("No recording to save", "error")
            return
        
        # Apply modifications
        modified_code = self.post_processor.apply()
        
        # Get the original file path to replace it
        session = self.current_recording_result.session
        original_file_path = self.current_recording_result.file_path
        
        # Use the same filename as the original recording
        file_name = os.path.basename(original_file_path) if original_file_path else \
                    f"test_{session.test_name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
        
        # Save using file manager
        self._initialize_managers()
        
        results = self.file_manager.save_test(
            file_name=file_name,
            content=modified_code,
            description=session.description
        )
        
        # Show results
        messages = []
        if results["local"]["success"]:
            messages.append(f"Saved locally: {results['local']['path']}")
        elif self.config.save_destination in (SaveDestination.LOCAL_ONLY, SaveDestination.LOCAL_AND_DEVOPS):
            messages.append(f"Local save failed: {results['local']['message']}")
        
        if results["devops"]["success"]:
            messages.append(f"Pushed to DevOps: {results['devops']['commit_id'][:8]}")
        elif self.config.save_destination in (SaveDestination.DEVOPS_ONLY, SaveDestination.LOCAL_AND_DEVOPS):
            if not self.skip_devops:
                messages.append(f"DevOps push failed: {results['devops']['message']}")
        
        self._show_snackbar("\n".join(messages), "success" if any(r["success"] for r in results.values()) else "error")
    
    def _on_reset_changes(self, e):
        """Handle reset changes button."""
        if self.post_processor:
            for inp in self.post_processor.get_inputs():
                self.post_processor.clear_modification(inp)
            self._update_postprocess_tab()
            self._show_snackbar("Changes reset", "info")
    
    # =========================================================================
    # RUN TESTS TAB
    # =========================================================================
    
    def _build_run_tests_tab(self) -> ft.Container:
        """Build the run tests tab content."""
        
        # Test file selection
        self.selected_test_file = ft.Text(
            "No test file selected",
            color=theme.TEXT_SECONDARY,
            size=14,
        )
        
        self.select_test_btn = theme.styled_button(
            text="Select Test File",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_select_test_file,
            primary=False,
        )
        
        self.select_recent_dropdown = ft.Dropdown(
            label="Or select recent test",
            hint_text="Choose from recent recordings",
            options=[],
            on_change=self._on_recent_test_selected,
            border_radius=8,
            width=400,
            bgcolor="#FFFFFF",
            color="#000000",
            text_style=ft.TextStyle(color="#000000"),
        )
        
        # Run options
        self.run_headed_checkbox = ft.Checkbox(
            label="Run in headed mode (show browser)",
            value=True,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        self.run_slowmo_checkbox = ft.Checkbox(
            label="Slow motion (500ms delay)",
            value=False,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        self.run_debug_checkbox = ft.Checkbox(
            label="Debug mode (pause on failure)",
            value=False,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        self.run_autologin_checkbox = ft.Checkbox(
            label="Auto-login before test (uses Key Vault credentials)",
            value=True,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        # Direct credential inputs (for when Key Vault is not configured)

        
        # Run button
        self.run_test_btn = theme.accent_button(
            text="Run Test",
            icon=ft.Icons.PLAY_ARROW,
            on_click=self._on_run_test,
            disabled=True,
        )
        
        self.stop_test_btn = theme.styled_button(
            text="Stop",
            icon=ft.Icons.STOP,
            on_click=self._on_stop_test,
            primary=False,
        )
        self.stop_test_btn.visible = False
        
        # Test status
        self.test_run_status = ft.Text(
            "Ready to run tests",
            color=theme.TEXT_SECONDARY,
            size=14,
        )
        
        self.test_run_progress = ft.ProgressRing(
            visible=False,
            width=24,
            height=24,
            stroke_width=3,
            color=theme.ACCENT
        )
        
        # Results section
        self.test_results_container = ft.Container(
            content=ft.Column([
                ft.Text("No results yet", color=theme.TEXT_SECONDARY),
            ]),
            visible=False,
        )
        
        # Results summary
        self.results_summary = ft.Row(
            controls=[],
            spacing=16,
        )
        
        # Output log
        self.test_output_log = ft.TextField(
            label="Test Output",
            multiline=True,
            min_lines=15,
            max_lines=20,
            read_only=True,
            value="",
            border_color=theme.BORDER,
            border_radius=8,
        )
        
        content = ft.Column(
            controls=[
                # Test Selection Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Select Test", ft.Icons.DESCRIPTION),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Row([
                            self.select_test_btn,
                            ft.Container(width=16),
                            ft.Column([self.selected_test_file], expand=True),
                        ]),
                        ft.Container(height=8),
                        self.select_recent_dropdown,
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # Run Options Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Run Options", ft.Icons.SETTINGS),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.run_headed_checkbox,
                        self.run_slowmo_checkbox,
                        self.run_debug_checkbox,
                        self.run_autologin_checkbox,
                        ft.Container(height=8),
                        ft.Row([
                            self.run_test_btn,
                            self.stop_test_btn,
                            ft.Container(width=16),
                            self.test_run_progress,
                            self.test_run_status,
                        ], spacing=12),
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # Results Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Test Results", ft.Icons.ASSESSMENT),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.results_summary,
                        ft.Container(height=8),
                        self.test_output_log,
                    ], spacing=12)
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        
        # Load recent tests on build
        self._refresh_recent_tests()
        
        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )
    
    def _refresh_recent_tests(self):
        """Refresh the list of recent test files."""
        recent_tests = []
        
        # Check output directory for test files
        output_dir = self.config.local_storage.output_directory
        if output_dir and os.path.exists(output_dir):
            try:
                files = sorted(
                    [f for f in os.listdir(output_dir) if f.startswith("test_") and f.endswith(".py")],
                    reverse=True  # Most recent first
                )[:10]  # Limit to 10 most recent
                
                for f in files:
                    recent_tests.append(
                        ft.dropdown.Option(
                            key=os.path.join(output_dir, f),
                            text=f
                        )
                    )
            except Exception as e:
                logger.warning(f"Could not list recent tests: {e}")
        
        self.select_recent_dropdown.options = recent_tests
        if hasattr(self, 'page') and self.page:
            self.page.update()
    
    def _on_select_test_file(self, e):
        """Handle select test file button click."""
        import platform
        import subprocess
        
        # On macOS, use AppleScript to show file picker
        if platform.system() == "Darwin":
            try:
                script = '''
                    tell application "Finder"
                        activate
                        set theFile to choose file with prompt "Select Test File" of type {"py"}
                        return POSIX path of theFile
                    end tell
                '''
                result = subprocess.run(
                    ['osascript', '-e', script],
                    capture_output=True, text=True, timeout=120
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    file_path = result.stdout.strip()
                    self._set_selected_test(file_path)
                    return
            except Exception as ex:
                logger.warning(f"AppleScript file picker failed: {ex}")
        
        # Fallback to Flet file picker
        try:
            self.test_file_picker.pick_files(
                dialog_title="Select Test File",
                allowed_extensions=["py"],
                allow_multiple=False
            )
        except Exception as ex:
            self._show_snackbar("File picker not available. Select from recent tests instead.", "warning")
    
    def _on_test_file_picked(self, e: ft.FilePickerResultEvent):
        """Handle test file picker result."""
        if e.files and len(e.files) > 0:
            self._set_selected_test(e.files[0].path)
    
    def _on_recent_test_selected(self, e):
        """Handle recent test dropdown selection."""
        if e.control.value:
            self._set_selected_test(e.control.value)
    
    def _set_selected_test(self, file_path: str):
        """Set the selected test file."""
        self._selected_test_path = file_path
        file_name = os.path.basename(file_path)
        self.selected_test_file.value = file_name
        self.selected_test_file.color = theme.TEXT_PRIMARY
        self.run_test_btn.disabled = False
        self.page.update()
    

    
    def _on_run_test(self, e):
        """Run the selected test."""
        print("[DEBUG] _on_run_test called")
        
        # Ensure managers are initialized with latest config
        self._initialize_managers()
        print(f"[DEBUG] Managers initialized - credentials_manager: {self.credentials_manager is not None}")
        
        if not hasattr(self, '_selected_test_path') or not self._selected_test_path:
            print("[DEBUG] No test selected")
            self._show_snackbar("Please select a test file first", "error")
            return
        
        if not os.path.exists(self._selected_test_path):
            print(f"[DEBUG] Test file not found: {self._selected_test_path}")
            self._show_snackbar("Test file not found", "error")
            return
        
        # Check if auto-login is needed and credentials are available
        if self.run_autologin_checkbox.value:
            print(f"[DEBUG] Auto-login enabled, credentials_manager: {self.credentials_manager is not None}")
            if not self.credentials_manager:
                print("[DEBUG] No credentials_manager - unchecking auto-login")
                self.run_autologin_checkbox.value = False
                self._show_snackbar("Auto-login disabled: Key Vault not configured. Configure in Settings to enable auto-login.", "warning")
                # Continue with test without auto-login
        
        print("[DEBUG] Starting test run...")
        
        # Update UI
        self.test_run_status.value = "Running test..."
        self.test_run_status.color = theme.ACCENT
        self.test_run_progress.visible = True
        self.run_test_btn.disabled = True
        self.stop_test_btn.visible = True
        self.test_output_log.value = ""
        self.results_summary.controls.clear()
        self.page.update()
        
        # Run in background thread
        def run_test():
            print("[DEBUG] Thread started")
            import subprocess
            
            try:
                # Build pytest command
                cmd = ["python", "-m", "pytest", self._selected_test_path, "-v", "--tb=short"]
                
                if self.run_headed_checkbox.value:
                    cmd.append("--headed")
                
                if self.run_slowmo_checkbox.value:
                    cmd.extend(["--slowmo", "500"])
                
                if self.run_debug_checkbox.value:
                    cmd.append("--pdb")
                
                # Set environment variables
                env = {**os.environ}
                env["PWDEBUG"] = "1" if self.run_debug_checkbox.value else "0"
                
                # Pass credentials via environment variables for auto-login
                if self.run_autologin_checkbox.value and self.credentials_manager:
                    try:
                        print(f"[DEBUG] Loading credentials from Key Vault...")
                        kv_config = self.config.keyvault
                        print(f"[DEBUG] Secret names: username={kv_config.fo_username_secret}, password={kv_config.fo_password_secret}, totp={kv_config.fo_totp_secret}")
                        
                        username = self.credentials_manager.get_fo_username(kv_config.fo_username_secret)
                        password = self.credentials_manager.get_fo_password(kv_config.fo_password_secret)
                        totp_secret = None
                        if kv_config.fo_totp_secret:
                            totp_secret = self.credentials_manager.get_secret(kv_config.fo_totp_secret)
                            print(f"[DEBUG] TOTP secret retrieved: {len(totp_secret) if totp_secret else 0} chars")
                        
                        print(f"[DEBUG] Key Vault results: username={'yes' if username else 'no'}, password={'yes' if password else 'no'}, totp={'yes' if totp_secret else 'no'}")
                        
                        if username and password:
                            env["D365_USERNAME"] = username
                            env["D365_PASSWORD"] = password
                            if totp_secret:
                                env["D365_TOTP_SECRET"] = totp_secret
                                self.test_output_log.value = f"✓ Credentials loaded from Key Vault.\n✓ TOTP secret configured - MFA will be automatic.\n\n"
                            else:
                                self.test_output_log.value = f"✓ Credentials loaded from Key Vault.\n⚠ No TOTP secret - you'll need to enter MFA code manually.\n\n"
                        else:
                            self.test_output_log.value = f"⚠ Could not retrieve credentials from Key Vault.\n\n"
                        self.page.update()
                    except Exception as cred_ex:
                        import traceback
                        print(f"[DEBUG] Key Vault error: {cred_ex}")
                        traceback.print_exc()
                        self.test_output_log.value = f"⚠ Error loading credentials: {cred_ex}\n\n"
                        self.page.update()
                
                self._test_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env
                )
                
                output_lines = []
                if self.test_output_log.value:
                    output_lines.append(self.test_output_log.value)
                    
                for line in self._test_process.stdout:
                    output_lines.append(line)
                    # Update UI with output
                    self.test_output_log.value = "".join(output_lines[-100:])  # Keep last 100 lines
                    self.page.update()
                
                self._test_process.wait()
                return_code = self._test_process.returncode
                
                # Parse results
                full_output = "".join(output_lines)
                self._display_test_results(return_code, full_output)
                
            except Exception as ex:
                self.test_run_status.value = f"Error: {str(ex)}"
                self.test_run_status.color = theme.ERROR
                self.test_output_log.value = str(ex)
            finally:
                self.test_run_progress.visible = False
                self.run_test_btn.disabled = False
                self.stop_test_btn.visible = False
                self._test_process = None
                self.page.update()
        
        self._test_thread = threading.Thread(target=run_test, daemon=True)
        self._test_thread.start()

    def _on_stop_test(self, e):
        """Stop the running test."""
        if hasattr(self, '_test_process') and self._test_process:
            self._test_process.terminate()
            self.test_run_status.value = "Test stopped"
            self.test_run_status.color = theme.WARNING
            self._show_snackbar("Test execution stopped", "warning")
    
    def _display_test_results(self, return_code: int, output: str):
        """Display test results in the UI."""
        # Determine status
        if return_code == 0:
            self.test_run_status.value = "✓ Test PASSED"
            self.test_run_status.color = theme.SUCCESS
            status_badge = theme.status_badge("PASSED", "success")
        elif return_code == 1:
            self.test_run_status.value = "✗ Test FAILED"
            self.test_run_status.color = theme.ERROR
            status_badge = theme.status_badge("FAILED", "error")
        else:
            self.test_run_status.value = f"Test finished with code {return_code}"
            self.test_run_status.color = theme.WARNING
            status_badge = theme.status_badge(f"CODE {return_code}", "warning")
        
        # Parse output for stats
        import re
        
        # Try to find pytest summary line like "1 passed in 5.23s"
        passed = 0
        failed = 0
        skipped = 0
        duration = "N/A"
        
        passed_match = re.search(r'(\d+) passed', output)
        if passed_match:
            passed = int(passed_match.group(1))
        
        failed_match = re.search(r'(\d+) failed', output)
        if failed_match:
            failed = int(failed_match.group(1))
        
        skipped_match = re.search(r'(\d+) skipped', output)
        if skipped_match:
            skipped = int(skipped_match.group(1))
        
        duration_match = re.search(r'in ([\d.]+)s', output)
        if duration_match:
            duration = f"{float(duration_match.group(1)):.2f}s"
        
        # Build summary
        self.results_summary.controls = [
            status_badge,
            ft.Container(width=16),
            ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, color=theme.SUCCESS, size=20),
                ft.Text(f"{passed} passed", color=theme.SUCCESS),
            ], spacing=4),
            ft.Row([
                ft.Icon(ft.Icons.CANCEL, color=theme.ERROR, size=20),
                ft.Text(f"{failed} failed", color=theme.ERROR if failed > 0 else theme.TEXT_SECONDARY),
            ], spacing=4),
            ft.Row([
                ft.Icon(ft.Icons.SKIP_NEXT, color=theme.WARNING, size=20),
                ft.Text(f"{skipped} skipped", color=theme.WARNING if skipped > 0 else theme.TEXT_SECONDARY),
            ], spacing=4),
            ft.Container(width=16),
            ft.Row([
                ft.Icon(ft.Icons.TIMER, color=theme.TEXT_SECONDARY, size=20),
                ft.Text(f"Duration: {duration}", color=theme.TEXT_SECONDARY),
            ], spacing=4),
        ]
        
        self.page.update()
    
    # =========================================================================
    # SETTINGS TAB
    # =========================================================================
    
    def _build_settings_tab(self) -> ft.Container:
        """Build the settings tab content."""
        
        # D365 Settings
        self.d365_url_field = theme.styled_textfield(
            label="D365 F&O Environment URL",
            hint_text="https://your-env.dynamics.com",
            icon=ft.Icons.LINK,
        )
        
        self.d365_auto_login = ft.Checkbox(
            label="Auto-login using Key Vault credentials",
            value=True,
        )
        
        # Key Vault Settings
        self.kv_url_field = theme.styled_textfield(
            label="Key Vault URL",
            hint_text="https://your-vault.vault.azure.net",
            icon=ft.Icons.SECURITY,
        )
        
        self.kv_tenant_field = theme.styled_textfield(
            label="Azure AD Tenant ID",
            hint_text="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            icon=ft.Icons.BUSINESS,
        )
        
        self.kv_client_id_field = theme.styled_textfield(
            label="Application (Client) ID",
            hint_text="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            icon=ft.Icons.APPS,
        )
        
        self.kv_client_secret_field = theme.styled_textfield(
            label="Client Secret",
            password=True,
            icon=ft.Icons.KEY,
        )
        
        # Key Vault Secret Names
        self.kv_fo_username_secret = theme.styled_textfield(
            label="F&O Username Secret Name",
            hint_text="fo-username",
        )
        
        self.kv_fo_password_secret = theme.styled_textfield(
            label="F&O Password Secret Name",
            hint_text="fo-password",
        )
        
        self.kv_fo_totp_secret = theme.styled_textfield(
            label="TOTP Secret Name (for auto MFA)",
            hint_text="fo-totp-secret",
        )
        
        self.kv_devops_pat_secret = theme.styled_textfield(
            label="DevOps PAT Secret Name",
            hint_text="devops-pat",
        )
        
        self.test_keyvault_btn = theme.styled_button(
            text="Test Connection",
            icon=ft.Icons.WIFI_TETHERING,
            on_click=self._on_test_keyvault,
            primary=False,
        )
        
        self.keyvault_status = ft.Text("", color=theme.TEXT_SECONDARY, size=12)
        
        # DevOps Settings
        self.devops_enabled = ft.Switch(
            label="Enable Azure DevOps Integration",
            value=False,
            on_change=self._on_devops_toggle,
        )
        
        self.devops_org_field = theme.styled_textfield(
            label="Organization",
            hint_text="your-org",
            icon=ft.Icons.BUSINESS,
        )
        
        self.devops_project_field = theme.styled_textfield(
            label="Project",
            hint_text="your-project",
            icon=ft.Icons.FOLDER,
        )
        
        self.devops_repo_field = theme.styled_textfield(
            label="Repository",
            hint_text="your-repo",
            icon=ft.Icons.SOURCE,
        )
        
        self.devops_branch_dropdown = ft.Dropdown(
            label="Branch",
            hint_text="Select branch",
            options=[],
            border_radius=8,
            bgcolor="#FFFFFF",
            color="#000000",
            text_style=ft.TextStyle(color="#000000"),
        )
        
        self.fetch_branches_btn = theme.styled_button(
            text="Fetch Branches",
            icon=ft.Icons.REFRESH,
            on_click=self._on_fetch_branches,
            primary=False,
        )
        
        self.devops_folder_field = theme.styled_textfield(
            label="Target Folder",
            hint_text="/tests/recorded",
            icon=ft.Icons.FOLDER_OPEN,
        )
        
        self.test_devops_btn = theme.styled_button(
            text="Test Connection",
            icon=ft.Icons.WIFI_TETHERING,
            on_click=self._on_test_devops,
            primary=False,
        )
        
        self.devops_status = ft.Text("", color=theme.TEXT_SECONDARY, size=12)
        
        # Local Storage Settings
        self.output_dir_field = theme.styled_textfield(
            label="Output Directory",
            hint_text="Enter path or click Browse",
            icon=ft.Icons.FOLDER,
            disabled=False,  # Allow manual entry too
        )
        
        self.browse_folder_btn = theme.styled_button(
            text="Browse",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_browse_folder,
            primary=False,
        )
        
        # Save Destination
        self.destination_dropdown = ft.Dropdown(
            label="Save Destination",
            options=[
                ft.dropdown.Option(key="local", text="Local Only"),
                ft.dropdown.Option(key="devops", text="DevOps Only"),
                ft.dropdown.Option(key="local_and_devops", text="Local + DevOps"),
            ],
            value="local",
            border_radius=8,
            bgcolor="#FFFFFF",
            color="#000000",
            text_style=ft.TextStyle(color="#000000"),
        )
        
        # Recording Settings
        self.browser_dropdown = ft.Dropdown(
            label="Browser",
            options=[
                ft.dropdown.Option(key="chromium", text="Chromium"),
                ft.dropdown.Option(key="firefox", text="Firefox"),
                ft.dropdown.Option(key="webkit", text="WebKit (Safari)"),
            ],
            value="chromium",
            border_radius=8,
            bgcolor="#FFFFFF",
            color="#000000",
            text_style=ft.TextStyle(color="#000000"),
        )
        
        self.viewport_dropdown = ft.Dropdown(
            label="Viewport",
            options=[
                ft.dropdown.Option(key="match_window", text="Match Window Size"),
                ft.dropdown.Option(key="1920x1080", text="1920x1080 (Full HD)"),
                ft.dropdown.Option(key="1366x768", text="1366x768 (HD)"),
                ft.dropdown.Option(key="1280x720", text="1280x720 (720p)"),
                ft.dropdown.Option(key="1440x900", text="1440x900 (Laptop)"),
                ft.dropdown.Option(key="custom", text="Custom"),
            ],
            value="match_window",
            border_radius=8,
            bgcolor="#FFFFFF",
            color="#000000",
            text_style=ft.TextStyle(color="#000000"),
        )
        
        self.add_screenshots = ft.Checkbox(
            label="Add screenshot on failure",
            value=True,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        self.add_retry = ft.Checkbox(
            label="Add retry configuration",
            value=True,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        self.cleanup_code = ft.Checkbox(
            label="Clean up recorded code (remove boilerplate)",
            value=True,
            label_style=ft.TextStyle(color=theme.TEXT_PRIMARY),
            check_color=theme.SURFACE,
            fill_color=theme.ACCENT,
        )
        
        self.retry_count_field = theme.styled_textfield(
            label="Retry Count",
            value="2",
        )
        
        # Save Settings Button
        self.save_settings_btn = theme.accent_button(
            text="Save Settings",
            icon=ft.Icons.SAVE,
            on_click=self._on_save_settings,
        )
        
        # Test timeout field
        self.test_timeout_field = theme.styled_textfield(
            label="Test Timeout (seconds)",
            hint_text="15",
            value="15",
            icon=ft.Icons.TIMER,
        )
        
        # Retry count field  
        self.test_retry_count_field = theme.styled_textfield(
            label="Retry Count on Failure",
            hint_text="2",
            value="2",
            icon=ft.Icons.REPLAY,
        )
        
        # Screenshot output directory
        self.screenshot_dir_field = theme.styled_textfield(
            label="Screenshot Output Directory",
            hint_text="/path/to/screenshots",
            icon=ft.Icons.FOLDER,
        )
        self.screenshot_dir_field.read_only = True
        
        self.browse_screenshot_dir_btn = theme.styled_button(
            text="Browse",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_browse_screenshot_dir,
            primary=False,
        )
        
        # Build settings content with sections
        content = ft.Column(
            controls=[
                # === GENERAL SECTION ===
                ft.Text("GENERAL", size=16, weight=ft.FontWeight.BOLD, color=theme.ACCENT),
                ft.Divider(height=2, color=theme.ACCENT),
                
                # D365 Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("D365 Finance & Operations", ft.Icons.BUSINESS_CENTER),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.d365_url_field,
                        self.d365_auto_login,
                    ], spacing=12)
                ),
                
                ft.Container(height=8),
                
                # Key Vault Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Azure Key Vault", ft.Icons.SECURITY),
                        ft.Text(
                            "Configure Azure AD App Registration to access Key Vault secrets",
                            color=theme.TEXT_SECONDARY,
                            size=12
                        ),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Row([
                            ft.Column([self.kv_url_field], expand=True),
                            ft.Column([self.kv_tenant_field], expand=True),
                        ], spacing=16),
                        ft.Row([
                            ft.Column([self.kv_client_id_field], expand=True),
                            ft.Column([self.kv_client_secret_field], expand=True),
                        ], spacing=16),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Text("Secret Names in Key Vault:", weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.Column([self.kv_fo_username_secret], expand=True),
                            ft.Column([self.kv_fo_password_secret], expand=True),
                        ], spacing=16),
                        ft.Row([
                            ft.Column([self.kv_fo_totp_secret], expand=True),
                            ft.Column([self.kv_devops_pat_secret], expand=True),
                        ], spacing=16),
                        ft.Text(
                            "💡 TOTP Secret: Store your authenticator app's TOTP secret in Key Vault for automatic MFA. "
                            "Leave empty for manual OTP entry.",
                            size=11,
                            color=theme.TEXT_SECONDARY,
                            italic=True,
                        ),
                        ft.Row([
                            self.test_keyvault_btn,
                            self.keyvault_status,
                        ], spacing=12),
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # DevOps Section
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Azure DevOps", ft.Icons.CODE),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        self.devops_enabled,
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Column([self.devops_org_field], expand=True),
                                    ft.Column([self.devops_project_field], expand=True),
                                ], spacing=16),
                                ft.Row([
                                    ft.Column([self.devops_repo_field], expand=True),
                                    ft.Column([self.devops_folder_field], expand=True),
                                ], spacing=16),
                                ft.Row([
                                    ft.Column([self.devops_branch_dropdown], expand=True),
                                    self.fetch_branches_btn,
                                ], spacing=16),
                                ft.Row([
                                    self.test_devops_btn,
                                    self.devops_status,
                                ], spacing=12),
                            ], spacing=12),
                            visible=False,
                            ref=ft.Ref[ft.Container](),
                        )
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # Local Storage & Destination
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Output Settings", ft.Icons.FOLDER),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Row([
                            ft.Column([self.output_dir_field], expand=True),
                            self.browse_folder_btn,
                        ], spacing=12),
                        self.destination_dropdown,
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # === RECORDING SECTION ===
                ft.Text("RECORDING", size=16, weight=ft.FontWeight.BOLD, color=theme.ACCENT),
                ft.Divider(height=2, color=theme.ACCENT),
                
                # Recording Settings
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Recording Options", ft.Icons.VIDEOCAM),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Row([
                            ft.Column([self.browser_dropdown], expand=True),
                            ft.Column([self.viewport_dropdown], expand=True),
                        ], spacing=16),
                        self.add_screenshots,
                        ft.Row([
                            self.add_retry,
                            ft.Column([self.retry_count_field], width=100),
                        ], spacing=16),
                        self.cleanup_code,
                    ], spacing=12)
                ),
                
                ft.Container(height=16),
                
                # === TESTING SECTION ===
                ft.Text("TESTING", size=16, weight=ft.FontWeight.BOLD, color=theme.ACCENT),
                ft.Divider(height=2, color=theme.ACCENT),
                
                # Test Execution Settings
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Test Execution", ft.Icons.TUNE),
                        ft.Text(
                            "Configure timeout and retry behavior for test execution.",
                            color=theme.TEXT_SECONDARY,
                            size=12
                        ),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Row([
                            ft.Column([self.test_timeout_field], expand=True),
                            ft.Column([self.test_retry_count_field], expand=True),
                        ], spacing=12),
                    ], spacing=12)
                ),
                
                ft.Container(height=8),
                
                # Screenshot Settings
                theme.styled_card(
                    ft.Column([
                        theme.section_title("Screenshot Settings", ft.Icons.CAMERA),
                        ft.Text(
                            "Specify where failure screenshots should be saved.",
                            color=theme.TEXT_SECONDARY,
                            size=12
                        ),
                        ft.Divider(height=1, color=theme.DIVIDER),
                        ft.Row([
                            ft.Column([self.screenshot_dir_field], expand=True),
                            self.browse_screenshot_dir_btn,
                        ], spacing=12),
                        ft.Text(
                            "Leave empty to save screenshots in the same directory as test files.",
                            color=theme.TEXT_SECONDARY,
                            size=11,
                            italic=True,
                        ),
                    ], spacing=12)
                ),
                
                ft.Container(height=24),
                
                # Save Button
                ft.Row([
                    self.save_settings_btn,
                ], alignment=ft.MainAxisAlignment.END),
                
                ft.Container(height=24),
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        )
        
        # Store reference to DevOps details container
        self.devops_details_container = content.controls[4].content.controls[-1]
        
        return ft.Container(
            content=content,
            padding=24,
            expand=True,
        )
    
    def _load_config_to_ui(self):
        """Load saved configuration into UI fields."""
        config = self.config
        
        # D365
        self.d365_url_field.value = config.d365.environment_url
        self.d365_auto_login.value = config.d365.auto_login
        
        # Key Vault
        self.kv_url_field.value = config.keyvault.vault_url
        self.kv_tenant_field.value = config.keyvault.tenant_id
        self.kv_client_id_field.value = config.keyvault.client_id
        self.kv_client_secret_field.value = config.keyvault.client_secret
        self.kv_fo_username_secret.value = config.keyvault.fo_username_secret
        self.kv_fo_password_secret.value = config.keyvault.fo_password_secret
        self.kv_fo_totp_secret.value = config.keyvault.fo_totp_secret
        self.kv_devops_pat_secret.value = config.keyvault.devops_pat_secret
        
        # DevOps
        self.devops_enabled.value = config.devops.enabled
        self.devops_org_field.value = config.devops.organization
        self.devops_project_field.value = config.devops.project
        self.devops_repo_field.value = config.devops.repository
        self.devops_folder_field.value = config.devops.target_folder
        
        if config.devops.branch:
            self.devops_branch_dropdown.options = [
                ft.dropdown.Option(key=config.devops.branch, text=config.devops.branch)
            ]
            self.devops_branch_dropdown.value = config.devops.branch
        
        # Toggle DevOps details visibility
        self.devops_details_container.visible = config.devops.enabled
        
        # Local Storage
        self.output_dir_field.value = config.local_storage.output_directory
        
        # Destination
        self.destination_dropdown.value = config.save_destination.value
        
        # Recording
        self.browser_dropdown.value = config.recording.browser.value
        self.viewport_dropdown.value = config.recording.viewport_preset.value
        self.add_screenshots.value = config.recording.add_screenshots
        self.add_retry.value = config.recording.add_retry
        self.retry_count_field.value = str(config.recording.retry_count)
        self.cleanup_code.value = config.recording.cleanup_code
        
        # Test Setup
        self.test_timeout_field.value = str(config.recording.test_timeout // 1000)  # Convert ms to seconds
        self.test_retry_count_field.value = str(config.recording.retry_count)
        self.screenshot_dir_field.value = getattr(config.recording, 'screenshot_output_dir', '')
        
        # Update summary
        self._update_config_summary()
        
        self.page.update()
    
    def _on_devops_toggle(self, e):
        """Handle DevOps enabled toggle."""
        self.devops_details_container.visible = e.control.value
        self.page.update()
    
    def _on_browse_folder(self, e):
        """Handle browse folder button click."""
        import platform
        import subprocess
        
        # On macOS, use AppleScript to show folder picker (avoids sandbox issues)
        if platform.system() == "Darwin":
            try:
                # Use Finder directly instead of System Events (more reliable)
                script = '''
                    tell application "Finder"
                        activate
                        set theFolder to choose folder with prompt "Select Output Directory for Tests"
                        return POSIX path of theFolder
                    end tell
                '''
                result = subprocess.run(
                    ['osascript', '-e', script],
                    capture_output=True, text=True, timeout=120
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    folder_path = result.stdout.strip()
                    self.output_dir_field.value = folder_path
                    self.page.update()
                    return
                elif result.returncode == -1 or "cancel" in result.stderr.lower():
                    # User cancelled - that's OK
                    return
            except subprocess.TimeoutExpired:
                logger.warning("Folder picker timed out - using manual entry")
                self._show_snackbar(
                    "Folder picker timed out. Please type the path manually.",
                    "warning"
                )
                return
            except Exception as ex:
                logger.warning(f"AppleScript folder picker failed: {ex}")
        
        # Try the standard Flet file picker
        try:
            self.folder_picker.get_directory_path(
                dialog_title="Select Output Directory"
            )
        except Exception as ex:
            # Fallback: show a dialog to enter path manually
            self._show_snackbar(
                "Folder picker not available. Please enter the path manually in the field.",
                "warning"
            )
    
    def _on_folder_picked(self, e: ft.FilePickerResultEvent):
        """Handle folder picker result."""
        if e.path:
            self.output_dir_field.value = e.path
            self.page.update()
    
    def _on_browse_screenshot_dir(self, e):
        """Handle browse screenshot directory button click."""
        import platform
        import subprocess
        
        # On macOS, use AppleScript to show folder picker
        if platform.system() == "Darwin":
            try:
                script = '''
                    tell application "Finder"
                        activate
                        set theFolder to choose folder with prompt "Select Screenshot Output Directory"
                        return POSIX path of theFolder
                    end tell
                '''
                result = subprocess.run(
                    ['osascript', '-e', script],
                    capture_output=True, text=True, timeout=120
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    folder_path = result.stdout.strip()
                    self.screenshot_dir_field.value = folder_path
                    self.page.update()
                    return
                elif result.returncode == -1 or "cancel" in result.stderr.lower():
                    return
            except subprocess.TimeoutExpired:
                logger.warning("Folder picker timed out")
                self._show_snackbar("Folder picker timed out. Please type the path manually.", "warning")
                return
            except Exception as ex:
                logger.warning(f"AppleScript folder picker failed: {ex}")
        
        # Fallback
        self._show_snackbar("Please enter the path manually in the field.", "warning")
    
    def _on_test_keyvault(self, e):
        """Test Key Vault connection."""
        self.keyvault_status.value = "Testing..."
        self.keyvault_status.color = theme.TEXT_SECONDARY
        self.page.update()
        
        def test():
            try:
                client = KeyVaultClient(
                    vault_url=self.kv_url_field.value,
                    tenant_id=self.kv_tenant_field.value,
                    client_id=self.kv_client_id_field.value,
                    client_secret=self.kv_client_secret_field.value,
                )
                success, message = client.test_connection()
                
                def update():
                    self.keyvault_status.value = message
                    self.keyvault_status.color = theme.SUCCESS if success else theme.ERROR
                    self.page.update()
                
                update()
                
            except Exception as ex:
                def update():
                    self.keyvault_status.value = str(ex)
                    self.keyvault_status.color = theme.ERROR
                    self.page.update()
                
                update()
        
        threading.Thread(target=test, daemon=True).start()
    
    def _on_test_devops(self, e):
        """Test DevOps connection."""
        self.devops_status.value = "Testing..."
        self.devops_status.color = theme.TEXT_SECONDARY
        self.page.update()
        
        def test():
            try:
                # Get PAT - try Key Vault first
                pat = None
                if self.config_manager.is_keyvault_configured():
                    creds_manager = CredentialsManager.from_config(self.config)
                    creds = creds_manager.get_devops_credentials(
                        pat_secret=self.kv_devops_pat_secret.value or "devops-pat"
                    )
                    if creds:
                        pat = creds.pat
                
                if not pat:
                    def update():
                        self.devops_status.value = "No PAT available. Configure Key Vault first."
                        self.devops_status.color = theme.ERROR
                        self.page.update()
                    update()
                    return
                
                client = AzureDevOpsClient(
                    organization=self.devops_org_field.value,
                    project=self.devops_project_field.value,
                    repository=self.devops_repo_field.value,
                    pat=pat,
                )
                success, message = client.test_connection()
                
                def update():
                    self.devops_status.value = message
                    self.devops_status.color = theme.SUCCESS if success else theme.ERROR
                    self.page.update()
                
                update()
                
            except Exception as ex:
                def update():
                    self.devops_status.value = str(ex)
                    self.devops_status.color = theme.ERROR
                    self.page.update()
                
                update()
        
        threading.Thread(target=test, daemon=True).start()
    
    def _on_fetch_branches(self, e):
        """Fetch branches from DevOps repository."""
        self.devops_status.value = "Fetching branches..."
        self.devops_status.color = theme.TEXT_SECONDARY
        self.page.update()
        
        def fetch():
            try:
                # Get PAT
                pat = None
                if self.config_manager.is_keyvault_configured():
                    creds_manager = CredentialsManager.from_config(self.config)
                    creds = creds_manager.get_devops_credentials(
                        pat_secret=self.kv_devops_pat_secret.value or "devops-pat"
                    )
                    if creds:
                        pat = creds.pat
                
                if not pat:
                    def update():
                        self.devops_status.value = "No PAT available. Configure Key Vault first."
                        self.devops_status.color = theme.ERROR
                        self.page.update()
                    update()
                    return
                
                client = AzureDevOpsClient(
                    organization=self.devops_org_field.value,
                    project=self.devops_project_field.value,
                    repository=self.devops_repo_field.value,
                    pat=pat,
                )
                branches = client.get_branch_names()
                
                def update():
                    if branches:
                        self.devops_branch_dropdown.options = [
                            ft.dropdown.Option(key=b, text=b) for b in branches
                        ]
                        if not self.devops_branch_dropdown.value and branches:
                            self.devops_branch_dropdown.value = branches[0]
                        self.devops_status.value = f"Found {len(branches)} branches"
                        self.devops_status.color = theme.SUCCESS
                    else:
                        self.devops_status.value = "No branches found"
                        self.devops_status.color = theme.WARNING
                    self.page.update()
                
                update()
                
            except Exception as ex:
                def update():
                    self.devops_status.value = str(ex)
                    self.devops_status.color = theme.ERROR
                    self.page.update()
                
                update()
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _on_save_settings(self, e):
        """Save all settings."""
        try:
            # Build config update dict
            update_data = {
                "d365": {
                    "environment_url": self.d365_url_field.value,
                    "auto_login": self.d365_auto_login.value,
                },
                "keyvault": {
                    "vault_url": self.kv_url_field.value,
                    "tenant_id": self.kv_tenant_field.value,
                    "client_id": self.kv_client_id_field.value,
                    "client_secret": self.kv_client_secret_field.value,
                    "fo_username_secret": self.kv_fo_username_secret.value,
                    "fo_password_secret": self.kv_fo_password_secret.value,
                    "fo_totp_secret": self.kv_fo_totp_secret.value,
                    "devops_pat_secret": self.kv_devops_pat_secret.value,
                },
                "devops": {
                    "enabled": self.devops_enabled.value,
                    "organization": self.devops_org_field.value,
                    "project": self.devops_project_field.value,
                    "repository": self.devops_repo_field.value,
                    "branch": self.devops_branch_dropdown.value or "main",
                    "target_folder": self.devops_folder_field.value,
                },
                "local_storage": {
                    "output_directory": self.output_dir_field.value,
                },
                "save_destination": self.destination_dropdown.value,
                "recording": {
                    "browser": self.browser_dropdown.value,
                    "viewport_preset": self.viewport_dropdown.value,
                    "add_screenshots": self.add_screenshots.value,
                    "add_retry": self.add_retry.value,
                    "retry_count": int(self.retry_count_field.value or "2"),
                    "cleanup_code": self.cleanup_code.value,
                    "test_timeout": int(self.test_timeout_field.value or "15") * 1000,  # Convert to ms
                    "screenshot_output_dir": self.screenshot_dir_field.value,
                },
            }
            
            self.config_manager.update(**update_data)
            self._update_config_summary()
            
            # Reinitialize managers with new settings (especially credentials_manager)
            print("[DEBUG] Reinitializing managers after settings save...")
            self._initialize_managers()
            print(f"[DEBUG] credentials_manager after reinit: {self.credentials_manager is not None}")
            
            self._show_snackbar("Settings saved successfully!", "success")
            
        except Exception as ex:
            self._show_snackbar(f"Failed to save settings: {ex}", "error")
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _initialize_managers(self):
        """Initialize managers based on current config."""
        config = self.config
        
        # Credentials manager
        if self.config_manager.is_keyvault_configured():
            self.credentials_manager = CredentialsManager.from_config(config)
        else:
            self.credentials_manager = None
        
        # DevOps manager
        if not self.skip_devops and config.devops.enabled:
            self.devops_manager = DevOpsManager(config, self.credentials_manager)
        else:
            self.devops_manager = None
        
        # Get D365 credentials for auto-login
        d365_creds = None
        if self.credentials_manager:
            try:
                from .recorder import D365Credentials
                kv_config = config.keyvault
                creds = self.credentials_manager.get_d365_credentials(
                    username_secret=kv_config.fo_username_secret,
                    password_secret=kv_config.fo_password_secret
                )
                if creds:
                    # Try to get TOTP secret if configured
                    totp_secret = ""
                    if kv_config.fo_totp_secret:
                        try:
                            totp_secret = self.credentials_manager.get_secret(kv_config.fo_totp_secret) or ""
                            if totp_secret:
                                logger.info("TOTP secret loaded for auto MFA")
                        except Exception as te:
                            logger.warning(f"Could not load TOTP secret: {te}")
                    
                    d365_creds = D365Credentials(
                        username=creds.username,
                        password=creds.password,
                        totp_secret=totp_secret
                    )
                    logger.info("D365 credentials loaded for auto-login")
            except Exception as e:
                logger.warning(f"Could not load D365 credentials: {e}")
        
        # Recorder (with optional credentials for auto-login)
        self.recorder = PlaywrightRecorder(config, credentials=d365_creds)
        
        # File manager
        self.file_manager = TestFileManager(config, self.devops_manager)
    
    def _switch_to_tab(self, index: int):
        """Switch to a specific tab."""
        self.tabs.selected_index = index
        self.page.update()
    
    def _show_snackbar(self, message: str, type: str = "info"):
        """Show a snackbar message."""
        colors = {
            "success": theme.SUCCESS,
            "error": theme.ERROR,
            "warning": theme.WARNING,
            "info": theme.INFO,
        }
        
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=colors.get(type, theme.INFO),
            duration=4000,
        )
        self.page.snack_bar.open = True
        self.page.update()


def main(page: ft.Page, skip_devops: bool = False):
    """Main entry point for the application."""
    app = PlaywrightUIApp(page, skip_devops=skip_devops)


def run_app(skip_devops: bool = False):
    """Run the application."""
    ft.app(target=lambda page: main(page, skip_devops=skip_devops))


if __name__ == "__main__":
    run_app()
