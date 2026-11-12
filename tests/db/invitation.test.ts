import { describe, it, expect, beforeAll } from 'vitest'
import { createClient } from '@supabase/supabase-js'
import { makeActor, makeOrphan, admin, accessToken, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => { alice = await makeActor('alice-invit') })

const fn = (name: string) => `${process.env.VITE_SUPABASE_URL}/functions/v1/${name}`

describe('invitation', () => {
  it('un foyer crée une invitation pour lui-même', async () => {
    const { data, error } = await alice.client.from('invitation')
      .insert({ household_id: alice.householdId, email: 'copine@test.local' })
      .select().single()
    expect(error).toBeNull()
    expect(data!.token).toBeTruthy()
    expect(new Date(data!.expires_at).getTime()).toBeGreaterThan(Date.now())
  })

  it('un foyer ne peut pas inviter chez un autre foyer', async () => {
    const other = await makeActor('other-invit')
    const { error } = await alice.client.from('invitation')
      .insert({ household_id: other.householdId, email: 'pirate@test.local' })
    expect(error, 'invitation croisée acceptée').not.toBeNull()
  })

  it('répond au préflight CORS', async () => {
    const res = await fetch(fn('accept-invite'), {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://localhost:5173',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization, content-type',
      },
    })
    expect(res.status, 'sans préflight, le front ne peut rien appeler').toBeLessThan(300)
    expect(res.headers.get('access-control-allow-origin')).toBeTruthy()
  })

  it("accept-invite rattache l'invité au foyer et consomme le token", async () => {
    const a = admin()
    const { data: inv } = await a.from('invitation')
      .insert({ household_id: alice.householdId, email: `nouveau-${Date.now()}@test.local` })
      .select().single()

    const { client: guest } = await makeOrphan()
    const res = await fetch(fn('accept-invite'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${await accessToken(guest)}`,
      },
      body: JSON.stringify({ token: inv!.token }),
    })
    expect(res.status, await res.clone().text()).toBe(200)

    const { data: hh } = await guest.rpc('current_household')
    expect(hh).toBe(alice.householdId)

    const { data: after } = await a.from('invitation')
      .select('accepted_at').eq('id', inv!.id).single()
    expect(after!.accepted_at, 'le token doit être consommé').not.toBeNull()
  })

  it('refuse un token expiré', async () => {
    const { data: inv } = await admin().from('invitation').insert({
      household_id: alice.householdId, email: `tard-${Date.now()}@test.local`,
      expires_at: new Date(Date.now() - 1000).toISOString(),
    }).select().single()

    const { client: guest } = await makeOrphan()
    const res = await fetch(fn('accept-invite'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${await accessToken(guest)}`,
      },
      body: JSON.stringify({ token: inv!.token }),
    })
    expect(res.status).toBe(410)
  })
})

describe('l’invitation est vraiment à usage unique', () => {
  /*
   * Trois défauts trouvés en relisant le lot 0a, tous prouvés avant correctif.
   * « Usage unique » et « valable 7 jours » étaient des intentions, pas des
   * propriétés du système.
   */
  it('ne se consomme qu’UNE fois, même sur deux appels simultanés', async () => {
    const hote = await makeActor('inv-hote')
    const { data: inv } = await hote.client.from('invitation')
      .insert({ household_id: hote.householdId, email: `double-${Date.now()}@test.local` })
      .select().single()

    const { client: a } = await makeOrphan()
    const { client: b } = await makeOrphan()
    const appelle = async (c: typeof a) => {
      const { data: s } = await c.auth.getSession()
      const r = await fetch(fn('accept-invite'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${s!.session!.access_token}`,
        },
        body: JSON.stringify({ token: inv!.token }),
      })
      return r.status
    }

    const [x, y] = await Promise.all([appelle(a), appelle(b)])
    expect([x, y].filter(s => s === 200).length,
      'deux personnes ont utilisé le même jeton').toBe(1)

    const { data: membres } = await admin().from('user_profile')
      .select('id').eq('household_id', hote.householdId)
    expect(membres!.length, 'le foyer a gagné deux membres pour une invitation').toBe(2)
  })

  it('ne se ressuscite pas une fois acceptée', async () => {
    const hote = await makeActor('inv-mort')
    const { data: inv } = await admin().from('invitation').insert({
      household_id: hote.householdId, email: `mort-${Date.now()}@test.local`,
      accepted_at: new Date().toISOString(),
    }).select().single()

    await hote.client.from('invitation')
      .update({ accepted_at: null, expires_at: '2999-01-01' }).eq('id', inv!.id)

    const { data } = await admin().from('invitation')
      .select('accepted_at').eq('id', inv!.id).single()
    expect(data!.accepted_at, 'une invitation acceptée a été rouverte').not.toBeNull()
  })

  it('ne se prolonge pas en jeton perpétuel', async () => {
    const hote = await makeActor('inv-eternel')
    const { data: inv } = await hote.client.from('invitation')
      .insert({ household_id: hote.householdId, email: `long-${Date.now()}@test.local` })
      .select().single()

    await hote.client.from('invitation')
      .update({ expires_at: '2999-01-01' }).eq('id', inv!.id)

    const { data } = await admin().from('invitation')
      .select('expires_at').eq('id', inv!.id).single()
    expect(new Date(data!.expires_at).getFullYear(),
      'une invitation a été rendue perpétuelle').toBeLessThan(2100)
  })
})

describe('supprimer son compte', () => {
  it('marche aussi quand le foyer compte deux personnes', async () => {
    // `invitation.created_by` référençait `auth.users` sans clause de
    // suppression : dès qu'on avait invité quelqu'un, supprimer son compte
    // levait un 23503 et annulait TOUTE la transaction — ni compte, ni profil,
    // ni cibles. Le test du dépôt passait parce que sa victime était seule.
    const hote = await makeActor('sup-hote')
    const { data: inv } = await hote.client.from('invitation')
      .insert({ household_id: hote.householdId, email: `part-${Date.now()}@test.local` })
      .select().single()
    expect(inv, "l'amorce a échoué : le test serait vert à vide").not.toBeNull()

    const { error } = await hote.client.rpc('delete_my_account')
    expect(error, `la suppression a échoué : ${error?.message}`).toBeNull()

    const { data: prof } = await admin().from('user_profile').select('id').eq('id', hote.userId)
    expect(prof ?? [], 'le profil a survécu').toHaveLength(0)
  })
})

describe('la durée du lien', () => {
  /* Mesuré sur le parcours : le lien expirait au bout de SEPT jours et elle
     emménageait dans dix. Elle cliquait, obtenait « Invitation expirée », se
     retrouvait authentifiée sans foyer — et l'écran d'arrivée lui proposait
     d'en créer un autre. Sept jours est la durée d'un lien de
     réinitialisation, où la brièveté protège ; une invitation à emménager
     s'envoie quand on y pense et se lit quand on s'installe. */
  it('tient trente jours, pas sept', async () => {
    const hote = await makeActor('duree-invit')
    const { data: inv, error } = await hote.client.from('invitation')
      .insert({ household_id: hote.householdId, email: `x-${Date.now()}@fumee.test`,
                created_by: hote.userId })
      .select('created_at, expires_at').single()
    expect(error, `invitation refusée : ${error?.message}`).toBeNull()

    const jours = (new Date(inv!.expires_at).getTime()
                   - new Date(inv!.created_at).getTime()) / 86_400_000
    expect(jours, 'le lien n’est pas valable trente jours').toBeCloseTo(30, 1)
  })

  it('une invitation EXPIRÉE peut être relancée', async () => {
    /*
     * Boucle morte mesurée par une revue : `tg_invitation_borne` rabattait
     * `expires_at` sur `created_at + 30 jours`. Tant que la durée par défaut
     * valait sept jours, prolonger passait sous le rabot ; depuis qu'elle vaut
     * trente, toute prolongation revenait à une date PASSÉE, en silence. Et
     * l'index partiel interdit d'en créer une seconde — une invitation expirée
     * ne pouvait plus JAMAIS être relancée.
     */
    const hote = await makeActor('relance-invit')
    const { data: inv } = await hote.client.from('invitation')
      .insert({ household_id: hote.householdId, email: `r-${Date.now()}@fumee.test`,
                created_by: hote.userId })
      .select('id').single()

    // On la fait expirer, comme le temps l'aurait fait.
    await admin().from('invitation')
      .update({ created_at: new Date(Date.now() - 40 * 864e5).toISOString(),
                expires_at: new Date(Date.now() - 10 * 864e5).toISOString() })
      .eq('id', inv!.id)

    const cible = new Date(Date.now() + 30 * 864e5)
    const { data: prolongee } = await admin().from('invitation')
      .update({ expires_at: cible.toISOString() })
      .eq('id', inv!.id).select('expires_at').single()

    expect(new Date(prolongee!.expires_at).getTime(),
      'la prolongation est rabattue sur une date passée')
      .toBeGreaterThan(Date.now())
  })
})

/**
 * Le lien suffit (décision du 19/10/2026).
 *
 * Cinq invitées réelles n'ont jamais dépassé la création de compte. Le mail
 * d'invitation portait un lien de connexion Supabase : il mourait au bout
 * d'UNE heure, ne servait qu'une fois (les antivirus de messagerie le
 * « cliquent » avant la personne), et partait par un serveur limité à deux
 * mails par heure, souvent rangé en indésirables. Le 30 septembre, l'invitée a
 * ouvert un mail vieux de huit jours : lien mort.
 *
 * Désormais le lien `/invite/<jeton>` — trente jours, usage unique — suffit :
 * elle y choisit son mot de passe, et son compte naît sur place.
 */
const anon = () => createClient(process.env.VITE_SUPABASE_URL!,
  process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })

/** Appelle `accept-invite` SANS session, comme l'invitée qui arrive. */
async function creeSonCompte(token: string, mot_de_passe: string) {
  return fetch(fn('accept-invite'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      apikey: process.env.VITE_SUPABASE_ANON_KEY!,
      Authorization: `Bearer ${process.env.VITE_SUPABASE_ANON_KEY!}`,
    },
    body: JSON.stringify({ token, mot_de_passe }),
  })
}

const MDP = 'un-mot-de-passe-solide'

async function inviteChez(hote: Actor, email: string, en_plus: Record<string, unknown> = {}) {
  const { data, error } = await admin().from('invitation')
    .insert({ household_id: hote.householdId, email, created_by: hote.userId, ...en_plus })
    .select().single()
  if (error) throw error
  return data!
}

async function compteDe(email: string) {
  const { data } = await admin().auth.admin.listUsers({ page: 1, perPage: 1000 })
  return data.users.find(u => u.email === email) ?? null
}

describe('le lien suffit', () => {
  let hote: Actor
  beforeAll(async () => { hote = await makeActor('Kamil') })

  it('l’invitée, sans compte, lit qui l’invite et pour quelle adresse', async () => {
    const email = `lit-${Date.now()}@fumee.test`
    const inv = await inviteChez(hote, email)
    const { data, error } = await anon().rpc('invitation_par_jeton', { jeton: inv.token })
    expect(error, error?.message).toBeNull()
    expect(data).toEqual([expect.objectContaining({
      email, invite_par: 'Kamil', etat: 'valide' })])
  })

  it('un lien expiré, déjà servi ou inconnu le dit', async () => {
    const tard = await inviteChez(hote, `tard-${Date.now()}@fumee.test`,
      { expires_at: new Date(Date.now() - 1000).toISOString() })
    const servi = await inviteChez(hote, `servi-${Date.now()}@fumee.test`,
      { accepted_at: new Date().toISOString() })
    const lis = async (j: string) => (await anon().rpc('invitation_par_jeton', { jeton: j })).data
    expect((await lis(tard.token))?.[0]?.etat).toBe('expiree')
    expect((await lis(servi.token))?.[0]?.etat).toBe('utilisee')
    expect(await lis(crypto.randomUUID())).toEqual([])
  })

  it('le jeton ne livre rien d’autre à qui ne l’a pas', async () => {
    /* La fonction est ouverte à `anon` : elle ne doit rendre QUE l'invitation
       de ce jeton, et rien du foyer. */
    const { data, error } = await anon().from('invitation').select('*')
    expect(error ?? data ?? []).not.toEqual(expect.arrayContaining([expect.anything()]))
  })

  it('elle choisit son mot de passe, son compte naît, elle est dans le foyer', async () => {
    const email = `thauba-${Date.now()}@fumee.test`
    const inv = await inviteChez(hote, email)

    const res = await creeSonCompte(inv.token, MDP)
    expect(res.status, await res.clone().text()).toBe(200)

    const elle = anon()
    const { error: se } = await elle.auth.signInWithPassword({ email, password: MDP })
    expect(se, 'son mot de passe ne l’a pas connectée').toBeNull()
    expect((await elle.rpc('current_household')).data).toBe(hote.householdId)

    const { data: p } = await admin().from('user_profile')
      .select('password_set, display_name, entre_le').eq('household_id', hote.householdId)
      .neq('id', hote.userId).single()
    // Le mot de passe est posé : l'écran « Ton mot de passe » ne la rattrape pas.
    expect(p!.password_set).toBe(true)
    // Pas de prénom fabriqué : c'est son profil qui le demande.
    expect(p!.display_name).toBe('')
    const premier = new Date(); premier.setUTCDate(1); premier.setUTCMonth(premier.getUTCMonth() + 1)
    expect(p!.entre_le).toBe(premier.toISOString().slice(0, 10))

    const { data: apres } = await admin().from('invitation')
      .select('accepted_at').eq('id', inv.id).single()
    expect(apres!.accepted_at, 'le jeton n’est pas consommé').not.toBeNull()
  })

  it('refuse un mot de passe trop court, et le jeton reste bon', async () => {
    const email = `court-${Date.now()}@fumee.test`
    const inv = await inviteChez(hote, email)
    const res = await creeSonCompte(inv.token, 'court')
    expect(res.status).toBe(400)
    expect(await compteDe(email), 'un compte est né d’un refus').toBeNull()
    const { data } = await admin().from('invitation').select('accepted_at').eq('id', inv.id).single()
    expect(data!.accepted_at).toBeNull()
  })

  it('refuse un lien expiré ou déjà servi, sans créer de compte', async () => {
    const e1 = `exp-${Date.now()}@fumee.test`
    const tard = await inviteChez(hote, e1, { expires_at: new Date(Date.now() - 1000).toISOString() })
    expect((await creeSonCompte(tard.token, MDP)).status).toBe(410)
    expect(await compteDe(e1)).toBeNull()

    const e2 = `use-${Date.now()}@fumee.test`
    const servi = await inviteChez(hote, e2, { accepted_at: new Date().toISOString() })
    expect((await creeSonCompte(servi.token, MDP)).status).toBe(409)
    expect(await compteDe(e2)).toBeNull()
  })

  it('le compte laissé par l’ancien mail d’invitation sert, sans rien perdre', async () => {
    /* L'ancien parcours créait le compte dès l'envoi (`inviteUserByEmail`),
       jamais confirmé, sans mot de passe ni profil : c'est l'état des
       invitées d'avant. Le même lien doit leur ouvrir le foyer. */
    const email = `ancienne-${Date.now()}@fumee.test`
    const inv = await inviteChez(hote, email)
    const { error: ie } = await admin().auth.admin.inviteUserByEmail(email)
    expect(ie, ie?.message).toBeNull()

    const res = await creeSonCompte(inv.token, MDP)
    expect(res.status, await res.clone().text()).toBe(200)
    const elle = anon()
    expect((await elle.auth.signInWithPassword({ email, password: MDP })).error).toBeNull()
    expect((await elle.rpc('current_household')).data).toBe(hote.householdId)
  })

  it('une adresse déjà membre d’un foyer garde son compte et son mot de passe', async () => {
    const autre = await makeActor('deja-ailleurs')
    const inv = await inviteChez(hote, autre.email)

    const res = await creeSonCompte(inv.token, 'quelqu-un-d-autre')
    expect(res.status).toBe(409)
    expect(await res.json()).toEqual(expect.objectContaining({ code: 'compte_existant' }))

    // Son mot de passe n'a pas changé, et elle est toujours chez elle.
    const elle = anon()
    expect((await elle.auth.signInWithPassword({ email: autre.email,
      password: 'test-password-12345' })).error).toBeNull()
    expect((await elle.rpc('current_household')).data).toBe(autre.householdId)
    const { data } = await admin().from('invitation').select('accepted_at').eq('id', inv.id).single()
    expect(data!.accepted_at, 'le jeton est consommé pour rien').toBeNull()
  })

  it('deux envois simultanés du même lien ne font qu’un compte', async () => {
    const email = `double-clic-${Date.now()}@fumee.test`
    const inv = await inviteChez(hote, email)
    const statuts = await Promise.all([creeSonCompte(inv.token, MDP), creeSonCompte(inv.token, MDP)])
      .then(rs => rs.map(r => r.status))
    expect(statuts.filter(s => s === 200)).toHaveLength(1)
    const { data: membres } = await admin().from('user_profile')
      .select('id').eq('household_id', hote.householdId)
    const { data: comptes } = await admin().auth.admin.listUsers({ page: 1, perPage: 1000 })
    expect(comptes.users.filter(u => u.email === email)).toHaveLength(1)
    expect(membres!.length).toBeGreaterThan(1)
  })

  it('inviter ne crée plus de compte et n’envoie plus de mail : on rend le lien', async () => {
    const email = `sans-mail-${Date.now()}@fumee.test`
    const res = await fetch(fn('invite'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 Authorization: `Bearer ${await accessToken(hote.client)}` },
      body: JSON.stringify({ email }),
    })
    expect(res.status, await res.clone().text()).toBe(200)
    const r = await res.json()
    expect(r.link).toMatch(/\/invite\/[0-9a-f-]{36}$/)
    expect(r.envoye).toBe(false)
    expect(await compteDe(email), 'l’invitation a créé un compte à sa place').toBeNull()
  })

  /* Grand test, parcours « nouveau venu » (22/10) : Kamil a tapé SA PROPRE
     adresse, l'écran a répondu « Invitation créée, envoie-lui ce lien » — un
     lien qui n'aurait mené qu'à « cette adresse a déjà un compte ». */
  it('inviter quelqu’un qui est déjà dans le foyer est refusé, et ne pose aucune invitation', async () => {
    const colocataire = await makeActor('deja-la')
    await admin().from('user_profile').update({ household_id: hote.householdId })
      .eq('id', colocataire.userId)
    const res = await fetch(fn('invite'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 Authorization: `Bearer ${await accessToken(hote.client)}` },
      body: JSON.stringify({ email: colocataire.email.toUpperCase() }),
    })
    expect(res.status, 'une invitation inutile a été créée').toBe(409)
    expect(await res.text()).toMatch(/déjà dans ton foyer/)
    const { data } = await admin().from('invitation').select('id')
      .eq('household_id', hote.householdId).eq('email', colocataire.email)
    expect(data, 'l’invitation est restée en base').toHaveLength(0)
  })

  /* Le même parcours : un double clic sur « Créer l'invitation » partait en
     deux requêtes ; la seconde heurtait `invitation_pending_unique` et
     l'écran affichait « duplicate key value violates unique constraint »
     sous un lien pourtant valide. */
  it('deux demandes simultanées pour la même adresse rendent le même lien', async () => {
    const email = `double-invite-${Date.now()}@fumee.test`
    const jeton = await accessToken(hote.client)
    const appelle = () => fetch(fn('invite'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${jeton}` },
      body: JSON.stringify({ email }),
    })
    const [a, b] = await Promise.all([appelle(), appelle()])
    const corps = await Promise.all([a, b].map(async r => ({ statut: r.status, texte: await r.text() })))
    expect(corps.map(c => c.statut), JSON.stringify(corps)).toEqual([200, 200])
    expect(JSON.parse(corps[0].texte).token).toBe(JSON.parse(corps[1].texte).token)
    const { data } = await admin().from('invitation').select('id').eq('email', email)
    expect(data).toHaveLength(1)
  })
})
