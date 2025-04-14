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
        
        # Display elements
        self.font = None
        self.status_text = ""
        self.status_alpha = 0  # For fade effect

    def run(self):
        """Main loop for the Pygame avatar display thread."""
        try:
            pygame.init()
            # Set display mode - consider flags like FULLSCREEN or NOFRAME for kiosk
            self.screen = pygame.display.set_mode(
                (config.AVATAR_WINDOW_WIDTH, config.AVATAR_WINDOW_HEIGHT)
                # pygame.FULLSCREEN | pygame.NOFRAME # Example flags for kiosk
            )
            pygame.display.set_caption("Project EchoCore Avatar")
            self.clock = pygame.time.Clock()
            self.font = pygame.font.SysFont("Arial", 18)  # Initialize font for status text
            logger.info("Pygame initialized.")
            self.running = True
        except pygame.error as e:
            logger.error(f"Error initializing Pygame: {e}")
            logger.warning("Ensure display environment is set up (e.g., X11 or KMSDRM on RPi).")
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
            self._draw_status_text()
            pygame.display.flip()

            # --- Update Effects ---
            self._update_effects()

            # --- Frame Rate Control ---
            self.clock.tick(config.AVATAR_FPS)

        self._cleanup()

    def _draw_enhanced_avatar(self, state):
        """Draws an enhanced avatar with animations based on state and amplitude."""
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
        
        # Different visualizations based on state
        if state == State.IDLE:
            # Gentle pulsing in idle state
            pulse = (math.sin(self.pulse_phase) + 1) / 2  # Value between 0 and 1
            radius = config.AVATAR_MIN_RADIUS + int(pulse * 10)
            
            # Draw main circle
            pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
            
            # Draw outer glow ring
            for i in range(5):
                alpha = max(0, int(150 - i * 30))
                glow_radius = radius + i * 2
                glow_surface = pygame.Surface((glow_radius*2, glow_radius*2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surface, color + (alpha,), (glow_radius, glow_radius), glow_radius)
                self.screen.blit(glow_surface, (center_x - glow_radius, center_y - glow_radius))
                
        elif state == State.LISTENING:
            # Ripple effect for listening
            num_rings = 3
            max_radius = config.AVATAR_MIN_RADIUS * 3
            
            # Draw main circle
            pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
            
            # Draw ripple rings
            for i in range(num_rings):
                ring_phase = (self.pulse_phase + i * (math.pi / num_rings)) % (math.pi * 2)
                ring_size = abs(math.sin(ring_phase)) * max_radius
                ring_alpha = int(150 * (1 - (ring_size / max_radius)))
                
                if ring_size > radius:
                    ring_surface = pygame.Surface((ring_size*2, ring_size*2), pygame.SRCALPHA)
                    pygame.draw.circle(ring_surface, color + (ring_alpha,), (ring_size, ring_size), ring_size, 2)
                    self.screen.blit(ring_surface, (center_x - ring_size, center_y - ring_size))
            
        elif state == State.THINKING or state == State.PROCESSING_STT:
            # Orbiting particles effect for thinking
            radius = config.AVATAR_MIN_RADIUS + 5
            
            # Draw main circle
            pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
            
            # Draw orbiting particles
            orbit_radius = radius * 2
            num_particles = 8
            for i in range(num_particles):
                angle = self.pulse_phase + (i * (2 * math.pi / num_particles))
                particle_x = center_x + int(math.cos(angle) * orbit_radius)
                particle_y = center_y + int(math.sin(angle) * orbit_radius)
                particle_size = 3 + int(math.sin(angle * 2) * 2)
                
                pygame.draw.circle(self.screen, color, (particle_x, particle_y), particle_size)
                
        elif state == State.SPEAKING:
            # Sound wave visualization for speaking
            # Scale radius based on amplitude
            radius = config.AVATAR_MIN_RADIUS + int(smooth_amplitude * (config.AVATAR_MAX_RADIUS_FACTOR * config.AVATAR_MIN_RADIUS))
            radius = max(config.AVATAR_MIN_RADIUS, radius)
            
            # Draw main circle with flaring effect
            pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
            
            # Draw sound wave circles
            num_waves = 8
            wave_spacing = 5
            for i in range(num_waves):
                wave_radius = radius + (i * wave_spacing)
                wave_thickness = max(1, int(3 * (1 - (i / num_waves))))
                wave_alpha = max(30, int(150 * (1 - (i / num_waves))))
                
                # Modulate wave based on amplitude
                wave_mod = int(smooth_amplitude * 10 * math.sin(i + self.pulse_phase))
                wave_radius += wave_mod
                
                # Draw wave circle
                wave_surface = pygame.Surface((wave_radius*2, wave_radius*2), pygame.SRCALPHA)
                pygame.draw.circle(wave_surface, color + (wave_alpha,), (wave_radius, wave_radius), wave_radius, wave_thickness)
                self.screen.blit(wave_surface, (center_x - wave_radius, center_y - wave_radius))
                
        elif state == State.SYNTHESIZING_TTS:
            # Loading animation for TTS synthesis
            radius = config.AVATAR_MIN_RADIUS + 5
            
            # Draw main circle
            pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
            
            # Draw rotating arc
            arc_radius = radius * 1.5
            arc_thickness = 3
            arc_length = math.pi  # Half circle
            
            for i in range(3):
                arc_angle = self.pulse_phase + (i * math.pi/1.5)
                arc_surface = pygame.Surface((arc_radius*2, arc_radius*2), pygame.SRCALPHA)
                pygame.draw.arc(
                    arc_surface, 
                    color + (200,),
                    pygame.Rect(0, 0, arc_radius*2, arc_radius*2),
                    arc_angle, 
                    arc_angle + arc_length,
                    arc_thickness
                )
                self.screen.blit(arc_surface, (center_x - arc_radius, center_y - arc_radius))
            
        elif state == State.ERROR:
            # Error state with warning flash
            pulse = (math.sin(self.pulse_phase * 3) + 1) / 2  # Faster pulsing
            radius = config.AVATAR_MIN_RADIUS + int(pulse * 15)
            
            # Draw main circle
            pygame.draw.circle(self.screen, color, (center_x, center_y), radius)
            
            # Draw X mark inside circle
            x_size = radius * 0.6
            x_thickness = 3
            pygame.draw.line(
                self.screen, 
                (255, 255, 255), 
                (center_x - x_size, center_y - x_size), 
                (center_x + x_size, center_y + x_size), 
                x_thickness
            )
            pygame.draw.line(
                self.screen, 
                (255, 255, 255), 
                (center_x + x_size, center_y - x_size), 
                (center_x - x_size, center_y + x_size), 
                x_thickness
            )
    
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

    def _cleanup(self):
        """Clean up Pygame resources."""
        logger.info("Cleaning up Avatar Display...")
        pygame.quit()
