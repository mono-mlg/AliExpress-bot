import os
import json
import time
import hmac
import hashlib
import requests
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────
#  CONFIGURACIÓN (se leen desde variables de entorno de GitHub)
# ─────────────────────────────────────────
APP_KEY        = os.environ["ALI_APP_KEY"]
APP_SECRET     = os.environ["ALI_APP_SECRET"]
TRACKING_ID    = os.environ["ALI_TRACKING_ID"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["TELEGRAM_CHAT_ID"]   # ID del canal, ej: @tucanal o -100xxxxxxxx

HISTORIAL_FILE = "historial.json"   # productos ya publicados (guardado en el repo)
MAX_POSTS      = 3                  # cuántos productos publicar por ejecución
MIN_DESCUENTO  = 30                 # % mínimo de descuento real para considerar oferta
CUPON_FIJO     = os.environ.get("CUPON_FIJO", "")  # ej: "MES03" — déjalo vacío si no tienes

# ─────────────────────────────────────────
#  FIRMA ALIEXPRESS API
# ─────────────────────────────────────────
ALI_API_URL = "https://api-sg.aliexpress.com/sync"

def _sign(params: dict, secret: str) -> str:
    sorted_params = sorted(params.items())
    base = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest().upper()

def ali_request(method: str, extra: dict) -> dict:
    params = {
        "method":         method,
        "app_key":        APP_KEY,
        "timestamp":      str(int(time.time() * 1000)),
        "sign_method":    "sha256",
        "format":         "json",
        "v":              "2.0",
    }
    params.update(extra)
    params["sign"] = _sign(params, APP_SECRET)
    r = requests.post(ALI_API_URL, data=params, timeout=20)
    r.raise_for_status()
    return r.json()

# ─────────────────────────────────────────
#  BUSCAR OFERTAS HOT
# ─────────────────────────────────────────
def buscar_ofertas() -> list[dict]:
    """Llama a la API de afiliados y devuelve lista de productos en oferta."""
    data = ali_request("aliexpress.affiliate.hotproduct.query", {
        "tracking_id":      TRACKING_ID,
        "page_no":          "1",
        "page_size":        "50",
        "sort":             "LAST_VOLUME_DESC",
        "fields":           "product_id,product_title,product_main_image_url,"
                            "sale_price,original_price,discount,promotion_link,"
                            "evaluate_rate,volume",
    })

    try:
        productos = (data["aliexpress_affiliate_hotproduct_query_response"]
                        ["resp_result"]["result"]["products"]["product"])
    except (KeyError, TypeError):
        print("⚠️  Sin productos en la respuesta:", json.dumps(data, indent=2))
        return []

    ofertas = []
    for p in productos:
        try:
            precio_orig = float(p.get("original_price", 0))
            precio_sale = float(p.get("sale_price", 0))
            if precio_orig <= 0 or precio_sale <= 0:
                continue
            descuento = round((1 - precio_sale / precio_orig) * 100)
            if descuento < MIN_DESCUENTO:
                continue
            ofertas.append({
                "id":          str(p["product_id"]),
                "titulo":      p["product_title"][:80],
                "imagen":      p["product_main_image_url"],
                "precio_orig": precio_orig,
                "precio_sale": precio_sale,
                "descuento":   descuento,
                "link":        p["promotion_link"],
            })
        except Exception as e:
            print(f"  ↳ error procesando producto: {e}")

    print(f"✅ {len(ofertas)} productos con ≥{MIN_DESCUENTO}% descuento encontrados")
    return ofertas

# ─────────────────────────────────────────
#  HISTORIAL (evitar repetir productos)
# ─────────────────────────────────────────
def cargar_historial() -> set:
    if Path(HISTORIAL_FILE).exists():
        with open(HISTORIAL_FILE) as f:
            return set(json.load(f))
    return set()

def guardar_historial(ids: set):
    # Mantener solo los últimos 500 para no crecer infinito
    lista = list(ids)[-500:]
    with open(HISTORIAL_FILE, "w") as f:
        json.dump(lista, f)

# ─────────────────────────────────────────
#  FORMATEAR MENSAJE TELEGRAM
# ─────────────────────────────────────────
def formatear_mensaje(p: dict) -> str:
    precio_final = p["precio_sale"]
    linea_cupon  = ""
    if CUPON_FIJO:
        # Estimamos un 5% adicional con cupón (ajusta si sabes el valor real)
        precio_final = round(p["precio_sale"] * 0.95, 2)
        linea_cupon  = (
            f"\n🏷️ *DESCUENTO EXTRA*\n"
            f"✂️ Cupón: `{CUPON_FIJO}`\n"
            f"🔥💵 Precio FINAL con cupón: *{precio_final:.2f}€*\n"
        )

    msg = (
        f"🔥 ‼️*BAJADA DE PRECIO*‼️ #Aliexpress\n\n"
        f"🌟 {p['titulo']}\n\n"
        f"❌ ~~PVP: {p['precio_orig']:.2f}€~~\n"
        f"✅ *Oferta: {p['precio_sale']:.2f}€*  (-{p['descuento']}%)\n"
        f"{linea_cupon}\n"
        f"🌍 [COMPRAR AQUÍ]({p['link']})\n\n"
        f"_Síguenos para más ofertas diarias_ 🛒"
    )
    return msg

# ─────────────────────────────────────────
#  ENVIAR A TELEGRAM (foto + texto)
# ─────────────────────────────────────────
def enviar_telegram(p: dict):
    texto = formatear_mensaje(p)
    url   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id":    TELEGRAM_CHAT,
        "photo":      p["imagen"],
        "caption":    texto,
        "parse_mode": "Markdown",
    }
    r = requests.post(url, json=payload, timeout=15)
    if r.status_code != 200:
        print(f"  ↳ Error Telegram: {r.text}")
    else:
        print(f"  ↳ ✅ Publicado: {p['titulo'][:50]}")

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print(f"\n🤖 Bot iniciado — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    historial = cargar_historial()
    ofertas   = buscar_ofertas()

    # Filtra ya publicados
    nuevas = [o for o in ofertas if o["id"] not in historial]
    print(f"📦 {len(nuevas)} productos nuevos (no publicados antes)")

    publicados = 0
    for producto in nuevas:
        if publicados >= MAX_POSTS:
            break
        enviar_telegram(producto)
        historial.add(producto["id"])
        publicados += 1
        time.sleep(2)   # pausa cortés entre mensajes

    guardar_historial(historial)
    print(f"✅ Fin — {publicados} productos publicados\n")

if __name__ == "__main__":
    main()
