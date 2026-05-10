import os, json, time, hashlib, re, requests, io, base64, schedule
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
GH_TOKEN       = os.environ["GH_TOKEN"]
GH_USER        = os.environ["GH_USER"]
GH_REPO        = os.environ["GH_REPO"]
INTERVALO_MIN  = int(os.environ.get("INTERVALO_MIN", "10"))
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")
LOGO_FILE      = "logo.png"
CANAL_NOMBRE   = "@MultiChollos"
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

tasa_cambio = 0.128

# ─────────────────────────────────────────
#  TIPO DE CAMBIO
# ─────────────────────────────────────────
def actualizar_tipo_cambio():
    global tasa_cambio
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/CNY", timeout=10)
        tasa_cambio = r.json()["rates"]["EUR"]
        print(">>> Tipo de cambio CNY->EUR: " + str(round(tasa_cambio, 5)))
    except:
        print(">>> Usando tipo de cambio de respaldo: " + str(tasa_cambio))

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
#  GITHUB — LEER Y ESCRIBIR COLA
# ─────────────────────────────────────────
GH_HEADERS = {
    "Authorization": "token " + GH_TOKEN,
    "Accept": "application/vnd.github.v3+json"
}

def leer_cola_github():
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/cola.txt"
    r = requests.get(url, headers=GH_HEADERS, timeout=15)
    if r.status_code == 404:
        return [], None
    data = r.json()
    contenido = base64.b64decode(data["content"]).decode("utf-8")
    sha = data["sha"]
    lineas = [l.strip() for l in contenido.split("\n") if l.strip() and not l.startswith("#")]
    return lineas, sha

def guardar_cola_github(lineas, sha):
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/cola.txt"
    header = "# Cola de publicacion MultiChollos\n# Un enlace por linea\n"
    contenido = header + "\n".join(lineas) + ("\n" if lineas else "")
    encoded = base64.b64encode(contenido.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "📋 Cola actualizada por Railway bot " + datetime.now().strftime("%H:%M"),
        "content": encoded,
        "sha": sha
    }
    r = requests.put(url, headers=GH_HEADERS, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        print("    Error guardando cola: " + str(r.status_code) + " " + r.text[:200])
        return False
    return True

# ─────────────────────────────────────────
#  EXTRAER PRODUCT ID
# ─────────────────────────────────────────
def extraer_product_id(url):
    if "s.click.aliexpress.com" in url or "aliexpress.com/e/" in url:
        try:
            r = requests.get(url, allow_redirects=True, timeout=15,
                           headers={"User-Agent": "Mozilla/5.0"})
            url = r.url
        except Exception as e:
            print("    Error resolviendo URL: " + str(e))
            return None
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
    return None

# ─────────────────────────────────────────
#  OBTENER DATOS DEL PRODUCTO
# ─────────────────────────────────────────
def obtener_producto(product_id):
    try:
        data = ali_request("aliexpress.affiliate.productdetail.get", {
            "tracking_id":     TRACKING_ID,
            "product_ids":     product_id,
            "ship_to_country": "ES",
            "fields":          "product_id,product_title,product_main_image_url,sale_price,original_price,promotion_link",
        })
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
#  GENERAR ENLACE AFILIADO
# ─────────────────────────────────────────
def generar_link_afiliado(url):
    try:
        data = ali_request("aliexpress.affiliate.link.generate", {
            "tracking_id":         TRACKING_ID,
            "promotion_link_type": "0",
            "source_values":       url,
        })
        return (data["aliexpress_affiliate_link_generate_response"]
                    ["resp_result"]["result"]["promotion_links"]["promotion_link"][0]
                    ["promotion_link"])
    except Exception as e:
        print("    Advertencia enlace: " + str(e))
        return url

# ─────────────────────────────────────────
#  CUPONES POR TRAMOS
# ─────────────────────────────────────────
def obtener_cupon(precio_sale):
    if not Path("cupones.json").exists():
        return None
    try:
        with open("cupones.json") as f:
            tramos = json.load(f)
        tramos.sort(key=lambda x: x["min"], reverse=True)
        for tramo in tramos:
            if precio_sale >= tramo["min"]:
                return tramo
        return None
    except:
        return None

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

        tam_logo = int(ancho * 0.18)
        if Path(LOGO_FILE).exists():
            logo = Image.open(LOGO_FILE).convert("RGBA")
            logo = logo.resize((tam_logo, tam_logo), Image.LANCZOS)
            r_ch, g_ch, b_ch, a_ch = logo.split()
            a_ch = a_ch.point(lambda x: int(x * 0.85))
            logo.putalpha(a_ch)
            img.paste(logo, (ancho - tam_logo - margen, margen), logo)

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
#  FORMATEAR MENSAJE
# ─────────────────────────────────────────
def formatear_mensaje(p, link, descripcion_es):
    cupon = obtener_cupon(p["precio_sale"])
    linea_cupon = ""
    if cupon:
        precio_final = round(p["precio_sale"] - cupon["descuento"], 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA CON CUPÓN*\n"
        linea_cupon += "✂️ Cupón: `" + cupon["cupon"] + "`\n"
        linea_cupon += "🔥💵 Precio FINAL con cupón: *~" + str(precio_final) + "€*\n"
    elif CUPON_FIJO:
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA*\n"
        linea_cupon += "✂️ Cupón: `" + CUPON_FIJO + "`\n"
        linea_cupon += "🔥💵 Precio FINAL con cupón: *~" + str(precio_final) + "€*\n"

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
#  CICLO PRINCIPAL
# ─────────────────────────────────────────
def publicar_siguiente():
    print("\n--- Ciclo " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ---")
    try:
        cola, sha = leer_cola_github()
        print(">>> " + str(len(cola)) + " URLs en la cola")

        if not cola:
            print(">>> Cola vacia, esperando...")
            return

        url = cola[0]
        print(">>> Procesando: " + url[:70])

        product_id = extraer_product_id(url)
        if not product_id:
            print("    Saltando — no se pudo extraer ID")
            cola.pop(0)
            guardar_cola_github(cola, sha)
            return

        producto = obtener_producto(product_id)
        if not producto:
            print("    Saltando — no se pudieron obtener datos")
            cola.pop(0)
            guardar_cola_github(cola, sha)
            return

        url_base = producto["link_orig"] if producto["link_orig"] else "https://www.aliexpress.com/item/" + producto["id"] + ".html"
        link = generar_link_afiliado(url_base)

        titulo_es = traducir_es(producto["titulo"])
        descripcion_es = generar_descripcion(titulo_es, producto["precio_sale"], producto["descuento"])

        enviar_telegram(producto, link, descripcion_es)

        cola.pop(0)
        if guardar_cola_github(cola, sha):
            print(">>> Cola actualizada: " + str(len(cola)) + " URLs restantes")

    except Exception as e:
        print(">>> Error en ciclo: " + str(e))

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("=== Railway Bot iniciado ===")
    print(">>> Intervalo: cada " + str(INTERVALO_MIN) + " minutos")

    actualizar_tipo_cambio()

    # Ejecutar inmediatamente al arrancar
    publicar_siguiente()

    # Programar ejecuciones exactas cada X minutos
    schedule.every(INTERVALO_MIN).minutes.do(publicar_siguiente)
    # Actualizar tipo de cambio cada 6 horas
    schedule.every(6).hours.do(actualizar_tipo_cambio)

    print(">>> Scheduler activo, esperando siguiente ciclo...")
    while True:
        schedule.run_pending()
        time.sleep(30)
