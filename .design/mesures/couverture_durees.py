#!/usr/bin/env python3
"""R1b, moitié déterministe : que couvre `default_duration` SANS aucun modèle ?

Prend les étapes réelles du corpus échantillonné, cherche les verbes de la table,
et mesure combien d'étapes reçoivent une durée par la table seule. Le reste est
ce que le LLM devra estimer — c'est le chiffre qui dimensionne le risque.

Aucun appel réseau payant : on relit le corpus déjà collecté.
"""
import json, re, html, urllib.request, sys, collections
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
      'Accept-Language': 'fr-FR,fr;q=0.9'}

VERBES = {v['verb']: v for v in json.load(open('seed/conversions.json'))['default_duration']}

# Formes fléchies réellement rencontrées dans les recettes, par verbe de la table.
FLEXIONS = {
    'éplucher': r'[ée]pluch\w*|pel(?:er|ez|é)\w*',
    'émincer': r'[ée]minc\w*',
    'hacher': r'hach\w*',
    'couper': r'coup(?:er|ez|é)\w*|taill(?:er|ez|é)\w*|d[ée]taill\w*|tronçonn\w*',
    'râper': r'r[âa]p(?:er|ez|é)\w*',
    'laver': r'lav(?:er|ez|é)\w*|rinc(?:er|ez|é)\w*|nettoy\w*',
    'mélanger': r'm[ée]lang\w*|remu(?:er|ez|é)\w*|incorpor\w*|ajout(?:er|ez|é)\w*|vers(?:er|ez|é)\w*',
    'assaisonner': r'assaisonn\w*|sal(?:er|ez|é)\w*|poivr(?:er|ez|é)\w*|[ée]pic\w*',
    'battre': r'batt(?:re|ez)\w*|fouett\w*|mont(?:er|ez)\s+(?:les|en)\b',
    'pétrir': r'p[ée]tri\w*',
    'étaler': r'[ée]tal(?:er|ez|é)\w*|abaiss\w*|[ée]tend(?:re|ez)\w*',
    'dresser': r'dress(?:er|ez|é)\w*|servi\w*|r[ée]parti\w*|garni\w*',
    'préchauffer': r'pr[ée]chauff\w*',
    'enfourner': r'enfourn\w*|au four\b|cuire au four',
    'gratiner': r'gratin\w*',
    'rôtir': r'r[ôo]ti\w*',
    'faire revenir': r'(?:faire|faites)\s+revenir|revenir\b',
    'saisir': r'saisi(?:r|ssez|e)\w*',
    'sauter': r'saut(?:er|ez|é)\w*(?:\s+à\s+la\s+po[êe]le)?',
    'dorer': r'dor(?:er|ez|é)\w*',
    'porter à ébullition': r'port(?:er|ez)\s+à\s+[ée]bullition|faire\s+bouillir|bouill\w*',
    'cuire': r'cui(?:re|sez|t|te)\w*',
    'mijoter': r'mijot\w*|laisser\s+cuire\s+à\s+feu\s+doux|compot\w*',
    'réduire': r'r[ée]dui(?:re|sez|t)\w*',
    'blanchir': r'blanchi\w*',
    'air fryer': r'air\s?fry\w*|friteuse\s+à\s+air',
    'mixer': r'mix(?:er|ez|é)\w*|blend\w*|mouliner\w*',
    'réchauffer': r'r[ée]chauff\w*|micro-?ondes?',
    'laisser reposer': r'(?:laiss\w+\s+)?repos(?:er|ez)\w*',
    'laisser lever': r'(?:laiss\w+\s+)?lev(?:er|ez)\w*|pouss(?:er|ez)\w*',
    'réfrigérer': r'r[ée]frig[ée]r\w*|au\s+(?:frigo|r[ée]frig[ée]rateur)|prendre\s+au\s+froid',
    'mariner': r'marin(?:er|ez|é)\w*',
    'refroidir': r'refroidi\w*|ti[ée]di\w*',
    'égoutter': r'[ée]goutt\w*',
    'réserver': r'r[ée]serv(?:er|ez|é)\w*',
    # ── ajoutés après la première mesure : ce que les 14 % non couverts contenaient
    'ciseler': r'cisel\w*',
    'zester': r'zest\w*',
    'séparer les blancs': r's[ée]par\w*\s+(?:le|les)\s+blancs?|clarifi\w*',
    'décortiquer': r'd[ée]cortiqu\w*|[ée]causs\w*|d[ée]veiner\w*',
    'gratter': r'gratt(?:er|ez|é)\w*|brosser\w*',
    'presser': r'press(?:er|ez|é)\w*\s+(?:le|la|les|un|une)|jus\s+de\s+citron\s+press',
    'rouler': r'roul(?:er|ez|é)\w*|fa[çc]onn\w*|bouler\w*',
    'dérouler': r'd[ée]roul\w*',
    'piquer': r'piqu(?:er|ez|é)\w*\s+(?:le|la|les)',
    'beurrer': r'beurr(?:er|ez|é)\w*|badigeonn\w*|graiss(?:er|ez|é)\w*|huil(?:er|ez|é)\w*\s+(?:le|la|les)',
    'farcir': r'farci\w*|remplis?s\w*|garni(?:r|ssez)\w*',
    'plier': r'pli(?:er|ez|é)\w*|rabatt\w*',
    'disposer': r'dispos(?:er|ez|é)\w*|d[ée]pos(?:er|ez|é)\w*|plac(?:er|ez|é)\w*|mett(?:re|ez)\b',
    'décorer': r'd[ée]cor(?:er|ez|é)\w*|parsem\w*|saupoudr\w*|napp(?:er|ez|é)\w*',
    'retirer du feu': r'retir(?:er|ez|é)\w*|sort(?:ir|ez)\w*\s+(?:du|de la)',
    'faire chauffer': r'(?:faire|faites)\s+chauffer|chauff(?:er|ez)\s+(?:le|la|l.|une|un)',
    'faire fondre': r'(?:faire|faites)\s+fondre|fond(?:re|ez)\b',
    'déglacer': r'd[ée]glac\w*',
    'cuire sous pression': r'sous\s+(?:haute\s+)?pression|autocuiseur|cocotte-minute',
    'tremper': r'tremp(?:er|ez|é)\w*|dessal\w*|r[ée]hydrat\w*',
}

# Les phrases qui ne décrivent aucun geste : elles n'ont pas de durée, elles sortent du plan.
NON_ACTION = [re.compile(m, re.I) for m in
              json.load(open('seed/conversions.json'))['non_action']['motifs']]
def est_action(texte):
    t = texte.strip()
    if len(t) < 12: return False
    return not any(m.search(t) for m in NON_ACTION)
assert set(FLEXIONS) <= set(VERBES), set(FLEXIONS) - set(VERBES)
MANQUANTS = set(VERBES) - set(FLEXIONS)
if MANQUANTS: print(f"(verbes de la table sans motif : {MANQUANTS})", file=sys.stderr)

def walk(o):
    if isinstance(o, dict):
        t = o.get('@type')
        if t == 'Recipe' or (isinstance(t, list) and 'Recipe' in t): yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

def grab(u):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=35).read().decode('utf-8','ignore')
    except Exception: return None
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', raw, re.S|re.I):
        try: d = json.loads(html.unescape(m.group(1)).strip())
        except Exception: continue
        for r in walk(d): return r
    return None

def etapes(r):
    out = []
    def rec(x):
        if isinstance(x, str): out.append(x)
        elif isinstance(x, dict):
            if x.get('text'): out.append(x['text'])
            elif x.get('itemListElement'): rec(x['itemListElement'])
        elif isinstance(x, list):
            for i in x: rec(i)
    rec(r.get('recipeInstructions') or [])
    return [s.strip() for s in out if s and s.strip()]

def verbes_de(texte):
    trouves = []
    for verbe, motif in FLEXIONS.items():
        if re.search(motif, texte, re.I): trouves.append(verbe)
    return trouves

urls = [l.strip().split('|')[1:] for l in open(
    'sm.out')
    if l.startswith('URL|')]

lignes, freq, non_couvertes, ecartees = [], collections.Counter(), [], []
def job(t):
    r = grab(t[1])
    return etapes(r) if r else []

with ThreadPoolExecutor(12) as ex:
    for st in ex.map(job, urls):
        for e in st:
            if not est_action(e):
                ecartees.append(e); continue
            v = verbes_de(e)
            lignes.append((e, v))
            for x in v: freq[x] += 1
            if not v: non_couvertes.append(e)

n = len(lignes)
couvertes = n - len(non_couvertes)
multi = sum(1 for _, v in lignes if len(v) >= 2)
print(f"\n### COUVERTURE DE default_duration — SANS aucun modèle\n")
print(f"  phrases écartées (pas des gestes)           : {len(ecartees):>4}         « bon appétit », « et voilà »…")
print(f"  étapes réellement ordonnançables            : {n:>4}\n")
print(f"  étapes où la table trouve au moins un verbe : {couvertes:>4}/{n}  = {100*couvertes/n:5.1f} %")
print(f"  étapes où elle n'en trouve aucun            : {len(non_couvertes):>4}/{n}  = {100*len(non_couvertes)/n:5.1f} %  <- pour le LLM")
print(f"  étapes à plusieurs verbes (à décomposer)    : {multi:>4}/{n}  = {100*multi/n:5.1f} %")
print(f"\n  verbes les plus rencontrés :")
for v, c in freq.most_common(12):
    print(f"    {v:<22} {c:>4}  ({VERBES[v]['base_minutes']:>2} min, {VERBES[v]['load_type']})")
print(f"\n  verbes de la table jamais rencontrés : "
      f"{', '.join(sorted(set(FLEXIONS) - set(freq))) or 'aucun'}")
print(f"\n  échantillon de ce que la table ne couvre pas :")
for e in non_couvertes[:6]:
    print(f"    · {e[:96]}")
