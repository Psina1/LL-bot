from __future__ import annotations

from dataclasses import dataclass
import hashlib
import posixpath
import re
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree


@dataclass(slots=True)
class OCRImage:
    slide_number: int | None
    name: str
    mime_type: str
    data: bytes
    width: int | None
    height: int | None
    sha256: str

    @property
    def label(self) -> str:
        if self.slide_number is None:
            return self.name
        return f"слайд {self.slide_number}: {self.name}"


IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
PPT_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
R_LINK = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}link"


def extract_pptx_images_for_ocr(
    file_path: Path,
    *,
    max_images: int,
    max_image_bytes: int,
    min_width: int,
    min_height: int,
) -> list[OCRImage]:
    """Extract large slide images from PPTX in slide order.

    Many corporate decks are exported as screenshots inside PPTX. python-pptx sees
    only a few editable text boxes, so this helper finds the actual slide images
    for vision OCR without requiring LibreOffice/Tesseract on the server.
    """
    images: list[OCRImage] = []
    seen_hashes: set[str] = set()

    with zipfile.ZipFile(file_path) as archive:
        names = set(archive.namelist())
        for slide_path in _slide_paths(names):
            relationships = _read_slide_relationships(archive, slide_path)
            for rel_id in _slide_image_rel_ids(archive, slide_path):
                target = relationships.get(rel_id)
                if not target:
                    continue

                image_path = _resolve_slide_target(slide_path, target)
                if image_path not in names:
                    continue

                suffix = Path(image_path).suffix.lower()
                mime_type = IMAGE_MIME_TYPES.get(suffix)
                if not mime_type:
                    continue

                info = archive.getinfo(image_path)
                if info.file_size > max_image_bytes:
                    continue

                data = archive.read(image_path)
                width, height = image_dimensions(data)
                if not _is_large_enough(width, height, min_width=min_width, min_height=min_height):
                    continue

                digest = hashlib.sha256(data).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)

                images.append(
                    OCRImage(
                        slide_number=_slide_number(slide_path),
                        name=image_path,
                        mime_type=mime_type,
                        data=data,
                        width=width,
                        height=height,
                        sha256=digest,
                    )
                )
                if len(images) >= max_images:
                    return images

    return images


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height

    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue

            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                break

            length = int.from_bytes(data[index : index + 2], "big")
            if length < 2 or index + length > len(data):
                break

            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height = int.from_bytes(data[index + 3 : index + 5], "big")
                width = int.from_bytes(data[index + 5 : index + 7], "big")
                return width, height

            index += length

    return None, None


def _slide_paths(names: set[str]) -> list[str]:
    slide_re = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
    slides = []
    for name in names:
        match = slide_re.match(name)
        if match:
            slides.append((int(match.group(1)), name))
    return [name for _, name in sorted(slides)]


def _slide_number(slide_path: str) -> int | None:
    match = re.search(r"slide(\d+)\.xml$", slide_path)
    return int(match.group(1)) if match else None


def _read_slide_relationships(archive: zipfile.ZipFile, slide_path: str) -> dict[str, str]:
    rels_path = f"{posixpath.dirname(slide_path)}/_rels/{posixpath.basename(slide_path)}.rels"
    if rels_path not in archive.namelist():
        return {}

    root = ElementTree.fromstring(archive.read(rels_path))
    relationships: dict[str, str] = {}
    for relationship in root.findall("rel:Relationship", REL_NS):
        rel_id = relationship.attrib.get("Id")
        target = relationship.attrib.get("Target")
        if rel_id and target:
            relationships[rel_id] = target
    return relationships


def _slide_image_rel_ids(archive: zipfile.ZipFile, slide_path: str) -> list[str]:
    root = ElementTree.fromstring(archive.read(slide_path))
    rel_ids: list[str] = []
    for blip in root.findall(".//a:blip", PPT_NS):
        rel_id = blip.attrib.get(R_EMBED) or blip.attrib.get(R_LINK)
        if rel_id:
            rel_ids.append(rel_id)
    return rel_ids


def _resolve_slide_target(slide_path: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(slide_path), target))


def _is_large_enough(
    width: int | None,
    height: int | None,
    *,
    min_width: int,
    min_height: int,
) -> bool:
    if width is None or height is None:
        return False
    return width >= min_width and height >= min_height
