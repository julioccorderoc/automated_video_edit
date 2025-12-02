"""
add_product_placement.py

OBJECTIVE:
    Overlays an image (e.g., a logo or product) onto a video at a specific moment.
    By default, the image appears at 75% of the video's timeline and stays for 5 seconds.

DEPENDENCIES:
    1. Python 3.9+
    2. FFmpeg installed on your system path.
    3. Python libraries: pip install "moviepy>=2.0.0" click

USAGE EXAMPLES:

    1. Simple Run (Defaults to 75% start time, center screen):
       python add_product_placement.py --video input.mp4 --image logo.png --out final.mp4

    2. Custom Timing (Start at 50%, last 3 seconds, top-left corner):
       python add_product_placement.py --video input.mp4 --image logo.png --out final.mp4 \
       --start-percent 50 --duration 3 --position top-left

    3. Advanced (Scale image down by half, overwrite existing output, use FFmpeg engine):
       python add_product_placement.py --video input.mp4 --image logo.png --out final.mp4 \
       --scale 0.5 --overwrite --mode ffmpeg
"""

import os
import sys
import subprocess
import logging
import click
from typing import Union, Tuple

# ---------------------------------------------------------------------------
# Setup Logging
# This replaces simple 'print' statements with a professional logging setup.
# INFO shows general progress, WARNING shows potential issues, ERROR shows failures.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import MoviePy
# We use a try-block to give a friendly error if the library is missing.
# ---------------------------------------------------------------------------
try:
    from moviepy import VideoFileClip, ImageClip, CompositeVideoClip, vfx
except ImportError:
    logger.error("MoviePy v2.0+ is not installed.")
    logger.error('Please run: pip install "moviepy>=2.0.0" click')
    sys.exit(1)


def get_overlay_timing(
    video_duration: float, start_pct: float, target_duration: float
) -> Tuple[float, float]:
    """
    Calculates exactly when the image should appear and for how long.

    Args:
        video_duration: Total length of the video in seconds.
        start_pct: The percentage (0.0 to 1.0) when the overlay starts.
        target_duration: How long the overlay *wants* to stay on screen.

    Returns:
        (start_time, actual_duration)
        We verify that the overlay doesn't try to play past the end of the video.
    """
    start_time = video_duration * start_pct

    # Edge Case: If the calculation says start at 105s but video is only 100s.
    if start_time >= video_duration:
        return start_time, 0.0

    # Calculate time remaining from start point to end of video
    remaining = video_duration - start_time

    # The image lasts for the target duration OR the remaining time, whichever is smaller.
    actual_duration = min(target_duration, remaining)

    return start_time, actual_duration


def mode_moviepy(
    video_path: str,
    image_path: str,
    output_path: str,
    start_pct: float,
    duration_sec: float,
    position: Union[str, Tuple[float, float]],
    scale: float,
    fade_in: float,
    fade_out: float,
    threads: int,
):
    """
    ENGINE A: MoviePy (Python Native)
    Good for: Complex positioning, transparencies, and debugging logic.
    """
    try:
        # Load the video file into memory objects
        video = VideoFileClip(video_path)
    except Exception as e:
        raise RuntimeError(f"Could not load video {video_path}: {e}")

    logger.info(f"Video loaded. Duration: {video.duration:.2f} seconds")

    # Sanity check for corrupt video headers
    if video.duration == 0:
        logger.critical("Video duration detected as 0. Processing will likely fail.")

    # Calculate timing
    start_t, dur_t = get_overlay_timing(video.duration, start_pct, duration_sec)
    logger.info(f"Overlay scheduled: Start at {start_t:.2f}s, Duration {dur_t:.2f}s")

    # If duration is 0, it means the video is too short for the requested start time
    if dur_t <= 0:
        logger.warning(
            f"Start time {start_t:.2f}s is after video ends. Saving original video without overlay."
        )
        if video.audio:
            video.write_videofile(
                output_path, codec="libx264", audio_codec="aac", logger=None
            )
        else:
            video.write_videofile(output_path, codec="libx264", logger=None)
        return

    # Load and Prepare the Image
    img = ImageClip(image_path)

    # 1. Resize Image (if scale is not 1.0)
    # We use .with_effects for v2.0+ compatibility
    if scale != 1.0:
        img = img.with_effects([vfx.Resize(scale)])

    # 2. Set Timing & Position
    # .with_start tells it when to appear in the timeline
    # .with_position tells it where to be (e.g., 'center', 'top-left')
    img = img.with_start(start_t).with_duration(dur_t).with_position(position)

    # 3. Add Fades (Optional visual polish)
    effects = []
    if fade_in > 0:
        effects.append(vfx.CrossFadeIn(fade_in))
    if fade_out > 0:
        effects.append(vfx.CrossFadeOut(fade_out))

    if effects:
        img = img.with_effects(effects)

    # 4. Composite (Layering)
    # This stacks the [video, image] on top of each other.
    # use_bgclip=True ensures the output is exactly the length/size of the 'video'
    final = CompositeVideoClip([video, img], use_bgclip=True)

    # 5. Audio Handling
    # Critical Step: Ensure the original video audio is copied to the new file.
    if video.audio:
        final = final.with_audio(video.audio)
    else:
        logger.warning("No audio track detected in source video.")

    # 6. Render and Save
    logger.info(f"Rendering to {output_path}...")
    final.write_videofile(
        output_path,
        codec="libx264",  # Standard web video codec
        audio_codec="aac",  # Standard audio codec
        threads=threads,  # Parallel processing
        preset="fast",  # Compression speed vs size trade-off
        logger="bar"
        if sys.stdout.isatty()
        else None,  # Show progress bar if in terminal
    )

    # Cleanup resources (Explicitly close files to release memory)
    video.close()
    img.close()
    final.close()


def mode_ffmpeg_cli(
    video_path: str,
    image_path: str,
    output_path: str,
    start_pct: float,
    duration_sec: float,
    position: str,
    scale: float,
    overwrite: bool,
):
    """
    ENGINE B: Direct FFmpeg (System Command)
    Good for: Speed, large files, and preserving audio perfectly (no re-encoding audio).
    """
    # 1. Get Duration using ffprobe (a tool that comes with ffmpeg)
    cmd_probe = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        probe_out = subprocess.check_output(cmd_probe).decode("utf-8").strip()
        total_duration = float(probe_out)
        logger.info(f"FFprobe detected duration: {total_duration:.2f}s")
    except Exception as e:
        raise RuntimeError(f"FFprobe failed to read video: {e}")

    # Calculate timing
    start_t, dur_t = get_overlay_timing(total_duration, start_pct, duration_sec)
    end_t = start_t + dur_t

    if dur_t <= 0:
        logger.warning("Overlay falls outside video duration. copying original.")
        subprocess.run(["ffmpeg", "-i", video_path, output_path])
        return

    # Map text positions to FFmpeg coordinate math
    pos_map = {
        "center": "x=(W-w)/2:y=(H-h)/2",
        "top-left": "x=0:y=0",
        "top-right": "x=W-w:y=0",
        "bottom-left": "x=0:y=H-h",
        "bottom-right": "x=W-w:y=H-h",
    }
    overlay_xy = pos_map.get(position, position)

    # Build the 'Complex Filter'
    # 1. [1:v]scale... resizes the image
    # 2. overlay=... places it on the video only 'between' specific timestamps
    filter_complex = (
        f"[1:v]scale=iw*{scale}:-1[ovr];"
        f"[0:v][ovr]overlay={overlay_xy}:enable='between(t,{start_t:.3f},{end_t:.3f})'"
    )

    cmd_ffmpeg = [
        "ffmpeg",
        "-i",
        video_path,
        "-i",
        image_path,
        "-filter_complex",
        filter_complex,
        "-c:a",
        "copy",  # Copy audio stream directly (No quality loss)
        "-c:v",
        "libx264",  # Re-encode video
        "-preset",
        "fast",
        "-y" if overwrite else "-n",  # Overwrite flag
        output_path,
    ]

    logger.info(f"Executing FFmpeg command: {' '.join(cmd_ffmpeg)}")
    subprocess.run(cmd_ffmpeg, check=True)


@click.command()
@click.option(
    "--video", required=True, type=click.Path(exists=True), help="Path to input video."
)
@click.option(
    "--image",
    required=True,
    type=click.Path(exists=True),
    help="Path to image to overlay.",
)
@click.option("--out", required=True, help="Path for the output file.")
@click.option("--position", default="center", help="'center', 'top-left', or '100,200'")
@click.option("--scale", default=1.0, help="Resize image (0.5 = 50% size).")
@click.option(
    "--start-percent", default=75.0, help="Start at this % of video (Default: 75)."
)
@click.option(
    "--duration", "duration_sec", default=5.0, help="How long image stays visible."
)
@click.option("--fade-in", default=0.0, help="Fade-in duration in seconds.")
@click.option("--fade-out", default=0.0, help="Fade-out duration in seconds.")
@click.option(
    "--mode",
    type=click.Choice(["moviepy", "ffmpeg"]),
    default="moviepy",
    help="Rendering engine.",
)
@click.option("--overwrite", is_flag=True, help="Overwrite output file if it exists.")
@click.option("--threads", default=4, help="CPU threads to use.")
def main(
    video,
    image,
    out,
    position,
    scale,
    start_percent,
    duration_sec,
    fade_in,
    fade_out,
    mode,
    overwrite,
    threads,
):
    # Check if output exists
    if not overwrite and os.path.exists(out):
        logger.error(
            f"Output file '{out}' already exists. Use --overwrite to replace it."
        )
        sys.exit(1)

    # ---------------------------------------------------------
    # Input Normalization (Handling 75 vs 0.75)
    # ---------------------------------------------------------
    # If user inputs "75", we assume they mean 75% (0.75).
    # If user inputs "0.75", we assume they mean 75% (0.75).
    # If user inputs "1.0", that is 100%.
    final_pct = start_percent
    if start_percent > 1.0:
        final_pct = start_percent / 100.0

    # Safety clamp
    if final_pct < 0 or final_pct > 1.0:
        logger.error(
            f"Start percentage must be between 0 and 100. Got: {start_percent}"
        )
        sys.exit(1)

    logger.info(f"Processing started using mode: {mode.upper()}")
    logger.info(f"Overlay set to start at {final_pct * 100:.1f}% of video.")

    if mode == "moviepy":
        # Handle Coordinate parsing (e.g., "100,200" string to tuple)
        pos_arg = position
        if "," in position:
            try:
                x, y = map(str.strip, position.split(","))
                # Remove decimals if they are clean integers
                x = float(x) if x.replace(".", "", 1).isdigit() else x
                y = float(y) if y.replace(".", "", 1).isdigit() else y
                pos_arg = (x, y)
            except ValueError:
                pass  # Keep as string if parsing fails

        mode_moviepy(
            video,
            image,
            out,
            final_pct,  # Pass the normalized 0.0-1.0 float
            duration_sec,
            pos_arg,
            scale,
            fade_in,
            fade_out,
            threads,
        )

    elif mode == "ffmpeg":
        mode_ffmpeg_cli(
            video, image, out, final_pct, duration_sec, position, scale, overwrite
        )

    logger.info("Processing complete.")


if __name__ == "__main__":
    main()
