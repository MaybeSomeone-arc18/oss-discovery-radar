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
            contributor TEXT,
            url TEXT,
            technologies TEXT,
            FOREIGN KEY (org_slug) REFERENCES organizations(slug),
            UNIQUE(org_slug, year, title)
        )
        ''')
        
        # Repositories
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS repositories (
            name TEXT PRIMARY KEY,
            org_slug TEXT,
            url TEXT,
            FOREIGN KEY (org_slug) REFERENCES organizations(slug)
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

def save_repository(name, url, org_slug=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO repositories (name, url, org_slug)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            url=excluded.url,
            org_slug=COALESCE(excluded.org_slug, repositories.org_slug)
        ''', (name, url, org_slug))
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
