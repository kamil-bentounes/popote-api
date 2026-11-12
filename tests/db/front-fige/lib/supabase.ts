import { createClient } from '@supabase/supabase-js'
import type { PostgrestSingleResponse } from '@supabase/supabase-js'
import type { Database } from './base.types.ts'
import { fragmentRepare } from './lien.ts'
import { SESSION_PERDUE, sessionPerdue } from './session-perdue.ts'
import { PAS_DE_RESEAU, enFrancais, estUnePanneDeReseau } from './reseau.ts'

/* ⚠️ AVANT `createClient` : c'est lui qui lit l'URL pour y chercher la session.
   Un lien empoisonné (`#error=…#access_token=…`, voir `fragmentRepare`) y
   serait lu comme une erreur, et la session jetée. */
if (typeof window !== 'undefined') {
  const repare = fragmentRepare(window.location.hash)
  if (repare) {
    window.history.replaceState(window.history.state, '',
      window.location.pathname + window.location.search + repare)
  }
}

/* Chaque requête de données passe ici : si elle part SANS jeton de session (la clé anonyme en
   tient lieu) et se fait refuser, la session a disparu — voir `session-perdue.ts`. */
const avecSurveillance: typeof fetch = async (entree, init) => {
  const res = await fetch(entree, init)
  if (typeof window !== 'undefined') {
    const url = entree instanceof Request ? entree.url : String(entree)
    const entetes = new Headers(init?.headers ?? (entree instanceof Request ? entree.headers : undefined))
    if (sessionPerdue(res.status, url, entetes.get('Authorization'),
                      import.meta.env.VITE_SUPABASE_ANON_KEY)) {
      window.dispatchEvent(new Event(SESSION_PERDUE))
    }
  }
  return res
}

export const supabase = createClient<Database>(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
  { global: { fetch: avecSurveillance } },
)

/** Une ligne de table, telle que la base la rend. Évite de retyper à la main. */
export type Ligne<T extends keyof Database['public']['Tables']> =
  Database['public']['Tables'][T]['Row']
export type Insertion<T extends keyof Database['public']['Tables']> =
  Database['public']['Tables'][T]['Insert']

/* On prend le type de la bibliothèque plutôt que d'en recopier la forme : son
   union discriminée (succès | échec) ne s'infère correctement que telle quelle,
   et `select()` la rend aussi bien pour une ligne que pour une liste. */

/**
 * PostgREST rend `{ data, error }`. Tout le code qui suit veut des exceptions :
 * TanStack Query sait quoi en faire, un `if (error)` recopié partout non.
 *
 * `ou` exige une réponse ; `ouNul` accepte l'absence. Les deux existent parce
 * que `maybeSingle()` rend légitimement `null`, et que confondre « rien trouvé »
 * avec « la requête a échoué » est la façon la plus sûre de masquer un bug.
 */
export function ou<T>({ data, error }: PostgrestSingleResponse<T>): T {
  if (error) throw new Error(enFrancais(error.message))
  if (data === null) throw new Error('La base n’a rien rendu.')
  return data
}

/* `maybeSingle()` porte déjà le null dans son type : on le laisse passer plutôt
   que de le redéclarer, ce que l'inférence ne saurait pas démêler. */
export function ouNul<T>({ data, error }: PostgrestSingleResponse<T>): T {
  if (error) throw new Error(enFrancais(error.message))
  return data
}

export const fn = (name: string) =>
  `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/${name}`

/** Appelle une Edge Function avec le jeton de la session courante. */
/**
 * Se déconnecter sur CET appareil, puis repartir de zéro.
 *
 * ⚠️ `signOut` rend une erreur dans deux cas qui ne se ressemblent pas.
 *    Si c'est la requête de déconnexion qui échoue, la session est QUAND MÊME
 *    effacée de l'appareil : pour nous, c'est réussi. Mais si le jeton a expiré
 *    et que le réseau manque pour le rafraîchir, l'erreur part AVANT que rien
 *    ne soit effacé : la session reste, et rouvrait le compte au retour du
 *    réseau — pour la personne suivante, sur un téléphone partagé. Seul
 *    l'événement `SIGNED_OUT` dit lequel des deux on vit ; dans le second,
 *    l'écran le dit.
 *
 * `local` : cet appareil seulement, les autres restent connectés. Et la page
 * se RECHARGE : la mémoire de l'application — charges, revenus — ne reste pas
 * pour la personne suivante.
 */
export async function deconnecte(vers: string = import.meta.env.BASE_URL): Promise<string | null> {
  let effacee = false
  const { data: ecoute } = supabase.auth.onAuthStateChange(e => { if (e === 'SIGNED_OUT') effacee = true })
  const { error } = await supabase.auth.signOut({ scope: 'local' })
  ecoute.subscription.unsubscribe()
  if (error && !effacee) return 'La déconnexion n’a pas abouti : vérifie ta connexion, puis réessaie.'
  window.location.href = vers
  return null
}

/** `delaiMs` : au-delà, l'appel est abandonné et dit « pas de réseau » — un fetch suspendu ne doit pas bloquer l'écran. */
export async function callFunction<T = unknown>(name: string, body: unknown, delaiMs?: number): Promise<T> {
  const { data, error } = await supabase.auth.getSession()
  if (!data.session) {
    /* ⚠️ Pas de session ne veut pas dire « session perdue ». Jeton de plus d'une heure + réseau
       coupé : auth-js ne peut pas le rafraîchir et rend `session: null` AVEC une erreur de réseau.
       C'était une simple panne, et « Ta session a expiré » renvoyait à la connexion. */
    if (error && estUnePanneDeReseau(error)) throw new ErreurDeFonction(PAS_DE_RESEAU, 'reseau', 0)
    window.dispatchEvent(new Event(SESSION_PERDUE))
    throw new Error('Connecte-toi d’abord.')
  }
  return appelle<T>(name, body, data.session.access_token, delaiMs)
}

/**
 * Appelle une Edge Function SANS session : la seule qui l'accepte est
 * `accept-invite`, quand l'invitée crée son compte depuis son lien.
 */
export function callFunctionPublique<T = unknown>(name: string, body: unknown): Promise<T> {
  return appelle<T>(name, body, import.meta.env.VITE_SUPABASE_ANON_KEY)
}

/** Une erreur de fonction, avec son code quand elle en porte un. */
export class ErreurDeFonction extends Error {
  readonly code: string | null
  readonly statut: number
  constructor(message: string, code: string | null, statut: number) {
    super(message)
    this.code = code
    this.statut = statut
  }
}

async function appelle<T>(name: string, body: unknown, jeton: string, delaiMs?: number): Promise<T> {
  /* Réseau coupé : `fetch` lève « Failed to fetch », que l'écran affichait tel quel. */
  const res = await fetch(fn(name), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: import.meta.env.VITE_SUPABASE_ANON_KEY,
      Authorization: `Bearer ${jeton}`,
    },
    body: JSON.stringify(body),
    signal: delaiMs ? AbortSignal.timeout(delaiMs) : undefined,
  }).catch(() => { throw new ErreurDeFonction(PAS_DE_RESEAU, 'reseau', 0) })
  if (!res.ok) {
    /* Le corps d'erreur est du JSON : le jeter tel quel affichait
       `{"erreur":"Quota atteint : 20 dictées…","restantes":0}` à l'écran.
       On en sort la phrase, et on garde le texte brut quand il n'y en a pas. */
    const brut = await res.text()
    let message = brut
    let code: string | null = null
    try {
      const parsed = JSON.parse(brut) as { erreur?: string; message?: string; error?: string; code?: string }
      message = parsed.erreur ?? parsed.message ?? parsed.error ?? brut
      code = parsed.code ?? null
    } catch { /* pas du JSON : on garde le texte */ }
    throw new ErreurDeFonction(message, code, res.status)
  }
  return res.json()
}
