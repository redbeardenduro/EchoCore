# avatar_display.py
"""
Displays the visual avatar using Pygame.
Animates based on application state and audio amplitude.
"""
import threading
import queue
import time
import pygame
import numpy as np
import config
from state_manager import StateManager, State

class AvatarDisplay(threading.Thread):
    """
    Thread to manage the Pygame window and render the avatar.
    Receives amplitude data from avatar_queue.
    """
    def __init__(self, avatar_queue: queue.Queue, state_manager: StateManager, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.avatar_queue = avatar_queue
        self.state_manager = state_manager
        self.stop_event = stop_event
        self.screen = None
        self.clock = None
        self.current_amplitude = 0.0
        self.running = False

    def run(self):
        """Main loop for the Pygame avatar display thread."""
        try:
            pygame.init()
            # Set display mode - consider flags like FULLSCREEN or NOFRAME for kiosk
            # Note: Kiosk mode setup (autostart, no window manager) is OS-level, not done here.
            # For RPi Lite, ensure SDL_VIDEODRIVER=kmsdrm is set in environment [35, 36]
            self.screen = pygame.display.set_mode(
                (config.AVATAR_WINDOW_WIDTH, config.AVATAR_WINDOW_HEIGHT)
                # pygame.FULLSCREEN | pygame.NOFRAME # Example flags for kiosk
            )
            pygame.display.set_caption("Project EchoCore Avatar")
            self.clock = pygame.time.Clock()
            print("Pygame initialized.")
            self.running = True
        except pygame.error as e:
            print(f"Error initializing Pygame: {e}")
            print("Ensure display environment is set up (e.g., X11 or KMSDRM on RPi).")
            self.state_manager.set_state(State.ERROR)
            self.running = False
            return # Exit thread if Pygame fails

        while self.running and not self.stop_event.is_set():
            # --- Event Handling ---
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    self.stop_event.set() # Signal other threads to stop
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: # Allow exit with ESC key
                         self.running = False
                         self.stop_event.set()

            # --- Get Amplitude ---
            try:
                # Get the latest amplitude value (non-blocking)
                while not self.avatar_queue.empty():
                    self.current_amplitude = self.avatar_queue.get_nowait()
            except queue.Empty:
                pass # Keep the last known amplitude if queue is empty

            # --- Get Current State ---
            current_state = self.state_manager.get_state()

            # --- Drawing ---
            self.screen.fill(config.AVATAR_BACKGROUND_COLOR)
            self._draw_avatar(current_state, self.current_amplitude)
            pygame.display.flip()

            # --- Frame Rate Control ---
            self.clock.tick(config.AVATAR_FPS)

        self._cleanup()

    def _draw_avatar(self, state, amplitude):
        """Draws a simple circle avatar based on state and amplitude."""
        center_x = config.AVATAR_WINDOW_WIDTH // 2
        center_y = config.AVATAR_WINDOW_HEIGHT // 2

        # Determine color based on state
        color = config.AVATAR_IDLE_COLOR
        if state == State.LISTENING:
            color = config.AVATAR_LISTENING_COLOR
        elif state == State.PROCESSING_STT or state == State.THINKING:
             color = config.AVATAR_THINKING_COLOR
        elif state == State.SYNTHESIZING_TTS or state == State.SPEAKING:
            color = config.AVATAR_SPEAKING_COLOR
        elif state == State.ERROR:
            color = config.AVATAR_ERROR_COLOR

        # Determine radius based on amplitude (only when speaking)
        radius = config.AVATAR_MIN_RADIUS
        if state == State.SPEAKING:
            # Scale radius based on amplitude
            radius += int(amplitude * (config.AVATAR_MAX_RADIUS_FACTOR * config.AVATAR_MIN_RADIUS))
            radius = max(config.AVATAR_MIN_RADIUS, radius) # Ensure minimum size

        # Draw the circle
        pygame.draw.circle(self.screen, color, (center_x, center_y), radius)

        # TODO: Add more sophisticated animations (pulsing, waveform, silhouette)
        # Example: Simple pulsing effect even when idle/listening
        # if state == State.IDLE or state == State.LISTENING:
        #     pulse_factor = (1 + math.sin(time.time() * 2)) / 2 # Slow pulse
        #     radius = config.AVATAR_MIN_RADIUS + int(pulse_factor * 5)
        #     pygame.draw.circle(self.screen, color, (center_x, center_y), radius)


    def _cleanup(self):
        """Clean up Pygame resources."""
        print("Cleaning up Avatar Display...")
        pygame.quit()
