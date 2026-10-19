import os
import re
import json
import time
import socket
import collections
import urllib.parse
import hashlib
import shutil
from html import escape, unescape
from datetime import datetime, timezone, timedelta
import requests
import cloudscraper
import feedparser
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from groq import Groq

# feedparser.parse(url) non ha timeout proprio: senza questo un sito che non
# risponde potrebbe bloccare l'intera esecuzione.
socket.setdefaulttimeout(30)

# ---------------------------------------------------------------------------
# CONFIGURAZIONE FONTI
# "tipo": "rss" (default) legge un feed RSS/Atom classico.
# "tipo": "pagina" segue una singola pagina/sezione del sito (nessun feed
# disponibile o feed non voluto) ed estrae solo i link agli articoli veri e
# propri, ignorando menu, sidebar e rumore.
# ---------------------------------------------------------------------------
FONTI = [
    {"nome": "Il Tascabile", "tipo": "rss", "url": "https://www.iltascabile.com/feed/", "fallback": None, "categoria": "Saggistica", "colore": "#059669"},
    {"nome": "The Italian Review", "tipo": "rss", "url": "https://www.theitalianreview.com/feed/", "fallback": None, "categoria": "Critica", "colore": "#4338ca"},
    {"nome": "Valigia Blu", "tipo": "rss", "url": "https://www.valigiablu.it/category/fuori-da-qui/feed/", "fallback": "https://www.valigiablu.it/feed/", "categoria": "Geopolitica", "colore": "#0284c7"},
    {"nome": "IrpiMedia (Inchieste)", "tipo": "rss", "url": "https://irpimedia.irpi.eu/inchieste/feed/", "fallback": "https://irpimedia.irpi.eu/feed/", "categoria": "Inchiesta", "colore": "#dc2626"},
    {"nome": "IrpiMedia (Editoriali)", "tipo": "rss", "url": "https://irpimedia.irpi.eu/editoriali/feed/", "fallback": "https://irpimedia.irpi.eu/feed/", "categoria": "Opinione", "colore": "#991b1b"},
    {"nome": "1000 Words", "tipo": "rss", "url": "https://www.1000wordsmag.com/feed/", "fallback": "http://www.1000wordsmag.com/feed/", "categoria": "Fotografia", "colore": "#d97706"},

    {"nome": "Frieze", "tipo": "pagina", "url": "https://www.frieze.com/opinion", "categoria": "Arte Contemporanea", "colore": "#0f172a"},
    {"nome": "ArtReview", "tipo": "pagina", "url": "https://artreview.com/category/review/", "categoria": "Critica d'Arte", "colore": "#7c3aed"},
    {"nome": "Aperture (Essays)", "tipo": "pagina", "url": "https://aperture.org/editorial/essays", "categoria": "Fotografia", "colore": "#b45309"},
    {"nome": "Aperture (Reviews)", "tipo": "pagina", "url": "https://aperture.org/editorial/reviews/", "categoria": "Fotografia", "colore": "#92400e"},
    {"nome": "Mousse Magazine", "tipo": "pagina", "url": "https://www.moussemagazine.it/magazine/category/reviews/", "categoria": "Arte Contemporanea", "colore": "#be123c"},
    {"nome": "Solomon", "tipo": "pagina", "url": "https://wearesolomon.com/en/", "categoria": "Cultura", "colore": "#0ea5e9"},
    {"nome": "FADA Collective", "tipo": "pagina", "url": "https://www.fadacollective.com/report", "categoria": "Reportage", "colore": "#ea580c"},
    {"nome": "Narratively", "tipo": "rss", "url": "https://www.narratively.com/feed", "categoria": "Narrativa", "colore": "#0f766e"},

    {"nome": "Italia che Cambia", "tipo": "pagina", "italiano": True, "url": "https://www.italiachecambia.org/cose%20da%20sapere/", "categoria": "Attualità", "colore": "#16a34a"},

    {"nome": "Pangea", "tipo": "rss", "italiano": True, "url": "https://www.pangea.news/feed/", "pagina_fallback": "https://www.pangea.news/", "categoria": "Cultura", "colore": "#9333ea"},
    {"nome": "Indiscreto", "tipo": "rss", "italiano": True, "url": "https://www.indiscreto.org/feed/", "pagina_fallback": "https://www.indiscreto.org/", "categoria": "Cultura", "colore": "#b91c1c"},
    {"nome": "Gli Asini", "tipo": "rss", "italiano": True, "url": "https://gliasinirivista.org/feed/", "pagina_fallback": "https://gliasinirivista.org/", "categoria": "Cultura", "colore": "#a16207"},
    {"nome": "Doppiozero (Filosofia)", "tipo": "pagina", "italiano": True, "url": "https://www.doppiozero.com/filosofia", "categoria": "Filosofia", "colore": "#0369a1"},

    {"nome": "Aeon", "tipo": "rss", "url": "https://aeon.co/feed.rss", "solo_link": "/essays/", "pagina_fallback": "https://aeon.co/essays", "categoria": "Saggi", "colore": "#1d4ed8"},

    {"nome": "Contemporary Art Daily", "tipo": "immagini", "url": "https://www.contemporaryartdaily.com", "categoria": "Arte Contemporanea", "colore": "#18181b"},

    {"nome": "Filosofia Stramba", "tipo": "telegram", "url": "https://t.me/s/filosofiastramba", "categoria": "Filosofia", "colore": "#eab308"},
]

DATABASE_FILE = "feed_database.json"
FEED_OUTPUT = "feed_sintesi.xml"
FEED_OUTPUT_IMMAGINI = "feed_contemporary_art_daily.xml"
FEED_SITE = "https://lorenzoromani367.github.io/NewsFeed/"
VERSIONE_CACHE = "v18"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

BLOCCO_ANTIBOT = re.compile(r"robot challenge|captcha|just a moment|verify you are human|checking your browser|attention required|enable javascript and cookies", re.I)

TESTI_DA_IGNORARE = {
    "read more", "continue reading", "share", "subscribe", "home", "next",
    "previous", "next page", "menu", "search", "leggi tutto", "leggi di più",
    "condividi", "iscriviti", "cerca", "pagina successiva",
}

scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'darwin', 'desktop': True})
client = Groq(api_key=os.environ.get("GROQ_API_KEY")) if os.environ.get("GROQ_API_KEY") else None

JINA_API_KEY = os.environ.get("JINA_API_KEY")
HEADERS_JINA = {**HEADERS, "Authorization": f"Bearer {JINA_API_KEY}"} if JINA_API_KEY else HEADERS

def carica_database():
    if not os.path.exists(DATABASE_FILE): return {}
    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # Meglio fermarsi che ripartire da un database vuoto e sovrascrivere la cache.
        raise SystemExit(f"{DATABASE_FILE} illeggibile ({e}): correggilo o ripristinalo prima di rilanciare.")

def salva_database(db):
    tmp = DATABASE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATABASE_FILE)

def scarica_bypass(url, timeout_diretto=12, timeout_proxy=15):
    """Scarica un URL tentando, in ordine, accesso diretto e proxy AllOrigins.
    (corsproxy.io è stato rimosso: richiede ora un'API key, risponde sempre
    401 senza). Non inghiotte gli errori: stampa sempre lo status HTTP o
    l'eccezione reale, per poter diagnosticare un blocco anti-bot invece di
    limitarsi a saltarlo in silenzio."""
    try:
        res = scraper.get(url, timeout=timeout_diretto)
        if res.status_code == 200 and len(res.content) > 200:
            return res.content, "diretto"
        print(f"    [DIRETTO] {url} -> HTTP {res.status_code}", flush=True)
    except Exception as e:
        print(f"    [DIRETTO] {url} -> {type(e).__name__}: {e}", flush=True)

    # Alcuni siti (es. indiscreto.org) rifiutano l'handshake TLS di cloudscraper:
    # una richiesta con le impostazioni TLS standard di requests passa.
    try:
        res = requests.get(url, headers=HEADERS, timeout=timeout_diretto)
        if res.status_code == 200 and len(res.content) > 200:
            return res.content, "requests"
        print(f"    [REQUESTS] {url} -> HTTP {res.status_code}", flush=True)
    except Exception as e:
        print(f"    [REQUESTS] {url} -> {type(e).__name__}: {e}", flush=True)

    try:
        safe_url = urllib.parse.quote(url, safe='')
        res = requests.get(f"https://api.allorigins.win/raw?url={safe_url}", headers=HEADERS, timeout=timeout_proxy)
        if res.status_code == 200 and len(res.content) > 200:
            return res.content, "allorigins"
        print(f"    [ALLORIGINS] {url} -> HTTP {res.status_code}", flush=True)
    except Exception as e:
        print(f"    [ALLORIGINS] {url} -> {type(e).__name__}: {e}", flush=True)

    return None, "fallito"

def _debug_candidati_link(soup, dominio, url):
    """Diagnostica temporanea: quando l'euristica h1-h4 non trova nulla ma la
    pagina è stata scaricata, stampa i link più promettenti (testo lungo,
    stesso dominio) con il tag e la classe del loro contenitore diretto, per
    capire come il sito marca i titoli e poter scrivere un selettore mirato."""
    visti = set()
    stampati = 0
    for tag in soup.find_all("a", href=True):
        testo = tag.get_text().strip()
        href = urllib.parse.urljoin(url, tag["href"])
        if len(testo) < 15 or urllib.parse.urlparse(href).netloc != dominio: continue
        if href in visti: continue
        visti.add(href)
        genitore = tag.parent
        percorso = " > ".join(
            f'{t.name}.{".".join(t.get("class", []))}' if t.get("class") else t.name
            for t in [genitore, genitore.parent if genitore else None] if t
        )
        print(f"    [DEBUG] \"{testo[:60]}\" href={href} contenitore={percorso}", flush=True)
        stampati += 1
        if stampati >= 8: break
    if stampati == 0:
        print(f"    [DEBUG] {url} -> nessun <a> con testo >= 15 caratteri sullo stesso dominio", flush=True)

def recupera_feed_xml(url, fallback_url=None):
    for target in [u for u in [url, fallback_url] if u]:
        contenuto, esito = scarica_bypass(target)
        if contenuto:
            parsed = feedparser.parse(contenuto)
            if len(parsed.entries) > 0: return parsed
            print(f"    [FEED] {target} scaricato ({esito}) ma senza voci valide", flush=True)
    return feedparser.parse(url)

def recupera_articoli_pagina(url, nome_fonte="", limite=2):
    """Ricava (titolo, link) degli articoli veri e propri da UNA pagina/sezione
    di un sito, senza bisogno di un feed RSS. Prova prima lo scraping diretto
    dell'HTML (cercando i link dentro ai titoli h1-h4, che nella pratica si è
    rivelato più affidabile del Reader di Jina, spesso rate-limitato sugli IP
    condivisi dei runner GitHub); se non trova nulla di utile, ripiega su
    Jina (r.jina.ai) come ultima risorsa."""
    dominio = urllib.parse.urlparse(url).netloc
    nome_fonte_norm = nome_fonte.strip().lower()

    def filtra_e_deduplica(coppie):
        visti, risultato = set(), []
        for testo, href in coppie:
            testo = " ".join(testo.split())  # collassa newline/spazi multipli (es. righe markdown incollate)
            href = href.split("#")[0].rstrip("/")
            if not href or href in visti: continue
            if href == url.rstrip("/"): continue
            if re.search(r"/(category|tag|author|page)/", urllib.parse.urlparse(href).path): continue
            if re.search(r"\.(pdf|jpe?g|png|gif|zip)$", href, re.I) or "/wp-content/uploads/" in href: continue
            if urllib.parse.urlparse(href).netloc != dominio: continue
            testo_norm = testo.lower()
            if len(testo) < 15 or testo.startswith(("!", "[")): continue
            if testo_norm == nome_fonte_norm: continue
            if any(k in testo_norm for k in TESTI_DA_IGNORARE): continue
            percorso = urllib.parse.urlparse(href).path
            if len(percorso.strip("/")) < 25: continue  # scarta link brevi/generici (menu, sezioni)
            visti.add(href)
            risultato.append((testo, href))
            if len(risultato) >= limite: break
        return risultato

    contenuto, esito = scarica_bypass(url)
    if contenuto:
        soup = BeautifulSoup(contenuto, "html.parser")
        coppie = [(tag.get_text(), urllib.parse.urljoin(url, tag.get("href", "")))
                  for tag in soup.select("h1 a[href], h2 a[href], h3 a[href], h4 a[href]")]
        risultato = filtra_e_deduplica(coppie)
        if risultato: return risultato
        print(f"    [PAGINA] {url} -> scaricato ({esito}) ma nessun link articolo riconosciuto", flush=True)
        _debug_candidati_link(soup, dominio, url)
    else:
        print(f"    [PAGINA] {url} -> irraggiungibile ({esito})", flush=True)

    try:
        res = requests.get(f"https://r.jina.ai/{url}", headers=HEADERS_JINA, timeout=20)
        if res.status_code == 200 and len(res.text) > 200:
            coppie = re.findall(r'(?<!!)\[([^\]]{8,200})\]\((https?://[^\s)]+)\)', res.text)
            risultato = filtra_e_deduplica(coppie)
            if risultato: return risultato
            print(f"    [JINA] {url} -> nessun link articolo riconosciuto", flush=True)
        else:
            print(f"    [JINA] {url} -> HTTP {res.status_code}", flush=True)
    except Exception as e:
        print(f"    [JINA] {url} -> {type(e).__name__}: {e}", flush=True)

    return []

MAX_IMMAGINI = 8

def url_sicuro(link):
    """URL con spazi e caratteri speciali codificati (alcuni siti hanno slug con spazi)."""
    return urllib.parse.quote(link, safe="%/:?#[]@!$&'()*+,;=~")

def immagini_valide_html(html, link=""):
    """Immagini <img> di una scheda che sono contenuto: non loghi/icone e non del dominio del sito."""
    host = urllib.parse.urlparse(link).netloc
    valide = []
    for u in re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', html):
        u = unescape(u)
        if immagine_scartata(u) or (host and urllib.parse.urlparse(u).netloc == host): continue
        if u not in valide: valide.append(u)
    return valide

def incornicia_immagini(html):
    """Avvolge ogni immagine in un link all'immagine stessa: toccandola si apre a
    tutto schermo (lightbox nelle nostre pagine; nei reader apre l'immagine nel browser)."""
    return re.sub(r'(<img\b[^>]*?\bsrc=")([^"]+)("[^>]*>)',
                  lambda m: f'<a class="zoom" href="{m.group(2)}">{m.group(0)}</a>', html)

def immagine_scartata(url):
    """True per immagini che non sono contenuto dell'articolo: pixel di
    tracciamento, emoji, icone e loghi dell'interfaccia, banner, SVG."""
    u = url.lower()
    if re.search(r"emoji|gravatar|spinner|1x1|doubleclick|facebook\.com/tr|googletagmanager|wp-content/themes|\.svg(\?|$)|/static/images/|donate|dona-modali|sprite|pixel\.", u):
        return True
    if "/uploads/" in u: return False
    return bool(re.search(r"(^|[-_/.])(logos?|icons?|avatars?|placeholder|banner)\d*([-_./]|$)", u))

def _chiave_immagine(url):
    u = url.split("?")[0].lower()
    return re.sub(r"-\d+x\d+(?=\.\w+$)", "", u)  # WordPress: foto-300x200.jpg e foto.jpg sono la stessa

def _src_da_tag(tag):
    # srcset (la versione più grande) > attributi lazy-load > src, che spesso è la miniatura
    srcset = tag.get("srcset") or tag.get("data-srcset")
    if srcset:
        migliore, peso = None, -1
        for parte in srcset.split(","):
            pezzi = parte.strip().split()
            if not pezzi or pezzi[0].startswith("data:"): continue
            m = re.match(r"(\d+)w", pezzi[1]) if len(pezzi) > 1 else None
            w = int(m.group(1)) if m else 0
            if w >= peso: migliore, peso = pezzi[0], w
        if migliore: return migliore
    for attr in ("data-src", "data-lazy-src", "data-original", "src"):
        val = tag.get(attr)
        if val and not val.startswith("data:"): return val
    return None

def normalizza_url_immagine(url):
    """CDN che avvolgono l'originale (es. Substack: .../fetch/w_1456/https%3A%2F%2Fbucket.s3...jpeg,
    spesso con 403 fuori dal sito): usa direttamente l'URL originale incorporato."""
    m = re.search(r"/(https?%3A%2F%2F.+)$", url, re.I)
    return urllib.parse.unquote(m.group(1)) if m else url

def estrai_immagini(html, base_url, og=True, limite=MAX_IMMAGINI):
    """Immagini del corpo dell'articolo, in ordine (prima og:image se richiesto),
    senza loghi/icone/pixel e senza duplicati."""
    if isinstance(html, bytes): html = html.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html or "", "html.parser")
    trovate, posizione = [], {}

    def aggiungi(src):
        if not src: return
        url = normalizza_url_immagine(urllib.parse.urljoin(base_url or "", src.strip()))
        if not url.startswith("http") or immagine_scartata(url): return
        k = _chiave_immagine(url)
        if k in posizione:
            # stessa foto già vista: tieni la versione senza suffisso -LxA (l'originale, non la miniatura)
            i = posizione[k]
            if re.search(r"-\d+x\d+\.\w+$", trovate[i].split("?")[0]) and not re.search(r"-\d+x\d+\.\w+$", url.split("?")[0]):
                trovate[i] = url
            return
        posizione[k] = len(trovate); trovate.append(url)

    if og:
        meta = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "twitter:image"})
        if meta: aggiungi(meta.get("content"))
    radice = soup.find("article") or soup.select_one(".entry-content, .post-content, .article-content, .article__body, main") or soup
    for tag in radice.find_all("img"):
        if tag.find_parent(["nav", "header", "footer", "aside", "noscript"]): continue
        piccolo = False
        for dim in ("width", "height"):
            m = re.match(r"\d+", str(tag.get(dim, "")))
            if m and int(m.group()) < 120: piccolo = True
        if piccolo: continue
        aggiungi(_src_da_tag(tag))
        if len(trovate) >= limite: break
    return trovate[:limite]

def immagini_markdown(testo, limite=MAX_IMMAGINI):
    """Immagini ![alt](url) nel markdown restituito da Jina Reader."""
    risultato = []
    for u in re.findall(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", testo):
        u = normalizza_url_immagine(u)
        if not immagine_scartata(u) and u not in risultato: risultato.append(u)
    return risultato[:limite]

def pulisci_markdown(testo):
    """Toglie immagini e URL dei link dal markdown di Jina: nel testo da riassumere sono solo rumore."""
    testo = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", testo)
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", testo)

def immagini_da_pagina(link):
    """(immagini, pagina_letta): scarica la pagina dell'articolo e ne estrae le immagini;
    se il sito blocca il download ripiega su Jina (browser reale)."""
    contenuto, _ = scarica_bypass(link)
    if contenuto and not BLOCCO_ANTIBOT.search(contenuto[:3000].decode("utf-8", errors="ignore")):
        return estrai_immagini(contenuto, link), True
    try:
        res = requests.get(f"https://r.jina.ai/{link}", headers=HEADERS_JINA, timeout=20)
        if res.status_code == 200 and not BLOCCO_ANTIBOT.search(res.text[:3000]):
            return immagini_markdown(res.text), True
    except Exception as e:
        print(f"    [JINA] {link} -> {type(e).__name__}: {e}", flush=True)
    return [], False

def immagine_utilizzabile(url, link_articolo):
    """URL da mettere nel feed: l'originale se si carica anche da un altro sito
    (senza Referer del sito di origine), altrimenti una copia ospitata su Pages.
    None se l'immagine è un pixel/file minuscolo."""
    try:
        r = requests.get(url, headers={**HEADERS, "Referer": FEED_SITE}, timeout=15, stream=True)
        tipo = r.headers.get("Content-Type", "").lower()
        peso = int(r.headers.get("Content-Length", "0") or 0)
        ok = r.status_code == 200 and tipo.startswith("image/")
        r.close()
        if ok:
            return None if 0 < peso < 3000 else url
    except Exception:
        pass
    ospitata = ospita_immagine(url, link_articolo)
    return ospitata  # se anche il download fallisce resta l'URL originale (può funzionare per il lettore)

def immagini_per_feed(candidate, link_articolo):
    finali = []
    for u in candidate[:MAX_IMMAGINI]:
        v = immagine_utilizzabile(u, link_articolo)
        if v and v not in finali: finali.append(v)
    return finali

MODELLO_GROQ = "openai/gpt-oss-120b"
TPM_LIMITE = 7000  # tetto gratuito Groq ~8000 token/minuto, con un po' di margine
CARATTERI_PER_PARTE = 12000
MAX_CARATTERI_ARTICOLO = 60000
_finestra_token = []

def _attendi_tpm(stimati):
    """Rispetta il tetto di token al minuto: aspetta finché la richiesta ci sta."""
    while True:
        ora = time.time()
        _finestra_token[:] = [(t, n) for t, n in _finestra_token if ora - t < 60]
        if not _finestra_token or sum(n for _, n in _finestra_token) + stimati <= TPM_LIMITE:
            break
        time.sleep(max(1, 60 - (ora - _finestra_token[0][0]) + 0.5))
    _finestra_token.append((time.time(), stimati))

def chiama_groq(prompt_sistema, prompt_utente, max_tokens):
    if not client: return None
    stimati = min((len(prompt_sistema) + len(prompt_utente)) // 3 + max_tokens, TPM_LIMITE)
    for tentativo in range(4):
        try:
            _attendi_tpm(stimati)
            completion = client.chat.completions.create(
                model=MODELLO_GROQ,
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_utente}
                ],
                temperature=0.2,
                max_tokens=max_tokens
            )
            return (completion.choices[0].message.content or "").strip() or None
        except Exception as e:
            print(f"    [Groq Fallito] {e}", flush=True)
            m = re.search(r"try again in (?:(\d+)m)?(\d+(?:\.\d+)?)(ms|s)", str(e))
            attesa = 15
            if m:
                attesa = (int(m.group(1) or 0) * 60 + float(m.group(2))) / (1000 if m.group(3) == "ms" else 1) + 1
            time.sleep(min(attesa, 90))
    return None

def dividi_testo(testo, max_car):
    """Divide il testo in parti di al massimo max_car caratteri, spezzando a fine frase."""
    parti, corrente = [], ""
    for frase in re.split(r"(?<=[.!?])\s+|\n+", testo):
        while len(frase) > max_car:
            if corrente: parti.append(corrente); corrente = ""
            parti.append(frase[:max_car]); frase = frase[max_car:]
        if corrente and len(corrente) + len(frase) + 1 > max_car:
            parti.append(corrente); corrente = ""
        corrente = f"{corrente} {frase}".strip()
    if corrente: parti.append(corrente)
    return parti

def genera_sintesi_e_traduzione(titolo, fonte, testo, traduci=True):
    if not client: return None, None
    prompt_sistema = """Sei un analista editoriale. Se il testo originale è in inglese, TRADUCILO IN ITALIANO sia il titolo che il testo.
REGOLE TASSATIVE:
1. LINGUA: Esclusivamente ITALIANO.
2. FORMATO DI RISPOSTA: Devi rispondere ESCLUSIVAMENTE con questo formato esatto:
TITOLO_TRADOTTO: [Inserisci qui il titolo tradotto]
---
[Inserisci qui il riassunto HTML con <p>, <strong>, <ol>, <li>]
3. LUNGHEZZA: Adatta la densità. Fornisci sempre 3-5 PUNTI CHIAVE alla fine del riassunto.
4. FEDELTÀ: riporta SOLO ciò che è scritto nel testo. Non aggiungere fatti, giudizi, nomi, date o numeri che non compaiono; se un'informazione manca, omettila. Mantieni esatti nomi propri, cifre e citazioni. Non inserire opinioni o interpretazioni tue."""

    if not traduci:
        prompt_sistema = prompt_sistema.replace(
            "Se il testo originale è in inglese, TRADUCILO IN ITALIANO sia il titolo che il testo.",
            "Il testo è già in italiano: NON tradurlo, lavora sul testo originale così com'è.").replace(
            "TITOLO_TRADOTTO: [Inserisci qui il titolo tradotto]", "TITOLO_TRADOTTO: [Ripeti qui il titolo originale, invariato]")

    testo = testo[:MAX_CARATTERI_ARTICOLO]
    if len(testo) > CARATTERI_PER_PARTE:
        # Articolo lungo: riassunto per parti (ognuna sotto il tetto di token/minuto
        # di Groq) e poi riassunto finale dei riassunti parziali.
        parti = dividi_testo(testo, CARATTERI_PER_PARTE)
        # Saggio molto lungo (3+ parti, ~4.000+ parole): riassunti parziali e finale più ampi.
        approfondito = len(parti) >= 3
        parole = "250-350" if approfondito else "150-250"
        parziali = []
        for n, parte in enumerate(parti, 1):
            print(f"    [PARTI] riassunto parte {n}/{len(parti)}", flush=True)
            ris = chiama_groq(
                f"Riassumi in ITALIANO, in modo fedele, questa parte di un articolo ({parole} parole): segui lo sviluppo dell'argomentazione, gli esempi e le tesi. Mantieni esatti nomi propri, cifre e citazioni; non aggiungere nulla che non sia nel testo. Solo testo semplice, nessun commento.",
                f"PARTE {n} DI {len(parti)} DELL'ARTICOLO \"{titolo}\":\n{parte}", 1000 if approfondito else 700)
            if not ris: return None, None
            parziali.append(f"[Parte {n}/{len(parti)}] {ris}")
        if approfondito:
            prompt_sistema += "\n5. SAGGIO LUNGO: scrivi un riassunto approfondito di circa 600-900 parole che segua lo sviluppo dell'argomentazione dall'inizio alla fine (tesi, passaggi, esempi, conclusione), poi 4-6 PUNTI CHIAVE."
        prompt_utente = (f"FONTE: {fonte}\nTITOLO ORIGINALE: {titolo}\n"
                         f"L'articolo è lungo: qui sotto i riassunti parziali in ordine. Componi un unico riassunto coerente e completo.\nTESTO:\n" + "\n\n".join(parziali))
    else:
        prompt_utente = f"FONTE: {fonte}\nTITOLO ORIGINALE: {titolo}\nTESTO:\n{testo}"

    ris = chiama_groq(prompt_sistema, prompt_utente, 3000 if len(testo) > 2 * CARATTERI_PER_PARTE else 1800)
    if not ris: return None, None
    ris = ris.replace("```html", "").replace("```", "").strip()
    parts = None
    if ris.startswith("TITOLO_TRADOTTO") and "---" in ris:
        parts = ris.split("---", 1)
    if parts:
        t = parts[0].replace("TITOLO_TRADOTTO:", "").strip()
        s = parts[1].strip()
        return (t or titolo), s
    return titolo, ris

def genera_sintesi_breve(testo, fonte):
    """Come genera_sintesi_e_traduzione ma senza traduzione: per fonti già in
    italiano (es. un canale Telegram), dove serve solo applicare sintesi e
    punti chiave, anche a un messaggio corto."""
    if not client: return None
    prompt_sistema = """Sei un analista editoriale italiano. Il testo è già in italiano: NON tradurlo, lavora sul testo originale così com'è.
REGOLE TASSATIVE:
1. Fornisci una sintesi breve (anche solo 2-3 frasi se il testo originale è corto) e SEMPRE un elenco di 2-4 PUNTI CHIAVE, anche per messaggi molto brevi.
2. FORMATO: Solo codice HTML (<p>, <strong>, <ol>, <li>). Nessun markdown.
3. FEDELTÀ: riporta SOLO ciò che è scritto nel testo. Non aggiungere fatti, nomi, date o numeri che non compaiono. Non inserire opinioni tue."""

    ris = chiama_groq(prompt_sistema, f"FONTE: {fonte}\nTESTO:\n{testo[:CARATTERI_PER_PARTE]}", 800)
    return ris.replace("```html", "").replace("```", "").strip() if ris else None

def componi_html_finale(fonte, categoria, colore, contenuto, link, immagini):
    """Scheda finale: copertina, riassunto, poi le altre immagini dell'articolo."""
    def tag(u): return f'<p><img src="{escape(u)}" referrerpolicy="no-referrer" style="max-width:100%"></p>'
    immagini = immagini or []
    copertina = tag(immagini[0]) if immagini else ""
    galleria = "".join(tag(u) for u in immagini[1:])
    return f"""
    <p><strong>FONTE:</strong> {fonte} | <strong>Ambito:</strong> <em>{categoria}</em></p>
    <hr>
    {copertina}
    {contenuto}
    {galleria}
    <hr>
    <p><a href="{escape(url_sicuro(link))}">Leggi originale su {fonte} &rarr;</a></p>
    """

def aggiungi_immagini_html(html, immagini):
    """Inserisce copertina e galleria in una scheda già composta (senza immagini)."""
    testa, sep1, resto = html.partition("<hr>")
    mezzo, sep2, coda = resto.rpartition("<hr>")
    if not (sep1 and sep2): return html
    def tag(u): return f'<p><img src="{escape(u)}" referrerpolicy="no-referrer" style="max-width:100%"></p>'
    return f"{testa}<hr>\n    {tag(immagini[0])}\n{mezzo}{''.join(tag(u) for u in immagini[1:])}\n    <hr>{coda}"

def elabora_voce(db, f, link, titolo, testo_grezzo="", img_url=None):
    link = (link or "").strip()
    titolo = (titolo or "Senza Titolo").strip()
    item_id = f"{VERSIONE_CACHE}_{link or titolo}"

    if item_id in db:
        return db[item_id]

    print(f"Elaborazione: {titolo[:40]}...", flush=True)

    candidate = ([img_url] if img_url else []) + estrai_immagini(testo_grezzo, link, og=False)
    pagina_letta = False

    soup = BeautifulSoup(testo_grezzo, "html.parser")
    for tag in soup(["script", "style"]): tag.decompose()
    testo_pulito = " ".join(soup.get_text().split())

    testo_feed = testo_pulito
    if len(testo_pulito) < 400 and link:
        contenuto, _ = scarica_bypass(link)
        if contenuto:
            s = BeautifulSoup(contenuto, "html.parser")
            testo_estratto = " ".join(p.get_text() for p in s.find_all("p"))
            if len(testo_estratto) > len(testo_pulito): testo_pulito = testo_estratto
            if not BLOCCO_ANTIBOT.search(contenuto[:3000].decode("utf-8", errors="ignore")):
                candidate = estrai_immagini(contenuto, link) + candidate
                pagina_letta = True

        if len(testo_pulito) < 400:
            # Se anche l'HTML diretto/proxy non basta (spesso un blocco 403),
            # Jina esegue un browser reale e restituisce il testo già
            # renderizzato: meglio un testo "sporco" (con qualche menu/nav
            # residuo) che nessun testo, che lascerebbe Groq senza nulla da
            # sintetizzare.
            try:
                res = requests.get(f"https://r.jina.ai/{link}", headers=HEADERS_JINA, timeout=20)
                if res.status_code == 200 and len(res.text) > len(testo_pulito):
                    testo_pulito = pulisci_markdown(res.text)
                    if not pagina_letta and not BLOCCO_ANTIBOT.search(res.text[:3000]):
                        candidate += immagini_markdown(res.text)
                        pagina_letta = True
                elif res.status_code != 200:
                    print(f"    [JINA] {link} -> HTTP {res.status_code}", flush=True)
            except Exception as e:
                print(f"    [JINA] {link} -> {type(e).__name__}: {e}", flush=True)

    if not candidate and link and not pagina_letta:
        candidate, pagina_letta = immagini_da_pagina(link)

    # elimina duplicati mantenendo l'ordine (copertina per prima)
    viste, uniche = set(), []
    for u in candidate:
        k = _chiave_immagine(u)
        if k not in viste: viste.add(k); uniche.append(u)
    immagini = immagini_per_feed(uniche, link)

    if BLOCCO_ANTIBOT.search(testo_pulito[:3000]):
        print(f"    [BLOCCO] {link} -> pagina anti-bot, uso solo il testo del feed", flush=True)
        testo_pulito = testo_feed

    if len(testo_pulito) < 150:
        titolo_tradotto, sintesi = titolo, None
    else:
        titolo_tradotto, sintesi = genera_sintesi_e_traduzione(titolo, f["nome"], testo_pulito, traduci=not f.get("italiano"))

    trad_ok = True
    if not sintesi:
        trad_ok = False
        titolo_tradotto = titolo
        sintesi = f"<p><em>Sintesi non disponibile.</em></p><p>{escape(testo_pulito[:800])}...</p>"

    html = componi_html_finale(f["nome"], f["categoria"], f["colore"], sintesi, link, immagini)
    record = {"id": item_id, "title": f"{f['nome']}: {titolo_tradotto}", "link": link, "html_content": html, "published": datetime.now(timezone.utc).isoformat(), "image_url": immagini[0] if immagini else None, "img_v": 1}

    if trad_ok: db[item_id] = record
    time.sleep(8)
    return record

def _diagnostica_immagini(testo, origine, link):
    """Diagnostica: stampa in che forma la pagina offre le immagini (varianti di
    dimensione, __NEXT_DATA__), per capire se esistono versioni più grandi."""
    if isinstance(testo, bytes): testo = testo.decode("utf-8", errors="ignore")
    urls = set(re.findall(r"https?://[^\s\"'<>)\\]+?\.(?:jpe?g|png|webp)", testo))
    forme = collections.Counter(re.sub(r"[0-9a-f]{16,}", "<h>", re.sub(r"/\d+/", "/<n>/", u)) for u in urls)
    print(f"    [DIAG] {origine} {link}: {len(urls)} URL immagine; next_data={'__NEXT_DATA__' in testo}", flush=True)
    for forma, n in forme.most_common(8): print(f"    [DIAG]   {n}x {forma[:160]}", flush=True)

def trova_immagini_progetto(link, limite_immagini=10):
    """Immagini di una pagina-progetto (es. una mostra di Contemporary Art Daily):
    prima l'HTML statico, poi Jina (browser reale) per i siti che caricano le
    immagini via JavaScript. Gli asset del sito (loghi, icone) stanno sul suo
    dominio, i contenuti su un CDN: le immagini del dominio vengono scartate."""
    host_sito = urllib.parse.urlparse(link).netloc

    def valide(urls):
        return [u for u in urls if not immagine_scartata(u) and urllib.parse.urlparse(u).netloc != host_sito]

    immagini = []
    contenuto, _ = scarica_bypass(link)
    if contenuto:
        _diagnostica_immagini(contenuto, 'html', link)
        immagini = valide(estrai_immagini(contenuto, link, og=False, limite=60))
    if not immagini:
        try:
            res = requests.get(f"https://r.jina.ai/{link}", headers=HEADERS_JINA, timeout=20)
            if res.status_code == 200 and len(res.text) > 200:
                _diagnostica_immagini(res.text, 'jina', link)
                immagini = valide(immagini_markdown(res.text, limite=60))
                if not immagini:
                    print(f"    [JINA] {link} -> nessuna immagine riconosciuta", flush=True)
            else:
                print(f"    [JINA] {link} -> HTTP {res.status_code}", flush=True)
        except Exception as e:
            print(f"    [JINA] {link} -> {type(e).__name__}: {e}", flush=True)
    return immagini[:limite_immagini]

def elabora_voce_immagini(db, f, link, titolo, limite_immagini=10):
    """Come elabora_voce ma senza sintesi/traduzione Groq: compone la voce
    con le sole immagini trovate nella pagina dell'articolo."""
    link = (link or "").strip()
    titolo = (titolo or "Senza Titolo").strip()
    item_id = f"{VERSIONE_CACHE}_{link or titolo}"

    if item_id in db:
        return db[item_id]

    print(f"Elaborazione: {titolo[:40]}...", flush=True)
    immagini = trova_immagini_progetto(link, limite_immagini) if link else []
    corpo = "" if immagini else "<p><em>Nessuna immagine trovata.</em></p>"
    html = componi_html_finale(f["nome"], f["categoria"], f["colore"], corpo, link, immagini)
    record = {"id": item_id, "title": f"{f['nome']}: {titolo}", "link": link, "html_content": html, "published": datetime.now(timezone.utc).isoformat(), "image_url": immagini[0] if immagini else None, "img_tentativi": 0 if immagini else 1}
    db[item_id] = record
    time.sleep(2)
    return record

def ripara_immagini_progetti(db, fonte, max_per_giro=20):
    """Rifà la ricerca delle immagini per le voci di una fonte solo-immagini che
    ne sono rimaste senza (es. contenevano soltanto il logo del sito)."""
    fatte = 0
    for v in db.values():
        if not v["title"].startswith(f"{fonte['nome']}: ") or not v.get("link"): continue
        if immagini_valide_html(v["html_content"], v["link"]) or v.get("img_tentativi", 0) >= 3: continue
        if fatte >= max_per_giro: break
        fatte += 1
        immagini = trova_immagini_progetto(v["link"])
        if not immagini:
            v["img_tentativi"] = v.get("img_tentativi", 0) + 1
            continue
        v["html_content"] = componi_html_finale(fonte["nome"], fonte["categoria"], fonte["colore"], "", v["link"], immagini)
        v["image_url"] = immagini[0]
        print(f"    [IMG] {v['title'][:50]} -> {len(immagini)} immagini ritrovate", flush=True)

def recupera_messaggi_telegram(url, limite=3):
    """Legge l'anteprima web pubblica di un canale Telegram (https://t.me/s/<canale>),
    che non richiede bot né API key, ed estrae gli ultimi messaggi con testo,
    link diretto e un'eventuale immagine allegata."""
    contenuto, esito = scarica_bypass(url)
    if not contenuto:
        print(f"    [TELEGRAM] {url} -> irraggiungibile ({esito})", flush=True)
        return []

    s = BeautifulSoup(contenuto, "html.parser")
    messaggi = []
    for blocco in s.select("div.tgme_widget_message"):
        post_id = blocco.get("data-post")
        testo_tag = blocco.select_one(".tgme_widget_message_text")
        if not post_id or not testo_tag: continue
        testo = testo_tag.get_text("\n").strip()
        if len(testo) < 10: continue

        img_urls = []
        for img_tag in blocco.select(".tgme_widget_message_photo_wrap"):
            m = re.search(r"url\('([^']+)'\)", img_tag.get("style", ""))
            if m and m.group(1) not in img_urls: img_urls.append(m.group(1))

        messaggi.append((testo, f"https://t.me/{post_id}", img_urls))

    if not messaggi:
        print(f"    [TELEGRAM] {url} -> scaricato ({esito}) ma nessun messaggio riconosciuto", flush=True)
    return messaggi[-limite:]  # la pagina elenca i messaggi dal più vecchio al più recente

def elabora_messaggio_telegram(db, f, testo_originale, link, img_urls=None):
    item_id = f"{VERSIONE_CACHE}_{link}"
    if item_id in db:
        return db[item_id]

    titolo_breve = " ".join(testo_originale.split())[:60]
    print(f"Elaborazione: {titolo_breve[:40]}...", flush=True)

    sintesi = genera_sintesi_breve(testo_originale, f["nome"])
    trad_ok = True
    if not sintesi:
        trad_ok = False
        sintesi = f"<p>{escape(testo_originale)}</p>"

    immagini = immagini_per_feed(img_urls or [], link)
    html = componi_html_finale(f["nome"], f["categoria"], f["colore"], sintesi, link, immagini)
    record = {"id": item_id, "title": f"{f['nome']}: {titolo_breve}", "link": link, "html_content": html, "published": datetime.now(timezone.utc).isoformat(), "image_url": immagini[0] if immagini else None, "img_v": 1}

    if trad_ok: db[item_id] = record
    time.sleep(5)
    return record

PAGINE_DIR = "articoli"
IMMAGINI_DIR = os.path.join(PAGINE_DIR, "img")
IMMAGINI_USATE = set()

def ospita_immagine(url_originale, referer):
    """Scarica un'immagine e la ripubblica su Pages: molti CDN bloccano il
    hotlinking (Referer diverso) e in reader come Bulletin l'immagine non si
    carica. Se il download fallisce restituisce l'URL originale."""
    if not url_originale or url_originale.startswith(FEED_SITE): return url_originale
    base = hashlib.sha1(url_originale.encode()).hexdigest()[:16]
    for ext in ("jpg", "png", "webp", "gif"):
        if os.path.exists(os.path.join(IMMAGINI_DIR, f"{base}.{ext}")):
            IMMAGINI_USATE.add(f"{base}.{ext}")
            return f"{FEED_SITE}{IMMAGINI_DIR}/{base}.{ext}"
    try:
        res = scraper.get(url_originale, headers={"Referer": referer}, timeout=20)
        tipo = res.headers.get("Content-Type", "").lower()
        if res.status_code != 200 or not tipo.startswith("image/") or len(res.content) > 8_000_000:
            print(f"    [IMG] {url_originale} -> HTTP {res.status_code} {tipo}", flush=True)
            return url_originale
        ext = "png" if "png" in tipo else "webp" if "webp" in tipo else "gif" if "gif" in tipo else "jpg"
        nome = f"{base}.{ext}"
        os.makedirs(IMMAGINI_DIR, exist_ok=True)
        with open(os.path.join(IMMAGINI_DIR, nome), "wb") as f:
            f.write(res.content)
        IMMAGINI_USATE.add(nome)
        return f"{FEED_SITE}{IMMAGINI_DIR}/{nome}"
    except Exception as e:
        print(f"    [IMG] {url_originale} -> {type(e).__name__}: {e}", flush=True)
        return url_originale

def ospita_immagini_item(item):
    item = dict(item)
    referer = item["link"]
    item["html_content"] = re.sub(
        r'(<img\b[^>]*?\bsrc=")([^"]+)(")',
        lambda m: m.group(1) + ospita_immagine(m.group(2), referer) + m.group(3),
        item["html_content"])
    if item.get("image_url"):
        item["image_url"] = ospita_immagine(item["image_url"], referer)
    return item

def url_pagina(item_id):
    return f"{FEED_SITE}{PAGINE_DIR}/{hashlib.sha1(item_id.encode()).hexdigest()[:16]}.html"

PAGINE_SCRITTE = set()

PAGINA_STILE = (
    "<style>"
    ":root{color-scheme:light dark}"
    "body{max-width:46rem;margin:0 auto;padding:1rem 1.1rem 3rem;font:18px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Georgia,serif}"
    "h1{font-size:1.5rem;line-height:1.25}h2{font-size:1.2rem;margin-top:1.8rem}"
    "img{max-width:100%;height:auto;border-radius:6px}"
    "a.zoom{display:block;cursor:zoom-in}"
    "a.originale{display:inline-block;padding:.65rem .95rem;border:1px solid currentColor;border-radius:9px;font-weight:600;text-decoration:none}"
    "#lb{display:none;position:fixed;top:0;left:0;right:0;bottom:0;z-index:99;background:rgba(0,0,0,.95);align-items:center;justify-content:center;cursor:zoom-out}"
    "#lb.on{display:flex}"
    "#lb img{max-width:100vw;max-height:100vh;border-radius:0;object-fit:contain}"
    "</style>"
)

PAGINA_SCRIPT = (
    "<script>(function(){var lb=document.getElementById('lb'),big=lb.querySelector('img');"
    "function chiudi(){lb.className='';big.removeAttribute('src');}"
    "document.addEventListener('click',function(e){"
    "var a=e.target.closest?e.target.closest('a.zoom'):null;"
    "if(a){e.preventDefault();big.src=a.href;lb.className='on';}"
    "else if(lb.className==='on'){chiudi();}});"
    "document.addEventListener('keydown',function(e){if(e.key==='Escape')chiudi();});})();</script>"
)

def scrivi_pagina(item):
    """Pagina HTML statica con la sintesi: alcuni reader (es. Bulletin) ignorano
    il contenuto del feed e scaricano la pagina del link, quindi il link
    dell'item punta a questa pagina invece che all'articolo originale. In cima
    c'è il pulsante per l'articolo integrale; toccando un'immagine si apre a tutto schermo."""
    contenuto = pulisci_immagini_html(item["html_content"]).strip()
    img = item.get("image_url")
    if img and immagine_scartata(img): img = None
    immagine = ""
    if img and img not in unescape(contenuto):
        immagine = f'<p><img src="{escape(img)}" alt="" style="max-width:100%;height:auto"></p>'
    titolo = escape(item["title"])
    link = item.get("link") or ""
    banner = ""
    if link and not item.get("digest"):
        host = urllib.parse.urlparse(link).netloc
        etichetta = "Apri il post su Telegram" if host == "t.me" else f"Leggi l'articolo integrale su {escape(host)}"
        banner = f'<p><a class="originale" href="{escape(url_sicuro(link))}" target="_blank" rel="noopener">{etichetta} &rarr;</a></p>'
        if host != "t.me":
            banner += f'<p><small><a href="https://r.jina.ai/{escape(url_sicuro(link))}" target="_blank" rel="noopener">Se non si apre: versione solo testo</a></small></p>'
    corpo = incornicia_immagini(immagine + contenuto)
    html = (f'<!doctype html><html lang="it"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="referrer" content="no-referrer"><title>{titolo}</title>{PAGINA_STILE}</head>'
            f'<body><article><h1>{titolo}</h1>{banner}{corpo}</article>'
            f'<div id="lb"><img alt=""></div>{PAGINA_SCRIPT}</body></html>')
    nome = url_pagina(item["id"]).rsplit("/", 1)[-1]
    PAGINE_SCRITTE.add(nome)
    with open(os.path.join(PAGINE_DIR, nome), "w", encoding="utf-8") as f:
        f.write(html)

def estratto_testo(item):
    """Testo semplice della sintesi per il campo <description>: alcuni reader
    (es. Bulletin) mostrano il <description> come testo puro, quindi li' non
    deve esserci HTML (l'HTML completo va in content:encoded)."""
    soup = BeautifulSoup(item["html_content"], "html.parser")
    righe = []
    for el in soup.find_all(["p", "li"]):
        t = " ".join(el.get_text(" ", strip=True).split())
        if not t or t.startswith("FONTE:"): continue
        if el.find("a") and "originale" in t.lower(): continue  # riga "Leggi/Vedi originale su ..."
        righe.append(("• " if el.name == "li" else "") + t)
    if righe: return "\n\n".join(righe)
    n = len(soup.find_all("img"))
    return f"{n} immagini" if n else item["title"]

VOCI_PER_FONTE = 3
MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
           "agosto", "settembre", "ottobre", "novembre", "dicembre"]

def finestra_digest(dt):
    """Finestra a cui appartiene dt: lun-mer esce giovedì, gio-dom esce lunedì (UTC)."""
    giorno = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if dt.weekday() <= 2:
        inizio = giorno - timedelta(days=dt.weekday())
        return inizio, inizio + timedelta(days=3)
    inizio = giorno - timedelta(days=dt.weekday() - 3)
    return inizio, inizio + timedelta(days=4)

DIGEST_REVISIONE_DA = datetime(2026, 10, 12, tzinfo=timezone.utc)  # i riepiloghi da questa data erano rimasti con il solo logo: nuovo GUID

def html_mostra(nome_fonte, titolo, link, immagini):
    corpo = f"<h2>{escape(titolo)}</h2>"
    corpo += "".join(f'<p><img src="{escape(u)}" style="max-width:100%;height:auto"></p>' for u in immagini)
    return corpo + f'<p><a href="{escape(url_sicuro(link))}">Vedi originale su {escape(nome_fonte)} &rarr;</a></p>'

def digest_immagini(db, nome_fonte, ora=None, max_digest=8, img_per_mostra=3):
    """Raggruppa le voci di una fonte solo-immagini in riepiloghi due volte a
    settimana (una voce per finestra conclusa), con poche immagini per mostra."""
    ora = ora or datetime.now(timezone.utc)
    prefisso = f"{nome_fonte}: "
    finestre = {}
    for v in db.values():
        if not v["title"].startswith(prefisso): continue
        try: dt = datetime.fromisoformat(v["published"])
        except (KeyError, ValueError): continue
        inizio, fine = finestra_digest(dt)
        if fine <= ora: finestre.setdefault((inizio, fine), []).append(v)

    risultato = []
    for (inizio, fine), voci in sorted(finestre.items(), reverse=True)[:max_digest]:
        voci.sort(key=lambda x: x["published"])
        mostre = [(v["title"][len(prefisso):], v["link"], immagini_valide_html(v["html_content"], v["link"])[:img_per_mostra]) for v in voci]
        corpo = "<p>Mostre: " + "; ".join(escape(t) for t, _, _ in mostre) + "</p>"
        corpo += "".join(html_mostra(nome_fonte, t, l, im) for t, l, im in mostre)
        ultimo = fine - timedelta(days=1)
        if inizio.month == ultimo.month:
            periodo = f"dal {inizio.day} al {ultimo.day} {MESI_IT[ultimo.month - 1]}"
        else:
            periodo = f"dal {inizio.day} {MESI_IT[inizio.month - 1]} al {ultimo.day} {MESI_IT[ultimo.month - 1]}"
        risultato.append({
            "id": f"{VERSIONE_CACHE}_digest-{nome_fonte}-{inizio.date()}" + ("-r2" if inizio >= DIGEST_REVISIONE_DA else ""),
            "title": f"{nome_fonte}: mostre {periodo}",
            "link": voci[0]["link"],
            "html_content": corpo,
            "published": fine.isoformat(),
            "image_url": next((im[0] for _, _, im in mostre if im), None),
            "digest": True,
        })
    return risultato

def scrivi_pagine_cache(db, fonti_img):
    """Una pagina per ogni voce in cache: i reader conservano le voci vecchie e i
    loro link devono continuare a funzionare anche dopo che escono dal feed."""
    nomi_img = [f["nome"] for f in fonti_img]
    for v in db.values():
        item = dict(v)
        nome = next((n for n in nomi_img if v["title"].startswith(n + ": ")), None)
        if nome:
            # singola mostra di una fonte solo-immagini: titolo, link e prime 3 immagini
            immagini = immagini_valide_html(v["html_content"], v["link"])[:3]
            item["html_content"] = html_mostra(nome, v["title"][len(nome) + 2:], v["link"], immagini)
            item["image_url"] = immagini[0] if immagini else None
            item = ospita_immagini_item(item)
        scrivi_pagina(item)

def voci_recenti(db, articoli_giro, fonti, per_fonte):
    """Le ultime per_fonte voci di ogni fonte, dalla cache più quelle di questo giro."""
    tutte = dict(db)
    for a in articoli_giro: tutte[a["id"]] = a
    risultato = []
    for f in fonti:
        prefisso = f"{f['nome']}: "
        voci = sorted((a for a in tutte.values() if a["title"].startswith(prefisso)),
                      key=lambda x: x.get("published", ""), reverse=True)
        risultato += voci[:per_fonte]
    return risultato

def pulisci_immagini_html(html):
    """Toglie da una scheda (anche vecchia) le immagini che non sono contenuto
    (pixel, icone, loghi) e scarta il wrapper dei CDN che avvolgono l'originale."""
    def tag(m):
        src = unescape(m.group(1))
        if immagine_scartata(src): return ""
        nuovo = normalizza_url_immagine(src)
        return m.group(0).replace(m.group(1), escape(nuovo)) if nuovo != src else m.group(0)
    return re.sub(r'<img\b[^>]*?\bsrc="([^"]+)"[^>]*>', tag, html)

def completa_immagini(db, voci, max_per_giro=20):
    """Per le voci già in cache create prima del supporto alle immagini: recupera
    le immagini dell'articolo e le inserisce nella scheda, senza rifare il riassunto."""
    fatte = 0
    for v in voci:
        if v.get("img_v") or v.get("id") not in db or not v.get("link"): continue
        if v["link"].startswith("https://t.me/"):
            v["img_v"] = 1
            continue
        if fatte >= max_per_giro: break
        fatte += 1
        candidate, letta = immagini_da_pagina(v["link"])
        if not letta:
            v["img_tentativi"] = v.get("img_tentativi", 0) + 1
            if v["img_tentativi"] >= 2: v["img_v"] = 1
            continue
        v["html_content"] = pulisci_immagini_html(v["html_content"])
        presenti = {_chiave_immagine(u) for u in re.findall(r'src="([^"]+)"', unescape(v["html_content"]))}
        immagini = immagini_per_feed([u for u in candidate if _chiave_immagine(u) not in presenti], v["link"])
        if immagini: v["html_content"] = aggiungi_immagini_html(v["html_content"], immagini)
        v["image_url"] = (immagini or [None])[0] or next(iter(re.findall(r'src="([^"]+)"', unescape(v["html_content"]))), None)
        v["img_v"] = 1
        print(f"    [IMG] {v['title'][:50]} -> {len(immagini)} immagini aggiunte", flush=True)

def genera_feed(articoli, output_file, titolo, descrizione, ospita_img=False):
    # Fonti diverse possono convergere sullo stesso link (fallback condivisi,
    # o pagine che ripescano le stesse sezioni generiche di un sito): la
    # cache in quel caso restituisce lo stesso record due volte. Deduplica
    # per id prima di generare il feed.
    visti_id, articoli_unici = set(), []
    for a in articoli:
        if a["id"] in visti_id: continue
        visti_id.add(a["id"])
        articoli_unici.append(a)

    fg = FeedGenerator()
    fg.load_extension("media")
    fg.title(titolo)
    fg.link(href=FEED_SITE + output_file, rel="self", type="application/rss+xml")
    # feedgen usa come <link> del canale l'ULTIMO link aggiunto: il sito va per ultimo.
    fg.link(href=FEED_SITE, rel="alternate")
    fg.description(descrizione)
    fg.language("it")

    for item in sorted(articoli_unici, key=lambda x: x.get("published", ""), reverse=True)[:120]:
        if ospita_img: item = ospita_immagini_item(item)
        item = {**item, "html_content": pulisci_immagini_html(item["html_content"])}
        copertina = item.get("image_url")
        if copertina: copertina = normalizza_url_immagine(copertina)
        if copertina and immagine_scartata(copertina): copertina = None
        if copertina and copertina not in unescape(item["html_content"]):
            item["html_content"] = aggiungi_immagini_html(item["html_content"], [copertina])
        item["image_url"] = copertina
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        scrivi_pagina(item)
        fe.link(href=url_pagina(item["id"]))
        # Alcuni reader (es. Bulletin) mostrano il codice HTML come testo se il
        # contenuto non inizia direttamente con un tag: niente spazi/righe vuote iniziali.
        fe.content("<div>" + incornicia_immagini(item["html_content"].strip()) + "</div>", type="CDATA")
        fe.description(estratto_testo(item))
        if copertina:
            ext = copertina.split("?")[0].rsplit(".", 1)[-1].lower()
            tipo = {"png": "image/png", "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
            fe.enclosure(copertina, 0, tipo)
            fe.media.thumbnail({"url": copertina})
            fe.media.content({"url": copertina, "medium": "image", "type": tipo})
        # Senza pubDate esplicito, un reader (Feedly incluso) non ha modo di
        # sapere l'ordine cronologico reale e si affida all'ordine fisico nel
        # documento — che feedgen inverte di default (ogni add_entry() fa un
        # "prepend"), facendo apparire in fondo gli articoli più recenti.
        try:
            fe.pubDate(datetime.fromisoformat(item["published"]))
        except (KeyError, ValueError):
            pass
    fg.rss_file(output_file, pretty=True)


def main():
    db = carica_database()
    articoli = []

    for f in FONTI:
        if f.get("tipo") == "telegram":
            for testo, link, img_urls in recupera_messaggi_telegram(f["url"]):
                articoli.append(elabora_messaggio_telegram(db, f, testo, link, img_urls))
            continue

        if f.get("tipo") == "immagini":
            for titolo, link in recupera_articoli_pagina(f["url"], nome_fonte=f["nome"]):
                elabora_voce_immagini(db, f, link, titolo)
            continue

        if f.get("tipo") == "pagina":
            for titolo, link in recupera_articoli_pagina(f["url"], nome_fonte=f["nome"]):
                articoli.append(elabora_voce(db, f, link, titolo))
            continue

        parsed = recupera_feed_xml(f["url"], f.get("fallback"))
        if (not hasattr(parsed, "entries") or not parsed.entries) and f.get("pagina_fallback"):
            print(f"    [FEED] {f['nome']}: nessun feed RSS utilizzabile, ripiego sulla pagina", flush=True)
            for titolo, link in recupera_articoli_pagina(f["pagina_fallback"], nome_fonte=f["nome"]):
                articoli.append(elabora_voce(db, f, link, titolo))
            continue
        if not hasattr(parsed, "entries"): continue

        entries = [e for e in parsed.entries if not f.get("solo_link") or f["solo_link"] in e.get("link", "")]
        for entry in entries[:2]:
            link = entry.get("link", "")
            titolo = entry.get("title", "Senza Titolo")
            testo_grezzo = entry.get("content", [{}])[0].get("value", entry.get("summary", ""))
            img_url = entry.media_content[0].get("url") if "media_content" in entry and len(entry.media_content) > 0 else None
            articoli.append(elabora_voce(db, f, link, titolo, testo_grezzo, img_url))

    fonti_std = [f for f in FONTI if f.get("tipo") != "immagini"]
    fonti_img = [f for f in FONTI if f.get("tipo") == "immagini"]
    voci_std = voci_recenti(db, articoli, fonti_std, VOCI_PER_FONTE)
    completa_immagini(db, voci_std)
    for f in fonti_img: ripara_immagini_progetti(db, f)
    salva_database(db)

    os.makedirs(IMMAGINI_DIR, exist_ok=True)
    # Pagine di TUTTE le voci in cache e di tutti i riepiloghi, non solo di quelle ancora
    # nel feed: i reader conservano le voci vecchie e i loro link non devono dare 404.
    scrivi_pagine_cache(db, fonti_img)
    digest_tutti = [d for f in fonti_img for d in digest_immagini(db, f["nome"], max_digest=None)]
    for d in digest_tutti: scrivi_pagina(ospita_immagini_item(d))
    # Il feed si costruisce da cache + voci di questo giro (non solo da quelle
    # appena scaricate): se un sito blocca o va in timeout in un giro, le sue
    # ultime voci restano nel feed invece di sparire.
    genera_feed(voci_std, FEED_OUTPUT, "Rassegna Personale Unificata", "Sintesi IA e proxy anti-blocco.")
    genera_feed(digest_tutti[:8], FEED_OUTPUT_IMMAGINI, "Contemporary Art Daily", "Riepilogo di immagini due volte a settimana, senza sintesi né traduzione.", ospita_img=True)

    for nome in os.listdir(PAGINE_DIR):
        if nome.endswith(".html") and nome not in PAGINE_SCRITTE: os.remove(os.path.join(PAGINE_DIR, nome))
    # Elimina le copie ospitate non più usate da nessuna voce in cache.
    usate = set(IMMAGINI_USATE)
    for v in db.values(): usate.update(re.findall(rf"{IMMAGINI_DIR}/([\w.]+)", v.get("html_content", "")))
    for nome in os.listdir(IMMAGINI_DIR):
        if nome not in usate: os.remove(os.path.join(IMMAGINI_DIR, nome))

if __name__ == "__main__":
    main()
