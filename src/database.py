import sqlite3
import os
import src.config as config
from contextlib import contextmanager

@contextmanager
def get_connection():
    db_path = config.DB_PATH
    
    is_test = "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("IS_PYTEST") == "1"
    if is_test and ("data/radar.db" in db_path or db_path == "data/radar.db"):
        raise RuntimeError(f"CRITICAL SAFETY ERROR: Test suite is attempting to connect to production database: {db_path}")
        
    os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        with conn:
            yield conn
    finally:
        conn.close()

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
        if 'classified_tags' not in columns:
            cursor.execute("ALTER TABLE gsoc_projects ADD COLUMN classified_tags TEXT")

        cursor.execute("PRAGMA table_info(organizations)")
        org_columns = [col[1] for col in cursor.fetchall()]
        if 'github_account' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN github_account TEXT")
        if 'opportunity_score' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN opportunity_score REAL")
        if 'score_breakdown' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN score_breakdown TEXT")
        if 'is_verified_github' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN is_verified_github BOOLEAN DEFAULT 0")
        if 'opportunity_confidence' not in org_columns:
            cursor.execute("ALTER TABLE organizations ADD COLUMN opportunity_confidence TEXT")
            
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
        new_repo_cols = [
            'stars', 'forks', 'open_issues', 'open_prs', 'last_pushed_at', 'primary_language', 'archived', 'default_branch',
            'repo_classification', 'repo_eligibility', 'repo_classification_evidence', 'upstream_repo', 'upstream_confidence'
        ]
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
        
        # Pull Requests
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS pull_requests (
            pr_number INTEGER,
            repo_name TEXT,
            title TEXT,
            state TEXT,
            created_at TEXT,
            updated_at TEXT,
            merged_at TEXT,
            author TEXT,
            review_comments_count INTEGER,
            url TEXT PRIMARY KEY,
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
        
        # Migration: Add columns to issues if they do not exist
        cursor.execute("PRAGMA table_info(issues)")
        issue_columns = [col[1] for col in cursor.fetchall()]
        if 'org_slug' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN org_slug TEXT")
        if 'issue_number' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN issue_number INTEGER")
        if 'state' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN state TEXT")
        if 'updated_at' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN updated_at TEXT")
        if 'comments_count' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN comments_count INTEGER DEFAULT 0")
        if 'author' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN author TEXT")
        if 'assignee_status' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN assignee_status TEXT")
        if 'milestone' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN milestone TEXT")
        if 'classified_tags' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN classified_tags TEXT")
        if 'opportunity_score' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN opportunity_score REAL")
        if 'activity_status' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN activity_status TEXT")
        if 'issue_quality' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN issue_quality TEXT")
        if 'contribution_type' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN contribution_type TEXT")
        if 'engineering_depth' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN engineering_depth TEXT")
        if 'gsoc_preparation_score' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN gsoc_preparation_score REAL")
        if 'contribution_value_score' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN contribution_value_score REAL")
            
        # Milestone 9: Opportunity Memory
        if 'first_seen_at' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN first_seen_at TIMESTAMP")
        if 'last_seen_at' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN last_seen_at TIMESTAMP")
        if 'lifecycle_status' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN lifecycle_status TEXT DEFAULT 'NEW'")
        if 'previous_score' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN previous_score REAL")
        if 'current_score' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN current_score REAL")
        if 'score_delta' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN score_delta REAL")
        if 'first_recommended_at' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN first_recommended_at TIMESTAMP")
        if 'last_recommended_at' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN last_recommended_at TIMESTAMP")
        if 'viewed' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN viewed BOOLEAN DEFAULT 0")
        if 'researched' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN researched BOOLEAN DEFAULT 0")
        if 'planned' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN planned BOOLEAN DEFAULT 0")
        if 'implemented' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN implemented BOOLEAN DEFAULT 0")
        if 'submitted' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN submitted BOOLEAN DEFAULT 0")
        if 'merged' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN merged BOOLEAN DEFAULT 0")
        if 'dismissed' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN dismissed BOOLEAN DEFAULT 0")
        if 'dismissal_reason' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN dismissal_reason TEXT")
        
        # Milestone 10 Correction: Eligibility Gate
        if 'eligibility_status' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN eligibility_status TEXT DEFAULT 'UNKNOWN'")
            
        # Milestone 11: Real Contribution Selection
        if 'first_contribution_score' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN first_contribution_score REAL")
        if 'first_contribution_notes' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN first_contribution_notes TEXT")
        if 'readiness_status' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN readiness_status TEXT DEFAULT 'UNKNOWN'")
        if 'readiness_evidence' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN readiness_evidence TEXT")
        
        # Anti-spam & Personal Learning
        if 'cooldown_until' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN cooldown_until TIMESTAMP")
        if 'user_difficulty' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN user_difficulty TEXT")
        if 'user_notes' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN user_notes TEXT")
        if 'skills_learned' not in issue_columns:
            cursor.execute("ALTER TABLE issues ADD COLUMN skills_learned TEXT")
            
        # Repository Analysis
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS repository_analysis (
            repo_name TEXT PRIMARY KEY,
            has_readme BOOLEAN,
            has_contributing BOOLEAN,
            has_code_of_conduct BOOLEAN,
            description TEXT,
            test_frameworks TEXT,
            build_systems TEXT,
            pr_patterns TEXT,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

def update_organization_score(slug, score, breakdown, github_account=None, is_verified=False, confidence=None):
    import json
    with get_connection() as conn:
        cursor = conn.cursor()
        if github_account:
            cursor.execute('''
            UPDATE organizations SET opportunity_score = ?, score_breakdown = ?, github_account = ?, is_verified_github = ?, opportunity_confidence = ? WHERE slug = ?
            ''', (score, json.dumps(breakdown), github_account, is_verified, confidence, slug))
        else:
            cursor.execute('''
            UPDATE organizations SET opportunity_score = ?, score_breakdown = ?, is_verified_github = ?, opportunity_confidence = ? WHERE slug = ?
            ''', (score, json.dumps(breakdown), is_verified, confidence, slug))
        conn.commit()

def save_gsoc_project(org_slug, year, title, description, short_description, contributor, url, code_url, technologies, classified_tags=None):
    import json
    tags_str = json.dumps(classified_tags) if classified_tags else None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO gsoc_projects (org_slug, year, title, description, short_description, contributor, url, code_url, technologies, classified_tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(org_slug, year, title) DO UPDATE SET
            description=excluded.description,
            short_description=excluded.short_description,
            contributor=excluded.contributor,
            url=excluded.url,
            code_url=excluded.code_url,
            technologies=excluded.technologies,
            classified_tags=excluded.classified_tags
        ''', (org_slug, year, title, description, short_description, contributor, url, code_url, technologies, tags_str))
        conn.commit()

def save_issue(url, repo_name, org_slug, issue_number, title, created_at, updated_at, state, labels, body_preview, comments_count, author, assignee_status, milestone, classified_tags=None):
    import json
    tags_str = json.dumps(classified_tags) if classified_tags else None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO issues (url, repo_name, org_slug, issue_number, title, created_at, updated_at, state, labels, body_preview, comments_count, author, assignee_status, milestone, classified_tags, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            updated_at=excluded.updated_at,
            state=excluded.state,
            labels=excluded.labels,
            body_preview=excluded.body_preview,
            comments_count=excluded.comments_count,
            assignee_status=excluded.assignee_status,
            milestone=excluded.milestone,
            classified_tags=excluded.classified_tags,
            last_seen_at=CURRENT_TIMESTAMP
        ''', (url, repo_name, org_slug, issue_number, title, created_at, updated_at, state, labels, body_preview, comments_count, author, assignee_status, milestone, tags_str))
        conn.commit()

def save_pull_request(url, pr_number, repo_name, title, state, created_at, updated_at, merged_at, author, review_comments_count):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO pull_requests (url, pr_number, repo_name, title, state, created_at, updated_at, merged_at, author, review_comments_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            state=excluded.state,
            updated_at=excluded.updated_at,
            merged_at=excluded.merged_at,
            review_comments_count=excluded.review_comments_count
        ''', (url, pr_number, repo_name, title, state, created_at, updated_at, merged_at, author, review_comments_count))
        conn.commit()

def update_issue_opportunity(url, score, activity_status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE issues SET 
            previous_score = COALESCE(current_score, opportunity_score),
            current_score = ?,
            score_delta = ? - COALESCE(current_score, opportunity_score),
            opportunity_score = ?,
            activity_status = ?
        WHERE url = ?
        ''', (score, score, score, activity_status, url))
        
        # Reset cooldown if score delta is significant
        cursor.execute('''
        UPDATE issues SET cooldown_until = NULL
        WHERE url = ? AND (score_delta > 1.0 OR score_delta < -1.0)
        ''', (url,))
        
        conn.commit()

def update_issue_deep_analysis(url, issue_quality, contribution_type, engineering_depth, gsoc_score, contribution_score):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE issues SET 
            issue_quality = ?,
            contribution_type = ?,
            engineering_depth = ?,
            gsoc_preparation_score = ?,
            contribution_value_score = ?
        WHERE url = ?
        ''', (issue_quality, contribution_type, engineering_depth, gsoc_score, contribution_score, url))
        conn.commit()

def update_eligibility_status(url, eligibility_status):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE issues SET eligibility_status = ? WHERE url = ?
        ''', (eligibility_status, url))
        conn.commit()

def update_first_contribution_score(url, score, notes):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE issues SET first_contribution_score = ?, first_contribution_notes = ? WHERE url = ?
        ''', (score, notes, url))
        conn.commit()

def update_readiness_status(url, status, evidence):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE issues SET readiness_status = ?, readiness_evidence = ? WHERE url = ?
        ''', (status, evidence, url))
        conn.commit()

def save_repository_analysis(repo_name, has_readme, has_contributing, has_code_of_conduct, description, test_frameworks, build_systems, pr_patterns):
    import json
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO repository_analysis (repo_name, has_readme, has_contributing, has_code_of_conduct, description, test_frameworks, build_systems, pr_patterns)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(repo_name) DO UPDATE SET
            has_readme=excluded.has_readme,
            has_contributing=excluded.has_contributing,
            has_code_of_conduct=excluded.has_code_of_conduct,
            description=excluded.description,
            test_frameworks=excluded.test_frameworks,
            build_systems=excluded.build_systems,
            pr_patterns=excluded.pr_patterns,
            analyzed_at=CURRENT_TIMESTAMP
        ''', (repo_name, has_readme, has_contributing, has_code_of_conduct, description, 
              json.dumps(test_frameworks), json.dumps(build_systems), json.dumps(pr_patterns)))
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

def update_repository_classification(repo_name, classification, eligibility, evidence, upstream_repo=None, upstream_confidence=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE repositories
            SET repo_classification = ?,
                repo_eligibility = ?,
                repo_classification_evidence = ?,
                upstream_repo = ?,
                upstream_confidence = ?
            WHERE name = ?
        ''', (classification, eligibility, evidence, upstream_repo, upstream_confidence, repo_name))
        conn.commit()
