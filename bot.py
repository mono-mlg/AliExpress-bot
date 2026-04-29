import os, json, time, hmac, hashlib, requests
from datetime import datetime
from pathlib import Path

APP_KEY        = os.environ["ALI_APP_KEY"]
APP_SECRET     = os.environ["ALI_APP_SECRET"]
TRACKING_ID    = os.environ["ALI_TRACKING_ID"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT_ID"]
HISTORIAL_FILE = "historial.json"
MAX_POSTS      = 3
MIN_DESCUENTO  = 10
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

def _sign(params, secret):
    sorted_params = sorted(params.items())
    base = secret + "".join(k + str(v) for k, v in sorted_params) + secret
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest().upper()

def ali_request(method, extra):
    params = {"method": method, "app_key": APP_KEY, "timestamp": str(int(time.time() * 1000)), "sign_method": "sha256", "format": "json", "v": "2.0"}
    params.update(extra)
    params["sign"] = _sign(params, APP_SECRET)
    r = requests.post(ALI_API_URL, data=params, timeout=20)
    r.raise_for_status()
    return r.json()

def buscar_ofertas():
    print(">>> Llamando a la API de AliExpress...")
    data = ali_request("aliexpress.affiliate.hotproduct.query", {
        "tracking_id": TRACKING_ID, "page_no": "1", "page_size": "10",
        "sort": "LAST_VOLUME_DESC",
        "fields": "product_id,product_title,product_main_image_url,sale_price,original_price,discount,promotion_link",
    })
    print(">>> RESPUESTA API:")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
    try:
        productos = data["aliexpress_affiliate_hotproduct_query_response"]["resp_result"]["result"]["products"]["product"]
        print(">>> " + str(len(productos)) + " productos recibidos")
    except (KeyError, TypeError) as e:
        print(">>> ERROR al leer productos: " + str(e))
        return []
    ofertas = []
    for p in productos:
        try:
            precio_orig = float(str(p.get("original_price", "0")).replace(",", "."))
            precio_sale = float(str(p.get("sale_price", "0")).replace(",", "."))
            if precio_orig <= 0 or precio_sale <= 0:
                print("  SKIP precio 0: " + p.get("product_title", "")[:40])
                continue
            descuento = round((1 - precio_sale / precio_orig) * 100)
            print("  " + p.get("product_title", "")[:40] + " | orig:" + str(precio_orig) + " sale:" + str(precio_sale) + " dto:" + str(descuento) + "%")
            if descuento < MIN_DESCUENTO:
                print("     FILTRADO dto < " + str(MIN_DESCUENTO) + "%")
                continue
            ofertas.append({"id": str(p["product_id"]), "titulo": p["product_title"][:80], "imagen": p["product_main_image_url"], "precio_orig": precio_orig, "precio_sale": precio_sale, "descuento": descuento, "link": p["promotion_link"]})
        except Exception as e:
            print("  ERROR: " + str(e))
    print(">>> " + str(len(ofertas)) + " productos pasan el filtro")
    return ofertas

def cargar_historial():
    if Path(HISTORIAL_FILE).exists():
        with open(HISTORIAL_FILE) as f:
            return set(json.load(f))
    return set()

def guardar_historial(ids):
    with open(HISTORIAL_FILE, "w") as f:
        json.dump(list(ids)[-500:], f)

def formatear_mensaje(p):
    linea_cupon = ""
    precio_final = p["precio_sale"]
    if CUPON_FIJO:
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon = "\n🏷️ *DESCUENTO EXTRA*\n✂️ Cupón: `" + CUPON_FIJO + "`\n🔥💵 Precio FINAL con cupón: *" + str(precio_final) + "€*\n"
    msg = "🔥 ‼️*BAJADA DE PRECIO*‼️ #Aliexpress\n\n"
    msg += "🌟 " + p["titulo"] + "\n\n"
    msg += "❌ ~~PVP: " + str(p["precio_orig"]) + "€~~\n"
    msg += "✅ *Oferta: " + str(p["precio_sale"]) + "€*  (-" + str(p["descuento"]) + "%)\n"
    msg += linea_cupon + "\n"
    msg += "🌍 [COMPRAR AQUÍ](" + p["link"] + ")\n\n"
    msg += "_Síguenos para más ofertas diarias_ 🛒"
    return msg

def enviar_telegram(p):
    texto = formatear_mensaje(p)
    print(">>> Enviando: " + p["titulo"][:50])
    r = requests.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
        json={"chat_id": TELEGRAM_CHAT, "photo": p["imagen"], "caption": texto, "parse_mode": "Markdown"}, timeout=15)
    print("    Telegram: " + str(r.status_code) + " " + r.text[:200])

def main():
    print("=== Bot iniciado " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")
    historial = cargar_historial()
    print(">>> Historial: " + str(len(historial)) + " productos")
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
