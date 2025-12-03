import os
import sys
import glob
import logging
import time
import datetime
import threading


import gradio as gr

import video_brand_automator as engine


# ---------------------------------------------------------------------------
# FIX FOR PYINSTALLER --NOCONSOLE CRASH
# Uvicorn requires a valid stdout/stderr to configure logging, even if unused.
# ---------------------------------------------------------------------------
if sys.stdout is None:

    class NullWriter:
        def write(self, data):
            pass

        def flush(self):
            pass

        def isatty(self):
            return False  # This prevents the crash

    sys.stdout = NullWriter()
    sys.stderr = NullWriter()

# ---------------------------------------------------------------------------
# 1. LOGGING SETUP (File Persistence)
# ---------------------------------------------------------------------------
LOG_FILENAME = "video_brander_logs.txt"


def setup_file_logging():
    """
    Configures logging to write to a file with a session header.
    """
    # 1. Create a file handler
    file_handler = logging.FileHandler(LOG_FILENAME, mode="a", encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)

    # 2. Attach to the Engine's logger (so we capture the backend logic)
    engine_logger = logging.getLogger("VideoAutomator")
    engine_logger.addHandler(file_handler)

    # 3. Create a GUI logger for high-level events
    gui_logger = logging.getLogger("GUI")
    gui_logger.setLevel(logging.INFO)
    gui_logger.addHandler(file_handler)

    # 4. Write Session Header
    separator = "=" * 50
    header = f"\n{separator}\nSESSION START: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{separator}"

    # Write directly to file to ensure header exists even if logging is silent
    with open(LOG_FILENAME, "a", encoding="utf-8") as f:
        f.write(header + "\n")

    return gui_logger


# Initialize Logger
gui_logger = setup_file_logging()

# ---------------------------------------------------------------------------
# 2. HELPER FUNCTIONS
# ---------------------------------------------------------------------------


def get_base_path():
    """
    Returns the folder where the script (or .exe) is running.
    Crucial for the 'Default' behavior to work in portable mode.
    """
    if getattr(sys, "frozen", False):
        # If running as a compiled .exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def kill_app():
    """
    Gracefully kills the app.
    Spawns a background thread to kill the process after 1 second,
    allowing this function to return successfully to the browser first.
    """

    def _shutdown():
        time.sleep(1.0)  # Wait for browser to receive the "OK"
        gui_logger.info("Shutdown sequence complete. Exiting.")
        os._exit(0)

    # Start the countdown in the background
    threading.Thread(target=_shutdown).start()

    # Return immediately so the browser sees a "Success" state
    return "⚡ Shutting down... You can close this tab now."


def run_processing_job(
    folder_path_input,
    image_path_input,
    margin_pct,
    position,
    start_pct,
    duration,
    scale_input,
    mode_selection,
):
    """
    The Bridge Logic:
    1. Resolves paths (uses Defaults if inputs are empty).
    2. Finds files.
    3. Calls the engine's process_single_video() in a loop.
    4. Yields real-time logs to the GUI.
    """
    base_dir = get_base_path()
    logs = []

    gui_logger.info(f"Job started. Mode: {mode_selection}")

    # --- 1. HANDLE DEFAULTS (The "Click Submit" Magic) ---

    # A. Video Folder
    video_folder = folder_path_input.strip()
    if not video_folder:
        video_folder = os.path.join(base_dir, "videos")
        logs.append(f"ℹ️ Input empty. Using default folder: {video_folder}")

    # B. Image File
    overlay_image = image_path_input
    if not overlay_image:
        default_img_dir = os.path.join(base_dir, "images")
        # Find first valid image
        possibles = glob.glob(os.path.join(default_img_dir, "*"))
        valid_imgs = [
            f
            for f in possibles
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ]

        if valid_imgs:
            overlay_image = valid_imgs[0]
            logs.append(
                f"ℹ️ Image empty. Using default: {os.path.basename(overlay_image)}"
            )
        else:
            msg = "❌ Error: No image provided and none found in ./images"
            gui_logger.error(msg)
            yield "\n".join(logs) + "\n" + msg
            return

    # --- 2. VALIDATION ---
    if not os.path.exists(video_folder):
        msg = f"❌ Error: Video folder not found: {video_folder}"
        gui_logger.error(msg)
        yield "\n".join(logs) + "\n" + msg
        return

    if not os.path.exists(overlay_image):
        msg = f"\n❌ Error: Image not found: {overlay_image}"
        gui_logger.error(msg)
        yield "\n".join(logs) + "\n" + msg
        return

    # Create Output Folder (default to ./output inside the source folder or root)
    output_folder = os.path.join(base_dir, "output")
    os.makedirs(output_folder, exist_ok=True)

    # --- 3. DISCOVERY ---
    video_extensions = ("*.mp4", "*.mov", "*.mkv", "*.avi", "*.webm")
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(os.path.join(video_folder, ext)))

    if not video_files:
        msg = f"⚠️ No videos found in {video_folder}"
        gui_logger.warning(msg)
        yield "\n".join(logs) + "\n" + msg
        return

    msg_start = f"✅ Found {len(video_files)} videos. Starting Batch..."
    gui_logger.info(msg_start)
    logs.append(msg_start)
    yield "\n".join(logs)

    # --- 4. EXECUTION LOOP ---
    success_count = 0
    total = len(video_files)

    # Convert scale input (Gradio might pass 0 or None)
    final_scale = float(scale_input) if scale_input > 0 else None
    # Convert margin from integer 5 to float 0.05
    final_margin = float(margin_pct) / 100.0

    for i, vid_path in enumerate(video_files, 1):
        filename = os.path.basename(vid_path)
        name_only = os.path.splitext(filename)[0]
        out_path = os.path.join(output_folder, f"{name_only}_branded.mp4")

        # Stream update
        current_log = f"⏳ [{i}/{total}] Processing: {filename}..."
        yield "\n".join(logs + [current_log])

        try:
            # CALL THE ENGINE
            engine.process_single_video(
                video=vid_path,
                image=overlay_image,
                out=out_path,
                position=position,  # e.g., "center"
                scale=final_scale,  # e.g., None or 0.5
                margin=final_margin,  # e.g., 0.05
                start_percent=start_pct,  # e.g., 75.0
                duration_sec=duration,  # e.g., 5.0
                fade_in=0.5,  # Hardcoded polish
                fade_out=0.5,
                mode=mode_selection.lower(),  # "ffmpeg" or "moviepy"
                overwrite=True,
                threads=4,
            )
            success_count += 1
            logs.append(f"✔️ Finished: {filename}")

        except Exception as e:
            err_msg = f"❌ Failed: {filename} ({str(e)})"
            gui_logger.error(err_msg)
            logs.append(err_msg)

        yield "\n".join(logs)

    # Final Summary
    final_msg = f"🎉 Batch Complete. {success_count}/{total} videos processed."
    gui_logger.info(final_msg)
    logs.append("-" * 30)
    logs.append(final_msg)
    logs.append(f"📂 Output Folder: {output_folder}")
    yield "\n".join(logs)


# ---------------------------------------------------------------------------
# 3. GUI LAYOUT
# ---------------------------------------------------------------------------


def build_interface():
    with gr.Blocks(title="Video Brand Automator") as app:
        gr.Markdown("# 🎥 Video Branding Tool")
        gr.Markdown(
            "Leave inputs empty to use default folders (`./videos` and `./images`)."
        )

        with gr.Row():
            with gr.Column(scale=2):
                # --- MAIN INPUTS ---
                folder_input = gr.Textbox(
                    label="Source Video Folder",
                    placeholder="Leave empty to use './videos'",
                )
                image_input = gr.Image(
                    label="Overlay Image",
                    type="filepath",
                    height=150,
                    sources=["upload", "clipboard"],
                )

                # --- ADVANCED SETTINGS (Accordion) ---
                with gr.Accordion("⚙️ Settings", open=False):
                    mode_select = gr.Radio(
                        ["FFmpeg", "MoviePy"],
                        label="Engine",
                        value="FFmpeg",
                    )
                    with gr.Row():
                        margin_slider = gr.Slider(
                            0, 50, value=5, step=1, label="Margin (%)"
                        )
                        scale_num = gr.Number(value=0, label="Force Scale (0 = Auto)")

                    with gr.Row():
                        start_slider = gr.Slider(
                            0, 100, value=75, label="Start Time (%)"
                        )
                        duration_num = gr.Number(value=5, label="Duration (s)")

                    pos_dropdown = gr.Dropdown(
                        [
                            "center",
                            "top-left",
                            "top-right",
                            "bottom-left",
                            "bottom-right",
                        ],
                        value="center",
                        label="Position",
                    )

                # --- ACTION BUTTONS ---
                with gr.Row():
                    submit_btn = gr.Button(
                        "🚀 Start Process", variant="primary", scale=2
                    )
                    exit_btn = gr.Button("❌ Exit App", variant="stop", scale=1)

            with gr.Column(scale=3):
                # --- LOG OUTPUT ---
                output_log = gr.Textbox(
                    label="Logs",
                    lines=22,
                    autoscroll=True,
                    value="Ready...",
                )

        # --- EVENT BINDING ---
        submit_btn.click(
            fn=run_processing_job,
            inputs=[
                folder_input,
                image_input,
                margin_slider,
                pos_dropdown,
                start_slider,
                duration_num,
                scale_num,
                mode_select,
            ],
            outputs=output_log,
        )
        exit_btn.click(fn=kill_app, inputs=None, outputs=output_log)

    return app


if __name__ == "__main__":
    app = build_interface()
    # allow_flagging="never" is handled inside Blocks implicitly by not adding flag buttons
    app.launch(inbrowser=True)
