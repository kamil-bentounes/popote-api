// L'API Storage de Supabase : ce que la copie et le dépôt des seaux ont en commun.
// Aucune dépendance : seulement `fetch` de Node.

const ESSAIS = 3
// Un appel de liste ou de gestion : 60 s. Un objet (téléchargement ou dépôt) : le délai couvre aussi le
// corps, donc 10 minutes, pour qu'une grosse photo sur une liaison lente ne fasse pas échouer la sauvegarde.
export const DELAI_MS = 60_000
export const DELAI_OBJET_MS = 600_000

/** Une réponse d'erreur de l'API. Le message ne cite jamais un nom d'objet (ce serait une donnée). */
export class ErreurStorage extends Error {
  constructor(message, { statut, cause } = {}) {
    super(message, { cause })
    this.name = 'ErreurStorage'
    this.statut = statut
  }
}

export function lireEnvironnement(env = process.env) {
  const manque = ['SUPABASE_URL', 'SUPABASE_SECRET_KEY'].filter((nom) => !env[nom])
  if (manque.length > 0) throw new ErreurStorage(`variables manquantes : ${manque.join(', ')}`)
  return { base: env.SUPABASE_URL.replace(/\/+$/, ''), cle: env.SUPABASE_SECRET_KEY }
}

/**
 * En-têtes d'authentification. Une clé JWT (la clé de service locale) va aussi en `Bearer` ;
 * une clé `sb_secret_…` n'est pas un JWT : seule `apikey` la porte, la passerelle la traduit.
 */
export function enTetes(cle, supplementaires = {}) {
  const entetes = { apikey: cle, ...supplementaires }
  if (cle.split('.').length === 3) entetes.Authorization = `Bearer ${cle}`
  return entetes
}

/** Encode chaque segment d'un chemin d'objet, pas les `/`. */
export const segments = (chemin) => chemin.split('/').map(encodeURIComponent).join('/')

const reessayable = (statut) => statut === 429 || statut >= 500

/**
 * Appel avec délai fini et trois essais au plus, seulement sur une erreur réseau, un 429 ou un 5xx.
 * `corps` est un Buffer ou une chaîne : il se rejoue sans surprise.
 */
export async function appeler(client, methode, chemin, { corps, entetes, libelle, delai = DELAI_MS } = {}) {
  const nom = libelle ?? methode
  let derniere
  for (let essai = 1; essai <= ESSAIS; essai++) {
    let reponse
    try {
      reponse = await fetch(`${client.base}${chemin}`, {
        method: methode,
        headers: enTetes(client.cle, entetes),
        body: corps,
        signal: AbortSignal.timeout(delai),
      })
    } catch (erreur) {
      derniere = new ErreurStorage(`${nom} : ${erreur.name}`, { cause: erreur })
    }
    if (reponse?.ok) return reponse
    if (reponse) {
      await reponse.body?.cancel()
      derniere = new ErreurStorage(`${nom} : statut ${reponse.status}`, { statut: reponse.status })
      if (!reessayable(reponse.status)) throw derniere
    }
    if (essai < ESSAIS) await new Promise((suite) => setTimeout(suite, 500 * 2 ** essai))
  }
  throw derniere
}
