import os
import re
import json
import time
import urllib.parse
from datetime import datetime, timezone
import requests
import cloudscraper
import feedparser
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from groq import Groq

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

    {"nome": "Contemporary Art Daily", "tipo": "immagini", "url": "https://www.contemporaryartdaily.com", "categoria": "Arte Contemporanea", "colore": "#18181b"},
]

DATABASE_FILE = "feed_database.json"
FEED_OUTPUT = "feed_sintesi.xml"
FEED_SITE = "https://lorenzoromani367.github.io/NewsFeed/"
VERSIONE_CACHE = "v18"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

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
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def salva_database(db):
    with open(DATABASE_FILE, "w", encoding="utf-8") as f: json.dump(db, f, ensure_ascii=False, indent=2)

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

def genera_sintesi_e_traduzione(titolo, fonte, testo):
    if not client: return None
    prompt_sistema = """Sei un analista editoriale. Se il testo originale è in inglese, TRADUCILO IN ITALIANO.
REGOLE TASSATIVE:
1. LINGUA: Esclusivamente ITALIANO.
2. LUNGHEZZA PROPORZIONALE: Adatta la densità. Testo breve: 1 paragrafo critico. Saggio lungo: 3-4 paragrafi critici. Fornisci sempre 3-5 PUNTI CHIAVE.
3. FORMATO: Solo codice HTML (<p>, <strong>, <ol>, <li>). Nessun markdown."""

    prompt_utente = f"FONTE: {fonte}\nTITOLO: {titolo}\nTESTO:\n{testo[:15000]}"

    for tentativo in range(3):
        try:
            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b", 
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_utente}
                ],
                temperature=0.3,
                max_tokens=1500
            )
            ris = completion.choices[0].message.content.strip()
            return ris.replace("```html", "").replace("```", "").strip()
        except Exception as e:
            print(f"    [Groq Fallito] {e}", flush=True)
            time.sleep(10)
    return None

def componi_html_finale(fonte, categoria, colore, contenuto, link, immagine_url):
    img_tag = f'<div style="margin-bottom: 20px;"><img src="{immagine_url}" style="width: 100%; max-height: 480px; object-fit: cover; border-radius: 8px; display: block;" /></div>' if immagine_url else ""
    return f"""<div style="font-family: 'Atkinson Hyperlegible', sans-serif; font-size: 16px; line-height: 1.65; color: #1e293b;">
    {img_tag}
    <div style="display: inline-block; padding: 4px 12px; margin-bottom: 8px; background-color: {colore}; color: #ffffff; font-weight: 700; font-size: 12px; border-radius: 4px;">FONTE: {fonte}</div>
    <div style="font-size: 13px; color: #64748b; margin-bottom: 18px;">Ambito: <em>{categoria}</em></div>
    <div style="border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 12px;">{contenuto}</div>
    <div style="margin-top: 30px; padding: 14px 18px; background-color: #f8fafc; border-left: 4px solid {colore};"><a href="{link}" style="color: {colore}; font-weight: 700;">Leggi originale su {fonte} &rarr;</a></div>
</div>"""

def elabora_voce(db, f, link, titolo, testo_grezzo="", img_url=None):
    link = (link or "").strip()
    titolo = (titolo or "Senza Titolo").strip()
    item_id = f"{VERSIONE_CACHE}_{link or titolo}"

    if item_id in db:
        return db[item_id]

    print(f"Elaborazione: {titolo[:40]}...", flush=True)

    soup = BeautifulSoup(testo_grezzo, "html.parser")
    for tag in soup(["script", "style"]): tag.decompose()
    testo_pulito = " ".join(soup.get_text().split())

    if len(testo_pulito) < 400 and link:
        contenuto, _ = scarica_bypass(link)
        if contenuto:
            s = BeautifulSoup(contenuto, "html.parser")
            testo_estratto = " ".join(p.get_text() for p in s.find_all("p"))
            if len(testo_estratto) > len(testo_pulito): testo_pulito = testo_estratto
            if not img_url and s.find("img"): img_url = s.find("img").get("src")

    if not img_url and soup.find("img"): img_url = soup.find("img").get("src")

    sintesi = genera_sintesi_e_traduzione(titolo, f["nome"], testo_pulito)

    trad_ok = True
    if not sintesi:
        trad_ok = False
        sintesi = f"<p><em>Traduzione non disponibile.</em></p><p>{testo_pulito[:800]}...</p>"

    html = componi_html_finale(f["nome"], f["categoria"], f["colore"], sintesi, link, img_url)
    record = {"id": item_id, "title": f"[{f['nome']}] {titolo}", "link": link, "html_content": html, "published": datetime.now(timezone.utc).isoformat()}

    if trad_ok: db[item_id] = record
    time.sleep(8)
    return record

def elabora_voce_immagini(db, f, link, titolo, limite_immagini=10):
    """Come elabora_voce ma senza sintesi/traduzione Groq: compone la voce
    con le sole immagini trovate nella pagina dell'articolo."""
    link = (link or "").strip()
    titolo = (titolo or "Senza Titolo").strip()
    item_id = f"{VERSIONE_CACHE}_{link or titolo}"

    if item_id in db:
        return db[item_id]

    print(f"Elaborazione: {titolo[:40]}...", flush=True)

    immagini = []
    contenuto, _ = scarica_bypass(link) if link else (None, None)
    if contenuto:
        s = BeautifulSoup(contenuto, "html.parser")
        for tag in s.find_all(["img", "source"]):
            src = None
            for attr in ("data-src", "data-lazy-src", "src"):
                val = tag.get(attr)
                if val and not val.startswith("data:"):
                    src = val
                    break
            if not src:
                srcset = tag.get("srcset") or tag.get("data-srcset")
                if srcset:
                    candidati = [c.strip().split(" ")[0] for c in srcset.split(",") if c.strip()]
                    candidati = [c for c in candidati if not c.startswith("data:")]
                    if candidati: src = candidati[-1]  # l'ultima è di solito la risoluzione più alta
            if not src: continue
            src = urllib.parse.urljoin(link, src)
            if "logo" in src.lower(): continue
            if src not in immagini:
                immagini.append(src)
            if len(immagini) >= limite_immagini: break

    if immagini:
        contenuto_html = "".join(
            f'<div style="margin-bottom: 14px;"><img src="{i}" style="width: 100%; border-radius: 8px; display: block;" /></div>'
            for i in immagini
        )
    else:
        contenuto_html = "<p><em>Nessuna immagine trovata.</em></p>"

    html = f"""<div style="font-family: 'Atkinson Hyperlegible', sans-serif; font-size: 16px; line-height: 1.65; color: #1e293b;">
    <div style="display: inline-block; padding: 4px 12px; margin-bottom: 8px; background-color: {f['colore']}; color: #ffffff; font-weight: 700; font-size: 12px; border-radius: 4px;">FONTE: {f['nome']}</div>
    <div style="font-size: 13px; color: #64748b; margin-bottom: 18px;">Ambito: <em>{f['categoria']}</em></div>
    <div style="border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 12px;">{contenuto_html}</div>
    <div style="margin-top: 30px; padding: 14px 18px; background-color: #f8fafc; border-left: 4px solid {f['colore']};"><a href="{link}" style="color: {f['colore']}; font-weight: 700;">Vedi originale su {f['nome']} &rarr;</a></div>
</div>"""

    record = {"id": item_id, "title": f"[{f['nome']}] {titolo}", "link": link, "html_content": html, "published": datetime.now(timezone.utc).isoformat()}
    db[item_id] = record
    time.sleep(2)
    return record

def main():
    db = carica_database()
    articoli = []

    for f in FONTI:
        if f.get("tipo") == "immagini":
            for titolo, link in recupera_articoli_pagina(f["url"], nome_fonte=f["nome"]):
                articoli.append(elabora_voce_immagini(db, f, link, titolo))
            continue

        if f.get("tipo") == "pagina":
            for titolo, link in recupera_articoli_pagina(f["url"], nome_fonte=f["nome"]):
                articoli.append(elabora_voce(db, f, link, titolo))
            continue

        parsed = recupera_feed_xml(f["url"], f.get("fallback"))
        if not hasattr(parsed, "entries"): continue

        for entry in parsed.entries[:2]:
            link = entry.get("link", "")
            titolo = entry.get("title", "Senza Titolo")
            testo_grezzo = entry.get("content", [{}])[0].get("value", entry.get("summary", ""))
            img_url = entry.media_content[0].get("url") if "media_content" in entry and len(entry.media_content) > 0 else None
            articoli.append(elabora_voce(db, f, link, titolo, testo_grezzo, img_url))

    salva_database(db)

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
    fg.title("Rassegna Personale Unificata")
    fg.link(href=FEED_SITE, rel="alternate")
    fg.description("Sintesi IA e proxy anti-blocco.")
    fg.language("it")

    for item in sorted(articoli_unici, key=lambda x: x.get("published", ""), reverse=True)[:30]:
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.content(item["html_content"], type="CDATA")
    fg.rss_file(FEED_OUTPUT, pretty=True)

if __name__ == "__main__":
    main()
