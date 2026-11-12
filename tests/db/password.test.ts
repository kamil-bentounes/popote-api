import { describe, it, expect, beforeAll } from 'vitest'
import { makeActor, admin, type Actor } from './helpers/db'

let alice: Actor
beforeAll(async () => { alice = await makeActor('alice-mdp') })

describe('mot de passe', () => {
  it('un profil neuf est marqué « sans mot de passe »', async () => {
    const { data } = await admin().from('user_profile')
      .select('password_set').eq('id', alice.userId).single()
    expect(data!.password_set, 'un compte créé par lien magique doit poser un mot de passe')
      .toBe(false)
  })

  it('la personne peut poser le sien, et pas celui d\'un autre', async () => {
    const { error } = await alice.client.from('user_profile')
      .update({ password_set: true }).eq('id', alice.userId)
    expect(error).toBeNull()

    const bob = await makeActor('bob-mdp')
    await alice.client.from('user_profile').update({ password_set: true }).eq('id', bob.userId)
    const { data } = await admin().from('user_profile')
      .select('password_set').eq('id', bob.userId).single()
    expect(data!.password_set, 'un membre a marqué le profil d’un autre').toBe(false)
  })
})
