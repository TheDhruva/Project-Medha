"""Centralized AI provider integration (Groq primary, Gemini fallback)."""

from app.ai.service import AIOutcome, AIService

__all__ = ["AIOutcome", "AIService"]
