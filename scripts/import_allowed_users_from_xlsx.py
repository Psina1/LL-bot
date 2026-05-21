from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.db.init_db import init_db
from app.db.repositories import AllowedUserRepository
from app.db.session import SessionLocal


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - 64)
    return index - 1


def read_first_sheet_rows(path: Path) -> list[list[str | None]]:
    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("a:si", NS):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", NS)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find("a:sheets/a:sheet", NS)
        if first_sheet is None:
            return []

        relationship_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target_by_id = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships}
        sheet_path = "xl/" + target_by_id[relationship_id].lstrip("/")

        worksheet = ET.fromstring(archive.read(sheet_path))
        rows: list[list[str | None]] = []
        for row in worksheet.findall("a:sheetData/a:row", NS):
            values_by_column: dict[int, str | None] = {}
            max_index = -1
            for cell in row.findall("a:c", NS):
                index = column_index(cell.attrib.get("r", "A1"))
                cell_type = cell.attrib.get("t")
                value_node = cell.find("a:v", NS)
                value = None if value_node is None else value_node.text
                if cell_type == "s" and value is not None:
                    value = shared_strings[int(value)]
                elif cell_type == "inlineStr":
                    value = "".join(text.text or "" for text in cell.findall(".//a:t", NS))
                value = value.strip() if isinstance(value, str) else value
                values_by_column[index] = value or None
                max_index = max(max_index, index)
            row_values = [values_by_column.get(index) for index in range(max_index + 1)]
            if any(row_values):
                rows.append(row_values)
        return rows


def parse_telegram_id(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if re.fullmatch(r"\d+(?:\.0+)?", value):
        return int(float(value))
    return None


def parse_username(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if value.startswith("@") and len(value) > 1:
        return value
    return None


async def import_allowed_users(path: Path) -> tuple[int, int, list[str]]:
    await init_db()
    rows = read_first_sheet_rows(path)
    imported = 0
    skipped: list[str] = []

    async with SessionLocal() as session:
        for row_number, row in enumerate(rows, start=1):
            full_name = row[0] if len(row) > 0 else None
            raw_username = row[1] if len(row) > 1 else None
            telegram_id = parse_telegram_id(row[2] if len(row) > 2 else None)
            phone = row[3] if len(row) > 3 else None
            username = parse_username(raw_username)

            if not full_name:
                skipped.append(f"row {row_number}: no full name")
                continue

            if telegram_id is None and username is None:
                note = f"no telegram id/username; raw second column: {raw_username or '-'}"
                skipped.append(f"row {row_number}: {full_name} ({note})")
                continue

            note = "imported from Excel allowlist"
            if raw_username and username is None:
                note += f"; raw second column: {raw_username}"

            await AllowedUserRepository.upsert(
                session=session,
                full_name=full_name,
                telegram_id=telegram_id,
                username=username,
                phone=phone,
                note=note,
                is_active=True,
            )
            imported += 1

    return len(rows), imported, skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import Telegram bot allowlist from XLSX.")
    parser.add_argument("xlsx_path", type=Path)
    args = parser.parse_args()

    total, imported, skipped = await import_allowed_users(args.xlsx_path)
    print(f"rows_total={total}")
    print(f"imported={imported}")
    print(f"skipped={len(skipped)}")
    for item in skipped:
        print(f"skipped: {item}")


if __name__ == "__main__":
    asyncio.run(main())
