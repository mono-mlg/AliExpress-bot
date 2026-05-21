import os, json, time, hashlib, random, base64, requests, re
from datetime import datetime

APP_KEY        = os.environ["ALI_APP_KEY"]
APP_SECRET     = os.environ["ALI_APP_SECRET"]
TRACKING_ID    = os.environ["ALI_TRACKING_ID"]
GH_TOKEN       = os.environ["GH_TOKEN"]
GH_USER        = os.environ["GH_USER"]
GH_REPO        = os.environ["GH_REPO"]
KEYWORD        = os.environ.get("KEYWORD", "smartwatch")
MIN_DESCUENTO  = int(os.environ.get("MIN_DESCUENTO", "20"))
MIN_PRECIO     = float(os.environ.get("MIN_PRECIO", "5"))
MAX_RESULTADOS = int(os.environ.get("MAX_RESULTADOS", "30"))
SORT           = os.environ.get("SORT", "LAST_VOLUME_DESC")
ALI_API_URL    = "https://api-sg.aliexpress.com/sync"

GH_HEADERS = {
    "Authorization": "token " + GH_TOKEN,
    "Accept": "application/vnd.github.v3+json"
}

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

def obtener_tipo_cambio():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/CNY", timeout=10)
        return r.json()["rates"]["EUR"]
    except:
        return 0.128

def buscar():
    tasa = obtener_tipo_cambio()
    print(">>> Buscando: " + KEYWORD)
    productos = []
    paginas_probadas = set()
    intentos = 0

    while len(productos) < MAX_RESULTADOS and intentos < 10:
        pagina = random.randint(1, 20)
        while pagina in paginas_probadas:
            pagina = random.randint(1, 20)
        paginas_probadas.add(pagina)
        intentos += 1
        try:
            data = ali_request("aliexpress.affiliate.hotproduct.query", {
                "tracking_id":     TRACKING_ID,
                "keywords":        KEYWORD,
                "page_no":         str(pagina),
                "page_size":       "50",
                "sort":            SORT,
                "ship_to_country": "ES",
                "fields":          "product_id,product_title,product_main_image_url,sale_price,original_price,promotion_link,evaluate_rate,volume",
            })
            raw = (data["aliexpress_affiliate_hotproduct_query_response"]
                       ["resp_result"]["result"]["products"]["product"])
            print("    Pagina " + str(pagina) + " — " + str(len(raw)) + " productos")
            for p in raw:
                try:
                    precio_orig = round(float(str(p.get("original_price","0")).replace(",",".")) * tasa, 2)
                    precio_sale = round(float(str(p.get("sale_price","0")).replace(",",".")) * tasa, 2)
                    if precio_orig < MIN_PRECIO or precio_sale <= 0:
                        continue
                    descuento = round((1 - precio_sale / precio_orig) * 100)
                    if descuento < MIN_DESCUENTO:
                        continue
                    productos.append({
                        "id":          str(p["product_id"]),
                        "titulo":      p.get("product_title","")[:100],
                        "imagen":      p.get("product_main_image_url",""),
                        "precio_orig": precio_orig,
                        "precio_sale": precio_sale,
                        "descuento":   descuento,
                        "rating":      float(p.get("evaluate_rate","0")),
                        "ventas":      int(p.get("volume","0")),
                        "link":        p.get("promotion_link",""),
                    })
                except:
                    continue
        except (KeyError, TypeError) as e:
            print("    Error: " + str(e))
        time.sleep(0.5)

    vistos = set()
    unicos = []
    for p in productos:
        if p["id"] not in vistos:
            vistos.add(p["id"])
            unicos.append(p)
    unicos.sort(key=lambda x: x["descuento"], reverse=True)
    return unicos[:MAX_RESULTADOS], tasa

def guardar_resultados(productos, tasa):
    resultado = {
        "keyword":   KEYWORD,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total":     len(productos),
        "tasa_eur":  tasa,
        "productos": productos,
    }
    url = f"https://api.github.com/repos/{GH_USER}/{GH_REPO}/contents/resultados_busqueda.json"
    contenido = json.dumps(resultado, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(contenido.encode("utf-8")).decode("utf-8")
    r = requests.get(url, headers=GH_HEADERS, timeout=15)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": "Resultados: " + KEYWORD, "content": encoded, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=GH_HEADERS, json=payload, timeout=15)
    print(">>> GitHub: " + str(r.status_code))

if __name__ == "__main__":
    print("=== Buscar Productos " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " ===")
    productos, tasa = buscar()
    print(">>> " + str(len(productos)) + " productos encontrados")
    guardar_resultados(productos, tasa)
    print("=== Fin ===")
