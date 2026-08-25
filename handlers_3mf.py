@app.post("/api/analyze_3mf")
async def analyze_3mf_api(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.3mf'):
        raise HTTPException(status_code=400, detail="Файл должен иметь расширение .3mf")
    try:
        file_bytes = await file.read()
        raw_colors = extract_colors_from_3mf(file_bytes)
        if not raw_colors:
            raise HTTPException(status_code=400, detail="Не удалось найти цвета в файле")
        grouped = group_similar_colors(raw_colors, tolerance=30)
        result = []
        for rgb in grouped:
            hex_str = rgb_to_hex(rgb)
            matches = find_closest_colors(hex_str, BAMBU_COLORS, top_n=3)
            result.append({
                "input_hex": hex_str,
                "matches": [
                    {
                        "name": m[1]['name'],
                        "hex": m[1]['hex'],
                        "type": m[1]['type'],
                        "code": m[1]['code'],
                        "location": m[1]['location'],
                        "distance": round(m[0], 2)
                    }
                    for m in matches
                ]
            })
        palette_img = generate_color_palette(grouped)
        palette_base64 = None
        if palette_img:
            import base64
            palette_base64 = base64.b64encode(palette_img).decode('utf-8')
        return JSONResponse(content={
            "colors": result,
            "palette": palette_base64,
            "count": len(result)
        })
    except Exception as e:
        logger.error(f"Ошибка анализа 3MF: {e}")
        raise HTTPException(status_code=500, detail=str(e))
