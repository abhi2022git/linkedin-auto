"""
Image Generator: Creates branded images for LinkedIn posts using Pillow.
"""

import os
import random
import math
import requests
import json
import io
import time
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
from .utils import Article, setup_logging, get_project_root

logger = setup_logging()


# ── Gradient Themes ──────────────────────────────────────────────────────────

THEMES = [
    {
        "name": "tech_blue",
        "colors": [(10, 25, 60), (30, 80, 180), (60, 150, 255)],
        "accent": (0, 200, 255),
        "text_color": (255, 255, 255),
    },
    {
        "name": "ai_purple",
        "colors": [(30, 10, 60), (100, 40, 160), (180, 80, 255)],
        "accent": (200, 100, 255),
        "text_color": (255, 255, 255),
    },
    {
        "name": "data_green",
        "colors": [(5, 30, 20), (20, 100, 60), (40, 200, 120)],
        "accent": (0, 255, 150),
        "text_color": (255, 255, 255),
    },
    {
        "name": "deep_red",
        "colors": [(40, 5, 10), (140, 20, 40), (220, 60, 80)],
        "accent": (255, 100, 120),
        "text_color": (255, 255, 255),
    },
    {
        "name": "sunset_orange",
        "colors": [(40, 15, 5), (180, 80, 20), (255, 150, 50)],
        "accent": (255, 200, 80),
        "text_color": (255, 255, 255),
    },
    {
        "name": "dark_minimal",
        "colors": [(15, 15, 20), (25, 25, 35), (40, 40, 55)],
        "accent": (100, 200, 255),
        "text_color": (240, 240, 250),
    },
]


class ImageGenerator:
    """Generates branded images for LinkedIn posts."""

    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        if not os.getenv("CLOUDFLARE_WORKER"):
            self.output_dir = os.path.join(get_project_root(), "data", "images")
            os.makedirs(self.output_dir, exist_ok=True)
        
        from database import get_db
        with get_db() as conn:
            row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (self.user_id,)).fetchone()
            self.settings = dict(row) if row else {}
            
        self.hf_key = self.settings.get("huggingface_api_key") or os.getenv("HUGGINGFACE_API_KEY")
        self.groq_key = self.settings.get("groq_api_key") or os.getenv("GROQ_API_KEY")
        
        # Determine base model for generation
        self.hf_model = "black-forest-labs/FLUX.1-schnell"
        
    def _create_image_prompt(self, article: Article, style: str, post_content: str = None) -> str:
        """Use an LLM to generate a highly descriptive prompt for the image."""
        if not self.groq_key:
            return f"A two-panel comic strip about {article.title}, tech professionals talking, modern art style, vibrant."
            
        from groq import Groq
        try:
            client = Groq(api_key=self.groq_key)
            if style == "comic":
                instruction = "Write a visual description for a 2-panel comic strip showing a conversation or scenario representing this LinkedIn post. The comic should visually explain the core point."
            elif style == "infographic":
                instruction = "Write a visual description for a clean, modern infographic illustration showing data flows, charts, and tech concepts related to the post."
            else:
                instruction = "Write a visual description for a high-quality 3D digital illustration of diverse tech professionals in a futuristic office working on the post's topic."
                
            context = f"Post: {post_content}" if post_content else f"Article Summary: {article.summary[:300]}"
            prompt_req = f"Write an AI image generation prompt for a LinkedIn graphic. {context}\n\n{instruction} No introductory text, just the comma-separated descriptive prompt."
            
            res = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt_req}],
                max_tokens=100
            )
            return res.choices[0].message.content.strip()
        except:
            return f"{style} style tech illustration of {article.title}, highly detailed masterpiece."

    def generate(self, article: Article, post_content: str = None, theme_name: str = None) -> str:
        """
        Attempt to generate an AI image using Hugging Face.
        Falls back to gradient generation if it fails or API key is missing.
        """
        # Feature toggle check
        if not self.settings.get("enable_image_generation", 1):
            logger.info("Image generation disabled in config.")
            return None

        # If no HF key, immediately use fallback
        if not self.hf_key:
            logger.info("No HUGGINGFACE_API_KEY found for user. Using Pillow fallback generator.")
            return self._generate_fallback(article, theme_name)
            
        try:
            # Determine style - heavily biased/defaulted to comic now
            style_pref = self.settings.get("image_style") or os.getenv("IMAGE_STYLE", "comic").lower()
            if style_pref == "auto" or not style_pref:
                style_pref = "comic"
                
            logger.info(f"🎨 Generating AI image ({style_pref} style) via Hugging Face...")
            
            # Generate the prompt based on actual post content
            image_prompt = self._create_image_prompt(article, style_pref, post_content)
            logger.info(f"✨ Image Prompt: {image_prompt[:100]}...")
            
            headers = {"Authorization": f"Bearer {self.hf_key}"}
            api_url = f"https://router.huggingface.co/hf-inference/models/{self.hf_model}"
            
            # Request payload
            payload = {
                "inputs": image_prompt,
                "parameters": {
                    "width": 1024,
                    "height": 576,  # ~16:9 ratio good for LinkedIn
                    "num_inference_steps": 4
                }
            }
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=45)
            
            # Handle rate limiting / model loading (503)
            if response.status_code != 200:
                logger.warning(f"HF API Error ({response.status_code}): {response.text[:100]}... Using fallback.")
                return self._generate_fallback(article, theme_name)
                
            # Success! Now upload to Cloudinary
            image_bytes = response.content
            
            safe_title = "".join(c if c.isalnum() or c == " " else "" for c in article.title)[:40]
            safe_title = safe_title.strip().replace(" ", "_").lower()
            filename = f"ai_post_{safe_title}_{random.randint(1000, 9999)}"
            
            # --- Cloudinary Upload ---
            cloud_name = self.settings.get("cloudinary_cloud_name") or os.getenv("CLOUDINARY_CLOUD_NAME")
            api_key = self.settings.get("cloudinary_api_key") or os.getenv("CLOUDINARY_API_KEY")
            api_secret = self.settings.get("cloudinary_api_secret") or os.getenv("CLOUDINARY_API_SECRET")
            
            if cloud_name and api_key and api_secret:
                import base64
                upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
                
                # We'll use a simple authenticated upload
                timestamp = int(time.time())
                # For manual uploads via requests, it's easier to use unsigned uploads or handle signatures
                # Given we have the secret, Cloudinary's "Upload API" supports basic auth or signature
                auth = (api_key, api_secret)
                
                logger.info(f"⬆️ Uploading to Cloudinary ({cloud_name})...")
                files = {"file": (f"{filename}.png", image_bytes, "image/png")}
                data = {
                    "public_id": filename,
                    "folder": "linkedin_autoposter",
                    "timestamp": timestamp
                }
                
                cloudinary_res = requests.post(upload_url, auth=auth, files=files, data=data, timeout=30)
                
                if cloudinary_res.status_code in (200, 201):
                    result_data = cloudinary_res.json()
                    logger.info(f"✅ AI Image saved to Cloudinary: {result_data['secure_url']}")
                    return result_data["secure_url"]
                else:
                    logger.warning(f"Cloudinary Error ({cloudinary_res.status_code}): {cloudinary_res.text[:100]}... Using local/fallback.")
            
            # If Cloudinary fails or is not configured, we might still be running locally
            if not os.getenv("CLOUDFLARE_WORKER") and hasattr(self, "output_dir"):
                image = Image.open(io.BytesIO(image_bytes))
                filepath = os.path.join(self.output_dir, f"{filename}.png")
                image.save(filepath, "PNG", quality=95)
                logger.info(f"✅ AI Image saved locally: {filepath}")
                return filepath
            
            return self._generate_fallback(article, theme_name)
            
        except Exception as e:
            logger.error(f"⚠️ AI Image Generation failed: {e}. Falling back to gradient generator.")
            return self._generate_fallback(article, theme_name)

    def _generate_fallback(self, article: Article, theme_name: str = None) -> str:
        """
        Generate a branded gradient image for the article using Pillow.
        Returns the path to the saved image.
        """
        # Select theme
        if theme_name:
            theme = next((t for t in THEMES if t["name"] == theme_name), random.choice(THEMES))
        else:
            theme = random.choice(THEMES)

        logger.info(f"🎨 Generating fallback image with '{theme['name']}' theme...")

        # Create image (1200x627 — LinkedIn recommended)
        width, height = 1200, 627
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        # Draw gradient background
        self._draw_gradient(draw, width, height, theme["colors"])

        # Draw decorative elements
        self._draw_decorations(draw, width, height, theme["accent"])

        # Draw category badge
        category_text = self._get_category_label(article.category)
        self._draw_badge(draw, category_text, theme["accent"], width)

        # Draw title text
        self._draw_title(draw, article.title, theme["text_color"], width, height)

        # Draw source info
        self._draw_source(draw, article.source, theme["text_color"], width, height)

        # Draw bottom accent line
        draw.rectangle(
            [(0, height - 4), (width, height)],
            fill=theme["accent"]
        )

        # Save
        safe_title = "".join(c if c.isalnum() or c == " " else "" for c in article.title)[:40]
        safe_title = safe_title.strip().replace(" ", "_").lower()
        filename = f"fallback_{safe_title}_{random.randint(1000, 9999)}.png"
        filepath = os.path.join(self.output_dir, filename)
        img.save(filepath, "PNG", quality=95)

        logger.info(f"✅ Fallback image saved: {filepath}")
        return filepath

    def _draw_gradient(self, draw: ImageDraw, width: int, height: int, colors: list):
        """Draw a multi-stop gradient background."""
        num_colors = len(colors)
        for y in range(height):
            ratio = y / height
            # Find which two colors to interpolate
            segment = ratio * (num_colors - 1)
            idx = min(int(segment), num_colors - 2)
            local_ratio = segment - idx

            c1 = colors[idx]
            c2 = colors[idx + 1]
            r = int(c1[0] + (c2[0] - c1[0]) * local_ratio)
            g = int(c1[1] + (c2[1] - c1[1]) * local_ratio)
            b = int(c1[2] + (c2[2] - c1[2]) * local_ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

    def _draw_decorations(self, draw: ImageDraw, width: int, height: int, accent: tuple):
        """Draw geometric decorative elements."""
        # Subtle grid of dots
        accent_faded = (*accent[:3], 30) if len(accent) == 4 else accent
        for x in range(0, width, 40):
            for y in range(0, height, 40):
                alpha = random.randint(10, 40)
                color = (accent[0], accent[1], accent[2])
                # Only draw some dots for a scattered effect
                if random.random() < 0.15:
                    draw.ellipse(
                        [(x - 1, y - 1), (x + 1, y + 1)],
                        fill=color
                    )

        # Corner accent shapes
        # Top-right arc
        draw.arc(
            [(width - 200, -100), (width + 100, 200)],
            start=90, end=270,
            fill=accent, width=2
        )
        # Bottom-left arc
        draw.arc(
            [(-100, height - 200), (200, height + 100)],
            start=270, end=90,
            fill=accent, width=2
        )

    def _draw_badge(self, draw: ImageDraw, text: str, accent: tuple, width: int):
        """Draw a category badge in the top-left."""
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except OSError:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            except OSError:
                font = ImageFont.load_default()

        padding = 12
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        badge_x = 40
        badge_y = 35
        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + text_w + padding * 2, badge_y + text_h + padding * 2)],
            radius=6,
            fill=accent
        )
        draw.text(
            (badge_x + padding, badge_y + padding),
            text, fill=(0, 0, 0), font=font
        )

    def _draw_title(self, draw: ImageDraw, title: str, color: tuple, width: int, height: int):
        """Draw the article title as wrapped text."""
        # Try different font sizes
        for font_size in [42, 36, 30, 24]:
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except OSError:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except OSError:
                    font = ImageFont.load_default()
                    font_size = 16

            # Word wrap
            words = title.split()
            lines = []
            current_line = ""
            max_width = width - 100  # 50px padding each side

            for word in words:
                test_line = f"{current_line} {word}".strip()
                bbox = draw.textbbox((0, 0), test_line, font=font)
                if bbox[2] - bbox[0] <= max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)

            # Check if it fits vertically
            line_height = font_size + 10
            total_text_height = len(lines) * line_height
            if total_text_height < height - 180:  # Leave space for badge and source
                break

        # Center vertically
        start_y = (height - total_text_height) // 2 + 10
        for i, line in enumerate(lines):
            draw.text(
                (50, start_y + i * line_height),
                line, fill=color, font=font
            )

    def _draw_source(self, draw: ImageDraw, source: str, color: tuple, width: int, height: int):
        """Draw source attribution at the bottom."""
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except OSError:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except OSError:
                font = ImageFont.load_default()

        text = f"📰 {source}"
        faded_color = (
            min(color[0], 200),
            min(color[1], 200),
            min(color[2], 200),
        )
        draw.text((50, height - 45), text, fill=faded_color, font=font)

    def _get_category_label(self, category: str) -> str:
        """Convert category code to display label."""
        labels = {
            "ai_ml": "🤖 AI / ML",
            "tech": "💻 TECH",
            "programming": "⌨️ CODE",
            "cloud_ai": "☁️ CLOUD AI",
        }
        return labels.get(category, "💡 TECH")
