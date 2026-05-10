import os, json, time, hashlib, re, random, requests, io
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────
#  CONFIGURACION
# ─────────────────────────────────────────
APP_KEY        = os.environ["ALI_APP_KEY"]
APP_SECRET     = os.environ["ALI_APP_SECRET"]
TRACKING_ID    = os.environ["ALI_TRACKING_ID"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT_ID"]
HISTORIAL_FILE = "historial.json"
MAX_POSTS      = 10
MIN_DESCUENTO  = 15
MIN_PRECIO     = 5.0
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"
LOGO_FILE      = "logo.png"
CANAL_NOMBRE   = "@MultiChollos"

CATEGORIAS = [
    "electronic", "home deco", "fitness", "led lighting", "camping gear",
    "perfume", "smartphone accessories", "kitchen gadgets", "fashion",
    "beauty", "toys", "pet supplies", "tools", "garden", "sports"
]

# ─────────────────────────────────────────
#  TIPO DE CAMBIO CNY -> EUR
# ─────────────────────────────────────────
def obtener_tipo_cambio_cny_eur():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/CNY", timeout=10)
        tasa = r.json()["rates"]["EUR"]
        print(">>> Tipo de cambio CNY->EUR: " + str(round(tasa, 5)))
        return 1 #tasa
    except Exception as e:
        print(">>> Advertencia tipo de cambio: " + str(e) + " — usando 0.128")
        return 1 #0.128

# ─────────────────────────────────────────
#  FIRMA MD5
# ─────────────────────────────────────────
def _sign(params, secret):
    sorted_params = sorted(params.items())
    base = secret + "".join(k + str(v) for k, v in sorted_params) + secret
    return hashlib.md5(base.encode("utf-8")).hexdigest().upper()

def ali_request(method, extra):
    params = {
        "method":      method,
        "app_key":     APP_KEY,
        "timestamp":   str(int(time.time() * 1000)),
        "sign_method": "md5",
        "format":      "json",
        "v":           "2.0",
    }
    params.update(extra)
    params["sign"] = _sign(params, APP_SECRET)
    r = requests.post(ALI_API_URL, data=params, timeout=20)
    r.raise_for_status()
    return r.json()

# ─────────────────────────────────────────
#  GENERAR ENLACE DE AFILIADO
# ─────────────────────────────────────────
def generar_link_afiliado(url_original):
    try:
        data = ali_request("aliexpress.affiliate.link.generate", {
            "tracking_id":         TRACKING_ID,
            "promotion_link_type": "0",
            "source_values":       url_original,
        })
        link = (data["aliexpress_affiliate_link_generate_response"]
                    ["resp_result"]["result"]["promotion_links"]["promotion_link"][0]
                    ["promotion_link"])
        return link
    except Exception as e:
        print("    Advertencia enlace: " + str(e))
        return url_original

# ─────────────────────────────────────────
#  MARCA DE AGUA
# ─────────────────────────────────────────
def aplicar_marca_agua(url_imagen):
    """Logo en esquina superior derecha, texto del canal en esquina inferior derecha."""
    try:
        r = requests.get(url_imagen, timeout=15)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        ancho, alto = img.size
        margen = int(ancho * 0.03)

        # ── LOGO — esquina superior derecha ──
        tam_logo = int(ancho * 0.18)
        if Path(LOGO_FILE).exists():
            logo = Image.open(LOGO_FILE).convert("RGBA")
            logo = logo.resize((tam_logo, tam_logo), Image.LANCZOS)
            r_ch, g_ch, b_ch, a_ch = logo.split()
            a_ch = a_ch.point(lambda x: int(x * 0.85))
            logo.putalpha(a_ch)
            img.paste(logo, (ancho - tam_logo - margen, margen), logo)
        else:
            print("    Advertencia: logo.png no encontrado")

        # ── TEXTO — esquina inferior derecha ──
        draw = ImageDraw.Draw(img)
        tam_fuente = max(int(ancho * 0.048), 14)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", tam_fuente)
        except:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), CANAL_NOMBRE, font=font)
        txt_ancho = bbox[2] - bbox[0]
        txt_alto  = bbox[3] - bbox[1]

        pad = 6
        pos_txt_x = ancho - txt_ancho - margen
        pos_txt_y = alto - txt_alto - margen

        # Fondo semitransparente detrás del texto
        fondo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        fondo_draw = ImageDraw.Draw(fondo)
        fondo_draw.rounded_rectangle(
            [pos_txt_x - pad, pos_txt_y - pad, pos_txt_x + txt_ancho + pad, pos_txt_y + txt_alto + pad],
            radius=6, fill=(0, 0, 0, 160)
        )
        img = Image.alpha_composite(img, fondo)
        draw = ImageDraw.Draw(img)
        draw.text((pos_txt_x, pos_txt_y), CANAL_NOMBRE, font=font, fill=(255, 220, 0, 255))

        img_final = img.convert("RGB")
        buffer = io.BytesIO()
        img_final.save(buffer, format="JPEG", quality=88)
        buffer.seek(0)
        return buffer

    except Exception as e:
        print("    Advertencia marca de agua: " + str(e))
        return None


# ─────────────────────────────────────────
#  TRADUCCION AL ESPAÑOL
# ─────────────────────────────────────────
def traducir_es(texto):
    """Traduce texto al español usando MyMemory API (gratuita, sin clave)."""
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": texto[:500], "langpair": "en|es"},
            timeout=8
        )
        resultado = r.json()
        traducido = resultado["responseData"]["translatedText"]
        if resultado["responseData"]["match"] < 0.3:
            return texto
        return traducido
    except Exception as e:
        print("    Advertencia traduccion: " + str(e))
        return texto

def generar_descripcion(titulo_es, precio_sale, descuento):
    if descuento >= 60:
        frase = "Oferta increible con mas del " + str(descuento) + "% de descuento."
    elif descuento >= 40:
        frase = "Gran descuento del " + str(descuento) + "% en este producto."
    else:
        frase = "Ahorra un " + str(descuento) + "% con esta oferta."
    return titulo_es + " " + frase + " Por solo ~" + str(precio_sale) + "€, no dejes escapar esta oportunidad."

# ─────────────────────────────────────────
#  DEDUPLICACION
# ─────────────────────────────────────────
def normalizar_titulo(titulo):
    titulo = titulo.lower()
    titulo = re.sub(r"[^a-z0-9 ]", " ", titulo)
    palabras = [p for p in titulo.split() if len(p) > 2]
    return " ".join(palabras[:5])

# ─────────────────────────────────────────
#  BUSCAR OFERTAS
# ─────────────────────────────────────────
def buscar_ofertas(tasa_cambio):
    print(">>> Consultando API avanzada hotproduct...")
    mejores = {}
    paginas_probadas = set()
    intentos = 0
    MAX_INTENTOS = 8  # maximo de paginas a consultar

    while len(mejores) < 5 and intentos < MAX_INTENTOS:
        # Elegir pagina aleatoria no repetida
        pagina = random.randint(1, 20)
        while pagina in paginas_probadas:
            pagina = random.randint(1, 20)
        paginas_probadas.add(pagina)
        intentos += 1

        print(">>> Pagina " + str(pagina) + " (intento " + str(intentos) + ", encontrados: " + str(len(mejores)) + ")")
        try:
            data = ali_request("aliexpress.affiliate.hotproduct.query", {
                "tracking_id":     TRACKING_ID,
                "page_no":         str(pagina),
                "page_size":       "50",
                "sort":            "LAST_VOLUME_DESC",
                "ship_to_country": "ES",
                "fields":          "product_id,product_title,product_main_image_url,sale_price,original_price,discount,promotion_link",
            })
            productos_raw = (data["aliexpress_affiliate_hotproduct_query_response"]
                                ["resp_result"]["result"]["products"]["product"])
            print("    " + str(len(productos_raw)) + " productos en esta pagina")
        except (KeyError, TypeError) as e:
            print("    Error: " + str(e))
            time.sleep(1)
            continue

        for p in productos_raw:
            try:
                precio_orig = round(float(str(p.get("original_price", "0")).replace(",", ".")) * tasa_cambio, 2)
                precio_sale = round(float(str(p.get("sale_price", "0")).replace(",", ".")) * tasa_cambio, 2)
                if precio_orig < MIN_PRECIO or precio_sale <= 0:
                    continue
                descuento = round((1 - precio_sale / precio_orig) * 100)
                if descuento < MIN_DESCUENTO:
                    continue
                clave = normalizar_titulo(p.get("product_title", ""))
                if clave not in mejores or descuento > mejores[clave]["descuento"]:
                    mejores[clave] = {
                        "id":          clave,
                        "product_id":  str(p["product_id"]),
                        "titulo":      p["product_title"][:80],
                        "imagen":      p["product_main_image_url"],
                        "precio_orig": precio_orig,
                        "precio_sale": precio_sale,
                        "descuento":   descuento,
                        "link_orig":   p.get("promotion_link", ""),
                        "keyword":     "hotproduct",
                    }
            except Exception as e:
                print("  ERROR: " + str(e))

        time.sleep(1)

    ofertas = list(mejores.values())
    ofertas.sort(key=lambda x: x["descuento"], reverse=True)
    print(">>> " + str(len(ofertas)) + " ofertas unicas tras " + str(intentos) + " paginas consultadas")
    return ofertas
# ─────────────────────────────────────────
#  HISTORIAL
# ─────────────────────────────────────────
def cargar_historial():
    if Path(HISTORIAL_FILE).exists():
        with open(HISTORIAL_FILE) as f:
            return set(json.load(f))
    return set()

def guardar_historial(ids):
    with open(HISTORIAL_FILE, "w") as f:
        json.dump(list(ids)[-500:], f)
# ─────────────────────────────────────────
#  OBTENER CUPÓN 
# ─────────────────────────────────────────

def obtener_cupon(precio_sale):
    """Selecciona el cupón correcto según el precio de oferta."""
    if not Path("cupones.json").exists():
        return None
    try:
        with open("cupones.json") as f:
            tramos = json.load(f)
        # Ordenar de mayor a menor para coger el mejor cupón posible
        tramos.sort(key=lambda x: x["min"], reverse=True)
        for tramo in tramos:
            if precio_sale >= tramo["min"]:
                return tramo
        return None
    except Exception as e:
        print("    Advertencia cupones: " + str(e))
        return None



# ─────────────────────────────────────────
#  FORMATEAR MENSAJE
# ─────────────────────────────────────────
def formatear_mensaje(p, link, descripcion_es):
    linea_cupon = ""
    precio_final = p["precio_sale"]
    if CUPON_FIJO:
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA*\n"
        linea_cupon += "✂️ Cupon: `" + CUPON_FIJO + "`\n"
        linea_cupon += "🔥💵 Precio FINAL con cupon: *~" + str(precio_final) + "€*\n"

    msg = "🔥 ‼️*BAJADA DE PRECIO*‼️ #Aliexpress\n\n"
    msg += "📦 " + descripcion_es + "\n\n"
    msg += "🏷️ Descuento: *-" + str(p["descuento"]) + "%*\n"
    msg += "💰 Precio oferta: *~" + str(p["precio_sale"]) + "€* _(puede ser menor al hacer clic)_\n"
    msg += linea_cupon + "\n"
    msg += "🌍 [VER PRECIO FINAL Y COMPRAR](" + link + ")\n\n"
    msg += "_Siguenos para mas ofertas diarias_ 🛒"
    return msg

# ─────────────────────────────────────────
#  ENVIAR A TELEGRAM
# ─────────────────────────────────────────
def enviar_telegram(p, link, descripcion_es):
    texto = formatear_mensaje(p, link, descripcion_es)
    print(">>> Enviando: " + p["titulo"][:50])

    imagen_con_marca = aplicar_marca_agua(p["imagen"])

    if imagen_con_marca:
        # Enviar imagen procesada como archivo
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT, "caption": texto, "parse_mode": "Markdown"},
            files={"photo": ("producto.jpg", imagen_con_marca, "image/jpeg")},
            timeout=30
        )
    else:
        # Fallback: enviar URL original si falla el procesamiento
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
            json={"chat_id": TELEGRAM_CHAT, "photo": p["imagen"], "caption": texto, "parse_mode": "Markdown"},
            timeout=15
        )

    print("    Telegram: " + str(r.status_code))
    if r.status_code != 200:
        print("    Error: " + r.text[:200])

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print("=== Bot iniciado " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")

    tasa_cambio = obtener_tipo_cambio_cny_eur()

    historial = cargar_historial()
    print(">>> Historial: " + str(len(historial)) + " productos ya publicados")

    ofertas = buscar_ofertas(tasa_cambio)
    nuevas = [o for o in ofertas if o["id"] not in historial]
    print(">>> " + str(len(nuevas)) + " ofertas nuevas disponibles")

    publicados = 0
    for p in nuevas:
        if publicados >= MAX_POSTS:
            break
        print(">>> Traduciendo titulo: " + p["titulo"][:40])
        titulo_es = traducir_es(p["titulo"])
        descripcion_es = generar_descripcion(titulo_es, p["precio_sale"], p["descuento"])
        print(">>> Generando enlace de afiliado para: " + p["titulo"][:40])
        link = generar_link_afiliado(p["link_orig"])
        print("    Link: " + link[:80])
        enviar_telegram(p, link, descripcion_es)
        historial.add(p["id"])
        publicados += 1
        time.sleep(2)

    guardar_historial(historial)
    print("=== Fin: " + str(publicados) + " publicados ===")

if __name__ == "__main__":
    main()
