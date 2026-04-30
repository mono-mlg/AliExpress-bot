import os, json, time, hashlib, requests
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
MAX_POSTS      = 3
MIN_DESCUENTO  = 30
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

# ─────────────────────────────────────────
#  FIRMA MD5 (metodo oficial AliExpress)
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
#  BUSCAR OFERTAS
# ─────────────────────────────────────────
#def buscar_ofertas():
#    print(">>> Llamando a la API de AliExpress...")
#    data = ali_request("aliexpress.affiliate.hotproduct.query", {
#        "tracking_id": TRACKING_ID,
#        "page_no":     "1",
#        "page_size":   "50",
#        "sort":        "LAST_VOLUME_DESC",
#        "fields":      "product_id,product_title,product_main_image_url,sale_price,original_price,discount,promotion_link",
#    })
#    print(">>> RESPUESTA API: " + json.dumps(data, ensure_ascii=False)[:500])
#
#    try:
#        productos = data["aliexpress_affiliate_hotproduct_query_response"]["resp_result"]["result"]["products"]["product"]
#        print(">>> " + str(len(productos)) + " productos recibidos de la API")
#    except (KeyError, TypeError) as e:
#        print(">>> ERROR al leer productos: " + str(e))
#        return []
#
#    ofertas = []
#    for p in productos:
#        try:
#            precio_orig = float(str(p.get("original_price", "0")).replace(",", "."))
#            precio_sale = float(str(p.get("sale_price", "0")).replace(",", "."))
#            if precio_orig <= 0 or precio_sale <= 0:
#                continue
#            descuento = round((1 - precio_sale / precio_orig) * 100)
#            print("  " + p.get("product_title", "")[:50] + " | " + str(precio_orig) + " -> " + str(precio_sale) + " (-" + str(descuento) + "%)")
#            if descuento < MIN_DESCUENTO:
#                continue
#            ofertas.append({
#                "id":          str(p["product_id"]),
#                "titulo":      p["product_title"][:80],
 #               "imagen":      p["product_main_image_url"],
#                "precio_orig": precio_orig,
 #               "precio_sale": precio_sale,
#                "descuento":   descuento,
#                "link":        p["promotion_link"],
#            })
#        except Exception as e:
# #           print("  ERROR procesando producto: " + str(e))
#
#    print(">>> " + str(len(ofertas)) + " productos con descuento >= " + str(MIN_DESCUENTO) + "%")
#    return ofertas

def buscar_ofertas():
def buscar_ofertas():
    CATEGORIAS = ["phone", "laptop", "headphones", "smartwatch", "tablet"]
    productos_totales = []

    for keyword in CATEGORIAS:
        print(">>> Buscando: " + keyword)
        try:
            data = ali_request("aliexpress.affiliate.product.query", {
                "tracking_id": TRACKING_ID,
                "keywords":    keyword,
                "page_no":     "1",
                "page_size":   "20",
                "sort":        "SALE_PRICE_ASC",
                "fields":      "product_id,product_title,product_main_image_url,sale_price,original_price,discount,promotion_link",
            })
            print(">>> RESPUESTA: " + json.dumps(data, ensure_ascii=False)[:300])
            prods = data["aliexpress_affiliate_product_query_response"]["resp_result"]["result"]["products"]["product"]
            productos_totales.extend(prods)
            print("    " + str(len(prods)) + " productos encontrados")
        except (KeyError, TypeError) as e:
            print("    Sin resultados: " + str(e))
        time.sleep(1)

    ofertas = []
    vistos = set()
    for p in productos_totales:
        try:
            pid = str(p["product_id"])
            if pid in vistos:
                continue
            vistos.add(pid)
            precio_orig = float(str(p.get("original_price", "0")).replace(",", "."))
            precio_sale = float(str(p.get("sale_price", "0")).replace(",", "."))
            if precio_orig <= 0 or precio_sale <= 0:
                continue
            descuento = round((1 - precio_sale / precio_orig) * 100)
            print("  " + p.get("product_title", "")[:50] + " | " + str(precio_orig) + " -> " + str(precio_sale) + " (-" + str(descuento) + "%)")
            if descuento < MIN_DESCUENTO:
                continue
            ofertas.append({
                "id":          pid,
                "titulo":      p["product_title"][:80],
                "imagen":      p["product_main_image_url"],
                "precio_orig": precio_orig,
                "precio_sale": precio_sale,
                "descuento":   descuento,
                "link":        p["promotion_link"],
            })
        except Exception as e:
            print("  ERROR: " + str(e))

    print(">>> " + str(len(ofertas)) + " productos con descuento >= " + str(MIN_DESCUENTO) + "%")
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
def formatear_mensaje(p):
    linea_cupon = ""
    precio_final = p["precio_sale"]
    if CUPON_FIJO:
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA*\n"
        linea_cupon += "✂️ Cupon: `" + CUPON_FIJO + "`\n"
        linea_cupon += "🔥💵 Precio FINAL con cupon: *" + str(precio_final) + "*\n"

    msg = "🔥 ‼️*BAJADA DE PRECIO*‼️ #Aliexpress\n\n"
    msg += "🌟 " + p["titulo"] + "\n\n"
    msg += "❌ ~~PVP: " + str(p["precio_orig"]) + "~~\n"
    msg += "✅ *Oferta: " + str(p["precio_sale"]) + "*  (-" + str(p["descuento"]) + "%)\n"
    msg += linea_cupon + "\n"
    msg += "🌍 [COMPRAR AQUI](" + p["link"] + ")\n\n"
    msg += "_Siguenos para mas ofertas diarias_ 🛒"
    return msg

# ─────────────────────────────────────────
#  ENVIAR A TELEGRAM
# ─────────────────────────────────────────
def enviar_telegram(p):
    texto = formatear_mensaje(p)
    print(">>> Enviando a Telegram: " + p["titulo"][:50])
    r = requests.post(
        "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
        json={"chat_id": TELEGRAM_CHAT, "photo": p["imagen"], "caption": texto, "parse_mode": "Markdown"},
        timeout=15
    )
    print("    Respuesta Telegram: " + str(r.status_code) + " " + r.text[:300])

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print("=== Bot iniciado " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")
    historial = cargar_historial()
    print(">>> Historial: " + str(len(historial)) + " productos ya publicados")

    ofertas = buscar_ofertas()
    nuevas = [o for o in ofertas if o["id"] not in historial]
    print(">>> " + str(len(nuevas)) + " productos nuevos")

    publicados = 0
    for p in nuevas:
        if publicados >= MAX_POSTS:
            break
        enviar_telegram(p)
        historial.add(p["id"])
        publicados += 1
        time.sleep(2)

    guardar_historial(historial)
    print("=== Fin: " + str(publicados) + " publicados ===")

if __name__ == "__main__":
    main()
