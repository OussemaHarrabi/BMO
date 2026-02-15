"""
Content Classifier - Classifies content into categories using Phi-3.5.
"""

from typing import Optional
from dataclasses import dataclass
import logging

from core.ollama_client import OllamaClient, ModelRole

logger = logging.getLogger(__name__)


# Valid categories
VALID_CATEGORIES = [
    "work",           # Professional tasks, emails, office work
    "code",           # Programming, development, debugging
    "research",       # Academic papers, learning materials, documentation
    "studying",       # Courses, education, study sessions, homework
    "meetings",       # Video calls, conferences, scheduled discussions
    "entertainment",  # Movies, music, games, social media, leisure
    "shopping",       # E-commerce, purchases, wishlists, product research
    "health",         # Fitness, medical, wellness, nutrition
    "travel",         # Trips, bookings, planning, destinations
    "finance",        # Banking, investments, budgets, transactions
    "social",         # Messaging apps, social networks, contacts
    "creative",       # Design, writing, art, photography, content creation
    "personal",       # Private notes, journal, diary, family
]

DEFAULT_CATEGORY = "uncategorized"


CLASSIFIER_SYSTEM_PROMPT = """You are a content classifier for a personal memory system.
Classify the given text into exactly ONE category.

Categories:
- work: Professional tasks, emails, office work, projects, colleagues
- code: Programming, software development, technical documentation, GitHub, APIs
- research: Academic papers, technical learning materials, documentation
- studying: Courses, education, study sessions, homework, lectures
- meetings: Video calls, conferences, scheduled discussions, calendar events
- entertainment: Movies, music, games, social media, leisure content
- shopping: E-commerce, purchases, wishlists, product research, checkouts
- health: Fitness, medical, wellness, nutrition, workouts, doctor visits
- travel: Trips, bookings, planning, destinations, flights, hotels
- finance: Banking, investments, budgets, transactions, financial news
- social: Messaging apps, social networks, contacts, chats
- creative: Design, writing, art, photography, content creation
- personal: Private notes, journal, diary, family, personal thoughts

Respond with ONLY the category name in lowercase, nothing else."""


@dataclass
class ClassificationResult:
    """Result of content classification."""
    category: str
    confidence: float
    latency_ms: int
    model: str


class ContentClassifier:
    """Classifies content into predefined categories."""
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """Initialize classifier.
        
        Args:
            client: Optional OllamaClient instance. Creates one if not provided.
        """
        self.client = client or OllamaClient()
    
    async def classify(
        self,
        text: str,
        max_chars: int = 1000
    ) -> ClassificationResult:
        """Classify text content into a category.
        
        Args:
            text: The text content to classify.
            max_chars: Maximum characters to use from text.
            
        Returns:
            ClassificationResult with category and metadata.
        """
        # Truncate text if needed
        truncated = text[:max_chars] if len(text) > max_chars else text
        
        prompt = f"Classify this content:\n\n{truncated}\n\nCategory:"
        
        try:
            result = await self.client.generate(
                role=ModelRole.CLASSIFIER,
                prompt=prompt,
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                temperature=0.1,  # Very deterministic
                max_tokens=20
            )
            
            # Parse response - extract category
            category = result.content.strip().lower()
            
            # Validate category
            if category not in VALID_CATEGORIES:
                logger.warning(f"Invalid category returned: {category}, using default")
                category = DEFAULT_CATEGORY
                confidence = 0.0
            else:
                # Estimate confidence based on response clarity
                confidence = 0.9 if category in VALID_CATEGORIES else 0.5
            
            return ClassificationResult(
                category=category,
                confidence=confidence,
                latency_ms=result.latency_ms,
                model=result.model
            )
            
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return ClassificationResult(
                category=DEFAULT_CATEGORY,
                confidence=0.0,
                latency_ms=0,
                model="error"
            )
    
    def classify_sync(
        self,
        text: str,
        max_chars: int = 1000
    ) -> ClassificationResult:
        """Classify text content (synchronous version).
        
        Args:
            text: The text content to classify.
            max_chars: Maximum characters to use from text.
            
        Returns:
            ClassificationResult with category and metadata.
        """
        truncated = text[:max_chars] if len(text) > max_chars else text
        prompt = f"Classify this content:\n\n{truncated}\n\nCategory:"
        
        try:
            result = self.client.generate_sync(
                role=ModelRole.CLASSIFIER,
                prompt=prompt,
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=20
            )
            
            category = result.content.strip().lower()
            
            if category not in VALID_CATEGORIES:
                logger.warning(f"Invalid category returned: {category}, using default")
                category = DEFAULT_CATEGORY
                confidence = 0.0
            else:
                confidence = 0.9
            
            return ClassificationResult(
                category=category,
                confidence=confidence,
                latency_ms=result.latency_ms,
                model=result.model
            )
            
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return ClassificationResult(
                category=DEFAULT_CATEGORY,
                confidence=0.0,
                latency_ms=0,
                model="error"
            )
    
    @staticmethod
    def classify_by_keywords(text: str) -> Optional[str]:
        """Fast keyword-based pre-classification (no LLM call).
        
        Can be used for quick filtering or as a fallback.
        
        Args:
            text: Text to classify.
            
        Returns:
            Category string or None if no strong match.
        """
        text_lower = text.lower()
        
        # Code indicators
        code_keywords = [
            "function", "class", "import", "def ", "const ", "let ", "var ",
            "github.com", "gitlab.com", "stackoverflow", "npm", "pip", "cargo",
            "async", "await", "return", "if (", "for (", "while ("
        ]
        if any(kw in text_lower for kw in code_keywords):
            return "code"
        
        # Finance indicators
        finance_keywords = [
            "bank", "investment", "stock", "crypto", "budget", "payment",
            "invoice", "$", "transaction", "dividend", "portfolio"
        ]
        if any(kw in text_lower for kw in finance_keywords):
            return "finance"
        
        # Research indicators
        research_keywords = [
            "paper", "study", "research", "abstract", "methodology",
            "arxiv", "ieee", "tutorial", "course", "learn"
        ]
        if any(kw in text_lower for kw in research_keywords):
            return "research"
        
        # Work indicators
        work_keywords = [
            "meeting", "deadline", "sprint", "jira", "confluence",
            "slack", "project manager", "client"
        ]
        if any(kw in text_lower for kw in work_keywords):
            return "work"
        
        # Entertainment indicators  
        entertainment_keywords = [
            "movie", "music", "game", "youtube", "netflix", "spotify",
            "twitch", "reddit", "twitter"
        ]
        if any(kw in text_lower for kw in entertainment_keywords):
            return "entertainment"
        
        # Studying indicators
        studying_keywords = [
            "course", "lecture", "exam", "homework", "quiz", "professor", "university"
        ]
        if any(kw in text_lower for kw in studying_keywords):
            return "studying"
        
        # Meetings indicators
        meetings_keywords = [
            "zoom", "meet", "teams", "webex", "calendar", "agenda", "attendees"
        ]
        if any(kw in text_lower for kw in meetings_keywords):
            return "meetings"
        
        # Shopping indicators
        shopping_keywords = [
            "amazon", "ebay", "cart", "checkout", "order", "shipping", "price"
        ]
        if any(kw in text_lower for kw in shopping_keywords):
            return "shopping"
        
        # Health indicators
        health_keywords = [
            "workout", "gym", "doctor", "medicine", "calories", "steps", "sleep"
        ]
        if any(kw in text_lower for kw in health_keywords):
            return "health"
        
        # Travel indicators
        travel_keywords = [
            "flight", "hotel", "booking", "airbnb", "trip", "destination", "passport"
        ]
        if any(kw in text_lower for kw in travel_keywords):
            return "travel"
        
        # Social indicators
        social_keywords = [
            "whatsapp", "messenger", "telegram", "discord", "chat", "message"
        ]
        if any(kw in text_lower for kw in social_keywords):
            return "social"
        
        # Creative indicators
        creative_keywords = [
            "photoshop", "figma", "canvas", "design", "draw", "write", "edit"
        ]
        if any(kw in text_lower for kw in creative_keywords):
            return "creative"
        
        return None


async def classify_content(
    text: str,
    client: Optional[OllamaClient] = None,
    use_keyword_fallback: bool = True
) -> str:
    """Convenience function to classify content.
    
    Args:
        text: Text to classify.
        client: Optional OllamaClient instance.
        use_keyword_fallback: Whether to try keyword classification first.
        
    Returns:
        Category string.
    """
    classifier = ContentClassifier(client)
    
    # Try keyword classification first (fast)
    if use_keyword_fallback:
        keyword_result = classifier.classify_by_keywords(text)
        if keyword_result:
            return keyword_result
    
    # Use LLM classification
    result = await classifier.classify(text)
    return result.category
