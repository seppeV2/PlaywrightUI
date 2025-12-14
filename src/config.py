"""
Configuration management module for Playwright UI.
Handles persistent storage and validation of application settings.
"""

import json
import os
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class SaveDestination(str, Enum):
    """Where to save recorded tests."""
    LOCAL_ONLY = "local"
    DEVOPS_ONLY = "devops"
    LOCAL_AND_DEVOPS = "local_and_devops"


class BrowserType(str, Enum):
    """Supported browser types for recording."""
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class ViewportPreset(str, Enum):
    """Common viewport presets."""
    MATCH_WINDOW = "match_window"
    DESKTOP_1920 = "1920x1080"
    DESKTOP_1366 = "1366x768"
    DESKTOP_1280 = "1280x720"
    LAPTOP = "1440x900"
    TABLET = "768x1024"
    CUSTOM = "custom"


class KeyVaultSettings(BaseModel):
    """Azure Key Vault configuration."""
    vault_url: str = Field(default="", description="Key Vault URL (e.g., https://myvault.vault.azure.net)")
    tenant_id: str = Field(default="", description="Azure AD Tenant ID")
    client_id: str = Field(default="", description="Azure AD Application (Client) ID")
    client_secret: str = Field(default="", description="Azure AD Application Client Secret")
    
    # Secret names in Key Vault
    fo_username_secret: str = Field(default="fo-username", description="Secret name for F&O username")
    fo_password_secret: str = Field(default="fo-password", description="Secret name for F&O password")
    fo_totp_secret: str = Field(default="fo-totp-secret", description="Secret name for TOTP authenticator secret (for auto MFA)")
    devops_pat_secret: str = Field(default="devops-pat", description="Secret name for Azure DevOps PAT")


class DevOpsSettings(BaseModel):
    """Azure DevOps Git repository configuration."""
    enabled: bool = Field(default=False, description="Enable Azure DevOps integration")
    organization: str = Field(default="", description="Azure DevOps organization name")
    project: str = Field(default="", description="Azure DevOps project name")
    repository: str = Field(default="", description="Git repository name")
    branch: str = Field(default="main", description="Target branch for commits")
    target_folder: str = Field(default="/tests/recorded", description="Folder path in repo for test files")
    
    # For application-based auth (not user-based)
    use_keyvault_pat: bool = Field(default=True, description="Use PAT from Key Vault")
    pat: str = Field(default="", description="Personal Access Token (if not using Key Vault)")


class D365Settings(BaseModel):
    """Dynamics 365 Finance & Operations settings."""
    environment_url: str = Field(default="", description="D365 F&O environment URL")
    auto_login: bool = Field(default=True, description="Automatically log in using Key Vault credentials")
    wait_for_load_timeout: int = Field(default=60000, description="Timeout (ms) to wait for page load")


class RecordingSettings(BaseModel):
    """Playwright recording settings."""
    browser: BrowserType = Field(default=BrowserType.CHROMIUM, description="Browser to use")
    viewport_preset: ViewportPreset = Field(default=ViewportPreset.MATCH_WINDOW, description="Viewport preset")
    custom_width: int = Field(default=1920, description="Custom viewport width")
    custom_height: int = Field(default=1080, description="Custom viewport height")
    headless: bool = Field(default=False, description="Run in headless mode (not recommended for recording)")
    slow_mo: int = Field(default=0, description="Slow down actions by ms")
    
    # Test generation options
    add_screenshots: bool = Field(default=True, description="Add screenshot on failure")
    screenshot_output_dir: str = Field(default="", description="Directory for failure screenshots")
    add_retry: bool = Field(default=True, description="Add retry configuration")
    retry_count: int = Field(default=2, description="Number of retries")
    test_timeout: int = Field(default=15000, description="Test timeout in ms")
    cleanup_code: bool = Field(default=True, description="Clean up recorded code (remove boilerplate)")


class LocalStorageSettings(BaseModel):
    """Local storage settings."""
    output_directory: str = Field(default="", description="Directory to save recorded tests")
    
    @field_validator('output_directory')
    @classmethod
    def validate_directory(cls, v: str) -> str:
        if v and not os.path.isabs(v):
            # Convert to absolute path
            v = str(Path(v).resolve())
        return v


class AppConfig(BaseModel):
    """Main application configuration."""
    keyvault: KeyVaultSettings = Field(default_factory=KeyVaultSettings)
    devops: DevOpsSettings = Field(default_factory=DevOpsSettings)
    d365: D365Settings = Field(default_factory=D365Settings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    local_storage: LocalStorageSettings = Field(default_factory=LocalStorageSettings)
    save_destination: SaveDestination = Field(default=SaveDestination.LOCAL_ONLY)
    
    # Available branches (populated dynamically)
    available_branches: List[str] = Field(default_factory=list)


class ConfigManager:
    """Manages application configuration persistence."""
    
    CONFIG_FILE_NAME = "playwright_ui_config.json"
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Directory to store config file. Defaults to user's home directory.
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            self.config_dir = Path.home() / ".playwright_ui"
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / self.CONFIG_FILE_NAME
        self._config: Optional[AppConfig] = None
    
    @property
    def config(self) -> AppConfig:
        """Get current configuration, loading from disk if needed."""
        if self._config is None:
            self._config = self.load()
        return self._config
    
    def load(self) -> AppConfig:
        """Load configuration from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return AppConfig(**data)
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Could not load config: {e}. Using defaults.")
                return AppConfig()
        return AppConfig()
    
    def save(self, config: Optional[AppConfig] = None) -> None:
        """Save configuration to disk."""
        if config:
            self._config = config
        
        if self._config:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config.model_dump(), f, indent=2)
    
    def update(self, **kwargs) -> AppConfig:
        """Update configuration with new values."""
        current_data = self.config.model_dump()
        
        # Deep update
        for key, value in kwargs.items():
            if key in current_data:
                if isinstance(value, dict) and isinstance(current_data[key], dict):
                    current_data[key].update(value)
                else:
                    current_data[key] = value
        
        self._config = AppConfig(**current_data)
        self.save()
        return self._config
    
    def reset(self) -> AppConfig:
        """Reset configuration to defaults."""
        self._config = AppConfig()
        self.save()
        return self._config
    
    def get_viewport_size(self, window_width: int = None, window_height: int = None) -> tuple[int, int]:
        """Get the viewport size based on current settings."""
        preset = self.config.recording.viewport_preset
        
        if preset == ViewportPreset.MATCH_WINDOW:
            # Use provided window dimensions or defaults
            return (window_width or 1920, window_height or 1080)
        
        if preset == ViewportPreset.CUSTOM:
            return (self.config.recording.custom_width, self.config.recording.custom_height)
        
        # Parse preset string "WIDTHxHEIGHT"
        width, height = preset.value.split('x')
        return (int(width), int(height))
    
    def is_keyvault_configured(self) -> bool:
        """Check if Key Vault settings are configured."""
        kv = self.config.keyvault
        return all([kv.vault_url, kv.tenant_id, kv.client_id, kv.client_secret])
    
    def is_devops_configured(self) -> bool:
        """Check if Azure DevOps settings are configured."""
        devops = self.config.devops
        return all([devops.organization, devops.project, devops.repository])
    
    def is_d365_configured(self) -> bool:
        """Check if D365 settings are configured."""
        return bool(self.config.d365.environment_url)
    
    def get_config_status(self) -> dict:
        """Get configuration status summary."""
        return {
            "keyvault_configured": self.is_keyvault_configured(),
            "devops_configured": self.is_devops_configured(),
            "d365_configured": self.is_d365_configured(),
            "output_directory_set": bool(self.config.local_storage.output_directory),
            "save_destination": self.config.save_destination.value
        }


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> AppConfig:
    """Shortcut to get current configuration."""
    return get_config_manager().config
