# avatar_display.py
"""
Displays the visual avatar using Pygame.
Animates based on application state and audio amplitude.
"""
import threading
import queue
import time
import math
import logging
import pygame
import numpy as np
import random
import config
from state_manager import StateManager, State

# Setup logger
logger = logging.getLogger(__name__)

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
        
        # Enhanced avatar variables
        self.amplitude_history = []  # Store recent amplitude values for smoother visualization
        self.history_max_length = 20  # Number of amplitude values to retain
        self.particles = []  # For particle effect
        self.pulse_phase = 0  # For pulsing effect
        self.transition_effect = 0  # For state transition effects
        self.previous_state = None  # To detect state changes
        
        # Improved particle and glow effects
        self.max_particles = 50
        self.glow_surfaces = {}  # Cache for glow surfaces
        self.animation_style = config.AVATAR_ANIMATION_STYLE
        
        # Display elements
        self.font = None
        self.status_text = ""
        self.status_alpha = 0  # For fade effect

    def run(self):
        """Main loop for the Pygame avatar display thread."""
        try:
            pygame.init()
            # Set display mode - consider flags like FULLSCREEN or NOFRAME for kiosk
            display_flags = 0
            if config.AVATAR_FULLSCREEN:
                display_flags = pygame.FULLSCREEN
                
            self.screen = pygame.display.set_mode(
                (config.AVATAR_WINDOW_WIDTH, config.AVATAR_WINDOW_HEIGHT),
                display_flags
            )
            pygame.display.set_caption("Project EchoCore Avatar")
            self.clock = pygame.time.Clock()
            self.font = pygame.font.SysFont("Arial", 18)  # Initialize font for status text
            logger.info("Pygame initialized.")
            self.running = True
        except pygame.error as e:
            logger.error(f"Error initializing Pygame: {e}")
            logger.warning("Ensure display environment is set up (e.g., X11 or KMSDRM on RPi).")
            self.state_manager.set_state(State.ERROR, error_message=f"Pygame initialization failed: {e}")
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
                    amplitude = self.avatar_queue.get_nowait()
                    self.current_amplitude = amplitude
                    
                    # Add to history for smoother visualization
                    self.amplitude_history.append(amplitude)
                    if len(self.amplitude_history) > self.history_max_length:
                        self.amplitude_history.pop(0)
            except queue.Empty:
                pass # Keep the last known amplitude if queue is empty

            # --- Get Current State ---
            current_state = self.state_manager.get_state()
            
            # Check for state transition
            if current_state != self.previous_state:
                self.transition_effect = 1.0  # Start transition effect
                self.previous_state = current_state
                
                # Update status text based on state
                if current_state == State.IDLE:
                    self.status_text = "Ready"
                elif current_state == State.LISTENING:
                    self.status_text = "Listening..."
                elif current_state == State.PROCESSING_STT:
                    self.status_text = "Processing speech..."
                elif current_state == State.THINKING:
                    self.status_text = "Thinking..."
                elif current_state == State.SYNTHESIZING_TTS:
                    self.status_text = "Generating response..."
                elif current_state == State.SPEAKING:
                    self.status_text = "Speaking..."
                elif current_state == State.ERROR:
                    self.status_text = "Error occurred"
                
                # Make status visible
                self.status_alpha = 255

            # --- Drawing ---
            self.screen.fill(config.AVATAR_BACKGROUND_COLOR)
            self._draw_enhanced_avatar(current_state)
            
            # Draw status text if enabled
            if config.AVATAR_DISPLAY_STATUS_TEXT:
                self._draw_status_text()
            
            # Draw error message if in ERROR state
            if current_state == State.ERROR:
                self._draw_error_message()
            
            # Draw debug overlay if enabled
            if config.AVATAR_DEBUG_OVERLAY:
                self._draw_debug_overlay(current_state)
                
            pygame.display.flip()

            # --- Update Effects ---
            self._update_effects()

            # --- Frame Rate Control ---
            self.clock.tick(config.AVATAR_FPS)

        self._cleanup()

    def _draw_enhanced_avatar(self, state):
        """Draws an enhanced avatar with animations based on state and amplitude."""
        # Use the configured animation style
        animation_style = config.AVATAR_ANIMATION_STYLE
        
        # Get screen center coordinates
        center_x = config.AVATAR_WINDOW_WIDTH // 2
        center_y = config.AVATAR_WINDOW_HEIGHT // 2

        # Get smooth amplitude by averaging history
        smooth_amplitude = 0.0
        if self.amplitude_history:
            smooth_amplitude = sum(self.amplitude_history) / len(self.amplitude_history)

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

        # Apply transition effect to color
        if self.transition_effect > 0:
            # Create a brighter version of the color for the transition flash
            bright_color = tuple(min(c + 100, 255) for c in color)
            
            # Interpolate between bright and normal color based on transition effect
            color = tuple(int(bright_color[i] * self.transition_effect + color[i] * (1 - self.transition_effect)) 
                          for i in range(3))

        # Base radius calculation
        radius = config.AVATAR_MIN_RADIUS
        
        if animation_style == "circle":
            self._draw_circle_animation(center_x, center_y, radius, color, state, smooth_amplitude)
        elif animation_style == "wave":
            self._draw_wave_animation(center_x, center_y, radius, color, state, smooth_amplitude)
        elif animation_style == "particle":
            self._draw_particle_animation(center_x, center_y, radius, color, state, smooth_amplitude)
        elif animation_style == "hologram":
            self._draw_hologram_animation(center_x, center_y, radius, color, state, smooth_amplitude)
        else:
            # Default to circle if animation style is not recognized
            self._draw_circle_animation(center_x, center_y, radius, color, state, smooth_amplitude)

    def _draw_circle_animation(self, center_x, center_y, base_radius, color, state, smooth_amplitude):
        """Basic circle animation style."""
        # Gentle pulsing in idle state
        pulse = (math.sin(self.pulse_phase) + 1) / 2  # Value between 0 and 1
        
        # Adjust radius based on state and amplitude
        if state == State.IDLE:
            radius = base_radius + int(pulse * 10)
        elif state == State.SPEAKING:
            radius = base_radius + int(smooth_amplitude * (config.AVATAR_MAX_RADIUS_FACTOR * base_radius))
            radius = max(base_radius, radius)
        else:
            radius = base_radius + 5
        
        # Draw main circle
        pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
        
        # Draw simple glow ring
        glow_radius = radius + 5
        glow_surface = pygame.Surface((glow_radius*2, glow_radius*2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surface, color + (100,), (glow_radius, glow_radius), glow_radius)
        self.screen.blit(glow_surface, (center_x - glow_radius, center_y - glow_radius))

    def _draw_wave_animation(self, center_x, center_y, base_radius, color, state, smooth_amplitude):
        """Wave-based animation with rings."""
        # Adjust radius based on state and amplitude
        if state == State.SPEAKING:
            radius = base_radius + int(smooth_amplitude * (config.AVATAR_MAX_RADIUS_FACTOR * base_radius))
            radius = max(base_radius, radius)
        else:
            pulse = (math.sin(self.pulse_phase) + 1) / 2  # Value between 0 and 1
            radius = base_radius + int(pulse * 5)
        
        # Draw main circle
        pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
        
        # Draw wave rings based on state
        if state == State.IDLE:
            # Single subtle pulsing ring for idle
            ring_radius = radius + int(pulse * 15)
            ring_alpha = max(0, int(150 - pulse * 120))
            
            ring_surface = pygame.Surface((ring_radius*2, ring_radius*2), pygame.SRCALPHA)
            pygame.draw.circle(ring_surface, color + (ring_alpha,), (ring_radius, ring_radius), ring_radius, 2)
            self.screen.blit(ring_surface, (center_x - ring_radius, center_y - ring_radius))
            
        elif state == State.LISTENING:
            # Multiple expanding rings for listening
            num_rings = 3
            for i in range(num_rings):
                ring_phase = (self.pulse_phase + i * (math.pi / num_rings)) % (math.pi * 2)
                ring_size = base_radius + int(abs(math.sin(ring_phase)) * base_radius * 3)
                ring_alpha = int(150 * (1 - (ring_size / (base_radius * 4))))
                
                if ring_alpha > 0:
                    ring_surface = pygame.Surface((ring_size*2, ring_size*2), pygame.SRCALPHA)
                    pygame.draw.circle(ring_surface, color + (ring_alpha,), (ring_size, ring_size), ring_size, 2)
                    self.screen.blit(ring_surface, (center_x - ring_size, center_y - ring_size))
        
        elif state == State.SPEAKING:
            # Sound wave visualization rings
            num_waves = 5
            wave_spacing = 8
            for i in range(num_waves):
                wave_radius = radius + (i * wave_spacing)
                wave_mod = int(smooth_amplitude * 10 * math.sin(i + self.pulse_phase))
                wave_radius += wave_mod
                wave_alpha = max(30, int(150 * (1 - (i / num_waves))))
                
                wave_surface = pygame.Surface((wave_radius*2, wave_radius*2), pygame.SRCALPHA)
                pygame.draw.circle(wave_surface, color + (wave_alpha,), (wave_radius, wave_radius), wave_radius, 
                                max(1, int(3 * (1 - (i / num_waves)))))
                self.screen.blit(wave_surface, (center_x - wave_radius, center_y - wave_radius))

    def _draw_particle_animation(self, center_x, center_y, base_radius, color, state, smooth_amplitude):
        """Particle-based animation with improved alpha blending."""
        # Core circle
        if state == State.SPEAKING:
            radius = base_radius + int(smooth_amplitude * 20)
        else:
            pulse = (math.sin(self.pulse_phase) + 1) / 2
            radius = base_radius + int(pulse * 5)
        
        # Create the main avatar surface with transparency
        avatar_surface = pygame.Surface((config.AVATAR_WINDOW_WIDTH, config.AVATAR_WINDOW_HEIGHT), pygame.SRCALPHA)
        
        # Draw main circle on the avatar surface
        pygame.draw.circle(avatar_surface, color + (230,), (center_x, center_y), radius)
        
        # Draw glow effect on the avatar surface
        for i in range(3):
            glow_radius = radius + (i * 5)
            alpha = 120 - (i * 40)
            pygame.draw.circle(avatar_surface, color + (alpha,), (center_x, center_y), glow_radius, 2)
        
        # Update and draw particles
        self._update_particles(center_x, center_y, radius, color, state, smooth_amplitude)
        
        for particle in self.particles:
            # Draw each particle with its own transparency
            pygame.draw.circle(avatar_surface, particle["color"], 
                              (particle["x"], particle["y"]), 
                              particle["size"])
        
        # Blit the avatar surface to the screen
        self.screen.blit(avatar_surface, (0, 0))

    def _update_particles(self, center_x, center_y, radius, color, state, smooth_amplitude):
        """Update particle positions and properties for particle animation."""
        # Remove faded particles
        self.particles = [p for p in self.particles if p["alpha"] > 0]
        
        # Create new particles based on state
        if state == State.IDLE:
            # Slow-moving orbital particles in idle
            if len(self.particles) < 10 and random.random() < 0.05:
                angle = random.random() * math.pi * 2
                dist = radius * 2
                self.particles.append({
                    "x": center_x + math.cos(angle) * dist,
                    "y": center_y + math.sin(angle) * dist,
                    "size": random.randint(1, 3),
                    "speed_x": math.cos(angle + math.pi/2) * 0.5,
                    "speed_y": math.sin(angle + math.pi/2) * 0.5,
                    "color": color + (150,),
                    "alpha": 150,
                    "decay": 0.2
                })
        
        elif state == State.LISTENING:
            # Particles moving toward center during listening
            if len(self.particles) < 20 and random.random() < 0.1:
                angle = random.random() * math.pi * 2
                dist = random.randint(radius * 3, radius * 5)
                
                self.particles.append({
                    "x": center_x + math.cos(angle) * dist,
                    "y": center_y + math.sin(angle) * dist,
                    "size": random.randint(2, 4),
                    "speed_x": -math.cos(angle) * 1.0,
                    "speed_y": -math.sin(angle) * 1.0,
                    "color": color + (180,),
                    "alpha": 180,
                    "decay": 0.5
                })
        
        elif state == State.THINKING:
            # Orbiting particles during thinking
            if len(self.particles) < 30:
                angle = self.pulse_phase + random.random() * 0.2
                dist = radius * 2 + random.randint(-5, 5)
                
                orbit_speed = 0.02
                self.particles.append({
                    "x": center_x + math.cos(angle) * dist,
                    "y": center_y + math.sin(angle) * dist,
                    "size": random.randint(2, 4),
                    "speed_x": -math.sin(angle) * orbit_speed * dist,
                    "speed_y": math.cos(angle) * orbit_speed * dist,
                    "color": color + (200,),
                    "alpha": 200,
                    "decay": 1.0
                })
        
        elif state == State.SPEAKING:
            # Particles emitting outward based on amplitude
            if len(self.particles) < self.max_particles and random.random() < 0.1 + (smooth_amplitude * 0.3):
                angle = random.random() * math.pi * 2
                dist = radius * 1.1
                speed = 0.5 + smooth_amplitude * 2
                
                self.particles.append({
                    "x": center_x + math.cos(angle) * dist,
                    "y": center_y + math.sin(angle) * dist,
                    "size": random.randint(1, 3) + int(smooth_amplitude * 3),
                    "speed_x": math.cos(angle) * speed,
                    "speed_y": math.sin(angle) * speed,
                    "color": color + (180,),
                    "alpha": 180,
                    "decay": 1.0 + smooth_amplitude * 2
                })
        
        # Update existing particles
        for particle in self.particles:
            # Move particle
            particle["x"] += particle["speed_x"]
            particle["y"] += particle["speed_y"]
            
            # Fade particle
            particle["alpha"] -= particle["decay"]
            
            # Update color with new alpha
            particle_color = list(particle["color"])
            particle_color[3] = max(0, int(particle["alpha"]))
            particle["color"] = tuple(particle_color)

    def _draw_hologram_animation(self, center_x, center_y, base_radius, color, state, smooth_amplitude):
        """Hologram-style animation with scan lines and glitches."""
        # Create surface with alpha channel
        hologram_surface = pygame.Surface((config.AVATAR_WINDOW_WIDTH, config.AVATAR_WINDOW_HEIGHT), pygame.SRCALPHA)
        
        # Adjust radius based on state and amplitude
        if state == State.SPEAKING:
            radius = base_radius + int(smooth_amplitude * (config.AVATAR_MAX_RADIUS_FACTOR * base_radius))
            radius = max(base_radius, radius)
        else:
            pulse = (math.sin(self.pulse_phase) + 1) / 2
            radius = base_radius + int(pulse * 8)
        
        # Draw main circle with fading edge
        for i in range(radius, radius-10, -1):
            if i <= 0:
                break
            # Fade transparency toward edge
            alpha = min(255, int(230 * (i/radius)))
            pygame.draw.circle(hologram_surface, color + (alpha,), (center_x, center_y), i)
        
        # Draw holographic scan lines
        scan_line_count = 20
        scan_line_height = config.AVATAR_WINDOW_HEIGHT // scan_line_count
        scan_line_alpha = 30
        
        # Move scan line up and down
        scan_offset = int(math.sin(self.pulse_phase * 0.5) * 10)
        
        for i in range(scan_line_count):
            y_pos = i * scan_line_height + scan_offset
            # Skip lines that would be outside the window
            if y_pos < 0 or y_pos >= config.AVATAR_WINDOW_HEIGHT:
                continue
                
            # Draw scan line with alpha blending
            scan_line = pygame.Surface((config.AVATAR_WINDOW_WIDTH, 1), pygame.SRCALPHA)
            scan_line.fill((*color, scan_line_alpha))
            hologram_surface.blit(scan_line, (0, y_pos))
        
        # Add random glitches during state transitions or speaking
        if self.transition_effect > 0 or state == State.SPEAKING:
            glitch_count = 3 if self.transition_effect > 0 else int(smooth_amplitude * 5)
            for _ in range(glitch_count):
                # Create random horizontal glitch line
                glitch_y = random.randint(center_y - radius * 2, center_y + radius * 2)
                glitch_width = random.randint(10, 50)
                glitch_x = random.randint(center_x - radius, center_x + radius)
                
                glitch = pygame.Surface((glitch_width, 2), pygame.SRCALPHA)
                glitch_alpha = random.randint(100, 200)
                glitch.fill((*color, glitch_alpha))
                hologram_surface.blit(glitch, (glitch_x, glitch_y))
        
        # Draw hexagonal grid pattern for holographic effect
        hex_size = 10
        hex_alpha = 40
        hex_offset_x = center_x % hex_size
        hex_offset_y = center_y % hex_size
        
        # Only draw hexagons within a certain distance from center
        max_hex_dist = radius * 2.5
        
        for x in range(-int(max_hex_dist), int(max_hex_dist), hex_size):
            for y in range(-int(max_hex_dist), int(max_hex_dist), hex_size):
                # Offset every other row
                row_offset = (hex_size // 2) if (y // hex_size) % 2 == 0 else 0
                hex_x = center_x + x + row_offset
                hex_y = center_y + y
                
                # Calculate distance from center
                dist = math.sqrt((hex_x - center_x)**2 + (hex_y - center_y)**2)
                if dist <= max_hex_dist:
                    # Make hexes closer to edge more transparent
                    edge_factor = 1.0 - (dist / max_hex_dist)
                    hex_alpha_adjusted = int(hex_alpha * edge_factor)
                    
                    if hex_alpha_adjusted > 5:  # Only draw visible hexes
                        # Draw a small dot at hex grid points
                        pygame.draw.circle(hologram_surface, (*color, hex_alpha_adjusted), 
                                          (hex_x, hex_y), 1)
        
        # Draw outer rings
        ring_count = 2
        for i in range(ring_count):
            ring_radius = radius * (1.5 + (i * 0.5))
            ring_width = 1
            ring_alpha = int(100 * (1 - (i / ring_count)))
            
            # Add some variation based on pulse
            ring_variation = int(math.sin(self.pulse_phase + i) * 5)
            ring_radius += ring_variation
            
            pygame.draw.circle(hologram_surface, (*color, ring_alpha), 
                              (center_x, center_y), ring_radius, ring_width)
        
        # Add small orbiting dots for hologram tech feel
        orbit_count = 8
        for i in range(orbit_count):
            angle = self.pulse_phase + (i * (2 * math.pi / orbit_count))
            orbit_dist = radius * 1.2
            orbit_x = center_x + int(math.cos(angle) * orbit_dist)
            orbit_y = center_y + int(math.sin(angle) * orbit_dist)
            
            pygame.draw.circle(hologram_surface, (*color, 160), (orbit_x, orbit_y), 2)
        
        # Finally, blit the hologram surface to the screen
        self.screen.blit(hologram_surface, (0, 0))

    def _draw_status_text(self):
        """Draw the current status text with fade effect."""
        if self.status_text and self.status_alpha > 0:
            text_surface = self.font.render(self.status_text, True, (255, 255, 255, self.status_alpha))
            text_rect = text_surface.get_rect(center=(config.AVATAR_WINDOW_WIDTH // 2, config.AVATAR_WINDOW_HEIGHT - 30))
            
            # Create a surface with alpha channel for text
            text_surface_alpha = pygame.Surface(text_surface.get_size(), pygame.SRCALPHA)
            text_surface_alpha.fill((255, 255, 255, self.status_alpha))
            text_surface.blit(text_surface_alpha, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            
            self.screen.blit(text_surface, text_rect)

    def _draw_error_message(self):
        """Draw the current error message when in ERROR state."""
        if not self.state_manager.is_state(State.ERROR):
            return
            
        error_message = self.state_manager.get_error_message()
        if not error_message:
            return
            
        # Create text surfaces for multiline error message
        max_line_width = config.AVATAR_WINDOW_WIDTH - 40  # Padding
        lines = []
        
        # Split error message into lines that fit the width
        words = error_message.split()
        current_line = ""
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            test_surface = self.font.render(test_line, True, (255, 255, 255))
            
            if test_surface.get_width() <= max_line_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
                
        if current_line:
            lines.append(current_line)
        
        # Render each line
        y_pos = config.AVATAR_WINDOW_HEIGHT - (len(lines) * 25) - 40
        for line in lines:
            text_surface = self.font.render(line, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(config.AVATAR_WINDOW_WIDTH // 2, y_pos))
            self.screen.blit(text_surface, text_rect)
            y_pos += 25

    def _draw_debug_overlay(self, current_state):
        """Draw debug information overlay when enabled in config."""
        if not config.AVATAR_DEBUG_OVERLAY:
            return
            
        # Create a semi-transparent background for debug info
        debug_surface = pygame.Surface((300, 100), pygame.SRCALPHA)
        pygame.draw.rect(debug_surface, (0, 0, 0, 180), pygame.Rect(0, 0, 300, 100))
        
        # Add debug text lines
        debug_font = pygame.font.SysFont("Courier", 14)
        
        # State info
        state_text = debug_font.render(f"State: {current_state.name}", True, (255, 255, 255))
        debug_surface.blit(state_text, (10, 10))
        
        # Amplitude info
        amp_value = 0.0
        if self.amplitude_history:
            amp_value = sum(self.amplitude_history) / len(self.amplitude_history)
        amp_text = debug_font.render(f"Amplitude: {amp_value:.4f}", True, (255, 255, 255))
        debug_surface.blit(amp_text, (10, 30))
        
        # FPS info
        fps = self.clock.get_fps()
        fps_text = debug_font.render(f"FPS: {fps:.1f}", True, (255, 255, 255))
        debug_surface.blit(fps_text, (10, 50))
        
        # History length
        history_text = debug_font.render(f"History: {len(self.amplitude_history)}/{self.history_max_length}", True, (255, 255, 255))
        debug_surface.blit(history_text, (10, 70))
        
        # Blit the debug overlay onto the main screen
        self.screen.blit(debug_surface, (10, 10))

    def _get_glow_surface(self, radius, color, alpha):
        """Get a cached glow surface or create a new one."""
        # Create a unique key for this glow surface
        key = (radius, color, alpha)
        
        # Return cached surface if it exists
        if key in self.glow_surfaces:
            return self.glow_surfaces[key]
        
        # Create new surface
        surface_size = radius * 2
        surface = pygame.Surface((surface_size, surface_size), pygame.SRCALPHA)
        
        # Create radial gradient
        center = radius
        for i in range(radius, 0, -1):
            # Calculate alpha gradient from center to edge
            current_alpha = int(alpha * (i / radius))
            pygame.draw.circle(surface, color + (current_alpha,), (center, center), i)
        
        # Cache the surface
        self.glow_surfaces[key] = surface
        return surface

    def _update_effects(self):
        """Update animation effects."""
        # Update pulse phase
        self.pulse_phase += 0.05
        if self.pulse_phase > math.pi * 2:
            self.pulse_phase -= math.pi * 2
        
        # Update transition effect
        if self.transition_effect > 0:
            self.transition_effect -= 0.05
            if self.transition_effect < 0:
                self.transition_effect = 0
            
        # Update status text fade
        if self.status_alpha > 0:
            self.status_alpha -= 1
            if self.state_manager.is_state(State.LISTENING) or self.state_manager.is_state(State.SPEAKING):
                # Keep text visible for these states
                self.status_alpha = max(self.status_alpha, 180)
    
        # Clean up glow surface cache if it gets too large
        if len(self.glow_surfaces) > 100:  # Maximum number of cached surfaces
            # Keep only the 50 most recently used surfaces
            self.glow_surfaces = {k: self.glow_surfaces[k] for k in list(self.glow_surfaces.keys())[:50]}

    # Make sure to import random at the top of the file
    import random

    # Also, update the cleanup method to clean up the glow surfaces cache
    def _cleanup(self):
        """Clean up Pygame resources."""
        logger.info("Cleaning up Avatar Display...")
        # Clear glow surfaces cache
        self.glow_surfaces.clear()
        pygame.quit()
