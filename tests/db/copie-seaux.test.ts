/**
 * La copie des seaux Storage pour la sauvegarde (ops/sauvegarde/copie-seaux.mjs), contre la pile locale :
 *
 *  · deux objets (l'un dans un dossier) déposés dans un seau d'essai donnent deux fichiers identiques
 *    et deux lignes d'index, avec le type et la taille ;
 *  · la liste se parcourt page par page et descend dans les dossiers ;
 *  · un nom qui voudrait sortir du dossier de copie est refusé ;
 *  · une clé refusée donne une erreur sans nom d'objet.
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
// @ts-expect-error — module JavaScript sans types
import { cheminSous, copier, listerObjets } from '../../ops/sauvegarde/copie-seaux.mjs'
// @ts-expect-error — module JavaScript sans types
import { ErreurStorage, lireEnvironnement } from '../../ops/sauvegarde/storage.mjs'

const seau = `test-sauvegarde-${Date.now()}`
const objets = [
  { nom: 'dossier/photo.txt', contenu: 'premier objet, dans un dossier', type: 'text/plain' },
  { nom: 'plat.json', contenu: '{"deuxieme":"objet"}', type: 'application/json' },
]
const storage = admin().storage
const client = lireEnvironnement({
  SUPABASE_URL: process.env.VITE_SUPABASE_URL,
  SUPABASE_SECRET_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
})
let travail: string

const deposeLesObjets = async () => {
  for (const o of objets) {
    const { error } = await storage.from(seau).upload(o.nom, Buffer.from(o.contenu), { contentType: o.type, upsert: true })
    if (error) throw error
  }
}

beforeAll(async () => {
  travail = await mkdtemp(join(tmpdir(), 'copie-seaux-'))
  const { error } = await storage.createBucket(seau, { public: false })
  if (error) throw error
  await deposeLesObjets()
})

afterAll(async () => {
  await storage.from(seau).remove(objets.map((o) => o.nom))
  await storage.deleteBucket(seau)
  await rm(travail, { recursive: true, force: true })
})

const lit = async (dossier: string) =>
  Object.fromEntries(await Promise.all(objets.map(async (o) =>
    [o.nom, await readFile(join(dossier, 'fichiers', seau, o.nom), 'utf8')] as const)))

describe('la copie', () => {
  it('retrouve les deux fichiers, leur index, leur type et leur taille', async () => {
    const dossier = join(travail, 'copie')
    const bilan = await copier(client, dossier, { seaux: [seau] })

    expect(bilan).toEqual({ seaux: 1, objets: 2, octets: objets.reduce((n, o) => n + o.contenu.length, 0) })
    expect(await lit(dossier)).toEqual(Object.fromEntries(objets.map((o) => [o.nom, o.contenu])))
    const index = (await readFile(join(dossier, 'index.jsonl'), 'utf8')).trim().split('\n').map((l) => JSON.parse(l))
    expect(index).toEqual(expect.arrayContaining(objets.map((o) => (
      { seau, nom: o.nom, octets: o.contenu.length, type: o.type }))))
    expect(index).toHaveLength(2)
  })

  it('refuse un dossier de copie qui n’est pas vide', async () => {
    const dossier = join(travail, 'copie')
    await expect(copier(client, dossier, { seaux: [seau] })).rejects.toThrow(/doit être vide/)
  })

  it('parcourt la liste page par page et descend dans les dossiers', async () => {
    const vus: string[] = []
    for await (const o of listerObjets(client, seau, '', 1)) vus.push(o.nom)
    expect(vus.sort()).toEqual(objets.map((o) => o.nom).sort())
  })
})

describe('les refus', () => {
  it('refuse un nom d’objet qui sort du dossier de copie', () => {
    expect(() => cheminSous(travail, 'seau', '../../etc/passwd')).toThrow(ErreurStorage)
    expect(cheminSous(travail, 'seau', 'a/b.txt')).toBe(join(travail, 'seau', 'a', 'b.txt'))
  })

  it('donne une erreur de statut sans nom d’objet quand la clé est refusée', async () => {
    const mauvais = { ...client, cle: 'sb_secret_pas_la_bonne' }
    const erreur = await copier(mauvais, join(travail, 'refus')).catch((e: unknown) => e)
    expect(erreur).toBeInstanceOf(ErreurStorage)
    expect((erreur as { statut: number }).statut).toBeGreaterThanOrEqual(400)
    expect((erreur as Error).message).not.toContain(seau)
  })

  it('exige l’URL et la clé', () => {
    expect(() => lireEnvironnement({})).toThrow(/SUPABASE_URL, SUPABASE_SECRET_KEY/)
  })
})
