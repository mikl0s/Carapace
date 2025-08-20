"""
Application auto-update system for Carapace
"""

import os
import sys
import json
import logging
import requests
import subprocess
import tempfile
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from packaging import version

from carapace import __version__

logger = logging.getLogger(__name__)


class ApplicationUpdater:
    """Handles checking for and downloading application updates from GitHub"""
    
    # GitHub API endpoints
    GITHUB_API_BASE = "https://api.github.com"
    GITHUB_REPO = "mikl0s/Carapace"
    RELEASES_URL = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases"
    LATEST_RELEASE_URL = f"{RELEASES_URL}/latest"
    
    def __init__(self):
        """Initialize the application updater"""
        self.current_version = __version__
        self.app_path = Path(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])
        self.is_frozen = getattr(sys, 'frozen', False)
        
    def parse_version(self, version_str: str) -> version.Version:
        """Parse a version string, handling 'v' prefix"""
        if version_str.startswith('v'):
            version_str = version_str[1:]
        return version.parse(version_str)
    
    def get_latest_release(self) -> Optional[Dict[str, Any]]:
        """
        Fetch the latest release information from GitHub
        
        Returns:
            dict: Release information or None if failed
        """
        try:
            headers = {'Accept': 'application/vnd.github.v3+json'}
            response = requests.get(self.LATEST_RELEASE_URL, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch latest release: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in release response: {e}")
            return None
    
    def check_for_updates(self) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if an application update is available
        
        Returns:
            tuple: (update_available, release_info)
        """
        release = self.get_latest_release()
        if not release:
            logger.info("Could not fetch release information")
            return False, None
        
        try:
            latest_version = self.parse_version(release['tag_name'])
            current_version = self.parse_version(self.current_version)
            
            if latest_version > current_version:
                logger.info(f"Update available: v{self.current_version} -> v{release['tag_name']}")
                return True, release
            
            logger.info(f"Application is up to date (v{self.current_version})")
            return False, release
            
        except Exception as e:
            logger.error(f"Error comparing versions: {e}")
            return False, None
    
    def get_download_url(self, release: Dict[str, Any]) -> Optional[str]:
        """
        Get the appropriate download URL for the current platform
        
        Args:
            release: GitHub release information
            
        Returns:
            str: Download URL or None if not found
        """
        if not release.get('assets'):
            return None
        
        # Look for Windows executable
        for asset in release['assets']:
            name = asset['name'].lower()
            if sys.platform == 'win32':
                if name.endswith('.exe') or 'windows' in name:
                    return asset['browser_download_url']
                elif name.endswith('.zip') and 'windows' in name:
                    return asset['browser_download_url']
        
        return None
    
    def download_update(self, url: str, target_path: Path) -> bool:
        """
        Download an update file
        
        Args:
            url: Download URL
            target_path: Path to save the file
            
        Returns:
            bool: True if successful
        """
        try:
            logger.info(f"Downloading update from {url}")
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(target_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            logger.debug(f"Download progress: {progress:.1f}%")
            
            logger.info(f"Downloaded update to {target_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download update: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error downloading update: {e}")
            return False
    
    def apply_update_windows(self, update_file: Path) -> bool:
        """
        Apply update on Windows using a batch script
        
        Args:
            update_file: Path to the downloaded update
            
        Returns:
            bool: True if update was initiated
        """
        if not self.is_frozen:
            logger.warning("Cannot auto-update when running from source")
            return False
        
        # Create update batch script
        batch_script = self.app_path.parent / "update.bat"
        current_exe = self.app_path
        backup_exe = current_exe.with_suffix('.exe.backup')
        
        script_content = f"""@echo off
echo Updating Carapace...
timeout /t 2 /nobreak > nul
move /y "{current_exe}" "{backup_exe}"
if errorlevel 1 (
    echo Failed to backup current version
    pause
    exit /b 1
)
"""
        
        # Handle zip or exe
        if update_file.suffix.lower() == '.zip':
            script_content += f"""
powershell -Command "Expand-Archive -Path '{update_file}' -DestinationPath '{current_exe.parent}' -Force"
if errorlevel 1 (
    echo Failed to extract update
    move /y "{backup_exe}" "{current_exe}"
    pause
    exit /b 1
)
del "{update_file}"
"""
        else:
            script_content += f"""
move /y "{update_file}" "{current_exe}"
if errorlevel 1 (
    echo Failed to apply update
    move /y "{backup_exe}" "{current_exe}"
    pause
    exit /b 1
)
"""
        
        script_content += f"""
echo Update complete!
echo Starting new version...
timeout /t 2 /nobreak > nul
start "" "{current_exe}"
del "%~f0"
"""
        
        try:
            with open(batch_script, 'w') as f:
                f.write(script_content)
            
            # Start the update script
            subprocess.Popen([str(batch_script)], shell=True)
            logger.info("Update script started, application will restart")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create update script: {e}")
            return False
    
    def perform_update(self, release: Dict[str, Any]) -> bool:
        """
        Download and apply an update
        
        Args:
            release: GitHub release information
            
        Returns:
            bool: True if update was successful or initiated
        """
        # Get download URL
        download_url = self.get_download_url(release)
        if not download_url:
            logger.error("No suitable download found for this platform")
            return False
        
        # Download to temp location
        temp_dir = Path(tempfile.gettempdir())
        filename = download_url.split('/')[-1]
        temp_file = temp_dir / filename
        
        if not self.download_update(download_url, temp_file):
            return False
        
        # Apply update based on platform
        if sys.platform == 'win32':
            return self.apply_update_windows(temp_file)
        else:
            logger.error(f"Auto-update not implemented for {sys.platform}")
            return False
    
    def check_and_notify(self) -> Optional[Dict[str, Any]]:
        """
        Check for updates and return info for notification
        
        Returns:
            dict: Update information if available, None otherwise
        """
        update_available, release = self.check_for_updates()
        
        if not update_available or not release:
            return None
        
        return {
            'current_version': self.current_version,
            'new_version': release['tag_name'],
            'release_notes': release.get('body', ''),
            'download_url': self.get_download_url(release),
            'release_url': release['html_url']
        }


def check_for_app_updates() -> Optional[Dict[str, Any]]:
    """
    Convenience function to check for application updates
    
    Returns:
        dict: Update information if available
    """
    updater = ApplicationUpdater()
    return updater.check_and_notify()


def perform_self_update() -> bool:
    """
    Perform a self-update of the application
    
    Returns:
        bool: True if update was initiated
    """
    updater = ApplicationUpdater()
    update_available, release = updater.check_for_updates()
    
    if not update_available:
        logger.info("No update available")
        return False
    
    if not release:
        logger.error("Could not fetch release information")
        return False
    
    return updater.perform_update(release)