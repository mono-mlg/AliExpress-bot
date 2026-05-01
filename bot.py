import os, json, time, hashlib, re, requests
from datetime import datetime
from pathlib import Path

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
MIN_DESCUENTO  = 40
MIN_PRECIO     = 5.0
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

CATEGORIAS = [
    #"smartwatch", "hair dryer", "electronic", "telephone", "xiaomi", "huawei", "wireless earbuds", "led strip", "decoration", "air fryer", "home", "sport", "crossfit"
   "electronic", "home deco", "crossfit", "led", "camping", "armaf", "afnan", "lattafa", "redmi", "huawei"
]

# ─────────────────────────────────────────
#  TIPO DE CAMBIO CNY -> EUR EN TIEMPO REAL
# ─────────────────────────────────────────
def obtener_tipo_cambio_cny_eur():
    """Obtiene el tipo de cambio CNY->EUR desde una API gratuita sin clave."""
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/CNY", timeout=10)
        tasa = r.json()["rates"]["EUR"]
        print(">>> Tipo de cambio CNY->EUR: " + str(round(tasa, 5)))
        return tasa
    except Exception as e:
        print(">>> Advertencia tipo de cambio: " + str(e) + " — usando valor fijo 0.128")
        return 0.128  # valor de respaldo aproximado

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
#  GENERAR ENLACE DE AFILIADO CORTO
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
#  DEDUPLICACION POR TITULO NORMALIZADO
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
    mejores = {}  # clave_titulo -> producto
    por_keyword = {}  # keyword -> cuantos productos lleva

    for keyword in CATEGORIAS:
        print(">>> Buscando: " + keyword)
        por_keyword[keyword] = 0
        try:
            data = ali_request("aliexpress.affiliate.product.query", {
                "tracking_id":     TRACKING_ID,
                "keywords":        keyword,
                "page_no":         "1",
                "page_size":       "20",
                "sort":            "LAST_VOLUME_DESC",
                "ship_to_country": "ES",
                "fields":          "product_id,product_title,product_main_image_url,sale_price,original_price,discount,promotion_link",
            })
            prods = (data["aliexpress_affiliate_product_query_response"]
                        ["resp_result"]["result"]["products"]["product"])
            print("    " + str(len(prods)) + " productos encontrados")
        except (KeyError, TypeError) as e:
            print("    Sin resultados: " + str(e))
            time.sleep(1)
            continue

        # Ordenar por descuento descendente para quedarnos con los mejores
        prods_validos = []
        for p in prods:
            try:
                precio_orig = round(float(str(p.get("original_price", "0")).replace(",", ".")) * tasa_cambio, 2)
                precio_sale = round(float(str(p.get("sale_price", "0")).replace(",", ".")) * tasa_cambio, 2)
                if precio_orig < MIN_PRECIO or precio_sale <= 0:
                    continue
                descuento = round((1 - precio_sale / precio_orig) * 100)
                if descuento < MIN_DESCUENTO:
                    continue
                prods_validos.append((descuento, p, precio_orig, precio_sale))
            except Exception as e:
                print("  ERROR: " + str(e))

        prods_validos.sort(key=lambda x: x[0], reverse=True)

        for descuento, p, precio_orig, precio_sale in prods_validos:
            if por_keyword[keyword] >= 2:
                break
            clave = normalizar_titulo(p.get("product_title", ""))
            if clave in mejores:
                continue
            mejores[clave] = {
                "id":          clave,
                "product_id":  str(p["product_id"]),
                "titulo":      p["product_title"][:80],
                "imagen":      p["product_main_image_url"],
                "precio_orig": precio_orig,
                "precio_sale": precio_sale,
                "descuento":   descuento,
                "link_orig":   p["promotion_link"],
                "keyword":     keyword,
            }
            por_keyword[keyword] += 1
            print("    ✓ " + p.get("product_title","")[:45] + " (-" + str(descuento) + "%)")

        time.sleep(1)

    ofertas = list(mejores.values())
    ofertas.sort(key=lambda x: x["descuento"], reverse=True)
    print(">>> " + str(len(ofertas)) + " ofertas unicas (max 2 por keyword)")
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
#  FORMATEAR MENSAJE TELEGRAM
# ─────────────────────────────────────────
def formatear_mensaje(p, link):
    linea_cupon = ""
    precio_final = p["precio_sale"]
    if CUPON_FIJO:
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA*\n"
        linea_cupon += "✂️ Cupon: `" + CUPON_FIJO + "`\n"
        linea_cupon += "🔥💵 Precio FINAL con cupon: *~" + str(precio_final) + "€*\n"

    msg = "🔥 ‼️*BAJADA DE PRECIO*‼️ #Aliexpress\n\n"
    msg += "🌟 " + p["titulo"] + "\n\n"
    msg += "🏷️ Descuento: *-" + str(p["descuento"]) + "%*\n"
    msg += "💰 Precio oferta: *~" + str(p["precio_sale"]) + "€* _(puede ser menor al hacer clic)_\n"
    msg += linea_cupon + "\n"
    msg += "🌍 [VER PRECIO FINAL Y COMPRAR](" + link + ")\n\n"
    msg += "_Siguenos para mas ofertas diarias_ 🛒"
    return msg

# ─────────────────────────────────────────
#  ENVIAR A TELEGRAM
# ─────────────────────────────────────────
def enviar_telegram(p, link):
    texto = formatear_mensaje(p, link)
    print(">>> Enviando: " + p["titulo"][:50])
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
        print(">>> Generando enlace de afiliado para: " + p["titulo"][:40])
        link = generar_link_afiliado(p["link_orig"])
        print("    Link: " + link[:80])
        enviar_telegram(p, link)
        historial.add(p["id"])
        publicados += 1
        time.sleep(2)

    guardar_historial(historial)
    print("=== Fin: " + str(publicados) + " publicados ===")

if __name__ == "__main__":
    main()
