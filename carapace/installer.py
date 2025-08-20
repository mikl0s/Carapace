"""
Addon installation and management
Based on GitAddonsManager approach
"""

import os
import stat
import zipfile
import shutil
import tempfile
import requests
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import logging
import re
import configparser
import json

from carapace.db import Database
from carapace.paths import get_addon_path

logger = logging.getLogger(__name__)

class AddonInstaller:
    """Handles addon installation, updates, and removal"""
    
    def __init__(self, db: Database):
        self.db = db
        self.addon_path = get_addon_path()
        # Cache for repo URL to addon name mapping
        self._repo_to_addon_cache = {}
        self._build_repo_cache()
    
    def _build_repo_cache(self):
        """Build a cache of repo URLs to addon names from the database"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT name, repo_url FROM addons 
            WHERE repo_url IS NOT NULL AND repo_url != ''
            AND deleted_at_utc IS NULL
        """)
        
        for row in cursor.fetchall():
            if row['repo_url']:
                # Normalize the URL for matching
                normalized_url = self._normalize_repo_url(row['repo_url'])
                self._repo_to_addon_cache[normalized_url] = row['name']
    
    def _normalize_repo_url(self, url: str) -> str:
        """Normalize a repository URL for comparison"""
        if not url:
            return ""
        
        # Remove protocol
        url = url.replace('https://', '').replace('http://', '').replace('git://', '')
        # Remove trailing .git
        url = url.rstrip('/').rstrip('.git')
        # Convert to lowercase
        url = url.lower()
        return url
    
    def _get_git_remote_url(self, addon_folder: Path) -> Optional[str]:
        """Extract the git remote URL from an addon folder's .git/config"""
        git_config = addon_folder / '.git' / 'config'
        if not git_config.exists():
            return None
        
        try:
            config = configparser.ConfigParser()
            config.read(git_config)
            
            # Look for [remote "origin"] section
            if 'remote "origin"' in config:
                url = config['remote "origin"'].get('url', '').strip()
                return url
            
            # Try alternative format
            for section in config.sections():
                if section.startswith('remote'):
                    url = config[section].get('url', '').strip()
                    if url:
                        return url
        except Exception as e:
            logger.debug(f"Error reading git config for {addon_folder.name}: {e}")
        
        return None
    
    def _match_by_folder_name(self, folder_name: str) -> Optional[str]:
        """Try to match addon by folder name using stored mappings"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT name, folder_names 
            FROM addons 
            WHERE folder_names IS NOT NULL 
            AND deleted_at_utc IS NULL
        """)
        
        for row in cursor.fetchall():
            addon_name, folders_json = row
            if folders_json:
                try:
                    folders = json.loads(folders_json)
                    if folder_name in folders:
                        return addon_name
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def get_installed_addons(self) -> Dict[str, Dict]:
        """Get all installed addons from database"""
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT name, version, path, installed_at_utc, source_repo_url, enabled
            FROM installed
            WHERE deleted_at_utc IS NULL
        """)
        
        installed = {}
        for row in cursor.fetchall():
            installed[row['name'].lower()] = {
                'name': row['name'],
                'version': row['version'],
                'path': row['path'],
                'installed_at': row['installed_at_utc'],
                'repo_url': row['source_repo_url'],
                'enabled': row['enabled'] if row['enabled'] is not None else 1  # Default to enabled
            }
        return installed
    
    def scan_addon_directory(self) -> Dict[str, Dict]:
        """
        Scan the addon directory for installed addons
        Returns: Dict of folder_name -> {has_toc, git_url, matched_addon}
        """
        if not self.addon_path or not self.addon_path.exists():
            return {}
        
        addon_info = {}
        for item in self.addon_path.iterdir():
            if item.is_dir():
                # Check for .toc file to confirm it's an addon
                toc_files = list(item.glob("*.toc"))
                if toc_files:
                    # Get git remote URL if available
                    git_url = self._get_git_remote_url(item)
                    
                    # Try to match with known addon
                    matched_addon = None
                    
                    # First try git URL matching
                    if git_url:
                        normalized_url = self._normalize_repo_url(git_url)
                        matched_addon = self._repo_to_addon_cache.get(normalized_url)
                    
                    # If no git match, try folder name matching
                    if not matched_addon:
                        matched_addon = self._match_by_folder_name(item.name)
                    
                    addon_info[item.name] = {
                        'has_toc': True,
                        'git_url': git_url,
                        'matched_addon': matched_addon,
                        'path': str(item)
                    }
                    
                    if matched_addon:
                        logger.info(f"Matched {item.name} -> {matched_addon} via git URL")
        
        return addon_info
    
    def sync_installed_state(self) -> Tuple[int, int]:
        """
        Sync installed addon state with actual filesystem
        Returns: (newly_found, removed)
        """
        if not self.addon_path:
            return 0, 0
        
        # Get what's in the database
        db_installed = self.get_installed_addons()
        
        # Scan what's actually on disk with git URL matching
        disk_addons = self.scan_addon_directory()
        
        newly_found = 0
        removed = 0
        now = datetime.utcnow().isoformat()
        cursor = self.db.conn.cursor()
        
        # Process addons found on disk
        for folder_name, info in disk_addons.items():
            addon_name = info['matched_addon'] or folder_name
            addon_key = addon_name.lower()
            
            if addon_key not in db_installed:
                # Add to installed table
                cursor.execute("""
                    INSERT INTO installed (name, version, path, installed_at_utc, 
                                         enabled, source_repo_url)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (addon_name, "unknown", info['path'], now, info['git_url'] or ''))
                newly_found += 1
                logger.info(f"Found addon: {addon_name} (folder: {folder_name})")
            else:
                # Update the path and repo URL if we have better info
                if info['git_url'] and info['matched_addon']:
                    cursor.execute("""
                        UPDATE installed
                        SET path = ?, source_repo_url = ?
                        WHERE name = ? AND deleted_at_utc IS NULL
                    """, (info['path'], info['git_url'], addon_name))
        
        # Check for removed addons
        for addon_key, addon_info in db_installed.items():
            addon_path = Path(addon_info['path'])
            if not addon_path.exists():
                # Mark as deleted
                cursor.execute("""
                    UPDATE installed
                    SET deleted_at_utc = ?
                    WHERE name = ? AND deleted_at_utc IS NULL
                """, (now, addon_info['name']))
                removed += 1
                logger.info(f"Addon no longer exists: {addon_info['name']}")
        
        if newly_found > 0 or removed > 0:
            self.db.conn.commit()
        
        return newly_found, removed
    
    def is_installed(self, addon_name: str) -> bool:
        """Check if an addon is installed"""
        installed = self.get_installed_addons()
        return addon_name.lower() in installed
    
    def get_installed_version(self, addon_name: str) -> Optional[str]:
        """Get the installed version of an addon"""
        installed = self.get_installed_addons()
        addon = installed.get(addon_name.lower())
        return addon['version'] if addon else None
    
    def set_override_url(self, addon_name: str, override_url: str) -> bool:
        """Set an override repository URL for an addon"""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                UPDATE addons 
                SET override_url = ?
                WHERE name = ?
            """, (override_url, addon_name))
            self.db.conn.commit()
            logger.info(f"Set override URL for {addon_name}: {override_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to set override URL: {e}")
            return False
    
    def mark_installed(self, addon_name: str, version: str = "unknown", 
                      repo_url: str = "", path: str = ""):
        """Mark an addon as installed in the database"""
        now = datetime.utcnow().isoformat()
        cursor = self.db.conn.cursor()
        
        # Check if already exists
        cursor.execute("""
            SELECT id FROM installed 
            WHERE name = ? AND deleted_at_utc IS NULL
        """, (addon_name,))
        
        existing = cursor.fetchone()
        if existing:
            # Update existing
            cursor.execute("""
                UPDATE installed
                SET version = ?, last_update_utc = ?, source_repo_url = ?
                WHERE id = ?
            """, (version, now, repo_url, existing['id']))
        else:
            # Insert new
            if not path and self.addon_path:
                path = str(self.addon_path / addon_name)
            
            cursor.execute("""
                INSERT INTO installed (name, version, path, installed_at_utc, 
                                     enabled, source_repo_url)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (addon_name, version, path, now, repo_url))
        
        self.db.conn.commit()
        self.db.log_event("addon_installed", addon_name=addon_name, 
                         details={"version": version})
    
    def _get_github_release_url(self, repo_url: str) -> Optional[str]:
        """Get the latest release download URL from GitHub/GitLab"""
        if not repo_url:
            return None
        
        # Parse GitHub URL
        if 'github.com' in repo_url:
            match = re.search(r'github\.com/([^/]+)/([^/]+)', repo_url)
            if match:
                owner, repo = match.groups()
                # Remove .git extension if present (but only the extension, not the letters)
                if repo.endswith('.git'):
                    repo = repo[:-4]
                
                # Try to get latest release
                api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
                try:
                    response = requests.get(api_url, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        # Look for zip assets
                        for asset in data.get('assets', []):
                            if asset['name'].endswith('.zip'):
                                return asset['browser_download_url']
                        # Fallback to zipball
                        return data.get('zipball_url')
                except Exception as e:
                    logger.debug(f"Could not get release for {repo_url}: {e}")
                
                # Fallback to archive of default branch
                return f"https://github.com/{owner}/{repo}/archive/refs/heads/master.zip"
        
        # Parse GitLab URL
        elif 'gitlab.com' in repo_url:
            match = re.search(r'gitlab\.com/([^/]+)/([^/]+)', repo_url)
            if match:
                owner, repo = match.groups()
                # Remove .git extension if present (but only the extension, not the letters)
                if repo.endswith('.git'):
                    repo = repo[:-4]
                # GitLab archive
                return f"https://gitlab.com/{owner}/{repo}/-/archive/master/{repo}-master.zip"
        
        return None
    
    def _download_addon(self, url: str, temp_dir: Path) -> Path:
        """Download addon zip to temp directory"""
        logger.info(f"Downloading from {url}")
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        # Save to temp file
        zip_path = temp_dir / "addon.zip"
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return zip_path
    
    def _find_toc_files(self, extract_dir: Path) -> List[Path]:
        """Find all .toc files in extracted directory"""
        return list(extract_dir.rglob("*.toc"))
    
    def _get_addon_folders(self, extract_dir: Path) -> List[Tuple[str, Path]]:
        """
        Detect addon folders from extracted zip
        Returns: List of (addon_name, source_path) tuples
        """
        toc_files = self._find_toc_files(extract_dir)
        if not toc_files:
            return []
        
        addon_folders = []
        seen_folders = set()  # Track which folders we've already added
        
        for toc_file in toc_files:
            # The parent of the .toc file is the addon folder
            addon_folder = toc_file.parent
            addon_name = addon_folder.name
            
            # Skip if we've already processed this folder
            if str(addon_folder) in seen_folders:
                continue
            
            # Skip common library folders that are nested inside other addons
            if addon_name in ('Libs', 'libs', 'Libraries'):
                continue
            
            # Check if this is likely a valid addon folder
            # Valid addon folders have .toc files that match the folder name
            # or are common addon .toc patterns
            toc_name = toc_file.stem  # filename without extension
            
            # Add the addon folder - we now scan all depths
            addon_folders.append((addon_name, addon_folder))
            seen_folders.add(str(addon_folder))
            logger.debug(f"Found addon folder: {addon_name} at {addon_folder.relative_to(extract_dir)}")
        
        # If no addons found, log the structure for debugging
        if not addon_folders:
            logger.error("No addon folders found. Directory structure:")
            for item in extract_dir.rglob("*"):
                if item.is_file():
                    logger.error(f"  {item.relative_to(extract_dir)}")
        
        return addon_folders
    
    def _get_addon_version(self, addon_folder: Path) -> str:
        """Extract version from .toc file"""
        toc_files = list(addon_folder.glob("*.toc"))
        if not toc_files:
            return "unknown"
        
        try:
            with open(toc_files[0], 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.startswith('## Version:'):
                        return line.split(':', 1)[1].strip()
        except Exception as e:
            logger.debug(f"Could not read version from .toc: {e}")
        
        return "unknown"
    
    def _scan_git_subfolders(self, repo_path: Path) -> List[str]:
        """
        Scan a Git repository for addon subfolders (folders containing .toc files)
        Similar to GAM's scanSubfolders approach
        """
        subfolders = []
        
        # Walk through the repository looking for .toc files
        for toc_file in repo_path.rglob("*.toc"):
            parent_folder = toc_file.parent
            relative_path = parent_folder.relative_to(repo_path)
            
            # Check if .toc file matches folder name (standard addon structure)
            folder_name = parent_folder.name
            toc_name = toc_file.stem
            
            # Skip library folders
            if folder_name in ('Libs', 'libs', 'Libraries'):
                continue
            
            # Check if this looks like a valid addon folder
            if toc_name.lower() == folder_name.lower() or \
               toc_name.lower().replace('-', '').replace('_', '') == folder_name.lower().replace('-', '').replace('_', ''):
                # Only add if it's a subfolder (not the root)
                if str(relative_path) != '.' and str(relative_path) not in subfolders:
                    subfolders.append(str(relative_path))
                    logger.debug(f"Found subfolder addon: {relative_path}")
        
        return subfolders
    
    def _create_junction(self, source: Path, target: Path) -> bool:
        """
        Create a directory junction on Windows (doesn't require admin rights)
        """
        try:
            # Remove target if it exists
            if target.exists():
                if target.is_dir():
                    # Check if it's a junction
                    import stat
                    if os.lstat(str(target)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        # It's a junction, remove it
                        os.rmdir(str(target))
                    else:
                        # It's a regular directory
                        shutil.rmtree(target)
                else:
                    target.unlink()
            
            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)
            
            # Windows: use junction for directories (doesn't require admin rights)
            result = subprocess.run(
                ['cmd', '/c', 'mklink', '/J', str(target), str(source)],
                capture_output=True,
                text=True,
                shell=False
            )
            if result.returncode != 0:
                logger.error(f"Failed to create junction: {result.stderr}")
                # Fallback to copying
                shutil.copytree(str(source), str(target))
                return False
            logger.info(f"Created junction: {target} -> {source}")
            return True
                
        except Exception as e:
            logger.error(f"Failed to create junction: {e}")
            # Fallback to copying
            shutil.copytree(str(source), str(target))
            return False
    
    def _get_repos_path(self) -> Path:
        """Get the path to the .repos directory"""
        repos_path = self.addon_path / ".repos"
        repos_path.mkdir(exist_ok=True)
        return repos_path
    
    def _link_subfolders(self, repo_path: Path, addon_name: str) -> List[Tuple[str, Path]]:
        """
        Link addon subfolders from a Git repository in .repos to the AddOns folder
        Returns list of (folder_name, linked_path) tuples
        """
        linked = []
        subfolders = self._scan_git_subfolders(repo_path)
        
        if not subfolders:
            # No subfolders, the addon is at the root level
            # Create a junction directly
            dest_path = self.addon_path / addon_name
            
            # Backup existing if present and not a junction
            import stat
            if dest_path.exists():
                is_junction = False
                try:
                    is_junction = os.lstat(str(dest_path)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                except:
                    pass
                
                if not is_junction:
                    backup_path = self.addon_path / f"{addon_name}.backup"
                    if backup_path.exists():
                        shutil.rmtree(backup_path)
                    shutil.move(str(dest_path), str(backup_path))
            
            self._create_junction(repo_path, dest_path)
            linked.append((addon_name, dest_path))
        else:
            # Link each subfolder
            for subfolder in subfolders:
                source_path = repo_path / subfolder
                folder_name = Path(subfolder).name
                dest_path = self.addon_path / folder_name
                
                # Backup existing if present and not a junction
                import stat
                if dest_path.exists():
                    is_junction = False
                    try:
                        is_junction = os.lstat(str(dest_path)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    except:
                        pass
                    
                    if not is_junction:
                        backup_path = self.addon_path / f"{folder_name}.backup"
                        if backup_path.exists():
                            shutil.rmtree(backup_path)
                        shutil.move(str(dest_path), str(backup_path))
                
                self._create_junction(source_path, dest_path)
                linked.append((folder_name, dest_path))
                logger.info(f"Linked subfolder: {folder_name}")
        
        return linked
    
    def install_addon_git(self, addon_name: str, repo_url: str = None) -> bool:
        """
        Install an addon using Git clone into .repos directory with junctions
        Falls back to zip download if Git fails
        """
        if not self.addon_path:
            logger.error("No addon path configured")
            return False
        
        # Get repository URL from database if not provided
        if not repo_url:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT repo_url, override_url FROM addons WHERE name = ?", (addon_name,))
            result = cursor.fetchone()
            if result:
                repo_url = result['override_url'] or result['repo_url']
        
        if not repo_url:
            logger.error(f"No repository URL for {addon_name}")
            return False
        
        # Clone to .repos directory
        repos_path = self._get_repos_path()
        repo_dest = repos_path / addon_name
        
        try:
            # Remove existing repo if present
            if repo_dest.exists():
                shutil.rmtree(repo_dest)
            
            # Git clone into .repos
            logger.info(f"Cloning {repo_url} to {repo_dest}")
            result = subprocess.run(
                ['git', 'clone', repo_url, str(repo_dest)],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.error(f"Git clone failed: {result.stderr}")
                # Fall back to zip download
                return self.install_addon_zip(addon_name, repo_url)
            
            # Create junctions for addon folders
            linked_folders = self._link_subfolders(repo_dest, addon_name)
            
            # Mark each linked folder as installed
            for folder_name, folder_path in linked_folders:
                version = self._get_addon_version(folder_path)
                # Store the repo path, not the junction path
                self.mark_installed(addon_name if folder_name == addon_name else folder_name, 
                                   version, repo_url, str(repo_dest))
                logger.info(f"Installed {folder_name} version {version} via Git with junction")
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"Git clone timed out for {addon_name}")
            # Fall back to zip download
            return self.install_addon_zip(addon_name, repo_url)
        except Exception as e:
            logger.error(f"Failed to install {addon_name} via Git: {e}")
            # Fall back to zip download
            return self.install_addon_zip(addon_name, repo_url)
    
    def install_addon_zip(self, addon_name: str, repo_url: str = None) -> bool:
        """
        Install an addon by downloading zip archive (fallback method)
        This is the original install_addon method renamed
        """
        if not self.addon_path:
            logger.error("No addon path configured")
            return False
        
        # Get repository URL from database if not provided
        if not repo_url:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT repo_url, override_url FROM addons WHERE name = ?", (addon_name,))
            result = cursor.fetchone()
            if result:
                repo_url = result['override_url'] or result['repo_url']
        
        if not repo_url:
            logger.error(f"No repository URL for {addon_name}")
            return False
        
        # Get download URL
        download_url = self._get_github_release_url(repo_url)
        if not download_url:
            logger.error(f"Could not determine download URL for {addon_name}")
            return False
        
        # Download and extract
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            try:
                # Download
                zip_path = self._download_addon(download_url, temp_path)
                
                # Extract
                extract_dir = temp_path / "extract"
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
                
                # Find addon folders
                addon_folders = self._get_addon_folders(extract_dir)
                if not addon_folders:
                    logger.error(f"No addon folders found in {addon_name}")
                    return False
                
                # Install each addon folder
                for folder_name, source_path in addon_folders:
                    dest_path = self.addon_path / folder_name
                    
                    # Backup existing if present
                    if dest_path.exists():
                        backup_path = self.addon_path / f"{folder_name}.backup"
                        if backup_path.exists():
                            shutil.rmtree(backup_path)
                        shutil.move(str(dest_path), str(backup_path))
                    
                    # Copy new addon
                    shutil.copytree(str(source_path), str(dest_path))
                    
                    # Get version
                    version = self._get_addon_version(dest_path)
                    
                    # Mark as installed
                    self.mark_installed(addon_name, version, repo_url, str(dest_path))
                    
                    logger.info(f"Installed {addon_name} ({folder_name}) version {version} via zip")
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to install {addon_name} via zip: {e}")
                return False
    
    def install_addon(self, addon_name: str, repo_url: str = None, use_git: bool = True) -> bool:
        """
        Install an addon - tries Git first, falls back to zip download
        
        Args:
            addon_name: Name of the addon to install
            repo_url: Repository URL (optional, will be fetched from DB)
            use_git: Whether to try Git clone first (default True)
        """
        if use_git:
            # Try Git clone first (primary method)
            logger.info(f"Installing {addon_name} using Git clone")
            return self.install_addon_git(addon_name, repo_url)
        else:
            # Use zip download directly
            logger.info(f"Installing {addon_name} using zip download")
            return self.install_addon_zip(addon_name, repo_url)
    
    def remove_addon(self, addon_name: str) -> bool:
        """Remove an addon - handles both junctions and .repos folders"""
        if not self.addon_path:
            return False
        
        # Get installed info
        installed = self.get_installed_addons()
        addon_info = installed.get(addon_name.lower())
        
        if not addon_info:
            logger.error(f"{addon_name} is not installed")
            return False
        
        try:
            # Check if it's in .repos (Git-based installation)
            repos_path = self._get_repos_path()
            repo_folder = repos_path / addon_name
            
            if repo_folder.exists():
                logger.info(f"Found Git repository at {repo_folder}")
                
                # Find and remove all junctions pointing to this repo
                for item in self.addon_path.iterdir():
                    if item.is_dir():
                        try:
                            # Check if it's a junction
                            if os.lstat(str(item)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                                # Check if this junction points to our repo
                                # For now, just remove junctions that match addon name or are in the repo
                                if item.name == addon_name or str(repo_folder) in str(item.resolve()):
                                    os.rmdir(str(item))  # Remove junction
                                    logger.info(f"Removed junction: {item}")
                        except:
                            pass
                
                # Remove the Git repository (handle read-only files)
                def remove_readonly(func, path, exc_info):
                    """Error handler for shutil.rmtree to handle read-only files"""
                    import stat
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                
                shutil.rmtree(repo_folder, onerror=remove_readonly)
                logger.info(f"Removed Git repository: {repo_folder}")
            
            else:
                # Old-style installation - just remove the addon folder
                addon_path = Path(addon_info['path'])
                
                # First check if it's a junction
                if addon_path.exists():
                    try:
                        if os.lstat(str(addon_path)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                            os.rmdir(str(addon_path))  # Remove junction
                            logger.info(f"Removed junction: {addon_path}")
                        else:
                            # Remove regular folder (handle read-only files)
                            def remove_readonly(func, path, exc_info):
                                """Error handler for shutil.rmtree to handle read-only files"""
                                os.chmod(path, stat.S_IWRITE)
                                func(path)
                            
                            shutil.rmtree(addon_path, onerror=remove_readonly)
                            logger.info(f"Removed folder: {addon_path}")
                    except:
                        # Fallback to regular removal (handle read-only files)
                        def remove_readonly(func, path, exc_info):
                            """Error handler for shutil.rmtree to handle read-only files"""
                            os.chmod(path, stat.S_IWRITE)
                            func(path)
                        
                        shutil.rmtree(addon_path, onerror=remove_readonly)
                        logger.info(f"Removed {addon_name} from {addon_path}")
            
            # Mark as deleted in database
            now = datetime.utcnow().isoformat()
            cursor = self.db.conn.cursor()
            cursor.execute("""
                UPDATE installed
                SET deleted_at_utc = ?
                WHERE name = ? AND deleted_at_utc IS NULL
            """, (now, addon_name))
            self.db.conn.commit()
            
            self.db.log_event("addon_removed", addon_name=addon_name)
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove {addon_name}: {e}")
            return False
    
    def check_for_updates(self) -> List[Dict]:
        """Check all installed addons for updates using git"""
        updates = []
        installed = self.get_installed_addons()
        
        for addon_key, addon_info in installed.items():
            addon_path = Path(addon_info['path'])
            if not addon_path.exists():
                continue
            
            # Check if it's a git repository
            git_dir = addon_path / '.git'
            if git_dir.exists():
                try:
                    # Get current commit
                    result = subprocess.run(
                        ['git', 'rev-parse', 'HEAD'],
                        cwd=addon_path,
                        capture_output=True,
                        text=True
                    )
                    current_commit = result.stdout.strip()
                    
                    # Fetch to see if there are updates
                    subprocess.run(
                        ['git', 'fetch'],
                        cwd=addon_path,
                        capture_output=True
                    )
                    
                    # Check if behind origin
                    result = subprocess.run(
                        ['git', 'rev-list', 'HEAD..origin/HEAD', '--count'],
                        cwd=addon_path,
                        capture_output=True,
                        text=True
                    )
                    
                    behind_count = int(result.stdout.strip() or 0)
                    if behind_count > 0:
                        updates.append({
                            'name': addon_info['name'],
                            'path': str(addon_path),
                            'current_version': addon_info.get('version', 'unknown'),
                            'commits_behind': behind_count
                        })
                        
                except Exception as e:
                    logger.debug(f"Could not check git status for {addon_info['name']}: {e}")
        
        return updates
    
    def update_addon(self, addon_name: str) -> bool:
        """Update an addon using git pull or reinstall"""
        installed = self.get_installed_addons()
        addon_info = installed.get(addon_name.lower())
        
        if not addon_info:
            logger.error(f"{addon_name} is not installed")
            return False
        
        addon_path = Path(addon_info['path'])
        
        # Try git pull if it's a git repo
        if (addon_path / '.git').exists():
            try:
                result = subprocess.run(
                    ['git', 'pull'],
                    cwd=addon_path,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    # Update version in database
                    version = self._get_addon_version(addon_path)
                    now = datetime.utcnow().isoformat()
                    cursor = self.db.conn.cursor()
                    cursor.execute("""
                        UPDATE installed
                        SET version = ?, last_update_utc = ?
                        WHERE name = ? AND deleted_at_utc IS NULL
                    """, (version, now, addon_name))
                    self.db.conn.commit()
                    
                    logger.info(f"Updated {addon_name} via git pull")
                    return True
                else:
                    logger.error(f"Git pull failed for {addon_name}: {result.stderr}")
                    
            except Exception as e:
                logger.error(f"Git update failed for {addon_name}: {e}")
        
        # Fallback to reinstall
        logger.info(f"Attempting reinstall for {addon_name}")
        repo_url = addon_info.get('repo_url')
        if repo_url:
            return self.install_addon(addon_name, repo_url)
        
        return False


def get_installer(db: Database) -> AddonInstaller:
    """Get an installer instance"""
    return AddonInstaller(db)