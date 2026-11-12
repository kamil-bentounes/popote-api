/**
 * « Cette réponse est fausse » (0118) : ce que le foyer peut écrire, lire, et ce qu'il ne peut pas.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor, bob: Actor
beforeAll(async () => { alice = await makeActor('alice-aide'); bob = await makeActor('bob-aide') })

const signal = (a: Actor, o: Partial<Record<string, unknown>> = {}) => ({
  household_id: a.householdId, user_profile_id: a.userId,
  question: 'Comment inviter Thauba ?', reponse: 'Sur l’accueil, touche « Inviter quelqu’un ».',
  pages: ['foyer-inviter'], ...o,
})

describe('aide_signalement', () => {
  it('une personne signale une réponse, et son foyer la relit', async () => {
    const { error } = await alice.client.from('aide_signalement').insert(signal(alice))
    expect(error).toBeNull()
    const { data } = await alice.client.from('aide_signalement').select('question, pages')
    expect(data).toEqual([{ question: 'Comment inviter Thauba ?', pages: ['foyer-inviter'] }])
  })

  it('un autre foyer ne voit rien', async () => {
    const { data } = await bob.client.from('aide_signalement').select('*')
    expect(data ?? []).toHaveLength(0)
  })

  it('on ne signale pas au nom de quelqu’un d’autre, ni dans le foyer d’un autre', async () => {
    const aUnAutre = await alice.client.from('aide_signalement')
      .insert(signal(alice, { user_profile_id: bob.userId }))
    expect(aUnAutre.error, 'signalé au nom de Bob').not.toBeNull()
    const dansUnAutreFoyer = await alice.client.from('aide_signalement')
      .insert(signal(alice, { household_id: bob.householdId }))
    expect(dansUnAutreFoyer.error, 'écrit dans le foyer de Bob').not.toBeNull()
  })

  it('un signalement est un fait : ni modifié ni supprimé par le client', async () => {
    const { data: avant } = await alice.client.from('aide_signalement').select('id').limit(1)
    const id = avant![0].id
    await alice.client.from('aide_signalement').update({ question: 'autre' }).eq('id', id)
    await alice.client.from('aide_signalement').delete().eq('id', id)
    const { data } = await admin().from('aide_signalement').select('question').eq('id', id).single()
    expect(data?.question).toBe('Comment inviter Thauba ?')
  })

  it('refuse le vide et le roman', async () => {
    expect((await alice.client.from('aide_signalement').insert(signal(alice, { question: '' }))).error).not.toBeNull()
    expect((await alice.client.from('aide_signalement')
      .insert(signal(alice, { reponse: 'x'.repeat(2001) }))).error).not.toBeNull()
  })

  it('figure dans l’export RGPD', async () => {
    const { data } = await alice.client.rpc('export_my_data')
    expect(data.aide_signalements.length).toBeGreaterThanOrEqual(1)
    expect(data.aide_signalements.every((s: any) => s.household_id === alice.householdId)).toBe(true)
  })
})
