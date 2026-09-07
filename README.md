# OSS Discovery Radar

OSS Discovery Radar is a local automation engine that discovers open-source issues and provides a data-backed Google Summer of Code (GSoC) intelligence system.

## Project Architecture
- **GitHub Client**: Fetches unassigned issues labeled "good first issue", "help wanted", "bug", or "documentation" from target organizations using the GitHub GraphQL API.
- **Triage Engine**: Persists fetched issues and repositories and generates a cleanly structured Markdown digest highlighting high-priority tasks.
- **Database Layer (`src/database.py`)**: Uses SQLite to persist fetched organizations, GSoC year mappings, repositories, and issues idempotently.
- **GSoC Collector (`src/gsoc_collector.py`)**: Ingests historical GSoC organization data directly from the official GSoC API archives (2022-2026). 

## Database Purpose
The local database (`data/radar.db`) serves as the core intelligence persistence layer for the application. It ensures data isn't duplicated across runs (using idempotent constraints) and supports building a rich historical knowledge base mapping GSoC organizations across various years to their respective repositories and open issues.

## Setup
1. Clone the repository and navigate to the root directory.
2. Ensure you have Python 3 installed.
3. Set up the virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Configure your environment:
   ```bash
   cp .env.example .env
   # Ensure you have a GitHub token either in .env or via `gh auth login`
   ```

## Commands
The radar operates through subcommands:
- `python main.py issues`: Runs the GitHub pipeline, fetches open issues, saves them to the database, and outputs a digest in `digests/`.
- `python main.py gsoc`: Fetches historical GSoC organization data for the configured years and stores it in the database.
- `python main.py status`: Prints current statistics about the populated database.

## Data Sources
- **GitHub GraphQL API**: Primary source for repository issues.
- **Google Summer of Code API** (`summerofcode.withgoogle.com/api/program/`): Primary authoritative source for historical participating organizations.

## Current Limitations
- **GSoC Projects**: The official Google API heavily restricts direct fetching of project endpoints for archived years, returning HTTP 403 Forbidden. Therefore, the GSoC collector currently primarily ingests **organization** data across multiple years.
- **Search Complexity**: Due to limitations in the GitHub Search API logic, complex logical `OR` conditions for organizations must be handled sequentially (via a loop) rather than bundled into a single GraphQL query.
