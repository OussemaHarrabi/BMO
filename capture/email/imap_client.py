"""
IMAP Client - Handles IMAP connections and email fetching.
"""

import imaplib
import email
from email.header import decode_header
from email.message import Message
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging
import time

from bmo.capture.email.config import EmailAccount

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """Parsed email message."""
    
    uid: str
    message_id: str
    subject: str
    from_email: str
    from_name: Optional[str]
    to_emails: List[str]
    cc_emails: List[str]
    date: datetime
    body_plain: str
    body_html: Optional[str]
    attachments: List[Dict[str, Any]]
    raw_headers: Dict[str, str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage.
        
        Returns:
            Dictionary representation.
        """
        return {
            "uid": self.uid,
            "message_id": self.message_id,
            "subject": self.subject,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "to_emails": self.to_emails,
            "cc_emails": self.cc_emails,
            "date": self.date.isoformat(),
            "body_plain": self.body_plain,
            "body_html": self.body_html,
            "attachments": self.attachments,
            "raw_headers": self.raw_headers,
        }


class IMAPClient:
    """IMAP client for fetching emails."""
    
    def __init__(self, account: EmailAccount):
        """Initialize IMAP client.
        
        Args:
            account: Email account configuration.
        """
        self.account = account
        self.connection: Optional[imaplib.IMAP4_SSL] = None
        self._last_poll: Optional[datetime] = None
    
    def connect(self) -> bool:
        """Connect to IMAP server.
        
        Returns:
            True if connection successful, False otherwise.
        """
        try:
            if self.account.use_ssl:
                self.connection = imaplib.IMAP4_SSL(
                    self.account.imap_server,
                    self.account.imap_port
                )
            else:
                self.connection = imaplib.IMAP4(
                    self.account.imap_server,
                    self.account.imap_port
                )
            
            # Login
            self.connection.login(self.account.email, self.account.password)
            logger.info(f"Connected to IMAP server for {self.account.email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server for {self.account.email}: {e}")
            self.connection = None
            return False
    
    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self.connection:
            try:
                self.connection.logout()
            except Exception as e:
                logger.warning(f"Error during IMAP logout: {e}")
            finally:
                self.connection = None
                logger.info(f"Disconnected from IMAP server for {self.account.email}")
    
    def select_folder(self, folder: Optional[str] = None) -> bool:
        """Select IMAP folder.
        
        Args:
            folder: Folder name (default: account's configured folder).
            
        Returns:
            True if folder selected successfully, False otherwise.
        """
        if not self.connection:
            logger.error("Not connected to IMAP server")
            return False
        
        folder = folder or self.account.folder
        
        try:
            result, data = self.connection.select(folder)
            if result != "OK":
                logger.error(f"Failed to select folder {folder}: {data}")
                return False
            
            logger.debug(f"Selected folder: {folder}")
            return True
            
        except Exception as e:
            logger.error(f"Error selecting folder {folder}: {e}")
            return False
    
    def fetch_unseen_emails(self, limit: int = 50) -> List[EmailMessage]:
        """Fetch unseen (unread) emails.
        
        Args:
            limit: Maximum number of emails to fetch.
            
        Returns:
            List of EmailMessage objects.
        """
        if not self.connection:
            logger.error("Not connected to IMAP server")
            return []
        
        try:
            # Search for unseen emails
            result, data = self.connection.search(None, "UNSEEN")
            if result != "OK":
                logger.error(f"Failed to search for unseen emails: {data}")
                return []
            
            # Get email UIDs
            email_uids = data[0].split()
            if not email_uids:
                logger.debug("No unseen emails found")
                return []
            
            # Limit number of emails
            email_uids = email_uids[-limit:] if len(email_uids) > limit else email_uids
            
            logger.info(f"Found {len(email_uids)} unseen email(s)")
            
            # Fetch emails
            emails = []
            for uid in email_uids:
                try:
                    email_msg = self._fetch_email_by_uid(uid.decode())
                    if email_msg:
                        emails.append(email_msg)
                except Exception as e:
                    logger.error(f"Failed to fetch email {uid}: {e}")
            
            return emails
            
        except Exception as e:
            logger.error(f"Error fetching unseen emails: {e}")
            return []
    
    def _fetch_email_by_uid(self, uid: str) -> Optional[EmailMessage]:
        """Fetch a single email by UID.
        
        Args:
            uid: Email UID.
            
        Returns:
            EmailMessage if successful, None otherwise.
        """
        if not self.connection:
            return None
        
        try:
            # Fetch email
            result, data = self.connection.fetch(uid, "(RFC822)")
            if result != "OK":
                logger.error(f"Failed to fetch email {uid}: {data}")
                return None
            
            # Parse email
            raw_email = data[0][1]
            email_msg = email.message_from_bytes(raw_email)
            
            # Extract fields
            parsed = self._parse_email(email_msg, uid)
            return parsed
            
        except Exception as e:
            logger.error(f"Error fetching email {uid}: {e}")
            return None
    
    def _parse_email(self, msg: Message, uid: str) -> EmailMessage:
        """Parse email message.
        
        Args:
            msg: Email message object.
            uid: Email UID.
            
        Returns:
            EmailMessage object.
        """
        # Extract subject
        subject = self._decode_header(msg.get("Subject", ""))
        
        # Extract from
        from_header = msg.get("From", "")
        from_email, from_name = self._parse_email_address(from_header)
        
        # Extract to
        to_header = msg.get("To", "")
        to_emails = self._parse_email_list(to_header)
        
        # Extract cc
        cc_header = msg.get("Cc", "")
        cc_emails = self._parse_email_list(cc_header)
        
        # Extract date
        date_str = msg.get("Date", "")
        date = self._parse_date(date_str)
        
        # Extract message ID
        message_id = msg.get("Message-ID", f"uid_{uid}")
        
        # Extract body
        body_plain, body_html = self._extract_body(msg)
        
        # Extract attachments
        attachments = self._extract_attachments(msg)
        
        # Extract raw headers
        raw_headers = {
            key: self._decode_header(value)
            for key, value in msg.items()
        }
        
        return EmailMessage(
            uid=uid,
            message_id=message_id,
            subject=subject,
            from_email=from_email,
            from_name=from_name,
            to_emails=to_emails,
            cc_emails=cc_emails,
            date=date,
            body_plain=body_plain,
            body_html=body_html,
            attachments=attachments,
            raw_headers=raw_headers,
        )
    
    def _decode_header(self, header: str) -> str:
        """Decode email header.
        
        Args:
            header: Raw header string.
            
        Returns:
            Decoded header string.
        """
        if not header:
            return ""
        
        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(encoding or "utf-8"))
                except Exception:
                    decoded_parts.append(part.decode("utf-8", errors="ignore"))
            else:
                decoded_parts.append(str(part))
        
        return " ".join(decoded_parts)
    
    def _parse_email_address(self, address: str) -> Tuple[str, Optional[str]]:
        """Parse email address with optional name.
        
        Args:
            address: Email address string (e.g., "Name <email@domain.com>").
            
        Returns:
            Tuple of (email, name).
        """
        import re
        
        decoded = self._decode_header(address)
        
        # Pattern: Name <email@domain.com>
        match = re.match(r'"?([^"<]+)"?\s*<([^>]+)>', decoded)
        if match:
            name = match.group(1).strip()
            email_addr = match.group(2).strip()
            return email_addr, name
        
        # Pattern: email@domain.com
        match = re.match(r'([^\s<>]+@[^\s<>]+)', decoded)
        if match:
            return match.group(1).strip(), None
        
        return decoded.strip(), None
    
    def _parse_email_list(self, addresses: str) -> List[str]:
        """Parse comma-separated list of email addresses.
        
        Args:
            addresses: Comma-separated email addresses.
            
        Returns:
            List of email addresses.
        """
        if not addresses:
            return []
        
        decoded = self._decode_header(addresses)
        emails = []
        
        for addr in decoded.split(","):
            email_addr, _ = self._parse_email_address(addr.strip())
            if email_addr:
                emails.append(email_addr)
        
        return emails
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse email date.
        
        Args:
            date_str: Email date string.
            
        Returns:
            Datetime object.
        """
        if not date_str:
            return datetime.now()
        
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except Exception as e:
            logger.warning(f"Failed to parse date '{date_str}': {e}")
            return datetime.now()
    
    def _extract_body(self, msg: Message) -> Tuple[str, Optional[str]]:
        """Extract email body (plain text and HTML).
        
        Args:
            msg: Email message object.
            
        Returns:
            Tuple of (plain_text, html).
        """
        body_plain = ""
        body_html = None
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                # Skip attachments
                if "attachment" in content_disposition:
                    continue
                
                # Extract text
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body_plain += payload.decode(charset, errors="ignore")
                    except Exception as e:
                        logger.warning(f"Failed to decode text/plain part: {e}")
                
                elif content_type == "text/html":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body_html = payload.decode(charset, errors="ignore")
                    except Exception as e:
                        logger.warning(f"Failed to decode text/html part: {e}")
        else:
            # Single part email
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                
                if isinstance(payload, bytes):
                    decoded = payload.decode(charset, errors="ignore")
                else:
                    decoded = str(payload)
                
                if content_type == "text/plain":
                    body_plain = decoded
                elif content_type == "text/html":
                    body_html = decoded
                else:
                    body_plain = decoded
                    
            except Exception as e:
                logger.warning(f"Failed to decode single part email: {e}")
        
        return body_plain.strip(), body_html
    
    def _extract_attachments(self, msg: Message) -> List[Dict[str, Any]]:
        """Extract attachment metadata from email.
        
        Args:
            msg: Email message object.
            
        Returns:
            List of attachment metadata dictionaries.
        """
        attachments = []
        
        if not msg.is_multipart():
            return attachments
        
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    filename = self._decode_header(filename)
                    
                    # Get content type and size
                    content_type = part.get_content_type()
                    size = len(part.get_payload(decode=True) or b"")
                    
                    attachments.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size_bytes": size,
                    })
        
        return attachments
    
    def mark_as_seen(self, uid: str) -> bool:
        """Mark email as seen (read).
        
        Args:
            uid: Email UID.
            
        Returns:
            True if successful, False otherwise.
        """
        if not self.connection:
            logger.error("Not connected to IMAP server")
            return False
        
        try:
            result, data = self.connection.store(uid, "+FLAGS", "\\Seen")
            if result != "OK":
                logger.error(f"Failed to mark email {uid} as seen: {data}")
                return False
            
            logger.debug(f"Marked email {uid} as seen")
            return True
            
        except Exception as e:
            logger.error(f"Error marking email {uid} as seen: {e}")
            return False
    
    def poll(self, max_emails: int = 50, mark_seen: bool = True) -> List[EmailMessage]:
        """Poll for new emails.
        
        Args:
            max_emails: Maximum number of emails to fetch.
            mark_seen: Whether to mark fetched emails as seen.
            
        Returns:
            List of EmailMessage objects.
        """
        # Connect if not connected
        if not self.connection:
            if not self.connect():
                return []
        
        # Select folder
        if not self.select_folder():
            return []
        
        # Fetch unseen emails
        emails = self.fetch_unseen_emails(limit=max_emails)
        
        # Mark as seen
        if mark_seen:
            for email_msg in emails:
                self.mark_as_seen(email_msg.uid)
        
        self._last_poll = datetime.now()
        return emails
