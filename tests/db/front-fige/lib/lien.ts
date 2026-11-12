/**
 * Ce qu'un lien par e-mail laisse dans l'URL quand il n'ouvre pas de session.
 *
 * Supabase renvoie vers l'adresse de retour avec `error`, `error_code` et
 * `error_description` — dans le fragment en flux implicite, dans la requête en
 * PKCE. L'écran de connexion s'affichait alors tel quel, sans un mot : le 30
 * septembre, l'invitée a ouvert un lien mort, puis redemandé trois liens sans
 * jamais savoir pourquoi le premier n'avait rien fait.
 *
 * Rend la phrase à afficher, ou `null` quand l'URL ne porte aucune erreur.
 */
export function erreurDeLien(url: string): string | null {
  const u = new URL(url)
  const p = new URLSearchParams(u.hash.replace(/^#/, ''))
  u.searchParams.forEach((v, k) => p.set(k, v))
  if (!p.has('error') && !p.has('error_code') && !p.has('error_description')) return null

  /* `otp_expired` couvre les deux cas que Supabase ne distingue pas dans
     l'URL : le lien trop vieux, et celui qui a déjà servi. */
  if (p.get('error_code') === 'otp_expired') {
    return 'Ce lien a expiré ou a déjà servi : un lien ne dure qu’une heure, et ne '
      + 'sert qu’une fois. Redemandes-en un ci-dessous.'
  }
  return 'Ce lien n’a pas pu t’ouvrir de session. Redemandes-en un ci-dessous.'
}

/**
 * Le fragment d'un lien EMPOISONNÉ, réparé — ou `null` s'il n'y a rien à faire.
 *
 * Supabase colle `#access_token=…` derrière l'adresse de retour sans regarder
 * si elle porte déjà un fragment. Une adresse de retour qui traînait
 * `#error=…` donne donc `#error=…&sb=#access_token=…` : supabase-js lit le
 * premier fragment, y trouve l'erreur, et jette une session pourtant valide.
 *
 * L'application n'émet plus de telles adresses (`App.tsx`), mais les liens
 * déjà partis en portent — et le premier chargement après un déploiement
 * tourne encore sur l'ancien code, que le service worker sert depuis son
 * cache. On garde donc le DERNIER fragment quand il porte un jeton : c'est
 * celui que Supabase a ajouté, et le seul qui dise quelque chose de vrai.
 */
export function fragmentRepare(hash: string): string | null {
  const morceaux = hash.split('#')
  if (morceaux.length < 3) return null
  const dernier = morceaux[morceaux.length - 1]
  return new URLSearchParams(dernier).has('access_token') ? `#${dernier}` : null
}

// ── Le lien d'un mail ouvert sans être connecté ─────────────────────────────

/**
 * Les paramètres que l'application sait lire dans une adresse : `sortir` (« C'est fait » d'un mail de rappel),
 * `jour` et `repas` (la semaine), `depuis` et `nouveau` (les aliments). Tout autre — `error`, `code`, un jeton — ne
 * se garde pas : ce n'est pas à nous de le rejouer après la connexion.
 */
const PARAMETRES_DE_RETOUR = ['sortir', 'jour', 'repas', 'depuis', 'nouveau'] as const
/* 1 500 : le mail « Sors N barquettes » met un identifiant par barquette dans `sortir`, jusqu'à `MAXIMUM_SORTIES`
   (40 × 36 caractères et leurs virgules). À 400, onze barquettes se perdaient sans un mot (revue du 27/10). */
const VALEUR_DE_RETOUR = /^[\w,.:-]{1,1500}$/
const CHEMIN_INTERNE = /^\/[a-z0-9][\w-]*(\/[\w-]+)*$/i

/**
 * Où ramener la personne une fois connectée : le chemin ET la requête de l'adresse qu'elle avait ouverte
 * (`/frigo?sortir=<ids>`), ou `null` quand il n'y a rien à garder.
 *
 * Seul un chemin INTERNE passe : jamais `//autre-site`, ni `https://…`, ni un chemin qui sort des lettres, chiffres,
 * tirets et barres. La requête est reconstruite, paramètre connu par paramètre connu.
 */
export function retourApresConnexion(chemin: string, recherche: string): string | null {
  if (!CHEMIN_INTERNE.test(chemin)) return null
  const lus = new URLSearchParams(recherche)
  const gardes = new URLSearchParams()
  for (const cle of PARAMETRES_DE_RETOUR) {
    const v = lus.get(cle)
    if (v !== null && VALEUR_DE_RETOUR.test(v)) gardes.set(cle, v)
  }
  const requete = gardes.toString()
  return requete ? `${chemin}?${requete}` : null
}

const CLE_DU_RETOUR = 'popote:retour'
/** Un lien de mail ne dure pas plus longtemps que le lien de connexion : une heure. */
const DUREE_DU_RETOUR_MS = 60 * 60 * 1000

type Stock = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

/** Garde le retour pour la connexion. Sans stockage (fenêtre privée), on perd le retour et rien d'autre. */
export function garderLeRetour(vers: string, stock?: Stock, maintenant = Date.now()): void {
  try {
    (stock ?? window.localStorage).setItem(CLE_DU_RETOUR, JSON.stringify({ vers, a: maintenant }))
  } catch { /* le retour se perd, la connexion non */ }
}

/**
 * Rend le retour gardé, UNE fois, s'il est récent, toujours un chemin interne valide, et gardé pour l'écran où l'on
 * arrive (`ici`) ; sinon `null`.
 *
 * - Un retour gardé pour `/frigo` ne se rejoue pas sur une connexion faite depuis `/` ou `/budget` : on l'a ouvert
 *   puis abandonné, il est jeté (revue du 27/10).
 * - Un onglet qui est DÉJÀ à cette adresse (`recherche` identique) n'a rien à rejouer : il ne le prend pas, et le
 *   laisse à l'onglet du lien de connexion par mail, qui arrive sur le chemin seul. L'heure fait le ménage.
 */
export function prendreLeRetour(ici: string, recherche: string, stock?: Stock, maintenant = Date.now()): string | null {
  let s: Stock | undefined
  try {
    s = stock ?? window.localStorage
    const brut = s.getItem(CLE_DU_RETOUR)
    if (brut === null) return null
    const { vers, a } = JSON.parse(brut) as { vers?: unknown; a?: unknown }
    const jette = () => { s!.removeItem(CLE_DU_RETOUR); return null }
    if (typeof vers !== 'string' || typeof a !== 'number') return jette()
    if (maintenant - a > DUREE_DU_RETOUR_MS || maintenant < a) return jette()
    const i = vers.indexOf('?')
    // Relu à la sortie comme à l'entrée : le stockage n'est pas une source de confiance.
    if (i <= 0 || retourApresConnexion(vers.slice(0, i), vers.slice(i)) !== vers) return jette()
    if (vers.slice(0, i) !== ici) return jette()
    if (retourApresConnexion(ici, recherche) === vers) return null
    s.removeItem(CLE_DU_RETOUR)
    return vers
  } catch {
    try { s?.removeItem(CLE_DU_RETOUR) } catch { /* rien à faire de plus */ }
    return null
  }
}
