/* Chargé par vitest avant chaque fichier de test (`setupFiles`) : tout fetch des tests, celui de supabase-js
   compris, passe par la reprise de `fetch-reprise.ts`. La marque évite d'envelopper deux fois le même fetch
   quand un processus de test enchaîne plusieurs fichiers. */
import { fetchAvecReprise } from './fetch-reprise'

const MARQUE = Symbol.for('popote.tests.fetch-avec-reprise')
type FetchMarque = typeof fetch & { [MARQUE]?: true }

if (!(globalThis.fetch as FetchMarque)[MARQUE]) {
  const enveloppe: FetchMarque = fetchAvecReprise(globalThis.fetch)
  enveloppe[MARQUE] = true
  globalThis.fetch = enveloppe
}
