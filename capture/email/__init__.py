"""
Email Capture Module - Polls IMAP servers and processes emails into BMO's memory.

This module provides email capture functionality that:
1. Connects to IMAP servers (Gmail, Outlook, Yahoo, etc.)
2. Polls for new emails at configurable intervals
3. Extracts email metadata (subject, sender, body, attachments)
4. Classifies emails using ContentClassifier
5. Stores emails in VectorStore with embeddings
6. Updates KnowledgeGraph with email-related entities

Usage:
    from bmo.capture.email import start_email_capture, EmailCaptureConfig
    
    # Load configuration from environment
    config = EmailCaptureConfig.from_env()
    
    # Start email capture (runs in background thread)
    start_email_capture(config)
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

from bmo.capture.email.config import (
    EmailAccount,
    EmailCaptureConfig,
    create_account_from_preset,
    IMAP_PRESETS,
)
from bmo.capture.email.imap_client import IMAPClient, EmailMessage
from bmo.capture.email.email_processor import EmailProcessor

logger = logging.getLogger(__name__)

# Module exports
__all__ = [
    "EmailAccount",
    "EmailCaptureConfig",
    "EmailMessage",
    "IMAPClient",
    "EmailProcessor",
    "EmailCaptureService",
    "start_email_capture",
    "create_account_from_preset",
    "IMAP_PRESETS",
]


class EmailCaptureService:
    """Service that manages email capture for multiple accounts."""
    
    def __init__(
        self,
        config: EmailCaptureConfig,
        processor: Optional[EmailProcessor] = None,
    ):
        """Initialize email capture service.
        
        Args:
            config: Email capture configuration.
            processor: Optional EmailProcessor instance.
        """
        self.config = config
        self.processor = processor or EmailProcessor(
            max_body_length=config.max_body_length
        )
        self.clients: Dict[str, IMAPClient] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start email capture in background thread."""
        if self._running:
            logger.warning("Email capture already running")
            return
        
        if not self.config.accounts:
            logger.error("No email accounts configured")
            return
        
        # Initialize IMAP clients
        for account in self.config.accounts:
            client = IMAPClient(account)
            self.clients[account.email] = client
            logger.info(f"Initialized IMAP client for {account.email}")
        
        # Start background thread
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        
        logger.info(f"Email capture started for {len(self.clients)} account(s)")
    
    def stop(self) -> None:
        """Stop email capture."""
        if not self._running:
            return
        
        logger.info("Stopping email capture...")
        self._running = False
        
        # Wait for thread to finish
        if self._thread:
            self._thread.join(timeout=10)
        
        # Disconnect all clients
        for email, client in self.clients.items():
            try:
                client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting {email}: {e}")
        
        self.clients.clear()
        logger.info("Email capture stopped")
    
    def _run(self) -> None:
        """Background thread main loop."""
        logger.info("Email capture thread started")
        
        while self._running:
            try:
                self._poll_all_accounts()
                
                # Sleep for the configured interval
                time.sleep(self.config.default_poll_interval)
                
            except Exception as e:
                logger.error(f"Error in email capture loop: {e}")
                time.sleep(10)  # Sleep briefly on error
        
        logger.info("Email capture thread stopped")
    
    def _poll_all_accounts(self) -> None:
        """Poll all configured email accounts."""
        for account_email, client in self.clients.items():
            try:
                self._poll_account(client, account_email)
            except Exception as e:
                logger.error(f"Error polling {account_email}: {e}")
    
    def _poll_account(self, client: IMAPClient, account_email: str) -> None:
        """Poll a single email account.
        
        Args:
            client: IMAP client.
            account_email: Email account address.
        """
        # Poll for new emails
        emails = client.poll(
            max_emails=self.config.max_emails_per_poll,
            mark_seen=True
        )
        
        if not emails:
            logger.debug(f"No new emails for {account_email}")
            return
        
        logger.info(f"Found {len(emails)} new email(s) for {account_email}")
        
        # Process emails
        stats = self.processor.process_batch(emails, account_email)
        
        logger.info(
            f"Processed {stats['successful']}/{stats['total']} emails for {account_email}"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get email capture statistics.
        
        Returns:
            Dictionary with statistics.
        """
        return {
            "running": self._running,
            "account_count": len(self.clients),
            "accounts": [email for email in self.clients.keys()],
            "poll_interval": self.config.default_poll_interval,
            "max_emails_per_poll": self.config.max_emails_per_poll,
        }


# Global service instance
_email_capture_service: Optional[EmailCaptureService] = None


def start_email_capture(config: Optional[EmailCaptureConfig] = None) -> EmailCaptureService:
    """Start email capture service.
    
    Args:
        config: Email capture configuration. If None, loads from environment.
        
    Returns:
        EmailCaptureService instance.
    """
    global _email_capture_service
    
    # Use provided config or load from environment
    if config is None:
        config = EmailCaptureConfig.from_env()
    
    # Create or reuse service
    if _email_capture_service is None:
        _email_capture_service = EmailCaptureService(config)
    
    # Start service
    _email_capture_service.start()
    
    return _email_capture_service


def stop_email_capture() -> None:
    """Stop email capture service."""
    global _email_capture_service
    
    if _email_capture_service:
        _email_capture_service.stop()
        _email_capture_service = None


def get_email_capture_service() -> Optional[EmailCaptureService]:
    """Get the current email capture service instance.
    
    Returns:
        EmailCaptureService instance or None if not started.
    """
    return _email_capture_service
