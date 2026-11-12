/**
 * La photo d'un plat (migration 0121) : un seau public en lecture, des écritures bornées au foyer,
 * à la taille et au type.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'

const SEAU = 'photos-des-plats'
/** Le plus petit JPEG qu'un navigateur ouvre. */
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xdb, 0x00, 0x43, 0x00, 0xff, 0xd9])

let alice: Actor
let bob: Actor
beforeAll(async () => {
  alice = await makeActor('photo-alice')
  bob = await makeActor('photo-bob')
})

const chemin = (a: Actor, nom = `${Date.now()}-${Math.random().toString(36).slice(2)}.jpg`) =>
  `${a.householdId}/${nom}`

describe('le seau des photos de plats', () => {
  it('existe, public, borné en taille et en type', async () => {
    const { data, error } = await admin().storage.getBucket(SEAU)
    expect(error).toBeNull()
    expect(data!.public).toBe(true)
    expect(data!.file_size_limit).toBe(2 * 1024 * 1024)
    expect(data!.allowed_mime_types).toEqual(['image/jpeg', 'image/png', 'image/webp'])
  })

  it('un foyer écrit dans SON dossier, et la photo se lit par son adresse publique, sans jeton', async () => {
    const p = chemin(alice)
    const { error } = await alice.client.storage.from(SEAU).upload(p, JPEG, { contentType: 'image/jpeg' })
    expect(error).toBeNull()
    const { data } = alice.client.storage.from(SEAU).getPublicUrl(p)
    const res = await fetch(data.publicUrl)
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toContain('image/jpeg')
  })

  it('refuse le dossier d’un autre foyer', async () => {
    const { error } = await alice.client.storage.from(SEAU)
      .upload(chemin(bob), JPEG, { contentType: 'image/jpeg' })
    expect(error, 'un foyer écrit chez un autre').not.toBeNull()
  })

  it('refuse un type qui n’est pas une photo (SVG, HTML) et une photo trop lourde', async () => {
    const svg = await alice.client.storage.from(SEAU)
      .upload(chemin(alice, 'x.svg'), new Blob(['<svg onload="alert(1)"/>']), { contentType: 'image/svg+xml' })
    expect(svg.error, 'le SVG passe').not.toBeNull()
    const lourde = await alice.client.storage.from(SEAU)
      .upload(chemin(alice), new Uint8Array(2 * 1024 * 1024 + 10), { contentType: 'image/jpeg' })
    expect(lourde.error, 'plus de 2 Mo passe').not.toBeNull()
  })

  it('refuse un sous-dossier, un nom caché et tout nom qui contient « .. » (un seul niveau sous le foyer)', async () => {
    for (const nom of ['sous/dossier.jpg', '.cache.jpg', '..jpg', 'a..b.jpg']) {
      const { error } = await alice.client.storage.from(SEAU)
        .upload(chemin(alice, nom), JPEG, { contentType: 'image/jpeg' })
      expect(error, `« ${nom} » est accepté`).not.toBeNull()
    }
    // Et le nom simple passe toujours.
    const { error } = await alice.client.storage.from(SEAU)
      .upload(chemin(alice, 'recette-1730000000000.jpg'), JPEG, { contentType: 'image/jpeg' })
    expect(error).toBeNull()
  })

  it('refuse l’écriture sans compte', async () => {
    const { createClient } = await import('@supabase/supabase-js')
    const anonyme = createClient(process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!,
      { auth: { persistSession: false } })
    const { error } = await anonyme.storage.from(SEAU)
      .upload(chemin(alice), JPEG, { contentType: 'image/jpeg' })
    expect(error).not.toBeNull()
  })

  it('un foyer ne retire pas la photo d’un autre, et retire la sienne', async () => {
    const p = chemin(alice)
    await alice.client.storage.from(SEAU).upload(p, JPEG, { contentType: 'image/jpeg' })
    await bob.client.storage.from(SEAU).remove([p])
    const encore = await admin().storage.from(SEAU).list(alice.householdId)
    expect(encore.data!.some(o => `${alice.householdId}/${o.name}` === p), 'Bob a retiré la photo d’Alice').toBe(true)
    const { error } = await alice.client.storage.from(SEAU).remove([p])
    expect(error).toBeNull()
    const apres = await admin().storage.from(SEAU).list(alice.householdId)
    expect(apres.data!.some(o => `${alice.householdId}/${o.name}` === p)).toBe(false)
  })

  it('la photo se pose sur SA recette, à l’adresse de SON dossier — et nulle part ailleurs', async () => {
    const pose = (a: Actor, recette: string, url: string | null) =>
      a.client.from('recipe').update({ image_url: url }).eq('id', recette).select()
    const adresse = (a: Actor, nom = 'p.jpg') => a.client.storage.from(SEAU).getPublicUrl(`${a.householdId}/${nom}`).data.publicUrl

    const { data: sienne } = await admin().from('recipe').insert({
      title: 'Plat à photographier', origin: 'manuelle', owner_household_id: alice.householdId,
    }).select().single()
    const { data: autre } = await admin().from('recipe').insert({
      title: 'Plat de Bob', origin: 'manuelle', owner_household_id: bob.householdId,
    }).select().single()
    const { data: catalogue } = await admin().from('recipe').insert({
      title: 'Plat du catalogue', origin: 'importee', source_url: `https://x/${Date.now()}-${Math.random()}`,
      image_url: 'https://exemple.test/site.jpg',
    }).select().single()

    const ok = await pose(alice, sienne!.id, adresse(alice))
    expect(ok.error, 'le foyer ne peut pas poser la photo de SA recette').toBeNull()
    expect(ok.data).toHaveLength(1)
    expect((await pose(alice, sienne!.id, null)).error, 'retirer sa photo').toBeNull()

    // L'adresse de n'importe qui, ou d'ailleurs : refus (tg_recipe_photo, 0092).
    for (const url of [
      'https://evil.example/storage/v1/object/public/photos-des-plats/' + alice.householdId + '/p.jpg',
      'https://exemple.test/p.jpg',
      adresse(bob),                              // le dossier d'un autre foyer
      adresse(alice, 'a/../b.jpg'),              // un chemin, pas un fichier
      adresse(alice) + '?x=1',
      adresse(alice, '.'),                       // « . » et « .. » ne sont pas des noms de fichier
      adresse(alice, '..'),
      adresse(alice, 'a..b.jpg'),
      adresse(alice, '.cache.jpg'),
    ]) {
      const r = await pose(alice, sienne!.id, url)
      expect(r.error, `${url} est accepté`).not.toBeNull()
    }
    // La recette d'un autre foyer, et celle du catalogue : jamais.
    expect((await pose(alice, autre!.id, adresse(alice))).data ?? [], 'photo posée chez Bob').toHaveLength(0)
    expect((await pose(alice, catalogue!.id, adresse(alice))).error, 'photo posée sur le catalogue').not.toBeNull()
    expect((await pose(alice, catalogue!.id, null)).error, 'photo du catalogue retirée').not.toBeNull()
  })
})
