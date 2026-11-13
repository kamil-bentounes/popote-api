/* Les tests de base parlent à la pile Supabase locale avec le fetch de Node (undici), qui garde ses connexions
   ouvertes pour les réutiliser. Il arrive que la passerelle ferme une connexion au moment précis où undici la
   reprend : la requête échoue en « other side closed » (SocketError, code UND_ERR_SOCKET), sans réponse.
   Vu six fois en CI les 12 et 13/11/2026, toujours pendant la préparation des données (tests/db/charges.test.ts).
   Dans ce seul cas, la requête est rejouée une fois, sur une connexion neuve. Toute autre erreur remonte telle
   quelle, et une seconde coupure aussi : une vraie panne de la pile fait toujours échouer le test. */

type Fetch = typeof fetch

/** Vrai pour l'erreur d'undici « other side closed » : l'autre bout a fermé la connexion. */
export function estConnexionFermeeParLautreBout(e: unknown): boolean {
  if (!(e instanceof TypeError)) return false
  const cause: unknown = e.cause
  return typeof cause === 'object' && cause !== null && (cause as { code?: unknown }).code === 'UND_ERR_SOCKET'
}

/** Un corps qu'on peut renvoyer tel quel. Ni un flux ni une Request : leur corps a déjà été lu. */
function peutRejouer(input: Parameters<Fetch>[0], init?: RequestInit): boolean {
  if (input instanceof Request) return false
  const corps = init?.body
  return corps === undefined || corps === null || typeof corps === 'string' || corps instanceof URLSearchParams
    || corps instanceof Blob || corps instanceof FormData || corps instanceof ArrayBuffer || ArrayBuffer.isView(corps)
}

/** Enveloppe `f` : une requête coupée par l'autre bout est rejouée une fois, jamais plus. */
export function fetchAvecReprise(f: Fetch): Fetch {
  return async (input, init) => {
    try {
      return await f(input, init)
    } catch (e) {
      if (!estConnexionFermeeParLautreBout(e) || !peutRejouer(input, init)) throw e
      return await f(input, init)
    }
  }
}
