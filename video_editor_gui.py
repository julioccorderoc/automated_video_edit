import gradio as gr
import os


def start_video_job(folder_path, image_path):
    """
    Core function stub.

    Args:
        folder_path (str): The absolute path string from the textbox.
        image_path (str): The temporary filepath of the uploaded image.
    """
    # 1. FAIL FAST: Validate folder
    if not folder_path:
        return "Error: Source Video Folder path is empty."

    # Sanitize path (remove quotes common when copying from Windows Explorer)
    folder_path = folder_path.strip().strip('"').strip("'")

    if not os.path.exists(folder_path):
        return f"Error: Path not found: '{folder_path}'"
    if not os.path.isdir(folder_path):
        return f"Error: Not a directory: '{folder_path}'"

    # 2. FAIL FAST: Validate image
    if not image_path:
        return "Error: No overlay image provided."

    # 3. MOCK LOGIC
    # In a real scenario, this is where you would iterate over files.
    video_extensions = (".mp4", ".mov", ".avi", ".mkv")
    video_files = [
        f for f in os.listdir(folder_path) if f.lower().endswith(video_extensions)
    ]

    return (
        f"✅ Job initiated successfully.\n"
        f"-----------------------------\n"
        f"📂 Source: {folder_path}\n"
        f"🎥 Videos Detected: {len(video_files)}\n"
        f"🖼️ Overlay: {os.path.basename(image_path)}\n"
        f"⚙️ Mode: Gradio 5.x Compatible"
    )


def build_interface():
    # GRADIO 5.0 STANDARDS:
    # 1. Use 'flagging_mode="never"' instead of 'allow_flagging'.
    # 2. Inputs defined clearly in the list.

    interface = gr.Interface(
        fn=start_video_job,
        inputs=[
            # Input 1: Zero-Copy Folder Selection (User pastes path)
            gr.Textbox(
                label="Source Video Folder",
                placeholder="Paste folder path here (e.g. C:\\Users\\Videos)",
                lines=1,
            ),
            # Input 2: Image Component (Better UX than generic File)
            # type="filepath" ensures we get a string path, not a numpy array.
            gr.Image(
                label="Overlay Image",
                type="filepath",
                sources=["upload", "clipboard"],
                height=300,
            ),
        ],
        outputs=gr.Textbox(label="Status Log", lines=6),
        title="Simple Video Processor",
        description="Paste the local folder path and upload an overlay image.",
        # UPDATED FOR GRADIO 5.0:
        flagging_mode="never",
    )
    return interface


if __name__ == "__main__":
    app = build_interface()
    # ssr_mode=False is often safer for local executables to prevent caching issues,
    # though optional.
    app.launch(inbrowser=True)
