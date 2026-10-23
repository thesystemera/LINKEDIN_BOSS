# GEMINI.md

This file provides guidance to Gemini CLI when working with code in this repository.

## Project Overview

LinkedIn Auto-Apply automation bot that scrapes LinkedIn Easy Apply jobs, evaluates them with Gemini AI, and automatically submits applications.

## Engineering Standards

- **Contextual Precedence**: This `GEMINI.md` file takes absolute precedence over general workflows.
- **Conventions & Style**: Adhere to existing patterns. Use `src/services/cv_data.py` as the single source of truth for user profile data.
- **Technical Integrity**: prioritize readability and maintainability. Align with the requested architectural direction.
- **Testing**: No test suite exists. Testing is done manually via dry runs. For new features or fixes, verify via manual scripts or dry runs.
- **Validation**: Always verify changes by running relevant commands (e.g., `python src/main.py stats` or specific service tests).

## Primary Workflows

### Development Lifecycle
1. **Research**: Map the codebase and validate assumptions.
2. **Strategy**: Formulate a grounded plan.
3. **Execution**: Iterative Plan -> Act -> Validate cycle.
    - **Plan**: Define implementation and testing strategy.
    - **Act**: Apply targeted, surgical changes.
    - **Validate**: Run tests and confirm success.

## Database Access

- **SQLite**: `data/applications.db`
- **Tables**: `jobs`, `evaluations`, `applications`, `daily_stats`.
- **Querying**: Use raw SQL via `sqlite3`.

## Critical Files

- `src/config.py`: Central configuration.
- `src/services/cv_data.py`: User profile and CV data.
- `src/main.py`: Entry point for the application.
- `src/services/database.py`: Database interaction logic.

## Summary Generation Task

- The user wants a condensed summary of applied jobs (1000+ jobs) over about 5-6 pages.
- Summarize by date and status.
- Focus on "success" applications.
- Output should be a very quick summary suitable for printing.

## Operational Rules

- **Explain Before Acting**: Provide a concise explanation of intent before executing tool calls.
- **No Chitchat**: Maintain a professional, direct, and concise tone.
- **Security First**: Never log or commit secrets. API keys are in `src/keys/`.
- **Parallelism**: Use parallel tool calls when feasible.
