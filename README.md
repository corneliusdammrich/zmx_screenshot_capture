## Features

- **Configurable Capture:**
  - Set save directory, JPEG quality, and interval.
  - **Monitor Capture:** Select and capture specific monitors.
  - **Active Window Capture:** Capture only the currently active window.

- **Motion & Input Detection:**
  - Enable/disable motion detection.
  - Choose detection mode: image-based, input-based, or combined.
  - Adjust sensitivity for image-based detection.
  - Listens for keyboard and mouse button events (note: continuous mouse movement isn’t detected).

- **Session Management:**
  - Create/select sessions with separate folders.
  - Continue existing sessions and track frame counts.

- **Real-Time Status:**
  - Display current screenshot filename.
  - Show movement and input detection status.
  - Indicate overall capture status and CPU usage.

- **Video Conversion:**
  - Select FPS and resolution.
  - Convert session screenshots into an MP4 video using FFmpeg.
  - Display conversion progress and notify upon completion.

- **Settings Persistence & Logging:**
  - Save/load user settings in a JSON file.
  - Log events/errors to session-specific log files.
