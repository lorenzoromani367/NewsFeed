import os
import json
import time
from datetime import datetime, timezone
import requests
import feedparser
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from groq import Groq

# ---------------------------------------------------------------------------
# CONFIGURAZIONE FONTI
# ---------------------------------------------------------------------------
FONTI = [
    {
        "nome": "Il Tascabile",
        "url": "https://www.iltascabile.com/feed/",
        "fallback": None,
        "categoria": "Saggistica & Dibattito Culturale",
        "colore": "#059669"
    },
    {
        "nome": "The Italian Review",
        "url": "https://www.theitalianreview.com/feed/",
        "fallback": None,
        "categoria": "Critica Letteraria & Società",
        "colore": "#4338ca"
    },
    {
        "nome": "Valigia Blu",
        "url": "https://www.valigiablu.it/category/fuori-da-qui/feed/",
        "fallback": "https://www.valigiablu.it/feed/",
        "categoria": "Geopolitica & Diritti Umani",
        "colore": "#0284c7"
    },
    {
        "nome": "IrpiMedia (Inchieste)",
        "url": "https://irpimedia.irpi.eu/inchieste/feed/",
        "fallback": "https://irpimedia.irpi.eu/feed/",
        "categoria": "Giornalismo d'Inchiesta",
        "colore": "#dc2626"
    },
    {
        "nome": "IrpiMedia (Editoriali)",
        "url": "https://irpimedia.irpi.eu/editoriali/feed/",
        "fallback": "https://irpimedia.irpi.eu/feed/",
        "categoria": "Opinione & Analisi",
        "colore": "#991b1b"
    },
    {
        "nome": "Frieze",
        "url": "https://www.frieze.com/rss.xml",
        "fallback": "https://www.frieze.com/feed",
        "categoria": "Critica d'Arte Contemporanea",
        "colore": "#0f172a"
    },
    {
        "nome": "ArtReview",
        "url": "https://artreview.com/category/opinion/feed/",
        "fallback": "https://artreview.com/feed/",
        "categoria": "Teoria Artistica & Controversie",
        "colore": "#7c3aed"
    },
    {
        "nome": "1000 Words",
        "url": "https://www.1000wordsmag.com/feed/",
        "fallback": "http://www.1000wordsmag.com/feed/",
        "categoria": "Fotografia Contemporanea",
        "colore": "#d97706"
    }
]

DATABASE_FILE = "feed_database.json"
FEED_OUTPUT = "feed_sintesi.xml"
FEED_URL = "https://lorenzoromani367.github.io/NewsFeed/feed_sintesi.xml"
FEED_SITE = "https://lorenzoromani367.github.io/NewsFeed/"

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

def carica_database():
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def salva_database(db):
    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def recupera_feed_xml(url, fallback_url=None):
    for target in [url, fallback_url]:
        if not target:
            continue
        try:
            res = requests.get(target, headers=HEADERS_BROWSER, timeout=12)
            if res.status_code == 200 and len(res.content) > 100:
                parsed = feedparser.parse(res.content)
                if len(parsed.entries) > 0:
                    return parsed
        except Exception:
            pass
    return feedparser.parse(url)

def pulisci_testo(html_raw):
    if not html_raw:
        return ""
    soup = BeautifulSoup(html_raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return " ".join(soup.get_text().split())

def estrai_immagine(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url")
    if "links" in entry:
        for link in entry.links:
            if link.get("type", "").startswith("image/"):
                return link.get("href")
    content = entry.get("summary", "") or entry.get("description", "")
    if content:
        soup = BeautifulSoup(content, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]
    return None

def genera_sintesi_approfondita(titolo, fonte, categoria, testo):
    if not client:
        print("     [ERRORE CRITICO] Chiave API Groq mancante o non configurata correttamente nei Secrets.")
        return None

    prompt_sistema = """Sei un analista editoriale. Produci un'analisi densa e rigorosa dell'articolo.
REGOLE TASSATIVE:
1. STRUTTURA:
   - "QUADRO CRITICO & CONTESTO": Testo articolato in 3 paragrafi ricchi. Analizza tesi e impatto.
   - "TESI CHIAVE & PUNTI SALIENTI": Elenco numerato di 3-4 concetti centrali.
2. FORMATO: Restituisci ESCLUSIVAMENTE codice HTML pulito. Usa solo <p>, <strong>, <ol>, <li>."""

    # Limite severo a 4000 caratteri per evitare di sforare i Token di Groq
    prompt_utente = f"FONTE: {fonte}\nTITOLO: {titolo}\nTESTO:\n{testo[:4000]}"

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_utente}
            ],
            temperature=0.3,
            max_tokens=900
        )
        risultato = completion.choices[0].message.content.strip()
        risultato = risultato.replace("```html", "").replace("```", "").strip()
        return risultato
    except Exception as e:
        print(f"     [GROQ ERROR RATE LIMIT] {e}")
        return None

def componi_html_finale(fonte, categoria, colore, riassunto_html, link_originale, immagine_url):
    img_tag = f'<div style="margin-bottom: 20px;"><img src="{immagine_url}" style="width: 100%; max-height: 480px; object-fit: cover; border-radius: 8px; display: block;" /></div>' if immagine_url else ""
    return f"""<div style="font-family: 'Atkinson Hyperlegible', sans-serif; font-size: 16px; line-height: 1.65; color: #1e293b;">
    {img_tag}
    <div style="display: inline-block; padding: 4px 12px; margin-bottom: 8px; background-color: {colore}; color: #ffffff; font-weight: 700; font-size: 12px; border-radius: 4px;">FONTE: {fonte}</div>
    <div style="font-size: 13px; color: #64748b; margin-bottom: 18px;">Ambito: <em>{categoria}</em></div>
    <div style="border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 12px;">{riassunto_html}</div>
    <div style="margin-top: 30px; padding: 14px 18px; background-color: #f8fafc; border-left: 4px solid {colore};"><a href="{link_originale}" style="color: {colore}; font-weight: 700;">Vai all'articolo su {fonte} &rarr;</a></div>
</div>"""

def main():
    db = carica_database()
    articoli_processati = []

    for f_info in FONTI:
        parsed = recupera_feed_xml(f_info["url"], f_info.get("fallback"))
        if not hasattr(parsed, "entries") or len(parsed.entries) == 0:
            continue

        for entry in parsed.entries[:2]:
            link = entry.get("link", "").strip()
            titolo = entry.get("title", "Senza Titolo").strip()
            item_id = f"v4_{link or titolo}" # Versione 4 per forzare riscrittura

            if item_id in db:
                articoli_processati.append(db[item_id])
                continue

            print(f"-> Elaborazione: {titolo[:40]}...")
            testo = pulisci_testo(entry.get("content", [{}])[0].get("value", entry.get("summary", "")))
            
            sintesi = genera_sintesi_approfondita(titolo, f_info["nome"], f_info["categoria"], testo)
            if not sintesi:
                sintesi = f"<p><strong>Estratto:</strong></p><p>{testo[:600]}...</p>"

            html_finale = componi_html_finale(f_info["nome"], f_info["categoria"], f_info["colore"], sintesi, link, estrai_immagine(entry))
            
            record = {
                "id": item_id,
                "title": f"[{f_info['nome']}] {titolo}",
                "link": link,
                "source": f_info["nome"],
                "category": f_info["categoria"],
                "html_content": html_finale,
                "published": datetime.now(timezone.utc).isoformat()
            }
            db[item_id] = record
            articoli_processati.append(record)
            time.sleep(15) # PAUSA FONDAMENTALE DI 15 SECONDI PER GROQ

    salva_database(db)
    
    fg = FeedGenerator()
    fg.title("Rassegna Personale: Arte, Fotografia & Inchieste")
    fg.link(href=FEED_SITE, rel="alternate")
    fg.description("Sintesi critiche approfondite.")
    fg.language("it")

    for item in sorted(articoli_processati, key=lambda x: x.get("published", ""), reverse=True)[:25]:
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.content(item["html_content"], type="CDATA")
    fg.rss_file(FEED_OUTPUT, pretty=True)

if __name__ == "__main__":
    main()
