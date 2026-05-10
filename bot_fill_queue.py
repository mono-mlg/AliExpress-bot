import os, json, time, hashlib, re, random, base64, requests
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────
#  CONFIGURACION
# ─────────────────────────────────────────
APP_KEY        = os.environ["ALI_APP_KEY"]
APP_SECRET     = os.environ["ALI_APP_SECRET"]
TRACKING_ID    = os.environ["ALI_TRACKING_ID"]
GH_TOKEN       = os.environ["GH_TOKEN"]
GH_USER        = os.environ["GH_USER"]
GH_REPO        = os.environ["GH_REPO"]
HISTORIAL_FILE = "historial.json"
MAX_EN_COLA    = 30
MAX_INTENTOS   = 20   # ← subir de 8 a 20
MIN_DESCUENTO  = 30
MIN_PRECIO     = 5.0
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

GH_HEADERS = {
    "Authorization": "token " + GH_TOKEN,
    "Accept": "application/vnd.github.v3+json"
}

# ─────────────────────────────────────────
#  TIPO DE CAMBIO
# ─────────────────────────────────────────
def obtener_tipo_cambio():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/CNY", timeout=10)
        tasa = r.json()["rates"]["EUR"]
        print(">>> Tipo de cambio CNY->EUR: " + str(round(tasa, 5)))
        return tasa
    except Exception as e:
        print(">>> Usando 0.128 — " + str(e))
        return 0.128

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
#  GITHUB — COLA
# ─────────────────────────────────────────
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

defdef guardar_cola_github(lineas, sha):
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/cola.txt"
    header = "# Cola de publicacion MultiChollos\n# Un enlace por linea\n"
    contenido = header + "\n".join(lineas) + ("\n" if lineas else "")
    encoded = base64.b64encode(contenido.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "📋 Cola rellenada automaticamente " + datetime.now().strftime("%Y-%m-%d %H:%M"),
        "content": encoded,
    }
    if sha:  # solo añadir sha si el archivo ya existe
        payload["sha"] = sha
    r = requests.put(url, headers=GH_HEADERS, json=payload, timeout=15)
    if r.status_code not in (200, 201):
        print("    Error guardando cola: " + str(r.status_code) + " " + r.text[:200])
        return False
    return True

# ─────────────────────────────────────────
#  GITHUB — HISTORIAL
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
#  DEDUPLICACION
# ─────────────────────────────────────────
def normalizar_titulo(titulo):
    titulo = titulo.lower()
    titulo = re.sub(r"[^a-z0-9 ]", " ", titulo)
    palabras = [p for p in titulo.split() if len(p) > 2]
    return " ".join(palabras[:5])

# ─────────────────────────────────────────
#  BUSCAR OFERTAS (hotproduct API avanzada)
# ─────────────────────────────────────────
def buscar_ofertas(tasa_cambio, historial):
    print(">>> Buscando ofertas con API avanzada...")
    mejores = {}
    paginas_probadas = set()
    intentos = 0
    MAX_INTENTOS = 8

    while len(mejores) < MAX_EN_COLA and intentos < MAX_INTENTOS:
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
                "fields":          "product_id,product_title,product_main_image_url,sale_price,original_price,promotion_link",
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
                if clave in historial or clave in mejores:
                    continue
                link = p.get("promotion_link", "")
                if not link:
                    link = "https://www.aliexpress.com/item/" + str(p["product_id"]) + ".html"
                mejores[clave] = {
                    "clave": clave,
                    "link":  link,
                    "titulo": p.get("product_title", "")[:60],
                    "descuento": descuento,
                }
            except Exception as e:
                print("  ERROR: " + str(e))

        time.sleep(1)

    ofertas = list(mejores.values())
    ofertas.sort(key=lambda x: x["descuento"], reverse=True)
    print(">>> " + str(len(ofertas)) + " ofertas nuevas encontradas")
    return ofertas

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print("=== Bot Fill Queue iniciado " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")

    tasa_cambio = obtener_tipo_cambio()
    historial = cargar_historial()
    print(">>> Historial local: " + str(len(historial)) + " productos ya publicados")

    # Leer cola actual para no añadir duplicados
    cola_actual, sha_cola = leer_cola_github()
    urls_en_cola = set(cola_actual)
    print(">>> Cola actual: " + str(len(cola_actual)) + " productos pendientes")

    # Buscar ofertas nuevas
    ofertas = buscar_ofertas(tasa_cambio, historial)

    # Añadir a la cola solo las que no estén ya
    nuevas_urls = []
    nuevas_claves = []
    for o in ofertas:
        if o["link"] not in urls_en_cola:
            nuevas_urls.append(o["link"])
            nuevas_claves.append(o["clave"])
            print("    + " + o["titulo"] + " (-" + str(o["descuento"]) + "%)")

    if not nuevas_urls:
        print(">>> Nada nuevo que añadir a la cola")
        return

    # Actualizar cola en GitHub
    cola_actualizada = cola_actual + nuevas_urls
    if guardar_cola_github(cola_actualizada, sha_cola):
        print(">>> Cola actualizada: " + str(len(cola_actualizada)) + " productos en total (" + str(len(nuevas_urls)) + " nuevos)")
    else:
        print(">>> Error al guardar la cola")
        return

    # Actualizar historial local para que el siguiente workflow no repita
    for clave in nuevas_claves:
        historial.add(clave)
    guardar_historial(historial)
    print("=== Fin: " + str(len(nuevas_urls)) + " productos añadidos a la cola ===")

if __name__ == "__main__":
    main()
