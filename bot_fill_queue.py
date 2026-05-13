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
MIN_DESCUENTO  = 20
MIN_PRECIO     = 5.0
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

GH_HEADERS = {
    "Authorization": "token " + GH_TOKEN,
    "Accept": "application/vnd.github.v3+json"
}

# Categorias principales de AliExpress con sus IDs
# Obtenidos via aliexpress.affiliate.category.get
CATEGORIAS_IDS = [
    ("200000783", "Telefonia y accesorios"),
    ("200000828", "Electronica de consumo"),
    ("200003498", "Informatica"),
    ("200000572", "Hogar y jardin"),
    ("200000519", "Ropa hombre"),
    ("200000520", "Ropa mujer"),
    ("200001075", "Deportes y ocio"),
    ("200000797", "Belleza y salud"),
    ("200000336", "Juguetes y hobbies"),
    ("200000739", "Joyeria y relojes"),
    ("200000606", "Herramientas"),
    ("200000640", "Automovil y moto"),
]

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
    if not Path("cola.txt").exists():
        return [], None
    with open("cola.txt") as f:
        lineas = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    return lineas, "local"

def guardar_cola_github(lineas, sha):
    header = "# Cola de publicacion MultiChollos\n# Un enlace por linea\n"
    contenido = header + "\n".join(lineas) + ("\n" if lineas else "")
    with open("cola.txt", "w") as f:
        f.write(contenido)
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
#  PROCESAR PRODUCTOS RAW
# ─────────────────────────────────────────
def procesar_productos(productos_raw, tasa_cambio, historial, mejores):
    nuevos = 0
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
                "clave":     clave,
                "link":      link,
                "titulo":    p.get("product_title", "")[:60],
                "descuento": descuento,
            }
            nuevos += 1
        except Exception as e:
            print("  ERROR procesando producto: " + str(e))
    return nuevos

# ─────────────────────────────────────────
#  FUENTE 1: hotproduct.query (paginas aleatorias)
# ─────────────────────────────────────────
def buscar_hotproduct_query(tasa_cambio, historial, mejores):
    print(">>> [1/3] hotproduct.query — paginas aleatorias")
    paginas_probadas = set()
    intentos = 0
    MAX_INTENTOS = 10

    while len(mejores) < MAX_EN_COLA and intentos < MAX_INTENTOS:
        pagina = random.randint(1, 40)
        while pagina in paginas_probadas:
            pagina = random.randint(1, 40)
        paginas_probadas.add(pagina)
        intentos += 1

        try:
            data = ali_request("aliexpress.affiliate.hotproduct.query", {
                "tracking_id":     TRACKING_ID,
                "page_no":         str(pagina),
                "page_size":       "50",
                "sort":            "LAST_VOLUME_DESC",
                "ship_to_country": "ES",
                "fields":          "product_id,product_title,sale_price,original_price,promotion_link",
            })
            productos_raw = (data["aliexpress_affiliate_hotproduct_query_response"]
                                ["resp_result"]["result"]["products"]["product"])
            nuevos = procesar_productos(productos_raw, tasa_cambio, historial, mejores)
            print("    Pagina " + str(pagina) + " — " + str(len(productos_raw)) + " productos, " + str(nuevos) + " nuevos (total: " + str(len(mejores)) + ")")
        except (KeyError, TypeError) as e:
            print("    Pagina " + str(pagina) + " — Error: " + str(e))

        time.sleep(0.5)

    print("    Subtotal tras hotproduct.query: " + str(len(mejores)) + " productos")

# ─────────────────────────────────────────
#  FUENTE 2: hotproduct.download (por categorias)
# ─────────────────────────────────────────
def buscar_hotproduct_download(tasa_cambio, historial, mejores):
    if len(mejores) >= MAX_EN_COLA:
        return
    print(">>> [2/3] hotproduct.download — por categorias")

    cats = random.sample(CATEGORIAS_IDS, min(6, len(CATEGORIAS_IDS)))
    for cat_id, cat_nombre in cats:
        if len(mejores) >= MAX_EN_COLA:
            break
        try:
            data = ali_request("aliexpress.affiliate.hotproduct.download", {
                "tracking_id":     TRACKING_ID,
                "category_ids":    cat_id,
                "page_no":         str(random.randint(1, 10)),
                "page_size":       "50",
                "ship_to_country": "ES",
                "fields":          "product_id,product_title,sale_price,original_price,promotion_link",
            })
            productos_raw = (data["aliexpress_affiliate_hotproduct_download_response"]
                                ["resp_result"]["result"]["products"]["product"])
            nuevos = procesar_productos(productos_raw, tasa_cambio, historial, mejores)
            print("    " + cat_nombre + " — " + str(len(productos_raw)) + " productos, " + str(nuevos) + " nuevos (total: " + str(len(mejores)) + ")")
        except (KeyError, TypeError) as e:
            print("    " + cat_nombre + " — Sin resultados: " + str(e))

        time.sleep(0.5)

    print("    Subtotal tras hotproduct.download: " + str(len(mejores)) + " productos")

# ─────────────────────────────────────────
#  FUENTE 3: smartmatch (por keywords relevantes)
# ─────────────────────────────────────────
def buscar_smartmatch(tasa_cambio, historial, mejores):
    if len(mejores) >= MAX_EN_COLA:
        return
    print(">>> [3/3] smartmatch — por keywords")

    keywords = [
        "smartphone", "smartwatch", "earbuds", "laptop", "tablet",
        "air fryer", "robot vacuum", "led lights", "perfume", "sneakers"
    ]
    random.shuffle(keywords)

    for kw in keywords:
        if len(mejores) >= MAX_EN_COLA:
            break
        try:
            data = ali_request("aliexpress.affiliate.smartmatch.product.query", {
                "tracking_id":  TRACKING_ID,
                "keywords":     kw,
                "page_no":      "1",
                "page_size":    "20",
                "country":      "ES",
                "fields":       "product_id,product_title,sale_price,original_price,promotion_link",
            })
            productos_raw = (data["aliexpress_affiliate_smartmatch_product_query_response"]
                                ["resp_result"]["result"]["products"]["product"])
            nuevos = procesar_productos(productos_raw, tasa_cambio, historial, mejores)
            print("    '" + kw + "' — " + str(len(productos_raw)) + " productos, " + str(nuevos) + " nuevos (total: " + str(len(mejores)) + ")")
        except (KeyError, TypeError) as e:
            print("    '" + kw + "' — Sin resultados: " + str(e))

        time.sleep(0.5)

    print("    Subtotal tras smartmatch: " + str(len(mejores)) + " productos")

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    print("=== Bot Fill Queue iniciado " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")

    tasa_cambio = obtener_tipo_cambio()
    historial = cargar_historial()
    print(">>> Historial local: " + str(len(historial)) + " productos ya publicados")

    cola_actual, sha_cola = leer_cola_github()
    urls_en_cola = set(cola_actual)
    print(">>> Cola actual: " + str(len(cola_actual)) + " productos pendientes")

    if len(cola_actual) >= MAX_EN_COLA:
        print(">>> Cola ya tiene " + str(len(cola_actual)) + " productos, no es necesario rellenar")
        return

    # Buscar con las 3 fuentes en cascada
    mejores = {}
    buscar_hotproduct_query(tasa_cambio, historial, mejores)
    buscar_hotproduct_download(tasa_cambio, historial, mejores)
    buscar_smartmatch(tasa_cambio, historial, mejores)

    ofertas = list(mejores.values())
    ofertas.sort(key=lambda x: x["descuento"], reverse=True)
    print(">>> " + str(len(ofertas)) + " ofertas nuevas encontradas en total")

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

    cola_actualizada = cola_actual + nuevas_urls
    if guardar_cola_github(cola_actualizada, sha_cola):
        print(">>> Cola actualizada: " + str(len(cola_actualizada)) + " productos (" + str(len(nuevas_urls)) + " nuevos)")
    else:
        print(">>> Error al guardar la cola")
        return

    for clave in nuevas_claves:
        historial.add(clave)
    guardar_historial(historial)


if __name__ == "__main__":
    main()
