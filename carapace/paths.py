"""
Path detection and management for TurtleWoW installation
"""

import os
import sys
import winreg
from pathlib import Path
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class PathDetector:
    """Detect and manage TurtleWoW installation paths"""
    
    def __init__(self):
        self.wow_path: Optional[Path] = None
        self.addon_path: Optional[Path] = None
    
    def detect_from_registry(self) -> Optional[Path]:
        r"""
        Detect TurtleWoW installation from Windows Registry
        Uses: HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall\TurtleWoW
        Value: InstallLocation
        """
        if sys.platform != 'win32':
            return None
        
        try:
            # Open the registry key
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\TurtleWoW"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                # Read the InstallLocation value
                install_location, _ = winreg.QueryValueEx(key, "InstallLocation")
                
                if install_location:
                    # Remove quotes if present
                    install_location = install_location.strip('"')
                    path = Path(install_location)
                    if self._validate_wow_directory(path):
                        logger.info(f"Found TurtleWoW in registry: {path}")
                        return path
                    else:
                        logger.warning(f"Registry path exists but invalid: {path}")
        except FileNotFoundError:
            logger.debug("TurtleWoW not found in registry")
        except Exception as e:
            logger.error(f"Error reading registry: {e}")
        
        return None
    
    def detect_from_common_locations(self) -> Optional[Path]:
        """Check common installation locations for TurtleWoW"""
        common_paths = [
            Path("C:/TurtleWoW"),
            Path("C:/Program Files/TurtleWoW"),
            Path("C:/Program Files (x86)/TurtleWoW"),
            Path("D:/TurtleWoW"),
            Path("D:/Games/TurtleWoW"),
            Path(os.path.expanduser("~/TurtleWoW")),
            Path(os.path.expanduser("~/Games/TurtleWoW")),
            Path(os.path.expanduser("~/Desktop/TurtleWoW")),
        ]
        
        for path in common_paths:
            if self._validate_wow_directory(path):
                logger.info(f"Found TurtleWoW at common location: {path}")
                return path
        
        return None
    
    def detect_from_desktop_shortcuts(self) -> List[Path]:
        """Scan desktop shortcuts for TurtleWoW.exe references"""
        potential_paths = []
        
        if sys.platform != 'win32':
            return potential_paths
        
        try:
            import winshell
            desktop = Path(winshell.desktop())
            
            for lnk_file in desktop.glob("*.lnk"):
                try:
                    shortcut = winshell.shortcut(str(lnk_file))
                    target = shortcut.path
                    if target and "turtlewow" in target.lower():
                        target_path = Path(target).parent
                        if self._validate_wow_directory(target_path):
                            potential_paths.append(target_path)
                            logger.debug(f"Found via shortcut {lnk_file.name}: {target_path}")
                except:
                    continue
        except ImportError:
            logger.debug("winshell not available for shortcut scanning")
        except Exception as e:
            logger.error(f"Error scanning shortcuts: {e}")
        
        return potential_paths
    
    def _validate_wow_directory(self, path: Path) -> bool:
        """Validate that a directory contains TurtleWoW installation"""
        if not path or not path.exists():
            return False
        
        # Check for TurtleWoW.exe (case-insensitive on Windows)
        exe_files = [
            "TurtleWoW.exe",
            "turtlewow.exe",
            "Turtle WoW.exe",
            "WoW.exe"
        ]
        
        for exe_name in exe_files:
            exe_path = path / exe_name
            if exe_path.exists() and exe_path.is_file():
                return True
        
        return False
    
    def detect_wow_path(self) -> Optional[Path]:
        """
        Detect TurtleWoW installation path using multiple methods:
        1. Check Windows Registry
        2. Check common installation locations
        3. Scan desktop shortcuts
        """
        # Try registry first (most reliable)
        path = self.detect_from_registry()
        if path:
            self.wow_path = path
            return path
        
        # Try common locations
        path = self.detect_from_common_locations()
        if path:
            self.wow_path = path
            return path
        
        # Try desktop shortcuts
        shortcut_paths = self.detect_from_desktop_shortcuts()
        if shortcut_paths:
            # Use the first valid path found
            self.wow_path = shortcut_paths[0]
            return shortcut_paths[0]
        
        logger.warning("Could not auto-detect TurtleWoW installation")
        return None
    
    def ensure_addon_directory(self, wow_path: Optional[Path] = None) -> Optional[Path]:
        r"""
        Ensure the Interface\AddOns directory exists
        Creates it if necessary
        """
        if wow_path is None:
            wow_path = self.wow_path
        
        if wow_path is None:
            wow_path = self.detect_wow_path()
        
        if wow_path is None:
            return None
        
        # Create Interface\AddOns path
        addon_path = wow_path / "Interface" / "AddOns"
        
        try:
            # Create directories if they don't exist
            addon_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"AddOns directory ready: {addon_path}")
            self.addon_path = addon_path
            return addon_path
        except Exception as e:
            logger.error(f"Failed to create addon directory: {e}")
            return None
    
    def get_addon_path(self) -> Optional[Path]:
        """Get the addon installation path, detecting if necessary"""
        if self.addon_path and self.addon_path.exists():
            return self.addon_path
        
        return self.ensure_addon_directory()
    
    def set_wow_path(self, path: Path) -> bool:
        """Manually set the WoW installation path"""
        if self._validate_wow_directory(path):
            self.wow_path = path
            logger.info(f"WoW path set to: {path}")
            return True
        else:
            logger.error(f"Invalid WoW directory: {path}")
            return False
    
    def prompt_for_path(self) -> Optional[Path]:
        """Prompt user to enter WoW installation path"""
        print("\nTurtleWoW installation not found automatically.")
        print("Please enter the path to your TurtleWoW installation")
        print("(the folder containing TurtleWoW.exe):")
        
        while True:
            user_input = input("> ").strip()
            
            if not user_input:
                return None
            
            path = Path(user_input)
            if self._validate_wow_directory(path):
                self.wow_path = path
                return path
            else:
                print(f"Error: TurtleWoW.exe not found in {path}")
                print("Please enter a valid path or press Enter to cancel:")


# Singleton instance
_detector = PathDetector()

def get_wow_path() -> Optional[Path]:
    """Get the detected WoW installation path"""
    return _detector.detect_wow_path()

def get_addon_path() -> Optional[Path]:
    """Get the addon installation path"""
    return _detector.get_addon_path()

def ensure_addon_directory() -> Optional[Path]:
    """Ensure addon directory exists and return its path"""
    return _detector.ensure_addon_directory()

def set_wow_path(path: Path) -> bool:
    """Set the WoW installation path manually"""
    return _detector.set_wow_path(path)