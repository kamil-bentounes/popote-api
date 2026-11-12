/**
 * Une panne de réseau se dit en français, et ne se confond jamais avec un refus.
 *
 * Grand test, parcours « nouveau venu » (22/10), réseau coupé pendant un geste :
 *   · « Se connecter » répondait « E-mail ou mot de passe incorrect. » — la panne prise pour
 *     une erreur de saisie, à quelqu'un qui avait le bon ;
 *   · « Mot de passe oublié » répondait « le lien vient de partir » ;
 *   · inviter, accepter une invitation, enregistrer son profil affichaient « Failed to fetch »
 *     ou « TypeError: Failed to fetch ».
 */
export const PAS_DE_RESEAU = 'Pas de réseau : vérifie ta connexion, puis réessaie.'

const PANNE = /failed to fetch|networkerror|network request failed|load failed|fetch failed|internet disconnected/i

/** Cette erreur est une panne de `fetch` (réseau coupé, serveur injoignable), pas un refus. */
export function estUnePanneDeReseau(e: unknown): boolean {
  if (!e || typeof e !== 'object') return false
  const { name = '', message = '' } = e as { name?: string; message?: string }
  return name === 'AuthRetryableFetchError' || PANNE.test(String(message))
}

/**
 * Les refus du stockage de photos (seau `photos-des-plats`, 0121) arrivent en anglais : taille, type, droits.
 * Chacun a sa phrase ; le reste passe tel quel.
 */
const PHOTO_TROP_LOURDE = 'Cette photo est trop lourde (2 Mo au plus) : reprends-la de plus loin.'
const PHOTO_FORMAT = 'Ce format de photo n’est pas accepté : JPEG, PNG ou WebP.'
const PHOTO_REFUSEE = 'Cette photo ne peut pas être envoyée dans ce foyer.'
const PHOTO_ILLISIBLE = 'Cette photo ne se lit pas (une photo HEIC, par exemple) : prends-la en JPEG ou en PNG.'
const STOCKAGE: [RegExp, string][] = [
  [/exceeded the maximum allowed size|payload too large|entity too large|file too large/i, PHOTO_TROP_LOURDE],
  [/mime type .* is not supported|invalid_mime_type|unsupported media type/i, PHOTO_FORMAT],
  [/row-level security policy for table "objects"|violates row-level security.*objects/i, PHOTO_REFUSEE],
]

/** Ce qu'on affiche : la phrase française pour une panne ou un refus du stockage, le message tel quel sinon. */
export function enFrancais(message: string): string {
  if (PANNE.test(message)) return PAS_DE_RESEAU
  for (const [motif, phrase] of STOCKAGE) if (motif.test(message)) return phrase
  return message
}

/**
 * Ce qu'on dit d'une photo que le navigateur n'a pas pu préparer (`prepare`, `createImageBitmap`) : une HEIC
 * d'iPhone, un fichier abîmé — « The source image could not be decoded », « InvalidStateError ». Nos propres
 * refus de `prepare` sont déjà en français et passent.
 */
export function photoEnFrancais(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e)
  if (/^(Photo trop lourde|Impossible de préparer)/.test(message)) return message
  return enFrancais(message) !== message ? enFrancais(message) : PHOTO_ILLISIBLE
}

export const LA_BASE_NE_REPOND_PAS = 'La base ne répond pas : réessaie dans un instant.'

/**
 * Le jeton est périmé : PostgREST répond `PGRST301` (« JWT expired »), `PGRST303` (revendications
 * refusées) ou 401. Ce n'est ni une panne ni « aucun foyer » : la personne doit se reconnecter.
 */
export function estUneSessionExpiree(e: unknown, statut?: number): boolean {
  if (statut === 401) return true
  if (!e || typeof e !== 'object') return false
  const { message = '', code = '' } = e as { message?: string; code?: string }
  return code === 'PGRST301' || code === 'PGRST303' || /jwt expired/i.test(String(message))
}

/**
 * Ce que dit une erreur de lecture de l'appli (`current_household`, le profil) : la session a
 * expiré (→ connexion), le réseau manque, ou la base ne répond pas. Toute erreur est une PANNE :
 * `current_household` sans foyer rend `data` nul SANS erreur, donc une `error` — 502, 503, 504, délai
 * dépassé, projet en pause — n'est jamais « aucun foyer » (Onboarding, « Il te faut une invitation »).
 */
export type Panne = 'expiree' | 'reseau' | 'base'
export function classeLaPanne(e: unknown, statut?: number): Panne {
  if (estUneSessionExpiree(e, statut)) return 'expiree'
  return estUnePanneDeReseau(e) ? 'reseau' : 'base'
}
