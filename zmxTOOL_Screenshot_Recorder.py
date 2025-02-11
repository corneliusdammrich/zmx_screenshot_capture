import os
import sys
import json
import time
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import mss
from PIL import Image, ImageChops
from pynput import keyboard
import mouse
import psutil
import traceback

try:
    import win32gui
except ImportError:
    win32gui = None

MARKER_FILENAME = ".zmxTOOL_session"

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class ScreenshotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("zmxTOOL Screen(shot) Recorder")
        self.root.geometry("800x700")
        self.root.resizable(False, False)

        # Initialize variables
        self.save_directory = tk.StringVar()
        self.interval = tk.DoubleVar(value=5.0)
        self.jpeg_quality = tk.IntVar(value=5)

        self.movement_detection_mode = tk.StringVar(value="image")
        self.detect_keyboard = tk.BooleanVar(value=True)
        self.movement_sensitivity = tk.IntVar(value=2)
        self.enable_motion_detection = tk.BooleanVar(value=True)

        self.enable_logging = tk.BooleanVar(value=True)
        self.session_name = tk.StringVar(value="")
        self.sessions = []

        self.is_running = False
        self.thread = None
        self.stop_event = threading.Event()
        self.counter = 1

        self.log_file = None
        self.previous_image = None
        self.input_activity = False
        self.input_lock = threading.Lock()

        self.keyboard_listener = None
        self.settings_file = resource_path("settings.json")

        # Styles for progress bars
        style = ttk.Style()
        style.theme_use('default')
        style.configure("green.Horizontal.TProgressbar", foreground='green', background='green')
        style.configure("orange.Horizontal.TProgressbar", foreground='orange', background='orange')
        style.configure("red.Horizontal.TProgressbar", foreground='red', background='red')

        self.capture_mode = tk.StringVar(value="monitors")
        self.selected_resolution = tk.StringVar(value="1920x1080")

        # Create the UI
        self.create_widgets()
        self.load_settings()
        self.populate_monitors()

        self.mouse_pressed = False

    def create_widgets(self):
        padding = {'padx': 10, 'pady': 5}
        self.settings_widgets = []

        # --- File Settings ---
        file_frame = ttk.LabelFrame(self.root, text="File Settings")
        file_frame.pack(fill='x', padx=10, pady=5)

        dir_frame = ttk.Frame(file_frame)
        dir_frame.pack(fill='x', **padding)
        ttk.Label(dir_frame, text="Save Directory:").pack(side='left')
        self.directory_entry = ttk.Entry(dir_frame, textvariable=self.save_directory, width=40)
        self.directory_entry.pack(side='left', padx=(5,5))
        self.settings_widgets.append(self.directory_entry)
        self.browse_button = ttk.Button(dir_frame, text="Browse", command=self.browse_directory)
        self.browse_button.pack(side='left')
        self.settings_widgets.append(self.browse_button)

        jpeg_quality_frame = ttk.Frame(file_frame)
        jpeg_quality_frame.pack(fill='x', padx=10, pady=5)
        ttk.Label(jpeg_quality_frame, text="JPEG Quality:").pack(side='left')
        self.jpeg_quality_slider = ttk.Scale(
            jpeg_quality_frame, from_=1, to=10, orient='horizontal',
            variable=self.jpeg_quality, command=self.on_quality_change, length=200
        )
        self.jpeg_quality_slider.pack(side='left', padx=(5,5), fill='x', expand=True)
        self.jpeg_quality_value_label = ttk.Label(jpeg_quality_frame, textvariable=self.jpeg_quality)
        self.jpeg_quality_value_label.pack(side='left', padx=(5,0))
        self.settings_widgets.extend([self.jpeg_quality_slider, self.jpeg_quality_value_label])

        interval_frame = ttk.Frame(file_frame)
        interval_frame.pack(fill='x', **padding)
        ttk.Label(interval_frame, text="Interval (seconds):").pack(side='left')
        self.interval_spinbox = ttk.Spinbox(
            interval_frame, textvariable=self.interval, from_=0.1, to=60.0,
            increment=0.1, format="%.1f", width=10
        )
        self.interval_spinbox.pack(side='left', padx=(5,5))
        self.interval_spinbox.set(5.0)
        self.settings_widgets.append(self.interval_spinbox)

        session_frame = ttk.Frame(file_frame)
        session_frame.pack(fill='x', **padding)
        ttk.Label(session_frame, text="Session:").pack(side='left')
        self.session_dropdown = ttk.OptionMenu(
            session_frame, self.session_name, "Select Session", command=self.on_session_select
        )
        self.session_dropdown.pack(side='left', padx=(5,5))
        self.settings_widgets.append(self.session_dropdown)
        self.new_session_entry = ttk.Entry(session_frame, textvariable=self.session_name, width=30)
        self.new_session_entry.pack(side='left', padx=(10,5))
        self.new_session_entry.bind("<KeyRelease>", self.on_session_name_change)
        self.settings_widgets.append(self.new_session_entry)

        log_frame = ttk.Frame(file_frame)
        log_frame.pack(fill='x', **padding)
        self.logging_check = ttk.Checkbutton(log_frame, text="Enable Logging", variable=self.enable_logging)
        self.logging_check.pack(side='left')
        self.settings_widgets.append(self.logging_check)

        # --- Capture Mode ---
        capture_mode_frame = ttk.LabelFrame(self.root, text="Capture Mode")
        capture_mode_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(capture_mode_frame, text="Select Capture Mode:").pack(side='left', padx=(5,5))
        rb_monitors = ttk.Radiobutton(
            capture_mode_frame, text="Monitors",
            variable=self.capture_mode, value="monitors",
            command=self.on_capture_mode_change
        )
        rb_monitors.pack(side='left', padx=(5,5))
        rb_active = ttk.Radiobutton(
            capture_mode_frame, text="Active Window",
            variable=self.capture_mode, value="active_window",
            command=self.on_capture_mode_change
        )
        rb_active.pack(side='left', padx=(5,5))

        # Monitors selection frame
        self.monitors_frame = ttk.LabelFrame(self.root, text="Select Monitors")
        self.monitors_frame.pack(fill='x', padx=10, pady=5)

        # --- Detection Settings ---
        self.detection_frame = ttk.LabelFrame(self.root, text="Detection Settings")
        self.detection_frame.pack(fill='x', padx=10, pady=5)

        detection_toggle_frame = ttk.Frame(self.detection_frame)
        detection_toggle_frame.pack(fill='x', **padding)
        ttk.Label(detection_toggle_frame, text="Motion Detection:").pack(side='left')
        self.motion_detection_check = ttk.Checkbutton(
            detection_toggle_frame, text="Enable",
            variable=self.enable_motion_detection, command=self.on_detection_toggle
        )
        self.motion_detection_check.pack(side='left', padx=(5,0))
        self.settings_widgets.append(self.motion_detection_check)

        self.mode_frame = ttk.Frame(self.detection_frame)
        self.mode_frame.pack(fill='x', **padding)
        ttk.Label(self.mode_frame, text="Movement Detection Mode:").pack(side='left')
        mode_options = [("Image-Based", "image"), ("Input-Based", "input"), ("Combined", "combined")]
        self.mode_radiobuttons = []
        for text, mode in mode_options:
            rb = ttk.Radiobutton(
                self.mode_frame, text=text,
                variable=self.movement_detection_mode,
                value=mode, command=self.on_mode_change
            )
            rb.pack(side='left', padx=(10,0))
            self.mode_radiobuttons.append(rb)
            self.settings_widgets.append(rb)

        self.sensitivity_frame = ttk.Frame(self.detection_frame)
        self.sensitivity_frame.pack(fill='x', **padding)
        ttk.Label(self.sensitivity_frame, text="Movement Sensitivity (%):").pack(side='left')
        self.sensitivity_slider = ttk.Scale(
            self.sensitivity_frame, from_=1, to=100, orient='horizontal',
            variable=self.movement_sensitivity, command=self.on_sensitivity_change, length=200
        )
        self.sensitivity_slider.pack(side='left', padx=(5,5), fill='x', expand=True)
        self.sensitivity_value_label = ttk.Label(
            self.sensitivity_frame, text=f"{self.movement_sensitivity.get()}%"
        )
        self.sensitivity_value_label.pack(side='left', padx=(5,0))
        self.sensitivity_slider.set(2)
        self.sensitivity_slider.pack_forget()
        self.settings_widgets.extend([self.sensitivity_slider, self.sensitivity_value_label])

        # --- Status Frame ---
        status_frame = ttk.LabelFrame(self.root, text="Status")
        status_frame.pack(fill='both', expand=True, padx=10, pady=5)

        progress_frame = ttk.Frame(status_frame)
        progress_frame.pack(fill='x', **padding)
        ttk.Label(progress_frame, text="Activity:").pack(side='left')
        self.progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.progress_bar.pack(side='left', fill='x', expand=True, padx=(5,0))

        cpu_frame = ttk.LabelFrame(status_frame, text="CPU Utilization")
        cpu_frame.pack(fill='x', padx=10, pady=10)
        self.cpu_progress = ttk.Progressbar(
            cpu_frame, orient='horizontal', length=300,
            mode='determinate', maximum=100, style="green.Horizontal.TProgressbar"
        )
        self.cpu_progress.pack(padx=10, pady=10)

        self.screenshot_label = ttk.Label(status_frame, text="Current Screenshot: None")
        self.screenshot_label.pack(fill='x', padx=10, pady=5)

        self.movement_status_label = ttk.Label(status_frame, text="Movement: None", foreground="red")
        self.movement_status_label.pack(fill='x', padx=10, pady=5)
        self.input_status_label = ttk.Label(status_frame, text="Input Detection: Active", foreground="green")
        self.input_status_label.pack(fill='x', padx=10, pady=5)

        self.status_label = ttk.Label(status_frame, text="Status: Idle")
        self.status_label.pack(fill='x', padx=10, pady=5)

        # --- Video Conversion ---
        convert_frame = ttk.LabelFrame(self.root, text="Video Conversion")
        convert_frame.pack(fill='x', padx=10, pady=5)

        self.frames_count_label = ttk.Label(convert_frame, text="Frames in session: 0")
        self.frames_count_label.pack(side='left', padx=10, pady=5)

        fps_options = [12, 24, 25, 30, 60]
        self.selected_fps = tk.IntVar(value=fps_options[0])
        self.fps_selector = ttk.Combobox(
            convert_frame, textvariable=self.selected_fps,
            values=fps_options, state='readonly', width=5
        )
        self.fps_selector.pack(side='left', padx=(10,5))
        ttk.Label(convert_frame, text="FPS").pack(side='left')

        resolution_options = ["1920x1080", "2560x1440", "3840x2160"]
        self.resolution_selector = ttk.Combobox(
            convert_frame, textvariable=self.selected_resolution,
            values=resolution_options, state='readonly', width=10
        )
        self.resolution_selector.pack(side='left', padx=(10,5))
        ttk.Label(convert_frame, text="Resolution").pack(side='left')

        self.convert_button = ttk.Button(
            convert_frame, text="Convert to video file",
            command=self.convert_session_to_video
        )
        self.convert_button.pack(side='left', padx=(10,5))

        self.conversion_status = ttk.Label(convert_frame, text="")
        self.conversion_status.pack(side='left', padx=(10,5))

        # --- Start/Stop Buttons ---
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill='x', padx=10, pady=5)
        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_capturing)
        self.start_button.pack(side='left', expand=True, fill='x', padx=(0,5))
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_capturing, state='disabled')
        self.stop_button.pack(side='left', expand=True, fill='x', padx=(5,0))

    def on_capture_mode_change(self):
        """Show/hide the monitor selection frame depending on capture mode."""
        if self.capture_mode.get() == "monitors":
            self.monitors_frame.pack(fill='x', padx=10, pady=5, before=self.detection_frame)
        else:
            self.monitors_frame.pack_forget()

    def on_session_name_change(self, event):
        self.update_start_button_label()

    def update_start_button_label(self):
        """Changes the Start button label to 'Continue' if session folder has screenshots."""
        session = self.session_name.get()
        save_dir = self.save_directory.get()
        if not session or not save_dir:
            self.start_button.config(text="Start")
            return
        session_folder = os.path.join(save_dir, session)
        if os.path.isdir(session_folder):
            files = [f for f in os.listdir(session_folder) if f.startswith(f"{session}_")]
            if files:
                self.start_button.config(text="Continue")
            else:
                self.start_button.config(text="Start")
        else:
            self.start_button.config(text="Start")

    def disable_settings(self):
        """Disable all setting widgets to prevent changes during capturing."""
        for widget in self.settings_widgets:
            try:
                widget.config(state='disabled')
            except:
                pass

    def enable_settings(self):
        """Enable all setting widgets after capturing stops."""
        for widget in self.settings_widgets:
            try:
                widget.config(state='normal')
            except:
                pass

    def browse_directory(self):
        """Open a dialog to select the save directory."""
        directory = filedialog.askdirectory()
        if directory:
            self.save_directory.set(directory)
            self.session_name.set("")
            self.sessions = []
            self.load_sessions()
            self.update_session_dropdown()
            self.save_settings()

    def initialize_logging_and_counter(self):
        """Sets up the log file and determines the screenshot counter based on existing files."""
        if self.save_directory.get() and self.session_name.get():
            session_folder = os.path.join(self.save_directory.get(), self.session_name.get())
            os.makedirs(session_folder, exist_ok=True)
            marker_path = os.path.join(session_folder, MARKER_FILENAME)
            if not os.path.exists(marker_path):
                with open(marker_path, "w") as f:
                    f.write("This folder is a valid zmxTOOL session folder.")
            self.log_file = os.path.join(session_folder, "screenshot_log.txt")
            self.load_counter()

    def load_counter(self):
        """Finds the largest existing screenshot number and increments from there."""
        session_folder = os.path.join(self.save_directory.get(), self.session_name.get())
        os.makedirs(session_folder, exist_ok=True)
        prefix = f"{self.session_name.get()}_"
        max_counter = 0
        for filename in os.listdir(session_folder):
            if filename.startswith(prefix):
                parts = filename.split('_')
                if len(parts) > 1:
                    num_part = parts[-1].split('.')[0]
                    try:
                        num = int(num_part)
                        max_counter = max(max_counter, num)
                    except:
                        pass
        self.counter = max_counter + 1

    def log_event(self, message, level="INFO"):
        """Writes a log entry to the session's log file, if logging is enabled."""
        if not self.enable_logging.get():
            return
        if self.log_file:
            try:
                with open(self.log_file, 'a') as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] [{level}] {message}\n")
            except Exception as e:
                messagebox.showerror("Logging Error", f"Failed to write to log file: {e}")

    def populate_monitors(self):
        """Refreshes the monitor selection checkboxes from mss."""
        with mss.mss() as sct:
            monitors = sct.monitors
            self.monitors = monitors
            for child in self.monitors_frame.winfo_children():
                child.destroy()
            self.monitor_vars = {}
            for idx, monitor in enumerate(monitors[1:], start=1):
                var = tk.BooleanVar(value=False)
                self.monitor_vars[idx] = var
                cb = ttk.Checkbutton(
                    self.monitors_frame,
                    text=f"Monitor {idx}: {monitor['width']}x{monitor['height']} @ {monitor['left']},{monitor['top']}",
                    variable=var
                )
                cb.pack(anchor='w')

    def on_quality_change(self, value):
        """Update JPEG quality based on the slider."""
        self.jpeg_quality.set(int(float(value)))

    def on_mode_change(self):
        """Show/hide the sensitivity slider depending on the chosen detection mode."""
        mode = self.movement_detection_mode.get()
        if mode in ["input", "image", "combined"]:
            self.sensitivity_slider.pack(fill='x', padx=10, pady=5)
        else:
            self.sensitivity_slider.pack_forget()

    def on_sensitivity_change(self, value):
        """Update movement sensitivity based on the slider."""
        self.movement_sensitivity.set(int(float(value)))
        self.sensitivity_value_label.config(text=f"{self.movement_sensitivity.get()}%")
        self.log_event(f"Movement Sensitivity set to {self.movement_sensitivity.get()}%.")

    def on_detection_toggle(self):
        """Handle toggling of motion detection."""
        state = self.enable_motion_detection.get()
        status = "enabled" if state else "disabled"
        self.log_event(f"Motion detection {status}.")
        if state:
            self.input_status_label.config(text="Input Detection: Active", foreground="green")
            self.mode_frame.pack(fill='x', padx=10, pady=5)
            self.sensitivity_frame.pack(fill='x', padx=10, pady=5)
            self.movement_status_label.pack(fill='x', padx=10, pady=5)
            self.input_status_label.pack(fill='x', padx=10, pady=5)
        else:
            self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
            self.movement_status_label.config(text="Movement: None", foreground="red")
            self.mode_frame.pack_forget()
            self.sensitivity_frame.pack_forget()
            self.movement_status_label.pack_forget()
            self.input_status_label.pack_forget()

    def load_sessions(self):
        """Loads valid sessions (those containing the marker file) from the save directory."""
        if self.save_directory.get() and os.path.isdir(self.save_directory.get()):
            try:
                all_dirs = [
                    d for d in os.listdir(self.save_directory.get()) 
                    if os.path.isdir(os.path.join(self.save_directory.get(), d))
                ]
                valid_sessions = []
                for d in all_dirs:
                    marker_path = os.path.join(self.save_directory.get(), d, MARKER_FILENAME)
                    if os.path.exists(marker_path):
                        valid_sessions.append(d)
                self.sessions = valid_sessions
            except Exception as e:
                self.log_event(f"Error reading session folders: {e}", level="ERROR")
                self.sessions = []
        else:
            self.sessions = []

    def update_session_dropdown(self):
        """Updates the session dropdown menu items and sets the default selection."""
        menu = self.session_dropdown["menu"]
        menu.delete(0, "end")
        for session in self.sessions:
            menu.add_command(label=session, command=lambda value=session: self.on_session_select(value))
        if self.sessions:
            if self.session_name.get() not in self.sessions:
                self.session_name.set(self.sessions[0])
        else:
            self.session_name.set("")
        self.update_start_button_label()
        self.update_frame_count()

    def on_session_select(self, value):
        """Handles user selecting a session from the dropdown."""
        self.session_name.set(value)
        self.log_event(f"Session selected: {value}")
        self.update_start_button_label()
        self.update_frame_count()

    def start_capturing(self):
        """Initiates the screenshot capturing process."""
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

        self.initialize_logging_and_counter()
        self.log_event("Starting screenshot capture.")
        self.disable_settings()
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.is_running = True
        self.stop_event.clear()
        self.progress_bar.start(10)
        self.update_status("Running")
        if self.movement_detection_mode.get() in ["image", "combined"]:
            self.previous_image = None
        self.start_input_listeners()
        self.thread = threading.Thread(target=self.capture_screenshots, daemon=True)
        self.thread.start()
        self.monitor_cpu()
        self.save_settings()

    def stop_capturing(self):
        """Stops the screenshot capturing process."""
        if self.is_running:
            self.stop_event.set()
            self.progress_bar.stop()
            self.is_running = False
            self.enable_settings()
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            self.update_status("Stopped")
            self.log_event("Stopped screenshot capture.")
            self.stop_input_listeners()
            self.save_settings()
            self.load_sessions()
            self.update_session_dropdown()

    def capture_screenshots(self):
        """Threaded function that captures screenshots at intervals, optionally using motion detection."""
        try:
            with mss.mss() as sct:
                current_date = datetime.now().strftime("%Y-%m-%d")
                while not self.stop_event.is_set():
                    if self.capture_mode.get() == "active_window" and win32gui:
                        hwnd = win32gui.GetForegroundWindow()
                        if hwnd == self.root.winfo_id():
                            time.sleep(self.interval.get())
                            continue
                        rect = win32gui.GetWindowRect(hwnd)
                        left, top, right, bottom = rect
                        width = right - left
                        height = bottom - top
                        region = {'left': left, 'top': top, 'width': width, 'height': height}
                    else:
                        selected_monitors = [self.monitors[idx] for idx, var in self.monitor_vars.items() if var.get()]
                        if not selected_monitors:
                            time.sleep(self.interval.get())
                            continue
                        left = min(m['left'] for m in selected_monitors)
                        top = min(m['top'] for m in selected_monitors)
                        right = max(m['left'] + m['width'] for m in selected_monitors)
                        bottom = max(m['top'] + m['height'] for m in selected_monitors)
                        width = right - left
                        height = bottom - top
                        region = {'left': left, 'top': top, 'width': width, 'height': height}

                    try:
                        sct_img = sct.grab(region)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                    except Exception as e:
                        self.queue_status(f"Error capturing screen: {e}")
                        self.log_event(f"Error capturing screen: {e}", level="ERROR")
                        self.stop_event.set()
                        break

                    movement_detected = False
                    if not self.enable_motion_detection.get():
                        movement_detected = True
                        self.log_event(
                            "Motion detection is disabled. Capturing screenshot unconditionally.",
                            level="INFO"
                        )
                        # Removed repetitive status updates to prevent flickering
                    else:
                        mode = self.movement_detection_mode.get()
                        if mode == "input":
                            with self.input_lock:
                                if self.input_activity:
                                    movement_detected = True
                                    self.input_activity = False
                                    self.log_event("Input-based movement detected.", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                                else:
                                    self.movement_status_label.config(text="Movement: None", foreground="red")
                        elif mode == "image":
                            if self.previous_image is None:
                                movement_detected = True
                                self.log_event("Initial image captured for movement detection.", level="INFO")
                                self.movement_status_label.config(text="Movement: Detected", foreground="green")
                            else:
                                diff = ImageChops.difference(img, self.previous_image)
                                diff_gray = diff.convert("L")
                                diff_pixels = sum(diff_gray.getdata())
                                max_diff = img.width * img.height * 255
                                diff_ratio = diff_pixels / max_diff
                                threshold = self.movement_sensitivity.get() / 100.0
                                if diff_ratio > threshold:
                                    movement_detected = True
                                    self.log_event(f"Image-based movement detected (diff_ratio={diff_ratio:.4f}).", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                                else:
                                    self.movement_status_label.config(text="Movement: None", foreground="red")
                        elif mode == "combined":
                            image_movement = False
                            input_movement = False
                            if self.previous_image is None:
                                image_movement = True
                                self.log_event("Initial image captured for movement detection.", level="INFO")
                                self.movement_status_label.config(text="Movement: Detected", foreground="green")
                            else:
                                diff = ImageChops.difference(img, self.previous_image)
                                diff_gray = diff.convert("L")
                                diff_pixels = sum(diff_gray.getdata())
                                max_diff = img.width * img.height * 255
                                diff_ratio = diff_pixels / max_diff
                                threshold = self.movement_sensitivity.get() / 100.0
                                if diff_ratio > threshold:
                                    image_movement = True
                                    self.log_event(f"Image-based movement detected (diff_ratio={diff_ratio:.4f}).", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                                else:
                                    self.movement_status_label.config(text="Movement: None", foreground="red")
                            with self.input_lock:
                                if self.input_activity:
                                    input_movement = True
                                    self.input_activity = False
                                    self.log_event("Input-based movement detected.", level="INFO")
                                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
                            if image_movement or input_movement:
                                movement_detected = True
                            else:
                                movement_detected = False

                    if movement_detected:
                        self.save_screenshot(img, current_date, detection_type=mode if self.enable_motion_detection.get() else "none")
                        self.queue_status("Running")
                    else:
                        self.queue_status("Paused: No movement detected.")
                        self.log_event("No movement detected. Pausing capture.", level="INFO")

                    if self.movement_detection_mode.get() in ["image", "combined"] and self.enable_motion_detection.get():
                        self.previous_image = img.copy()

                    if self.stop_event.wait(self.interval.get()):
                        break
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Fatal error in capture_screenshots: {tb}", level="FATAL")
            self.queue_status("Fatal Error: Check log for details.")
            self.stop_event.set()

    def save_screenshot(self, img, current_date, detection_type="unknown"):
        """Saves the captured screenshot to the designated folder."""
        counter_str = f"{self.counter:06d}"
        extension = "jpeg"
        filename = f"{self.session_name.get()}_{counter_str}.{extension}"
        session_folder = os.path.join(self.save_directory.get(), self.session_name.get())
        os.makedirs(session_folder, exist_ok=True)
        filepath = os.path.join(session_folder, filename)

        try:
            self.screenshot_label.config(text=f"Saving: {filename}")
            img = img.convert("RGB")
            if self.jpeg_quality.get() == 10:
                pillow_quality = 95
            else:
                pillow_quality = max(1, min(95, int((self.jpeg_quality.get() / 10) * 95)))
            img.save(filepath, "JPEG", quality=pillow_quality)
            self.queue_status(f"Saved: {filename} ({detection_type.capitalize()} Detection)")
            self.log_event(f"Saved: {filename} ({detection_type.capitalize()} Detection)")
            self.counter += 1
            if self.counter > 999999:
                self.queue_status("Error: Maximum screenshot limit reached.")
                self.log_event("Error: Maximum screenshot limit reached.", level="ERROR")
                self.stop_event.set()
            self.screenshot_label.config(text=f"Saved: {filename}")
            self.update_frame_count()
        except Exception as e:
            self.queue_status(f"Error saving screenshot: {e}")
            self.log_event(f"Error saving screenshot: {e}", level="ERROR")
            self.stop_event.set()

    def queue_status(self, message):
        """Queues a status update to be run in the main thread."""
        self.root.after(0, self.update_status, message)

    def update_status(self, message):
        """Updates the status label with the provided message."""
        self.status_label.config(text=f"Status: {message}")

    def update_frame_count(self):
        """Updates the frame count label based on saved screenshots."""
        session = self.session_name.get()
        save_dir = self.save_directory.get()
        count = 0
        if session and save_dir:
            session_folder = os.path.join(save_dir, session)
            if os.path.isdir(session_folder):
                prefix = f"{session}_"
                count = sum(1 for f in os.listdir(session_folder)
                            if f.startswith(prefix) and f.lower().endswith((".jpg", ".jpeg")))
        self.frames_count_label.config(text=f"Frames in session: {count}")

    def convert_session_to_video(self):
        """Converts saved screenshots in the session to a video file using FFmpeg."""
        session = self.session_name.get()
        save_dir = self.save_directory.get()
        if not session or not save_dir:
            messagebox.showwarning("Error", "Please select a valid session and save directory.")
            return

        session_folder = os.path.join(save_dir, session)
        if not os.path.isdir(session_folder):
            messagebox.showwarning("Error", "Session folder does not exist.")
            return

        fps = self.selected_fps.get()
        output_file = filedialog.asksaveasfilename(
            defaultextension=".mp4",
            initialdir=save_dir,
            title="Save video as",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")]
        )
        if not output_file:
            return

        resolution = self.selected_resolution.get()
        target_width, target_height = map(int, resolution.split('x'))

        processed_dir = os.path.join(session_folder, "_processed_video")
        os.makedirs(processed_dir, exist_ok=True)

        files = sorted(
            f for f in os.listdir(session_folder)
            if f.lower().endswith((".jpg",".jpeg")) and f.startswith(f"{session}_")
        )

        if not files:
            messagebox.showwarning("Warning", "No screenshot images found in the session folder.")
            return

        self.log_event(f"Found {len(files)} screenshots to process.", level="INFO")

        for i, filename in enumerate(files, start=1):
            filepath = os.path.join(session_folder, filename)
            self.log_event(f"Processing file: {filename}", level="INFO")
            try:
                img = Image.open(filepath)
                aspect_ratio = img.width / img.height
                target_ratio = target_width / target_height
                if aspect_ratio > target_ratio:
                    new_width = target_width
                    new_height = int(target_width / aspect_ratio)
                else:
                    new_height = target_height
                    new_width = int(target_height * aspect_ratio)
                img_resized = img.resize((new_width, new_height), resample=Image.LANCZOS)

                new_img = Image.new("RGB", (target_width, target_height), (0,0,0))
                x_offset = (target_width - new_width) // 2
                y_offset = (target_height - new_height) // 2
                new_img.paste(img_resized, (x_offset, y_offset))

                new_filename = f"{session}_{i:06d}.jpeg"
                new_filepath = os.path.join(processed_dir, new_filename)
                new_img.save(new_filepath, "JPEG", quality=95)
            except Exception as e:
                self.log_event(f"Error processing {filename}: {e}", level="ERROR")

        processed_files = os.listdir(processed_dir)
        self.log_event(f"Processed {len(processed_files)} images for video conversion.", level="INFO")

        input_pattern = os.path.join(processed_dir, f"{session}_%06d.jpeg")
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", input_pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-progress", "pipe:1",
            output_file
        ]

        self.conversion_status.config(text="Starting conversion...")

        def run_conversion():
            try:
                import subprocess
                total_frames = len([
                    f for f in os.listdir(processed_dir)
                    if f.startswith(f"{session}_") and f.lower().endswith((".jpg",".jpeg"))
                ])
                self.log_event(f"Starting FFmpeg conversion with {total_frames} frames.", level="INFO")
                self.log_event(f"Executing command: {' '.join(cmd)}", level="INFO")
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    if line.startswith("frame="):
                        try:
                            frame_num = int(line.split("=")[1].strip())
                            percent = (frame_num / total_frames) * 100 if total_frames > 0 else 0
                            self.root.after(0, lambda p=percent: self.conversion_status.config(text=f"{p:.2f}% of Conversion Done"))
                        except:
                            pass
                    if "progress=end" in line:
                        break
                process.wait()
                if process.returncode != 0:
                    error_output = process.stdout.read()
                    self.log_event(f"FFmpeg failed with return code {process.returncode}. Output: {error_output}", level="ERROR")
                    self.root.after(0, lambda: messagebox.showerror("Error", "FFmpeg conversion failed."))
                else:
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Video file created at {output_file}"))
                    self.log_event(f"Converted session '{session}' to video file {output_file} at {fps}fps.", level="INFO")
                    self.root.after(0, lambda: self.conversion_status.config(text="Conversion Completed: 100%"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to convert video: {e}"))
                self.log_event(f"Error converting session '{session}' to video file: {e}", level="ERROR")

        threading.Thread(target=run_conversion, daemon=True).start()

    def save_settings(self):
        """Saves the current settings to a JSON file."""
        settings = {
            "save_directory": self.save_directory.get(),
            "interval": self.interval.get(),
            "jpeg_quality": self.jpeg_quality.get(),
            "movement_detection_mode": self.movement_detection_mode.get(),
            "detect_keyboard": self.detect_keyboard.get(),
            "movement_sensitivity": self.movement_sensitivity.get(),
            "enable_motion_detection": self.enable_motion_detection.get(),
            "enable_logging": self.enable_logging.get()
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_event("Settings saved.")
        except Exception as e:
            self.log_event(f"Error saving settings: {e}", level="ERROR")

    def load_settings(self):
        """Loads settings from the JSON file if it exists."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                self.save_directory.set(settings.get("save_directory", ""))
                self.interval.set(settings.get("interval", 5.0))
                self.jpeg_quality.set(settings.get("jpeg_quality", 5))
                self.movement_detection_mode.set(settings.get("movement_detection_mode", "image"))
                self.detect_keyboard.set(settings.get("detect_keyboard", True))
                self.movement_sensitivity.set(settings.get("movement_sensitivity", 2))
                self.enable_motion_detection.set(settings.get("enable_motion_detection", True))
                self.enable_logging.set(settings.get("enable_logging", True))
                self.session_name.set("")
                self.on_mode_change()
                self.on_detection_toggle()
                self.load_sessions()
                self.update_session_dropdown()
                self.log_event("Settings loaded.")
            except Exception as e:
                tb = traceback.format_exc()
                self.log_event(f"Error loading settings: {tb}", level="ERROR")

    def start_input_listeners(self):
        """Starts keyboard and mouse listeners for input-based motion detection."""
        try:
            if self.enable_motion_detection.get():
                if self.detect_keyboard.get():
                    self.keyboard_listener = keyboard.Listener(on_press=self.on_input_event)
                    self.keyboard_listener.start()
                else:
                    self.keyboard_listener = None
                mouse.hook(self.on_mouse_event)
                self.log_event("Keyboard and mouse listeners started.", level="INFO")
            else:
                self.keyboard_listener = None

            if self.detect_keyboard.get() and self.enable_motion_detection.get():
                self.input_status_label.config(text="Input Detection: Active", foreground="green")
            else:
                self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error starting input listeners: {tb}", level="ERROR")
            self.input_status_label.config(text="Input Detection: Error", foreground="red")

    def stop_input_listeners(self):
        """Stops keyboard and mouse listeners."""
        try:
            if self.keyboard_listener is not None:
                self.keyboard_listener.stop()
                self.keyboard_listener = None
                self.log_event("Keyboard listener stopped.", level="INFO")
            mouse.unhook(self.on_mouse_event)
            self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error stopping input listeners: {tb}", level="ERROR")

    def on_input_event(self, key):
        """Callback for keyboard events."""
        try:
            with self.input_lock:
                self.input_activity = True
            self.log_event(f"Keyboard activity detected: {key}", level="INFO")
            self.movement_status_label.config(text="Movement: Detected", foreground="green")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error in keyboard event callback: {tb}", level="ERROR")

    def on_mouse_event(self, event):
        """Callback for mouse events."""
        try:
            if hasattr(event, 'event_type') and event.event_type == 'down':
                if not self.mouse_pressed:
                    self.mouse_pressed = True
                    with self.input_lock:
                        self.input_activity = True
                    self.log_event(f"Mouse button {event.button} pressed at ({event.x}, {event.y})", level="INFO")
                    self.movement_status_label.config(text="Movement: Detected", foreground="green")
            elif hasattr(event, 'event_type') and event.event_type == 'up':
                if self.mouse_pressed:
                    self.mouse_pressed = False
                    self.log_event(f"Mouse button {event.button} released at ({event.x}, {event.y})", level="INFO")
        except AttributeError:
            pass
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error in mouse event callback: {tb}", level="ERROR")

    def monitor_cpu(self):
        """Monitors CPU utilization and updates the progress bar."""
        if not self.is_running:
            return
        cpu_percent = psutil.cpu_percent(interval=None)
        self.update_cpu_bar(cpu_percent)
        self.root.after(1000, self.monitor_cpu)

    def update_cpu_bar(self, cpu_percent):
        """Updates the CPU utilization progress bar with appropriate color."""
        self.cpu_progress['value'] = cpu_percent
        if cpu_percent <= 50:
            style = "green.Horizontal.TProgressbar"
        elif 50 < cpu_percent <= 80:
            style = "orange.Horizontal.TProgressbar"
        else:
            style = "red.Horizontal.TProgressbar"
        current_style = self.cpu_progress['style']
        if current_style != style:
            self.cpu_progress.config(style=style)

    def on_close(self):
        """Handles the application closing event."""
        if self.is_running:
            if messagebox.askokcancel("Quit", "Screenshot capture is running. Do you want to quit?"):
                self.stop_capturing()
                self.save_settings()
                self.root.destroy()
        else:
            self.save_settings()
            self.root.destroy()

def main():
    """Main function to start the application."""
    try:
        root = tk.Tk()
        app = ScreenshotApp(root)
        root.protocol("WM_DELETE_WINDOW", app.on_close)
        root.mainloop()
    except Exception as e:
        error_log_path = resource_path("error_log.txt")
        try:
            with open(error_log_path, "a") as f:
                f.write(f"An unexpected error occurred: {traceback.format_exc()}\n")
        except:
            pass
        messagebox.showerror("Fatal Error", f"An unexpected error occurred:\n{e}")

if __name__ == "__main__":
    main()
