"""
image_renderer.py - Renders Urdu text onto a background image using Pillow.

This module:
- Loads a background image (or creates a blank one)
- Overlays Urdu text with proper shaping and font
- Saves the final image to a temporary file for posting
"""

import os
import random
from PIL import Image, ImageDraw, ImageFont
from config.config import FONT_PATH, BACKGROUND_IMAGES


# ----------------------------------------------------------------------
# 1. Render text onto a background image
# ----------------------------------------------------------------------
def render_poetry_to_image(poem_text: str, output_path: str = None) -> str:
    """
    Takes a poem (string) and renders it onto a background image.
    Saves the result and returns the file path.

    Args:
        poem_text (str): The Urdu poem to display.
        output_path (str, optional): Where to save the image.
            If not provided, saves to 'data/temp_poem.png'.

    Returns:
        str: Path to the saved image file.
    """
    if output_path is None:
        output_path = os.path.join("data", "temp_poem.png")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 1. Load a background image (randomly pick from available ones)
    bg_path = None
    if BACKGROUND_IMAGES:
        bg_path = random.choice(BACKGROUND_IMAGES)

    if bg_path and os.path.exists(bg_path):
        img = Image.open(bg_path)
    else:
        # Fallback: create a plain gradient background
        img = Image.new("RGB", (800, 600), color=(30, 30, 80))
        draw = ImageDraw.Draw(img)
        # Draw a simple gradient (optional)
        for i in range(600):
            r = int(30 + (i / 600) * 50)
            g = int(30 + (i / 600) * 40)
            b = int(80 + (i / 600) * 60)
            draw.line([(0, i), (800, i)], fill=(r, g, b))

    draw = ImageDraw.Draw(img)

    # 2. Load the Urdu font
    try:
        # Use a large font size, adjust as needed
        font = ImageFont.truetype(FONT_PATH, 45)
    except IOError:
        print(f"⚠️ Font not found at {FONT_PATH}. Using default font.")
        font = ImageFont.load_default()

    # 3. Wrap the text into lines (simple approach: split by newline)
    lines = poem_text.split("\n")
    # Remove empty lines
    lines = [line.strip() for line in lines if line.strip()]

    # 4. Calculate total height of text block
    line_spacing = 10
    total_height = sum(
        [draw.textbbox((0, 0), line, font=font)[3] + line_spacing for line in lines]
    )
    # Start y position (centered vertically)
    y_start = (img.height - total_height) // 2

    # 5. Draw each line centered horizontally
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (img.width - text_width) // 2
        y = y_start + i * (bbox[3] + line_spacing)
        # Add a subtle shadow for readability (optional)
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 240))

    # 6. Save the image
    img.save(output_path)
    print(f"✅ Image saved to {output_path}")
    return output_path


# ----------------------------------------------------------------------
# Test (when run directly)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    sample_poem = "دل کی بات\nسنو میرے دوست\nمحبت ہے زندگی"
    render_poetry_to_image(sample_poem, "test_output.png")
