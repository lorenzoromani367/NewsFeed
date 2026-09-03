#!/usr/bin/env python3
"""
Pipeline di sintesi RSS su Groq (Llama 3.3 70B).
Esecuzione rapida senza errori di quota, esportazione per Feedly.
"""

import hashlib
import json
import os
import re
import time
import warnings
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from dateutil import parser as date_parser

warnings.filterwarnings("ignore")

from bs4 import BeautifulSoup
import feedparser
from feedgen.feed import FeedGenerator
from groq import Groq
from pydantic import BaseModel, Field
import requests

# ==============================================================================
# 1. FONTI CONFIGURATE
# ==============================================================================
FONTI_CONFIGURATE = [
    # Fotografia
    {
        "nome": "British Journal of Photography",
        "url": "https://www.1854.photography/feed/",
        "tipo": "rss",
        "attivo": True
    },
    {
        "nome": "Aperture Foundation",
        "url": "https://aperture.org/feed/",
        "tipo": "rss",
        "attivo": True
    },
    {
      
    },

    # Arte & Critica
    {
        "nome": "Hyperallergic",
        "url": "https://hyperallergic.com/feed/",
        "tipo": "rss",
        "attivo": True
    },

    # Inchieste
    {
        "nome": "IrpiMedia - Archivio Serie",
        "url": "https://irpimedia.irpi.eu/serie/",
        "tipo": "html",
        "attivo": True
    }
]

# ==============================================================================
# 2. PARAMETRI DI SISTEMA
# ==============================================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_ID = "llama-3.3-70b-versatile"

DB_FILE = "feed_database.json"
OUTPUT_FEED_FILE = "feed_sintesi.xml"
MAX_FEED_ITEMS = 100
ARTICOLI_PER_FONTE = 5

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# ==============================================================================
# 3. SCHEMA DATI STRUTTURATO
# ==============================================================================
class ArticleAnalysis(BaseModel):
    category: Literal["arte", "fotografia", "news", "newsletter", "altro"]
    italian_title: str
    long_summary: str
    key_points: list[str]


# ==============================================================================
# 4. UTILITIES DI ESTRAZIONE
# ==============================================================================
def clean_url(url: str) -> str:
    parsed = urlparse(url)
    clean_query = [
        (k, v) for k, v in parse_qsl(parsed.query)
        if not k.startswith("utm_") and k not in ("ref", "fbclid", "gclid")
    ]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(clean_query), ""))

def load_db() -> list[dict]:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_db(items: list[dict]):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def extract_lead_image(page_url: str, entry_obj=None) -> str | None:
    if entry_obj:
        if "media_content" in entry_obj and entry_obj.media_content:
            return entry_obj.media_content[0].get("url")
        if "media_thumbnail" in entry_obj and entry_obj.media_thumbnail:
            return entry_obj.media_thumbnail[0].get("url")
        if "enclosures" in entry_obj and entry_obj.enclosures:
            for enc in entry_obj.enclosures:
                if enc.get("type", "").startswith("image/"):
                    return enc.get("href")

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        res = requests.get(page_url, headers=headers, timeout=6)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
            if og_img and og_img.get("content"):
                return urljoin(page_url, og_img["content"])
    except Exception:
        pass
    return None

def fetch_clean_content(url: str) -> str | None:
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "X-Timeout": "15"}
    try:
        res = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=18)
        res.encoding = "utf-8"
        if res.status_code == 200 and len(res.text.strip()) > 250:
            return res.text
    except Exception as e:
        print(f"  [!] Fallito recupero per {url}: {e}")
    return None

MESI_ITALIANI = {
    "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
    "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
    "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12"
}

def parse_italian_date(date_str: str) -> datetime:
    try:
        clean = date_str.lower().strip()
        for it_month, num in MESI_ITALIANI.items():
            if it_month in clean:
                clean = clean.replace(it_month, num)
                break
        dt = date_parser.parse(clean)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def extract_items_from_html_page(page_url: str) -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    try:
        res = requests.get(page_url, headers=headers, timeout=15)
        if res.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(res.text, "html.parser")
    for noise in soup.find_all(["header", "nav", "footer", "aside"]):
        noise.decompose()

    entries, seen = [], set()
    for el in soup.find_all(["article", "div", "li", "section"]):
        a_tag = el.find("a", href=True)
        if not a_tag:
            continue
        full_url = urljoin(page_url, a_tag["href"])
        if urlparse(full_url).netloc != urlparse(page_url).netloc or full_url == page_url or full_url in seen:
            continue
        if any(x in full_url.lower() for x in ["/category/", "/tag/", "/chi-siamo/", "/privacy", "#", "wp-login", "/serie/"]):
            continue

        heading = el.find(["h1", "h2", "h3", "h4"])
        title = heading.get_text(strip=True) if heading else a_tag.get_text(strip=True)
        if not title or len(title) < 14:
            continue

        text_all = el.get_text(" ", strip=True)
        date_obj = datetime.now(timezone.utc)
        m = re.search(r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})', text_all)
        if m:
            date_obj = parse_italian_date(m.group(1))

        seen.add(full_url)
        entries.append({"title": title, "link": full_url, "date": date_obj, "entry_obj": None})
    return entries


# ==============================================================================
# 5. ANALISI TRAMITE GROQ (LLAMA 3.3 70B)
# ==============================================================================
def analyze_with_groq(text: str, original_title: str) -> ArticleAnalysis | None:
    if not client:
        raise ValueError("GROQ_API_KEY mancante nell'ambiente.")

    system_prompt = (
        "Sei un redattore editoriale esperto. Restituisci ESCLUSIVAMENTE un oggetto JSON valido conforme allo schema:\n"
        "{\n"
        '  "category": "arte" | "fotografia" | "news" | "newsletter" | "altro",\n'
        '  "italian_title": "string (titolo in italiano colto, fedele e non sensazionalistico)",\n'
        '  "long_summary": "string (riassunto approfondito in 2-4 paragrafi densi di fatti, contesto e figure citate)",\n'
        '  "key_points": ["string (da 3 a 5 punti cardine con dettagli precisi)"]\n'
        "}\n"
        "Non inserire testo aggiuntivo fuori dal blocco JSON."
    )

    user_prompt = f"Titolo originale: {original_title}\n\nTesto articolo:\n{text[:25000]}"

    for attempt in range(3):
        try:
            chat_completion = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw_json = chat_completion.choices[0].message.content
            return ArticleAnalysis.model_validate_json(raw_json)
        except Exception as e:
            print(f"  [!] Tentativo {attempt + 1} fallito: {e}")
            time.sleep(2)
    return None


# ==============================================================================
# 6. RENDERING HTML TIPOGRAFICO
# ==============================================================================
def render_html_content(analysis: ArticleAnalysis, original_link: str, image_url: str | None) -> str:
    points_html = "".join([f"<li style='margin-bottom: 8px;'>{pt}</li>" for pt in analysis.key_points])

    image_html = ""
    if image_url:
        image_html = f"""
        <div style="margin: 16px 0 20px 0;">
          <img src="{image_url}" alt="{analysis.italian_title}" style="max-width: 100%; height: auto; border-radius: 6px; display: block;" />
        </div>
        """

    colors = {
        "arte": "#7b1fa2", "fotografia": "#00796b", "news": "#c62828",
        "newsletter": "#e65100", "altro": "#455a64"
    }
    accent = colors.get(analysis.category, "#455a64")

    paragraphs = [p.strip() for p in analysis.long_summary.split("\n") if p.strip()]
    summary_html = "".join([f"<p style='margin-bottom: 12px; font-size: 1.05em;'>{p}</p>" for p in paragraphs])

    return f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400;1,700&display=swap');
      .reader-container {{
        font-family: 'Atkinson Hyperlegible', -apple-system, BlinkMacSystemFont, sans-serif;
        line-height: 1.7;
        color: #1a1a1a;
        font-size: 16px;
      }}
    </style>
    <div class="reader-container">
      <p style="margin-bottom: 8px;">
        <span style="background-color: {accent}; color: #ffffff; padding: 3px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;">
          {analysis.category}
        </span>
      </p>

      <h1 style="font-size: 1.6em; line-height: 1.25; margin-top: 6px; margin-bottom: 16px; color: #111;">
        {analysis.italian_title}
      </h1>

      {image_html}

      <h2 style="font-size: 1.15em; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; margin-top: 24px; margin-bottom: 10px; color: #111;">
        Riassunto
      </h2>
      <div style="color: #262626;">
        {summary_html}
      </div>

      <h2 style="font-size: 1.15em; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; margin-top: 24px; margin-bottom: 10px; color: #111;">
        Punti principali
      </h2>
      <ul style="padding-left: 22px; margin-top: 0; color: #262626;">
        {points_html}
      </ul>

      <p style="margin-top: 30px; padding-top: 12px; border-top: 1px solid #eee; font-size: 0.95em;">
        <a href="{original_link}" target="_blank" style="color: {accent}; text-decoration: underline; font-weight: 700;">
          Leggi l'articolo originale ↗
        </a>
      </p>
    </div>
    """


# ==============================================================================
# 7. CICLO PRINCIPALE
# ==============================================================================
def extract_date_from_rss(entry) -> datetime:
    for field in ("published", "updated", "created"):
        if hasattr(entry, field):
            try:
                dt = date_parser.parse(getattr(entry, field))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)

def run():
    history = load_db()
    seen_ids = {item["id"] for item in history}
    new_records = []

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Avvio scansione canali...")

    for fonte in FONTI_CONFIGURATE:
        if not fonte or not isinstance(fonte, dict) or not fonte.get("attivo", True):
            continue
        url = (fonte.get("url") or "").strip()
        if not url:
            continue

        nome = (fonte.get("nome") or "").strip() or url
        tipo = fonte.get("tipo", "rss")

        print(f"\n--- Canale: {nome} ---")
        items = []

        if tipo == "html":
            items = extract_items_from_html_page(url)
        else:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:ARTICOLI_PER_FONTE]:
                raw_link = entry.get("link")
                if raw_link:
                    items.append({
                        "title": entry.get("title", "Senza Titolo"),
                        "link": raw_link,
                        "date": extract_date_from_rss(entry),
                        "entry_obj": entry
                    })

        for item in items[:ARTICOLI_PER_FONTE]:
            clean_item_link = clean_url(item["link"])
            article_id = hashlib.sha256(clean_item_link.encode("utf-8")).hexdigest()

            if article_id in seen_ids:
                continue

            print(f"  -> Rilevato: {item['title']}")

            text_content = fetch_clean_content(clean_item_link)
            if not text_content:
                continue

            analysis = analyze_with_groq(text_content, item["title"])
            if not analysis:
                continue

            image_url = extract_lead_image(clean_item_link, item.get("entry_obj"))

            print(f"  -> Sintetizzato [{analysis.category.upper()}]: {analysis.italian_title}")
            if image_url:
                print(f"     [Immagine: {image_url[:55]}...]")

            html_body = render_html_content(analysis, clean_item_link, image_url)

            record = {
                "id": article_id,
                "title": f"[{analysis.category.upper()}] {analysis.italian_title}",
                "category": analysis.category,
                "link": clean_item_link,
                "html_content": html_body,
                "published_iso": item["date"].isoformat()
            }

            new_records.append(record)
            seen_ids.add(article_id)

    if not new_records and os.path.exists(OUTPUT_FEED_FILE):
        print("\nNessun nuovo articolo rilevato.")
        return

    updated_history = (new_records + history)[:MAX_FEED_ITEMS]
    save_db(updated_history)

    fg = FeedGenerator()
    fg.id("https://feed-sintesi-personale.local/rss.xml")
    fg.title("Rassegna Personale: Arte, Fotografia & Inchieste")
    fg.link(href="https://feed-sintesi-personale.local", rel="self")
    fg.description("Riassunti approfonditi con Atkinson Hyperlegible")
    fg.language("it")

    for item in updated_history:
        fe = fg.add_entry()
        fe.id(item["id"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.category(term=item["category"])
        fe.description(item["html_content"])

        dt = date_parser.parse(item["published_iso"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        fe.published(dt)

    fg.rss_file(OUTPUT_FEED_FILE)
    print(f"\nOperazione completata: {len(updated_history)} articoli pronti in '{OUTPUT_FEED_FILE}'.")

if __name__ == "__main__":
    run()