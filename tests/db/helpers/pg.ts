/**
 * Une connexion DIRECTE à Postgres, sans PostgREST.
 *
 * Trois choses que rien d'autre ne permet : tenir une transaction ouverte
 * pendant qu'une autre attend (le verrou du foyer), poser l'heure de la base,
 * et agir COMME un membre dans une transaction qu'on garde ouverte.
 */
import pg from 'pg'

export const URL_PG = process.env.SUPABASE_DB_URL
  ?? 'postgresql://postgres:postgres@127.0.0.1:54322/postgres'
/** Le superutilisateur local : seul à pouvoir poser `popote.maintenant`. */
export const URL_PG_ADMIN = process.env.SUPABASE_ADMIN_DB_URL
  ?? 'postgresql://supabase_admin:postgres@127.0.0.1:54322/postgres'

export async function connexion(url = URL_PG): Promise<pg.Client> {
  const c = new pg.Client({ connectionString: url })
  await c.connect()
  return c
}

/**
 * Ouvre une transaction qui agit comme ce membre : rôle `authenticated`,
 * `auth.uid()` = lui. RLS, triggers et gardes jouent comme pour le client ; la
 * transaction reste ouverte tant qu'on ne la ferme pas.
 */
export async function commeLui(c: pg.Client, userId: string) {
  await c.query('begin')
  await c.query(`select set_config('request.jwt.claims', $1, true)`,
    [JSON.stringify({ sub: userId, role: 'authenticated' })])
  await c.query('set local role authenticated')
}

/**
 * Comme le PROPRIÉTAIRE des fonctions, avec `auth.uid()` = ce membre : pour
 * appeler une fonction interne, fermée au client, comme le ferait la fonction
 * `security definer` qui l'appelle.
 */
export async function enProprietaire(c: pg.Client, userId: string) {
  await c.query('begin')
  await c.query(`select set_config('request.jwt.claims', $1, true)`,
    [JSON.stringify({ sub: userId, role: 'authenticated' })])
}

/** Une promesse dont on peut demander si elle a fini : c'est ainsi qu'on prouve qu'elle ATTEND. */
export function suivie<T>(p: PromiseLike<T>) {
  const s = { fini: false, p: Promise.resolve(p).finally(() => { s.fini = true }) }
  return s
}

export const attends = (ms: number) => new Promise(r => setTimeout(r, ms))
