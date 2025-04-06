import json
import os
import threading
import platform
import time
from typing import Dict, List, Any, Optional
from pathlib import Path

if platform.system() != 'Windows':
    import fcntl
else:
    import msvcrt

class SettingsManager:
    """
    Thread-safe settings manager for handling settings file operations.
    Uses file locking to prevent race conditions when multiple threads/processes
    access the settings file simultaneously.
    """
    _instance = None
    _lock = threading.Lock()
    
    # Constants for file locking
    MAX_RETRIES = 5
    RETRY_DELAY = 0.1  # seconds
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SettingsManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance
            
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._file_lock = threading.Lock()
        
    def _acquire_file_lock(self, file_path: str, mode: str) -> tuple[Any, Any]:
        """
        Acquires both an exclusive file lock and opens the file.
        Uses retry logic to wait for lock to become available.
        
        Args:
            file_path: Path to the settings file
            mode: File open mode ('r' or 'w')
            
        Returns:
            Tuple of (file handle, file descriptor)
            
        Raises:
            Exception: If lock cannot be acquired after max retries
        """
        retries = 0
        while retries < self.MAX_RETRIES:
            try:
                # Open file and get file descriptor
                file = open(file_path, mode)
                fd = file.fileno()
                
                # Platform-specific file locking with retry logic
                if platform.system() != 'Windows':
                    # Unix-like systems use fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                else:
                    # Windows systems use msvcrt with retry
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    except IOError:
                        # If lock fails, close file and retry
                        file.close()
                        time.sleep(self.RETRY_DELAY)
                        retries += 1
                        continue
                
                return file, fd
                
            except Exception as e:
                if 'file' in locals():
                    file.close()
                if retries >= self.MAX_RETRIES - 1:
                    raise Exception(f"Failed to acquire file lock after {self.MAX_RETRIES} retries: {str(e)}")
                time.sleep(self.RETRY_DELAY)
                retries += 1
                
        raise Exception(f"Failed to acquire file lock after {self.MAX_RETRIES} retries")
            
    def _release_file_lock(self, file: Any, fd: int):
        """
        Releases the file lock and closes the file.
        
        Args:
            file: File handle
            fd: File descriptor
        """
        try:
            if platform.system() != 'Windows':
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            file.close()
        except Exception as e:
            print(f"Warning: Error releasing file lock: {str(e)}")

    def load_settings(self, settings_path: str) -> List[Dict]:
        """
        Loads settings from file in a thread-safe manner.
        
        Args:
            settings_path: Path to settings file
            
        Returns:
            List of settings dictionaries
        """
        with self._file_lock:
            if not os.path.exists(settings_path):
                return []
                
            try:
                file, fd = self._acquire_file_lock(settings_path, 'r')
                settings = json.load(file)
                self._release_file_lock(file, fd)
                return settings
            except json.JSONDecodeError:
                if 'file' in locals():
                    self._release_file_lock(file, fd)
                return []
            except Exception as e:
                if 'file' in locals():
                    self._release_file_lock(file, fd)
                raise Exception(f"Failed to load settings: {str(e)}")

    def save_settings(self, settings_path: str, settings: List[Dict]):
        """
        Saves settings to file in a thread-safe manner.
        Uses atomic write pattern with temporary file.
        
        Args:
            settings_path: Path to settings file
            settings: List of settings dictionaries to save
        """
        with self._file_lock:
            try:
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(settings_path), exist_ok=True)
                
                # Write to a temporary file first
                temp_path = f"{settings_path}.tmp"
                with open(temp_path, 'w') as f:
                    json.dump(settings, f, indent=4)
                
                # Then acquire lock and do atomic rename
                file, fd = self._acquire_file_lock(settings_path, 'w')
                os.replace(temp_path, settings_path)
                self._release_file_lock(file, fd)
                
            except Exception as e:
                if 'file' in locals():
                    self._release_file_lock(file, fd)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise Exception(f"Failed to save settings: {str(e)}")

    def update_settings(self, settings_path: str, assistant_id: str, new_settings: Dict):
        """
        Updates specific assistant settings in a thread-safe manner.
        
        Args:
            settings_path: Path to settings file
            assistant_id: ID of assistant to update
            new_settings: New settings dictionary
        """
        with self._file_lock:
            try:
                settings = self.load_settings(settings_path)
                
                # Find and update assistant settings
                updated = False
                for i, setting in enumerate(settings):
                    if setting.get('id') == assistant_id:
                        settings[i] = new_settings
                        updated = True
                        break
                        
                # Add new settings if not found
                if not updated:
                    settings.append(new_settings)
                    
                self.save_settings(settings_path, settings)
                
            except Exception as e:
                raise Exception(f"Failed to update settings: {str(e)}")

    def delete_settings(self, settings_path: str, assistant_id: str):
        """
        Deletes specific assistant settings in a thread-safe manner.
        
        Args:
            settings_path: Path to settings file
            assistant_id: ID of assistant to delete
        """
        with self._file_lock:
            try:
                settings = self.load_settings(settings_path)
                settings = [s for s in settings if s.get('id') != assistant_id]
                self.save_settings(settings_path, settings)
            except Exception as e:
                raise Exception(f"Failed to delete settings: {str(e)}") 