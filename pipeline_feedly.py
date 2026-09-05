import os
import json
import time
from datetime import datetime, timezone
import requests
import feedparser
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from groq import Groq

FONTI = [
    {"nome": "Il Tascabile", "url": "https://www.iltascabile.com/feed/", "fallback": None, "categoria": "Saggistica", "colore": "#059669"},
    {"nome": "1000 Words", "url": "https://www.1000wordsmag.com/feed/", "fallback": "http://www.1000wordsmag.com/feed/", "categoria": "Fotografia", "colore": "#d97706"},
    {"nome": "Frieze", "url": "https://www.frieze.com/rss.xml", "fallback": "https://www.frieze.com/feed", "categoria": "Arte Contemporanea", "colore": "#0f172a"}
]

DATABASE_FILE = "feed_database.json"
FEED_OUTPUT = "feed_sintesi.xml"
FEED_SITE = "https://lorenzoromani367.github.io/NewsFeed/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

def carica_database():
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def salva_database(db):
    with open(DATABASE_FILE, "w", encoding="utf-8") as f: json.dump(db, f, ensure_ascii=False, indent=2)

def genera_sintesi_e_traduzione(titolo, fonte, testo):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return "ERRORE_SISTEMA: La variabile GROQ_API_KEY è vuota. GitHub non sta passando il Secret al codice."

    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="llama3-8b-8192", 
            messages=[
                {"role": "system", "content": "Sei un traduttore. TRADUCI IN ITALIANO e riassumi in 3 punti. Solo codice HTML (<p>, <ul>)."},
                {"role": "user", "content": f"FONTE: {fonte}\nTITOLO: {titolo}\nTESTO:\n{testo[:3000]}"}
            ],
            temperature=0.3,
            max_tokens=900
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"ERRORE_GROQ: {str(e)}"

def main():
    db = carica_database()
    articoli = []

    for f in FONTI:
        try:
            res = requests.get(f["url"], headers=HEADERS, timeout=12)
            parsed = feedparser.parse(res.content)
        except: continue

        for entry in parsed.entries[:2]:
            link = entry.get("link", "").strip()
            titolo = entry.get("title", "Senza Titolo").strip()
            item_id = f"v12_{link or titolo}"

            if item_id in db:
                articoli.append(db[item_id])
                continue
            
            testo_grezzo = entry.get("content", [{}])[0].get("value", entry.get("summary", ""))
            soup = BeautifulSoup(testo_grezzo, "html.parser")
            for tag in soup(["script", "style"]): tag.decompose()
            testo_pulito = " ".join(soup.get_text().split())

            sintesi = genera_sintesi_e_traduzione(titolo, f["nome"], testo_pulito)
            traduzione_riuscita = True

            if sintesi and sintesi.startswith("ERRORE_"):
                traduzione_riuscita = False
                sintesi = f"<div style='background-color: #fee2e2; color: #991b1b; padding: 15px; border: 2px solid #ef4444; border-radius: 8px; font-weight: bold; margin-bottom: 20px;'>⚠️ DIAGNOSTICA GUASTO:<br><br>{sintesi}</div>"
            elif not sintesi:
                traduzione_riuscita = False
                sintesi = "<p>Errore sconosciuto.</p>"

            html = f"""<div style="font-family: sans-serif; font-size: 16px; line-height: 1.6; color: #1e293b;">
                <div style="display: inline-block; padding: 4px 12px; margin-bottom: 8px; background-color: {f['colore']}; color: white; font-weight: bold; border-radius: 4px;">{f['nome']}</div>
                <div style="margin-top: 15px;">{sintesi}</div>
                <div style="margin-top: 20px;"><a href="{link}" style="color: {f['colore']}; font-weight: bold;">Leggi originale &rarr;</a></div>
            </div>"""
            
            record = {"id": item_id, "title": f"[{f['nome']}] {titolo}", "link": link, "html_content": html, "published": datetime.now(timezone.utc).isoformat()}
            
            if traduzione_riuscita: db[item_id] = record
            articoli.append(record)
            time.sleep(3)

    salva_database(db)
    
    fg = FeedGenerator()
    fg.title("Rassegna Diagnostica")
    fg.link(href=FEED_SITE, rel="alternate")
    fg.description("Test Diagnostico per scovare l'errore")
    fg.language("it")

    for item in sorted(articoli, key=lambda x: x.get("published", ""), reverse=True)[:10]:
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.content(item["html_content"], type="CDATA")
    fg.rss_file(FEED_OUTPUT, pretty=True)

if __name__ == "__main__":
    main()
