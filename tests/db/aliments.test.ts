/**
 * Nos aliments (migration 0124) : ce que le foyer mange, avec ses vraies valeurs pour 100 g.
 *
 *  · la RLS : un autre foyer ne voit rien, n'écrit rien, ne change rien, ne retire rien ;
 *  · les bornes : on ne range pas une étiquette lue en kJ, ni un poids nul, ni deux fois le même nom ;
 *  · le geste : une unité (« un pot ») s'écrit dans `meal_extra` avec les vraies valeurs, par
 *    `choisir_un_repas`, et compte dans le bilan comme un repère ;
 *  · l'export RGPD les emporte.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { admin, makeActor, type Actor } from './helpers/db'
import { choixDeLUnite } from './front-fige/lib/aliments/calcul'
import { phraseDeLEcriture } from './front-fige/lib/aliments/brouillon'

let kamil: Actor
let autre: Actor
const db = admin()

beforeAll(async () => {
  kamil = await makeActor('aliments-kamil')
  autre = await makeActor('aliments-autre')
})

/* Le yaourt dessert protéiné du foyer : 76 kcal, 10 g de protéines… pour 100 g, dans un pot de 125 g. */
const yaourt = (o: Record<string, unknown> = {}) => ({
  label: 'Yaourt dessert protéiné', kcal_100g: 76, protein_100g: 10, carb_100g: 5.6, fat_100g: 1.4, fiber_100g: 0,
  unite: 'pot', unite_g: 125, ...o,
})
let n = 0
const nom = (base = 'Aliment') => `${base} ${Date.now()}-${++n}`
const cree = (a: Actor, o: Record<string, unknown> = {}) =>
  a.client.from('aliment').insert({ household_id: a.householdId, ...yaourt({ label: nom('Yaourt') }), ...o }).select().single()

describe('la RLS du foyer', () => {
  it('un foyer lit les siens, jamais ceux d’un autre', async () => {
    const mien = (await cree(kamil)).data!
    const leur = (await cree(autre)).data!
    const { data: vus } = await kamil.client.from('aliment').select('id')
    const ids = (vus ?? []).map(x => x.id)
    expect(ids).toContain(mien.id)
    expect(ids, 'un aliment d’un autre foyer est visible').not.toContain(leur.id)
    const { data: direct } = await kamil.client.from('aliment').select('id').eq('id', leur.id)
    expect(direct).toHaveLength(0)
  })

  it('on n’écrit pas au nom d’un autre foyer', async () => {
    const { error } = await kamil.client.from('aliment')
      .insert({ household_id: autre.householdId, ...yaourt({ label: nom() }) })
    expect(error?.message).toMatch(/row-level security/)
  })

  it('on ne déplace pas un aliment vers un autre foyer, et on ne modifie ni ne retire celui d’un autre', async () => {
    const mien = (await cree(kamil)).data!
    const leur = (await cree(autre)).data!

    const deplace = await kamil.client.from('aliment').update({ household_id: autre.householdId }).eq('id', mien.id)
    expect(deplace.error?.message).toMatch(/row-level security/)

    // Rien n'est touché chez l'autre : la ligne est invisible, donc ni changée ni retirée.
    await kamil.client.from('aliment').update({ kcal_100g: 1 }).eq('id', leur.id)
    await kamil.client.from('aliment').delete().eq('id', leur.id)
    const { data: intact } = await db.from('aliment').select('kcal_100g').eq('id', leur.id).single()
    expect(Number(intact!.kcal_100g)).toBe(76)
  })

  it('l’anonyme ne voit rien', async () => {
    const { data } = await db.from('aliment').select('id').limit(1)
    expect(data!.length).toBeGreaterThan(0) // le service voit tout…
    const anon = (await import('@supabase/supabase-js')).createClient(
      process.env.VITE_SUPABASE_URL!, process.env.VITE_SUPABASE_ANON_KEY!, { auth: { persistSession: false } })
    const { data: rien } = await anon.from('aliment').select('id')
    expect(rien ?? []).toHaveLength(0) // … l'anonyme rien.
  })

  it('le foyer modifie et retire les siens', async () => {
    const a = (await cree(kamil)).data!
    const maj = await kamil.client.from('aliment').update({ kcal_100g: 80, unite_g: 150 }).eq('id', a.id).select().single()
    expect(maj.error).toBeNull()
    expect(Number(maj.data!.kcal_100g)).toBe(80)
    const del = await kamil.client.from('aliment').delete().eq('id', a.id).select()
    expect(del.error).toBeNull()
    expect(del.data).toHaveLength(1)
  })
})

describe('le déclencheur `updated_at`', () => {
  it('une modification avance `updated_at` ; une ligne relue sans changement ne bouge pas', async () => {
    const a = (await cree(kamil)).data!
    /* Un vrai délai : sans lui, `now()` de l'insertion et de la mise à jour pourraient tomber dans la même milliseconde. */
    await new Promise(r => setTimeout(r, 1100))
    const maj = await kamil.client.from('aliment').update({ unite_g: 130 }).eq('id', a.id).select().single()
    expect(maj.error).toBeNull()
    const avant = new Date(a.updated_at).getTime()
    const apres = new Date(maj.data!.updated_at).getTime()
    expect(apres - avant, 'updated_at doit avancer d’au moins le délai attendu').toBeGreaterThanOrEqual(1000)
    expect(maj.data!.created_at, 'created_at ne bouge jamais').toBe(a.created_at)
    const relu = await kamil.client.from('aliment').select('updated_at').eq('id', a.id).single()
    expect(relu.data!.updated_at).toBe(maj.data!.updated_at)
  })
})

describe('les bornes', () => {
  const refus = async (o: Record<string, unknown>, motif: RegExp) => {
    const { error } = await cree(kamil, o)
    expect(error?.message, JSON.stringify(o)).toMatch(motif)
    /* La vraie erreur de la base, passée par le vrai code de l'écran : une phrase française, jamais le nom d'un index. */
    const phrase = phraseDeLEcriture(error!.message)
    expect(phrase, JSON.stringify(o)).not.toMatch(/aliment_|violates|constraint|relation|row/i)
    expect(phrase, JSON.stringify(o)).not.toBe('L’enregistrement a échoué : réessaie dans un instant.')
  }

  it('un aliment complet entre, avec ses défauts (« pot », source « main »)', async () => {
    const { data, error } = await kamil.client.from('aliment')
      .insert({ household_id: kamil.householdId, label: nom('Skyr'), kcal_100g: 57, unite_g: 140 }).select().single()
    expect(error).toBeNull()
    expect(data!.unite).toBe('pot')
    expect(data!.source).toBe('main')
    expect(Number(data!.protein_100g)).toBe(0)
    expect(data!.code_barres).toBeNull()
  })

  it('les calories : ni négatives, ni au-delà de 900 pour 100 g (des kJ pris pour des kcal)', async () => {
    await refus({ kcal_100g: -1 }, /aliment_kcal_100g_check/)
    await refus({ kcal_100g: 901 }, /aliment_kcal_100g_check/)
    expect((await cree(kamil, { label: nom('Huile'), kcal_100g: 900, protein_100g: 0, carb_100g: 0, fat_100g: 100 })).error).toBeNull()
    expect((await cree(kamil, { label: nom('Eau'), kcal_100g: 0, protein_100g: 0, carb_100g: 0, fat_100g: 0 })).error).toBeNull()
  })

  it('les macros : ni négatives, ni au-delà de 100 g, ni plus de 105 g à elles trois', async () => {
    await refus({ protein_100g: -0.1 }, /aliment_protein_100g_check/)
    await refus({ carb_100g: 101 }, /aliment_carb_100g_check/)
    await refus({ fat_100g: 100.1 }, /aliment_fat_100g_check/)
    await refus({ fiber_100g: -1 }, /aliment_fiber_100g_check/)
    await refus({ protein_100g: 50, carb_100g: 50, fat_100g: 10 }, /aliment_macros_plausibles/)
  })

  it('l’unité pèse entre 1 g et 5 kg et porte un nom', async () => {
    await refus({ unite_g: 0 }, /aliment_unite_g_check/)
    await refus({ unite_g: -125 }, /aliment_unite_g_check/)
    await refus({ unite_g: 5001 }, /aliment_unite_g_check/)
    await refus({ unite: '   ' }, /aliment_unite_check/)
    await refus({ unite: 'x'.repeat(21) }, /aliment_unite_check/)
  })

  it('un nom fait de blancs seulement (espaces, tabulation, espace insécable) est refusé', async () => {
    await refus({ label: '\t' }, /aliment_label_check/)
    await refus({ label: '\u00a0\u00a0' }, /aliment_label_check/)
    await refus({ label: ' \t \u00a0 ' }, /aliment_label_check/)
  })

  it('le nom : ni vide, ni de plus de 80 caractères', async () => {
    await refus({ label: '   ' }, /aliment_label_check/)
    await refus({ label: 'x'.repeat(81) }, /aliment_label_check/)
  })

  it('la provenance : main, etiquette ou code_barres, rien d’autre', async () => {
    for (const source of ['main', 'etiquette', 'code_barres']) {
      expect((await cree(kamil, { label: nom('Source'), source })).error, source).toBeNull()
    }
    await refus({ source: 'devine' }, /aliment_source_check/)
  })

  it('le code-barres : 8, 12, 13 ou 14 chiffres, et rien d’autre', async () => {
    await refus({ code_barres: '12345' }, /aliment_code_barres_check/)
    for (const neuf of ['123456789', '1234567890', '12345678901']) await refus({ code_barres: neuf }, /aliment_code_barres_check/)
    await refus({ code_barres: '30334900047AB' }, /aliment_code_barres_check/)
    await refus({ code_barres: '123456789012345' }, /aliment_code_barres_check/)
    await refus({ code_barres: '3033 4900 04743' }, /aliment_code_barres_check/)
    /* Chaque longueur permise entre (quatre codes différents : le même GTIN écrit deux fois est un seul code, plus bas). */
    for (const bon of ['12345670', '123456789012', '3033490004743', '30334900047430']) {
      expect((await cree(kamil, { label: nom('Code'), code_barres: bon })).error, bon).toBeNull()
    }
  })

  it('`remplace_repere` : le nom d’un repère, ou rien — jamais une chaîne vide', async () => {
    const a = (await cree(kamil, { label: nom('Remplace'), remplace_repere: 'Yaourt' })).data!
    expect(a.remplace_repere).toBe('Yaourt')
    expect((await cree(kamil, { label: nom('Sans') })).data!.remplace_repere).toBeNull()
    await refus({ remplace_repere: '   ' }, /aliment_remplace_repere_check/)
    await refus({ remplace_repere: 'x'.repeat(81) }, /aliment_remplace_repere_check/)
  })

  it('un nom, une fois par foyer — sans tenir compte de la casse ni des espaces — mais libre chez un autre foyer', async () => {
    const base = nom('Fromage blanc')
    expect((await cree(kamil, { label: base })).error).toBeNull()
    const double = await cree(kamil, { label: `  ${base.toUpperCase()} ` })
    expect(double.error?.message).toMatch(/aliment_label_unique/)
    expect((await cree(autre, { label: base })).error, 'un autre foyer a le droit au même nom').toBeNull()
  })

  it('le nom se compare sans accents, avec des espaces unifiés (insécable et tabulation compris)', async () => {
    const stamp = `${Date.now()}-${++n}`
    expect((await cree(kamil, { label: `Crème brûlée ${stamp}` })).error).toBeNull()
    for (const variante of [
      `creme brulee ${stamp}`, `CRÈME BRÛLÉE ${stamp}`, `  Creme   brulee\t${stamp}  `, `Crème\u00a0brûlée ${stamp}`,
    ]) {
      const double = await cree(kamil, { label: variante })
      expect(double.error?.message, JSON.stringify(variante)).toMatch(/aliment_label_unique/)
      expect(phraseDeLEcriture(double.error!.message)).toMatch(/porte déjà ce nom/)
    }
    expect((await cree(kamil, { label: `Crème brûlée vanille ${stamp}` })).error, 'un autre nom reste permis').toBeNull()
    /* Modifier un nom vers celui d'un autre aliment est refusé de même. */
    const b = (await cree(kamil, { label: nom('Autre nom') })).data!
    const renomme = await kamil.client.from('aliment').update({ label: `CREME BRULEE ${stamp}` }).eq('id', b.id)
    expect(renomme.error?.message).toMatch(/aliment_label_unique/)
  })

  it('un code-barres, une fois par foyer ; plusieurs aliments sans code-barres', async () => {
    const code = String(4_000_000_000_000 + Math.floor(Math.random() * 999_999_999_999))
    expect((await cree(kamil, { label: nom('A'), code_barres: code })).error).toBeNull()
    expect((await cree(kamil, { label: nom('B'), code_barres: code })).error?.message).toMatch(/aliment_code_barres_unique/)
    expect((await cree(autre, { label: nom('C'), code_barres: code })).error).toBeNull()
    expect((await cree(kamil, { label: nom('D') })).error).toBeNull()
    expect((await cree(kamil, { label: nom('E') })).error).toBeNull()
  })

  it('le même code-barres écrit sur 13 et sur 14 chiffres (zéros à gauche) est UN code : GTIN-14', async () => {
    const treize = String(2_000_000_000_000 + Math.floor(Math.random() * 999_999_999_999))
    expect(treize).toHaveLength(13)
    expect((await cree(kamil, { label: nom('Treize'), code_barres: treize })).error).toBeNull()
    const quatorze = await cree(kamil, { label: nom('Quatorze'), code_barres: `0${treize}` })
    expect(quatorze.error?.message, '13 puis 14 chiffres').toMatch(/aliment_code_barres_unique/)
    /* Et dans l'autre sens, sur un code de huit chiffres (EAN-8) écrit sur quatorze. */
    const huit = String(10_000_000 + Math.floor(Math.random() * 89_999_999))
    expect((await cree(kamil, { label: nom('Huit'), code_barres: `000000${huit}` })).error).toBeNull()
    expect((await cree(kamil, { label: nom('Huit bis'), code_barres: huit })).error?.message).toMatch(/aliment_code_barres_unique/)
    /* Un autre foyer garde le droit au même code. */
    expect((await cree(autre, { label: nom('Autre foyer'), code_barres: treize })).error).toBeNull()
  })
})

describe('un geste : une unité, avec les vraies valeurs', () => {
  /* La base compare la date de l'appareil à la sienne (`choisir_un_repas`) : de vrais jours, pas des dates lointaines.
     Une case est unique par personne, jour et repas : chaque test vit un autre jour. */
  let decalage = 0
  const jourDans = (k: number) => new Date(Date.now() + (decalage + k) * 86_400_000).toISOString().slice(0, 10)
  const aujourdhui = () => new Date().toISOString().slice(0, 10)

  it('« un pot » du yaourt dessert protéiné vaut 95 kcal et 12,5 g, écrits par `choisir_un_repas`', async () => {
    decalage += 3
    const a = (await cree(kamil, { label: nom('Yaourt dessert protéiné') })).data!
    /* Le VRAI code de l'appli (`choixDeLUnite`), appelé sur la ligne que la base vient de rendre : le calcul n'est pas
       réécrit ici, il est lu là où l'écran le lit. */
    const unite = choixDeLUnite(a)
    expect(unite).toMatchObject({ type: 'repere', label: a.label, grams: 125, kcal: 95, protein_g: 12.5, carb_g: 7, fat_g: 1.8, fiber_g: 0 })

    const r = await kamil.client.rpc('choisir_un_repas', {
      p_day: jourDans(0), p_meal: 'collation', p_users: [kamil.userId], p_today: aujourdhui(),
      p_choix: unite,
    })
    expect(r.error).toBeNull()

    const { data: slot } = await db.from('meal_slot').select('id, state, portion_id')
      .eq('user_profile_id', kamil.userId).eq('day', jourDans(0)).eq('meal', 'collation').single()
    expect(slot!.state).toBe('prevu')
    expect(slot!.portion_id).toBeNull()
    const { data: extras } = await db.from('meal_extra').select('*').eq('meal_slot_id', slot!.id)
    expect(extras).toHaveLength(1)
    expect(extras![0]).toMatchObject({ label: a.label, household_id: kamil.householdId })
    expect(Number(extras![0].grams)).toBe(125)
    expect(Number(extras![0].kcal)).toBe(95)
    expect(Number(extras![0].protein_g)).toBe(12.5)
    expect(Number(extras![0].carb_g)).toBe(7)
    expect(Number(extras![0].fat_g)).toBe(1.8)
  })

  it('l’extra est une COPIE : corriger l’aliment ensuite ne réécrit pas le repas d’hier', async () => {
    decalage += 3
    const a = (await cree(kamil, { label: nom('Copie') })).data!
    const hier = choixDeLUnite(a)
    expect(hier.kcal).toBe(95)
    const r = await kamil.client.rpc('choisir_un_repas', {
      p_day: jourDans(0), p_meal: 'collation', p_users: [kamil.userId], p_today: aujourdhui(), p_choix: hier,
    })
    expect(r.error).toBeNull()

    const maj = await kamil.client.from('aliment').update({ kcal_100g: 200 }).eq('id', a.id).select().single()
    expect(maj.error).toBeNull()
    const demain = choixDeLUnite(maj.data!)
    expect(demain.kcal, 'l’aliment corrigé, lui, vaut bien autre chose').toBe(250)

    const { data: slot } = await db.from('meal_slot').select('id')
      .eq('user_profile_id', kamil.userId).eq('day', jourDans(0)).eq('meal', 'collation').single()
    const { data: extras } = await db.from('meal_extra').select('kcal, protein_g').eq('meal_slot_id', slot!.id)
    expect(extras).toHaveLength(1)
    expect(Number(extras![0].kcal), 'le repas noté garde ses 95 kcal').toBe(95)
    expect(Number(extras![0].protein_g)).toBe(12.5)
  })
})

describe('l’export RGPD', () => {
  it('emporte nos aliments, et seulement les nôtres', async () => {
    const mien = (await cree(kamil, { label: nom('Exporté') })).data!
    const leur = (await cree(autre, { label: nom('Pas à lui') })).data!
    const { data, error } = await kamil.client.rpc('export_my_data')
    expect(error).toBeNull()
    const ids = (data.aliments as { id: string }[]).map(x => x.id)
    expect(ids).toContain(mien.id)
    expect(ids).not.toContain(leur.id)
  })
})
