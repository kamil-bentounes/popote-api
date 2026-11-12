# Popote — documentation

| Doc | Contenu |
|---|---|
| [`api.md`](api.md) | Surface d'API : tables, verbes autorisés, fonctions RPC, Edge Functions |
| [`cycle.md`](cycle.md) | Le cycle : les états, la séquence, ce que produit une session |
| [`schema.md`](schema.md) | Modèle de données et règles d'isolation |
| [`ingestion.md`](ingestion.md) | Remplir le catalogue de recettes |
| [`llm.md`](llm.md) | Quel modèle, où, ce qu'il voit, ce qu'il coûte |
| [`prix.md`](prix.md) | Le ticket de caisse, le rapprochement, les prix appris |
| [`suivi.md`](suivi.md) | Le tableau de bord : jours non renseignés, deux graphiques, budget |
| [`prompts.md`](prompts.md) | Les prompts, le schéma strict, la lecture de photo |
| [`mails.md`](mails.md) | Ce qui part par e-mail, et le réglage SMTP à faire |
| [`dev.md`](dev.md) | Lancer le projet en local |
| [`normes-api.md`](normes-api.md) | Les normes d'API : adresses, codes, erreurs, écritures sûres, limites, contrat (§ 3 de la spec du socle) |
| [`securite.md`](securite.md) | Connexion, sessions, rôles de base, photos, sécurité de l'API (§ 4, 5.1, 6, 7 de la spec du socle) |
| [`exploitation.md`](exploitation.md) | Opérations sur un projet hébergé : droits d'un projet neuf, migrations, sauvegardes, environnements, bascule |
| [`preuves-0.2.md`](preuves-0.2.md) | Les six preuves de l'étape 0.2 et leur état |
| [`inventaire-surface.md`](inventaire-surface.md) | Les appels que le front fait aujourd'hui à Supabase : la liste des routes de l'étape 0.5 |

## Référence

La [spec du socle](https://github.com/kamil-bentounes/popote-web/blob/main/docs/superpowers/specs/2026-11-12-socle-design.md) et le [plan de l'étape 0.2](https://github.com/kamil-bentounes/popote-web/blob/main/docs/superpowers/plans/2026-11-12-socle-0-2.md) sont dans `popote-web`, `docs/superpowers/`.
Les documents ci-dessus en sont découpés et renvoient à elle ; en cas d'écart, la spec fait foi.
Les conventions du front sont dans `popote-web/docs/conventions.md`.
