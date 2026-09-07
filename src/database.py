import sqlite3
import os
from src.config import DB_PATH

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Organizations
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS organizations (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT,
            year_first_seen INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # GSoC Years mapping
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS gsoc_years (
            org_slug TEXT,
            year INTEGER,
            PRIMARY KEY (org_slug, year),
            FOREIGN KEY (org_slug) REFERENCES organizations(slug)
        )
        ''')
        
        # GSoC Projects
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS gsoc_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_slug TEXT,
            year INTEGER,
            title TEXT,
            description TEXT,
            short_description TEXT,
            contributor TEXT,
            url TEXT,
            code_url TEXT,
            technologies TEXT,
            FOREIGN KEY (org_slug) REFERENCES organizations(slug),
            UNIQUE(org_slug, year, title)
        )
        ''')
        
        # Migration: Add columns if they do not exist
        cursor.execute("PRAGMA table_info(gsoc_projects)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'short_description' not in columns:
            cursor.execute("ALTER TABLE gsoc_projects ADD COLUMN short_description TEXT")
        if 'code_url' not in columns:
            cursor.execute("ALTER TABLE gsoc_projects ADD COLUMN code_url TEXT")

        cursor.execute("PRAGMA table_info(organizations)")
        org_columns = [col[1] for col in cursor.fetchall()]
        if 'github_account' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN github_account TEXT")
        if 'opportunity_score' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN opportunity_score REAL")
        if 'score_breakdown' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN score_breakdown TEXT")
            
        # Repositories
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS repositories (
            name TEXT PRIMARY KEY,
            org_slug TEXT,
            url TEXT,
            FOREIGN KEY (org_slug) REFERENCES organizations(slug)
        )
        ''')

        cursor.execute("PRAGMA table_info(repositories)")
        repo_columns = [col[1] for col in cursor.fetchall()]
        new_repo_cols = ['stars', 'forks', 'open_issues', 'open_prs', 'last_pushed_at', 'primary_language', 'archived', 'default_branch']
        for col in new_repo_cols:
            if col not in repo_columns:
                cursor.execute(f"ALTER TABLE repositories ADD COLUMN {col} TEXT")

        # Repository Metrics (Intelligence)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS repository_metrics (
            repo_name TEXT PRIMARY KEY,
            issues_created_recently INTEGER DEFAULT 0,
            issues_closed_recently INTEGER DEFAULT 0,
            prs_opened_recently INTEGER DEFAULT 0,
            prs_merged_recently INTEGER DEFAULT 0,
            prs_external INTEGER DEFAULT 0,
            recent_commits INTEGER DEFAULT 0,
            maintainer_response_time_hours REAL,
            review_merge_activity_score REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_name) REFERENCES repositories(name)
        )
        ''')
        
        # Issues
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS issues (
            url TEXT PRIMARY KEY,
            repo_name TEXT,
            title TEXT,
            created_at TEXT,
            labels TEXT,
            body_preview TEXT,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_name) REFERENCES repositories(name)
        )
        ''')
        conn.commit()

def save_organization(slug, name, url=None, year=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO organizations (slug, name, url, year_first_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            name=excluded.name,
            url=COALESCE(excluded.url, organizations.url),
            year_first_seen=COALESCE(organizations.year_first_seen, excluded.year_first_seen)
        ''', (slug, name, url, year))
        
        if year:
            cursor.execute('''
            INSERT OR IGNORE INTO gsoc_years (org_slug, year)
            VALUES (?, ?)
            ''', (slug, year))
        conn.commit()

def save_repository(name, url, org_slug=None, stars=0, forks=0, open_issues=0, open_prs=0, last_pushed_at=None, primary_language=None, archived=False, default_branch=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO repositories (name, url, org_slug, stars, forks, open_issues, open_prs, last_pushed_at, primary_language, archived, default_branch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            url=excluded.url,
            org_slug=COALESCE(excluded.org_slug, repositories.org_slug),
            stars=excluded.stars,
            forks=excluded.forks,
            open_issues=excluded.open_issues,
            open_prs=excluded.open_prs,
            last_pushed_at=excluded.last_pushed_at,
            primary_language=excluded.primary_language,
            archived=excluded.archived,
            default_branch=excluded.default_branch
        ''', (name, url, org_slug, str(stars), str(forks), str(open_issues), str(open_prs), last_pushed_at, primary_language, str(archived), default_branch))
        conn.commit()

def save_repository_metrics(repo_name, issues_created, issues_closed, prs_opened, prs_merged, prs_external, recent_commits, maintainer_response_time, review_activity_score):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO repository_metrics (
            repo_name, issues_created_recently, issues_closed_recently, prs_opened_recently, 
            prs_merged_recently, prs_external, recent_commits, maintainer_response_time_hours, review_merge_activity_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo_name) DO UPDATE SET
            issues_created_recently=excluded.issues_created_recently,
            issues_closed_recently=excluded.issues_closed_recently,
            prs_opened_recently=excluded.prs_opened_recently,
            prs_merged_recently=excluded.prs_merged_recently,
            prs_external=excluded.prs_external,
            recent_commits=excluded.recent_commits,
            maintainer_response_time_hours=excluded.maintainer_response_time_hours,
            review_merge_activity_score=excluded.review_merge_activity_score,
            updated_at=CURRENT_TIMESTAMP
        ''', (repo_name, issues_created, issues_closed, prs_opened, prs_merged, prs_external, recent_commits, maintainer_response_time, review_activity_score))
        conn.commit()

def update_organization_score(slug, score, breakdown, github_account=None):
    import json
    with get_connection() as conn:
        cursor = conn.cursor()
        if github_account:
            cursor.execute('''
            UPDATE organizations SET opportunity_score = ?, score_breakdown = ?, github_account = ? WHERE slug = ?
            ''', (score, json.dumps(breakdown), github_account, slug))
        else:
            cursor.execute('''
            UPDATE organizations SET opportunity_score = ?, score_breakdown = ? WHERE slug = ?
            ''', (score, json.dumps(breakdown), slug))
        conn.commit()

def save_gsoc_project(org_slug, year, title, description, short_description, contributor, url, code_url, technologies):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO gsoc_projects (org_slug, year, title, description, short_description, contributor, url, code_url, technologies)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(org_slug, year, title) DO UPDATE SET
            description=excluded.description,
            short_description=excluded.short_description,
            contributor=excluded.contributor,
            url=excluded.url,
            code_url=excluded.code_url,
            technologies=excluded.technologies
        ''', (org_slug, year, title, description, short_description, contributor, url, code_url, technologies))
        conn.commit()

def save_issue(url, repo_name, title, created_at, labels, body_preview):
    with get_connection() as conn:
        cursor = conn.cursor()
        labels_str = ",".join(labels) if isinstance(labels, list) else labels
        cursor.execute('''
        INSERT INTO issues (url, repo_name, title, created_at, labels, body_preview)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            labels=excluded.labels,
            body_preview=excluded.body_preview
        ''', (url, repo_name, title, created_at, labels_str, body_preview))
        conn.commit()

def get_stats():
    stats = {}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM organizations")
        stats['organizations'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT year) FROM gsoc_years")
        stats['years'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM gsoc_projects")
        stats['projects'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM repositories")
        stats['repositories'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM issues")
        stats['issues'] = cursor.fetchone()[0]
    return stats
