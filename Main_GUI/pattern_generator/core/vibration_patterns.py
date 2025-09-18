#!/usr/bin/env python3
import time
import math
import random

class VibrationPattern:
    """Base class for all vibration patterns"""
    def __init__(self, name, description):
        self.name = name
        self.description = description
        self.api = None
        self.stop_flag = False
        self.active_actuators = set()
    
    def set_api(self, api):
        self.api = api
    
    def stop(self):
        self.stop_flag = True
        self.stop_all_active_actuators()
    
    def stop_all_active_actuators(self):
        if self.api:
            for addr in self.active_actuators:
                self.api.send_command(addr, 0, 0, 0)
            self.active_actuators.clear()
    
    def start_actuator(self, addr, intensity, frequency):
        if self.api:
            self.active_actuators.add(addr)
            return self.api.send_command(addr, intensity, frequency, 1)
        return False
    
    def stop_actuator(self, addr):
        if self.api:
            self.active_actuators.discard(addr)
            return self.api.send_command(addr, 0, 0, 0)
        return False
    
    def execute(self, **kwargs):
        raise NotImplementedError

class SinglePulsePattern(VibrationPattern):
    def __init__(self):
        super().__init__("Single Pulse", "Single vibration pulse on selected actuators")
    
    def execute(self, actuators, intensity, frequency, duration):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        for addr in actuators:
            self.start_actuator(addr, intensity, frequency)
        
        start_time = time.time()
        while time.time() - start_time < duration and not self.stop_flag:
            time.sleep(0.1)
        
        self.stop_all_active_actuators()
        return True

class WavePattern(VibrationPattern):
    def __init__(self):
        super().__init__("Wave", "Wave pattern moving across actuators")
    
    def execute(self, actuators, intensity, frequency, duration, wave_speed=0.5):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        actuators = sorted(actuators)
        step_duration = wave_speed / len(actuators) if actuators else 0.1
        total_time = 0
        
        while total_time < duration and not self.stop_flag:
            for i, addr in enumerate(actuators):
                if self.stop_flag:
                    break
                
                self.start_actuator(addr, intensity, frequency)
                if i > 0:
                    self.stop_actuator(actuators[i-1])
                
                time.sleep(step_duration)
                total_time += step_duration
                
                if total_time >= duration:
                    break
        
        self.stop_all_active_actuators()
        return True

class PulseTrainPattern(VibrationPattern):
    def __init__(self):
        super().__init__("Pulse Train", "Repeated pulses with on/off intervals")
    
    def execute(self, actuators, intensity, frequency, duration, pulse_on=0.2, pulse_off=0.3):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        total_time = 0
        
        while total_time < duration and not self.stop_flag:
            # Turn on
            for addr in actuators:
                self.start_actuator(addr, intensity, frequency)
            
            start_time = time.time()
            while time.time() - start_time < pulse_on and not self.stop_flag:
                time.sleep(0.01)
            total_time += pulse_on
            
            if total_time >= duration or self.stop_flag:
                break
            
            # Turn off
            for addr in actuators:
                self.stop_actuator(addr)
            
            start_time = time.time()
            while time.time() - start_time < pulse_off and not self.stop_flag:
                time.sleep(0.01)
            total_time += pulse_off
        
        self.stop_all_active_actuators()
        return True

class FadePattern(VibrationPattern):
    def __init__(self):
        super().__init__("Fade", "Gradual fade in and out")
    
    def execute(self, actuators, max_intensity, frequency, duration, fade_steps=10):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        fade_duration = duration / (2 * fade_steps)
        
        # Fade in
        for step in range(fade_steps + 1):
            if self.stop_flag:
                break
            
            intensity = int((step / fade_steps) * max_intensity)
            for addr in actuators:
                if intensity > 0:
                    self.start_actuator(addr, intensity, frequency)
                else:
                    self.stop_actuator(addr)
            
            start_time = time.time()
            while time.time() - start_time < fade_duration and not self.stop_flag:
                time.sleep(0.01)
        
        # Fade out
        for step in range(fade_steps, -1, -1):
            if self.stop_flag:
                break
            
            intensity = int((step / fade_steps) * max_intensity)
            for addr in actuators:
                if intensity > 0:
                    self.start_actuator(addr, intensity, frequency)
                else:
                    self.stop_actuator(addr)
            
            start_time = time.time()
            while time.time() - start_time < fade_duration and not self.stop_flag:
                time.sleep(0.01)
        
        self.stop_all_active_actuators()
        return True

class CircularPattern(VibrationPattern):
    def __init__(self):
        super().__init__("Circular", "Circular rotation pattern")
    
    def execute(self, actuators, intensity, frequency, duration, rotation_speed=1.0):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        actuators = sorted(actuators)
        if len(actuators) < 2:
            return self._single_pulse_fallback(actuators, intensity, frequency, duration)
        
        step_duration = rotation_speed / len(actuators)
        total_time = 0
        current_index = 0
        
        while total_time < duration and not self.stop_flag:
            for addr in actuators:
                self.stop_actuator(addr)
            
            self.start_actuator(actuators[current_index], intensity, frequency)
            
            start_time = time.time()
            while time.time() - start_time < step_duration and not self.stop_flag:
                time.sleep(0.01)
            
            total_time += step_duration
            current_index = (current_index + 1) % len(actuators)
        
        self.stop_all_active_actuators()
        return True
    
    def _single_pulse_fallback(self, actuators, intensity, frequency, duration):
        for addr in actuators:
            self.start_actuator(addr, intensity, frequency)
        
        start_time = time.time()
        while time.time() - start_time < duration and not self.stop_flag:
            time.sleep(0.1)
        
        self.stop_all_active_actuators()
        return True

class RandomPattern(VibrationPattern):
    def __init__(self):
        super().__init__("Random", "Random actuator activation")
    
    def execute(self, actuators, intensity, frequency, duration, change_interval=0.3):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        total_time = 0
        
        while total_time < duration and not self.stop_flag:
            for addr in actuators:
                self.stop_actuator(addr)
            
            num_active = random.randint(1, max(1, len(actuators) // 2))
            active_actuators = random.sample(actuators, num_active)
            
            for addr in active_actuators:
                self.start_actuator(addr, intensity, frequency)
            
            start_time = time.time()
            while time.time() - start_time < change_interval and not self.stop_flag:
                time.sleep(0.01)
            
            total_time += change_interval
        
        self.stop_all_active_actuators()
        return True

class SineWavePattern(VibrationPattern):
    def __init__(self):
        super().__init__("Sine Wave", "Sine wave intensity modulation")
    
    def execute(self, actuators, max_intensity, frequency, duration, sine_frequency=2.0):
        if not self.api:
            return False
        
        self.active_actuators.clear()
        start_time = time.time()
        
        while time.time() - start_time < duration and not self.stop_flag:
            current_time = time.time() - start_time
            sine_value = math.sin(2 * math.pi * sine_frequency * current_time)
            intensity = int(max_intensity * (sine_value + 1) / 2)
            
            for addr in actuators:
                if intensity > 0:
                    self.start_actuator(addr, intensity, frequency)
                else:
                    self.stop_actuator(addr)
            
            time.sleep(0.05)
        
        self.stop_all_active_actuators()
        return True