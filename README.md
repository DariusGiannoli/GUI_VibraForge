# VibraForge GUI

# Authors: Darius Giannoli & Gabriel Taieb 

Haptic Graphical User Interface (GUI) for the VibraForge project of BingJian Huang

# Pattern Generator — Main GUI
---
### 1. Waveform Lab
Main control tab for testing actuators and playing waveforms.
- **Menu Bar → Connection**
  - **Scan Ports**: Detect available COM ports.
  - **Select Port**: Choose a port for your device.
  - **Connect**: Connect to the selected device.
- **Waveform Selection**
  - Load a waveform from file.
  - Create a new waveform in the **Waveform Designer**.
- **Global Parameters**
  - Select **Intensity** and **Frequency** for actuators when testing:
    - Single actuator test
    - Drawing playback
    - Timeline playback
- **Control**
  - **Preview**: Test actuator activations manually or preview pre-made patterns without hardware.
  - **Start**: Play on device (pre-made patterns or selected actuators).
  - **Pause**: Stop playback on the device.
---
### 2. Pattern Library
Save and replay patterns, both pre-made and custom.
- **Pre-Made Patterns**
  - Includes: Trio Burst, 3×3 Sweep, Back Ring, Pulse Train (8-act).
  - Select and play via the **Waveform Lab → Control** panel.
- **Custom Patterns**
  - Saved patterns created with the **Timeline**.
  - Play with either **Preview** or **Play on Device** buttons from the Timeline.
---
### 3. Drawing Library
Save, replay, and live-render freehand drawings using phantom rendering.
- **Parameters**
  - **Clear**: Clear canvas (drawing + phantoms).
  - **Save**: Save the current drawing.
  - **Draw**: Enable freehand drawing on canvas.
  - **Live Drawing**: When enabled and connected, drawings are played *immediately* on the device.
  - **High-Density Trajectory Creation**
    - **Max Phantoms**: Maximum number of phantoms placed along a stroke.
    - **Sampling Rate (ms)**: Minimum interval between phantom placements during drawing.
    - **Trajectory Mode (phantoms)**: Display phantoms on the canvas.
- **Drawing Library**
  - List of saved drawings that can be reloaded and replayed.
- **Draw Stroke Playback**
  - Uses frequency & intensity from **Waveform Lab → Global Parameters**.
  - **Total Time**: Total playback time of the stroke.
  - **Step Duration ≤ 69 ms**: Interval between consecutive bursts (stimulus onset asynchrony).
  - **Rendered**: Number of bursts generated after resampling.
  - **Phantom (3-Act)**: Phantom computation based on *Park et al. 2016*.
  - **Physical (nearest-1)**: Single-actuator mode for testing.
  - **Preview / Play Drawing / Stop**: Preview on canvas, play on device, or stop playback.
---
### 4. Canvas
Visual editor for actuator layouts.
- **General Parameters**
  - **Clear**: Deselect all actuators.
  - **All**: Select all actuators.
- **Designer**
  - Drag & drop actuators onto canvas.
  - Create one or more actuator chains.
  - Move individual actuators or groups together.
- **Layouts**
  - **3×3 Grid**: For testing drawings in a uniform grid.
  - **Back Layout (2-4-4-2)**: Simulates back-mounted actuators.
---
### 5. Timeline
Precise sequencer for actuator clips and advanced patterns.
- **Workflow**
  1. In **Waveform Lab**, select a waveform for a given actuator (from Designer Canvas).
  2. Set start and stop times.
  3. Add a clip for the selected actuator.
  4. Play preview or play on device.
  5. Save the sequence to **Pattern Library**.
  6. Remove clips individually or clear the entire timeline.
---
### 6. Waveform Designer
Advanced tool for creating and customizing waveforms.
- **Menu → Device**
  - Connect to a device (scan/select port).
  - Test a waveform on a specific actuator.
  - Select frequency code and click **Test Actuator**.
- **Menu → View**
  - Show frequency, amplitude, or both on the canvas.
  - Clear plot, hide logs.
  - Save the signal as CSV.
- **Modifiers**
  - Modify amplitude, timing, and ADSR envelopes.
---
### 7. Waveform Library Tab
- **Oscillators**
  - Double-click to load a built-in waveform with default parameters.
  - Drag & drop onto the canvas to customize parameters.
- **Customized Signals**
  - Save and reuse your custom waveforms.
---
### 8. Waveform Design Tab
- **Waveform Information**
  - Name, category, and description of the waveform.
- **Haptic File**
  - Import CSV waveforms.
  - Import `.haptic` files.
  - Create with Meta Haptics Studio.
- **Mathematic Generator**
  - Generate signals from equations.
  - Define frequency, duration, and sampling rate.
---
##  Summary
- **Waveform Lab** → load, preview, and play signals.
- **Pattern Library** → replay pre-made and custom patterns.
- **Drawing Library** → phantom drawing creation, saving, and live playback.
- **Canvas** → design actuator layouts.
- **Timeline** → precise sequencing and clip-based pattern design.
- **Waveform Designer** → advanced waveform editing and generation.
