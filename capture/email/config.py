"""
Email Capture Configuration - Email account configuration and settings.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class EmailAccount:
    """Configuration for a single email account."""
    
    email: str
    password: str  # App password for Gmail/OAuth token
    imap_server: str
    imap_port: int = 993
    use_ssl: bool = True
    folder: str = "INBOX"
    poll_interval_seconds: int = 60
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.email:
            raise ValueError("Email address is required")
        if not self.password:
            raise ValueError("Password/app password is required")
        if not self.imap_server:
            raise ValueError("IMAP server is required")
        if self.imap_port <= 0:
            raise ValueError("IMAP port must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be positive")
    
    @classmethod
    def from_dict(cls, data: dict) -> "EmailAccount":
        """Create EmailAccount from dictionary.
        
        Args:
            data: Dictionary with account configuration.
            
        Returns:
            EmailAccount instance.
        """
        return cls(
            email=data.get("email", ""),
            password=data.get("password", ""),
            imap_server=data.get("imap_server", ""),
            imap_port=data.get("imap_port", 993),
            use_ssl=data.get("use_ssl", True),
            folder=data.get("folder", "INBOX"),
            poll_interval_seconds=data.get("poll_interval_seconds", 60),
        )
    
    def to_safe_dict(self) -> dict:
        """Convert to dictionary with password redacted.
        
        Returns:
            Dictionary with safe configuration (password masked).
        """
        return {
            "email": self.email,
            "password": "***" if self.password else "",
            "imap_server": self.imap_server,
            "imap_port": self.imap_port,
            "use_ssl": self.use_ssl,
            "folder": self.folder,
            "poll_interval_seconds": self.poll_interval_seconds,
        }


@dataclass
class EmailCaptureConfig:
    """Global email capture configuration."""
    
    accounts: List[EmailAccount] = field(default_factory=list)
    default_poll_interval: int = 60
    max_emails_per_poll: int = 50
    process_attachments: bool = True
    max_body_length: int = 10000
    
    @classmethod
    def from_env(cls) -> "EmailCaptureConfig":
        """Load configuration from environment variables.
        
        Environment variables:
            EMAIL_ACCOUNTS: JSON array of account configurations
            EMAIL_POLL_INTERVAL: Default poll interval in seconds
            EMAIL_MAX_PER_POLL: Maximum emails to fetch per poll
            EMAIL_PROCESS_ATTACHMENTS: Whether to process attachments
            EMAIL_MAX_BODY_LENGTH: Maximum body length to store
            
        Returns:
            EmailCaptureConfig instance.
        """
        accounts = []
        
        # Load accounts from EMAIL_ACCOUNTS JSON
        accounts_json = os.getenv("EMAIL_ACCOUNTS", "[]")
        try:
            accounts_data = json.loads(accounts_json)
            for account_data in accounts_data:
                try:
                    account = EmailAccount.from_dict(account_data)
                    accounts.append(account)
                    logger.info(f"Loaded email account: {account.email}")
                except Exception as e:
                    logger.error(f"Failed to load email account {account_data.get('email', 'unknown')}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse EMAIL_ACCOUNTS JSON: {e}")
        
        # Load global settings
        default_poll_interval = int(os.getenv("EMAIL_POLL_INTERVAL", "60"))
        max_emails_per_poll = int(os.getenv("EMAIL_MAX_PER_POLL", "50"))
        process_attachments = os.getenv("EMAIL_PROCESS_ATTACHMENTS", "true").lower() == "true"
        max_body_length = int(os.getenv("EMAIL_MAX_BODY_LENGTH", "10000"))
        
        return cls(
            accounts=accounts,
            default_poll_interval=default_poll_interval,
            max_emails_per_poll=max_emails_per_poll,
            process_attachments=process_attachments,
            max_body_length=max_body_length,
        )
    
    def get_account(self, email: str) -> Optional[EmailAccount]:
        """Get account configuration by email address.
        
        Args:
            email: Email address to search for.
            
        Returns:
            EmailAccount if found, None otherwise.
        """
        for account in self.accounts:
            if account.email == email:
                return account
        return None


# Common IMAP server configurations
IMAP_PRESETS = {
    "gmail": {
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "use_ssl": True,
    },
    "outlook": {
        "imap_server": "outlook.office365.com",
        "imap_port": 993,
        "use_ssl": True,
    },
    "yahoo": {
        "imap_server": "imap.mail.yahoo.com",
        "imap_port": 993,
        "use_ssl": True,
    },
    "icloud": {
        "imap_server": "imap.mail.me.com",
        "imap_port": 993,
        "use_ssl": True,
    },
}


def create_account_from_preset(
    preset: str,
    email: str,
    password: str,
    **kwargs
) -> EmailAccount:
    """Create an email account using a preset configuration.
    
    Args:
        preset: Preset name (gmail, outlook, yahoo, icloud).
        email: Email address.
        password: App password or OAuth token.
        **kwargs: Additional configuration overrides.
        
    Returns:
        EmailAccount instance.
        
    Raises:
        ValueError: If preset is unknown.
    """
    if preset not in IMAP_PRESETS:
        raise ValueError(f"Unknown preset '{preset}'. Available: {list(IMAP_PRESETS.keys())}")
    
    preset_config = IMAP_PRESETS[preset].copy()
    preset_config.update(kwargs)
    preset_config["email"] = email
    preset_config["password"] = password
    
    return EmailAccount.from_dict(preset_config)
