import { createClient, SupabaseClient } from '@supabase/supabase-js'
import 'dotenv/config'

const URL = process.env.VITE_SUPABASE_URL!
const ANON = process.env.VITE_SUPABASE_ANON_KEY!
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY!

/** Client qui contourne RLS. Réservé à la préparation des données. */
export const admin = () =>
  createClient(URL, SERVICE, { auth: { persistSession: false } })

export type Actor = { client: SupabaseClient; userId: string; householdId: string; email: string }

const PASSWORD = 'test-password-12345'
const uniqueEmail = (p: string) =>
  `${p}-${Date.now()}-${Math.random().toString(36).slice(2)}@test.local`

/** Crée un foyer, un utilisateur confirmé, et le client authentifié correspondant. */
export async function makeActor(name: string): Promise<Actor> {
  const a = admin()
  const email = uniqueEmail(name)

  const { data: u, error: ue } = await a.auth.admin.createUser({
    email, password: PASSWORD, email_confirm: true,
  })
  if (ue) throw ue

  const { data: h, error: he } = await a
    .from('household').insert({ name: `foyer-${name}` }).select().single()
  if (he) throw he

  const { error: pe } = await a
    .from('user_profile').insert({ id: u.user.id, household_id: h.id, display_name: name })
  if (pe) throw pe

  const client = createClient(URL, ANON, { auth: { persistSession: false } })
  const { error: se } = await client.auth.signInWithPassword({ email, password: PASSWORD })
  if (se) throw se

  return { client, userId: u.user.id, householdId: h.id, email }
}

/** Authentifié mais SANS profil : doit ne rien voir. */
export async function makeOrphan(): Promise<{ client: SupabaseClient; userId: string }> {
  const a = admin()
  const email = uniqueEmail('orphan')
  const { data, error } = await a.auth.admin.createUser({
    email, password: PASSWORD, email_confirm: true,
  })
  if (error) throw error
  const client = createClient(URL, ANON, { auth: { persistSession: false } })
  await client.auth.signInWithPassword({ email, password: PASSWORD })
  return { client, userId: data.user.id }
}

/**
 * Connecte le client PARTAGÉ de `src/lib/supabase.ts` au compte de cet acteur.
 *
 * Nécessaire pour éprouver les fonctions de `src/lib/donnees/*` telles que
 * l'application les appelle : elles utilisent ce client-là, pas celui du test.
 * Sans session, la RLS répond « rien », et le test serait vert à vide.
 */
export async function connecteLeClientPartage(a: Actor) {
  const { supabase } = await import('../front-fige/lib/supabase.ts')
  const { error } = await supabase.auth.signInWithPassword({
    email: a.email, password: PASSWORD,
  })
  if (error) throw error
  return supabase
}

/** Jeton d'accès brut, pour appeler les Edge Functions en fetch direct. */
export async function accessToken(client: SupabaseClient): Promise<string> {
  const { data } = await client.auth.getSession()
  if (!data.session) throw new Error('pas de session')
  return data.session.access_token
}
