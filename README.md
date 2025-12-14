# Playwright UI - D365 F&O Test Recorder

A user-friendly interface for recording Playwright tests for Dynamics 365 Finance & Operations, with Azure Key Vault integration and Azure DevOps Git push capabilities.

**By 9altitudes**

![9altitudes](https://img.shields.io/badge/9altitudes-Digital%20Transformation-1e3a5f)
![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Flet](https://img.shields.io/badge/Flet-UI%20Framework-orange)
![Playwright](https://img.shields.io/badge/Playwright-Test%20Recording-green)

## Features

- 🎬 **Record Playwright Tests** - Easy-to-use interface for recording browser tests
- 🔐 **Azure Key Vault Integration** - Secure credential management for D365 F&O login
- 📤 **Azure DevOps Integration** - Push recorded tests directly to Git repositories
- 🔧 **Post-Processing** - Extract and modify input values after recording
- 📁 **Local Storage** - Save tests locally with proper naming conventions
- 🎨 **9altitudes Themed** - Professional UI following 9altitudes brand guidelines

## Installation

### Prerequisites

- Python 3.9 or higher
- Playwright browsers installed

### Setup

1. **Clone or download this project**

2. **Create a virtual environment (recommended)**
   ```bash
   cd playwrightUI
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers**
   ```bash
   playwright install
   ```

## Usage

### Running the Application

```bash
# Full mode (with DevOps integration)
python main.py

# Test mode (without DevOps - for local testing)
python main.py --skip-devops

# Debug mode
python main.py --debug
```

### Configuration

On first run, go to the **Settings** tab to configure:

#### 1. D365 Finance & Operations
- **Environment URL**: Your D365 F&O environment URL (e.g., `https://your-env.dynamics.com`)
- **Auto-login**: Enable to automatically log in using Key Vault credentials

#### 2. Azure Key Vault
Configure your Azure AD App Registration to access Key Vault:
- **Key Vault URL**: `https://your-vault.vault.azure.net`
- **Tenant ID**: Your Azure AD tenant ID
- **Client ID**: App registration client ID
- **Client Secret**: App registration client secret

**Secret Names** (configure the names of secrets in your Key Vault):
- F&O Username Secret: Name of the secret containing D365 username
- F&O Password Secret: Name of the secret containing D365 password
- DevOps PAT Secret: Name of the secret containing Azure DevOps PAT

#### 3. Azure DevOps (Optional)
- **Organization**: Your Azure DevOps organization name
- **Project**: Project name
- **Repository**: Git repository name
- **Branch**: Target branch for commits (fetched dynamically)
- **Target Folder**: Folder path in repo (e.g., `/tests/recorded`)

#### 4. Output Settings
- **Output Directory**: Local folder for saving recorded tests
- **Save Destination**: Choose where to save (Local, DevOps, or both)

### Recording a Test

1. Go to the **Record Test** tab
2. Enter a **Test Name** (e.g., "Create Sales Order")
3. Enter a **Description** of what the test covers
4. Click **Start Recording**
5. A browser window will open - perform your test actions
6. Close the browser when done
7. Review detected inputs in the **Post-Process** tab

### Post-Processing

After recording, the **Post-Process** tab shows all detected input values:

- **View all inputs** used during recording
- **Modify values** - Change hardcoded values
- **Create variables** - Convert values to variables for parameterized tests
- **Use suggested names** - Auto-generate meaningful variable names

### Generated Test Structure

Recorded tests include:
- Test metadata (name, description, timestamp)
- D365-specific wait configurations
- Screenshot on failure (configurable)
- Retry configuration (configurable)
- Variables section for easy parameterization

## Azure Setup Guide

### 1. Create Azure AD App Registration

1. Go to Azure Portal → Microsoft Entra ID → App registrations
2. Click **New registration**
3. Enter a name (e.g., "Playwright UI")
4. Select "Accounts in this organizational directory only"
5. Click **Register**
6. Note the **Application (client) ID** and **Directory (tenant) ID**

### 2. Create Client Secret

1. In the app registration, go to **Certificates & secrets**
2. Click **New client secret**
3. Add a description and expiry
4. **Copy the secret value immediately** (shown only once)

### 3. Grant Key Vault Access

1. Go to your Key Vault → **Access control (IAM)**
2. Click **Add role assignment**
3. Select **Key Vault Secrets User** role
4. Assign to your app registration

### 4. Add Secrets to Key Vault

Add these secrets to your Key Vault:
- `fo-username`: D365 F&O login username
- `fo-password`: D365 F&O login password
- `devops-pat`: Azure DevOps Personal Access Token

### 5. Create Azure DevOps PAT

1. Go to Azure DevOps → User Settings → Personal access tokens
2. Click **New Token**
3. Grant **Code (Read & Write)** permission
4. Copy the token and store it in Key Vault

## Project Structure

```
playwrightUI/
├── main.py                 # Entry point
├── pyproject.toml          # Project config & dependencies (for flet build)
├── requirements.txt        # Python dependencies (for pip install)
├── README.md              # This file
├── assets/
│   └── icon.svg           # Application icon
└── src/
    ├── __init__.py
    ├── app.py             # Main Flet application
    ├── config.py          # Configuration management
    ├── theme.py           # 9altitudes theme styling
    ├── keyvault.py        # Azure Key Vault integration
    ├── devops.py          # Azure DevOps Git integration
    ├── recorder.py        # Playwright recording wrapper
    └── postprocess.py     # Test post-processing
```

## Building for Distribution

### Prerequisites for Building

- **macOS**: Xcode 15+, CocoaPods, Rosetta 2 (on Apple Silicon)
- **Windows**: Visual Studio Build Tools
- **Linux**: Required system packages

### Build Commands

```bash
# Install Flet CLI
pip install flet

# Build for macOS (run on macOS only)
flet build macos

# Build for Windows (run on Windows)
flet build windows

# Build for Linux (run on Linux)
flet build linux

# Build for web (static site)
flet build web
```

### Build Output

Built applications are placed in `build/<platform>/`:
- **macOS**: `build/macos/Playwright UI.app`
- **Windows**: `build/windows/playwright-ui.exe`
- **Linux**: `build/linux/playwright-ui`

### Development Mode with Hot Reload

```bash
flet run main.py
```

## Configuration File

Settings are stored in `~/.playwright_ui/playwright_ui_config.json`

## Troubleshooting

### "Playwright not found"
```bash
pip install playwright
playwright install
```

### "Azure SDK not installed"
```bash
pip install azure-identity azure-keyvault-secrets
```

### Key Vault connection fails
- Verify the app registration has Key Vault Secrets User role
- Check that tenant ID, client ID, and secret are correct
- Ensure the Key Vault URL is correct

### DevOps push fails
- Verify the PAT has Code (Read & Write) permissions
- Check organization, project, and repository names
- Ensure the target branch exists

## License

Internal use - 9altitudes

## Support

For issues and questions, contact the 9altitudes development team.
