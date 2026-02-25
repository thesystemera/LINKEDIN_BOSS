"""
CV Data - Single Source of Truth for your profile.

SETUP: Copy this file to cv_data.py and fill in YOUR information.
       cp src/services/cv_data_example.py src/services/cv_data.py

cv_data.py is gitignored - your personal data stays local.
"""

CV_SUPPLEMENTARY = {
    "role_preferences": {
        "instruction": "These are PREFERENCES, not hard requirements. Evaluate each role on its merits.",
        "preferred_levels": ["Staff Engineer", "Principal Engineer", "Lead Engineer", "Engineering Manager", "Technical Architect", "Solutions Architect"],
        "open_to": "Strong Senior roles at great companies with growth potential.",
        "context": "Describe your experience level and what you're looking for."
    },

    "salary_strategy": {
        "instruction": "Be intelligent about salary. NO hardcoded numbers - evaluate each role on its merits.",
        "rules": [
            "1. If the job listing states a salary range, answer within that range (upper half is reasonable)",
            "2. If asked for 'expected salary' with no range given, research what's fair for that specific role title + level + location",
            "3. Consider local market differences",
            "4. Consider company size and industry",
            "5. Consider role level: Junior < Mid < Senior < Staff < Principal < Director",
            "6. Don't undersell, but don't price yourself out either - aim for fair market rate"
        ],
        "format": "Always return a single whole number with no symbols (e.g. 150000, not $150k or 150,000)"
    },

    "target_locations": ["YOUR_CITY", "YOUR_COUNTRY", "Remote"],

    "background_context": {
        "instruction": "Provide full context beyond the formal CV. Use this to explain depth of experience.",
        "origin_story": {
            "summary": "Describe your background and how you got into tech.",
            "context": "What makes your background unique or interesting?"
        },
        "technology_timeline": {
            "note": "Describe how long you've been using key technologies and in what context."
        }
    },

    "technology_experience_years": {
        "instruction": "PROFESSIONAL work experience only. When asked 'How many years of work experience with X?', use these numbers.",
        "primary_languages": {
            "Python": "X years (describe usage)",
            "JavaScript": "X years (describe usage)",
            # Add your primary languages
        },
        "secondary_languages": {
            # Add secondary languages
        },
        "frameworks_platforms": {
            # Add frameworks/platforms
        },
        "note": "If asked about a technology NOT listed here, estimate conservatively or answer 0-1 if only peripheral exposure."
    },

    "supplementary_skills": {
        # List additional skills not on your CV
        "additional": [],
        "context": "Describe any other relevant skills or experience"
    },

    "supplementary_experience": {
        # Add any notable experiences or context
        "meta_automation": {
            "context": "Built custom AI-powered job application system (Playwright + Gemini) that extracts form fields, generates contextual answers, and optimizes application throughput.",
            "relevance": "Demonstrates end-to-end automation thinking, AI orchestration, and 'scratch your own itch' engineering philosophy"
        }
    },

    "contact_details": {
        "first_name": "YOUR_FIRST_NAME",
        "last_name": "YOUR_LAST_NAME",
        "email": "your.email@example.com",
        "phone": "+1234567890",
        "phone_number": "+1234567890",
        "mobile_phone_number": "+1234567890",
        "phone_country_code": "YOUR_COUNTRY (+XX)",
        "city": "YOUR_CITY",
        "location": "YOUR_CITY, YOUR_COUNTRY"
    },

    "residency_status": {
        "citizenship": "YOUR_CITIZENSHIP",
        "authorized_to_work": "Yes/No - describe your work authorization",
        "require_sponsorship": "Yes/No",
        "current_location": "YOUR_COUNTRY",
        "notice_period": "X weeks / Immediate",
        "willing_to_relocate": "Yes/No - describe your relocation preferences"
    },

    "profile_links": {
        "linkedin_url": "https://linkedin.com/in/YOUR_PROFILE",
        "github_url": "https://github.com/YOUR_USERNAME",
        "portfolio_url": "https://your-portfolio.com"
    }
}

CV_FULL_TEXT = """
YOUR FULL NAME
Your Title | Your Speciality
Your City, Your Country | your.linkedin.com/in/profile

PROFESSIONAL SUMMARY
Write a compelling summary of your background and what makes you unique.
Focus on your core strengths and what you bring to the table.

EXPERIENCE
Your Most Recent Role | Company Name
YYYY – Present
- Key achievement 1
- Key achievement 2
- Key achievement 3

Previous Role | Company Name
YYYY – YYYY
- Key achievement 1
- Key achievement 2

TECHNICAL SKILLS
List your key technical skills here.

EDUCATION
Your Degree | Your Institution | Year

HONOURS & RECOGNITION
Any awards, publications, or notable recognition.
"""
