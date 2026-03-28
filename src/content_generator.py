"""
LLM Content Generator: Generates LinkedIn posts using Groq API with multi-model rotation.
"""

import os
import random
import requests
import json
from typing import Optional, Tuple
from groq import Groq
from dotenv import load_dotenv
from .utils import Article, setup_logging, DatabaseManager

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

logger = setup_logging()


# ── Model Configuration ─────────────────────────────────────────────────────

MODELS = [
    {
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B",
        "provider": "groq",
        "strength": "detailed, analytical posts",
        "max_tokens": 4096,
    },
    {
        "id": "llama-3.1-70b-versatile",
        "name": "Llama 3.1 70B",
        "provider": "groq",
        "strength": "creative, varied writing",
        "max_tokens": 4096,
    },
    {
        "id": "deepseek-r1-distill-llama-70b",
        "name": "DeepSeek R1 70B",
        "provider": "groq",
        "strength": "advanced reasoning, analytical posts",
        "max_tokens": 4096,
    },
    {
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B",
        "provider": "groq",
        "strength": "fast, engaging content",
        "max_tokens": 4096,
    },
    {
        "id": "meta-llama/llama-3-8b-instruct:free",
        "name": "OR: Llama 3 8B (Free)",
        "provider": "openrouter",
        "strength": "fast, engaging content",
        "max_tokens": 4096,
    },
    {
        "id": "mistralai/mistral-7b-instruct:free",
        "name": "OR: Mistral 7B (Free)",
        "provider": "openrouter",
        "strength": "flowing narrative, professional tone",
        "max_tokens": 4096,
    },
    {
        "id": "meta-llama/Meta-Llama-3-8B-Instruct",
        "name": "HF: Llama 3 8B",
        "provider": "huggingface",
        "strength": "fast, engaging content",
        "max_tokens": 4096,
    },
    {
        "id": "Qwen/Qwen2.5-72B-Instruct",
        "name": "HF: Qwen 2.5 72B",
        "provider": "huggingface",
        "strength": "detailed, analytical posts",
        "max_tokens": 4096,
    },
]

# ── Post Styles ──────────────────────────────────────────────────────────────

POST_STYLES = [
    {
        "name": "thought_leadership",
        "instruction": (
            "Write as a thought leader sharing a strong perspective. Start with a bold, "
            "attention-grabbing statement. Share your unique take on why this matters for "
            "the industry. Be confident and opinionated but backed by reasoning."
        ),
    },
    {
        "name": "tutorial_insight",
        "instruction": (
            "Write as someone breaking down a complex topic for their network. Start with "
            "a relatable problem or question. Explain the concept step-by-step in simple terms. "
            "Include a practical takeaway or tip that readers can apply immediately."
        ),
    },
    {
        "name": "news_commentary",
        "instruction": (
            "Write as an industry insider commenting on breaking news. Start with the news "
            "hook, then add your own analysis of what it means. Discuss implications, risks, "
            "and opportunities. Be forward-looking about what comes next."
        ),
    },
    {
        "name": "hot_take",
        "instruction": (
            "Write a bold, provocative take that challenges conventional thinking. Start with "
            "a controversial or surprising statement. Back it up with logic and evidence. "
            "Invite debate and discussion. Be authentic and slightly contrarian."
        ),
    },
    {
        "name": "listicle",
        "instruction": (
            "Write a structured list post (e.g., '5 things I learned about...' or "
            "'3 reasons why...'). Make each point concise and impactful. Use numbers "
            "and emojis for readability. End with a strong takeaway or question."
        ),
    },
]


class ContentGenerator:
    """Generates LinkedIn posts using Groq API with multi-model rotation."""

    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        import sqlite3
        from .utils import get_project_root
        db_path = os.path.join(get_project_root(), "data", "history.db")
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (self.user_id,)).fetchone()
            settings = dict(row) if row else {}
            
        groq_key = settings.get("groq_api_key") or os.getenv("GROQ_API_KEY")
        self.or_key = settings.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY")
        self.hf_key = settings.get("huggingface_api_key") or os.getenv("HUGGINGFACE_API_KEY")
        self.preferred_model = settings.get("preferred_model") or os.getenv("PREFERRED_MODEL", "auto")
        
        if not groq_key and not self.or_key and not self.hf_key:
            logger.warning(f"No API keys found for User {self.user_id}! Please configure them in the dashboard Settings.")
        
        # We can still init Groq if the key exists, else it will be None
        self.client = Groq(api_key=groq_key) if groq_key else None
        self.db = DatabaseManager()

    def _select_model(self, override_model: str = None) -> dict:
        """Select a model using rotation (avoid repeating the last model)."""
        if override_model:
            for m in MODELS:
                if m["id"] == override_model:
                    return m
            logger.warning(f"Override model '{override_model}' not found, falling back")

        if self.preferred_model != "auto":
            # User specified a model in config
            for m in MODELS:
                if m["id"] == self.preferred_model:
                    return m
            logger.warning(f"Model '{self.preferred_model}' not found, using auto-rotation")

        last_model = self.db.get_last_model_used()
        available = [m for m in MODELS if m["id"] != last_model]
        if not available:
            available = MODELS
        return random.choice(available)

    def _select_style(self) -> dict:
        """Randomly select a post style."""
        return random.choice(POST_STYLES)

    def _build_prompt(self, article: Article, style: dict) -> str:
        """Build the LLM prompt for generating a LinkedIn post."""
        return f"""You are a professional LinkedIn content creator specializing in technology and AI/ML topics.

Your task: Write a compelling LinkedIn post based on the article information below.

## Article Information
- **Title**: {article.title}
- **Source**: {article.source}
- **Summary**: {article.summary}
- **Tags**: {', '.join(article.tags) if article.tags else 'N/A'}
- **URL**: {article.url}

## Post Style
{style['instruction']}

## Rules (MUST follow)
1. Start with a hook line — the first 2 lines must grab attention (this is what shows before "...see more")
2. Keep the total post under 2800 characters (LinkedIn limit is 3000)
3. Use short paragraphs (1-3 sentences max per paragraph)
4. Add line breaks between paragraphs for readability
5. Include 3-5 relevant hashtags at the end (e.g., #AI #MachineLearning #DeepLearning)
6. Use 2-3 emojis sparingly for visual appeal — don't overdo it
7. Write in first person — be authentic and professional
8. DO NOT use any markdown formatting (no **, no ##, no bullet points with -)
9. Instead of bullet points, use plain text with line breaks, or use emojis as markers (→, •, ▸)
10. Include the article URL naturally in the post (don't just paste it at the end)
11. Add a call to action at the end (ask a question, invite comments, etc.)
12. DO NOT start with "I just read..." or "I came across..." — be more creative
13. Sound human — avoid corporate jargon and buzzword-stuffing

## Output
Write ONLY the LinkedIn post text. No titles, no explanations, no meta-commentary. Just the post itself, ready to publish."""

    def generate_post(self, article: Article, override_model: str = None) -> Tuple[str, str]:
        """
        Generate a LinkedIn post for the given article.
        Returns: (post_content, model_id)
        """
        style = self._select_style()
        prompt = self._build_prompt(article, style)

        # Try models with fallback
        errors = []
        selected_model = self._select_model(override_model)
        models_to_try = [selected_model] + [m for m in MODELS if m != selected_model]
        
        # Deduplicate while preserving order
        seen = set()
        unique_models = []
        for m in models_to_try:
            if m["id"] not in seen:
                seen.add(m["id"])
                unique_models.append(m)

        for model in unique_models:
            try:
                logger.info(f"🤖 Generating with {model['name']} (style: {style['name']})...")
                
                provider = model.get("provider", "groq")
                post_content = ""
                
                system_msg = "You are a professional LinkedIn content creator. Write engaging, authentic posts about technology topics. Never use markdown formatting. Write in plain text only."
                
                if provider == "groq":
                    if not self.client:
                        raise ValueError("Groq API key not configured")
                    response = self.client.chat.completions.create(
                        model=model["id"],
                        messages=[
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=model["max_tokens"],
                        temperature=0.8,
                        top_p=0.9,
                    )
                    post_content = response.choices[0].message.content.strip()
                
                elif provider == "openrouter":
                    if not self.or_key:
                        raise ValueError("OpenRouter API key not configured")
                    headers = {
                        "Authorization": f"Bearer {self.or_key}",
                        "HTTP-Referer": "http://localhost:8000",
                        "X-Title": "LinkedIn Auto-Poster",
                    }
                    data = {
                        "model": model["id"],
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": model["max_tokens"],
                        "temperature": 0.8,
                        "top_p": 0.9,
                    }
                    res = requests.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=data
                    )
                    if res.status_code != 200:
                        raise RuntimeError(f"OpenRouter API error {res.status_code}: {res.text}")
                    post_content = res.json()["choices"][0]["message"]["content"].strip()
                
                elif provider == "huggingface":
                    if not self.hf_key:
                        raise ValueError("Hugging Face API key not configured")
                    headers = {
                        "Authorization": f"Bearer {self.hf_key}",
                        "Content-Type": "application/json"
                    }
                    data = {
                        "model": model["id"],
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": model["max_tokens"],
                        "temperature": 0.8,
                        "top_p": 0.9,
                    }
                    res = requests.post(
                        f"https://router.huggingface.co/hf-inference/models/{model['id']}/v1/chat/completions",
                        headers=headers,
                        json=data
                    )
                    if res.status_code != 200:
                        raise RuntimeError(f"Hugging Face API error {res.status_code}: {res.text}")
                    post_content = res.json()["choices"][0]["message"]["content"].strip()
                
                else:
                    raise ValueError(f"Unknown provider: {provider}")
                
                # Clean up any accidental markdown
                post_content = self._clean_post(post_content)
                
                # Validate length
                if len(post_content) > 3000:
                    post_content = post_content[:2950] + "\n\n..."
                
                if len(post_content) < 100:
                    logger.warning(f"Post too short ({len(post_content)} chars), trying next model...")
                    continue
                
                logger.info(f"✅ Generated {len(post_content)} chars with {model['name']}")
                return post_content, model["id"]
            
            except Exception as e:
                error_msg = str(e)
                errors.append(f"{model['name']}: {error_msg}")
                logger.warning(f"⚠️ {model['name']} failed: {error_msg}")
                continue
        
        raise RuntimeError(
            f"All models failed to generate content.\nErrors:\n" +
            "\n".join(f"  • {e}" for e in errors)
        )

    def _clean_post(self, text: str) -> str:
        """Remove any markdown formatting that slipped through."""
        import re
        # Remove bold markdown
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        # Remove italic markdown
        text = re.sub(r'\*(.*?)\*', r'\1', text)
        # Remove headers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        # Remove markdown links, keep text
        text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1 (\2)', text)
        # Remove markdown bullet points
        text = re.sub(r'^[\s]*[-*]\s+', '→ ', text, flags=re.MULTILINE)
        return text.strip()

    def preview_post(self, article: Article, override_model: str = None) -> str:
        """Generate and display a preview of the post (for dry-run mode)."""
        post_content, model_id = self.generate_post(article, override_model=override_model)
        
        preview = f"""
{'='*60}
📝 LINKEDIN POST PREVIEW
{'='*60}
Model: {model_id}
Topic: {article.title}
Source: {article.source}
Length: {len(post_content)} characters
{'─'*60}

{post_content}

{'='*60}
"""
        print(preview)
        return post_content
