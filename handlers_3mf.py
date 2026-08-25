import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
import math
import webcolors
import numpy as np
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.filters import Command
import logging

logger = logging.getLogger(__name__)

router = Router()

# ---------- Вспомогательные функции для работы с 3MF ----------

def parse_hex_color(hex_str: str):
    """
    Преобразует строку вида "#RRGGBB" или "#AARRGGBB" в кортеж (R, G, B).
    Альфа-канал игнорируется.
    """
    hex_str = hex_str.strip().upper()
    if hex_str.startswith('#'):
        hex_str = hex_str[1:]
    if len(hex_str) == 6:
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return (r, g, b)
    elif len(hex_str) == 8:  # с альфой
        r = int(hex_str[2:4], 16)
        g = int(hex_str[4:6], 16)
        b = int(hex_str[6:8], 16)
        return (r, g, b)
    else:
        return None

def extract_colors_from_3mf(file_bytes: bytes) -> list:
    """
    Извлекает все уникальные RGB-цвета (в виде кортежей (R,G,B)) из 3MF-файла.
    Поддерживает вершинные цвета (p:color) и цвета треугольников (color).
    """
    colors = set()
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            # Ищем файл .model (обычно 3D/3dmodel.model или просто .model)
            model_files = [f for f in zf.namelist() if f.endswith('.model')]
            if not model_files:
                return []  # Не найден model-файл

            # Берём первый попавшийся
            with zf.open(model_files[0]) as model_file:
                tree = ET.parse(model_file)
                root = tree.getroot()

                # Пространства имён, используемые в 3MF
                ns = {
                    'p': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
                    'm': 'http://schemas.microsoft.com/3dmanufacturing/material/2015/02'
                }

                # Регистрируем пространства для поиска
                for prefix, uri in ns.items():
                    ET.register_namespace(prefix, uri)

                # 1. Ищем цвета в объектах (тег <object> с атрибутом p:color)
                for obj in root.findall('.//p:object', ns):
                    color_attr = obj.get('{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}color')
                    if color_attr:
                        rgb = parse_hex_color(color_attr)
                        if rgb:
                            colors.add(rgb)

                # 2. Ищем цвета в вершинах (тег <vertex> с атрибутом p:color)
                for vertex in root.findall('.//p:vertex', ns):
                    color_attr = vertex.get('{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}color')
                    if color_attr:
                        rgb = parse_hex_color(color_attr)
                        if rgb:
                            colors.add(rgb)

                # 3. Ищем цвета в треугольниках (тег <triangle> с атрибутом color)
                for tri in root.findall('.//p:triangle', ns):
                    color_attr = tri.get('color')
                    if not color_attr:
                        color_attr = tri.get('{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}color')
                    if color_attr:
                        rgb = parse_hex_color(color_attr)
                        if rgb:
                            colors.add(rgb)

                # 4. Ищем цвета через материалы (тег <color> внутри <m:colors>)
                for color_elem in root.findall('.//m:color', ns):
                    color_val = color_elem.get('color')
                    if color_val:
                        rgb = parse_hex_color(color_val)
                        if rgb:
                            colors.add(rgb)

    except Exception as e:
        logger.error(f"Ошибка при парсинге 3MF: {e}")
        return []

    return list(colors)

def rgb_to_color_name(rgb: tuple, tolerance: int = 30) -> str:
    """
    Сопоставляет RGB-кортеж с названием цвета.
    Использует стандартные CSS-цвета (140 имён) через библиотеку webcolors.
    Если точного совпадения нет, ищет ближайший по евклидову расстоянию.
    """
    r, g, b = rgb
    try:
        # Попытка точного совпадения
        return webcolors.rgb_to_name((r, g, b))
    except ValueError:
        # Поиск ближайшего цвета (с допуском)
        min_dist = float('inf')
        closest_name = None
        for name, hex_val in webcolors.CSS3_NAMES_TO_HEX.items():
            cr = int(hex_val[1:3], 16)
            cg = int(hex_val[3:5], 16)
            cb = int(hex_val[5:7], 16)
            dist = math.sqrt((r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2)
            if dist < min_dist:
                min_dist = dist
                closest_name = name
        if min_dist <= tolerance:
            return closest_name
        else:
            # Если все далеко, возвращаем HEX
            return f"#{r:02X}{g:02X}{b:02X}"

def group_similar_colors(colors: list, tolerance: int = 30) -> list:
    """
    Группирует близкие цвета (по евклидову расстоянию) и возвращает усреднённые.
    """
    if not colors:
        return []

    arr = np.array(colors, dtype=np.float64)
    groups = []

    for color in arr:
        found = False
        for group in groups:
            centroid = np.mean(group, axis=0)
            if np.linalg.norm(color - centroid) <= tolerance:
                group.append(color)
                found = True
                break
        if not found:
            groups.append([color])

    averaged = []
    for group in groups:
        avg = np.mean(group, axis=0).astype(int)
        averaged.append(tuple(avg))

    return averaged

def generate_color_palette(colors: list) -> bytes:
    """
    Генерирует изображение с палитрой цветов и возвращает его в виде байтов.
    """
    from PIL import Image, ImageDraw

    if not colors:
        return None

    # Размеры: квадраты 60x60, отступ 10, 5 цветов в ряд
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

    # Сохраняем в байты
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()

# ---------- Обработчики команд ----------

@router.message(Command("analyze_3mf"))
async def cmd_analyze_3mf(message: Message):
    """Команда /analyze_3mf — инструкция по использованию."""
    await message.answer(
        "📐 *Анализ 3MF-файла*\n\n"
        "Просто отправьте мне файл с расширением `.3mf`, и я:\n"
        "• Извлеку все цвета из модели\n"
        "• Сгруппирую близкие оттенки\n"
        "• Назову каждый цвет\n"
        "• Покажу палитру\n\n"
        "Поддерживаются цвета вершин, граней и материалов.",
        parse_mode="Markdown"
    )

@router.message(F.document)
async def handle_3mf_file(message: Message):
    """Обработчик получения 3MF-файла."""
    doc = message.document

    # Проверяем расширение .3mf
    if not doc.file_name or not doc.file_name.lower().endswith('.3mf'):
        return  # пропускаем файлы, которые не являются 3MF

    # Отправляем сообщение о начале обработки
    processing_msg = await message.answer("⏳ Анализирую 3MF-файл...")

    try:
        # Скачиваем файл
        file = await message.bot.get_file(doc.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        file_data = file_bytes.read()

        # Извлекаем цвета
        raw_colors = extract_colors_from_3mf(file_data)

        if not raw_colors:
            await processing_msg.edit_text(
                "❌ Не удалось найти цвета в этом 3MF-файле.\n"
                "Проверьте, что файл содержит цветные данные."
            )
            return

        # Группируем близкие цвета
        grouped = group_similar_colors(raw_colors, tolerance=30)

        # Получаем названия
        color_list = []
        for rgb in grouped:
            name = rgb_to_color_name(rgb)
            if name.startswith('#'):
                color_list.append(f"• {name} (RGB {rgb[0]},{rgb[1]},{rgb[2]})")
            else:
                color_list.append(f"• {name.capitalize()} (RGB {rgb[0]},{rgb[1]},{rgb[2]})")

        # Формируем текстовый ответ
        if len(color_list) == 1:
            reply = "🎨 В файле найден один цвет:\n" + color_list[0]
        else:
            reply = "🎨 Найдены следующие цвета:\n" + "\n".join(color_list)

        # Генерируем палитру
        palette_img = generate_color_palette(grouped)

        if palette_img:
            # Отправляем изображение с палитрой и текстом
            await processing_msg.delete()
            await message.answer_photo(
                BufferedInputFile(palette_img, filename="palette.png"),
                caption=reply
            )
        else:
            # Если не удалось создать палитру, отправляем только текст
            await processing_msg.edit_text(reply)

    except Exception as e:
        logger.error(f"Ошибка обработки 3MF: {e}")
        await processing_msg.edit_text(
            f"❌ Произошла ошибка при обработке файла: {str(e)}"
        )
