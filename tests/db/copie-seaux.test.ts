/**
 * La copie des seaux Storage pour la sauvegarde (ops/sauvegarde/copie-seaux.mjs) et son pendant,
 * le dépôt de la restauration (depose-seaux.mjs), contre la pile locale :
 *
 *  · deux objets (l'un dans un dossier) déposés dans un seau d'essai donnent deux fichiers identiques
 *    et deux lignes d'index, avec le type et la taille ;
 *  · après effacement des objets, le dépôt les remet à l'identique (contenu et type) ;
 *  · la liste se parcourt page par page et descend dans les dossiers ;
 *  · un nom qui voudrait sortir du dossier de copie est refusé ; deux noms qui se confondent sur disque
 *    (`a` et `a/b`, `a//b`) aussi, avec une erreur claire ;
 *  · la copie est comparée, nom et taille, à la liste de l'instantané de la base ;
 *  · une clé refusée donne une erreur sans nom d'objet.
 */
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { admin } from './helpers/db'
// @ts-expect-error — module JavaScript sans types
import { cheminSous, copier, listerObjets, registreDeNoms } from '../../ops/sauvegarde/copie-seaux.mjs'
// @ts-expect-error — module JavaScript sans types
import { comparer } from '../../ops/sauvegarde/verifie-seaux.mjs'
// @ts-expect-error — module JavaScript sans types
import { deposer } from '../../ops/sauvegarde/depose-seaux.mjs'
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
})

// Chaque test part du même état, quel que soit l'ordre : les deux objets sont là, et lui seul les déplace.
beforeEach(async () => {
  await deposeLesObjets()
})

afterAll(async () => {
  await storage.from(seau).remove(objets.map((o) => o.nom))
  await storage.deleteBucket(seau)
  await rm(travail, { recursive: true, force: true })
})

let compteur = 0
const nouveauDossier = () => join(travail, `copie-${++compteur}`)

const lit = async (dossier: string) =>
  Object.fromEntries(await Promise.all(objets.map(async (o) =>
    [o.nom, await readFile(join(dossier, 'fichiers', seau, o.nom), 'utf8')] as const)))

describe('la copie', () => {
  it('retrouve les deux fichiers, leur index, leur type et leur taille', async () => {
    const dossier = nouveauDossier()
    const bilan = await copier(client, dossier, { seaux: [seau] })

    expect(bilan).toEqual({ seaux: 1, objets: 2, octets: objets.reduce((n, o) => n + o.contenu.length, 0) })
    expect(await lit(dossier)).toEqual(Object.fromEntries(objets.map((o) => [o.nom, o.contenu])))
    const index = (await readFile(join(dossier, 'index.jsonl'), 'utf8')).trim().split('\n').map((l) => JSON.parse(l))
    expect(index).toEqual(expect.arrayContaining(objets.map((o) => (
      { seau, nom: o.nom, octets: o.contenu.length, type: o.type }))))
    expect(index).toHaveLength(2)
  })

  it('refuse un dossier de copie qui n’est pas vide', async () => {
    const dossier = nouveauDossier()
    await copier(client, dossier, { seaux: [seau] })
    await expect(copier(client, dossier, { seaux: [seau] })).rejects.toThrow(/doit être vide/)
  })

  it('parcourt la liste page par page et descend dans les dossiers', async () => {
    const vus: string[] = []
    for await (const o of listerObjets(client, seau, '', 1)) vus.push(o.nom)
    expect(vus.sort()).toEqual(objets.map((o) => o.nom).sort())
  })
})

describe('le dépôt', () => {
  it('remet les objets effacés, à l’identique (contenu et type)', async () => {
    const dossier = nouveauDossier()
    await copier(client, dossier, { seaux: [seau] })
    expect((await storage.from(seau).remove(objets.map((o) => o.nom))).error).toBeNull()
    expect((await storage.from(seau).list()).data).toHaveLength(0)

    const bilan = await deposer(client, dossier)

    expect(bilan.objets).toBe(2)
    for (const o of objets) {
      const { data, error } = await storage.from(seau).download(o.nom)
      expect(error).toBeNull()
      expect(await data!.text()).toBe(o.contenu)
      // Le type enregistré par Storage, pas celui que le téléchargement complète d'un charset.
      expect((await storage.from(seau).info(o.nom)).data?.contentType).toBe(o.type)
    }
  })

  it('refuse un fichier dont la taille n’est plus celle de l’index', async () => {
    const dossier = nouveauDossier()
    await copier(client, dossier, { seaux: [seau] })
    await writeFile(join(dossier, 'fichiers', seau, 'plat.json'), 'trop court')
    await expect(deposer(client, dossier)).rejects.toThrow(/tronqué/)
  })
})

describe('les noms qui se confondent sur disque', () => {
  it('refuse un objet et un dossier du même nom, dans les deux ordres', () => {
    const parObjetPuisDossier = registreDeNoms('seau')
    parObjetPuisDossier.ajouter('a')
    expect(() => parObjetPuisDossier.ajouter('a/b')).toThrow(/se confondent sur disque/)

    const parDossierPuisObjet = registreDeNoms('seau')
    parDossierPuisObjet.ajouter('x/y/z')
    expect(() => parDossierPuisObjet.ajouter('x/y')).toThrow(/se confondent sur disque/)
    expect(() => parDossierPuisObjet.ajouter('x/y/z')).toThrow(/se confondent sur disque/)
  })

  it.each(['a//b', 'a/', './a', 'a/./b', '../a', '/a', ''])('refuse le nom %j, qui ne reste pas le même fichier', (nom) => {
    expect(() => registreDeNoms('seau').ajouter(nom)).toThrow(ErreurStorage)
    expect(() => registreDeNoms('seau').ajouter(nom)).toThrow(/même fichier sur disque/)
  })

  it('accepte des noms voisins qui restent distincts ; l’erreur cite le seau, jamais un nom', () => {
    const registre = registreDeNoms('seau')
    for (const nom of ['a', 'ab', 'a.b', 'sous/a', 'sous/ab', 'sous2/a']) registre.ajouter(nom)
    const erreur = (() => { try { registre.ajouter('sous/a/c') } catch (e) { return e as Error } })()
    expect(erreur?.message).toContain('seau')
    expect(erreur?.message).not.toContain('sous')
  })
})

describe('un seau réel dont deux objets se confondent', () => {
  it('fait échouer la copie avec une erreur claire, sans nom d’objet', async () => {
    const piege = `${seau}-piege`
    expect((await storage.createBucket(piege, { public: false })).error).toBeNull()
    try {
      for (const nom of ['a', 'a/b']) {
        expect((await storage.from(piege).upload(nom, Buffer.from('x'), { upsert: true })).error).toBeNull()
      }
      const erreur = await copier(client, nouveauDossier(), { seaux: [piege] }).catch((e: unknown) => e)
      expect(erreur).toBeInstanceOf(ErreurStorage)
      expect((erreur as Error).message).toMatch(/se confondent sur disque/)
      expect((erreur as Error).message).not.toMatch(/a\/b/)
    } finally {
      await storage.from(piege).remove(['a', 'a/b'])
      await storage.deleteBucket(piege)
    }
  })
})

describe('la comparaison à l’instantané', () => {
  const ecrit = async (dossier: string, copies: object[], instantane: object[]) => {
    await mkdir(dossier, { recursive: true })
    await writeFile(join(dossier, 'index.jsonl'), copies.map((o) => JSON.stringify(o)).join('\n') + '\n')
    await writeFile(join(dossier, 'instantane.jsonl'), instantane.map((o) => JSON.stringify(o)).join('\n') + '\n')
    return join(dossier, 'instantane.jsonl')
  }

  it('ne voit aucun écart quand noms et tailles concordent (taille inconnue ignorée)', async () => {
    const dossier = nouveauDossier()
    const fichier = await ecrit(dossier,
      [{ seau: 's', nom: 'a', octets: 3 }, { seau: 's', nom: 'b/c', octets: 5 }],
      [{ seau: 's', nom: 'b/c', octets: 5 }, { seau: 's', nom: 'a', octets: null }])
    expect(await comparer(dossier, fichier)).toEqual({ manquants: 0, enTrop: 0, tailles: 0 })
  })

  it('compte un objet manquant, un objet en trop et une taille différente', async () => {
    const dossier = nouveauDossier()
    const fichier = await ecrit(dossier,
      [{ seau: 's', nom: 'a', octets: 3 }, { seau: 's', nom: 'nouveau', octets: 1 }, { seau: 's', nom: 'c', octets: 9 }],
      [{ seau: 's', nom: 'a', octets: 4 }, { seau: 's', nom: 'disparu', octets: 2 }, { seau: 's', nom: 'c', octets: 9 }])
    expect(await comparer(dossier, fichier)).toEqual({ manquants: 1, enTrop: 1, tailles: 1 })
  })

  it('distingue deux seaux qui portent le même nom d’objet', async () => {
    const dossier = nouveauDossier()
    const fichier = await ecrit(dossier,
      [{ seau: 's1', nom: 'a', octets: 3 }, { seau: 's1', nom: 'a', octets: 3 }],
      [{ seau: 's1', nom: 'a', octets: 3 }, { seau: 's2', nom: 'a', octets: 3 }])
    expect(await comparer(dossier, fichier)).toEqual({ manquants: 1, enTrop: 0, tailles: 0 })
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
