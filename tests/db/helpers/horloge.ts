/**
 * L'heure de la base, réglée pour un banc.
 *
 * `public.maintenant()` lit `popote.maintenant`. On le pose au niveau de la
 * BASE : PostgREST ouvre ses propres connexions, qu'un `set` de session
 * n'atteindrait pas. Le réglage ne vaut que pour les connexions ouvertes APRÈS
 * lui — on ferme donc celles de PostgREST, qui les rouvre.
 *
 * L'heure posée AVANCE : on écrit « heure jouée @ heure vraie », et la base
 * ajoute le temps écoulé. Figée, une facture qui attend le verrou ne passerait
 * jamais minuit, et le seul cas qui justifie `clock_timestamp()` resterait sans
 * banc.
 *
 * ⚠️ Toujours `remetLHeure()` en `afterAll`. Un banc qui meurt l'heure posée
 *    fausse tous les suivants, et ceux des autres chantiers. À la main :
 *    psql "postgresql://supabase_admin:postgres@127.0.0.1:54322/postgres" \
 *      -c "alter database postgres reset popote.maintenant"
 */
import { admin } from './db'
import { connexion, URL_PG_ADMIN } from './pg'

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/

export async function regleLHeure(iso: string) {
  if (!ISO.test(iso)) throw new Error(`Heure illisible : ${iso}`)
  await pose(async c => {
    const { rows: [{ vraie }] } = await c.query('select clock_timestamp() as vraie')
    /* Une instruction DDL ne prend pas de paramètre : la valeur passe par le
       littéral, et la forme vient d'être vérifiée. */
    await c.query(`alter database postgres set popote.maintenant = '${iso}@${(vraie as Date).toISOString()}'`)
  })
}

export async function remetLHeure() {
  await pose(c => c.query('alter database postgres reset popote.maintenant'))
}

async function pose(f: (c: Awaited<ReturnType<typeof connexion>>) => Promise<unknown>) {
  const c = await connexion(URL_PG_ADMIN)
  try {
    await f(c)
    await c.query(`select pg_terminate_backend(pid) from pg_stat_activity
                    where usename = 'authenticator' and pid <> pg_backend_pid()`)
  } finally { await c.end() }
  // PostgREST rouvre ses connexions : on attend qu'il réponde de nouveau.
  for (let essai = 0; essai < 50; essai++) {
    const { error } = await admin().rpc('maintenant')
    if (!error) return
    await new Promise(r => setTimeout(r, 200))
  }
  throw new Error('PostgREST ne répond plus après le changement d’heure.')
}
