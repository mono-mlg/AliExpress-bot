import os, json, time, hashlib, re, requests, io
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
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"
COLA_FILE      = "cola.txt"
LOGO_FILE      = "logo.png"
CANAL_NOMBRE   = "@MultiChollos"
MAX_POSTS      = 3

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
#  TIPO DE CAMBIO CNY -> EUR
# ─────────────────────────────────────────
def obtener_tipo_cambio():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/CNY", timeout=10)
        tasa = r.json()["rates"]["EUR"]
        print(">>> Tipo de cambio CNY->EUR: " + str(round(tasa, 5)))
        return tasa
    except:
        return 0.128

# ─────────────────────────────────────────
#  EXTRAER PRODUCT ID DE LA URL
# ─────────────────────────────────────────
def extraer_product_id(url):
    """Funciona con URLs directas y acortadas de AliExpress."""
    # Si es URL acortada (s.click.aliexpress.com), seguir redirección
    if "s.click.aliexpress.com" in url or "aliexpress.com/e/" in url:
        try:
            r = requests.get(url, allow_redirects=True, timeout=15,
                           headers={"User-Agent": "Mozilla/5.0"})
            url = r.url
            print("    URL resuelta: " + url[:80])
        except Exception as e:
            print("    Error resolviendo URL: " + str(e))
            return None

    # Extraer ID del patrón /item/XXXXXXXXX.html o /i/XXXXXXXXX.html
    patrones = [
        r"/item/(\d+)\.html",
        r"/i/(\d+)\.html",
        r"productId=(\d+)",
        r"/(\d{10,20})\.html",
    ]
    for patron in patrones:
        m = re.search(patron, url)
        if m:
            return m.group(1)

    print("    No se pudo extraer el ID del producto de: " + url[:80])
    return None

# ─────────────────────────────────────────
#  OBTENER DATOS DEL PRODUCTO VIA API
# ─────────────────────────────────────────
def obtener_producto(product_id, tasa_cambio):
    """Consulta la API de afiliados con el ID del producto."""
    try:
        data = ali_request("aliexpress.affiliate.productdetail.get", {
            "tracking_id":  TRACKING_ID,
            "product_ids":  product_id,
            "fields":       "product_id,product_title,product_main_image_url,sale_price,original_price,discount,promotion_link",
            "ship_to_country": "ES",
        })
        print("    Respuesta API: " + json.dumps(data, ensure_ascii=False)[:200])
        p = (data["aliexpress_affiliate_productdetail_get_response"]
                 ["resp_result"]["result"]["products"]["product"][0])

        precio_orig = round(float(str(p.get("original_price", "0")).replace(",", ".")) * tasa_cambio, 2)
        precio_sale = round(float(str(p.get("sale_price", "0")).replace(",", ".")) * tasa_cambio, 2)
        descuento = round((1 - precio_sale / precio_orig) * 100) if precio_orig > 0 else 0

        return {
            "id":          str(p["product_id"]),
            "titulo":      p["product_title"][:80],
            "imagen":      p["product_main_image_url"],
            "precio_orig": precio_orig,
            "precio_sale": precio_sale,
            "descuento":   descuento,
            "link_orig":   p.get("promotion_link", ""),
        }
    except Exception as e:
        print("    Error obteniendo producto: " + str(e))
        return None

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
        return (data["aliexpress_affiliate_link_generate_response"]
                    ["resp_result"]["result"]["promotion_links"]["promotion_link"][0]
                    ["promotion_link"])
    except Exception as e:
        print("    Advertencia enlace: " + str(e))
        return url_original

# ─────────────────────────────────────────
#  TRADUCCION
# ─────────────────────────────────────────
def traducir_es(texto):
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
    except:
        return texto

def generar_descripcion(titulo_es, precio_sale, descuento):
    if descuento >= 60:
        frase = "Oferta increible con mas del " + str(descuento) + "% de descuento."
    elif descuento >= 40:
        frase = "Gran descuento del " + str(descuento) + "% en este producto."
    elif descuento > 0:
        frase = "Ahorra un " + str(descuento) + "% con esta oferta."
    else:
        frase = "Precio especial disponible por tiempo limitado."
    return titulo_es + " " + frase + " Por solo ~" + str(precio_sale) + "€, no dejes escapar esta oportunidad."

# ─────────────────────────────────────────
#  MARCA DE AGUA
# ─────────────────────────────────────────
def aplicar_marca_agua(url_imagen):
    try:
        r = requests.get(url_imagen, timeout=15)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        ancho, alto = img.size
        margen = int(ancho * 0.03)

        # Logo — esquina superior derecha
        tam_logo = int(ancho * 0.18)
        if Path(LOGO_FILE).exists():
            logo = Image.open(LOGO_FILE).convert("RGBA")
            logo = logo.resize((tam_logo, tam_logo), Image.LANCZOS)
            r_ch, g_ch, b_ch, a_ch = logo.split()
            a_ch = a_ch.point(lambda x: int(x * 0.85))
            logo.putalpha(a_ch)
            img.paste(logo, (ancho - tam_logo - margen, margen), logo)

        # Texto — esquina inferior derecha
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
#  LEER Y ACTUALIZAR COLA
# ─────────────────────────────────────────
def leer_cola():
    if not Path(COLA_FILE).exists():
        return []
    with open(COLA_FILE) as f:
        lineas = [l.strip() for l in f.readlines() if l.strip() and not l.startswith("#")]
    return lineas

def guardar_cola(lineas):
    with open(COLA_FILE, "w") as f:
        f.write("\n".join(lineas) + ("\n" if lineas else ""))

# ─────────────────────────────────────────
#  FORMATEAR MENSAJE
# ─────────────────────────────────────────
def formatear_mensaje(p, link, descripcion_es):
    linea_cupon = ""
    if CUPON_FIJO:
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA*\n"
        linea_cupon += "✂️ Cupon: `" + CUPON_FIJO + "`\n"
        linea_cupon += "🔥💵 Precio FINAL con cupon: *~" + str(precio_final) + "€*\n"

    msg = "🔥 ‼️*BAJADA DE PRECIO*‼️ #Aliexpress\n\n"
    msg += "📦 " + descripcion_es + "\n\n"
    if p["descuento"] > 0:
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
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT, "caption": texto, "parse_mode": "Markdown"},
            files={"photo": ("producto.jpg", imagen_con_marca, "image/jpeg")},
            timeout=30
        )
    else:
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
    print("=== Bot Cola iniciado " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")

    cola = leer_cola()
    print(">>> " + str(len(cola)) + " URLs en la cola")

    if not cola:
        print(">>> Cola vacia, nada que publicar")
        return

    tasa_cambio = obtener_tipo_cambio()
    publicados = 0
    cola_restante = list(cola)

    for url in cola:
        if publicados >= MAX_POSTS:
            break

        print(">>> Procesando: " + url[:70])
        cola_restante.pop(0)  # Eliminar de la cola aunque falle

        product_id = extraer_product_id(url)
        if not product_id:
            print("    Saltando — no se pudo extraer ID")
            continue

        print("    Product ID: " + product_id)
        producto = obtener_producto(product_id, tasa_cambio)

        if not producto:
            print("    Saltando — no se pudieron obtener datos del producto")
            continue

        # Generar link de afiliado
        link = generar_link_afiliado(url if producto["link_orig"] == "" else producto["link_orig"])
        print("    Link afiliado: " + link[:70])

        # Traducir y generar descripcion
        titulo_es = traducir_es(producto["titulo"])
        descripcion_es = generar_descripcion(titulo_es, producto["precio_sale"], producto["descuento"])

        enviar_telegram(producto, link, descripcion_es)
        publicados += 1
        time.sleep(2)

    guardar_cola(cola_restante)
    print(">>> Cola actualizada: " + str(len(cola_restante)) + " URLs restantes")
    print("=== Fin: " + str(publicados) + " publicados ===")

if __name__ == "__main__":
    main()
