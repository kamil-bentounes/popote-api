/**
 * Rapprocher un ticket de caisse d'une liste de courses (lot 5).
 *
 * Il n'existe aucune API de prix pour un particulier, et les bases
 * communautaires sont trouées. La seule source EXACTE de prix qu'on ait, c'est
 * le ticket : daté, à la bonne enseigne, et déjà dans la poche.
 *
 * Reste le vrai problème, qui est ici : une caisse écrit « PDT CHARLOTTE 2.5KG »
 * là où la liste dit « pomme de terre ». Rapprocher les deux est du texte
 * approximatif, donc faillible — d'où trois partis pris :
 *
 *  · **La couverture du libellé de la LISTE mène le score.** Un ticket ajoute
 *    du bruit d'emballage (marque, poids, code) ; la liste, elle, dit ce qu'on
 *    voulait. « LAIT DEMI ECREME 1L » couvre « lait » entièrement.
 *  · **On garde un peu de la couverture du TICKET** en second, pour préférer
 *    la ligne la plus spécifique quand deux se disputent le même article.
 *  · **Rien ne s'écrit sous le seuil.** Au-dessus, c'est coché d'avance ;
 *    en dessous, c'est proposé ; très en dessous, c'est laissé de côté. Un
 *    rapprochement faux fait apprendre un prix faux, et un prix faux se
 *    propage à toutes les estimations suivantes.
 */

/** Au-dessus : coché d'avance. Le libellé de la liste est entièrement couvert. */
export const SEUIL_SUR = 0.72
/** Au-dessus : proposé, décoché. En dessous : la ligne reste sans article. */
export const SEUIL_PROPOSE = 0.4

/**
 * Ce que les caisses abrègent le plus, et qu'aucune règle de préfixe ne
 * rattrape. Liste courte et assumée : on n'invente pas un dictionnaire, on note
 * ce qu'on a vu sur de vrais tickets.
 */
const ABREVIATIONS: Record<string, string> = {
  pdt: 'pomme de terre', pdterre: 'pomme de terre',
  plt: 'poulet', pqt: 'paquet', crm: 'creme', cr: 'creme',
  yt: 'yaourt', yaou: 'yaourt', fromg: 'fromage', frmg: 'fromage',
  ecr: 'ecreme', dmi: 'demi', nat: 'nature',
  ctel: 'cotelette', esc: 'escalope', filt: 'filet',
  tom: 'tomate', crt: 'carotte', ogn: 'oignon', oign: 'oignon',
  hch: 'hache', surg: 'surgele', bt: 'boite', bqt: 'barquette',
}

/**
 * Les mots qui ne distinguent RIEN : articles, liaisons, et le vocabulaire de
 * l'emballage. « Sachet de tomates » et « tomates » sont le même achat.
 */
const VIDES = new Set([
  'de', 'du', 'des', 'le', 'la', 'les', 'l', 'd', 'au', 'aux', 'a', 'en', 'et',
  'sachet', 'paquet', 'boite', 'barquette', 'pack', 'lot', 'filet', 'botte',
  'bio', 'frais', 'fraiche', 'premier', 'prix', 'marque', 'repere',
])

/** Ce qui ressemble à un poids, un volume ou un compte d'emballage. */
const MESURE = /^(\d+(?:[.,]\d+)?)\s*(kg|kgs|g|gr|grs|ml|cl|l|lt|x|pce|pces)?$/
const MULTIPLE = /^x\s*(\d+)$/

/** Minuscules, sans accents, sans ponctuation. */
export function normalise(texte: string): string {
  return texte
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9.,]+/g, ' ')
    .trim()
}

export type Poids = { quantite: number; unite: 'g' | 'ml' | 'u' } | null

/**
 * Le poids ou le volume caché dans un libellé de caisse.
 *
 * Sert de FILET quand le modèle n'a pas su lire la colonne quantité : sans
 * quantité, « 2,30 € » ne dit pas si c'est cher, parce qu'on ignore si c'est
 * pour 200 g ou pour un kilo.
 */
export function poidsDuLibelle(texte: string): Poids {
  const mots = normalise(texte).split(/\s+/)
  for (const mot of mots) {
    // « 500g », « 1.5kg », « 75cl » — collés, c'est la forme la plus courante.
    const colle = mot.match(/^(\d+(?:[.,]\d+)?)(kg|g|gr|ml|cl|l)$/)
    if (colle) {
      const n = Number(colle[1].replace(',', '.'))
      switch (colle[2]) {
        case 'kg': return { quantite: n * 1000, unite: 'g' }
        case 'g': case 'gr': return { quantite: n, unite: 'g' }
        case 'l': return { quantite: n * 1000, unite: 'ml' }
        case 'cl': return { quantite: n * 10, unite: 'ml' }
        case 'ml': return { quantite: n, unite: 'ml' }
      }
    }
    const mult = mot.match(MULTIPLE)
    if (mult) return { quantite: Number(mult[1]), unite: 'u' }
  }
  return null
}

/**
 * Les mots qui portent l'identité du produit.
 *
 * On jette les mesures : « 500 g » ne dit pas QUOI, et le garder ferait
 * ressembler deux produits sans rapport vendus au même poids.
 */
export function motsUtiles(texte: string): string[] {
  const bruts = normalise(texte).split(/\s+/).filter(Boolean)
  const mots: string[] = []
  for (const brut of bruts) {
    const mot = brut.replace(/[.,]+$/, '')
    if (!mot) continue
    if (MESURE.test(mot)) continue
    if (MULTIPLE.test(mot)) continue       // « x4 » : un compte d'emballage
    if (/^\d/.test(mot)) continue          // code article, prix, poids détaché
    const developpe = ABREVIATIONS[mot] ?? mot
    for (const m of developpe.split(' ')) {
      if (m.length > 1 && !VIDES.has(m)) mots.push(m)
    }
  }
  return mots
}

/** Deux mots désignent-ils la même chose ? L'un peut être tronqué par la caisse. */
function memeMot(a: string, b: string): boolean {
  if (a === b) return true
  // Pluriels et troncatures : « tomat » pour « tomates », « yaour » pour
  // « yaourt ». Quatre lettres au moins — en dessous, « pom » rapprocherait
  // pomme, pommade et pompe.
  const court = a.length < b.length ? a : b
  const long = a.length < b.length ? b : a
  return court.length >= 4 && long.startsWith(court)
}

/**
 * À quel point cette ligne de ticket est-elle CET article de la liste ?
 *
 * La couverture du libellé de la liste mène ; celle du ticket départage. Un
 * retour de 0 veut dire « aucun rapport », jamais « pas sûr ».
 */
export function ressemblance(libelleTicket: string, libelleListe: string): number {
  const ticket = motsUtiles(libelleTicket)
  const liste = motsUtiles(libelleListe)
  if (ticket.length === 0 || liste.length === 0) return 0

  // Un mot du ticket ne sert qu'une fois : « lait lait » ne couvre pas
  // « lait de coco » deux fois mieux.
  const restants = [...ticket]
  let couverts = 0
  for (const mot of liste) {
    const i = restants.findIndex(t => memeMot(t, mot))
    if (i >= 0) { restants.splice(i, 1); couverts++ }
  }
  if (couverts === 0) return 0

  const couvertureListe = couverts / liste.length
  const couvertureTicket = couverts / ticket.length
  return couvertureListe * (0.85 + 0.15 * couvertureTicket)
}

export type LigneTicket = {
  /** Le libellé TEL QU'IMPRIMÉ : c'est lui qui reconnaîtra le produit la fois
      suivante, et le développer perdrait cette information. */
  label: string
  quantity?: number | null
  unit?: string | null
  price_eur: number
  /** Ce que le modèle pense de SA lecture — pas du rapprochement, qui se
      mesure ici. Une ligne mal imprimée n'est pas une ligne mal rattachée. */
  confiance?: number | null
  remise_eur?: number | null
}

export type ArticleListe = {
  id: string
  label: string
  food_id?: string | null
  /** Déjà payé : on ne rapproche pas deux fois le même article. */
  paid_price_eur?: number | string | null
}

export type Rapprochement = {
  ligne: LigneTicket
  /** L'article retenu, ou `null` quand rien ne ressemble assez. */
  article: ArticleListe | null
  score: number
  /** `true` quand le rapprochement est assez sûr pour être coché d'avance. */
  sur: boolean
}

/**
 * Rapproche chaque ligne du ticket d'au plus un article de la liste.
 *
 * Affectation gloutonne : on traite les paires par score décroissant, et un
 * article pris ne l'est plus. Un algorithme optimal (hongrois) coûterait cent
 * lignes pour un gain nul — un ticket fait trente lignes, et les meilleures
 * paires sont rarement en concurrence.
 *
 * Le résultat garde l'ORDRE DU TICKET : l'écran se relit une ligne de papier à
 * la fois, et un tri par score obligerait à chercher où on en était.
 */
export function rapproche(
  lignes: LigneTicket[],
  articles: ArticleListe[],
): Rapprochement[] {
  // Un article DÉJÀ payé ne se rapproche pas une deuxième fois. Le cas est
  // celui que l'écran recommande lui-même — « si le ticket est long,
  // photographie-le en deux fois » : la seconde photo revoyait la même liste,
  // réattrapait les articles déjà soldés, et écrasait leur prix payé avec le
  // montant d'une autre ligne.
  const libres = articles.filter(a => a.paid_price_eur === null
                                   || a.paid_price_eur === undefined)

  const paires: { i: number; j: number; score: number }[] = []
  for (let i = 0; i < lignes.length; i++) {
    for (let j = 0; j < libres.length; j++) {
      const score = ressemblance(lignes[i].label, libres[j].label)
      if (score >= SEUIL_PROPOSE) paires.push({ i, j, score })
    }
  }
  // Score décroissant, puis ordre du ticket : à égalité parfaite, deux lancers
  // doivent rendre le même rapprochement (D50).
  paires.sort((a, b) => b.score - a.score || a.i - b.i || a.j - b.j)

  const prisLigne = new Set<number>()
  const prisArticle = new Set<number>()
  const retenu = new Map<number, { article: ArticleListe; score: number }>()
  for (const p of paires) {
    if (prisLigne.has(p.i) || prisArticle.has(p.j)) continue
    prisLigne.add(p.i)
    prisArticle.add(p.j)
    retenu.set(p.i, { article: libres[p.j], score: p.score })
  }

  return lignes.map((ligne, i) => {
    const r = retenu.get(i)
    return {
      ligne,
      article: r?.article ?? null,
      score: r?.score ?? 0,
      sur: (r?.score ?? 0) >= SEUIL_SUR,
    }
  })
}

export type PrixAppris = {
  label: string
  food_id: string | null
  store_id: string | null
  unit: string
  avg_price_eur: number | string
  last_price_eur: number | string
  observations: number
}

/**
 * Ce que coûtera probablement cet article, d'après ce qu'on a déjà payé.
 *
 * On préfère le prix appris CHEZ CETTE ENSEIGNE : le même yaourt n'y vaut pas
 * le même prix. À défaut, un prix appris ailleurs vaut mieux que rien — mais on
 * le dit, pour que l'écran n'affiche pas une estimation d'enseigne sur une
 * autre sans prévenir.
 */
export function estimation(
  article: { label: string; food_id?: string | null; quantity?: number | null; unit?: string | null },
  prix: PrixAppris[],
  magasinId: string | null,
): { euros: number; source: 'magasin' | 'ailleurs'; observations: number } | null {
  const candidats = prix
    .map(p => ({
      p,
      score: p.food_id && article.food_id && p.food_id === article.food_id
        ? 1
        : ressemblance(p.label, article.label),
    }))
    .filter(c => c.score >= SEUIL_SUR)
  if (candidats.length === 0) return null

  const ici = candidats.filter(c => c.p.store_id === magasinId)
  const retenus = ici.length > 0 ? ici : candidats
  // Le mieux ressemblant, puis le plus observé : un prix vu six fois vaut mieux
  // qu'un prix vu une fois.
  //
  // ⚠️ Et le LIBELLÉ en dernier recours, sans quoi le tri serait à égalité et
  //    c'est l'ordre physique des lignes Postgres qui trancherait — un ordre
  //    qui change après chaque UPDATE. Deux téléphones estimeraient alors la
  //    même liste différemment (D50), et `useEstimeListe` écrirait le résultat.
  retenus.sort((a, b) => b.score - a.score
    || b.p.observations - a.p.observations
    || a.p.label.localeCompare(b.p.label, 'fr'))
  const gagnant = retenus[0].p

  const unitaire = Number(gagnant.avg_price_eur)
  // Un prix au kilo ne devient un prix d'article que si l'on sait combien on
  // achète. Sans quantité, on rend le prix tel quel plutôt que d'inventer.
  let euros = unitaire
  if (gagnant.unit === 'kg' && article.quantity && article.unit === 'g') {
    euros = unitaire * (Number(article.quantity) / 1000)
  } else if (gagnant.unit === 'l' && article.quantity && article.unit === 'ml') {
    euros = unitaire * (Number(article.quantity) / 1000)
  } else if (gagnant.unit === 'u' && article.quantity && (article.unit === 'u' || !article.unit)) {
    euros = unitaire * Number(article.quantity)
  }

  return {
    euros: Math.round(euros * 100) / 100,
    source: ici.length > 0 ? 'magasin' : 'ailleurs',
    observations: gagnant.observations,
  }
}
