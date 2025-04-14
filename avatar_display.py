# avatar_display.py
"""
Manages the visual avatar display using Pygame.

Renders animations synchronized with application state and audio amplitude,
displaying status text, error messages, and optional debug information.
"""

import threading
import queue
import time
import math
import random
import logging
import sys
from typing import Optional, List, Tuple, Dict, Any # For type hinting

# Attempt Pygame import early and handle failure
try:
    import pygame
    import numpy as np # Required for some effects
except ImportError as e:
    logging.critical(f"Pygame or NumPy not found. Avatar display cannot function. Error: {e}")
    logging.critical("Please install them: pip install pygame numpy")
    # Set a flag or dummy class to prevent errors if the rest of the app can run without avatar
    pygame = None
    np = None
    # raise # Or re-raise if Pygame is absolutely essential

# Import project modules
try:
    import config
    from state_manager import StateManager, State
except ImportError as e:
    logging.error(f"Error importing project modules in avatar_display.py: {e}")
    raise


# Setup logger
logger = logging.getLogger(__name__)

# Type alias for color tuples/lists
ColorTuple = Tuple[int, int, int]
ColorList = List[int] # From config JSON
ColorValue = Union[ColorTuple, ColorList] # Type hint for color values

# Type alias for particle dictionary
ParticleDict = Dict[str, Any] # More specific types possible if needed

class AvatarDisplay(threading.Thread):
    """
    Thread to manage the Pygame window and render the avatar visualization.

    Receives normalized amplitude data (float) from the avatar_queue and
    monitors the application state via the StateManager to update animations.
    """
    def __init__(
        self,
        avatar_queue: queue.Queue[float], # Receives normalized amplitude
        state_manager: StateManager,
        stop_event: threading.Event
    ):
        """
        Initializes the AvatarDisplay thread.

        Args:
            avatar_queue: Queue receiving normalized amplitude (0.0-1.0).
            state_manager: The application's state manager instance.
            stop_event: Threading event to signal when to stop.
        """
        # Check if Pygame loaded successfully before proceeding
        if pygame is None:
            logger.error("Pygame dependency missing, AvatarDisplay cannot initialize.")
            # We need to prevent the thread from starting
            # One way is to set the stop_event immediately or raise an exception
            stop_event.set() # Signal thread should not run
            # Or raise an error to halt initialization
            raise RuntimeError("Pygame not found, cannot start AvatarDisplay.")


        super().__init__(name="AvatarDisplayThread", daemon=True)
        self.avatar_queue = avatar_queue
        self.state_manager = state_manager
        self.stop_event = stop_event

        # --- Pygame Specific ---
        self.screen: Optional[pygame.Surface] = None
        self.clock: Optional[pygame.time.Clock] = None
        self.font: Optional[pygame.font.Font] = None
        self.debug_font: Optional[pygame.font.Font] = None
        self._pygame_initialized: bool = False
        self._display_flags: int = 0

        # --- Configuration ---
        self.width: int = config.AVATAR_WINDOW_WIDTH
        self.height: int = config.AVATAR_WINDOW_HEIGHT
        self.center_x: int = self.width // 2
        self.center_y: int = self.height // 2
        self.fps: int = config.AVATAR_FPS
        self.fullscreen: bool = config.AVATAR_FULLSCREEN
        self.debug_overlay: bool = config.AVATAR_DEBUG_OVERLAY
        self.show_status_text: bool = config.AVATAR_DISPLAY_STATUS_TEXT
        self.animation_style: str = config.AVATAR_ANIMATION_STYLE

        # Colors (convert from list in config if necessary)
        self.bg_color: ColorTuple = tuple(config.AVATAR_BACKGROUND_COLOR) # type: ignore
        self.colors: Dict[State, ColorTuple] = {
            State.IDLE: tuple(config.AVATAR_IDLE_COLOR), # type: ignore
            State.LISTENING: tuple(config.AVATAR_LISTENING_COLOR), # type: ignore
            State.PROCESSING_STT: tuple(config.AVATAR_THINKING_COLOR), # type: ignore
            State.THINKING: tuple(config.AVATAR_THINKING_COLOR), # type: ignore
            State.SYNTHESIZING_TTS: tuple(config.AVATAR_SPEAKING_COLOR), # type: ignore
            State.SPEAKING: tuple(config.AVATAR_SPEAKING_COLOR), # type: ignore
            State.ERROR: tuple(config.AVATAR_ERROR_COLOR) # type: ignore
        }
        self.default_color: ColorTuple = self.colors[State.IDLE] # Fallback color

        # Animation parameters
        self.min_radius: int = config.AVATAR_MIN_RADIUS
        self.max_radius_factor: float = config.AVATAR_MAX_RADIUS_FACTOR

        # --- State & Data ---
        self.current_amplitude: float = 0.0
        self.amplitude_history: List[float] = []
        self.history_max_length: int = max(1, self.fps // 3) # History based on FPS (e.g., 10 frames at 30fps)

        # --- Animation Effects ---
        self.particles: List[ParticleDict] = []
        self.max_particles: int = 75 # Increased max particles
        self.pulse_phase: float = 0.0
        self.transition_effect: float = 0.0 # Controls flash on state change (0 to 1)
        self.previous_state: Optional[State] = None
        self.glow_surfaces: Dict[Any, pygame.Surface] = {} # Cache for glow surfaces
        self.status_text: str = ""
        self.status_alpha: int = 0 # For fade effect

        logger.debug("AvatarDisplay initialized.")


    def _init_pygame(self) -> bool:
        """Initialize Pygame display, fonts, and clock."""
        if self._pygame_initialized:
            return True
        logger.info("Initializing Pygame for Avatar Display...")
        try:
            pygame.init()
            pygame.font.init() # Explicitly initialize font module

            # Set display mode
            self._display_flags = pygame.RESIZABLE # Start with resizable for flexibility
            if self.fullscreen:
                 self._display_flags = pygame.FULLSCREEN | pygame.SCALED # Use SCALED with FULLSCREEN
                 logger.info("Pygame Fullscreen mode enabled.")

            self.screen = pygame.display.set_mode((self.width, self.height), self._display_flags)
            pygame.display.set_caption("Project EchoCore Avatar")

            self.clock = pygame.time.Clock()

            # Load fonts (handle potential errors)
            try:
                self.font = pygame.font.SysFont("Arial", 18)
                self.debug_font = pygame.font.SysFont("Courier", 14)
            except Exception as font_error:
                 logger.warning(f"Failed to load system fonts, using default: {font_error}")
                 self.font = pygame.font.Font(None, 24) # Pygame default font
                 self.debug_font = pygame.font.Font(None, 18)


            self._pygame_initialized = True
            logger.info("Pygame initialized successfully.")
            return True

        except pygame.error as e:
            logger.error(f"Error initializing Pygame: {e}")
            logger.error("Ensure a display environment is available (e.g., X11 server or KMSDRM on RPi).")
            # Set error state if Pygame fails critically
            self.state_manager.set_state(State.ERROR, error_message=f"Pygame init failed: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error during Pygame initialization: {e}")
            self.state_manager.set_state(State.ERROR, error_message=f"Unexpected Pygame init error: {e}")
            return False

    def _update_amplitude(self) -> None:
        """Get the latest amplitude value from the queue and update history."""
        try:
            # Process all available amplitude updates in the queue
            while not self.avatar_queue.empty():
                 amplitude = self.avatar_queue.get_nowait()
                 # Clamp amplitude between 0.0 and 1.0
                 self.current_amplitude = max(0.0, min(float(amplitude), 1.0))

                 # Add to history
                 self.amplitude_history.append(self.current_amplitude)
                 # Trim history
                 if len(self.amplitude_history) > self.history_max_length:
                     # More efficient trimming than pop(0)
                     self.amplitude_history = self.amplitude_history[-self.history_max_length:]

        except queue.Empty:
            # If queue is empty, gradually decrease amplitude towards 0? Or hold last?
            # Let's hold the last known amplitude for now.
            pass
        except Exception as e:
            logger.error(f"Error reading from avatar queue: {e}")
            self.current_amplitude = 0.0 # Default to zero on error


    def _handle_input(self) -> None:
        """Handle Pygame events like quit or key presses."""
        if not self._pygame_initialized or self.screen is None: return

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                logger.info("Pygame QUIT event received.")
                self.stop_event.set() # Signal all threads to stop
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    logger.info("Escape key pressed.")
                    self.stop_event.set()
                elif event.key == pygame.K_f: # Toggle fullscreen example
                     self.fullscreen = not self.fullscreen
                     flags = pygame.FULLSCREEN | pygame.SCALED if self.fullscreen else pygame.RESIZABLE
                     try:
                          pygame.display.set_mode((self.width, self.height), flags)
                          logger.info(f"Toggled fullscreen: {self.fullscreen}")
                     except pygame.error as e:
                          logger.error(f"Failed to toggle fullscreen: {e}")

            elif event.type == pygame.VIDEORESIZE: # Handle window resize
                 if not self.fullscreen:
                      self.width = event.w
                      self.height = event.h
                      self.center_x = self.width // 2
                      self.center_y = self.height // 2
                      try:
                          self.screen = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
                          logger.info(f"Window resized to {self.width}x{self.height}")
                      except pygame.error as e:
                           logger.error(f"Failed to resize window: {e}")


    def _update_state_and_effects(self) -> Tuple[State, ColorTuple, float]:
        """Update internal state based on StateManager and manage transition effects."""
        current_state = self.state_manager.get_state()
        smooth_amplitude = sum(self.amplitude_history) / len(self.amplitude_history) if self.amplitude_history else 0.0

        # --- State Transition Logic ---
        if current_state != self.previous_state:
            logger.debug(f"Avatar detected state change: {self.previous_state} -> {current_state}")
            self.transition_effect = 1.0 # Start transition flash effect
            self.previous_state = current_state

            # Update status text based on the new state
            self.status_text = current_state.name.replace("_", " ").title() # Auto-format state name
            if current_state == State.IDLE: self.status_text = "Ready"
            elif current_state == State.LISTENING: self.status_text = "Listening..."
            elif current_state == State.PROCESSING_STT: self.status_text = "Processing Speech..."
            elif current_state == State.THINKING: self.status_text = "Thinking..."
            elif current_state == State.SYNTHESIZING_TTS: self.status_text = "Generating Response..."
            elif current_state == State.SPEAKING: self.status_text = "Speaking..."
            elif current_state == State.ERROR: self.status_text = "Error Occurred"

            self.status_alpha = 255 # Make status text fully visible on change

        # --- Update Ongoing Effects ---
        # Update pulse phase for idle animations etc.
        self.pulse_phase = (self.pulse_phase + 0.05) % (2 * math.pi)

        # Decay transition effect
        if self.transition_effect > 0:
            self.transition_effect = max(0.0, self.transition_effect - 0.05) # Linear decay

        # Decay status text alpha (unless in certain states)
        if self.status_alpha > 0 and current_state not in (State.LISTENING, State.SPEAKING, State.ERROR):
             self.status_alpha = max(0, self.status_alpha - 2) # Slow fade out
        elif current_state in (State.LISTENING, State.SPEAKING, State.ERROR):
             self.status_alpha = 255 # Keep visible

        # --- Determine Color ---
        base_color = self.colors.get(current_state, self.default_color)

        # Apply transition effect (flash brighter)
        if self.transition_effect > 0:
             # Interpolate towards a brighter version of the base color
             bright_color = tuple(min(c + 100, 255) for c in base_color)
             final_color = tuple(int(bright_color[i] * self.transition_effect + base_color[i] * (1.0 - self.transition_effect))
                                 for i in range(3))
        else:
            final_color = base_color

        return current_state, final_color, smooth_amplitude


    # --- Drawing Methods ---

    def _draw_avatar(self, state: State, color: ColorTuple, amplitude: float) -> None:
        """Calls the appropriate drawing function based on animation style."""
        # Map style string to drawing method
        draw_func_map = {
            "circle": self._draw_circle_animation,
            "wave": self._draw_wave_animation,
            "particle": self._draw_particle_animation,
            "hologram": self._draw_hologram_animation,
        }
        draw_function = draw_func_map.get(self.animation_style, self._draw_circle_animation) # Default to circle

        # Call the selected drawing function
        try:
            draw_function(self.center_x, self.center_y, self.min_radius, color, state, amplitude)
        except Exception as e:
             logger.exception(f"Error during avatar drawing ({self.animation_style}): {e}")
             # Optionally draw a simple fallback if drawing fails?
             pygame.draw.circle(self.screen, self.colors[State.ERROR], (self.center_x, self.center_y), self.min_radius)

    def _draw_circle_animation(self, cx: int, cy: int, base_radius: int, color: ColorTuple, state: State, amplitude: float) -> None:
        """Basic circle animation style."""
        pulse = (math.sin(self.pulse_phase) + 1) / 2 # 0 to 1
        radius = base_radius
        if state == State.SPEAKING:
            radius += int(amplitude * (self.max_radius_factor * base_radius * 0.5)) # Scaled effect
        elif state == State.IDLE:
             radius += int(pulse * 5) # Gentle pulse

        radius = max(base_radius // 2, radius) # Ensure minimum size

        # Draw main circle
        pygame.draw.circle(self.screen, color, (cx, cy), radius)
        # Draw simple glow ring
        self._draw_glow(cx, cy, radius + 5, color, 100)


    def _draw_wave_animation(self, cx: int, cy: int, base_radius: int, color: ColorTuple, state: State, amplitude: float) -> None:
        """Wave-based animation with rings."""
        pulse = (math.sin(self.pulse_phase) + 1) / 2
        radius = base_radius + int(pulse * 5)
        if state == State.SPEAKING:
             radius += int(amplitude * 15) # Add amplitude effect
        radius = max(base_radius // 2, radius)

        pygame.draw.circle(self.screen, color, (cx, cy), radius)

        num_rings = 3
        max_ring_radius = base_radius * self.max_radius_factor * 0.8

        if state == State.SPEAKING:
            # Rings expand with amplitude
            for i in range(num_rings):
                ring_rad = radius + int(amplitude * max_ring_radius * ((i + 1) / num_rings))
                alpha = max(0, int(150 * (1 - amplitude) * (1 - i / num_rings)))
                if alpha > 10:
                    pygame.draw.circle(self.screen, color + (alpha,), (cx, cy), ring_rad, max(1, 3 - i))
        elif state == State.LISTENING:
             # Rings expand and fade cyclically
             for i in range(num_rings):
                 ring_phase = (self.pulse_phase * 1.5 + i * (math.pi / num_rings)) % (math.pi * 2)
                 ring_rad = base_radius + int(abs(math.sin(ring_phase)) * max_ring_radius * 0.8)
                 alpha = max(0, int(150 * (1 - abs(math.sin(ring_phase)))))
                 if alpha > 10 and ring_rad > base_radius:
                      pygame.draw.circle(self.screen, color + (alpha,), (cx, cy), ring_rad, 2)
        else: # Idle, Thinking, etc.
            # Single subtle pulsing ring
            ring_rad = radius + int(pulse * 15)
            alpha = max(0, int(100 - pulse * 80))
            if alpha > 10:
                 pygame.draw.circle(self.screen, color + (alpha,), (cx, cy), ring_rad, 1)


    def _draw_particle_animation(self, cx: int, cy: int, base_radius: int, color: ColorTuple, state: State, amplitude: float) -> None:
        """Particle-based animation."""
        if np is None: # Guard if numpy failed import
             self._draw_circle_animation(cx, cy, base_radius, color, state, amplitude)
             return

        pulse = (math.sin(self.pulse_phase) + 1) / 2
        radius = base_radius + int(pulse * 5)
        if state == State.SPEAKING:
             radius += int(amplitude * 20)
        radius = max(base_radius // 2, radius)

        # Draw core circle and glow
        pygame.draw.circle(self.screen, color, (cx, cy), radius)
        self._draw_glow(cx, cy, radius + 10, color, 150)

        # Update and draw particles
        self._update_particles(cx, cy, radius, color, state, amplitude)
        for p in self.particles:
            # Ensure alpha is valid before creating color tuple
            alpha = max(0, min(255, int(p["alpha"])))
            # Check if color already has alpha
            p_color = p["color"][:3] + (alpha,) if len(p["color"]) == 4 else p["color"] + (alpha,)

            # Draw particle using pygame.draw.circle for simplicity
            # Using surfaces for each particle can be slow
            try:
                pygame.draw.circle(self.screen, p_color, (int(p["x"]), int(p["y"])), int(p["size"]))
            except ValueError as e:
                 logger.warning(f"Invalid color for particle draw: {p_color}, Error: {e}")
            except TypeError as e:
                 logger.warning(f"Invalid position/size for particle draw: x={p['x']}, y={p['y']}, size={p['size']}, Error: {e}")


    def _update_particles(self, cx: int, cy: int, radius: int, color: ColorTuple, state: State, amplitude: float) -> None:
        """Update particle positions and properties for particle animation."""
        dt = self.clock.get_time() / 1000.0 if self.clock else 0.016 # Delta time in seconds

        # Remove faded particles
        self.particles = [p for p in self.particles if p["alpha"] > 0]

        # Add new particles based on state
        spawn_prob = 0.0
        max_state_particles = 20
        if state == State.IDLE:
            spawn_prob = 0.03
            max_state_particles = 15
        elif state == State.LISTENING:
            spawn_prob = 0.1
            max_state_particles = 30
        elif state == State.THINKING:
            spawn_prob = 0.08
            max_state_particles = 40
        elif state == State.SPEAKING:
             spawn_prob = 0.1 + (amplitude * 0.4) # Spawn more with higher amplitude
             max_state_particles = self.max_particles

        if len(self.particles) < max_state_particles and random.random() < spawn_prob:
            angle = random.uniform(0, 2 * math.pi)
            dist = radius * random.uniform(1.0, 1.5)
            speed = random.uniform(10, 30)
            size = random.uniform(1, 3)
            alpha = random.uniform(150, 220)
            decay = random.uniform(50, 100) # Alpha decay per second

            px = cx + math.cos(angle) * dist
            py = cy + math.sin(angle) * dist
            vx = math.cos(angle) * speed
            vy = math.sin(angle) * speed

            if state == State.LISTENING:
                # Move towards center
                 vx *= -1.5
                 vy *= -1.5
                 decay *= 1.5
            elif state == State.THINKING:
                 # Orbiting motion (simple tangential velocity)
                 tangent_angle = angle + math.pi / 2
                 orbit_speed = random.uniform(20, 40)
                 vx = math.cos(tangent_angle) * orbit_speed
                 vy = math.sin(tangent_angle) * orbit_speed
                 decay *= 0.8 # Live longer
            elif state == State.SPEAKING:
                 # Burst outwards, faster with amplitude
                 speed += amplitude * 50
                 vx = math.cos(angle) * speed
                 vy = math.sin(angle) * speed
                 size += amplitude * 2
                 decay += amplitude * 50


            self.particles.append({
                "x": px, "y": py, "vx": vx, "vy": vy,
                "size": size, "color": color, "alpha": alpha, "decay": decay
            })


        # Update existing particles
        for p in self.particles:
             p["x"] += p["vx"] * dt
             p["y"] += p["vy"] * dt
             p["alpha"] -= p["decay"] * dt

             # Optional: Add drag/friction
             # p["vx"] *= 0.98
             # p["vy"] *= 0.98

             # Optional: Bounce off edges (crude)
             # if not (0 < p["x"] < self.width): p["vx"] *= -1
             # if not (0 < p["y"] < self.height): p["vy"] *= -1


    def _draw_hologram_animation(self, cx: int, cy: int, base_radius: int, color: ColorTuple, state: State, amplitude: float) -> None:
        """Hologram-style animation with scan lines and effects."""
        if np is None: # Guard if numpy failed import
             self._draw_circle_animation(cx, cy, base_radius, color, state, amplitude)
             return

        pulse = (math.sin(self.pulse_phase) + 1) / 2
        radius = base_radius + int(pulse * 8)
        if state == State.SPEAKING:
             radius += int(amplitude * 25)
        radius = max(base_radius, radius) # Ensure minimum size

        # Create a dedicated surface for the hologram effect for better alpha blending
        holo_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        # Draw core circle with fading edge
        steps = 10
        for i in range(steps):
            r = radius * (1 - i / steps)
            alpha = int(200 * (1 - i / steps)**2)
            if r > 0 and alpha > 0:
                 pygame.draw.circle(holo_surface, color + (alpha,), (cx, cy), int(r))


        # Scan lines effect
        num_scan_lines = 30
        line_height = 2
        scan_speed = 150 # Pixels per second
        scan_pos = (time.monotonic() * scan_speed) % (self.height + line_height * num_scan_lines) # Loop position
        for i in range(num_scan_lines):
             y = (scan_pos - i * (self.height / num_scan_lines)) % self.height
             alpha = int(50 * (1 - abs(cy - y) / (self.height / 2))**2) # Fade near edges
             alpha = max(0, min(50, alpha))
             if alpha > 5:
                 pygame.draw.rect(holo_surface, color + (alpha,), pygame.Rect(0, int(y), self.width, line_height))

        # Glitches (more frequent when speaking or transitioning)
        glitch_prob = 0.01 + (amplitude * 0.1) if state == State.SPEAKING else 0.01
        if self.transition_effect > 0.5: glitch_prob += 0.1

        if random.random() < glitch_prob:
             num_glitches = random.randint(1, 5)
             for _ in range(num_glitches):
                 glitch_y = random.randint(0, self.height - 2)
                 glitch_x = random.randint(0, self.width // 2)
                 glitch_w = random.randint(self.width // 4, self.width // 2)
                 glitch_h = random.randint(1, 3)
                 glitch_alpha = random.randint(80, 150)
                 try:
                     pygame.draw.rect(holo_surface, color + (glitch_alpha,), pygame.Rect(glitch_x, glitch_y, glitch_w, glitch_h))
                 except ValueError as e:
                     logger.warning(f"Invalid color for glitch draw: {color + (glitch_alpha,)}, Error: {e}")


        # Orbiting elements (simple dots)
        num_orbiters = 5
        orbit_radius = radius * 1.3
        for i in range(num_orbiters):
             angle = self.pulse_phase * 0.8 + i * (2 * math.pi / num_orbiters)
             ox = cx + int(math.cos(angle) * orbit_radius)
             oy = cy + int(math.sin(angle) * orbit_radius)
             pygame.draw.circle(holo_surface, color + (180,), (ox, oy), 2)

        # Blit the complete hologram surface onto the main screen
        self.screen.blit(holo_surface, (0, 0))


    def _draw_glow(self, cx: int, cy: int, radius: int, color: ColorTuple, base_alpha: int) -> None:
        """Draws a simple glow effect around a center point."""
        if radius <= 0 or base_alpha <= 0: return
        try:
            # Use integer radius for surface creation
            radius_int = max(1, int(radius))
            # Create a surface slightly larger than the glow radius
            surface_size = radius_int * 2
            glow_surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)

            # Draw concentric circles with decreasing alpha
            steps = 5
            for i in range(steps):
                r = radius_int * (1 - i / steps)
                alpha = int(base_alpha * (1 - i / steps)**2) # Exponential fade
                if r > 0 and alpha > 0:
                    # Ensure alpha is within valid range 0-255
                    valid_alpha = max(0, min(255, alpha))
                    pygame.draw.circle(glow_surface, color + (valid_alpha,), (radius_int, radius_int), int(r))

            # Blit the glow surface centered at (cx, cy)
            self.screen.blit(glow_surface, (cx - radius_int, cy - radius_int))
        except (pygame.error, ValueError, OverflowError) as e:
             logger.warning(f"Error drawing glow effect (radius={radius}, alpha={base_alpha}): {e}")


    def _draw_status_text(self) -> None:
        """Draw the current status text with fade effect."""
        if not self.show_status_text or not self.status_text or self.status_alpha <= 0 or self.font is None:
            return

        try:
            # Render text with current alpha
            # Pygame fonts don't handle alpha directly in render, need surface trick
            text_surface = self.font.render(self.status_text, True, (255, 255, 255)) # Render white
            text_surface.set_alpha(self.status_alpha) # Set alpha on the surface

            text_rect = text_surface.get_rect(center=(self.center_x, self.height - 30)) # Position near bottom center
            self.screen.blit(text_surface, text_rect)
        except Exception as e:
            logger.error(f"Error rendering status text: {e}")


    def _draw_error_message(self) -> None:
        """Draw the stored error message when in ERROR state."""
        if not self.state_manager.is_state(State.ERROR) or self.font is None:
            return

        error_message = self.state_manager.get_error_message()
        if not error_message:
            error_message = "Unknown Error" # Default message if none provided

        try:
            # Simple red text display for error
            error_color = self.colors[State.ERROR]
            text_surface = self.font.render(f"ERROR: {error_message}", True, error_color)
            # Position error message (e.g., below status text or centered)
            text_rect = text_surface.get_rect(center=(self.center_x, self.height - 50))
            self.screen.blit(text_surface, text_rect)
        except Exception as e:
            logger.error(f"Error rendering error message: {e}")


    def _draw_debug_overlay(self, state: State, amplitude: float) -> None:
        """Draw debug information overlay."""
        if not self.debug_overlay or self.debug_font is None or self.clock is None:
            return

        try:
            # Use a list of lines for easy rendering
            lines = [
                f"State: {state.name}",
                f"Amplitude: {amplitude:.4f}",
                f"FPS: {self.clock.get_fps():.1f}",
                f"History: {len(self.amplitude_history)}/{self.history_max_length}",
                f"Particles: {len(self.particles)}",
                f"Style: {self.animation_style}",
            ]

            y_pos = 10
            for i, line in enumerate(lines):
                text_surface = self.debug_font.render(line, True, (200, 200, 200)) # Light gray text
                self.screen.blit(text_surface, (10, y_pos + i * 18))

        except Exception as e:
             logger.error(f"Error rendering debug overlay: {e}")

    # --- Main Loop ---
    def run(self) -> None:
        """Main loop for the Pygame avatar display thread."""
        if not self._init_pygame():
            logger.error("AvatarDisplay thread exiting due to Pygame initialization failure.")
            self._cleanup()
            return # Stop thread if Pygame init fails

        logger.info("AvatarDisplay thread started.")
        while not self.stop_event.is_set():
            # --- Input Handling ---
            self._handle_input()

            # --- Data Update ---
            self._update_amplitude()

            # --- State Update & Effects ---
            current_state, current_color, smooth_amplitude = self._update_state_and_effects()

            # --- Drawing ---
            if self.screen:
                try:
                    # 1. Fill background
                    self.screen.fill(self.bg_color)

                    # 2. Draw avatar based on style
                    self._draw_avatar(current_state, current_color, smooth_amplitude)

                    # 3. Draw status text (if enabled and visible)
                    self._draw_status_text()

                    # 4. Draw error message (if in error state)
                    self._draw_error_message()

                    # 5. Draw debug overlay (if enabled)
                    if self.debug_overlay:
                        self._draw_debug_overlay(current_state, smooth_amplitude)

                    # 6. Update the display
                    pygame.display.flip()

                except pygame.error as e:
                     logger.error(f"Pygame error during drawing loop: {e}")
                     # Consider attempting to recover or just logging
                except Exception as e:
                     logger.exception(f"Unexpected error during drawing loop: {e}")
                     # Maybe set error state? Depends if drawing errors are critical.


            # --- Frame Rate Control ---
            if self.clock:
                self.clock.tick(self.fps)
            else:
                 time.sleep(1.0 / self.fps if self.fps > 0 else 0.1) # Fallback sleep


        logger.info("AvatarDisplay thread stopping...")
        self._cleanup()
        logger.info("AvatarDisplay thread finished.")

    def _cleanup(self) -> None:
        """Clean up Pygame resources."""
        logger.info("Cleaning up AvatarDisplay resources...")
        # Clear caches if needed (e.g., glow surfaces)
        self.glow_surfaces.clear()
        # Quit Pygame modules
        if self._pygame_initialized:
             pygame.font.quit()
             pygame.quit()
             self._pygame_initialized = False
             logger.info("Pygame quit.")
