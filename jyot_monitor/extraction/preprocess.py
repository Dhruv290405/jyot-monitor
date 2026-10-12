"""Image preprocessing for OCR enhancement."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


class ImagePreprocessor:
    """Preprocesses images for conventional OCR and visual model extraction."""

    PROFILES = ["none", "standard", "high_contrast", "binarize", "upscale", "crop_chrome"]

    def __init__(self, default_profile: str = "standard"):
        self.default_profile = default_profile

    def load_image(self, image_input: Union[str, Path, bytes, Image.Image]) -> Image.Image:
        """Load and normalize an image to PIL Image object."""
        if isinstance(image_input, Image.Image):
            return image_input.copy()
        if isinstance(image_input, (str, Path)):
            return Image.open(str(image_input)).convert("RGB")
        if isinstance(image_input, bytes):
            return Image.open(io.BytesIO(image_input)).convert("RGB")
        raise ValueError(f"Unsupported image input type: {type(image_input)}")

    def estimate_orientation(self, img: Image.Image) -> int:
        """Estimate orientation angle (0, 90, 180, 270) based on EXIF or image dimensions."""
        try:
            exif = img.getexif()
            if exif:
                orientation = exif.get(0x0112)
                if orientation == 3:
                    return 180
                elif orientation == 6:
                    return 270
                elif orientation == 8:
                    return 90
        except Exception:
            pass
        return 0

    def apply_profile(
        self,
        image_input: Union[str, Path, bytes, Image.Image],
        profile: Optional[str] = None,
    ) -> Image.Image:
        """Applies a preprocessing profile to the image."""
        img = self.load_image(image_input)
        profile_name = (profile or self.default_profile).lower()

        if profile_name == "none":
            return img

        # Auto-rotate based on EXIF orientation if present
        angle = self.estimate_orientation(img)
        if angle != 0:
            img = img.rotate(angle, expand=True)

        if profile_name == "standard":
            # Grayscale -> Contrast enhance -> Mild sharpen
            gray = ImageOps.grayscale(img)
            enhancer = ImageEnhance.Contrast(gray)
            enhanced = enhancer.enhance(1.4)
            sharpened = enhanced.filter(ImageFilter.SHARPEN)
            return sharpened

        elif profile_name == "high_contrast":
            gray = ImageOps.grayscale(img)
            enhancer = ImageEnhance.Contrast(gray)
            high_cont = enhancer.enhance(2.2)
            return high_cont

        elif profile_name == "binarize":
            # Grayscale -> Otsu/Threshold binarization
            gray = ImageOps.grayscale(img)
            # Threshold at middle intensity
            threshold = 128
            table = [0 if i < threshold else 255 for i in range(256)]
            binary = gray.point(table, "L")
            return binary

        elif profile_name == "upscale":
            # 2x bicubic upscale for low-res screenshots
            w, h = img.size
            upscaled = img.resize((w * 2, h * 2), Image.Resampling.BICUBIC)
            gray = ImageOps.grayscale(upscaled)
            return gray

        elif profile_name == "crop_chrome":
            # Crop top 5% and bottom 5% (typical mobile status bar / home bar)
            w, h = img.size
            if h > 200:
                top_crop = int(h * 0.05)
                bottom_crop = int(h * 0.95)
                cropped = img.crop((0, top_crop, w, bottom_crop))
                return ImageOps.grayscale(cropped)
            return ImageOps.grayscale(img)

        # Fallback to standard
        return ImageOps.grayscale(img)
