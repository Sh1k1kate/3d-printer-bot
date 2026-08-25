import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
import math
import re
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
import logging

logger = logging.getLogger(__name__)

router = Router()

MAX_FILE_SIZE = 50 * 1024 * 1024

# ---------- База цветов Bambu Lab ----------
BAMBU_COLORS = [
    {"type":"PLA Basic","name":"Jade White",      "hex":"#FFFFFF","code":10001,"location":"PLA 01"},
    {"type":"PLA Basic","name":"Beige",           "hex":"#F7E6DE","code":10201,"location":"PLA 02"},
    {"type":"PLA Basic","name":"Light Grey",      "hex":"#D1D3D5","code":10104,"location":"PLA 03"},
    {"type":"PLA Basic","name":"Yellow",          "hex":"#F4EE2A","code":10400,"location":"PLA 04"},
    {"type":"PLA Basic","name":"Sunflower Yellow","hex":"#FEC600","code":10200,"location":"PLA 05"},
    {"type":"PLA Basic","name":"Gold",            "hex":"#E4BD68","code":10401,"location":"PLA 06"},
    {"type":"PLA Basic","name":"Pumpkin Orange",  "hex":"#FF9016","code":10301,"location":"PLA 07"},
    {"type":"PLA Basic","name":"Orange",          "hex":"#FF6A13","code":10300,"location":"PLA 08"},
    {"type":"PLA Basic","name":"Pink",            "hex":"#F55A74","code":10203,"location":"PLA 09"},
    {"type":"PLA Basic","name":"Hot Pink",        "hex":"#F5547C","code":10204,"location":"PLA 10"},
    {"type":"PLA Basic","name":"Magenta",         "hex":"#EC008C","code":10202,"location":"PLA 11"},
    {"type":"PLA Basic","name":"Red",             "hex":"#C12E1F","code":10200,"location":"PLA 12"},
    {"type":"PLA Basic","name":"Maroon Red",      "hex":"#9D2235","code":10205,"location":"PLA 13"},
    {"type":"PLA Basic","name":"Purple",          "hex":"#5E43B7","code":10700,"location":"PLA 14"},
    {"type":"PLA Basic","name":"Indigo Purple",   "hex":"#482960","code":10701,"location":"PLA 15"},
    {"type":"PLA Basic","name":"Bright Green",    "hex":"#BECF00","code":10503,"location":"PLA 16"},
    {"type":"PLA Basic","name":"Bambu Green",     "hex":"#00AE42","code":10501,"location":"PLA 17"},
    {"type":"PLA Basic","name":"Mistletoe Green", "hex":"#3F8E43","code":10502,"location":"PLA 18"},
    {"type":"PLA Basic","name":"Turquoise",       "hex":"#00B1B7","code":10605,"location":"PLA 19"},
    {"type":"PLA Basic","name":"Cyan",            "hex":"#0086D6","code":10603,"location":"PLA 20"},
    {"type":"PLA Basic","name":"Cobalt Blue",     "hex":"#0056B8","code":10604,"location":"PLA 21"},
    {"type":"PLA Basic","name":"Blue",            "hex":"#0A2989","code":10601,"location":"PLA 22"},
    {"type":"PLA Basic","name":"Brown",           "hex":"#9D432C","code":10800,"location":"PLA 23"},
    {"type":"PLA Basic","name":"Cocoa Brown",     "hex":"#6F5034","code":10802,"location":"PLA 24"},
    {"type":"PLA Basic","name":"Bronze",          "hex":"#847D48","code":10801,"location":"PLA 25"},
    {"type":"PLA Basic","name":"Grey",            "hex":"#8E9089","code":10103,"location":"PLA 26"},
    {"type":"PLA Basic","name":"Silver",          "hex":"#A6A9AA","code":10102,"location":"PLA 27"},
    {"type":"PLA Basic","name":"Blue Grey",       "hex":"#5B6579","code":10602,"location":"PLA 28"},
    {"type":"PLA Basic","name":"Dark Grey",       "hex":"#545454","code":10105,"location":"PLA 29"},
    {"type":"PLA Basic","name":"Black",           "hex":"#000000","code":10101,"location":"PLA 30"},
    {"type":"PLA Silk+",       "name":"Gold",     "hex":"#E4BD68","code":13405,"location":"PLA Silk 01"},
    {"type":"PLA Silk+",       "name":"White",    "hex":"#FFFFFF","code":13110,"location":"PLA Silk 02"},
    {"type":"PLA Matte",       "name":"Ivory White","hex":"#FFFFFF","code":11100,"location":"PLA Matte 04"},
    {"type":"PLA Matte",       "name":"Inland Wood Brown","hex":"#D2B48C","code":0,"location":"PLA Matte 02"},
    {"type":"PETG Translucent","name":"Inland Clear","hex":"#F0F2F5","code":0,"location":"PETG Translucent 01"}
]

# ---------- Улучшенные цветовые функции ----------
def hex_to_rgb(hex_str):
    hex_str = hex_str.strip().upper().replace('#', '')
    if len(hex_str) == 6:
        return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
    return (0, 0, 0)

def rgb_to_hex(rgb):
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

def rgb_to_lab(r, g, b):
    r /= 255.0
    g /= 255.0
    b /= 255.0
    r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r / 12.92
    g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g / 12.92
    b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b / 12.92
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    x *= 100
    y *= 100
    z *= 100
    xn, yn, zn = 95.047, 100.000, 108.883
    x /= xn
    y /= yn
    z /= zn
    fx = x ** (1/3) if x > 0.008856 else (7.787 * x + 16/116)
    fy = y ** (1/3) if y > 0.008856 else (7.787 * y + 16/116)
    fz = z ** (1/3) if z > 0.008856 else (7.787 * z + 16/116)
    l = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return (l, a, b)

def delta_e_2000(lab1, lab2):
    return math.sqrt((lab1[0]-lab2[0])**2 + (lab1[1]-lab2[1])**2 + (lab1[2]-lab2[2])**2)

def find_closest_colors(input_hex, colors, top_n=1):
    input_rgb = hex_to_rgb(input_hex)
    input_lab = rgb_to_lab(*input_rgb)
    distances = []
    for c in colors:
        target_rgb = hex_to_rgb(c['hex'])
        target_lab = rgb_to_lab(*target_rgb)
        dist = delta_e_2000(input_lab, target_lab)
        distances.append((dist, c))
    distances.sort(key=lambda x: x[0])
    return distances[:top_n]

# ---------- Парсер 3MF ----------
def extract_colors_from_3mf(file_bytes: bytes) -> list:
    colors = []
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            config_files = [f for f in zf.namelist() if f.lower().endswith('project_settings.config')]
            if config_files:
                with zf.open(config_files[0]) as cf:
                    content = cf.read().decode('utf-8', errors='ignore')
                    match = re.search(r'"filament_colour":\s*\[([\s\S]*?)\]', content)
                    if match:
                        hexes = re.findall(r'#[A-Fa-f0-9]{6}', match.group(1))
                        if hexes:
                            logger.info(f"[3MF] Найдено {len(hexes)} цветов в filament_colour")
                            return [h.upper() for h in set(hexes)]
                        hexes_no_hash = re.findall(r'\b([A-Fa-f0-9]{6})\b', match.group(1))
                        if hexes_no_hash:
                            logger.info(f"[3MF] Найдено {len(hexes_no_hash)} цветов без # в filament_colour")
                            return ['#' + h.upper() for h in set(hexes_no_hash)]
                    hexes_all = re.findall(r'#[A-Fa-f0-9]{6}', content)
                    if hexes_all:
                        logger.info(f"[3MF] Найдено {len(hexes_all)} цветов во всём config")
                        return [h.upper() for h in set(hexes_all)]
                    hexes_no_hash_all = re.findall(r'\b([A-Fa-f0-9]{6})\b', content)
                    if hexes_no_hash_all:
                        logger.info(f"[3MF] Найдено {len(hexes_no_hash_all)} цветов без # во всём config")
                        return ['#' + h.upper() for h in set(hexes_no_hash_all)]
            model_files = [f for f in zf.namelist() if f.endswith('.model')]
            for mf in model_files:
                with zf.open(mf) as f:
                    content = f.read().decode('utf-8', errors='ignore')
                    hexes = re.findall(r'#[A-Fa-f0-9]{6}', content)
                    if hexes:
                        colors.extend([h.upper() for h in set(hexes)])
                    hexes_no_hash = re.findall(r'\b([A-Fa-f0-9]{6})\b', content)
                    if hexes_no_hash:
                        colors.extend(['#' + h.upper() for h in set(hexes_no_hash)])
    except Exception as e:
        logger.error(f"Ошибка парсинга 3MF: {e}")
        return []
    unique = list(set(colors))
    logger.info(f"[3MF] Всего уникальных цветов: {len(unique)}")
    return unique

def group_similar_colors(colors_rgb, tolerance=20, max_colors=10):
    if not colors_rgb:
        return []
    colors_lab = [rgb_to_lab(r, g, b) for (r, g, b) in colors_rgb]
    groups = []
    for i, lab in enumerate(colors_lab):
        found = False
        for group in groups:
            avg_lab = tuple(sum(colors_lab[idx][k] for idx in group) / len(group) for k in range(3))
            if delta_e_2000(lab, avg_lab) < tolerance:
                group.append(i)
                found = True
                break
        if not found:
            groups.append([i])
    while len(groups) > max_colors:
        min_dist = float('inf')
        merge_pair = None
        for i in range(len(groups)):
            for j in range(i+1, len(groups)):
                lab_i = tuple(sum(colors_lab[idx][k] for idx in groups[i]) / len(groups[i]) for k in range(3))
                lab_j = tuple(sum(colors_lab[idx][k] for idx in groups[j]) / len(groups[j]) for k in range(3))
                dist = delta_e_2000(lab_i, lab_j)
                if dist < min_dist:
                    min_dist = dist
                    merge_pair = (i, j)
        if merge_pair is None:
            break
        i, j = merge_pair
        groups[i].extend(groups[j])
        del groups[j]
    result_rgb = []
    for group in groups:
        avg_r = int(sum(colors_rgb[idx][0] for idx in group) / len(group))
        avg_g = int(sum(colors_rgb[idx][1] for idx in group) / len(group))
        avg_b = int(sum(colors_rgb[idx][2] for idx in group) / len(group))
        result_rgb.append((avg_r, avg_g, avg_b))
    final_colors = []
    for rgb in result_rgb:
        r, g, b = rgb
        brightness = (r + g + b) / 3
        if brightness < 30:
            if (0,0,0) not in final_colors:
                final_colors.append((0,0,0))
            continue
        if brightness > 225:
            if (255,255,255) not in final_colors:
                final_colors.append((255,255,255))
            continue
        if abs(r - g) < 10 and abs(g - b) < 10 and abs(r - b) < 10:
            gray = int(brightness)
            if (gray, gray, gray) not in final_colors:
                final_colors.append((gray, gray, gray))
            continue
        final_colors.append(rgb)
    unique = []
    for c in final_colors:
        if c not in unique:
            unique.append(c)
    return unique

def generate_color_palette(colors):
    from PIL import Image, ImageDraw
    if not colors:
        return None
    square_size = 60
    padding = 10
    cols = min(5, len(colors))
    rows = (len(colors) + cols - 1) // cols
    width = cols * (square_size + padding) + padding
    height = rows * (square_size + padding) + padding
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    for i, rgb in enumerate(colors):
        col = i % cols
        row = i // cols
        x = padding + col * (square_size + padding)
        y = padding + row * (square_size + padding)
        draw.rectangle([x, y, x + square_size, y + square_size], fill=rgb)
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()

# ---------- Обработчики Telegram (с уникальными матчами) ----------
@router.message(Command("analyze_3mf"))
async def cmd_analyze_3mf(message: Message):
    await message.answer(
        "📐 *Анализ 3MF-файла*\n\n"
        "Просто отправьте мне файл с расширением `.3mf`, и я:\n"
        "• Извлеку все цвета из модели\n"
        "• Сгруппирую близкие оттенки\n"
        "• Подберу соответствующие цвета из базы Bambu Lab\n"
        "• Покажу палитру\n\n"
        "⚠️ Максимальный размер файла — 50 МБ.",
        parse_mode="Markdown"
    )

@router.message(F.document)
async def handle_3mf_file(message: Message):
    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith('.3mf'):
        return
    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        size_mb = doc.file_size // (1024 * 1024)
        await message.answer(
            f"❌ Файл слишком большой ({size_mb} МБ).\n"
            f"Максимальный размер для обработки — 50 МБ."
        )
        return
    processing_msg = await message.answer("⏳ Анализирую 3MF-файл...")
    try:
        file = await message.bot.get_file(doc.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        file_data = file_bytes.read()
        raw_colors_hex = extract_colors_from_3mf(file_data)
        if not raw_colors_hex:
            await processing_msg.edit_text(
                "❌ Не удалось найти цвета в этом 3MF-файле.\n"
                "Проверьте, что файл содержит цветные данные."
            )
            return
        raw_colors_rgb = [hex_to_rgb(h) for h in raw_colors_hex]
        grouped = group_similar_colors(raw_colors_rgb, tolerance=20, max_colors=10)
        # Подбираем уникальные цвета из базы
        unique_matches = []
        seen_hex = set()
        for rgb in grouped:
            hex_str = rgb_to_hex(rgb)
            matches = find_closest_colors(hex_str, BAMBU_COLORS, top_n=1)
            if matches:
                match = matches[0][1]
                if match['hex'] not in seen_hex:
                    seen_hex.add(match['hex'])
                    unique_matches.append(match)
        if not unique_matches:
            await processing_msg.edit_text("❌ Не удалось подобрать цвета из базы Bambu Lab.")
            return
        color_list = []
        for m in unique_matches:
            color_list.append(f"• {m['name']} ({m['hex']}) — {m['type']} [{m['location']}]")
        reply = "🎨 Найдены цвета в модели (из базы Bambu Lab):\n" + "\n".join(color_list)
        # Для палитры используем сгруппированные RGB (оригинальные цвета модели)
        palette_img = generate_color_palette(grouped)
        if palette_img:
            await processing_msg.delete()
            await message.answer_photo(
                BufferedInputFile(palette_img, filename="palette.png"),
                caption=reply
            )
        else:
            await processing_msg.edit_text(reply)
    except Exception as e:
        logger.error(f"Ошибка обработки 3MF: {e}")
        await processing_msg.edit_text(f"❌ Произошла ошибка: {str(e)}")
