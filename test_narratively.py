import sys
import json
from bs4 import BeautifulSoup
import urllib.parse

from pipeline_feedly import recupera_articoli_pagina

url = "https://www.narratively.com/s/secret-lives"
res = recupera_articoli_pagina(url, nome_fonte="Narratively")
print(json.dumps(res, indent=2))
