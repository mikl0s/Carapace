"""
Database update checker and downloader for Carapace
"""

import os
import json
import logging
import requests
import hashlib
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class DatabaseUpdater:
    """Handles checking for and downloading database updates from GitHub"""
    
    # GitHub raw content URL for the public repository
    GITHUB_RAW_BASE = "https://raw.githubusercontent.com/mikl0s/Carapace/main"
    MANIFEST_URL = f"{GITHUB_RAW_BASE}/db/manifest.json"
    DATABASE_URL = f"{GITHUB_RAW_BASE}/db/carapace.db"
    
    def __init__(self, db_path: Path):
        """
        Initialize the updater
        
        Args:
            db_path: Path to the local database file
        """
        self.db_path = Path(db_path)
        self.db_dir = self.db_path.parent
        self.manifest_path = self.db_dir / "manifest.json"
        
        # Ensure db directory exists
        self.db_dir.mkdir(parents=True, exist_ok=True)
    
    def get_local_manifest(self) -> Optional[Dict[str, Any]]:
        """Get the local manifest if it exists"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read local manifest: {e}")
        return None
    
    def fetch_remote_manifest(self) -> Optional[Dict[str, Any]]:
        """Fetch the manifest from GitHub"""
        try:
            response = requests.get(self.MANIFEST_URL, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch remote manifest: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in remote manifest: {e}")
            return None
    
    def check_for_updates(self) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if a database update is available
        
        Returns:
            tuple: (update_available, remote_manifest)
        """
        # Get local manifest
        local_manifest = self.get_local_manifest()
        
        # Get remote manifest
        remote_manifest = self.fetch_remote_manifest()
        if not remote_manifest:
            logger.info("Could not fetch remote manifest")
            return False, None
        
        # If no local manifest or database, update is needed
        if not local_manifest or not self.db_path.exists():
            logger.info("No local database found, update needed")
            return True, remote_manifest
        
        # Compare versions
        local_version = local_manifest.get('version', 0)
        remote_version = remote_manifest.get('version', 0)
        
        if remote_version > local_version:
            logger.info(f"Update available: v{local_version} -> v{remote_version}")
            return True, remote_manifest
        
        logger.info(f"Database is up to date (v{local_version})")
        return False, remote_manifest
    
    def download_database(self, expected_checksum: str = None) -> bool:
        """
        Download the database from GitHub
        
        Args:
            expected_checksum: Expected SHA256 checksum of the database
            
        Returns:
            bool: True if download successful
        """
        try:
            # Download to temporary file
            temp_path = self.db_path.with_suffix('.tmp')
            
            logger.info(f"Downloading database from {self.DATABASE_URL}")
            response = requests.get(self.DATABASE_URL, stream=True, timeout=30)
            response.raise_for_status()
            
            # Write to temp file
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # Verify checksum if provided
            if expected_checksum:
                with open(temp_path, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                
                if file_hash != expected_checksum:
                    logger.error(f"Checksum mismatch! Expected: {expected_checksum}, Got: {file_hash}")
                    temp_path.unlink()
                    return False
                
                logger.info("Checksum verified successfully")
            
            # Backup existing database if it exists
            if self.db_path.exists():
                backup_path = self.db_path.with_suffix('.backup')
                shutil.copy2(self.db_path, backup_path)
                logger.info(f"Backed up existing database to {backup_path}")
            
            # Move temp file to final location
            shutil.move(str(temp_path), str(self.db_path))
            logger.info(f"Database downloaded successfully to {self.db_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download database: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error downloading database: {e}")
            return False
    
    def update_database(self) -> bool:
        """
        Check for and apply database updates
        
        Returns:
            bool: True if database was updated or is already up to date
        """
        update_available, remote_manifest = self.check_for_updates()
        
        if not update_available:
            return True
        
        if not remote_manifest:
            logger.error("Remote manifest not available")
            return False
        
        # Download the database
        checksum = remote_manifest.get('checksum')
        if not self.download_database(checksum):
            return False
        
        # Save the manifest
        try:
            with open(self.manifest_path, 'w') as f:
                json.dump(remote_manifest, f, indent=2)
            logger.info(f"Updated manifest to version {remote_manifest.get('version')}")
            return True
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")
            return False
    
    def get_database_info(self) -> Dict[str, Any]:
        """Get information about the current database"""
        info = {
            'exists': self.db_path.exists(),
            'path': str(self.db_path),
            'manifest_exists': self.manifest_path.exists()
        }
        
        if self.manifest_path.exists():
            manifest = self.get_local_manifest()
            if manifest:
                info.update({
                    'version': manifest.get('version'),
                    'addon_count': manifest.get('addon_count'),
                    'updated': manifest.get('updated'),
                    'wiki_revision': manifest.get('wiki_revision')
                })
        
        return info


def check_and_update_database(db_path: Path, force: bool = False) -> bool:
    """
    Convenience function to check and update database
    
    Args:
        db_path: Path to the database
        force: Force download even if up to date
        
    Returns:
        bool: True if successful
    """
    updater = DatabaseUpdater(db_path)
    
    if force:
        logger.info("Forcing database download...")
        remote_manifest = updater.fetch_remote_manifest()
        if remote_manifest:
            checksum = remote_manifest.get('checksum')
            if updater.download_database(checksum):
                with open(updater.manifest_path, 'w') as f:
                    json.dump(remote_manifest, f, indent=2)
                return True
        return False
    
    return updater.update_database()