import os
import subprocess
from dotenv import load_dotenv

load_dotenv()

def get_github_token():
    # First check if it's set in the environment or .env
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token
    
    # Fallback to GitHub CLI
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None
    except FileNotFoundError:
        # gh CLI not installed
        return None

GITHUB_TOKEN = get_github_token()

# Milestone 2 Configs
DB_PATH = os.getenv("DB_PATH", "data/radar.db")
PROFILE_PATH = os.getenv("PROFILE_PATH", "config/profile.yaml")
ORG_ALIASES_PATH = os.getenv("ORG_ALIASES_PATH", "config/org_aliases.yaml")
GSOC_YEARS_ENV = os.getenv("GSOC_YEARS", "2022,2023,2024,2025,2026")
GSOC_YEARS = [int(y.strip()) for y in GSOC_YEARS_ENV.split(",") if y.strip().isdigit()]
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 30))
MAX_REPOS_PER_ORG = int(os.getenv("MAX_REPOS_PER_ORG", 20))
ENRICH_ORG_BATCH_SIZE = int(os.getenv("ENRICH_ORG_BATCH_SIZE", 25))

TARGET_ORGANIZATIONS = [
    "jenkins-infra",
    "cloudnative",
    "owasp",
    "scipy",
    "kubernetes"
]

GRAPHQL_API_URL = "https://api.github.com/graphql"
