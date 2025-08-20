import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
from platformdirs import user_data_dir

class Database:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            app_dir = Path(user_data_dir("Carapace", appauthor=False))
            app_dir.mkdir(parents=True, exist_ok=True)
            db_path = app_dir / "app.db"
        
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        cursor = self.conn.cursor()
        
        # Settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Sources table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE,
                url TEXT,
                etag TEXT,
                last_modified TEXT,
                content_hash TEXT,
                last_checked_utc TEXT
            )
        """)
        
        # Addons table with soft delete
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS addons (
                id INTEGER PRIMARY KEY,
                name TEXT,
                repo_url TEXT,
                override_url TEXT,
                status TEXT CHECK(status IN ('active','broken','missing','unstable')),
                host TEXT CHECK(host IN ('github','gitlab','bitbucket','other')),
                description TEXT,
                homepage_url TEXT,
                license TEXT,
                category TEXT,
                compatible_client TEXT,
                latest_version TEXT,
                install_method TEXT,
                tags TEXT,  -- JSON array of tags
                created_at_utc TEXT,
                updated_at_utc TEXT,
                deleted_at_utc TEXT DEFAULT NULL,
                UNIQUE(name, repo_url)
            )
        """)
        
        # Installed addons table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS installed (
                id INTEGER PRIMARY KEY,
                name TEXT,
                version TEXT,
                path TEXT,
                installed_at_utc TEXT,
                last_update_utc TEXT,
                enabled INTEGER DEFAULT 1,
                source_repo_url TEXT,
                deleted_at_utc TEXT DEFAULT NULL
            )
        """)
        
        # Themes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS themes (
                name TEXT PRIMARY KEY,
                file TEXT,
                preview_ascii TEXT,
                deleted_at_utc TEXT DEFAULT NULL
            )
        """)
        
        # Events audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                ts_utc TEXT,
                kind TEXT,
                addon_name TEXT,
                details_json TEXT
            )
        """)
        
        # Addon history tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS addon_history (
                id INTEGER PRIMARY KEY,
                addon_id INTEGER,
                ts_utc TEXT,
                field TEXT,
                old_value TEXT,
                new_value TEXT
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_addons_repo_url ON addons(repo_url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_installed_name ON installed(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_utc)")
        
        self.conn.commit()
    
    def upsert_addon(self, addon_data: Dict[str, Any]) -> int:
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        
        # Convert tags list to JSON
        if 'tags' in addon_data and isinstance(addon_data['tags'], list):
            addon_data['tags'] = json.dumps(addon_data['tags'])
        
        # Check if addon exists
        cursor.execute("""
            SELECT id, name, repo_url, description, tags FROM addons 
            WHERE name = ? AND (repo_url = ? OR repo_url IS NULL)
        """, (addon_data['name'], addon_data.get('repo_url')))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing addon
            addon_id = existing['id']
            changes = []
            
            # Track changes for history
            for field in ['description', 'tags', 'repo_url']:
                old_val = existing[field]
                new_val = addon_data.get(field)
                if old_val != new_val:
                    changes.append((addon_id, now, field, old_val, new_val))
            
            # Update addon
            cursor.execute("""
                UPDATE addons SET
                    repo_url = ?,
                    description = ?,
                    tags = ?,
                    updated_at_utc = ?
                WHERE id = ?
            """, (
                addon_data.get('repo_url'),
                addon_data.get('description'),
                addon_data.get('tags'),
                now,
                addon_id
            ))
            
            # Insert history records
            if changes:
                cursor.executemany("""
                    INSERT INTO addon_history (addon_id, ts_utc, field, old_value, new_value)
                    VALUES (?, ?, ?, ?, ?)
                """, changes)
        else:
            # Insert new addon
            cursor.execute("""
                INSERT INTO addons (
                    name, repo_url, host, description, tags,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                addon_data['name'],
                addon_data.get('repo_url'),
                self._detect_host(addon_data.get('repo_url', '')),
                addon_data.get('description'),
                addon_data.get('tags'),
                now,
                now
            ))
            addon_id = cursor.lastrowid
        
        self.conn.commit()
        return addon_id
    
    def _detect_host(self, repo_url: str) -> str:
        if not repo_url:
            return 'other'
        url_lower = repo_url.lower()
        if 'github.com' in url_lower:
            return 'github'
        elif 'gitlab.com' in url_lower:
            return 'gitlab'
        elif 'bitbucket.org' in url_lower:
            return 'bitbucket'
        return 'other'
    
    def get_addons(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        query = "SELECT * FROM addons"
        if not include_deleted:
            query += " WHERE deleted_at_utc IS NULL"
        
        cursor.execute(query)
        addons = []
        for row in cursor.fetchall():
            addon = dict(row)
            # Parse tags JSON back to list
            if addon.get('tags'):
                addon['tags'] = json.loads(addon['tags'])
            addons.append(addon)
        return addons
    
    def log_event(self, kind: str, addon_name: str = None, details: Dict = None):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO events (ts_utc, kind, addon_name, details_json)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            kind,
            addon_name,
            json.dumps(details) if details else None
        ))
        self.conn.commit()
    
    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        return result['value'] if result else default
    
    def set_setting(self, key: str, value: str):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        """, (key, value))
        self.conn.commit()
    
    def set_addon_override_url(self, addon_name: str, override_url: str):
        """Set an override URL for an addon"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE addons 
            SET override_url = ?
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (override_url, addon_name))
        self.conn.commit()
    
    def set_addon_status(self, addon_name: str, status: str):
        """Set addon status (active, broken, missing, unstable)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE addons 
            SET status = ?
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (status, addon_name))
        self.conn.commit()
    
    def get_broken_addons(self) -> List[Dict[str, Any]]:
        """Get all addons marked as broken or without valid URLs"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM addons 
            WHERE deleted_at_utc IS NULL 
            AND (status = 'broken' OR repo_url IS NULL OR repo_url = '')
            ORDER BY name
        """)
        addons = []
        for row in cursor.fetchall():
            addon = dict(row)
            if addon.get('tags'):
                addon['tags'] = json.loads(addon['tags'])
            addons.append(addon)
        return addons
    
    def get_addon_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a single addon by name"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM addons 
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (name,))
        row = cursor.fetchone()
        if row:
            addon = dict(row)
            if addon.get('tags'):
                addon['tags'] = json.loads(addon['tags'])
            return addon
        return None
    
    def close(self):
        self.conn.close()