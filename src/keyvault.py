"""
Azure Key Vault integration module.
Handles secure retrieval of credentials from Azure Key Vault.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class D365Credentials:
    """D365 F&O login credentials."""
    username: str
    password: str


@dataclass
class DevOpsCredentials:
    """Azure DevOps credentials."""
    pat: str


class KeyVaultClient:
    """
    Azure Key Vault client for retrieving secrets.
    Uses Azure AD Application (Service Principal) authentication.
    """
    
    def __init__(
        self,
        vault_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str
    ):
        """
        Initialize Key Vault client.
        
        Args:
            vault_url: Key Vault URL (e.g., https://myvault.vault.azure.net)
            tenant_id: Azure AD Tenant ID
            client_id: Azure AD Application (Client) ID
            client_secret: Azure AD Application Client Secret
        """
        self.vault_url = vault_url.rstrip('/')
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        
        self._client: Optional[Any] = None
        self._secrets_cache: Dict[str, str] = {}
    
    def _get_client(self):
        """Lazily initialize the Key Vault client."""
        if self._client is None:
            try:
                from azure.identity import ClientSecretCredential
                from azure.keyvault.secrets import SecretClient
                
                credential = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                
                self._client = SecretClient(
                    vault_url=self.vault_url,
                    credential=credential
                )
            except ImportError as e:
                raise ImportError(
                    "Azure SDK not installed. Run: pip install azure-identity azure-keyvault-secrets"
                ) from e
        
        return self._client
    
    def get_secret(self, secret_name: str, use_cache: bool = True) -> Optional[str]:
        """
        Retrieve a secret from Key Vault.
        
        Args:
            secret_name: Name of the secret to retrieve
            use_cache: Whether to use cached value if available
            
        Returns:
            Secret value or None if not found
        """
        if use_cache and secret_name in self._secrets_cache:
            return self._secrets_cache[secret_name]
        
        try:
            client = self._get_client()
            secret = client.get_secret(secret_name)
            value = secret.value
            
            if use_cache:
                self._secrets_cache[secret_name] = value
            
            logger.info(f"Successfully retrieved secret: {secret_name}")
            return value
            
        except Exception as e:
            logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
            return None
    
    def clear_cache(self) -> None:
        """Clear the secrets cache."""
        self._secrets_cache.clear()
    
    def test_connection(self, test_secret_name: str = None) -> tuple[bool, str]:
        """
        Test the Key Vault connection.
        
        Args:
            test_secret_name: Optional secret name to test with. If not provided,
                             tries to get any secret to verify connectivity.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            client = self._get_client()
            
            if test_secret_name:
                # Try to get a specific secret
                secret = client.get_secret(test_secret_name)
                return True, f"Connection successful (verified with '{test_secret_name}')"
            else:
                # Try listing secrets first
                try:
                    secrets = client.list_properties_of_secrets()
                    secret_list = list(secrets)
                    return True, f"Connection successful ({len(secret_list)} secrets found)"
                except Exception:
                    # List might fail due to permissions, try a common secret name
                    # This will fail with a "not found" error if connected but secret doesn't exist
                    # vs an auth error if not connected
                    try:
                        client.get_secret("fo-username")
                        return True, "Connection successful"
                    except Exception as inner_e:
                        error_str = str(inner_e).lower()
                        if "not found" in error_str or "secretnotfound" in error_str:
                            # Connected but secret doesn't exist - that's OK
                            return True, "Connection successful (no test secret found)"
                        raise
        except Exception as e:
            error_msg = str(e)
            if "403" in error_msg or "Forbidden" in error_msg:
                return False, "Access denied. Check Service Principal permissions on Key Vault."
            elif "401" in error_msg or "Unauthorized" in error_msg:
                return False, "Authentication failed. Check credentials."
            return False, f"Connection failed: {error_msg}"


class CredentialsManager:
    """
    Manages credentials retrieval from Key Vault.
    Provides typed access to specific credentials.
    """
    
    def __init__(self, keyvault_client: Optional[KeyVaultClient] = None):
        """
        Initialize credentials manager.
        
        Args:
            keyvault_client: Optional pre-configured Key Vault client
        """
        self._client = keyvault_client
        self._d365_creds: Optional[D365Credentials] = None
        self._devops_creds: Optional[DevOpsCredentials] = None
    
    @classmethod
    def from_config(cls, config) -> 'CredentialsManager':
        """
        Create credentials manager from application config.
        
        Args:
            config: AppConfig instance
            
        Returns:
            CredentialsManager instance
        """
        from .config import AppConfig
        
        if not isinstance(config, AppConfig):
            raise TypeError("Expected AppConfig instance")
        
        kv = config.keyvault
        
        if not all([kv.vault_url, kv.tenant_id, kv.client_id, kv.client_secret]):
            # Return manager without client (will use mock/manual credentials)
            return cls(keyvault_client=None)
        
        client = KeyVaultClient(
            vault_url=kv.vault_url,
            tenant_id=kv.tenant_id,
            client_id=kv.client_id,
            client_secret=kv.client_secret
        )
        
        return cls(keyvault_client=client)
    
    def has_keyvault(self) -> bool:
        """Check if Key Vault client is configured."""
        return self._client is not None
    
    def get_secret(self, secret_name: str) -> Optional[str]:
        """
        Retrieve a secret from Key Vault.
        
        Args:
            secret_name: Name of the secret to retrieve
            
        Returns:
            Secret value or None if not found/not configured
        """
        if not self._client:
            logger.warning("Key Vault not configured, cannot retrieve secret")
            return None
        
        return self._client.get_secret(secret_name)
    
    def get_d365_credentials(
        self,
        username_secret: str = "fo-username",
        password_secret: str = "fo-password"
    ) -> Optional[D365Credentials]:
        """
        Retrieve D365 F&O credentials from Key Vault.
        
        Args:
            username_secret: Secret name for username
            password_secret: Secret name for password
            
        Returns:
            D365Credentials or None if unavailable
        """
        if self._d365_creds:
            return self._d365_creds
        
        if not self._client:
            logger.warning("Key Vault not configured, cannot retrieve D365 credentials")
            return None
        
        username = self._client.get_secret(username_secret)
        password = self._client.get_secret(password_secret)
        
        if username and password:
            self._d365_creds = D365Credentials(username=username, password=password)
            return self._d365_creds
        
        logger.error("Failed to retrieve D365 credentials from Key Vault")
        return None
    
    def get_devops_credentials(
        self,
        pat_secret: str = "devops-pat"
    ) -> Optional[DevOpsCredentials]:
        """
        Retrieve Azure DevOps credentials from Key Vault.
        
        Args:
            pat_secret: Secret name for PAT
            
        Returns:
            DevOpsCredentials or None if unavailable
        """
        if self._devops_creds:
            return self._devops_creds
        
        if not self._client:
            logger.warning("Key Vault not configured, cannot retrieve DevOps credentials")
            return None
        
        pat = self._client.get_secret(pat_secret)
        
        if pat:
            self._devops_creds = DevOpsCredentials(pat=pat)
            return self._devops_creds
        
        logger.error("Failed to retrieve DevOps credentials from Key Vault")
        return None
    
    def get_fo_username(self, secret_name: str = "fo-username") -> Optional[str]:
        """
        Retrieve D365 F&O username from Key Vault.
        
        Args:
            secret_name: Secret name for username (default: fo-username)
            
        Returns:
            Username string or None if unavailable
        """
        if not self._client:
            logger.warning("Key Vault not configured, cannot retrieve username")
            return None
        
        return self._client.get_secret(secret_name)
    
    def get_fo_password(self, secret_name: str = "fo-password") -> Optional[str]:
        """
        Retrieve D365 F&O password from Key Vault.
        
        Args:
            secret_name: Secret name for password (default: fo-password)
            
        Returns:
            Password string or None if unavailable
        """
        if not self._client:
            logger.warning("Key Vault not configured, cannot retrieve password")
            return None
        
        return self._client.get_secret(secret_name)
    
    def clear_cached_credentials(self) -> None:
        """Clear all cached credentials."""
        self._d365_creds = None
        self._devops_creds = None
        if self._client:
            self._client.clear_cache()
    
    def test_keyvault_connection(self) -> tuple[bool, str]:
        """
        Test Key Vault connection.
        
        Returns:
            Tuple of (success, message)
        """
        if not self._client:
            return False, "Key Vault not configured"
        
        return self._client.test_connection()


class MockCredentialsManager(CredentialsManager):
    """
    Mock credentials manager for testing without Key Vault.
    """
    
    def __init__(
        self,
        d365_username: str = "",
        d365_password: str = "",
        devops_pat: str = ""
    ):
        """
        Initialize mock credentials manager.
        
        Args:
            d365_username: Mock D365 username
            d365_password: Mock D365 password
            devops_pat: Mock DevOps PAT
        """
        super().__init__(keyvault_client=None)
        
        if d365_username and d365_password:
            self._d365_creds = D365Credentials(
                username=d365_username,
                password=d365_password
            )
        
        if devops_pat:
            self._devops_creds = DevOpsCredentials(pat=devops_pat)
    
    def has_keyvault(self) -> bool:
        """Mock always returns True."""
        return True
    
    def test_keyvault_connection(self) -> tuple[bool, str]:
        """Mock always succeeds."""
        return True, "Mock connection (testing mode)"
