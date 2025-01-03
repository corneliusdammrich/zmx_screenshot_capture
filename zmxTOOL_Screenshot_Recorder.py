import os
import sys  # Added for resource path handling
import json
import time
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import mss
from PIL import Image, ImageChops
from pynput import keyboard
import psutil
import traceback  # Added for detailed logging

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller.

    Parameters:
        relative_path (str): The relative path to the resource.

    Returns:
        str: The absolute path to the resource.
    """
    try:
        # PyInstaller creates a temporary folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class ScreenshotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("zmxTOOL Screen(shot) Recorder")  # Updated Title for Version 2.5
        self.root.geometry("800x600")  # Increased height to accommodate additional widgets
        self.root.resizable(False, False)

        # Initialize variables
        self.save_directory = tk.StringVar()
        self.file_format = tk.StringVar(value="png")
        self.interval = tk.DoubleVar(value=5.0)  # Supports fractional seconds
        self.selected_monitor = tk.StringVar()
        self.jpeg_quality = tk.IntVar(value=5)  # Default JPEG quality set to midpoint (5)

        # Movement Detection Variables
        self.movement_detection_mode = tk.StringVar(value="image")  # Modes: image, input, combined
        self.detect_keyboard = tk.BooleanVar(value=True)  # Default to detecting keyboard
        self.movement_sensitivity = tk.IntVar(value=2)  # Lowered default sensitivity (2%)

        # **New Variable for Motion Detection Toggle**
        self.enable_motion_detection = tk.BooleanVar(value=True)  # Motion detection enabled by default

        self.is_running = False
        self.thread = None
        self.stop_event = threading.Event()
        self.counter = 1  # Initialize counter

        # Initialize log file path and counter file path
        self.log_file = None
        self.counter_file = None

        # Previous screenshot for image-based movement detection
        self.previous_image = None

        # Flags for input activity
        self.input_activity = False
        self.input_lock = threading.Lock()

        # **Modified: Settings file path using resource_path**
        self.settings_file = resource_path("settings.json")

        # Initialize ttk styles
        style = ttk.Style()
        style.theme_use('default')  # Use the default theme to ensure style changes are applied

        # Define styles for different CPU usage levels
        style.configure("green.Horizontal.TProgressbar", foreground='green', background='green')
        style.configure("orange.Horizontal.TProgressbar", foreground='orange', background='orange')
        style.configure("red.Horizontal.TProgressbar", foreground='red', background='red')

        # Build GUI
        self.create_widgets()

        # Load user preferences
        self.load_settings()

        # Populate monitor list
        self.populate_monitors()

        # Note: CPU Monitoring will start when capturing starts

    def create_widgets(self):
        padding = {'padx': 10, 'pady': 5}

        # Save Directory
        dir_frame = ttk.Frame(self.root)
        dir_frame.pack(fill='x', **padding)

        dir_label = ttk.Label(dir_frame, text="Save Directory:")
        dir_label.pack(side='left')

        dir_entry = ttk.Entry(dir_frame, textvariable=self.save_directory, width=40)
        dir_entry.pack(side='left', padx=(5, 5))

        dir_button = ttk.Button(dir_frame, text="Browse", command=self.browse_directory)
        dir_button.pack(side='left')

        # File Format
        format_frame = ttk.Frame(self.root)
        format_frame.pack(fill='x', **padding)

        format_label = ttk.Label(format_frame, text="File Format:")
        format_label.pack(side='left')

        format_options = ["png", "jpg"]
        format_menu = ttk.OptionMenu(format_frame, self.file_format, self.file_format.get(), *format_options, command=self.on_format_change)
        format_menu.pack(side='left', padx=(5, 5))

        # JPEG Quality Slider (Initially Hidden and Positioned Below File Format)
        self.jpeg_quality_frame = ttk.Frame(self.root)
        self.jpeg_quality_label = ttk.Label(self.jpeg_quality_frame, text="JPEG Quality:")
        self.jpeg_quality_label.pack(side='left')

        # Slider with 10 steps from 1 to 10 using ttk.Scale for consistency
        self.jpeg_quality_slider = ttk.Scale(
            self.jpeg_quality_frame,
            from_=1,
            to=10,
            orient='horizontal',
            variable=self.jpeg_quality,
            command=self.on_quality_change,
            length=200
        )
        self.jpeg_quality_slider.pack(side='left', padx=(5, 5), fill='x', expand=True)

        # Display the current slider value
        self.jpeg_quality_value_label = ttk.Label(self.jpeg_quality_frame, textvariable=self.jpeg_quality)
        self.jpeg_quality_value_label.pack(side='left', padx=(5, 0))

        # Initially hide the JPEG quality slider
        self.jpeg_quality_frame.pack_forget()

        # Interval Time
        interval_frame = ttk.Frame(self.root)
        interval_frame.pack(fill='x', **padding)

        interval_label = ttk.Label(interval_frame, text="Interval (seconds):")
        interval_label.pack(side='left')

        # Replace Entry with Spinbox for 0.1 increments
        interval_spinbox = ttk.Spinbox(
            interval_frame,
            textvariable=self.interval,
            from_=0.1,
            to=60.0,
            increment=0.1,
            format="%.1f",
            width=10
        )
        interval_spinbox.pack(side='left', padx=(5, 5))
        interval_spinbox.set(5.0)  # Default value

        # Movement Detection Mode Selection
        mode_frame = ttk.Frame(self.root)
        mode_frame.pack(fill='x', **padding)

        mode_label = ttk.Label(mode_frame, text="Movement Detection Mode:")
        mode_label.pack(side='left')

        mode_options = [("Image-Based", "image"), ("Input-Based", "input"), ("Combined", "combined")]
        for text, mode in mode_options:
            rb = ttk.Radiobutton(mode_frame, text=text, variable=self.movement_detection_mode, value=mode, command=self.on_mode_change)
            rb.pack(side='left', padx=(10, 0))

        # **New: Motion Detection Toggle Checkbutton**
        detection_toggle_frame = ttk.Frame(self.root)
        detection_toggle_frame.pack(fill='x', **padding)

        detection_toggle_label = ttk.Label(detection_toggle_frame, text="Motion Detection:")
        detection_toggle_label.pack(side='left')

        detection_toggle_checkbox = ttk.Checkbutton(
            detection_toggle_frame,
            text="Enable",
            variable=self.enable_motion_detection,
            command=self.on_detection_toggle
        )
        detection_toggle_checkbox.pack(side='left', padx=(5, 0))

        # Movement Sensitivity Slider
        sensitivity_frame = ttk.Frame(self.root)
        sensitivity_frame.pack(fill='x', **padding)

        sensitivity_label = ttk.Label(sensitivity_frame, text="Movement Sensitivity (%):")
        sensitivity_label.pack(side='left')

        self.sensitivity_slider = ttk.Scale(
            sensitivity_frame,
            from_=1,
            to=100,
            orient='horizontal',
            variable=self.movement_sensitivity,
            command=self.on_sensitivity_change,
            length=200
        )
        self.sensitivity_slider.pack(side='left', padx=(5, 5), fill='x', expand=True)
        self.sensitivity_slider.set(2)  # Set to new default

        # Initially hide the sensitivity slider if not needed
        self.sensitivity_slider.pack_forget()

        # Monitor Selection
        monitor_frame = ttk.Frame(self.root)
        monitor_frame.pack(fill='x', **padding)

        monitor_label = ttk.Label(monitor_frame, text="Select Monitor:")
        monitor_label.pack(side='left')

        self.monitor_menu = ttk.OptionMenu(monitor_frame, self.selected_monitor, "")
        self.monitor_menu.pack(side='left', padx=(5, 5))

        # Start and Stop Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill='x', **padding)

        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_capturing)
        self.start_button.pack(side='left', expand=True, fill='x', padx=(0, 5))

        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_capturing, state='disabled')
        self.stop_button.pack(side='left', expand=True, fill='x', padx=(5, 0))

        # Progress Bar
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill='x', **padding)

        self.progress_label = ttk.Label(progress_frame, text="Activity:")
        self.progress_label.pack(side='left')

        self.progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.progress_bar.pack(side='left', fill='x', expand=True, padx=(5, 0))

        # CPU Utilization Progress Bar
        cpu_frame = ttk.LabelFrame(self.root, text="CPU Utilization")
        cpu_frame.pack(fill='x', padx=10, pady=10)

        # Define the CPU progress bar with initial style
        self.cpu_progress = ttk.Progressbar(
            cpu_frame,
            orient='horizontal',
            length=300,
            mode='determinate',
            maximum=100,
            style="green.Horizontal.TProgressbar"
        )
        self.cpu_progress.pack(padx=10, pady=10)

        # Screenshot Saving Indicator
        self.screenshot_label = ttk.Label(self.root, text="Current Screenshot: None")
        self.screenshot_label.pack(fill='x', padx=10, pady=5)

        # Movement Status Label (Additional Feedback)
        self.movement_status_label = ttk.Label(self.root, text="Movement: None", foreground="red")
        self.movement_status_label.pack(fill='x', padx=10, pady=5)

        # Input Detection Status Label (Additional Feedback)
        self.input_status_label = ttk.Label(self.root, text="Input Detection: Active", foreground="green")
        self.input_status_label.pack(fill='x', padx=10, pady=5)

        # Status Label
        self.status_label = ttk.Label(self.root, text="Status: Idle")
        self.status_label.pack(fill='x', **padding)

    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.save_directory.set(directory)
            self.initialize_logging_and_counter()
            self.save_settings()

    def initialize_logging_and_counter(self):
        """Initialize log file and counter file paths."""
        if self.save_directory.get():
            self.log_file = os.path.join(self.save_directory.get(), "screenshot_log.txt")
            self.counter_file = os.path.join(self.save_directory.get(), "screenshot_counter.txt")
            # Initialize log file if it doesn't exist
            if not os.path.exists(self.log_file):
                with open(self.log_file, 'w') as f:
                    f.write("zmxTOOL Screen(shot) Recorder Log\n")
                    f.write("=================================\n\n")
            # Initialize counter
            self.load_counter()

    def load_counter(self):
        """Load the last counter value from the counter file."""
        if self.counter_file and os.path.exists(self.counter_file):
            try:
                with open(self.counter_file, 'r') as f:
                    last_counter = f.read().strip()
                    if last_counter.isdigit():
                        self.counter = int(last_counter) + 1
                    else:
                        self.counter = 1
            except Exception as e:
                self.log_event(f"Error reading counter file: {e}", level="ERROR")
                self.counter = 1
        else:
            self.counter = 1

    def save_counter(self):
        """Save the current counter value to the counter file."""
        if self.counter_file:
            try:
                with open(self.counter_file, 'w') as f:
                    f.write(str(self.counter))
            except Exception as e:
                self.log_event(f"Error writing counter file: {e}", level="ERROR")

    def log_event(self, message, level="INFO"):
        """Append a message to the log file with a timestamp."""
        if self.log_file:
            try:
                with open(self.log_file, 'a') as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] [{level}] {message}\n")
            except Exception as e:
                # If logging fails, show a message box
                messagebox.showerror("Logging Error", f"Failed to write to log file: {e}")

    def populate_monitors(self):
        with mss.mss() as sct:
            monitors = sct.monitors
            monitor_list = []
            for idx, monitor in enumerate(monitors[1:], start=1):  # Skip the virtual monitor
                name = f"Monitor {idx}: {monitor['width']}x{monitor['height']} @ {monitor['left']},{monitor['top']}"
                monitor_list.append(name)
            if not monitor_list:
                messagebox.showerror("Error", "No monitors detected.")
                self.root.destroy()
                return
            menu = self.monitor_menu["menu"]
            menu.delete(0, "end")
            for monitor in monitor_list:
                menu.add_command(label=monitor, command=lambda value=monitor: self.selected_monitor.set(value))
            if self.selected_monitor.get() not in monitor_list:
                self.selected_monitor.set(monitor_list[0])  # Set default selection if not already set

    def on_format_change(self, *args):
        """Show or hide the JPEG quality slider based on the selected file format."""
        selected_format = self.file_format.get().lower()
        print(f"File format changed to: {selected_format}")  # Debugging statement

        if selected_format == "jpg":
            self.jpeg_quality_frame.pack(fill='x', padx=10, pady=5)
        else:
            self.jpeg_quality_frame.pack_forget()

    def on_quality_change(self, value):
        """Ensure the JPEG quality is an integer."""
        self.jpeg_quality.set(int(float(value)))
        print(f"JPEG Quality set to: {self.jpeg_quality.get()}")  # Debugging statement

    def on_mode_change(self):
        """Update UI elements based on the selected movement detection mode."""
        mode = self.movement_detection_mode.get()
        print(f"Movement Detection Mode changed to: {mode}")  # Debugging statement
        if mode in ["input", "image", "combined"]:
            self.sensitivity_slider.pack(fill='x', padx=10, pady=5)
        else:
            self.sensitivity_slider.pack_forget()

    def on_sensitivity_change(self, value):
        """Update movement sensitivity."""
        self.movement_sensitivity.set(int(float(value)))
        self.log_event(f"Movement Sensitivity set to {self.movement_sensitivity.get()}%.")
        print(f"Movement Sensitivity set to: {self.movement_sensitivity.get()}%")  # Debugging statement

    # **New: Callback for Motion Detection Toggle**
    def on_detection_toggle(self):
        """Handle the enabling or disabling of motion detection."""
        state = self.enable_motion_detection.get()
        status = "enabled" if state else "disabled"
        self.log_event(f"Motion detection {status}.")
        print(f"Motion detection {status}.")  # Debugging statement

        # Update input detection status accordingly
        if state:
            self.input_status_label.config(text="Input Detection: Active", foreground="green")
        else:
            self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
            # Optionally reset movement status
            self.movement_status_label.config(text="Movement: None", foreground="red")

    def start_capturing(self):
        # Validate inputs
        if not self.save_directory.get():
            messagebox.showwarning("Input Error", "Please select a save directory.")
            return
        if not os.path.isdir(self.save_directory.get()):
            messagebox.showwarning("Input Error", "Selected save directory does not exist.")
            return
        try:
            interval = self.interval.get()
            if interval <= 0:
                raise ValueError
        except:
            messagebox.showwarning("Input Error", "Interval must be a positive number.")
            return
        if self.file_format.get() not in ["png", "jpg"]:
            messagebox.showwarning("Input Error", "Unsupported file format selected.")
            return
        if not self.selected_monitor.get():
            messagebox.showwarning("Input Error", "Please select a monitor.")
            return

        # Initialize logging and counter
        self.initialize_logging_and_counter()
        self.log_event("Starting screenshot capture.")

        # Disable inputs
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.is_running = True
        self.stop_event.clear()

        # Start Progress Bar
        self.progress_bar.start(10)  # Update every 10 ms

        # Update status
        self.update_status("Running")

        # Reset previous_image if image-based movement detection is enabled
        mode = self.movement_detection_mode.get()
        if mode in ["image", "combined"]:
            self.previous_image = None

        # Start input listeners
        self.start_input_listeners()

        # Start screenshot thread
        self.thread = threading.Thread(target=self.capture_screenshots, daemon=True)
        self.thread.start()

        # Start CPU Monitoring
        self.monitor_cpu()

        # Save settings
        self.save_settings()

    def stop_capturing(self):
        if self.is_running:
            self.stop_event.set()
            # Stop Progress Bar
            self.progress_bar.stop()
            self.is_running = False
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            self.update_status("Stopped")
            self.log_event("Stopped screenshot capture.")

            # Stop input listeners
            self.stop_input_listeners()

            # Save settings
            self.save_settings()

    def capture_screenshots(self):
        try:
            # Extract monitor index from selected_monitor string
            monitor_str = self.selected_monitor.get()
            try:
                monitor_idx = int(monitor_str.split(":")[0].split(" ")[1])  # Extract the number after "Monitor "
            except (IndexError, ValueError):
                self.queue_status("Error: Invalid monitor selection.")
                self.log_event("Error: Invalid monitor selection.", level="ERROR")
                self.stop_event.set()
                return

            with mss.mss() as sct:
                monitors = sct.monitors
                if monitor_idx < 1 or monitor_idx > len(monitors) - 1:
                    self.queue_status(f"Error: Monitor {monitor_idx} does not exist.")
                    self.log_event(f"Error: Monitor {monitor_idx} does not exist.", level="ERROR")
                    self.stop_event.set()
                    return
                monitor = monitors[monitor_idx]

                # Get current date in YYYY-MM-DD format
                current_date = datetime.now().strftime("%Y-%m-%d")

                while not self.stop_event.is_set():
                    try:
                        # Capture the screen
                        sct_img = sct.grab(monitor)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                    except Exception as e:
                        self.queue_status(f"Error capturing screen: {e}")
                        self.log_event(f"Error capturing screen: {e}", level="ERROR")
                        self.stop_event.set()
                        break

                    movement_detected = False

                    # **New: Check if Motion Detection is Enabled**
                    if not self.enable_motion_detection.get():
                        movement_detected = True  # Capture unconditionally
                        self.log_event("Motion detection is disabled. Capturing screenshot unconditionally.", level="INFO")
                        self.queue_status("Running: Motion Detection Disabled")
                        self.movement_status_label.config(text="Motion Detection: Disabled", foreground="orange")
                    else:
                        # Movement Detection Logic
                        mode = self.movement_detection_mode.get()
                        if mode == "input":
                            # Input-Based Detection
                            with self.input_lock:
                                if self.input_activity:
                                    movement_detected = True
                                    self.input_activity = False  # Reset flag
                                    self.log_event("Input-based movement detected.", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                                else:
                                    self.movement_status_label.config(text="Movement: None", foreground="red")

                        elif mode == "image":
                            # Image-Based Detection
                            if self.previous_image is None:
                                movement_detected = True
                                self.log_event("Initial image captured for movement detection.", level="INFO")
                                self.movement_status_label.config(text="Movement: Detected", foreground="green")
                            else:
                                # Compare with previous image
                                diff = ImageChops.difference(img, self.previous_image)
                                # Convert to grayscale to sum differences
                                diff_gray = diff.convert("L")
                                diff_pixels = sum(diff_gray.getdata())
                                max_diff = img.width * img.height * 255
                                diff_ratio = diff_pixels / max_diff
                                # Threshold based on sensitivity
                                threshold = self.movement_sensitivity.get() / 100.0  # Convert percentage to ratio
                                if diff_ratio > threshold:
                                    movement_detected = True
                                    self.log_event(f"Image-based movement detected (diff_ratio={diff_ratio:.4f}).", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                                else:
                                    self.movement_status_label.config(text="Movement: None", foreground="red")

                        elif mode == "combined":
                            # Combined Detection: Image-Based OR Input-Based
                            image_movement = False
                            input_movement = False

                            # Image-Based Detection
                            if self.previous_image is None:
                                image_movement = True
                                self.log_event("Initial image captured for movement detection.", level="INFO")
                                self.movement_status_label.config(text="Movement: Detected", foreground="green")
                            else:
                                # Compare with previous image
                                diff = ImageChops.difference(img, self.previous_image)
                                # Convert to grayscale to sum differences
                                diff_gray = diff.convert("L")
                                diff_pixels = sum(diff_gray.getdata())
                                max_diff = img.width * img.height * 255
                                diff_ratio = diff_pixels / max_diff
                                # Threshold based on sensitivity
                                threshold = self.movement_sensitivity.get() / 100.0  # Convert percentage to ratio
                                if diff_ratio > threshold:
                                    image_movement = True
                                    self.log_event(f"Image-based movement detected (diff_ratio={diff_ratio:.4f}).", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                                else:
                                    self.movement_status_label.config(text="Movement: None", foreground="red")

                            # Input-Based Detection
                            with self.input_lock:
                                if self.input_activity:
                                    input_movement = True
                                    self.input_activity = False  # Reset flag
                                    self.log_event("Input-based movement detected.", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")

                            # Determine if movement is detected in combined mode
                            if image_movement or input_movement:
                                movement_detected = True
                            else:
                                movement_detected = False

                    if movement_detected:
                        # Save the screenshot
                        self.save_screenshot(img, current_date, detection_type=mode if self.enable_motion_detection.get() else "none")
                        # Update status to indicate active capturing
                        self.queue_status("Running")
                    else:
                        # No movement detected; pause capturing
                        self.queue_status("Paused: No movement detected.")
                        self.log_event("No movement detected. Pausing capture.", level="INFO")

                    # Update previous_image for image-based detection
                    if self.movement_detection_mode.get() in ["image", "combined"] and self.enable_motion_detection.get():
                        self.previous_image = img.copy()

                    # Use wait instead of sleep for responsive stopping
                    if self.stop_event.wait(self.interval.get()):
                        break
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Fatal error in capture_screenshots: {tb}", level="FATAL")
            self.queue_status("Fatal Error: Check log for details.")
            self.stop_event.set()

    def save_screenshot(self, img, current_date, detection_type="unknown"):
        """Save the screenshot and handle logging and counter."""
        # Format counter with leading zeros (6 digits)
        counter_str = f"{self.counter:06d}"

        # Determine file extension
        extension = "png" if self.file_format.get() == "png" else "jpeg"

        # Construct filename
        filename = f"screenshot_captures_session_{current_date}_{counter_str}.{extension}"
        filepath = os.path.join(self.save_directory.get(), filename)

        try:
            # Update the screenshot label to indicate saving
            self.screenshot_label.config(text=f"Saving: {filename}")

            if extension == "png":
                img.save(filepath, "PNG")
            else:
                img = img.convert("RGB")  # Ensure no alpha channel for JPEG
                # Map slider value (1-10) to Pillow's quality (1-95)
                if self.jpeg_quality.get() == 10:
                    pillow_quality = 95
                else:
                    pillow_quality = max(1, min(95, int((self.jpeg_quality.get() / 10) * 95)))
                img.save(filepath, "JPEG", quality=pillow_quality)
            
            # Update status and log
            self.queue_status(f"Saved: {filename} ({detection_type.capitalize()} Detection)")
            self.log_event(f"Saved: {filename} ({detection_type.capitalize()} Detection)")

            # Save counter before incrementing to prevent skipping
            self.save_counter()
            self.counter += 1  # Increment counter

            # Optional: Prevent counter from exceeding 999999
            if self.counter > 999999:
                self.queue_status("Error: Maximum screenshot limit reached.")
                self.log_event("Error: Maximum screenshot limit reached.", level="ERROR")
                self.stop_event.set()

            # Update the screenshot label to indicate completion
            self.screenshot_label.config(text=f"Saved: {filename}")

        except Exception as e:
            # Update status and log on error
            self.queue_status(f"Error saving screenshot: {e}")
            self.log_event(f"Error saving screenshot: {e}", level="ERROR")
            self.stop_event.set()

    def queue_status(self, message):
        """Thread-safe method to update the status label."""
        self.root.after(0, self.update_status, message)

    def update_status(self, message):
        """Update the status label."""
        self.status_label.config(text=f"Status: {message}")

    def save_settings(self):
        """Save user preferences to a settings file."""
        settings = {
            "save_directory": self.save_directory.get(),
            "file_format": self.file_format.get(),
            "interval": self.interval.get(),
            "selected_monitor": self.selected_monitor.get(),
            "jpeg_quality": self.jpeg_quality.get(),
            "movement_detection_mode": self.movement_detection_mode.get(),
            "detect_keyboard": self.detect_keyboard.get(),
            "movement_sensitivity": self.movement_sensitivity.get(),
            "enable_motion_detection": self.enable_motion_detection.get()  # **New: Save Motion Detection State**
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_event("Settings saved.")
        except Exception as e:
            self.log_event(f"Error saving settings: {e}", level="ERROR")

    def load_settings(self):
        """Load user preferences from a settings file."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                self.save_directory.set(settings.get("save_directory", ""))
                self.file_format.set(settings.get("file_format", "png"))
                self.interval.set(settings.get("interval", 5.0))
                self.selected_monitor.set(settings.get("selected_monitor", ""))
                self.jpeg_quality.set(settings.get("jpeg_quality", 5))
                self.movement_detection_mode.set(settings.get("movement_detection_mode", "image"))
                self.detect_keyboard.set(settings.get("detect_keyboard", True))
                self.movement_sensitivity.set(settings.get("movement_sensitivity", 2))
                self.enable_motion_detection.set(settings.get("enable_motion_detection", True))  # **New: Load Motion Detection State**
                self.on_format_change()  # Removed argument
                self.on_mode_change()
                self.on_detection_toggle()  # Update UI based on loaded state
                if self.movement_detection_mode.get() in ["input", "image", "combined"]:
                    self.sensitivity_slider.pack(fill='x', padx=10, pady=5)
                else:
                    self.sensitivity_slider.pack_forget()
                self.log_event("Settings loaded.")
            except Exception as e:
                tb = traceback.format_exc()
                self.log_event(f"Error loading settings: {tb}", level="ERROR")

    def on_close(self):
        if self.is_running:
            if messagebox.askokcancel("Quit", "Screenshot capture is running. Do you want to quit?"):
                self.stop_capturing()
                self.save_settings()
                self.root.destroy()
        else:
            self.save_settings()
            self.root.destroy()

    # Input Event Monitoring Methods
    def start_input_listeners(self):
        """Start listeners for keyboard events."""
        try:
            if self.detect_keyboard.get() and self.enable_motion_detection.get():  # **Modified: Only listen if motion detection is enabled**
                self.keyboard_listener = keyboard.Listener(on_press=self.on_input_event)
                self.keyboard_listener.start()
                self.log_event("Keyboard listener started.", level="INFO")
            else:
                self.keyboard_listener = None

            # Update input detection status accordingly
            if self.detect_keyboard.get() and self.enable_motion_detection.get():
                self.input_status_label.config(text="Input Detection: Active", foreground="green")
            else:
                self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error starting input listeners: {tb}", level="ERROR")
            self.input_status_label.config(text="Input Detection: Error", foreground="red")

    def stop_input_listeners(self):
        """Stop listeners for keyboard events."""
        try:
            if hasattr(self, 'keyboard_listener') and self.keyboard_listener is not None:
                self.keyboard_listener.stop()
                self.keyboard_listener = None
                self.log_event("Keyboard listener stopped.", level="INFO")

            # Update input detection status
            self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error stopping input listeners: {tb}", level="ERROR")

    def on_input_event(self, key):
        """Callback for any keyboard event."""
        try:
            with self.input_lock:
                self.input_activity = True
            self.log_event(f"Input activity detected: {key}", level="INFO")
            # Update movement status label
            self.movement_status_label.config(text="Movement: Detected", foreground="green")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error in input event callback: {tb}", level="ERROR")

    # CPU Monitoring Methods
    def monitor_cpu(self):
        """Start monitoring CPU usage and update the bar."""
        if not self.is_running:
            return

        # Get current CPU usage
        cpu_percent = psutil.cpu_percent(interval=None)

        # Update the CPU bar
        self.update_cpu_bar(cpu_percent)

        # Schedule the next update
        self.root.after(1000, self.monitor_cpu)  # Update every second

    def update_cpu_bar(self, cpu_percent):
        """Update the CPU utilization progress bar based on current CPU usage."""
        # Update the progress bar's value
        self.cpu_progress['value'] = cpu_percent

        # Determine the appropriate style based on CPU usage
        if cpu_percent <= 50:
            style = "green.Horizontal.TProgressbar"
        elif 50 < cpu_percent <= 80:
            style = "orange.Horizontal.TProgressbar"
        else:
            style = "red.Horizontal.TProgressbar"

        # Update the progress bar's style if it has changed
        current_style = self.cpu_progress['style']
        if current_style != style:
            self.cpu_progress.config(style=style)

    # **New: Save Motion Detection Toggle in Settings**
    # (Already handled in save_settings and load_settings)

def main():
    try:
        root = tk.Tk()
        app = ScreenshotApp(root)  # Correct capitalization
        root.protocol("WM_DELETE_WINDOW", app.on_close)
        root.mainloop()
    except Exception as e:
        # Log unexpected errors to a separate log file
        error_log_path = resource_path("error_log.txt")  # Use resource_path for the error log
        try:
            with open(error_log_path, "a") as f:
                f.write(f"An unexpected error occurred: {traceback.format_exc()}\n")
        except:
            pass  # If logging fails, there's not much we can do
        messagebox.showerror("Fatal Error", f"An unexpected error occurred:\n{e}")

if __name__ == "__main__":
    main()
