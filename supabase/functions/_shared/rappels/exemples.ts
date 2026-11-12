/**
 * Un mail d'EXEMPLE par type (« M'envoyer un exemple ») : des données inventées, plausibles, qui montrent le
 * mail tel qu'il arrive. Aucune ne vient de la base : on n'y lit rien du foyer, et rien ne s'écrit dans
 * `rappel_envoye`. Les liens pointent vers les vrais écrans ; sans barquette réelle, « C'est fait » mène au frigo
 * sans rien à sortir.
 */
import { illustration } from './liens.ts'
import { jourDeParis } from './texte.ts'
import type { TypeDeRappel } from './types.ts'

const jourPlus = (maintenant: Date, n: number) => jourDeParis(new Date(maintenant.getTime() + n * 86_400_000))

/** Le premier jour du mois de `maintenant`, décalé de `n` mois. */
function moisPlus(maintenant: Date, n: number): string {
  const [a, m] = jourDeParis(maintenant).split('-').map(Number)
  return new Date(Date.UTC(a, m - 1 + n, 1)).toISOString().slice(0, 10)
}

export function exemple(type: TypeDeRappel, maintenant: Date, prenom: string, base: string): Record<string, unknown> {
  switch (type) {
    case 'sortir_du_congelateur':
      return {
        jour: jourPlus(maintenant, 1),
        plats: [{
          label: 'Wraps poulet', recipe_id: null, image_url: null, n: 4, portion_ids: [], restant: 16,
          repas: [
            { meal: 'dejeuner', pour: [prenom, 'Léa'] },
            { meal: 'diner', pour: [prenom, 'Léa'] },
          ],
        }],
      }
    case 'barquette_perime':
      return {
        n: 2,
        plats: [
          {
            label: 'Lasagnes au saumon-poireaux', recipe_id: null,
            // La photo de l'exemple est servie par le site (`public/mail/lasagnes.png`) : jamais celle d'un autre site.
            image_url: illustration(base, 'lasagnes'), n: 1, portion_ids: [],
            expire: `${jourPlus(maintenant, 1)}T07:00:00Z`, tardives: [],
          },
          {
            // Demain soir : le plus tard qu'un vrai rappel annonce. Prévue après : le mail le dit.
            label: 'Pizza vietnamienne protéinée', recipe_id: null, image_url: null, n: 1, portion_ids: [],
            expire: `${jourPlus(maintenant, 1)}T19:30:00Z`, tardives: [jourPlus(maintenant, 3)],
          },
        ],
      }
    case 'choisir_les_repas': {
      const jours = Array.from({ length: 7 }, (_, i) => ({
        jour: jourPlus(maintenant, i + 1),
        midi: i === 0 ? 'congelateur' : i < 3 ? 'frigo' : 'vide',
        soir: i === 0 ? 'congelateur' : i === 2 ? 'autre' : 'vide',
      }))
      return { semaine: '', vides: 5, jours, congelateur: 2, frigo: 8 }
    }
    case 'noter_les_depenses':
      return { mois: moisPlus(maintenant, 0), semaine: '', depuis_jours: 7, lignes: 1 }
    case 'confirmer_les_charges':
      return {
        mois: moisPlus(maintenant, -1), n: 2,
        lignes: [
          { libelle: 'Électricité', montant_cents: 8_240 },
          { libelle: 'Internet', montant_cents: 3_700 },
        ],
      }
    case 'cloturer_le_mois':
      return { mois: moisPlus(maintenant, 0), lignes: 18, a_confirmer: 2 }
    case 'facture_annuelle':
      return {
        n: 2,
        charges: [
          {
            charge_id: '', libelle: 'Taxe foncière', annee: Number(jourDeParis(maintenant).slice(0, 4)),
            mois: moisPlus(maintenant, 1), derniere_paye_le: jourPlus(maintenant, -330), derniere_montant_cents: 142_000,
          },
          {
            charge_id: '', libelle: 'Assurance habitation', annee: Number(jourDeParis(maintenant).slice(0, 4)),
            mois: moisPlus(maintenant, 1), derniere_paye_le: jourPlus(maintenant, -335), derniere_montant_cents: 38_600,
          },
        ],
      }
  }
}
