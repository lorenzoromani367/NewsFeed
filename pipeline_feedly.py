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
# CONFIGURAZIONE FONTI CON FALLBACK ANTI-BLOCCO
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
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
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
    """Scarica il feed usando uno User-Agent reale per bypassare i blocchi 403."""
    for target in [url, fallback_url]:
        if not target:
            continue
        try:
            res = requests.get(target, headers=HEADERS_BROWSER, timeout=12)
            if res.status_code == 200 and len(res.content) > 100:
                parsed = feedparser.parse(res.content)
                if len(parsed.entries) > 0:
                    return parsed
        except Exception as e:
            print(f"    [RETE] Avviso su {target}: {e}")
    # Tentativo diretto come extrema ratio
    return feedparser.parse(url)

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
    if not client:
        return None

    prompt_sistema = """Sei un analista editoriale senior per una rassegna culturale, artistica e d'inchiesta d'avanguardia.
Produci un'analisi densa, rigorosa e stimolante dell'articolo fornito.

REGOLE TASSATIVE:
1. LINGUA: Italiano colto, incisivo, privo di convenevoli o formule generiche.
2. STRUTTURA IN DUE BLOCCHI:
   - Blocco 1: "QUADRO CRITICO & CONTESTO" -> Testo articolato in 3 paragrafi ricchi. Analizza tesi, presupposti teorici o metodologici e impatto culturale/politico.
   - Blocco 2: "TESI CHIAVE & PUNTI SALIENTI" -> Elenco numerato di 3-4 punti specifici (concetti centrali, evidenze o snodi critici).
3. FORMATO: Restituisci ESCLUSIVAMENTE codice HTML pulito (senza blocchi markdown ```html). Usa solo i tag <p>, <strong>, <ol>, <li>.
"""

    prompt_utente = f"FONTE: {fonte}\nCATEGORIA: {categoria}\nTITOLO: {titolo}\n\nTESTO ARTICOLO:\n{testo[:6000]}"

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_utente}
            ],
            temperature=0.35,
            max_tokens=1300
        )
        risultato = completion.choices[0].message.content.strip()
        risultato = risultato.replace("```html", "").replace("```", "").strip()
        return risultato
    except Exception as e:
        print(f"    [GROQ ERROR] {e}")
        return None

def componi_html_finale(fonte, categoria, colore, riassunto_html, link_originale, immagine_url):
    img_tag = ""
    if immagine_url:
        img_tag = f'<div style="margin-bottom: 20px;"><img src="{immagine_url}" style="width: 100%; max-height: 480px; object-fit: cover; border-radius: 8px; display: block;" alt="Copertina" /></div>'

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

    print("=== INIZIO ACQUISIZIONE FONTI ===")

    for f_info in FONTI:
        nome_fonte = f_info["nome"]
        categoria = f_info["categoria"]
        colore = f_info["colore"]

        parsed = recupera_feed_xml(f_info["url"], f_info.get("fallback"))
        num_articoli = len(parsed.entries) if hasattr(parsed, "entries") else 0
        print(f"\n[FONTE] {nome_fonte}: trovati {num_articoli} articoli.")

        if num_articoli == 0:
            continue

        for entry in parsed.entries[:2]:
            link = entry.get("link", "").strip()
            titolo_originale = entry.get("title", "Senza Titolo").strip()
            item_id = f"v3_{link or titolo_originale}"

            if item_id in db:
                print(f"  -> In archivio: {titolo_originale[:40]}...")
                articoli_processati.append(db[item_id])
                continue

            print(f"  -> Elaborazione: {titolo_originale[:40]}...")

            testo_grezzo = ""
            if "content" in entry:
                testo_grezzo = entry.content[0].value
            elif "summary" in entry:
                testo_grezzo = entry.summary
            elif "description" in entry:
                testo_grezzo = entry.description

            testo_pulito = pulisci_testo(testo_grezzo)

            if len(testo_pulito) < 300 and link:
                try:
                    r = requests.get(link, headers=HEADERS_BROWSER, timeout=8)
                    if r.status_code == 200:
                        soup = BeautifulSoup(r.text, "html.parser")
                        paragraphs = soup.find_all("p")
                        testo_estratto = " ".join([p.get_text() for p in paragraphs])
                        if len(testo_estratto) > len(testo_pulito):
                            testo_pulito = testo_estratto
                except Exception:
                    pass

            sintesi_corpo = genera_sintesi_approfondita(titolo_originale, nome_fonte, categoria, testo_pulito)
            
            # Fail-safe: se Groq non risponde, usa l'estratto per non svuotare il feed
            if not sintesi_corpo:
                print(f"     [AVVISO] Sintesi LLM fallita, utilizzo estratto originale.")
                anteprima = testo_pulito[:700] if len(testo_pulito) > 100 else "Testo disponibile al link originale."
                sintesi_corpo = f"<p><strong>Estratto:</strong></p><p>{anteprima}...</p>"

            immagine = estrai_immagine(entry)
            html_finale = componi_html_finale(nome_fonte, categoria, colore, sintesi_corpo, link, immagine)
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
            time.sleep(2)

    salva_database(db)

    print(f"\n=== GENERAZIONE XML: {len(articoli_processati)} ARTICOLI TOTALI ===")

    if len(articoli_processati) == 0:
        print("[ERRORE CRITICO] Nessun articolo recuperato dalle fonti.")
        return

    fg = FeedGenerator()
    fg.title("Rassegna Personale: Arte, Fotografia & Inchieste")
    fg.link(href=FEED_SITE, rel="alternate")
    fg.link(href=FEED_URL, rel="self")
    fg.description("Sintesi critiche approfondite e monitoraggio editoriale con Groq Llama 3.3 70B.")
    fg.language("it")

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
    print(f"[COMPLETATO] Feed salvato con successo in {FEED_OUTPUT}")

if __name__ == "__main__":
    main()
