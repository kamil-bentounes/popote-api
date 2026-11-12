/**
 * La fonction `rappels`, sans Deno : `sert(req, dépendances)` avec un faux client de base, un faux transport SMTP, une
 * fausse horloge. Ce qu'on éprouve ici, c'est ce que `index.ts` laisse à `service.ts` : le secret, le JWT, les codes
 * de réponse (401, 429, 500…), l'essai envoyé à l'adresse du jeton SEULEMENT, la limite d'un exemple par heure, l'en-tête
 * `List-Unsubscribe`, un seul transport par passe, et l'absence de secret ou d'adresse dans les journaux.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleDEssai, DELAI_ESSAI_MS, heureDEssai, MESSAGE_ESSAI_TROP_TOT, sert } from '../../supabase/functions/_shared/rappels/service.ts'
import type { ClientAdmin, Dependances, Transport } from '../../supabase/functions/_shared/rappels/service.ts'
import type { OptionsDuMail } from '../../supabase/functions/_shared/rappels/smtp.ts'
import { TYPES_DE_RAPPEL } from '../../supabase/functions/_shared/rappels/types.ts'
import type { RappelDu } from '../../supabase/functions/_shared/rappels/types.ts'
import { DELAI_ESSAI_CLIENT_MS } from './front-fige/lib/rappels.ts'

const BASE = 'https://kamil-bentounes.github.io/batchcooking'
const SECRET = 'le-secret-de-la-fonction-0123456789'
const JETON = 'jwt-de-kamil'
const MOI = { id: '00000000-0000-4000-8000-0000000000aa', email: 'kamil.moi@exemple.test', email_confirmed_at: '2026-10-01T08:00:00Z' }
const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`
/** Mardi 11 juin 2030, 19 h à Paris. */
const T0 = new Date('2030-06-11T17:00:00Z')

type Banc = ReturnType<typeof banc>
function banc(o: {
  env?: Record<string, string | undefined>
  dus?: RappelDu[] | Error
  profil?: { display_name: string | null } | null
  utilisateur?: { id: string; email: string | null; email_confirmed_at?: string | null } | null
  preparation?: Error
  envoi?: (opts: OptionsDuMail) => Error | undefined
  verifie?: Error
  ms?: number
  reservationsPrises?: Set<string>
} = {}) {
  const appels: string[] = []
  const rpcs: { nom: string; args: Record<string, unknown> }[] = []
  const journal: string[] = []
  const envoyes: OptionsDuMail[] = []
  const pris = o.reservationsPrises ?? new Set<string>()
  let horloge = T0.getTime()
  let transports = 0, fermes = 0, verifies = 0

  const client: ClientAdmin = {
    rpc: async (nom, args = {}) => {
      appels.push(nom); rpcs.push({ nom, args })
      switch (nom) {
        case 'prepare_les_rappels': return o.preparation ? { data: null, error: { message: o.preparation.message } } : { data: {}, error: null }
        case 'rappels_a_envoyer':
          if (o.dus instanceof Error) return { data: null, error: { message: o.dus.message } }
          return { data: o.dus ?? [], error: null }
        case 'reserve_rappel': {
          const k = `${args.p_user}|${args.p_type}|${(args.p_cles as string[]).join(',')}`
          if (pris.has(k)) return { data: false, error: null }
          pris.add(k); return { data: true, error: null }
        }
        case 'libere_rappel':
          pris.delete(`${args.p_user}|${args.p_type}|${(args.p_cles as string[]).join(',')}`)
          return { data: null, error: null }
        default: return { data: null, error: null }
      }
    },
    auth: {
      getUser: async (jwt) => ({ data: { user: jwt === JETON ? (o.utilisateur === undefined ? MOI : o.utilisateur) : null } }),
    },
    from: () => ({ select: () => ({ eq: () => ({ maybeSingle: async () => ({ data: o.profil === undefined ? { display_name: 'Kamil' } : o.profil, error: null }) }) }) }),
  }

  const env: Record<string, string | undefined> = {
    APP_BASE_URL: BASE, RAPPELS_SECRET: SECRET, GMAIL_USER: 'popote@exemple.test', GMAIL_APP_PASSWORD: 'abcd efgh ijkl mnop',
    SUPABASE_URL: 'http://base.test', SUPABASE_SERVICE_ROLE_KEY: 'cle-de-service-secrete', ...o.env,
  }
  const dep: Dependances = {
    env: n => env[n],
    creeClient: () => client,
    creeTransport: (user, pass) => {
      transports++
      expect(user).toBe('popote@exemple.test')
      expect(pass, 'les espaces du mot de passe d’application ne comptent pas').toBe('abcdefghijklmnop')
      const t: Transport = {
        envoie: async (opts) => {
          horloge += o.ms ?? 0
          const e = o.envoi?.(opts)
          if (e) throw e
          envoyes.push(opts)
        },
        verifie: async () => { verifies++; if (o.verifie) throw o.verifie },
        ferme: () => { fermes++ },
      }
      return t
    },
    maintenant: () => new Date(horloge),
    journal: l => journal.push(l),
  }
  return {
    dep, appels, rpcs, journal, envoyes, pris, env,
    get transports() { return transports }, get fermes() { return fermes }, get verifies() { return verifies },
    avance: (ms: number) => { horloge += ms },
  }
}

const requete = (o: { methode?: string; secret?: string | null; jeton?: string | null; corps?: unknown; entetes?: Record<string, string> } = {}) =>
  new Request('https://exemple.test/functions/v1/rappels', {
    method: o.methode ?? 'POST',
    headers: {
      ...(o.secret ? { 'x-rappels-secret': o.secret } : {}),
      ...(o.jeton ? { Authorization: `Bearer ${o.jeton}` } : {}),
      ...o.entetes,
    },
    body: o.methode === 'GET' ? undefined : typeof o.corps === 'string' ? o.corps : JSON.stringify(o.corps ?? {}),
  })

const du = (i: number, type = 'sortir_du_congelateur', donnees?: Record<string, unknown>): RappelDu => ({
  user_id: ID(100 + i), email: `membre${i}@exemple.test`, prenom: 'Kamil', type, cle: `cle-${i}`, cles: [`cle-${i}`],
  donnees: donnees ?? {
    jour: '2030-06-12',
    plats: [{ label: 'Wrap', recipe_id: null, image_url: null, n: 2, portion_ids: [ID(1), ID(2)], restant: 1,
      repas: [{ meal: 'diner', pour: ['Kamil', 'Thauba'] }] }],
  },
})
const erreurSmtp = (code: string, command: string, message: string) => Object.assign(new Error(message), { code, command })
const json = async (r: Response) => JSON.parse(await r.text())

afterEach(() => { vi.useRealTimers() })

describe('l’entrée', () => {
  it('seul POST passe ; OPTIONS répond au préambule', async () => {
    const b = banc()
    expect((await sert(requete({ methode: 'GET' }), b.dep)).status).toBe(405)
    expect((await sert(requete({ methode: 'OPTIONS' }), b.dep)).status).toBe(200)
    expect(b.appels).toEqual([])
  })

  it('sans APP_BASE_URL (ou avec une adresse fausse), 503 : un mail sans lien juste ne part pas', async () => {
    for (const v of [undefined, '', 'pas une adresse', 'javascript:alert(1)']) {
      const b = banc({ env: { APP_BASE_URL: v } })
      expect((await sert(requete({ secret: SECRET }), b.dep)).status, String(v)).toBe(503)
      expect(b.appels).toEqual([])
    }
  })
})

describe('la branche secret', () => {
  it('un secret faux, absent de l’environnement, vide : 401, 503, 401 — et la base n’est pas touchée', async () => {
    const b = banc()
    expect((await sert(requete({ secret: 'pas-le-bon' }), b.dep)).status).toBe(401)
    expect((await sert(requete({ secret: SECRET + 'x' }), b.dep)).status).toBe(401)
    expect((await sert(requete({ entetes: { 'x-rappels-secret': '' } }), b.dep)).status).toBe(401)
    expect(b.appels).toEqual([])
    const c = banc({ env: { RAPPELS_SECRET: undefined } })
    expect((await sert(requete({ secret: SECRET }), c.dep)).status).toBe(503)
    expect((await sert(requete({ entetes: { 'x-rappels-secret': '' } }), banc({ env: { RAPPELS_SECRET: '' } }).dep)).status).toBe(503)
    expect(c.appels).toEqual([])
  })

  it('le bon secret : prépare, lit, réserve, envoie, note — dans cet ordre, avec UN seul transport fermé à la fin', async () => {
    const b = banc({ dus: [du(1), du(2), du(3)] })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(200)
    expect(await json(r)).toEqual({ dus: 3, envoyes: 3, ignores: 0, echecs: 0, reportes: 0 })
    expect(b.appels).toEqual([
      'prepare_les_rappels', 'rappels_a_envoyer',
      'reserve_rappel', 'reserve_rappel', 'reserve_rappel',
      'note_la_passe',
    ])
    expect(b.rpcs.at(-1)!.args).toEqual({ p_statut: 'ok', p_dus: 3, p_envoyes: 3, p_echecs: 0 })
    expect(b.transports, 'un transport par passe').toBe(1)
    expect(b.verifies).toBe(1)
    expect(b.fermes).toBe(1)
    expect(b.envoyes.map(e => e.to)).toEqual(['membre1@exemple.test', 'membre2@exemple.test', 'membre3@exemple.test'])
    // Les mois du budget s'ouvrent à l'instant de la passe.
    expect(b.rpcs[0].args).toEqual({ p_maintenant: T0.toISOString() })
  })

  it('l’en-tête List-Unsubscribe mène à l’écran des rappels, et l’expéditeur est « Popote »', async () => {
    const b = banc({ dus: [du(1)] })
    await sert(requete({ secret: SECRET }), b.dep)
    expect(b.envoyes[0].headers).toEqual({ 'List-Unsubscribe': `<${BASE}/rappels>` })
    expect(b.envoyes[0].from).toEqual({ name: 'Popote', address: 'popote@exemple.test' })
    expect(b.envoyes[0].html).toContain('<!doctype html>')
  })

  it('rien de dû : 200, pas de transport ouvert, mais le passage est noté', async () => {
    const b = banc({ dus: [] })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(200)
    expect(b.transports).toBe(0)
    expect(b.verifies).toBe(0)
    expect(b.rpcs.at(-1)).toEqual({ nom: 'note_la_passe', args: { p_statut: 'ok', p_dus: 0, p_envoyes: 0, p_echecs: 0 } })
  })

  it('500 quand un rappel échoue : le nombre, jamais le contenu ni une adresse', async () => {
    const b = banc({
      dus: [du(1), du(2)],
      envoi: o => (o.to.startsWith('membre1') ? erreurSmtp('EAUTH', 'AUTH PLAIN', 'Invalid login') : undefined),
    })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(500)
    const corps = await r.clone().text()
    expect(JSON.parse(corps)).toEqual({ dus: 2, envoyes: 1, ignores: 0, echecs: 1, reportes: 0 })
    expect(corps).not.toMatch(/@|exemple\.test|Wrap|Kamil|Invalid login/)
    expect(b.rpcs.at(-1)!.args).toEqual({ p_statut: 'echecs', p_dus: 2, p_envoyes: 1, p_echecs: 1 })
    // L'échec était sûrement avant DATA : la réservation est rendue ; l'autre mail est parti.
    expect(b.appels).toContain('libere_rappel')
  })

  it('un envoi ambigu : 500 aussi, mais la réservation reste', async () => {
    const b = banc({ dus: [du(1)], envoi: () => erreurSmtp('ETIMEDOUT', 'CONN', 'Timeout') })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(500)
    expect(b.appels).not.toContain('libere_rappel')
    expect(b.pris.size).toBe(1)
  })

  it('le transport en panne : 500, rien réservé, rien envoyé', async () => {
    const b = banc({ dus: [du(1), du(2)], verifie: erreurSmtp('EAUTH', 'AUTH PLAIN', 'Invalid login') })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(500)
    expect(await json(r)).toMatchObject({ dus: 2, envoyes: 0, echecs: 2 })
    expect(b.appels).not.toContain('reserve_rappel')
    expect(b.fermes).toBe(1)
  })

  it('les identifiants Gmail absents : 500, rien n’est réservé', async () => {
    const b = banc({ dus: [du(1)], env: { GMAIL_USER: undefined } })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(500)
    expect(b.appels).not.toContain('reserve_rappel')
  })

  it('la lecture de ce qui est dû échoue : 500, rien n’est parti', async () => {
    const b = banc({ dus: new Error('base injoignable') })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(500)
    expect(b.envoyes).toEqual([])
    expect(b.rpcs.at(-1)!.args).toMatchObject({ p_statut: 'erreur' })
  })

  it('la préparation des mois échoue : les rappels partent quand même, et la passe répond 500', async () => {
    const b = banc({ dus: [du(1)], preparation: new Error('boum') })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(r.status).toBe(500)
    expect(await json(r)).toMatchObject({ envoyes: 1, echecs: 1 })
    expect(b.envoyes).toHaveLength(1)
  })

  it('un budget de temps de 20 s : les suivants partent à la passe suivante', async () => {
    const b = banc({ dus: Array.from({ length: 6 }, (_, i) => du(i)), ms: 8_000 })
    const r = await sert(requete({ secret: SECRET }), b.dep)
    expect(await json(r)).toMatchObject({ dus: 6, envoyes: 3, reportes: 3, echecs: 0 })
    expect(r.status, 'un report n’est pas une panne').toBe(200)
  })
})

describe('l’essai', () => {
  it('sans jeton, avec un jeton qui ne mène à personne, ou sans adresse : 401', async () => {
    const b = banc()
    expect((await sert(requete({ corps: { essai: 'choisir_les_repas' } }), b.dep)).status).toBe(401)
    expect((await sert(requete({ jeton: 'un-autre-jeton', corps: { essai: 'choisir_les_repas' } }), b.dep)).status).toBe(401)
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), banc({ utilisateur: { id: MOI.id, email: null } }).dep)).status).toBe(401)
    // Une adresse jamais confirmée : 403, et rien n'est réservé ni envoyé.
    const nonConfirme = banc({ utilisateur: { id: MOI.id, email: MOI.email, email_confirmed_at: null } })
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), nonConfirme.dep)).status).toBe(403)
    expect(nonConfirme.appels).not.toContain('reserve_rappel')
    expect(b.envoyes).toEqual([])
  })

  it('quel rappel ? 400 ; aucun foyer 403 ; corps trop gros 413 ; JSON cassé 400', async () => {
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'spam' } }), banc().dep)).status).toBe(400)
    expect((await sert(requete({ jeton: JETON, corps: {} }), banc().dep)).status).toBe(400)
    expect((await sert(requete({ jeton: JETON, corps: '{pas du json' }), banc().dep)).status).toBe(400)
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), banc({ profil: null }).dep)).status).toBe(403)
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' }, entetes: { 'content-length': '5000' } }), banc().dep)).status).toBe(413)
  })

  it('un exemple part à l’adresse du JETON seulement, jamais à une adresse du corps', async () => {
    const b = banc()
    const r = await sert(requete({
      jeton: JETON,
      corps: { essai: 'sortir_du_congelateur', to: 'pirate@exemple.test', email: 'pirate@exemple.test', a: 'pirate@exemple.test', cc: 'pirate@exemple.test' },
    }), b.dep)
    expect(r.status).toBe(200)
    expect(await json(r)).toEqual({ ok: true })
    expect(b.envoyes).toHaveLength(1)
    expect(b.envoyes[0].to).toBe(MOI.email)
    expect(JSON.stringify(b.envoyes[0])).not.toContain('pirate')
    expect(b.envoyes[0].subject.startsWith('[Exemple] ')).toBe(true)
    expect(b.envoyes[0].headers).toEqual({ 'List-Unsubscribe': `<${BASE}/rappels>` })
    expect(b.transports).toBe(1)
    expect(b.fermes).toBe(1)
  })

  it('un exemple n’écrit pas un vrai rappel : il ne lit rien du foyer, il réserve seulement sa propre clé', async () => {
    const b = banc()
    await sert(requete({ jeton: JETON, corps: { essai: 'barquette_perime' } }), b.dep)
    expect(b.appels).toEqual(['reserve_rappel'])
    expect(b.rpcs[0].args).toEqual({ p_user: MOI.id, p_type: 'barquette_perime', p_cles: [cleDEssai('barquette_perime', T0)] })
    expect(cleDEssai('barquette_perime', T0)).toBe('essai:barquette_perime:2030-06-11T17')
  })

  it('un exemple par type, par membre et par heure : le second reçoit 429 et une phrase française', async () => {
    const b = banc()
    const essai = (type: string) => sert(requete({ jeton: JETON, corps: { essai: type } }), b.dep)
    expect((await essai('choisir_les_repas')).status).toBe(200)
    const trop = await essai('choisir_les_repas')
    expect(trop.status).toBe(429)
    expect(await trop.text()).toBe(MESSAGE_ESSAI_TROP_TOT)
    expect(MESSAGE_ESSAI_TROP_TOT).toMatch(/exemple.*heure/)
    expect(b.envoyes, 'le second n’est pas parti').toHaveLength(1)
    // Un autre type, la même heure : permis.
    expect((await essai('noter_les_depenses')).status).toBe(200)
    expect(b.envoyes).toHaveLength(2)
    // À l'heure suivante : permis de nouveau.
    b.avance(3_600_000)
    expect((await essai('choisir_les_repas')).status).toBe(200)
    expect(b.envoyes).toHaveLength(3)
    expect(heureDEssai(new Date('2030-06-11T17:59:59Z'))).toBe('2030-06-11T17')
    expect(heureDEssai(new Date('2030-06-11T18:00:00Z'))).toBe('2030-06-11T18')
  })

  it('un autre membre a sa propre limite', async () => {
    const pris = new Set<string>()
    const a = banc({ reservationsPrises: pris })
    const c = banc({ reservationsPrises: pris, utilisateur: { id: '00000000-0000-4000-8000-0000000000bb', email: 'thauba@exemple.test', email_confirmed_at: '2026-10-01T08:00:00Z' } })
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), a.dep)).status).toBe(200)
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), c.dep)).status).toBe(200)
    expect(c.envoyes[0].to).toBe('thauba@exemple.test')
  })

  it('un envoi qui échoue AVANT les données rend la clé : on peut réessayer tout de suite', async () => {
    let panne = true
    const b = banc({ envoi: () => (panne ? erreurSmtp('EAUTH', 'AUTH PLAIN', 'Invalid login') : undefined) })
    const essai = () => sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), b.dep)
    const r = await essai()
    expect(r.status).toBe(502)
    expect(await r.text()).toBe('Le mail n’a pas pu partir. Réessaie dans un instant.')
    expect(b.pris.size).toBe(0)
    panne = false
    expect((await essai()).status).toBe(200)
  })

  it('un envoi ambigu garde la clé : pas de doublon d’exemple', async () => {
    const b = banc({ envoi: () => erreurSmtp('ECONNECTION', 'CONN', 'Connection closed unexpectedly') })
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), b.dep)).status).toBe(502)
    expect(b.pris.size).toBe(1)
  })

  it(`un envoi suspendu s’arrête au bout de ${DELAI_ESSAI_MS / 1000} s : 502, la clé reste (le mail est peut-être parti)`, async () => {
    vi.useFakeTimers()
    const b = banc()
    b.dep.creeTransport = () => ({ envoie: () => new Promise(() => {}), verifie: async () => {}, ferme: () => {} })
    const p = sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), b.dep)
    await vi.advanceTimersByTimeAsync(DELAI_ESSAI_MS + 100)
    expect((await p).status).toBe(502)
    expect(b.pris.size).toBe(1)
  })

  it('le délai du client est au moins celui du serveur', () => {
    expect(DELAI_ESSAI_CLIENT_MS).toBeGreaterThanOrEqual(DELAI_ESSAI_MS)
  })

  it('les mails ne sont pas configurés : 503, aucune clé réservée', async () => {
    const b = banc({ env: { GMAIL_APP_PASSWORD: undefined } })
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }), b.dep)).status).toBe(503)
    expect(b.appels).toEqual([])
  })

  it('chaque type a son exemple', async () => {
    const b = banc()
    for (const t of TYPES_DE_RAPPEL) expect((await sert(requete({ jeton: JETON, corps: { essai: t } }), b.dep)).status, t).toBe(200)
    expect(b.envoyes).toHaveLength(TYPES_DE_RAPPEL.length)
    for (const e of b.envoyes) expect(e.html).not.toMatch(/undefined|NaN|\[object/)
  })

  it('un prénom vide : le mail dit « toi »', async () => {
    const b = banc({ profil: { display_name: '   ' } })
    expect((await sert(requete({ jeton: JETON, corps: { essai: 'sortir_du_congelateur' } }), b.dep)).status).toBe(200)
    expect(b.envoyes[0].text).toContain('pour vous deux')
  })
})

describe('les journaux', () => {
  it('ni secret, ni adresse, ni clé de service, ni contenu — quoi qu’il arrive', async () => {
    const scenes: Banc[] = []
    const lance = async (b: Banc, r: Request) => { scenes.push(b); return sert(r, b.dep) }
    await lance(banc({ dus: [du(1), du(2)], envoi: o => (o.to.startsWith('membre1') ? erreurSmtp('EAUTH', 'AUTH PLAIN', `Invalid login ${o.to} abcd efgh`) : undefined) }), requete({ secret: SECRET }))
    await lance(banc({ dus: [du(1)], preparation: new Error(`boum ${SECRET}`) }), requete({ secret: SECRET }))
    await lance(banc({ dus: new Error(`illisible ${SECRET}`) }), requete({ secret: SECRET }))
    await lance(banc({ dus: [du(1)], verifie: erreurSmtp('ECONNECTION', 'CONN', `connect ECONNREFUSED popote@exemple.test`) }), requete({ secret: SECRET }))
    await lance(banc({ envoi: () => erreurSmtp('EAUTH', 'AUTH PLAIN', `Invalid login ${MOI.email}`) }), requete({ jeton: JETON, corps: { essai: 'choisir_les_repas' } }))
    await lance(banc(), requete({ secret: 'mauvais' }))
    const tout = scenes.flatMap(b => b.journal).join('\n')
    expect(tout.length).toBeGreaterThan(40)
    for (const interdit of [SECRET, 'cle-de-service-secrete', 'abcd', 'efgh', '@', 'exemple.test', 'Wrap', 'Kamil', 'membre', JETON]) {
      expect(tout, interdit).not.toContain(interdit)
    }
  })
})
