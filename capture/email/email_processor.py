"""
Email Processor - Processes emails and stores them in BMO's memory system.
"""

import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from bmo.capture.email.imap_client import EmailMessage
from bmo.processing.classifier import ContentClassifier
from bmo.memory.vector_store import VectorStore
from bmo.memory.knowledge_graph import KnowledgeGraph, extract_entities_from_text
from bmo.core.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class EmailProcessor:
    """Processes emails and stores them in BMO's memory system."""
    
    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        knowledge_graph: Optional[KnowledgeGraph] = None,
        classifier: Optional[ContentClassifier] = None,
        ollama_client: Optional[OllamaClient] = None,
        max_body_length: int = 10000,
    ):
        """Initialize email processor.
        
        Args:
            vector_store: VectorStore instance for storing emails.
            knowledge_graph: KnowledgeGraph instance for entity extraction.
            classifier: ContentClassifier instance for categorization.
            ollama_client: OllamaClient instance for AI operations.
            max_body_length: Maximum body length to store.
        """
        self.vector_store = vector_store or VectorStore()
        self.knowledge_graph = knowledge_graph or KnowledgeGraph()
        self.ollama_client = ollama_client or OllamaClient()
        self.classifier = classifier or ContentClassifier(self.ollama_client)
        self.max_body_length = max_body_length
    
    def process(self, email_msg: EmailMessage, account_email: str) -> bool:
        """Process a single email message.
        
        Args:
            email_msg: Email message to process.
            account_email: Email account that received this message.
            
        Returns:
            True if processing successful, False otherwise.
        """
        try:
            logger.info(f"Processing email: {email_msg.subject} from {email_msg.from_email}")
            
            # Create summary text
            summary = self._create_summary(email_msg)
            
            # Classify email
            classification = self.classifier.classify_sync(
                text=summary,
                max_chars=1000
            )
            
            logger.info(f"Email classified as '{classification.category}' (confidence: {classification.confidence:.2f})")
            
            # Extract entities
            entities = extract_entities_from_text(summary)
            
            # Extract email domain
            domain = self._extract_domain(email_msg.from_email)
            
            # Prepare metadata
            metadata = self._create_metadata(
                email_msg=email_msg,
                account_email=account_email,
                category=classification.category,
                confidence=classification.confidence,
                entities=entities,
                domain=domain,
            )
            
            # Store in vector database
            self.vector_store.add_sync(
                text=summary,
                metadata=metadata
            )
            
            logger.info(f"Stored email in vector database: {email_msg.message_id}")
            
            # Update knowledge graph
            self._update_knowledge_graph(
                email_msg=email_msg,
                summary=summary,
                entities=entities,
                domain=domain,
            )
            
            logger.info(f"Updated knowledge graph for email: {email_msg.message_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to process email {email_msg.message_id}: {e}")
            return False
    
    def _create_summary(self, email_msg: EmailMessage) -> str:
        """Create a summary text from email.
        
        Args:
            email_msg: Email message.
            
        Returns:
            Summary text.
        """
        # Start with subject
        parts = [f"Subject: {email_msg.subject}"]
        
        # Add sender info
        if email_msg.from_name:
            parts.append(f"From: {email_msg.from_name} <{email_msg.from_email}>")
        else:
            parts.append(f"From: {email_msg.from_email}")
        
        # Add recipients
        if email_msg.to_emails:
            parts.append(f"To: {', '.join(email_msg.to_emails)}")
        
        # Add date
        parts.append(f"Date: {email_msg.date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Add body (truncated)
        if email_msg.body_plain:
            # Clean body text
            body = self._clean_body(email_msg.body_plain)
            
            # Truncate if needed
            if len(body) > self.max_body_length:
                body = body[:self.max_body_length] + "..."
            
            parts.append(f"\nBody:\n{body}")
        
        # Add attachment info
        if email_msg.attachments:
            attachment_names = [att["filename"] for att in email_msg.attachments]
            parts.append(f"\nAttachments: {', '.join(attachment_names)}")
        
        return "\n".join(parts)
    
    def _clean_body(self, body: str) -> str:
        """Clean email body text.
        
        Args:
            body: Raw body text.
            
        Returns:
            Cleaned body text.
        """
        # Remove excessive whitespace
        body = re.sub(r'\n{3,}', '\n\n', body)
        body = re.sub(r' {2,}', ' ', body)
        
        # Remove common email footers
        body = re.sub(r'Unsubscribe.*$', '', body, flags=re.IGNORECASE | re.MULTILINE)
        
        # Remove reply/forward markers (simple heuristic)
        body = re.sub(r'^>.*$', '', body, flags=re.MULTILINE)
        body = re.sub(r'^On .* wrote:.*$', '', body, flags=re.MULTILINE)
        
        return body.strip()
    
    def _extract_domain(self, email_address: str) -> str:
        """Extract domain from email address.
        
        Args:
            email_address: Email address.
            
        Returns:
            Domain string.
        """
        if "@" in email_address:
            return email_address.split("@")[1].lower()
        return "unknown"
    
    def _create_metadata(
        self,
        email_msg: EmailMessage,
        account_email: str,
        category: str,
        confidence: float,
        entities: Any,
        domain: str,
    ) -> Dict[str, Any]:
        """Create metadata for vector storage.
        
        Args:
            email_msg: Email message.
            account_email: Email account that received this message.
            category: Classification category.
            confidence: Classification confidence.
            entities: Extracted entities.
            domain: Sender domain.
            
        Returns:
            Metadata dictionary.
        """
        return {
            "source": "email",
            "message_id": email_msg.message_id,
            "uid": email_msg.uid,
            "account_email": account_email,
            "subject": email_msg.subject,
            "from_email": email_msg.from_email,
            "from_name": email_msg.from_name or "",
            "from_domain": domain,
            "to_emails": email_msg.to_emails,
            "cc_emails": email_msg.cc_emails,
            "date": email_msg.date.isoformat(),
            "timestamp": email_msg.date.isoformat(),
            "category": category,
            "confidence": confidence,
            "has_attachments": len(email_msg.attachments) > 0,
            "attachment_count": len(email_msg.attachments),
            "attachment_names": [att["filename"] for att in email_msg.attachments],
            "files": [f["name"] for f in entities.files] if hasattr(entities, "files") else [],
            "apps": [a["name"] for a in entities.apps] if hasattr(entities, "apps") else [],
            "websites": [w["name"] for w in entities.websites] if hasattr(entities, "websites") else [],
            "actions": entities.actions if hasattr(entities, "actions") else [],
        }
    
    def _update_knowledge_graph(
        self,
        email_msg: EmailMessage,
        summary: str,
        entities: Any,
        domain: str,
    ) -> None:
        """Update knowledge graph with email data.
        
        Args:
            email_msg: Email message.
            summary: Email summary text.
            entities: Extracted entities.
            domain: Sender domain.
        """
        try:
            # Ingest email as activity
            self.knowledge_graph.ingest_activity(
                text=summary,
                activity_id=email_msg.message_id,
                timestamp=email_msg.date.isoformat(),
                activity_type="email_received"
            )
            
            # Create person node for sender
            if email_msg.from_email:
                person_name = email_msg.from_name or email_msg.from_email
                self._create_person_node(
                    name=person_name,
                    email=email_msg.from_email,
                    domain=domain
                )
            
            # Create person nodes for recipients
            for to_email in email_msg.to_emails:
                self._create_person_node(
                    name=to_email,
                    email=to_email,
                    domain=self._extract_domain(to_email)
                )
            
        except Exception as e:
            logger.warning(f"Failed to update knowledge graph: {e}")
    
    def _create_person_node(
        self,
        name: str,
        email: str,
        domain: str
    ) -> None:
        """Create or update person node in knowledge graph.
        
        Args:
            name: Person name.
            email: Email address.
            domain: Email domain.
        """
        try:
            # Use Neo4j driver directly to create/merge person node
            # This is a simplified implementation - you may want to extend this
            query = """
            MERGE (p:Person {email: $email})
            ON CREATE SET p.name = $name, p.domain = $domain, p.created_at = datetime()
            ON MATCH SET p.last_seen = datetime()
            RETURN p
            """
            
            # Note: This requires knowledge_graph to expose a way to execute queries
            # For now, we'll use the ingest_activity method which should handle entities
            logger.debug(f"Person node update for {email} would be created here")
            
        except Exception as e:
            logger.warning(f"Failed to create person node for {email}: {e}")
    
    def process_batch(
        self,
        emails: List[EmailMessage],
        account_email: str
    ) -> Dict[str, int]:
        """Process a batch of emails.
        
        Args:
            emails: List of email messages.
            account_email: Email account that received these messages.
            
        Returns:
            Dictionary with processing statistics.
        """
        stats = {
            "total": len(emails),
            "successful": 0,
            "failed": 0,
        }
        
        for email_msg in emails:
            try:
                success = self.process(email_msg, account_email)
                if success:
                    stats["successful"] += 1
                else:
                    stats["failed"] += 1
            except Exception as e:
                logger.error(f"Unexpected error processing email {email_msg.message_id}: {e}")
                stats["failed"] += 1
        
        logger.info(
            f"Batch processing complete: {stats['successful']}/{stats['total']} successful, "
            f"{stats['failed']} failed"
        )
        
        return stats
