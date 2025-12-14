"""
Azure DevOps Git integration module.
Handles pushing test files to Azure DevOps Git repositories.
"""

import base64
import logging
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Branch:
    """Git branch information."""
    name: str
    object_id: str
    
    @property
    def short_name(self) -> str:
        """Get branch name without refs/heads/ prefix."""
        return self.name.replace("refs/heads/", "")


@dataclass
class PushResult:
    """Result of a push operation."""
    success: bool
    message: str
    commit_id: Optional[str] = None
    push_id: Optional[int] = None


class AzureDevOpsClient:
    """
    Azure DevOps Git REST API client.
    Uses PAT (Personal Access Token) for authentication.
    """
    
    API_VERSION = "7.1"
    
    def __init__(
        self,
        organization: str,
        project: str,
        repository: str,
        pat: str
    ):
        """
        Initialize Azure DevOps client.
        
        Args:
            organization: Azure DevOps organization name
            project: Project name
            repository: Repository name
            pat: Personal Access Token
        """
        self.organization = organization
        self.project = project
        self.repository = repository
        
        # Build base URL
        self.base_url = (
            f"https://dev.azure.com/{organization}/{project}"
            f"/_apis/git/repositories/{repository}"
        )
        
        # PAT authentication - Base64 encode ":PAT"
        auth_string = f":{pat}"
        auth_bytes = base64.b64encode(auth_string.encode()).decode()
        
        self.headers = {
            "Authorization": f"Basic {auth_bytes}",
            "Content-Type": "application/json"
        }
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> requests.Response:
        """Make an API request."""
        url = f"{self.base_url}/{endpoint}"
        
        if params is None:
            params = {}
        params["api-version"] = self.API_VERSION
        
        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            params=params,
            json=json_data,
            timeout=30
        )
        
        return response
    
    def test_connection(self) -> tuple[bool, str]:
        """
        Test the connection to Azure DevOps.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            response = self._make_request("GET", "refs", params={"filter": "heads/"})
            
            if response.status_code == 200:
                return True, "Connection successful"
            elif response.status_code == 401:
                return False, "Authentication failed - check PAT"
            elif response.status_code == 404:
                return False, "Repository not found - check organization, project, and repository names"
            else:
                return False, f"Connection failed: HTTP {response.status_code}"
                
        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"
    
    def get_branches(self) -> List[Branch]:
        """
        Get all branches in the repository.
        
        Returns:
            List of Branch objects
        """
        try:
            response = self._make_request("GET", "refs", params={"filter": "heads/"})
            response.raise_for_status()
            
            data = response.json()
            branches = []
            
            for ref in data.get("value", []):
                branches.append(Branch(
                    name=ref["name"],
                    object_id=ref["objectId"]
                ))
            
            return branches
            
        except Exception as e:
            logger.error(f"Failed to get branches: {e}")
            return []
    
    def get_branch_names(self) -> List[str]:
        """
        Get list of branch names (short names without refs/heads/).
        
        Returns:
            List of branch names
        """
        branches = self.get_branches()
        return [b.short_name for b in branches]
    
    def get_branch_object_id(self, branch_name: str) -> Optional[str]:
        """
        Get the latest commit ID for a branch.
        
        Args:
            branch_name: Branch name (with or without refs/heads/ prefix)
            
        Returns:
            Object ID (commit SHA) or None
        """
        if not branch_name.startswith("refs/heads/"):
            branch_name = f"refs/heads/{branch_name}"
        
        branches = self.get_branches()
        for branch in branches:
            if branch.name == branch_name:
                return branch.object_id
        
        return None
    
    def file_exists(self, branch: str, file_path: str) -> bool:
        """
        Check if a file exists in the repository.
        
        Args:
            branch: Branch name
            file_path: Path to file in repository
            
        Returns:
            True if file exists
        """
        try:
            # Ensure path starts with /
            if not file_path.startswith("/"):
                file_path = f"/{file_path}"
            
            response = self._make_request(
                "GET",
                f"items",
                params={
                    "path": file_path,
                    "versionDescriptor.version": branch,
                    "versionDescriptor.versionType": "branch"
                }
            )
            
            return response.status_code == 200
            
        except Exception:
            return False
    
    def push_file(
        self,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str,
        author_name: str = "Playwright UI",
        author_email: str = "playwright-ui@9altitudes.com"
    ) -> PushResult:
        """
        Push a single file to the repository.
        
        Args:
            branch: Target branch name
            file_path: Path in repository (e.g., /tests/recorded/test_example.py)
            content: File content
            commit_message: Commit message
            author_name: Git author name
            author_email: Git author email
            
        Returns:
            PushResult object
        """
        try:
            # Get current branch head
            object_id = self.get_branch_object_id(branch)
            if not object_id:
                return PushResult(
                    success=False,
                    message=f"Branch '{branch}' not found"
                )
            
            # Ensure path starts with /
            if not file_path.startswith("/"):
                file_path = f"/{file_path}"
            
            # Determine change type
            change_type = "edit" if self.file_exists(branch, file_path) else "add"
            
            # Build push payload
            payload = {
                "refUpdates": [
                    {
                        "name": f"refs/heads/{branch}",
                        "oldObjectId": object_id
                    }
                ],
                "commits": [
                    {
                        "comment": commit_message,
                        "author": {
                            "name": author_name,
                            "email": author_email
                        },
                        "changes": [
                            {
                                "changeType": change_type,
                                "item": {
                                    "path": file_path
                                },
                                "newContent": {
                                    "content": content,
                                    "contentType": "rawtext"
                                }
                            }
                        ]
                    }
                ]
            }
            
            response = self._make_request("POST", "pushes", json_data=payload)
            
            if response.status_code in (200, 201):
                data = response.json()
                commits = data.get("commits", [])
                commit_id = commits[0]["commitId"] if commits else None
                
                return PushResult(
                    success=True,
                    message="File pushed successfully",
                    commit_id=commit_id,
                    push_id=data.get("pushId")
                )
            else:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", response.text)
                except Exception:
                    pass
                
                return PushResult(
                    success=False,
                    message=f"Push failed: {error_msg}"
                )
                
        except Exception as e:
            logger.error(f"Push failed: {e}")
            return PushResult(
                success=False,
                message=f"Push failed: {str(e)}"
            )
    
    def push_multiple_files(
        self,
        branch: str,
        files: List[Dict[str, str]],
        commit_message: str,
        author_name: str = "Playwright UI",
        author_email: str = "playwright-ui@9altitudes.com"
    ) -> PushResult:
        """
        Push multiple files in a single commit.
        
        Args:
            branch: Target branch name
            files: List of dicts with 'path' and 'content' keys
            commit_message: Commit message
            author_name: Git author name
            author_email: Git author email
            
        Returns:
            PushResult object
        """
        try:
            # Get current branch head
            object_id = self.get_branch_object_id(branch)
            if not object_id:
                return PushResult(
                    success=False,
                    message=f"Branch '{branch}' not found"
                )
            
            # Build changes list
            changes = []
            for file_info in files:
                file_path = file_info["path"]
                if not file_path.startswith("/"):
                    file_path = f"/{file_path}"
                
                change_type = "edit" if self.file_exists(branch, file_path) else "add"
                
                changes.append({
                    "changeType": change_type,
                    "item": {"path": file_path},
                    "newContent": {
                        "content": file_info["content"],
                        "contentType": "rawtext"
                    }
                })
            
            # Build push payload
            payload = {
                "refUpdates": [
                    {
                        "name": f"refs/heads/{branch}",
                        "oldObjectId": object_id
                    }
                ],
                "commits": [
                    {
                        "comment": commit_message,
                        "author": {
                            "name": author_name,
                            "email": author_email
                        },
                        "changes": changes
                    }
                ]
            }
            
            response = self._make_request("POST", "pushes", json_data=payload)
            
            if response.status_code in (200, 201):
                data = response.json()
                commits = data.get("commits", [])
                commit_id = commits[0]["commitId"] if commits else None
                
                return PushResult(
                    success=True,
                    message=f"Pushed {len(files)} files successfully",
                    commit_id=commit_id,
                    push_id=data.get("pushId")
                )
            else:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", response.text)
                except Exception:
                    pass
                
                return PushResult(
                    success=False,
                    message=f"Push failed: {error_msg}"
                )
                
        except Exception as e:
            logger.error(f"Push failed: {e}")
            return PushResult(
                success=False,
                message=f"Push failed: {str(e)}"
            )


class DevOpsManager:
    """
    High-level manager for Azure DevOps operations.
    Integrates with credentials manager and configuration.
    """
    
    def __init__(self, config, credentials_manager=None):
        """
        Initialize DevOps manager.
        
        Args:
            config: AppConfig instance
            credentials_manager: Optional CredentialsManager instance
        """
        from .config import AppConfig
        from .keyvault import CredentialsManager
        
        self.config = config
        self.credentials_manager = credentials_manager
        self._client: Optional[AzureDevOpsClient] = None
    
    def _get_pat(self) -> Optional[str]:
        """Get PAT from Key Vault or config."""
        devops_config = self.config.devops
        
        if devops_config.use_keyvault_pat and self.credentials_manager:
            creds = self.credentials_manager.get_devops_credentials(
                pat_secret=self.config.keyvault.devops_pat_secret
            )
            if creds:
                return creds.pat
        
        # Fall back to config PAT
        return devops_config.pat if devops_config.pat else None
    
    def _get_client(self) -> Optional[AzureDevOpsClient]:
        """Get or create the DevOps client."""
        if self._client is None:
            devops_config = self.config.devops
            
            if not devops_config.enabled:
                return None
            
            pat = self._get_pat()
            if not pat:
                logger.error("No PAT available for Azure DevOps")
                return None
            
            self._client = AzureDevOpsClient(
                organization=devops_config.organization,
                project=devops_config.project,
                repository=devops_config.repository,
                pat=pat
            )
        
        return self._client
    
    def is_available(self) -> bool:
        """Check if DevOps integration is available and configured."""
        return (
            self.config.devops.enabled and
            self.config.devops.organization and
            self.config.devops.project and
            self.config.devops.repository and
            self._get_pat() is not None
        )
    
    def test_connection(self) -> tuple[bool, str]:
        """Test connection to Azure DevOps."""
        client = self._get_client()
        if not client:
            return False, "Azure DevOps not configured"
        
        return client.test_connection()
    
    def fetch_branches(self) -> List[str]:
        """Fetch available branches from repository."""
        client = self._get_client()
        if not client:
            return []
        
        return client.get_branch_names()
    
    def push_test_file(
        self,
        file_name: str,
        content: str,
        description: str = ""
    ) -> PushResult:
        """
        Push a test file to the repository.
        
        Args:
            file_name: Name of the test file
            content: Test file content
            description: Test description for commit message
            
        Returns:
            PushResult object
        """
        client = self._get_client()
        if not client:
            return PushResult(
                success=False,
                message="Azure DevOps not configured"
            )
        
        # Build file path
        folder = self.config.devops.target_folder.rstrip("/")
        file_path = f"{folder}/{file_name}"
        
        # Build commit message
        commit_message = f"Add recorded test: {file_name}"
        if description:
            commit_message += f"\n\n{description}"
        
        return client.push_file(
            branch=self.config.devops.branch,
            file_path=file_path,
            content=content,
            commit_message=commit_message
        )
