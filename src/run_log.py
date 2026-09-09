from src.database import get_connection

def log_event(action: str, result: str, message: str, issue_id: int = None):
    """
    Logs an automated action to the audit_logs table.
    
    :param action: Action performed (e.g., 'sync', 'digest', 'hermes_research')
    :param result: Result of the action ('success', 'skipped', 'failed')
    :param message: Human-readable context or error message
    :param issue_id: Optional issue ID if the action is issue-specific
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO audit_logs (action, issue_id, result, message)
        VALUES (?, ?, ?, ?)
        ''', (action, issue_id, result, message))
        conn.commit()

def get_recent_logs(limit=50):
    """Returns the most recent audit logs."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT id, timestamp, action, issue_id, result, message 
        FROM audit_logs 
        ORDER BY timestamp DESC 
        LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
