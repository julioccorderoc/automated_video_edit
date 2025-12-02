r"""
video_brand_automator.py

OBJECTIVE:
    Automates the process of overlaying an image (logo/branding) onto videos.
    The overlay appears at a specific percentage of the video duration (default 75%)
    and remains for a set duration (default 5s).

    Supports two modes of operation:
    1. AUTOMATION (Batch): Processes all videos in a './videos' folder using an image from './images'.
    2. MANUAL (CLI): Processes a specific video and image via command line arguments.

DEPENDENCIES:
    1. Python 3.9+
    2. FFmpeg installed on system PATH.
    3. Libraries: pip install "moviepy>=2.0.0" click

USAGE EXAMPLES:

    [A] AUTOMATION MODE (Default - MoviePy Engine)
        1. Create 'videos', 'images', 'output' folders.
        2. Run:
           python video_brand_automator.py

    [B] AUTOMATION MODE (High Performance - FFmpeg Engine)
        # Use this for large files or if audio sync issues occur.
        # Processes all videos in ./videos using the logo in ./images
        python video_brand_automator.py --mode ffmpeg --overwrite

    [C] AUTOMATION MODE (Custom Folders)
        # Processes all videos in "C:\Raw" using the logo in "C:\Assets"
        python video_brand_automator.py --video "C:\Raw" --image "C:\Assets\logo.png" --out "C:\Done" --margin 0.05

    [D] MANUAL MODE (Smart Resize)
        # Fits image to video width/height with 5% margin
        python video_brand_automator.py --video input.mp4 --image logo.png --margin 0.05

    [E] MANUAL MODE (Force Scale)
        # Forces image to be 30% of original size (ignores margin)
        python video_brand_automator.py --video input.mp4 --image logo.png --scale 0.3

    [F] ADVANCED
        # 50% start time, 3s duration, top-right position
        python video_brand_automator.py --video input.mp4 --image logo.png \
        --start-percent 50 --duration 3 --position top-right --mode ffmpeg
"""

import os
import sys
import glob
import logging
import subprocess
import click
import time
from datetime import timedelta
from typing import Union, Tuple, Optional, Dict

# ---------------------------------------------------------------------------
# CONFIGURATION & LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VideoAutomator")

# ---------------------------------------------------------------------------
# DEPENDENCY CHECK
# ---------------------------------------------------------------------------
try:
    from moviepy import VideoFileClip, ImageClip, CompositeVideoClip, vfx
except ImportError:
    logger.error("MoviePy v2.0+ is not installed.")
    logger.error('Please run: pip install "moviepy>=2.0.0" click')
    sys.exit(1)


# ---------------------------------------------------------------------------
# CORE LOGIC
# ---------------------------------------------------------------------------


def get_binary_path(binary_name: str) -> str:
    """
    Smartly resolves the path to external tools (ffmpeg/ffprobe).
    Priority:
    1. Look in the current script directory (Best for portability & compiled .exe).
    2. Look in system PATH.
    """
    # 1. Check local folder (e.g., C:\Users\...\video_edit\ffmpeg.exe)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(base_dir, binary_name)

    # Windows requires .exe extension check
    if sys.platform.startswith("win"):
        if not local_path.lower().endswith(".exe"):
            local_path += ".exe"

    if os.path.exists(local_path):
        return local_path

    # 2. Fallback to system PATH (return just the name)
    return binary_name


def get_overlay_timing(
    video_duration: float, start_pct: float, target_duration: float
) -> Tuple[float, float]:
    """
    Calculates start time and actual duration.
    Ensures the overlay does not extend beyond the video's end.
    """
    start_time = video_duration * start_pct

    # If start time is beyond video length, return 0 duration (skip)
    if start_time >= video_duration:
        return start_time, 0.0

    # Clamp duration to available remaining time
    remaining = video_duration - start_time
    actual_duration = min(target_duration, remaining)

    return start_time, actual_duration


def calculate_smart_scale(
    video_size: Tuple[Union[int, float], Union[int, float]],
    image_size: Tuple[Union[int, float], Union[int, float]],
    margin_pct: float,
) -> float:
    """
    Calculates the scale factor to fit the image inside the video with a margin.
    Logic:
      1. Calculate available space: Video Dimension - (2 * Margin).
      2. Compare Image Width vs Available Width.
      3. Compare Image Height vs Available Height.
      4. Use the smaller scale factor to ensure it fits entirely (Aspect Ratio Preserved).
    """
    vw, vh = video_size
    iw, ih = image_size

    # Calculate safe area (subtracting margin from both sides)
    # margin_pct is 0.05 for 5%.
    safe_w = vw * (1.0 - (2 * margin_pct))
    safe_h = vh * (1.0 - (2 * margin_pct))

    # Calculate scale needed for width and height
    scale_w = safe_w / iw
    scale_h = safe_h / ih

    # Choose the smaller scale to ensure it fits within BOTH dimensions
    # This effectively "matches" the video width or height, whichever is the constraint.
    final_scale = min(scale_w, scale_h)

    return final_scale


def mode_moviepy(
    video_path: str,
    image_path: str,
    output_path: str,
    start_pct: float,
    duration_sec: float,
    position: Union[str, Tuple[float, float]],
    scale: Optional[float],
    margin: float,
    fade_in: float,
    fade_out: float,
    threads: int,
):
    try:
        video = VideoFileClip(video_path)
    except Exception as e:
        raise RuntimeError(f"Could not load video {video_path}: {e}")

    logger.info(
        f"Video: {os.path.basename(video_path)} | Size: {video.size} | Duration: {video.duration:.2f}s"
    )

    # --- TIMING LOGIC ---
    start_t, dur_t = get_overlay_timing(video.duration, start_pct, duration_sec)

    if dur_t <= 0:
        logger.warning("Overlay skipped (Start time is after video ends).")
        if video.audio:
            video.write_videofile(
                output_path, codec="libx264", audio_codec="aac", logger=None
            )
        else:
            video.write_videofile(output_path, codec="libx264", logger=None)
        return

    logger.info(f"Overlay Timing: Start={start_t:.2f}s | Duration={dur_t:.2f}s")

    # --- IMAGE PREPARATION ---
    # FIX 1: Set duration immediately on the image clip
    img = ImageClip(image_path).with_duration(dur_t)

    # Smart Resizing
    target_scale = 1.0
    if scale is not None:
        target_scale = scale
    else:
        target_scale = calculate_smart_scale(
            (video.size[0], video.size[1]), (img.size[0], img.size[1]), margin
        )
        logger.info(f"Auto-calculated scale: {target_scale:.3f}")

    img = img.with_effects([vfx.Resize(target_scale)])

    # FIX 2: Apply position and start time AFTER duration is set
    img = img.with_start(start_t).with_position(position)

    # Fades
    effects = []
    if fade_in > 0:
        effects.append(vfx.CrossFadeIn(fade_in))
    if fade_out > 0:
        effects.append(vfx.CrossFadeOut(fade_out))
    if effects:
        img = img.with_effects(effects)

    # --- COMPOSITING FIX ---
    # FIX 3: Do not use use_bgclip=True alone. Explicitly build the composite.
    # We layer [video, img].
    final = CompositeVideoClip([video, img], size=video.size)

    # FIX 4: Explicitly force the Duration and FPS to match the source video
    # This prevents the "Freeze" where the compositor thinks the video ended early.
    final = final.with_duration(video.duration).with_fps(video.fps)

    # Audio Sync
    if video.audio:
        final = final.with_audio(video.audio)

    # Render
    logger.info(f"Rendering -> {output_path}")
    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        threads=threads,
        preset="fast",
        logger="bar" if sys.stdout.isatty() else None,
    )

    video.close()
    img.close()
    final.close()


def get_media_info_ffmpeg(path: str) -> Dict[str, Union[int, float]]:
    """Helper: Returns duration, width, height using ffprobe."""
    # CHANGED: Use helper to find ffprobe
    ffprobe_bin = get_binary_path("ffprobe")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        # Output format is usually: width\nheight\nduration
        out = subprocess.check_output(cmd).decode("utf-8").strip().splitlines()
        if len(out) >= 3:
            return {
                "width": int(out[0]),
                "height": int(out[1]),
                "duration": float(out[2]),
            }
        return {"width": int(out[0]), "height": int(out[1]), "duration": 0.0}
    except FileNotFoundError:
        # Specific error if ffprobe.exe is still missing
        raise RuntimeError(f"Could not find '{ffprobe_bin}'. Did you download FFmpeg?")
    except Exception as e:
        raise RuntimeError(f"FFprobe failed for {path}: {e}")


def mode_ffmpeg_cli(
    video_path: str,
    image_path: str,
    output_path: str,
    start_pct: float,
    duration_sec: float,
    position: str,
    scale: Optional[float],
    margin: float,
    overwrite: bool,
):
    # 1. Get Video & Image Info
    try:
        v_info = get_media_info_ffmpeg(video_path)
        i_info = get_media_info_ffmpeg(image_path)
    except Exception as e:
        logger.error(f"{e}")
        return

    total_duration = v_info["duration"]

    # 2. Calculate Timing
    start_t, dur_t = get_overlay_timing(total_duration, start_pct, duration_sec)
    end_t = start_t + dur_t

    # CHANGED: Use helper to find ffmpeg
    ffmpeg_bin = get_binary_path("ffmpeg")

    if dur_t <= 0:
        logger.warning("Overlay out of bounds. Copying stream.")
        subprocess.run([ffmpeg_bin, "-i", video_path, output_path])
        return

    # 3. Calculate Scale
    if scale is not None:
        final_scale = scale
    else:
        final_scale = calculate_smart_scale(
            (int(v_info["width"]), int(v_info["height"])),
            (int(i_info["width"]), int(i_info["height"])),
            margin,
        )
        logger.info(f"FFmpeg Auto-Scale: {final_scale:.3f} (Margin {margin * 100}%)")

    # 4. Filter Construction
    pos_map = {
        "center": "x=(W-w)/2:y=(H-h)/2",
        "top-left": "x=0:y=0",
        "top-right": "x=W-w:y=0",
        "bottom-left": "x=0:y=H-h",
        "bottom-right": "x=W-w:y=H-h",
    }
    overlay_xy = pos_map.get(position, position)

    filter_complex = (
        f"[1:v]scale=iw*{final_scale}:-1[ovr];"
        f"[0:v][ovr]overlay={overlay_xy}:enable='between(t,{start_t:.3f},{end_t:.3f})'"
    )

    cmd_ffmpeg = [
        ffmpeg_bin,
        "-i",
        video_path,
        "-i",
        image_path,
        "-filter_complex",
        filter_complex,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-y" if overwrite else "-n",
        output_path,
    ]

    logger.info("Running FFmpeg...")
    subprocess.run(cmd_ffmpeg, check=True)


def process_single_video(
    video: str,
    image: str,
    out: str,
    position: str,
    scale: Optional[float],  # Updated type
    margin: float,  # Added argument
    start_percent: float,
    duration_sec: float,
    fade_in: float,
    fade_out: float,
    mode: str,
    overwrite: bool,
    threads: int,
):
    """
    Orchestrator for a single video. Handles checks, normalization, and dispatching.
    """
    if not overwrite and os.path.exists(out):
        logger.warning(f"File '{out}' exists. Skipping. Use --overwrite to force.")
        return

    # Normalize Percentage
    final_pct = start_percent
    if start_percent > 1.0:
        final_pct = start_percent / 100.0

    if not (0.0 <= final_pct <= 1.0):
        logger.error(f"Invalid start percentage: {start_percent}. Must be 0-100.")
        return

    logger.info(f"Processing: {os.path.basename(video)}")

    if mode == "moviepy":
        # Coordinate Parsing
        pos_arg = position
        if "," in position:
            try:
                x, y = map(str.strip, position.split(","))
                x = float(x) if x.replace(".", "", 1).isdigit() else None
                y = float(y) if y.replace(".", "", 1).isdigit() else None
                if x is not None and y is not None:
                    pos_arg = (x, y)
                else:
                    raise ValueError
            except ValueError:
                pos_arg = (0.0, 0.0)

        mode_moviepy(
            video,
            image,
            out,
            final_pct,
            duration_sec,
            pos_arg,
            scale,
            margin,
            fade_in,
            fade_out,
            threads,
        )

    elif mode == "ffmpeg":
        mode_ffmpeg_cli(
            video,
            image,
            out,
            final_pct,
            duration_sec,
            position,
            scale,
            margin,
            overwrite,
        )


# ---------------------------------------------------------------------------
# CLI & BATCH ORCHESTRATION
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--video", required=False, help="Input video file OR Directory of videos."
)
@click.option("--image", required=False, help="Input image file.")
@click.option("--out", required=False, help="Output file path (or Output Folder).")
@click.option(
    "--position", default="center", help="Position: 'center', 'top-left' or '100,200'."
)
@click.option(
    "--scale", default=None, type=float, help="Force specific scale (Overrides margin)."
)
@click.option(
    "--margin",
    default=0.0,
    help="Margin as % of video size (0.05 = 5%). Used if scale is not set.",
)
@click.option("--start-percent", default=75.0, help="Start overlay at this % of video.")
@click.option(
    "--duration", "duration_sec", default=5.0, help="Duration of overlay in seconds."
)
@click.option("--fade-in", default=0.0, help="Fade-in seconds.")
@click.option("--fade-out", default=0.0, help="Fade-out seconds.")
@click.option(
    "--mode",
    type=click.Choice(["moviepy", "ffmpeg"]),
    default="moviepy",
    help="Rendering engine.",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing files.")
@click.option("--threads", default=4, help="CPU threads.")
def main(
    video,
    image,
    out,
    position,
    scale,
    margin,
    start_percent,
    duration_sec,
    fade_in,
    fade_out,
    mode,
    overwrite,
    threads,
):
    """
    Main Entry Point.
    """
    # METRICS START
    process_start_time = time.time()
    total_video_duration_processed = 0.0
    videos_processed_count = 0

    # Helper to calculate video length before processing (for logging)
    def get_vid_duration(path):
        try:
            # Quick probe using MoviePy context just to read header
            with VideoFileClip(path) as v:
                return v.duration
        except (OSError, IOError, ValueError):
            # OSError: file not found or permission denied
            # IOError: I/O related errors
            # ValueError: invalid video format
            logger.debug(f"Could not read duration from {path}")
            return 0.0

    # --- LOGIC: LIST OF VIDEOS TO PROCESS ---
    tasks = []  # List of tuples: (vid_path, img_path, out_path)

    # 1. BATCH MODE (Custom Folder)
    if video and os.path.isdir(video):
        logger.info(f"Batch Mode Detected: Input folder '{video}'")
        video_dir = video

        image_path = image
        if not image_path:
            imgs = glob.glob(os.path.join("images", "*"))
            if imgs:
                image_path = imgs[0]

        if not image_path or not os.path.exists(image_path):
            logger.error("Batch Error: No valid image provided or found.")
            return

        output_dir = out if out else os.path.join(os.getcwd(), "output")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        vid_exts = ["*.mp4", "*.mov", "*.mkv", "*.avi", "*.webm"]
        for ext in vid_exts:
            for v in glob.glob(os.path.join(video_dir, ext)):
                name = os.path.splitext(os.path.basename(v))[0]
                o = os.path.join(output_dir, f"{name}_branded.mp4")
                tasks.append((v, image_path, o))

    # 2. SINGLE FILE
    elif video and os.path.isfile(video) and image:
        if not out:
            base = os.path.splitext(os.path.basename(video))[0]
            out = os.path.join("output", f"{base}_branded.mp4")
            os.makedirs("output", exist_ok=True)
        tasks.append((video, image, out))

    # 3. DEFAULT BATCH
    else:
        logger.info(
            "No arguments provided. Using default ./videos and ./images folders."
        )
        video_dir = "videos"
        image_dir = "images"
        output_dir = "output"

        if not os.path.exists(video_dir) or not os.path.exists(image_dir):
            logger.error("Default folders not found.")
            return

        # Find Image
        img_files = glob.glob(os.path.join(image_dir, "*"))
        img_files = [
            f
            for f in img_files
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ]
        if not img_files:
            logger.error("No images found.")
            return
        selected_image = img_files[0]

        # Find Videos
        vid_files = []
        for ext in ["*.mp4", "*.mov", "*.mkv", "*.avi"]:
            vid_files.extend(glob.glob(os.path.join(video_dir, ext)))

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        for v in vid_files:
            name = os.path.splitext(os.path.basename(v))[0]
            o = os.path.join(output_dir, f"{name}_branded.mp4")
            tasks.append((v, selected_image, o))

    # --- EXECUTION LOOP ---
    if not tasks:
        logger.warning("No videos found to process.")
        return

    logger.info(f"Starting queue: {len(tasks)} videos.")

    for vid_path, img_path, out_path in tasks:
        try:
            # Metrics: Add duration
            dur = get_vid_duration(vid_path)
            total_video_duration_processed += dur

            process_single_video(
                vid_path,
                img_path,
                out_path,
                position,
                scale,
                margin,
                start_percent,
                duration_sec,
                fade_in,
                fade_out,
                mode,
                overwrite,
                threads,
            )
            videos_processed_count += 1
        except Exception as e:
            logger.error(f"Failed to process {os.path.basename(vid_path)}: {e}")

    # --- FINAL METRICS LOGGING ---
    process_end_time = time.time()
    execution_time_seconds = process_end_time - process_start_time

    # Format times to HH:MM:SS
    exec_time_str = str(timedelta(seconds=int(execution_time_seconds)))
    video_time_str = str(timedelta(seconds=int(total_video_duration_processed)))

    print("-" * 40)
    print("PROCESSING SUMMARY")
    print("-" * 40)
    print(f"Total Videos Processed: {videos_processed_count}")
    print(f"Total Video Content:    {video_time_str} (HH:MM:SS)")
    print(f"Total Execution Time:   {exec_time_str} (HH:MM:SS)")
    print("-" * 40)


if __name__ == "__main__":
    main()
