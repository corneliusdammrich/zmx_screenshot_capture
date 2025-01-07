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
import psutil
import traceback

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller.
    """
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
        self.file_format = tk.StringVar(value="png")
        self.interval = tk.DoubleVar(value=5.0)
        self.selected_monitor = tk.StringVar()
        self.jpeg_quality = tk.IntVar(value=5)

        self.movement_detection_mode = tk.StringVar(value="image")
        self.detect_keyboard = tk.BooleanVar(value=True)
        self.movement_sensitivity = tk.IntVar(value=2)
        self.enable_motion_detection = tk.BooleanVar(value=True)

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

        self.settings_file = resource_path("settings.json")

        style = ttk.Style()
        style.theme_use('default')
        style.configure("green.Horizontal.TProgressbar", foreground='green', background='green')
        style.configure("orange.Horizontal.TProgressbar", foreground='orange', background='orange')
        style.configure("red.Horizontal.TProgressbar", foreground='red', background='red')

        self.create_widgets()
        self.load_settings()
        self.populate_monitors()

    def create_widgets(self):
        padding = {'padx': 10, 'pady': 5}

        # Save Directory
        dir_frame = ttk.Frame(self.root)
        dir_frame.pack(fill='x', **padding)
        ttk.Label(dir_frame, text="Save Directory:").pack(side='left')
        ttk.Entry(dir_frame, textvariable=self.save_directory, width=40).pack(side='left', padx=(5,5))
        ttk.Button(dir_frame, text="Browse", command=self.browse_directory).pack(side='left')

        # File Format
        format_frame = ttk.Frame(self.root)
        format_frame.pack(fill='x', **padding)
        ttk.Label(format_frame, text="File Format:").pack(side='left')
        format_options = ["png", "jpg"]
        ttk.OptionMenu(format_frame, self.file_format, self.file_format.get(), *format_options, command=self.on_format_change).pack(side='left', padx=(5,5))

        # JPEG Quality Slider
        self.jpeg_quality_frame = ttk.Frame(self.root)
        self.jpeg_quality_label = ttk.Label(self.jpeg_quality_frame, text="JPEG Quality:")
        self.jpeg_quality_label.pack(side='left')
        self.jpeg_quality_slider = ttk.Scale(self.jpeg_quality_frame, from_=1, to=10, orient='horizontal',
                                             variable=self.jpeg_quality, command=self.on_quality_change, length=200)
        self.jpeg_quality_slider.pack(side='left', padx=(5,5), fill='x', expand=True)
        self.jpeg_quality_value_label = ttk.Label(self.jpeg_quality_frame, textvariable=self.jpeg_quality)
        self.jpeg_quality_value_label.pack(side='left', padx=(5,0))
        self.jpeg_quality_frame.pack_forget()

        # Interval
        interval_frame = ttk.Frame(self.root)
        interval_frame.pack(fill='x', **padding)
        ttk.Label(interval_frame, text="Interval (seconds):").pack(side='left')
        interval_spinbox = ttk.Spinbox(interval_frame, textvariable=self.interval, from_=0.1, to=60.0,
                                       increment=0.1, format="%.1f", width=10)
        interval_spinbox.pack(side='left', padx=(5,5))
        interval_spinbox.set(5.0)

        # Movement Detection Mode
        mode_frame = ttk.Frame(self.root)
        mode_frame.pack(fill='x', **padding)
        ttk.Label(mode_frame, text="Movement Detection Mode:").pack(side='left')
        mode_options = [("Image-Based", "image"), ("Input-Based", "input"), ("Combined", "combined")]
        for text, mode in mode_options:
            ttk.Radiobutton(mode_frame, text=text, variable=self.movement_detection_mode, value=mode,
                            command=self.on_mode_change).pack(side='left', padx=(10,0))

        # Motion Detection Toggle
        detection_toggle_frame = ttk.Frame(self.root)
        detection_toggle_frame.pack(fill='x', **padding)
        ttk.Label(detection_toggle_frame, text="Motion Detection:").pack(side='left')
        ttk.Checkbutton(detection_toggle_frame, text="Enable", variable=self.enable_motion_detection,
                        command=self.on_detection_toggle).pack(side='left', padx=(5,0))

        # Movement Sensitivity Slider
        sensitivity_frame = ttk.Frame(self.root)
        sensitivity_frame.pack(fill='x', **padding)
        ttk.Label(sensitivity_frame, text="Movement Sensitivity (%):").pack(side='left')
        self.sensitivity_slider = ttk.Scale(
            sensitivity_frame, from_=1, to=100, orient='horizontal',
            variable=self.movement_sensitivity, command=self.on_sensitivity_change, length=200
        )
        self.sensitivity_slider.pack(side='left', padx=(5,5), fill='x', expand=True)
        # Label to display current sensitivity value
        self.sensitivity_value_label = ttk.Label(sensitivity_frame, text=f"{self.movement_sensitivity.get()}%")
        self.sensitivity_value_label.pack(side='left', padx=(5,0))
        self.sensitivity_slider.set(2)
        self.sensitivity_slider.pack_forget()

        # Session Management
        session_frame = ttk.Frame(self.root)
        session_frame.pack(fill='x', **padding)
        ttk.Label(session_frame, text="Session:").pack(side='left')
        self.session_dropdown = ttk.OptionMenu(session_frame, self.session_name, "", command=self.on_session_select)
        self.session_dropdown.pack(side='left', padx=(5,5))
        new_session_entry = ttk.Entry(session_frame, textvariable=self.session_name, width=30)
        new_session_entry.pack(side='left', padx=(10,5))
        ttk.Button(session_frame, text="Create New Session", command=self.create_new_session).pack(side='left')

        # Monitor Selection
        monitor_frame = ttk.Frame(self.root)
        monitor_frame.pack(fill='x', **padding)
        ttk.Label(monitor_frame, text="Select Monitor:").pack(side='left')
        self.monitor_menu = ttk.OptionMenu(monitor_frame, self.selected_monitor, "")
        self.monitor_menu.pack(side='left', padx=(5,5))

        # Start/Stop Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill='x', **padding)
        self.start_button = ttk.Button(button_frame, text="Start", command=self.start_capturing)
        self.start_button.pack(side='left', expand=True, fill='x', padx=(0,5))
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self.stop_capturing, state='disabled')
        self.stop_button.pack(side='left', expand=True, fill='x', padx=(5,0))

        # Progress Bar
        progress_frame = ttk.Frame(self.root)
        progress_frame.pack(fill='x', **padding)
        ttk.Label(progress_frame, text="Activity:").pack(side='left')
        self.progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.progress_bar.pack(side='left', fill='x', expand=True, padx=(5,0))

        # CPU Utilization
        cpu_frame = ttk.LabelFrame(self.root, text="CPU Utilization")
        cpu_frame.pack(fill='x', padx=10, pady=10)
        self.cpu_progress = ttk.Progressbar(cpu_frame, orient='horizontal', length=300,
                                            mode='determinate', maximum=100, style="green.Horizontal.TProgressbar")
        self.cpu_progress.pack(padx=10, pady=10)

        # Status Labels
        self.screenshot_label = ttk.Label(self.root, text="Current Screenshot: None")
        self.screenshot_label.pack(fill='x', padx=10, pady=5)
        self.movement_status_label = ttk.Label(self.root, text="Movement: None", foreground="red")
        self.movement_status_label.pack(fill='x', padx=10, pady=5)
        self.input_status_label = ttk.Label(self.root, text="Input Detection: Active", foreground="green")
        self.input_status_label.pack(fill='x', padx=10, pady=5)
        self.status_label = ttk.Label(self.root, text="Status: Idle")
        self.status_label.pack(fill='x', **padding)

    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.save_directory.set(directory)
            # Clear session data on new directory selection
            self.session_name.set("")
            self.sessions = []
            self.load_sessions()
            self.update_session_dropdown()
            self.save_settings()

    def initialize_logging_and_counter(self):
        """Initialize log file and session counter based on current session."""
        if self.save_directory.get() and self.session_name.get():
            session_folder = os.path.join(self.save_directory.get(), self.session_name.get())
            os.makedirs(session_folder, exist_ok=True)
            self.log_file = os.path.join(session_folder, "screenshot_log.txt")
            self.counter_file = os.path.join(session_folder, "screenshot_counter.txt")
            if not os.path.exists(self.log_file):
                with open(self.log_file, 'w') as f:
                    f.write(f"zmxTOOL Screen(shot) Recorder Log - Session: {self.session_name.get()}\n")
                    f.write("=========================================\n\n")
            self.load_counter()

    def load_counter(self):
        if self.counter_file and os.path.exists(self.counter_file):
            try:
                with open(self.counter_file, 'r') as f:
                    last_counter = f.read().strip()
                    self.counter = int(last_counter) + 1 if last_counter.isdigit() else 1
            except Exception as e:
                self.log_event(f"Error reading counter file: {e}", level="ERROR")
                self.counter = 1
        else:
            self.counter = 1

    def save_counter(self):
        if self.counter_file:
            try:
                with open(self.counter_file, 'w') as f:
                    f.write(str(self.counter))
            except Exception as e:
                self.log_event(f"Error writing counter file: {e}", level="ERROR")

    def log_event(self, message, level="INFO"):
        if self.log_file:
            try:
                with open(self.log_file, 'a') as f:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{timestamp}] [{level}] {message}\n")
            except Exception as e:
                messagebox.showerror("Logging Error", f"Failed to write to log file: {e}")

    def populate_monitors(self):
        with mss.mss() as sct:
            monitors = sct.monitors
            monitor_list = []
            for idx, monitor in enumerate(monitors[1:], start=1):
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
                self.selected_monitor.set(monitor_list[0])

    def on_format_change(self, *args):
        selected_format = self.file_format.get().lower()
        if selected_format == "jpg":
            self.jpeg_quality_frame.pack(fill='x', padx=10, pady=5)
        else:
            self.jpeg_quality_frame.pack_forget()

    def on_quality_change(self, value):
        self.jpeg_quality.set(int(float(value)))

    def on_mode_change(self):
        mode = self.movement_detection_mode.get()
        if mode in ["input", "image", "combined"]:
            self.sensitivity_slider.pack(fill='x', padx=10, pady=5)
        else:
            self.sensitivity_slider.pack_forget()

    def on_sensitivity_change(self, value):
        # Update sensitivity value and label
        self.movement_sensitivity.set(int(float(value)))
        self.sensitivity_value_label.config(text=f"{self.movement_sensitivity.get()}%")
        self.log_event(f"Movement Sensitivity set to {self.movement_sensitivity.get()}%.")

    def on_detection_toggle(self):
        state = self.enable_motion_detection.get()
        status = "enabled" if state else "disabled"
        self.log_event(f"Motion detection {status}.")
        if state:
            self.input_status_label.config(text="Input Detection: Active", foreground="green")
        else:
            self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
            self.movement_status_label.config(text="Movement: None", foreground="red")

    def load_sessions(self):
        if self.save_directory.get() and os.path.isdir(self.save_directory.get()):
            try:
                self.sessions = [d for d in os.listdir(self.save_directory.get())
                                 if os.path.isdir(os.path.join(self.save_directory.get(), d))]
            except Exception as e:
                self.log_event(f"Error reading session folders: {e}", level="ERROR")
                self.sessions = []
        else:
            self.sessions = []

    def update_session_dropdown(self):
        menu = self.session_dropdown["menu"]
        menu.delete(0, "end")
        for session in self.sessions:
            menu.add_command(label=session, command=lambda value=session: self.session_name.set(value))
        if self.sessions:
            if self.session_name.get() not in self.sessions:
                self.session_name.set(self.sessions[0])
        else:
            self.session_name.set("")

    def on_session_select(self, value):
        selected_session = value
        self.session_name.set(selected_session)
        print(f"Session selected: {selected_session}")

    def create_new_session(self):
        session = self.session_name.get().strip()
        if not session:
            messagebox.showwarning("Input Error", "Please enter a valid session name.")
            return
        if session in self.sessions:
            messagebox.showwarning("Input Error", "Session name already exists. Please choose a different name.")
            return
        self.sessions.append(session)
        session_folder = os.path.join(self.save_directory.get(), session)
        os.makedirs(session_folder, exist_ok=True)
        self.update_session_dropdown()
        messagebox.showinfo("Success", f"Session '{session}' created successfully.")
        self.log_event(f"Session '{session}' created.")

    def start_capturing(self):
        if not self.save_directory.get():
            messagebox.showwarning("Input Error", "Please select a save directory.")
            return
        if not os.path.isdir(self.save_directory.get()):
            messagebox.showwarning("Input Error", "Selected save directory does not exist.")
            return
        if not self.session_name.get():
            messagebox.showwarning("Input Error", "Please select or create a session.")
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

        self.initialize_logging_and_counter()
        self.log_event("Starting screenshot capture.")
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.is_running = True
        self.stop_event.clear()
        self.progress_bar.start(10)
        self.update_status("Running")
        mode = self.movement_detection_mode.get()
        if mode in ["image", "combined"]:
            self.previous_image = None
        self.start_input_listeners()
        self.thread = threading.Thread(target=self.capture_screenshots, daemon=True)
        self.thread.start()
        self.monitor_cpu()
        self.save_settings()

    def stop_capturing(self):
        if self.is_running:
            self.stop_event.set()
            self.progress_bar.stop()
            self.is_running = False
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            self.update_status("Stopped")
            self.log_event("Stopped screenshot capture.")
            self.stop_input_listeners()
            self.save_settings()

    def capture_screenshots(self):
        try:
            monitor_str = self.selected_monitor.get()
            try:
                monitor_idx = int(monitor_str.split(":")[0].split(" ")[1])
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
                current_date = datetime.now().strftime("%Y-%m-%d")

                while not self.stop_event.is_set():
                    try:
                        sct_img = sct.grab(monitor)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                    except Exception as e:
                        self.queue_status(f"Error capturing screen: {e}")
                        self.log_event(f"Error capturing screen: {e}", level="ERROR")
                        self.stop_event.set()
                        break

                    movement_detected = False

                    if not self.enable_motion_detection.get():
                        movement_detected = True
                        self.log_event("Motion detection is disabled. Capturing screenshot unconditionally.", level="INFO")
                        self.queue_status("Running: Motion Detection Disabled")
                        self.movement_status_label.config(text="Motion Detection: Disabled", foreground="orange")
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
        counter_str = f"{self.counter:06d}"
        extension = "png" if self.file_format.get() == "png" else "jpeg"
        filename = f"{self.session_name.get()}_{counter_str}.{extension}"
        session_folder = os.path.join(self.save_directory.get(), self.session_name.get())
        os.makedirs(session_folder, exist_ok=True)
        filepath = os.path.join(session_folder, filename)

        try:
            self.screenshot_label.config(text=f"Saving: {filename}")
            if extension == "png":
                img.save(filepath, "PNG")
            else:
                img = img.convert("RGB")
                if self.jpeg_quality.get() == 10:
                    pillow_quality = 95
                else:
                    pillow_quality = max(1, min(95, int((self.jpeg_quality.get() / 10) * 95)))
                img.save(filepath, "JPEG", quality=pillow_quality)
            self.queue_status(f"Saved: {filename} ({detection_type.capitalize()} Detection)")
            self.log_event(f"Saved: {filename} ({detection_type.capitalize()} Detection)")
            self.save_counter()
            self.counter += 1
            if self.counter > 999999:
                self.queue_status("Error: Maximum screenshot limit reached.")
                self.log_event("Error: Maximum screenshot limit reached.", level="ERROR")
                self.stop_event.set()
            self.screenshot_label.config(text=f"Saved: {filename}")
        except Exception as e:
            self.queue_status(f"Error saving screenshot: {e}")
            self.log_event(f"Error saving screenshot: {e}", level="ERROR")
            self.stop_event.set()

    def queue_status(self, message):
        self.root.after(0, self.update_status, message)

    def update_status(self, message):
        self.status_label.config(text=f"Status: {message}")

    def save_settings(self):
        settings = {
            "save_directory": self.save_directory.get(),
            "file_format": self.file_format.get(),
            "interval": self.interval.get(),
            "selected_monitor": self.selected_monitor.get(),
            "jpeg_quality": self.jpeg_quality.get(),
            "movement_detection_mode": self.movement_detection_mode.get(),
            "detect_keyboard": self.detect_keyboard.get(),
            "movement_sensitivity": self.movement_sensitivity.get(),
            "enable_motion_detection": self.enable_motion_detection.get()
            # session_name is intentionally not saved
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
            self.log_event("Settings saved.")
        except Exception as e:
            self.log_event(f"Error saving settings: {e}", level="ERROR")

    def load_settings(self):
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
                self.enable_motion_detection.set(settings.get("enable_motion_detection", True))
                self.session_name.set("")  # Do not restore session from settings
                self.on_format_change()
                self.on_mode_change()
                self.on_detection_toggle()
                self.load_sessions()
                self.update_session_dropdown()
                self.log_event("Settings loaded.")
            except Exception as e:
                tb = traceback.format_exc()
                self.log_event(f"Error loading settings: {tb}", level="ERROR")

    def start_input_listeners(self):
        try:
            if self.detect_keyboard.get() and self.enable_motion_detection.get():
                self.keyboard_listener = keyboard.Listener(on_press=self.on_input_event)
                self.keyboard_listener.start()
                self.log_event("Keyboard listener started.", level="INFO")
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
        try:
            if hasattr(self, 'keyboard_listener') and self.keyboard_listener is not None:
                self.keyboard_listener.stop()
                self.keyboard_listener = None
                self.log_event("Keyboard listener stopped.", level="INFO")
            self.input_status_label.config(text="Input Detection: Inactive", foreground="red")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error stopping input listeners: {tb}", level="ERROR")

    def on_input_event(self, key):
        try:
            with self.input_lock:
                self.input_activity = True
            self.log_event(f"Input activity detected: {key}", level="INFO")
            self.movement_status_label.config(text="Movement: Detected", foreground="green")
        except Exception as e:
            tb = traceback.format_exc()
            self.log_event(f"Error in input event callback: {tb}", level="ERROR")

    def monitor_cpu(self):
        if not self.is_running:
            return
        cpu_percent = psutil.cpu_percent(interval=None)
        self.update_cpu_bar(cpu_percent)
        self.root.after(1000, self.monitor_cpu)

    def update_cpu_bar(self, cpu_percent):
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
        if self.is_running:
            if messagebox.askokcancel("Quit", "Screenshot capture is running. Do you want to quit?"):
                self.stop_capturing()
                self.save_settings()
                self.root.destroy()
        else:
            self.save_settings()
            self.root.destroy()

def main():
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
