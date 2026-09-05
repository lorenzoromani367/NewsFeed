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
    {"nome": "Il Tascabile", "url": "https://www.iltascabile.com/feed/", "fallback": None, "categoria": "Saggistica", "colore": "#059669"},
    {"nome": "The Italian Review", "url": "https://www.theitalianreview.com/feed/", "fallback": None, "categoria": "Critica", "colore": "#4338ca"},
    {"nome": "Valigia Blu", "url": "https://www.valigiablu.it/category/fuori-da-qui/feed/", "fallback": "https://www.valigiablu.it/feed/", "categoria": "Geopolitica", "colore": "#0284c7"},
    {"nome": "IrpiMedia (Inchieste)", "url": "https://irpimedia.irpi.eu/inchieste/feed/", "fallback": "https://irpimedia.irpi.eu/feed/", "categoria": "Inchiesta", "colore": "#dc2626"},
    {"nome": "IrpiMedia (Editoriali)", "url": "https://irpimedia.irpi.eu/editoriali/feed/", "fallback": "https://irpimedia.irpi.eu/feed/", "categoria": "Opinione", "colore": "#991b1b"},
    {"nome": "Frieze", "url": "https://www.frieze.com/rss.xml", "fallback": "https://www.frieze.com/feed", "categoria": "Arte Contemporanea", "colore": "#0f172a"},
    {"nome": "ArtReview", "url": "https://artreview.com/category/opinion/feed/", "fallback": "https://artreview.com/feed/", "categoria": "Teoria Artistica", "colore": "#7c3aed"},
    {"nome": "1000 Words", "url": "https://www.1000wordsmag.com/feed/", "fallback": "http://www.1000wordsmag.com/feed/", "categoria": "Fotografia", "colore": "#d97706"}
]

DATABASE_FILE = "feed_database.json"
FEED_OUTPUT = "feed_sintesi.xml"
FEED_SITE = "https://lorenzoromani367.github.io/NewsFeed/"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

client = Groq(api_key=os.environ.get("GROQ_API_KEY")) if os.environ.get("GROQ_API_KEY") else None

def carica_database():
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def salva_database(db):
    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def recupera_feed_xml(url, fallback_url=None):
    for target in [url, fallback_url]:
        if not target: continue
        try:
            res = requests.get(target, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                parsed = feedparser.parse(res.content)
                if len(parsed.entries) > 0: return parsed
        except: pass
    return feedparser.parse(url)

def genera_sintesi_e_traduzione(titolo, fonte, testo):
    if not client: 
        print("    [ERRORE] Chiave Groq non trovata!", flush=True)
        return None

    prompt_sistema = """Sei un analista editoriale. Se il testo originale è in inglese, TRADUCILO IN ITALIANO.
REGOLE TASSATIVE:
1. LINGUA: Esclusivamente ITALIANO.
2. STRUTTURA:
   - "QUADRO CRITICO": 2-3 paragrafi di analisi profonda.
   - "PUNTI CHIAVE": Elenco numerato di 3 concetti salienti.
3. FORMATO: Solo codice HTML (<p>, <strong>, <ol>, <li>). Nessun markdown."""

    prompt_utente = f"FONTE: {fonte}\nTITOLO: {titolo}\nTESTO:\n{testo[:4000]}"

    for tentativo in range(3):
        try:
            # IL NUOVO MODELLO ATTIVO DA AGOSTO 2026
            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b", 
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": prompt_utente}
                ],
                temperature=0.3,
                max_tokens=900
            )
            ris = completion.choices[0].message.content.strip()
            return ris.replace("```html", "").replace("```", "").strip()
        except Exception as e:
            # FLUSH=TRUE PERMETTE DI VEDERE L'ERRORE LIVE NEL TERMINALE DI GITHUB
            print(f"    [Groq Fallito - Tentativo {tentativo+1}/3] {e}", flush=True)
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

def main():
    db = carica_database()
    articoli = []

    for f in FONTI:
        parsed = recupera_feed_xml(f["url"], f.get("fallback"))
        if not hasattr(parsed, "entries"): continue

        for entry in parsed.entries[:2]:
            link = entry.get("link", "").strip()
            titolo = entry.get("title", "Senza Titolo").strip()
            item_id = f"v14_{link or titolo}"

            if item_id in db:
                articoli.append(db[item_id])
                continue
            
            print(f"Elaborazione: {titolo[:40]}...", flush=True)
            
            testo_grezzo = entry.get("content", [{}])[0].get("value", entry.get("summary", ""))
            soup = BeautifulSoup(testo_grezzo, "html.parser")
            for tag in soup(["script", "style"]): tag.decompose()
            testo_pulito = " ".join(soup.get_text().split())

            if len(testo_pulito) < 400 and link:
                try:
                    r = requests.get(link, headers=HEADERS, timeout=8)
                    s = BeautifulSoup(r.text, "html.parser")
                    testo_estratto = " ".join([p.get_text() for p in s.find_all("p")])
                    if len(testo_estratto) > len(testo_pulito): testo_pulito = testo_estratto
                except: pass

            sintesi = genera_sintesi_e_traduzione(titolo, f["nome"], testo_pulito)
            
            traduzione_riuscita = True
            if not sintesi: 
                traduzione_riuscita = False
                sintesi = f"<p><em>Traduzione temporaneamente non disponibile. Riproverà al prossimo aggiornamento.</em></p><p>{testo_pulito[:800]}...</p>"

            img_url = None
            if "media_content" in entry and len(entry.media_content) > 0: img_url = entry.media_content[0].get("url")
            elif soup.find("img"): img_url = soup.find("img").get("src")

            html = componi_html_finale(f["nome"], f["categoria"], f["colore"], sintesi, link, img_url)
            
            record = {
                "id": item_id,
                "title": f"[{f['nome']}] {titolo}",
                "link": link,
                "html_content": html,
                "published": datetime.now(timezone.utc).isoformat()
            }
            
            if traduzione_riuscita:
                db[item_id] = record
            
            articoli.append(record)
            time.sleep(8)

    salva_database(db)
    
    fg = FeedGenerator()
    fg.title("Rassegna Personale Unificata")
    fg.link(href=FEED_SITE, rel="alternate")
    fg.description("Le migliori testate con traduzione e analisi IA.")
    fg.language("it")

    for item in sorted(articoli, key=lambda x: x.get("published", ""), reverse=True)[:30]:
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.content(item["html_content"], type="CDATA")
    fg.rss_file(FEED_OUTPUT, pretty=True)

if __name__ == "__main__":
    main()
