import os
import json
import time
from datetime import datetime, timezone
import feedparser
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from groq import Groq

# ---------------------------------------------------------------------------
# CONFIGURAZIONE FONTI
# ---------------------------------------------------------------------------
FONTI = [
    {
        "nome": "Frieze (Opinion)",
        "url": "https://www.frieze.com/rss.xml",
        "categoria": "Critica d'Arte & Dibattito Culturale",
        "colore": "#0f172a"
    },
    {
        "nome": "ArtReview (Opinion)",
        "url": "https://artreview.com/category/opinion/feed/",
        "categoria": "Teoria Artistica & Controversie",
        "colore": "#7c3aed"
    },
    {
        "nome": "Valigia Blu (Fuori da qui)",
        "url": "https://www.valigiablu.it/category/fuori-da-qui/feed/",
        "categoria": "Geopolitica & Diritti Umani",
        "colore": "#0284c7"
    },
    {
        "nome": "IrpiMedia (Editoriali)",
        "url": "https://irpimedia.irpi.eu/editoriali/feed/",
        "categoria": "Opinione & Analisi Investigativa",
        "colore": "#dc2626"
    },
    {
        "nome": "IrpiMedia (Inchieste)",
        "url": "https://irpimedia.irpi.eu/inchieste/feed/",
        "categoria": "Giornalismo d'Inchiesta",
        "colore": "#991b1b"
    },
    {
        "nome": "IrpiMedia (Feature)",
        "url": "https://irpimedia.irpi.eu/feature/feed/",
        "categoria": "Reportage & Approfondimento",
        "colore": "#b91c1c"
    },
    {
        "nome": "1000 Words",
        "url": "https://www.1000wordsmag.com/feed/",
        "categoria": "Fotografia Contemporanea & Linguaggi Visivi",
        "colore": "#d97706"
    },
    {
        "nome": "Il Tascabile",
        "url": "https://www.iltascabile.com/feed/",
        "categoria": "Saggistica, Filosofia & Scienze",
        "colore": "#059669"
    },
    {
        "nome": "The Italian Review",
        "url": "https://www.theitalianreview.com/feed/",
        "categoria": "Critica Letteraria & Sguardo d'Autore",
        "colore": "#4338ca"
    }
]

DATABASE_FILE = "feed_database.json"
FEED_OUTPUT = "feed_sintesi.xml"
FEED_URL = "https://lorenzoromani367.github.io/NewsFeed/feed_sintesi.xml"
FEED_SITE = "https://lorenzoromani367.github.io/NewsFeed/"

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

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

def pulisci_testo(html_raw):
    if not html_raw:
        return ""
    soup = BeautifulSoup(html_raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()
    return " ".join(soup.get_text().split())

def estrai_immagine(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url")
    if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get("url")
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
    prompt_sistema = """Sei un analista editoriale senior per una rassegna culturale, artistica e investigativa d'avanguardia.
Il tuo compito è produrre un'analisi densa, approfondita e stimolante dell'articolo fornito.

REGOLE TASSATIVE:
1. LINGUA: Italiano colto, incisivo, privo di formule banali o frasi fatte (vietato esordire con "L'articolo parla di...", "Questo pezzo esplora...").
2. STRUTTURA A DUE SEZIONI:
   - Sezione 1: "QUADRO CRITICO & CONTESTO" -> Sviluppa un testo approfondito articolato in 3 paragrafi ricchi. Devi contestualizzare l'opera o l'inchiesta, analizzare le metodologie o la visione dell'autore e metterne a fuoco le implicazioni politiche, estetiche o sociali.
   - Sezione 2: "TESI CHIAVE & PUNTI SALIENTI" -> Elenco numerato di 3-4 punti specifici contenenti dati, dichiarazioni significative, concetti cardine o risvolti operativi emersi.
3. FORMATO OUTPUT: Restituisci ESCLUSIVAMENTE codice HTML pulito (senza blocchi markdown ```html). Usa solo i tag <p>, <strong>, <ol>, <li>.
"""

    prompt_utente = f"""FONTE: {fonte}
CATEGORIA: {categoria}
TITOLO: {titolo}

TESTO ARTICOLO:
{testo[:6500]}

Genera l'analisi approfondita seguendo rigorosamente le regole e la struttura stabilite."""

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_utente}
            ],
            temperature=0.35,
            max_tokens=1400
        )
        risultato = completion.choices[0].message.content.strip()
        if risultato.startswith("```html"):
            risultato = risultato[7:]
        if risultato.startswith("```"):
            risultato = risultato[3:]
        if risultato.endswith("```"):
            risultato = risultato[:-3]
        return risultato.strip()
    except Exception as e:
        print(f"Errore Groq: {e}")
        return None

def componi_html_finale(fonte, categoria, colore, riassunto_html, link_originale, immagine_url):
    img_tag = ""
    if immagine_url:
        img_tag = f"""
        <div style="margin-bottom: 20px;">
            <img src="{immagine_url}" style="width: 100%; max-height: 480px; object-fit: cover; border-radius: 8px; display: block;" alt="Copertina" />
        </div>
        """

    return f"""<div style="font-family: 'Atkinson Hyperlegible', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 16px; line-height: 1.65; color: #1e293b; max-width: 680px;">
    {img_tag}
    <div style="display: inline-block; padding: 4px 12px; margin-bottom: 8px; background-color: {colore}; color: #ffffff; font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; border-radius: 4px;">
        FONTE: {fonte}
    </div>
    <div style="font-size: 13px; color: #64748b; margin-bottom: 18px; font-weight: 500;">
        Ambito: <em>{categoria}</em>
    </div>

    <div style="border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 12px;">
        {riassunto_html}
    </div>

    <div style="margin-top: 30px; padding: 14px 18px; background-color: #f8fafc; border-left: 4px solid {colore}; border-radius: 4px;">
        <span style="font-weight: 600; font-size: 14px; color: #334155;">Consulta l'originale integrale:</span><br/>
        <a href="{link_originale}" target="_blank" rel="noopener" style="color: {colore}; font-weight: 700; text-decoration: underline; font-size: 14px;">
            Vai all'articolo su {fonte} &rarr;
        </a>
    </div>
</div>"""

def main():
    db = carica_database()
    articoli_processati = []

    print("--- INIZIO ELABORAZIONE FONTI ---")

    for f_info in FONTI:
        nome_fonte = f_info["nome"]
        url_feed = f_info["url"]
        categoria = f_info["categoria"]
        colore = f_info["colore"]

        print(f"\nScansione feed: {nome_fonte}...")
        parsed = feedparser.parse(url_feed)

        for entry in parsed.entries[:3]:
            link = entry.get("link", "")
            titolo_originale = entry.get("title", "Senza Titolo").strip()
            
            # Chiave v2 per forzare il refresh strutturale su Feedly
            item_id = f"v2_{link or titolo_originale}"

            if item_id in db:
                print(f"  [GIA ARCHIVIATO] {titolo_originale[:40]}...")
                articoli_processati.append(db[item_id])
                continue

            print(f"  [NUOVO] Elaborazione: {titolo_originale[:40]}...")
            
            # Estrazione corpo articolo
            testo_grezzo = ""
            if "content" in entry:
                testo_grezzo = entry.content[0].value
            elif "summary" in entry:
                testo_grezzo = entry.summary
            elif "description" in entry:
                testo_grezzo = entry.description

            testo_pulito = pulisci_testo(testo_grezzo)

            # Approfondimento da pagina originale se il feed RSS è troppo corto
            if len(testo_pulito) < 400 and link:
                try:
                    r = requests.get(link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        paragraphs = soup.find_all("p")
                        testo_pulito = " ".join([p.get_text() for p in paragraphs])
                except Exception:
                    pass

            if len(testo_pulito) < 150:
                print(f"  [SCARTATO] Testo insufficiente per {titolo_originale}")
                continue

            sintesi_corpo = genera_sintesi_approfondita(titolo_originale, nome_fonte, categoria, testo_pulito)
            if not sintesi_corpo:
                continue

            immagine = estrai_immagine(entry)
            html_finale = componi_html_finale(nome_fonte, categoria, colore, sintesi_corpo, link, immagine)

            # Titolo esplicito: [Fonte] Titolo originale
            titolo_formattato = f"[{nome_fonte}] {titolo_originale}"

            data_pub = datetime.now(timezone.utc)
            if "published_parsed" in entry and entry.published_parsed:
                data_pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            record = {
                "id": item_id,
                "title": titolo_formattato,
                "link": link,
                "source": nome_fonte,
                "category": categoria,
                "html_content": html_finale,
                "published": data_pub.isoformat()
            }

            db[item_id] = record
            articoli_processati.append(record)
            time.sleep(1)

    salva_database(db)

    # ---------------------------------------------------------------------------
    # GENERAZIONE FEED RSS XML
    # ---------------------------------------------------------------------------
    fg = FeedGenerator()
    fg.title("Rassegna Personale: Arte, Fotografia & Inchieste")
    fg.link(href=FEED_SITE, rel="alternate")
    fg.link(href=FEED_URL, rel="self")
    fg.description("Sintesi critiche approfondite e monitoraggio editoriale con Groq Llama 3.3 70B.")
    fg.language("it")

    # Ordina cronologicamente
    articoli_processati.sort(key=lambda x: x.get("published", ""), reverse=True)

    for item in articoli_processati[:25]:
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.author({"name": item.get("source", "Redazione")})
        fe.content(item["html_content"], type="CDATA")
        fe.published(item["published"])

    fg.rss_file(FEED_OUTPUT, pretty=True)
    print(f"\nFeed salvato con successo in {FEED_OUTPUT} ({len(articoli_processati[:25])} articoli).")

if __name__ == "__main__":
    main()
