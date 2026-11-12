import { createClient } from 'jsr:@supabase/supabase-js@2'
import { preflight, reply } from '../_shared/cors.ts'

/**
 * Rejoindre un foyer par son lien d'invitation.
 *
 * Deux portes, et le corps de la requête dit laquelle :
 *
 *   · `{ token, mot_de_passe }` — L'INVITÉE N'A PAS DE COMPTE. Le lien suffit
 *     (décision du 19/10/2026) : son compte naît ici, avec le mot de passe
 *     qu'elle vient de choisir, l'adresse de l'invitation, et l'adresse tenue
 *     pour confirmée. C'est la porte de tous les jours.
 *
 *     Avant, le compte naissait d'un lien de connexion envoyé par mail : mort
 *     au bout d'une heure, consommé par les antivirus de messagerie, parti
 *     par un serveur limité à deux mails par heure. Cinq invitées n'ont jamais
 *     dépassé cette étape.
 *
 *     Ce n'est pas une preuve de l'adresse, et ce n'est pas le but : c'est le
 *     lien qui donne accès au foyer, comme celui qu'on envoie pour rejoindre
 *     un groupe. Il vaut trente jours, une seule fois, et se révoque.
 *
 *   · `{ token }`, avec une session — elle a déjà un compte, sans foyer, et
 *     s'est connectée sur le lien. On la rattache.
 */
Deno.serve(async (req) => {
  const pre = preflight(req); if (pre) return pre
  if (req.method !== 'POST') return reply('Method not allowed', 405)

  const admin = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )

  const corps = await req.json().catch(() => ({}))
  const token = typeof corps?.token === 'string' ? corps.token : null
  if (!token) return reply('Token manquant', 400)

  const { data: inv } = await admin.from('invitation').select('*').eq('token', token).maybeSingle()
  if (!inv) return reply('Invitation inconnue', 404)
  if (inv.accepted_at) return reply('Invitation déjà utilisée', 409)
  if (new Date(inv.expires_at) < new Date()) return reply('Invitation expirée', 410)

  if (typeof corps.mot_de_passe === 'string') {
    return creeSonCompte(admin, inv, corps.mot_de_passe)
  }

  const jwt = (req.headers.get('Authorization') ?? '').replace('Bearer ', '')
  if (!jwt) return reply('Non authentifié', 401)
  const { data: userRes, error: userErr } = await admin.auth.getUser(jwt)
  if (userErr || !userRes.user) return reply('Non authentifié', 401)

  const { data: existing } = await admin
    .from('user_profile').select('id').eq('id', userRes.user.id).maybeSingle()
  if (existing) return reply('Déjà rattaché à un foyer', 409)

  if (!await consomme(admin, inv.id)) return reply('Invitation déjà utilisée', 409)
  const pe = await rattache(admin, userRes.user.id, inv.household_id, false)
  if (pe) {
    // Le rattachement a échoué : on rend le jeton, sinon l'invitation est
    // perdue pour de bon et personne ne peut plus rejoindre le foyer.
    await rends(admin, inv.id)
    return reply(pe, 500)
  }
  return reply({ household_id: inv.household_id })
})

type Admin = ReturnType<typeof createClient>
type Invitation = { id: string; household_id: string; email: string }

async function creeSonCompte(admin: Admin, inv: Invitation, motDePasse: string) {
  /* 72 octets : au-delà, bcrypt ignore la fin en silence, et un mot de passe
     tapé en entier passerait pour un autre. */
  if (motDePasse.length < 8) return reply('Il faut au moins 8 caractères.', 400)
  if (new TextEncoder().encode(motDePasse).length > 72) {
    return reply('Ce mot de passe est trop long.', 400)
  }

  const { data: comptes, error: ce } = await admin
    .rpc('compte_pour_invitation', { adresse: inv.email })
  if (ce) return reply(ce.message, 500)
  const compte = (comptes as { id: string; a_un_profil: boolean }[] | null)?.[0] ?? null

  /* ⚠️ AVANT de consommer le jeton : une adresse déjà membre d'un foyer garde
     son compte, son mot de passe et son foyer. Le lien n'est pas un moyen de
     reprendre le compte de quelqu'un. */
  if (compte?.a_un_profil) {
    return reply({
      erreur: 'Cette adresse a déjà un compte Popote. Connecte-toi avec ton mot de passe.',
      code: 'compte_existant',
    }, 409)
  }

  if (!await consomme(admin, inv.id)) return reply('Invitation déjà utilisée', 409)

  let id: string
  let cree = false
  if (compte) {
    /* Le compte que laissait l'ancien mail, ou un lien de connexion suivi sans
       jamais rejoindre : il ne porte rien, ni foyer ni donnée. */
    const { error } = await admin.auth.admin.updateUserById(compte.id,
      { password: motDePasse, email_confirm: true })
    if (error) { await rends(admin, inv.id); return reply(enFrancais(error.message), 400) }
    id = compte.id
  } else {
    const { data, error } = await admin.auth.admin.createUser(
      { email: inv.email, password: motDePasse, email_confirm: true })
    if (error || !data.user) {
      await rends(admin, inv.id)
      return reply(enFrancais(error?.message ?? 'Le compte n’a pas pu être créé.'), 400)
    }
    id = data.user.id
    cree = true
  }

  const pe = await rattache(admin, id, inv.household_id, true)
  if (pe) {
    await rends(admin, inv.id)
    // Un compte né ici et resté sans foyer ne servirait qu'à bloquer le suivant.
    if (cree) await admin.auth.admin.deleteUser(id)
    return reply(pe, 500)
  }
  return reply({ household_id: inv.household_id, email: inv.email })
}

/**
 * ⚠️ ON CONSOMME LE JETON D'ABORD, et la condition `accepted_at is null` fait
 *    la course pour nous.
 *
 *    L'ordre inverse — rattacher puis marquer — laissait deux POST simultanés
 *    avec le même jeton réussir tous les deux : mesuré, le foyer passait de un
 *    à trois membres. `update … select` ne rend une ligne que si la condition
 *    tenait AU MOMENT de l'écriture : c'est le verrou, et il est atomique.
 */
async function consomme(admin: Admin, id: string): Promise<boolean> {
  const { data } = await admin.from('invitation')
    .update({ accepted_at: new Date().toISOString() })
    .eq('id', id).is('accepted_at', null)
    .gt('expires_at', new Date().toISOString())
    .select().maybeSingle()
  return !!data
}

async function rends(admin: Admin, id: string) {
  await admin.from('invitation').update({ accepted_at: null }).eq('id', id)
}

/**
 * Le profil, dans le foyer de l'invitation.
 *
 * ⚠️ PAS de prénom fabriqué depuis l'adresse : `lea-1790147184836` finissait
 *    pré-rempli, validé sans regarder, puis lu sur chaque ligne de charge. Le
 *    profil, où elle atterrit, le lui demande.
 *
 * ⚠️ `entre_le` au PREMIER DU MOIS PROCHAIN, pas aujourd'hui : la colonne vaut
 *    `current_date` par défaut, et `tg_membre_rejoint_les_communes` l'inscrit
 *    aussitôt à toutes les charges communes à partir de là. Mesuré : au seul
 *    clic, elle se voyait 854 € pour un mois où elle n'habite pas encore là.
 *    Le profil lui demande la vraie date.
 */
async function rattache(admin: Admin, id: string, foyer: string, motDePassePose: boolean) {
  const arrivee = new Date()
  arrivee.setUTCDate(1)
  arrivee.setUTCMonth(arrivee.getUTCMonth() + 1)
  const { error } = await admin.from('user_profile').insert({
    id, household_id: foyer, display_name: '',
    entre_le: arrivee.toISOString().slice(0, 10),
    password_set: motDePassePose,
  })
  return error?.message ?? null
}

/** Les refus de Supabase Auth arrivent en anglais : on dit les nôtres. */
function enFrancais(message: string): string {
  if (/weak|short|characters|password/i.test(message)) {
    return 'Ce mot de passe est trop faible : allonge-le.'
  }
  return 'Le compte n’a pas pu être créé. Réessaie dans un instant.'
}
