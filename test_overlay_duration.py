import os
import shutil
import pytest

# Updated imports for v2.0
from moviepy import ColorClip, VideoFileClip
from add_product_placement import get_overlay_timing, mode_moviepy

OUTPUT_DIR = "test_output"


@pytest.fixture(scope="module")
def artifacts():
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)

    # Create input video
    video_path = os.path.join(OUTPUT_DIR, "input_red.mp4")
    # v2.0: ColorClip args changed slightly (color, duration, size)
    # But usually color=(R,G,B), size=(W,H), duration=D
    red = ColorClip(color=(255, 0, 0), size=(640, 360), duration=10.0)
    red.fps = 24
    red.write_videofile(video_path, verbose=False, logger=None)

    # Create input image
    image_path = os.path.join(OUTPUT_DIR, "overlay_blue.png")
    blue = ColorClip(color=(0, 0, 255), size=(100, 100), duration=1)
    # .save_frame works same way
    blue.save_frame(image_path, t=0)

    yield video_path, image_path


def test_integration_moviepy(artifacts):
    video_path, image_path = artifacts
    out_path = os.path.join(OUTPUT_DIR, "final_moviepy.mp4")

    # 75% of 10s = 7.5s start
    mode_moviepy(
        video_path=video_path,
        image_path=image_path,
        output_path=out_path,
        start_pct=0.75,
        duration_sec=2.0,
        position="center",
        scale=1.0,
        fade_in=0,
        fade_out=0,
        threads=2,
    )

    result = VideoFileClip(out_path)

    # 7.0s -> RED
    px_before = result.get_frame(7.0)[180, 320]
    assert px_before[0] > 200, "Should be red before overlay"

    # 8.0s -> BLUE
    px_during = result.get_frame(8.0)[180, 320]
    assert px_during[2] > 200, "Should be blue during overlay"

    result.close()
