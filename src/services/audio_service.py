"""
Audio Service for FlowCoder

Handles sound effect playback using pygame.mixer.
"""

import logging
from pathlib import Path
import pygame


logger = logging.getLogger(__name__)


class AudioServiceError(Exception):
    """Base exception for audio service errors."""
    pass


class AudioService:
    """
    Service for playing sound effects.

    Features:
    - Non-blocking sound playback
    - Volume control (0.0 to 1.0)
    - Mute toggle
    - Multiple concurrent sounds
    - Sound file validation
    """

    def __init__(self, sounds_dir: str = "sounds", enabled: bool = True):
        """
        Initialize audio service.

        Args:
            sounds_dir: Directory containing sound files
            enabled: Whether audio is enabled
        """
        self.sounds_dir = Path(sounds_dir)
        self.enabled = enabled
        self._volume = 0.7  # Default volume (70%)
        self._muted = False
        self._initialized = False

        # Initialize pygame mixer
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self._initialized = True
            logger.info("AudioService initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize audio: {e}. Audio will be disabled.")
            self.enabled = False
            self._initialized = False

    def play_sound(self, filename: str) -> bool:
        """
        Play a sound effect (non-blocking).

        Args:
            filename: Name of the sound file (e.g., "success.wav")

        Returns:
            True if sound was played successfully, False otherwise
        """
        if not self.enabled or self._muted or not self._initialized:
            logger.debug(f"Sound playback skipped: enabled={self.enabled}, muted={self._muted}, initialized={self._initialized}")
            return False

        if not filename:
            logger.debug("No filename provided for sound playback")
            return False

        try:
            # Construct full path
            sound_path = self.sounds_dir / filename

            # Check if file exists
            if not sound_path.exists():
                logger.warning(f"Sound file not found: {sound_path}")
                return False

            # Check file extension
            if sound_path.suffix.lower() not in ['.wav', '.ogg', '.mp3']:
                logger.warning(f"Unsupported sound file format: {sound_path.suffix}")
                return False

            # Load and play sound
            sound = pygame.mixer.Sound(str(sound_path))
            sound.set_volume(self._volume)
            sound.play()

            logger.debug(f"Playing sound: {filename} (volume={self._volume})")
            return True

        except Exception as e:
            logger.error(f"Failed to play sound '{filename}': {e}", exc_info=True)
            return False

    def set_volume(self, volume: float) -> None:
        """
        Set playback volume.

        Args:
            volume: Volume level (0.0 = silent, 1.0 = maximum)
        """
        # Clamp volume to valid range
        self._volume = max(0.0, min(1.0, volume))
        logger.debug(f"Volume set to {self._volume}")

    def get_volume(self) -> float:
        """
        Get current volume level.

        Returns:
            Current volume (0.0 to 1.0)
        """
        return self._volume

    def mute(self) -> None:
        """Mute all sound playback."""
        self._muted = True
        logger.info("Audio muted")

    def unmute(self) -> None:
        """Unmute sound playback."""
        self._muted = False
        logger.info("Audio unmuted")

    def toggle_mute(self) -> bool:
        """
        Toggle mute state.

        Returns:
            New mute state (True = muted, False = unmuted)
        """
        if self._muted:
            self.unmute()
        else:
            self.mute()
        return self._muted

    def is_muted(self) -> bool:
        """
        Check if audio is muted.

        Returns:
            True if muted, False otherwise
        """
        return self._muted

    def is_enabled(self) -> bool:
        """
        Check if audio service is enabled and initialized.

        Returns:
            True if enabled and initialized, False otherwise
        """
        return self.enabled and self._initialized

    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable audio service.

        Args:
            enabled: True to enable, False to disable
        """
        self.enabled = enabled and self._initialized
        logger.info(f"Audio service {'enabled' if self.enabled else 'disabled'}")

    def stop_all_sounds(self) -> None:
        """Stop all currently playing sounds."""
        if self._initialized:
            try:
                pygame.mixer.stop()
                logger.debug("All sounds stopped")
            except Exception as e:
                logger.error(f"Failed to stop sounds: {e}")

    def get_available_sounds(self) -> list:
        """
        Get list of available sound files in sounds directory.

        Returns:
            List of sound filenames
        """
        if not self.sounds_dir.exists():
            logger.warning(f"Sounds directory does not exist: {self.sounds_dir}")
            return []

        try:
            sound_files = []
            for ext in ['.wav', '.ogg', '.mp3']:
                sound_files.extend([
                    f.name for f in self.sounds_dir.glob(f'*{ext}')
                ])
            return sorted(sound_files)
        except Exception as e:
            logger.error(f"Failed to list sound files: {e}")
            return []

    def shutdown(self) -> None:
        """Shutdown audio service and cleanup resources."""
        if self._initialized:
            try:
                pygame.mixer.quit()
                logger.info("AudioService shut down")
            except Exception as e:
                logger.error(f"Error during audio shutdown: {e}")
        self._initialized = False
