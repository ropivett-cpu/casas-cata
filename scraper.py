#!/usr/bin/env python3
"""
Casas para Cata — scraper diario v4
Estrategia: recolectar links de las páginas de resultados y extraer
todos los datos de las páginas individuales (selectores confirmados).
"""

import json, time, random, hashlib, re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ── Configuración ─────────────────────────────────────────────────────────────
MAX_PROPS  = 20
MAX_PHOTOS = 5
MAX_PRICE  = 150000
PHOTOS_DIR = Path("photos")
DELAY      = (2, 4)

# URLs de búsqueda (formato confirmado en el navegador)
ZONAPROP_SEARCHES = {
    "Florida":        "https://www.zonaprop.com.ar/casas-venta-florida-menos-150000-dolar.html",
    "Munro":          "https://www.zonaprop.com.ar/casas-venta-munro-menos-150000-dolar.html",
    "Villa Martelli": "https://www.zonaprop.com.ar/casas-venta-villa-martelli-menos-150000-dolar.html",
    "Vicente López":  "https://www.zonaprop.com.ar/casas-venta-vicente-lopez-menos-150000-dolar.html",
}

# Una sola búsqueda de Argenprop cubre todas las zonas
ARGENPROP_SEARCH = "https://www.argenprop.com/casas/venta/florida-vicente-lopez-o-munro-o-vicente-lopez-vicente-lopez-o-villa-martelli/dolares-hasta-150000"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def get(url, retries=3):
    for i in range(retries):
        try:
            time.sleep(random.uniform(*DELAY))
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"  ⚠ intento {i+1} fallido: {e}")
            time.sleep(6)
    return None

def slugify(text):
    text = text.lower().strip()
    for chars, rep in [('áàä','a'),('éèë','e'),('íìï','i'),('óòö','o'),('úùü','u'),('ñ','n')]:
        for c in chars: text = text.replace(c, rep)
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')[:50]

def photo_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:10]

def parse_price_usd(text):
    text = text.upper().replace('.','').replace(',','').replace('\n','').replace(' ','')
    if not any(x in text for x in ['USD','U$D','U$S']):
        return None
    nums = re.findall(r'\d+', text)
    candidates = [int(n) for n in nums if 4 <= len(n) <= 8]
    return max(candidates) if candidates else None

def is_within_budget(price_text):
    if not price_text or price_text.strip().lower() in ('consultar','a consultar',''):
        return True
    usd = parse_price_usd(price_text)
    if usd is None:
        return True
    return usd <= MAX_PRICE

def infer_zone(address_text):
    t = address_text.lower()
    if "martelli" in t: return "Villa Martelli"
    if "munro" in t: return "Munro"
    if "florida" in t: return "Florida"
    if "vicente" in t or "lopez" in t or "lópez" in t: return "Vicente López"
    return "Zona Norte"

def download_photo(url, prop_id, idx):
    try:
        ext = Path(urlparse(url).path).suffix or ".jpg"
        if len(ext) > 5 or "?" in ext: ext = ".jpg"
        filename = PHOTOS_DIR / f"p{prop_id}_{idx}{ext}"
        if filename.exists():
            return str(filename)
        r = get(url)
        if r and r.content and len(r.content) > 5000:  # descartar placeholders diminutos
            filename.write_bytes(r.content)
            print(f"    📷 foto {idx}: {filename.name}")
            return str(filename)
    except Exception as e:
        print(f"    ⚠ error foto: {e}")
    return None

# ── Zonaprop ──────────────────────────────────────────────────────────────────
def collect_links_zonaprop(search_url):
    """Junta los links a publicaciones individuales de una página de resultados."""
    r = get(search_url)
    if not r: return []
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/propiedades/clasificado/" in href:
            full = href if href.startswith("http") else f"https://www.zonaprop.com.ar{href}"
            full = full.split("?")[0]  # limpiar parámetros de tracking
            if full not in links:
                links.append(full)
    return links

def parse_property_zonaprop(url, zone_hint):
    """Extrae todos los datos de una publicación individual de Zonaprop."""
    r = get(url)
    if not r: return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Título — selector confirmado: h1.title-property
    title_el = soup.select_one("h1.title-property, h1[class*='title']")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title: return None

    # Precio — buscar el texto con USD
    price = "Consultar"
    for el in soup.find_all(["span","div","p"]):
        txt = el.get_text(strip=True)
        if re.match(r'^(USD|U\$S|U\$D)\s*[\d\.,]+$', txt):
            price = txt
            break

    # Dirección — selector confirmado: h4
    addr_el = soup.select_one("h4")
    addr = addr_el.get_text(strip=True) if addr_el else zone_hint

    # Descripción
    desc_el = soup.select_one("#longDescription, [class*='description'], [id*='description']")
    desc = desc_el.get_text(strip=True) if desc_el else ""

    # Fotos — selector confirmado: imgs de zonapropcdn
    photos = []
    for img in soup.find_all("img"):
        src = img.get("src","") or img.get("data-src","")
        if "zonapropcdn" in src and "avisos" in src and src not in photos:
            photos.append(src.split("?")[0])
        if len(photos) >= MAX_PHOTOS: break

    zone = infer_zone(addr)
    prop_id = f"zp-{photo_id(url)}"
    return {
        "id": prop_id, "title": title,
        "addr": addr, "price": price, "zona": zone,
        "estado": "A confirmar", "tipo": "Casa / PB",
        "desc": desc[:600] if desc else "Ver descripción completa en el portal.",
        "photo_urls": photos, "photos": [], "featured": False,
        "links": [{"l": "Zonaprop", "u": url}]
    }

def scrape_zonaprop():
    props = []
    for zone, search_url in ZONAPROP_SEARCHES.items():
        print(f"\n🔍 Zonaprop → {zone}")
        links = collect_links_zonaprop(search_url)
        print(f"   {len(links)} links encontrados")
        for link in links[:6]:
            print(f"   📄 {link.split('/')[-1][:60]}")
            p = parse_property_zonaprop(link, zone)
            if not p:
                print("      ⚠ no se pudo parsear")
                continue
            if not is_within_budget(p["price"]):
                print(f"      ⛔ Fuera de presupuesto: {p['price']}")
                continue
            print(f"      ✅ {p['title'][:50]} — {p['price']} — {len(p['photo_urls'])} fotos")
            props.append(p)
    return props

# ── Argenprop ─────────────────────────────────────────────────────────────────
def collect_links_argenprop(search_url):
    r = get(search_url)
    if not r: return []
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Los links de publicaciones de Argenprop terminan en --NNNNNNN
        if re.search(r'--\d{6,}$', href):
            full = href if href.startswith("http") else f"https://www.argenprop.com{href}"
            if full not in links:
                links.append(full)
    return links

def parse_property_argenprop(url):
    r = get(url)
    if not r: return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Título
    title_el = soup.select_one("h1, .titlebar__title, [class*='titlebar'] h2")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title: return None

    # Precio — selector confirmado: .titlebar__price
    price_el = soup.select_one(".titlebar__price")
    price = re.sub(r'\s+',' ', price_el.get_text(strip=True)) if price_el else "Consultar"

    # Dirección
    addr_el = soup.select_one(".titlebar__address, [class*='address'] span, .location-container span")
    addr = addr_el.get_text(strip=True) if addr_el else ""
    if not addr:
        # fallback: buscar spans con texto que parezca dirección
        for span in soup.find_all("span"):
            txt = span.get_text(strip=True)
            if re.search(r'al \d+|,.*Vicente|,.*Florida|,.*Munro|,.*Martelli', txt):
                addr = txt
                break
    if not addr: addr = "Zona Norte GBA"

    # Descripción
    desc_el = soup.select_one("#description, [class*='description'], .section-description")
    desc = desc_el.get_text(strip=True) if desc_el else ""

    # Fotos — confirmado: divs con background-image + imgs de static-content
    photos = []
    for div in soup.select("div[style*='background']"):
        style = div.get("style","")
        for m in re.findall(r'url\(([^)]+)\)', style):
            m = m.strip("'\" ")
            if m.startswith("http") and "placeholder" not in m and "logo" not in m and m not in photos:
                photos.append(m)
        if len(photos) >= MAX_PHOTOS: break
    if len(photos) < MAX_PHOTOS:
        for img in soup.find_all("img"):
            src = img.get("src","") or img.get("data-src","")
            if src and "static-content" in src and src not in photos:
                photos.append(src)
            if len(photos) >= MAX_PHOTOS: break

    zone = infer_zone(addr + " " + title)
    prop_id = f"ar-{photo_id(url)}"
    return {
        "id": prop_id, "title": title,
        "addr": addr, "price": price, "zona": zone,
        "estado": "A confirmar", "tipo": "Casa / PB",
        "desc": desc[:600] if desc else "Ver descripción completa en el portal.",
        "photo_urls": photos[:MAX_PHOTOS], "photos": [], "featured": False,
        "links": [{"l": "Argenprop", "u": url}]
    }

def scrape_argenprop():
    props = []
    print(f"\n🔍 Argenprop → todas las zonas")
    links = collect_links_argenprop(ARGENPROP_SEARCH)
    print(f"   {len(links)} links encontrados")
    for link in links[:12]:
        print(f"   📄 {link.split('/')[-1][:60]}")
        p = parse_property_argenprop(link)
        if not p:
            print("      ⚠ no se pudo parsear")
            continue
        if not is_within_budget(p["price"]):
            print(f"      ⛔ Fuera de presupuesto: {p['price']}")
            continue
        print(f"      ✅ {p['title'][:50]} — {p['price']} — {len(p['photo_urls'])} fotos")
        props.append(p)
    return props

# ── Dedup ─────────────────────────────────────────────────────────────────────
def dedup(props):
    seen, result = set(), []
    for p in props:
        key = slugify(p["title"])[:40]
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result

# ── Descargar fotos ───────────────────────────────────────────────────────────
def download_all_photos(props):
    PHOTOS_DIR.mkdir(exist_ok=True)
    for p in props:
        downloaded = []
        for i, url in enumerate(p.get("photo_urls",[])[:MAX_PHOTOS], 1):
            path = download_photo(url, p["id"], i)
            if path: downloaded.append(path)
        p["photos"] = downloaded
        print(f"  {'✅' if downloaded else '⚠'} {p['title'][:45]}: {len(downloaded)} fotos")
    return props

# ── Generar HTML ──────────────────────────────────────────────────────────────
def gen_html(props, week_str):
    total = len(props)
    prices = [parse_price_usd(p["price"]) for p in props]
    prices = [x for x in prices if x]
    price_range = f"U$D {min(prices)//1000}k – {max(prices)//1000}k" if prices else "–"
    patio = sum(1 for p in props if "patio" in (p["desc"]+p["title"]).lower())
    for i, p in enumerate(props):
        p["featured"] = i < 3
    props_js = json.dumps(props, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Chez Coqui</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@2.44.0/tabler-icons.min.css">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg:#F7F6F3;--bg2:#EDECEA;--text:#1A1916;--text2:#5C5A55;--text3:#9A9891;--border:#D8D6D1;
      --green:#1D9E75;--green-bg:#E1F5EE;--green-text:#085041;--green-border:#5DCAA5;
      --amber:#EF9F27;--amber-bg:#FAEEDA;--amber-text:#633806;--amber-border:#EF9F27;
      --purple:#7B74E0;--purple-bg:#EEEDFE;--purple-text:#3C3489;--purple-border:#AFA9EC;
      --red-bg:#FCEBEB;--red-text:#501313;--red-border:#F09595;
      --radius-sm:6px;--radius-md:10px;--radius-lg:14px;
    }}
    body {{ background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.5;min-height:100vh; }}
    .page {{ max-width:860px;margin:0 auto;padding:2rem 1.25rem 4rem; }}
    .site-header {{ margin-bottom:2rem;display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem; }}
    .site-header h1 {{ font-size:26px;font-weight:600;letter-spacing:-0.02em; }}
    .site-header p {{ font-size:13px;color:var(--text3);margin-top:4px; }}
    .mis-votos-btn {{ display:flex;align-items:center;gap:6px;background:var(--text);color:#fff;font-size:13px;font-weight:500;padding:8px 14px;border-radius:var(--radius-md);border:none;cursor:pointer;white-space:nowrap; }}
    .mis-votos-btn:hover {{ background:#333; }}
    .metrics {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin-bottom:2.5rem; }}
    .metric {{ background:var(--bg2);border-radius:var(--radius-md);padding:.85rem 1rem; }}
    .metric-label {{ font-size:11px;color:var(--text3);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em; }}
    .metric-val {{ font-size:24px;font-weight:600;color:var(--text); }}
    .metric-val.sm {{ font-size:13px;font-weight:500;padding-top:4px; }}
    .section-label {{ font-size:11px;font-weight:600;color:var(--text3);letter-spacing:.07em;text-transform:uppercase;margin-bottom:.75rem;display:flex;align-items:center;gap:6px; }}
    .grid {{ display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1.25rem;margin-bottom:2.5rem; }}
    @media(max-width:480px){{.grid{{grid-template-columns:1fr;}}}}
    .card-wrap {{ border-radius:var(--radius-lg);overflow:hidden; }}
    .card {{ background:#fff;border:0.5px solid var(--border);border-radius:var(--radius-lg);overflow:hidden;display:flex;flex-direction:column; }}
    .card.featured {{ border:2px solid var(--green); }}
    .carousel {{ position:relative;width:100%;aspect-ratio:16/10;background:var(--bg2);overflow:hidden; }}
    .carousel a.overlay-link {{ position:absolute;inset:0;z-index:5;display:block; }}
    .carousel img {{ position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s; }}
    .carousel img.active {{ opacity:1; }}
    .carousel-placeholder {{ position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:var(--text3); }}
    .carousel-placeholder i {{ font-size:36px; }}
    .carousel-nav {{ position:absolute;inset:0;display:flex;align-items:center;justify-content:space-between;padding:0 10px;pointer-events:none;z-index:10; }}
    .nav-btn {{ width:34px;height:34px;border-radius:50%;background:rgba(0,0,0,0.45);border:none;cursor:pointer;pointer-events:all;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px; }}
    .nav-btn:hover {{ background:rgba(0,0,0,0.7); }}
    .dots {{ position:absolute;bottom:10px;left:0;right:0;display:flex;justify-content:center;gap:5px;z-index:10;pointer-events:none; }}
    .dot {{ width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,0.5);pointer-events:all;cursor:pointer;transition:background .2s; }}
    .dot.active {{ background:#fff; }}
    .photo-count {{ position:absolute;top:10px;right:10px;background:rgba(0,0,0,0.5);color:#fff;font-size:11px;padding:3px 8px;border-radius:20px;z-index:10;pointer-events:none; }}
    .open-badge {{ position:absolute;bottom:10px;right:10px;background:rgba(0,0,0,0.55);color:#fff;font-size:11px;padding:4px 9px;border-radius:var(--radius-sm);z-index:10;pointer-events:none;display:flex;align-items:center;gap:4px; }}
    .feat-badge {{ position:absolute;top:10px;left:10px;background:var(--green);color:#fff;font-size:11px;padding:3px 9px;border-radius:20px;z-index:10;pointer-events:none;display:flex;align-items:center;gap:4px; }}
    .portal-links {{ display:flex;gap:6px;padding:.6rem 1rem;border-bottom:0.5px solid var(--border);flex-wrap:wrap; }}
    .plink {{ font-size:12px;color:#2563eb;text-decoration:none;border:0.5px solid #93c5fd;border-radius:var(--radius-sm);padding:3px 9px;display:flex;align-items:center;gap:4px; }}
    .plink:hover {{ background:#eff6ff; }}
    .card-body {{ padding:.85rem 1.25rem;display:flex;flex-direction:column;gap:8px;flex:1; }}
    .card-title {{ font-size:15px;font-weight:600;color:var(--text);line-height:1.35; }}
    .card-addr {{ font-size:13px;color:var(--text2);display:flex;align-items:center;gap:4px; }}
    .tags {{ display:flex;flex-wrap:wrap;gap:5px; }}
    .tag {{ font-size:11px;padding:3px 9px;border-radius:20px;border:0.5px solid; }}
    .tag-zona {{ background:var(--green-bg);color:var(--green-text);border-color:var(--green-border); }}
    .tag-estado {{ background:var(--amber-bg);color:var(--amber-text);border-color:var(--amber-border); }}
    .tag-tipo {{ background:var(--purple-bg);color:var(--purple-text);border-color:var(--purple-border); }}
    .desc-label {{ font-size:10px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px; }}
    .desc-block {{ background:var(--bg2);border-radius:var(--radius-sm);padding:.6rem .85rem;font-size:12px;color:var(--text2);line-height:1.65;border-left:2px solid var(--border); }}
    .desc-text {{ display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden; }}
    .desc-text.expanded {{ display:block;overflow:visible; }}
    .ver-mas {{ font-size:11px;color:var(--green-text);cursor:pointer;margin-top:4px;display:inline-block;font-weight:500;background:none;border:none;padding:0; }}
    .price-row {{ border-top:0.5px solid var(--border);padding:.75rem 1.25rem; }}
    .price {{ font-size:15px;font-weight:600;color:var(--text); }}
    .vote-bar {{ border-top:0.5px solid var(--border);padding:.6rem 1.25rem;display:flex;align-items:center;gap:7px;flex-wrap:wrap; }}
    .vote-label {{ font-size:12px;color:var(--text3);margin-right:2px; }}
    .vote-btn {{ font-size:12px;padding:4px 11px;border:0.5px solid var(--border);border-radius:var(--radius-sm);background:transparent;cursor:pointer;color:var(--text2);display:flex;align-items:center;gap:4px;transition:transform .1s; }}
    .vote-btn:active {{ transform:scale(0.95); }}
    .vote-btn:hover {{ background:var(--bg2); }}
    .vote-btn.active-love {{ background:var(--green-bg);color:var(--green-text);border-color:var(--green-border); }}
    .vote-btn.active-meh {{ background:var(--amber-bg);color:var(--amber-text);border-color:var(--amber-border); }}
    .vote-btn.active-no {{ background:var(--red-bg);color:var(--red-text);border-color:var(--red-border); }}
    .divider {{ border:none;border-top:0.5px solid var(--border);margin-bottom:2rem; }}
    .empty-state {{ background:var(--bg2);border-radius:var(--radius-lg);padding:1.25rem 1.5rem;font-size:13px;color:var(--text3);margin-bottom:2rem;display:flex;align-items:center;gap:8px; }}
    .floater {{ position:fixed;pointer-events:none;font-size:28px;z-index:9999; }}
    @keyframes float-up {{ 0%{{opacity:1;transform:translateY(0) scale(1)}} 100%{{opacity:0;transform:translateY(-120px) scale(1.4)}} }}
    @keyframes float-right {{ 0%{{opacity:1;transform:translateX(0) scale(1)}} 100%{{opacity:0;transform:translateX(120px) scale(1.4)}} }}
    @keyframes float-upright {{ 0%{{opacity:1;transform:translate(0,0) scale(1)}} 100%{{opacity:0;transform:translate(60px,-90px) scale(1.2)}} }}
    @keyframes slide-up {{ 0%{{opacity:1;transform:translateY(0)}} 100%{{opacity:0;transform:translateY(-30px)}} }}
    @keyframes slide-right {{ 0%{{opacity:1;transform:translateX(0)}} 100%{{opacity:0;transform:translateX(60px)}} }}
    @media(prefers-reduced-motion:reduce){{ .floater,.card-wrap{{animation:none!important;}} }}
    .modal-overlay {{ display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;overflow-y:auto;padding:2rem 1rem; }}
    .modal-overlay.open {{ display:block; }}
    .modal {{ background:var(--bg);border-radius:var(--radius-lg);max-width:800px;margin:0 auto;overflow:hidden; }}
    .modal-header {{ display:flex;justify-content:space-between;align-items:center;padding:1.25rem 1.5rem;border-bottom:0.5px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10; }}
    .modal-header h2 {{ font-size:18px;font-weight:600; }}
    .modal-close {{ background:none;border:none;cursor:pointer;color:var(--text3);font-size:20px;display:flex;align-items:center; }}
    .modal-body {{ padding:1.5rem; }}
    .modal-section-label {{ font-size:11px;font-weight:600;color:var(--text3);letter-spacing:.07em;text-transform:uppercase;margin-bottom:1rem;display:flex;align-items:center;gap:6px; }}
    .modal-list {{ display:flex;flex-direction:column;gap:.75rem;margin-bottom:2rem; }}
    .modal-item {{ background:#fff;border:0.5px solid var(--border);border-radius:var(--radius-md);padding:1rem 1.25rem;display:flex;justify-content:space-between;align-items:flex-start;gap:1rem; }}
    .modal-item.love-border {{ border-left:3px solid var(--green); }}
    .modal-item.meh-border {{ border-left:3px solid var(--amber); }}
    .modal-item-info {{ flex:1;min-width:0; }}
    .modal-item-title {{ font-size:14px;font-weight:600;color:var(--text);margin-bottom:3px;line-height:1.3; }}
    .modal-item-addr {{ font-size:12px;color:var(--text3); }}
    .modal-item-price {{ font-size:13px;font-weight:600;color:var(--text);margin-top:4px; }}
    .modal-item-links {{ display:flex;flex-direction:column;gap:5px;flex-shrink:0; }}
    .modal-link {{ font-size:12px;color:#2563eb;text-decoration:none;border:0.5px solid #93c5fd;border-radius:var(--radius-sm);padding:4px 10px;display:flex;align-items:center;gap:4px;white-space:nowrap; }}
    .modal-link:hover {{ background:#eff6ff; }}
    .modal-empty {{ font-size:13px;color:var(--text3);margin-bottom:2rem; }}
    .modal-remove {{ font-size:12px;color:var(--red-text);background:var(--red-bg);border:0.5px solid var(--red-border);border-radius:var(--radius-sm);padding:4px 10px;cursor:pointer;display:flex;align-items:center;gap:4px;white-space:nowrap; }}
    .modal-remove:hover {{ opacity:0.8; }}
  </style>
</head>
<body>
<div class="page">
  <header class="site-header">
    <div>
      <h1>Chez Coqui</h1>
      <p>Actualizado el {week_str} · Florida · Munro · Villa Martelli · hasta U$D 150.000</p>
    </div>
    <button class="mis-votos-btn" onclick="openModal()"><i class="ti ti-heart"></i> Mis votos</button>
  </header>
  <div class="metrics">
    <div class="metric"><div class="metric-label">Relevadas</div><div class="metric-val">{total}</div></div>
    <div class="metric"><div class="metric-label">Rango</div><div class="metric-val sm">{price_range}</div></div>
    <div class="metric"><div class="metric-label">Con patio</div><div class="metric-val">{patio} / {total}</div></div>
    <div class="metric"><div class="metric-label">Favoritas</div><div class="metric-val" id="count-love">–</div></div>
    <div class="metric"><div class="metric-label">Posibles</div><div class="metric-val" id="count-meh">–</div></div>
  </div>
  <div id="sec-love" style="display:none"><div class="section-label"><i class="ti ti-heart"></i> Favoritas</div><div class="grid" id="grid-love"></div><hr class="divider"></div>
  <div id="sec-meh" style="display:none"><div class="section-label"><i class="ti ti-clock"></i> Posibles</div><div class="grid" id="grid-meh"></div><hr class="divider"></div>
  <div class="section-label"><i class="ti ti-star"></i> Destacadas</div>
  <div class="grid" id="grid-featured"></div>
  <div class="section-label" style="margin-top:.25rem"><i class="ti ti-list"></i> Otras opciones</div>
  <div class="grid" id="grid-others"></div>
</div>
<div class="modal-overlay" id="modal-overlay" onclick="closeModalOutside(event)">
  <div class="modal">
    <div class="modal-header"><h2>Mis votos</h2><button class="modal-close" onclick="closeModal()"><i class="ti ti-x"></i></button></div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>
<script>
const PROPS = {props_js};
const STORAGE_KEY = 'casas-cata-votos';
const cs = {{}};
function loadVotes(){{ try{{ return JSON.parse(localStorage.getItem(STORAGE_KEY))||{{}}; }}catch{{return{{}};}} }}
function saveVotes(v){{ try{{ localStorage.setItem(STORAGE_KEY,JSON.stringify(v)); }}catch{{}} }}
let votes = loadVotes();
function spawnFloater(emoji,btnEl,anim){{
  const rect=btnEl.getBoundingClientRect();
  const el=document.createElement('div');
  el.className='floater';el.textContent=emoji;
  el.style.left=(rect.left+rect.width/2-14)+'px';
  el.style.top=(rect.top-10)+'px';
  el.style.animation=`${{anim}} 0.7s ease-out forwards`;
  document.body.appendChild(el);setTimeout(()=>el.remove(),750);
}}
function animateCard(id,animName){{
  const wrap=document.querySelector(`#card-wrap-${{id}}`);
  if(wrap)wrap.style.animation=`${{animName}} 0.35s ease-out forwards`;
}}
function carouselHTML(p){{
  const ph=p.photos||[];
  const firstLink=(p.links&&p.links[0])?p.links[0].u:'#';
  if(!ph.length)return`<div class="carousel"><div class="carousel-placeholder"><i class="ti ti-photo"></i><span>Sin fotos disponibles</span></div></div>`;
  const imgs=ph.map((s,i)=>`<img src="${{s}}" alt="Foto ${{i+1}}" class="${{i===0?'active':''}}" loading="lazy">`).join('');
  const dots=ph.length>1?ph.map((_,i)=>`<span class="dot${{i===0?' active':''}}" onclick="event.stopPropagation();goTo('${{p.id}}',${{i}})"></span>`).join(''):'';
  const feat=p.featured?`<div class="feat-badge"><i class="ti ti-star"></i> Destacada</div>`:'';
  const count=ph.length>1?`<div class="photo-count" id="pc-${{p.id}}">1 / ${{ph.length}}</div>`:'';
  const nav=ph.length>1?`<div class="carousel-nav">
    <button class="nav-btn" onclick="event.preventDefault();event.stopPropagation();goSlide('${{p.id}}',-1)"><i class="ti ti-chevron-left"></i></button>
    <button class="nav-btn" onclick="event.preventDefault();event.stopPropagation();goSlide('${{p.id}}',1)"><i class="ti ti-chevron-right"></i></button>
  </div><div class="dots">${{dots}}</div>`:'';
  return`<div class="carousel" data-id="${{p.id}}">
    <a class="overlay-link" href="${{firstLink}}" target="_blank"></a>
    ${{imgs}}${{feat}}${{count}}
    <div class="open-badge"><i class="ti ti-external-link"></i> Ver publicación</div>
    ${{nav}}
  </div>`;
}}
function cardHTML(p){{
  const links=(p.links||[]).map(l=>`<a class="plink" href="${{l.u}}" target="_blank">${{l.l}} <i class="ti ti-external-link" style="font-size:11px"></i></a>`).join('');
  const v=votes[p.id]||'';
  return`<div id="card-wrap-${{p.id}}" class="card-wrap">
    <div class="card${{p.featured?' featured':''}}" id="card-${{p.id}}">
      ${{carouselHTML(p)}}
      <div class="portal-links">${{links}}</div>
      <div class="card-body">
        <div class="card-title">${{p.title}}</div>
        <div class="card-addr"><i class="ti ti-map-pin" style="font-size:13px"></i> ${{p.addr}}</div>
        <div class="tags"><span class="tag tag-zona">${{p.zona}}</span><span class="tag tag-estado">${{p.estado}}</span><span class="tag tag-tipo">${{p.tipo}}</span></div>
        <div>
          <div class="desc-label">Descripción del portal</div>
          <div class="desc-block">
            <div class="desc-text" id="desc-${{p.id}}">${{p.desc}}</div>
            <button class="ver-mas" id="vm-${{p.id}}" onclick="toggleDesc('${{p.id}}')">Ver más</button>
          </div>
        </div>
      </div>
      <div class="price-row"><span class="price">${{p.price}}</span></div>
      <div class="vote-bar">
        <span class="vote-label">¿Qué te parece?</span>
        <button class="vote-btn${{v==='love'?' active-love':''}}" data-id="${{p.id}}" data-vote="love" onclick="setVote('${{p.id}}','love',this)"><i class="ti ti-heart"></i> Me encanta</button>
        <button class="vote-btn${{v==='meh'?' active-meh':''}}" data-id="${{p.id}}" data-vote="meh" onclick="setVote('${{p.id}}','meh',this)">Puede ser</button>
        <button class="vote-btn${{v==='no'?' active-no':''}}" data-id="${{p.id}}" data-vote="no" onclick="setVote('${{p.id}}','no',this)"><i class="ti ti-x"></i> No</button>
      </div>
    </div>
  </div>`;
}}
function toggleDesc(id){{
  const el=document.getElementById(`desc-${{id}}`);
  const btn=document.getElementById(`vm-${{id}}`);
  if(!el||!btn)return;
  const exp=el.classList.toggle('expanded');
  btn.textContent=exp?'Ver menos':'Ver más';
}}
function goSlide(id,dir){{
  const p=PROPS.find(x=>x.id===id);const ph=p?p.photos:[];if(!ph.length)return;
  const imgs=document.querySelectorAll(`.carousel[data-id="${{id}}"] img`);
  const dots=document.querySelectorAll(`.carousel[data-id="${{id}}"] .dot`);
  let cur=cs[id]||0;
  imgs[cur].classList.remove('active');if(dots[cur])dots[cur].classList.remove('active');
  cur=(cur+dir+ph.length)%ph.length;cs[id]=cur;
  imgs[cur].classList.add('active');if(dots[cur])dots[cur].classList.add('active');
  const pc=document.getElementById(`pc-${{id}}`);if(pc)pc.textContent=`${{cur+1}} / ${{ph.length}}`;
}}
function goTo(id,idx){{
  const p=PROPS.find(x=>x.id===id);const ph=p?p.photos:[];if(!ph.length)return;
  const imgs=document.querySelectorAll(`.carousel[data-id="${{id}}"] img`);
  const dots=document.querySelectorAll(`.carousel[data-id="${{id}}"] .dot`);
  let cur=cs[id]||0;
  imgs[cur].classList.remove('active');if(dots[cur])dots[cur].classList.remove('active');
  cs[id]=idx;imgs[idx].classList.add('active');if(dots[idx])dots[idx].classList.add('active');
  const pc=document.getElementById(`pc-${{id}}`);if(pc)pc.textContent=`${{idx+1}} / ${{ph.length}}`;
}}
function setVote(id,val,btnEl){{
  const prev=votes[id];
  if(prev===val){{delete votes[id];saveVotes(votes);render();return;}}
  votes[id]=val;saveVotes(votes);
  if(val==='love')spawnFloater('❤️',btnEl,'float-up');
  else if(val==='meh')spawnFloater('🤔',btnEl,'float-upright');
  else spawnFloater('✕',btnEl,'float-right');
  if(!prev){{animateCard(id,val==='no'?'slide-right':'slide-up');setTimeout(()=>render(),360);}}
  else render();
}}
function render(){{
  const loved=PROPS.filter(p=>votes[p.id]==='love');
  const meh=PROPS.filter(p=>votes[p.id]==='meh');
  const hidden=new Set(PROPS.filter(p=>votes[p.id]==='no').map(p=>p.id));
  document.getElementById('count-love').textContent=loved.length||'–';
  document.getElementById('count-meh').textContent=meh.length||'–';
  const sl=document.getElementById('sec-love');const sm=document.getElementById('sec-meh');
  sl.style.display=loved.length?'block':'none';
  sm.style.display=meh.length?'block':'none';
  if(loved.length)document.getElementById('grid-love').innerHTML=loved.map(cardHTML).join('');
  if(meh.length)document.getElementById('grid-meh').innerHTML=meh.map(cardHTML).join('');
  const feat=PROPS.filter(p=>p.featured&&!votes[p.id]&&!hidden.has(p.id));
  const others=PROPS.filter(p=>!p.featured&&!votes[p.id]&&!hidden.has(p.id));
  document.getElementById('grid-featured').innerHTML=feat.length?feat.map(cardHTML).join(''):`<div class="empty-state"><i class="ti ti-check"></i> Ya las clasificaste todas.</div>`;
  document.getElementById('grid-others').innerHTML=others.length?others.map(cardHTML).join(''):`<div class="empty-state"><i class="ti ti-check"></i> Ya las clasificaste todas.</div>`;
}}
function openModal(){{
  const loved=PROPS.filter(p=>votes[p.id]==='love');
  const meh=PROPS.filter(p=>votes[p.id]==='meh');
  function itemHTML(p,cls){{
    const links=(p.links||[]).map(l=>`<a class="modal-link" href="${{l.u}}" target="_blank"><i class="ti ti-external-link" style="font-size:11px"></i> ${{l.l}}</a>`).join('');
    return`<div class="modal-item ${{cls}}"><div class="modal-item-info"><div class="modal-item-title">${{p.title}}</div><div class="modal-item-addr">${{p.addr}}</div><div class="modal-item-price">${{p.price}}</div></div><div class="modal-item-links">${{links}}<button class="modal-remove" onclick="removeVote('${{p.id}}')"><i class="ti ti-trash" style="font-size:11px"></i> Quitar</button></div></div>`;
  }}
  let html='';
  html+=`<div class="modal-section-label"><i class="ti ti-heart"></i> Favoritas</div>`;
  html+=loved.length?`<div class="modal-list">${{loved.map(p=>itemHTML(p,'love-border')).join('')}}</div>`:`<p class="modal-empty">Todavía no marcaste ninguna como favorita.</p>`;
  html+=`<div class="modal-section-label"><i class="ti ti-clock"></i> Posibles</div>`;
  html+=meh.length?`<div class="modal-list">${{meh.map(p=>itemHTML(p,'meh-border')).join('')}}</div>`:`<p class="modal-empty">Todavía no marcaste ninguna como posible.</p>`;
  document.getElementById('modal-body').innerHTML=html;
  document.getElementById('modal-overlay').classList.add('open');
  document.body.style.overflow='hidden';
}}
function removeVote(id){{
  delete votes[id];
  saveVotes(votes);
  render();
  openModal();
}}
function closeModal(){{
  document.getElementById('modal-overlay').classList.remove('open');
  document.body.style.overflow='';
}}
function closeModalOutside(e){{
  if(e.target===document.getElementById('modal-overlay'))closeModal();
}}
render();
</script>
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("🏠 Casas para Cata — scraper v4\n")
    props = []
    props += scrape_zonaprop()
    props += scrape_argenprop()
    print(f"\n📦 Total bruto: {len(props)}")
    props = dedup(props)
    props = props[:MAX_PROPS]
    print(f"✅ Después de dedup: {len(props)}")
    print("\n📷 Descargando fotos...")
    props = download_all_photos(props)
    MESES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    today = date.today()
    week_str = f"{today.day} de {MESES[today.month-1]} de {today.year}"
    print("\n📝 Generando index.html...")
    html = gen_html(props, week_str)
    Path("index.html").write_text(html, encoding="utf-8")
    print(f"\n✅ Listo. {len(props)} propiedades.")

if __name__ == "__main__":
    main()
