"""
LinkedIn Auto-Apply Services

This package contains all the core services for LinkedIn job automation:
- SessionManager: Handles LinkedIn session persistence
- Database: SQLite database for tracking jobs and applications
- JobScraper: Scrapes LinkedIn job listings
- JobEvaluator: AI-powered job evaluation using Gemini
- AutoApplier: Automated job application submission
- AIService: Gemini AI integration with structured outputs
- FormFieldFiller: Intelligent form field detection and filling
- cv_data: User CV/profile data for AI prompts
"""

from .session_manager import SessionManager
from .database import Database
from .job_scraper import JobScraper
from .job_evaluator import JobEvaluator
from .auto_applier import AutoApplier
from .ai_service import AIService
from .form_field_filler import FormFieldFiller
from .cv_data import CV_SUPPLEMENTARY, CV_FULL_TEXT
from .base_service import SingletonService

__all__ = [
    'SessionManager',
    'Database',
    'JobScraper',
    'JobEvaluator',
    'AutoApplier',
    'AIService',
    'FormFieldFiller',
    'CV_SUPPLEMENTARY',
    'CV_FULL_TEXT',
    'SingletonService',
]
